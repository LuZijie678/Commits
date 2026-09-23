from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_stage1_official_validation_dryrun import main as dryrun_main
from code.mica.runners.run_stage1_official_validation_dryrun import run_stage1_official_validation_dryrun


def _write_protocol_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "repo_overlap_allowed_for_stage1_synthetic": True,
            }
        ),
        encoding="utf-8",
    )


def _write_thresholds(path: Path) -> None:
    path.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "splits": {
                    "train": [{"sample_id": "s1", "gold_count": 1, "source_kind": "atomic_k1", "repo": "r1", "sha": "a1"}],
                    "dev": [{"sample_id": "s2", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "r2", "sha": "a2", "synthetic_id": "syn2"}],
                    "test": [],
                }
            }
        ),
        encoding="utf-8",
    )


def _review_ready_prediction_row() -> dict[str, object]:
    return {
        "sample_id": "s2",
        "predicted_count": 1,
        "count_probs": {"1": 0.96},
        "active_slots": [
            {
                "slot_id": "slot_1",
                "existence_prob": 0.95,
                "edit_unit_ids": ["u1"],
                "hunk_ids": ["h1"],
                "confidence": 0.91,
                "assignment_scores": {"u1": 0.97},
                "diagnostics": {},
            }
        ],
        "all_slots": [
            {
                "slot_id": "slot_1",
                "existence_prob": 0.95,
                "edit_unit_ids": ["u1"],
                "hunk_ids": ["h1"],
                "confidence": 0.91,
                "assignment_scores": {"u1": 0.97},
                "diagnostics": {},
            }
        ],
        "unit_to_slot": {"u1": "slot_1"},
        "unit_assignment_scores": {"u1": {"slot_1": 0.97}},
        "metadata": {"release_decision": "decompose"},
        "unit_records": [
            {
                "unit_id": "u1",
                "hunk_id": "h1",
                "file_path": "src/auth.py",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ auth = 1"],
                "deleted_lines": [],
                "changed_identifiers": ["auth"],
                "metadata": {"enclosing_symbol_name": "auth"},
            }
        ],
    }


def test_runner_requires_dry_run_flag(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    with pytest.raises(ValueError):
        dryrun_main(
            [
                "--protocol-spec",
                str(spec),
                "--metric-thresholds",
                str(thresholds),
                "--manifest",
                str(manifest),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_runner_writes_manifest_and_does_not_apply_thresholds(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    result = run_stage1_official_validation_dryrun(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    saved = read_json(tmp_path / "out" / "stage1_validation_dryrun_manifest.json")
    assert result["official_validation_executed"] is False
    assert result["training_executed"] is False
    assert result["thresholds_applied_to_pass_fail"] is False
    assert saved["stage2_allowed"] is False


def test_runner_can_emit_metric_dryrun_summary_when_predictions_provided(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    edit_units_jsonl = tmp_path / "edit_units.jsonl"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)
    write_jsonl(
        prediction_jsonl,
        [
            {
                "sample_id": "s2",
                "predicted_count": 2,
                "active_slots": [{"slot_id": "slot_1"}, {"slot_id": "slot_2"}],
                "unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
            }
        ],
    )
    write_jsonl(
        edit_units_jsonl,
        [
            {
                "sample_id": "s2",
                "edit_units": [
                    {"unit_id": "u1", "gold_intent_id": "i1"},
                    {"unit_id": "u2", "gold_intent_id": "i2"},
                ],
            }
        ],
    )

    result = run_stage1_official_validation_dryrun(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        prediction_jsonl=prediction_jsonl,
        edit_units_jsonl=edit_units_jsonl,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    metric_summary = read_json(tmp_path / "out" / "stage1_metric_dryrun_summary.json")
    assert result["official_validation_executed"] is False
    assert metric_summary["metric_dryrun_executed"] is True


def test_runner_can_export_consumer_plans_when_predictions_provided(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)
    write_jsonl(prediction_jsonl, [_review_ready_prediction_row()])

    result = run_stage1_official_validation_dryrun(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        prediction_jsonl=prediction_jsonl,
        output_root=tmp_path / "out",
        dry_run=True,
        export_consumer_plans_artifact=True,
        consumer_plan_review_ready=True,
    )

    export_summary = read_json(tmp_path / "out" / "stage1_official_validation_dryrun_consumer_plan_export_summary.json")
    exported = read_jsonl(tmp_path / "out" / "stage1_official_validation_dryrun_consumer_plans.jsonl")
    export_metadata = result["metadata"]["consumer_plan_export"]
    assert export_metadata["requested"] is True
    assert export_metadata["review_ready"] is True
    assert export_metadata["output_jsonl"] == "stage1_official_validation_dryrun_consumer_plans.jsonl"
    assert export_metadata["error_jsonl"] == "stage1_official_validation_dryrun_consumer_plan_export_errors.jsonl"
    assert export_metadata["summary_json"] == "stage1_official_validation_dryrun_consumer_plan_export_summary.json"
    assert export_summary["review_ready_exported_count"] == 1
    assert exported[0]["decision"] == "decompose"


def test_runner_rejects_consumer_plan_export_without_prediction_jsonl(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    with pytest.raises(ValueError, match="prediction_jsonl"):
        run_stage1_official_validation_dryrun(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            output_root=tmp_path / "out",
            dry_run=True,
            export_consumer_plans_artifact=True,
            consumer_plan_review_ready=True,
        )
