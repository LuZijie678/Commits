from __future__ import annotations

import json
from pathlib import Path

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_official_stage1_validation import run_official_stage1_validation


def _write_protocol_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "stage": "stage1",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "schedule": {"epochs": 15},
            }
        ),
        encoding="utf-8",
    )


def _write_thresholds(path: Path) -> None:
    path.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")


def _write_manifest(path: Path) -> None:
    path.write_text(json.dumps({"schedule_candidate": "naive_balanced_mixed_large_scale", "stage2_allowed": False}), encoding="utf-8")


def _prediction_row() -> dict:
    return {
        "sample_id": "sample_1",
        "predicted_count": 1,
        "count_probs": {"1": 0.9},
        "active_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}}
        ],
        "all_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}}
        ],
        "unit_to_slot": {"u1": "slot_1"},
        "unit_assignment_scores": {"u1": {"slot_1": 0.9}},
        "source": "predicted_plan",
        "metadata": {},
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/auth.py", "hunk_id": "h1", "file_role": "source", "changed_identifiers": ["auth"], "added_lines": ["auth = 1"]}
        ],
    }


def test_plan_smoke_check_only_runs_with_explicit_flag(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)
    write_jsonl(prediction_jsonl, [_prediction_row()])

    result = run_official_stage1_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
        prediction_jsonl=prediction_jsonl,
        plan_smoke_check=False,
    )

    assert result["plan_smoke_check_executed"] is False
    assert not (tmp_path / "out" / "stage1_official_validation_plan_smoke.json").exists()


def test_plan_smoke_check_executes_without_official_validation(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)
    write_jsonl(prediction_jsonl, [_prediction_row()])

    result = run_official_stage1_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
        prediction_jsonl=prediction_jsonl,
        plan_smoke_check=True,
    )

    summary = read_json(tmp_path / "out" / "stage1_official_validation_plan_smoke.json")
    assert result["official_validation_executed"] is False
    assert result["training_executed"] is False
    assert result["plan_smoke_check_executed"] is True
    assert result["thresholds_applied_to_pass_fail"] is False
    assert summary["plans_built"] == 1
