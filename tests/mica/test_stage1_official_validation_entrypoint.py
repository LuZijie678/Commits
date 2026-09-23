from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.models.mica_model import MicaModel
from code.mica.runners.run_stage1_official_validation import run_stage1_official_validation
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import build_model_checkpoint_payload, save_checkpoint


def _write_protocol_spec(path, *, approved: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "advisor_stage1_validation_approved": approved,
            }
        ),
        encoding="utf-8",
    )


def _prediction_row(*, include_release_decision: bool = True) -> dict:
    metadata: dict[str, object] = {}
    if include_release_decision:
        metadata["release_decision"] = "decompose"
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
        "metadata": metadata,
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


def test_stage1_official_validation_entrypoint_writes_dry_run_manifest(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec, approved=False)
    thresholds.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")
    manifest.write_text(json.dumps({"rows": [], "schedule_candidate": "naive_balanced_mixed_large_scale"}), encoding="utf-8")

    result = run_stage1_official_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    saved = read_json(tmp_path / "out" / "stage1_official_validation_manifest.json")
    assert result["official_validation_executed"] is False
    assert saved["execute_requested"] is False
    assert saved["thresholds_applied_to_pass_fail"] is False
    assert saved["metadata"]["experiment_manifest"]["runner_name"] == "run_stage1_official_validation"
    assert saved["metadata"]["experiment_manifest"]["stage"] == "stage1"


def test_stage1_official_validation_entrypoint_rejects_execute_without_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec, approved=False)
    thresholds.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")
    manifest.write_text(json.dumps({"rows": [], "schedule_candidate": "naive_balanced_mixed_large_scale"}), encoding="utf-8")

    with pytest.raises(ValueError, match="advisor approval"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            output_root=tmp_path / "out",
            execute=True,
        )


def test_stage1_official_validation_entrypoint_can_export_consumer_plans(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    prediction_jsonl = tmp_path / "predictions.jsonl"
    _write_protocol_spec(spec, approved=False)
    thresholds.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "rows": [{"sample_id": "s2", "gold_count": 1, "source_kind": "synthetic_k1"}],
                "schedule_candidate": "naive_balanced_mixed_large_scale",
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(prediction_jsonl, [_prediction_row()])

    result = run_stage1_official_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        prediction_jsonl=prediction_jsonl,
        output_root=tmp_path / "out",
        dry_run=True,
        export_consumer_plans_artifact=True,
        consumer_plan_review_ready=True,
    )

    export_summary = read_json(tmp_path / "out" / "stage1_official_validation_consumer_plan_export_summary.json")
    exported = read_jsonl(tmp_path / "out" / "stage1_official_validation_consumer_plans.jsonl")
    export_metadata = result["metadata"]["consumer_plan_export"]
    assert export_metadata["requested"] is True
    assert export_metadata["review_ready"] is True
    assert export_metadata["output_jsonl"] == "stage1_official_validation_consumer_plans.jsonl"
    assert export_metadata["error_jsonl"] == "stage1_official_validation_consumer_plan_export_errors.jsonl"
    assert export_metadata["summary_json"] == "stage1_official_validation_consumer_plan_export_summary.json"
    assert export_metadata["summary"]["review_ready_exported_count"] == 1
    assert export_summary["review_ready_exported_count"] == 1
    assert exported[0]["decision"] == "decompose"


def test_stage1_official_validation_entrypoint_rejects_review_ready_export_without_prediction_jsonl(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec, approved=False)
    thresholds.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")
    manifest.write_text(json.dumps({"rows": [], "schedule_candidate": "naive_balanced_mixed_large_scale"}), encoding="utf-8")

    with pytest.raises(ValueError, match="prediction_jsonl"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            output_root=tmp_path / "out",
            dry_run=True,
            export_consumer_plans_artifact=True,
            consumer_plan_review_ready=True,
        )


def _write_formal_asset_manifest(path: Path, *, rows: list[dict], split: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": path.stem,
                "split": split,
                "formal_ready": True,
                "summary": {
                    "record_count": len(rows),
                    "repo_count": len({row.get("repo") for row in rows}),
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def _write_formal_registry(
    path: Path,
    *,
    k1_dev: Path,
    k2_dev: Path,
    stage1_dev: Path | None = None,
    stage1_final_test: Path | None = None,
    stage1_checkpoint: Path | None = None,
) -> None:
    stage1_dev_payload = {
        "path": str(stage1_dev) if stage1_dev is not None else None,
        "status": "frozen" if stage1_dev is not None else "pending_generation",
        "schema_version": "mica-formal-asset-manifest-v1",
        "source_pool": "combined_stage1_dev_assets",
        "split": "dev",
        "record_count": 2 if stage1_dev is not None else None,
        "checksum": "placeholder" if stage1_dev is not None else None,
        "created_by": "unit_test",
        "leakage_group_key": "leakage_group",
        "required_for": ["stage1_validation"],
        "allowed_stages": ["stage1_validation"],
        "forbidden_stages": [],
        "eval_only": False,
    }
    stage1_final_test_payload = {
        "path": str(stage1_final_test) if stage1_final_test is not None else None,
        "status": "frozen" if stage1_final_test is not None else "pending_generation",
        "schema_version": "mica-formal-asset-manifest-v1",
        "source_pool": "combined_stage1_test_assets",
        "split": "test",
        "record_count": 2 if stage1_final_test is not None else None,
        "checksum": "placeholder" if stage1_final_test is not None else None,
        "created_by": "unit_test",
        "leakage_group_key": "leakage_group",
        "required_for": ["stage1_validation_execute"],
        "allowed_stages": ["stage1_validation_execute", "final_eval"],
        "forbidden_stages": ["stage1_threshold_selection", "stage1_candidate_validation", "tuning"],
        "eval_only": True,
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-data-asset-registry-v2",
                "registry_status": "formal_assets_populated",
                "assets": {
                    "step1_high_conf_single_dev": {
                        "path": str(k1_dev),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
                        "split": "dev",
                        "record_count": 1,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "allowed_stages": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                    "strict_synthetic_dev": {
                        "path": str(k2_dev),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl",
                        "split": "dev",
                        "record_count": 1,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "allowed_stages": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                    "stage1_official_validation_dev": stage1_dev_payload,
                    "stage1_official_final_test": stage1_final_test_payload,
                    "hard_b_test": {
                        "path": None,
                        "status": "missing",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage2_calibration", "tuning"],
                    },
                    "m_final_test": {
                        "path": None,
                        "status": "missing",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/m_verified/canonical/usable_m_with_real_diff.csv",
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"],
                    },
                    "real_domain_split_test": {
                        "path": None,
                        "status": "pending_generation",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": None,
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"],
                    },
                    "real_domain_selective_test": {
                        "path": None,
                        "status": "pending_generation",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": None,
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"],
                    },
                    "stage1_checkpoint_input": {
                        "path": str(stage1_checkpoint) if stage1_checkpoint is not None else None,
                        "status": "frozen" if stage1_checkpoint is not None else "pending_generation",
                        "schema_version": "mica-checkpoint-v2",
                        "source_pool": None,
                        "split": "n/a",
                        "record_count": None,
                        "checksum": "placeholder" if stage1_checkpoint is not None else None,
                        "created_by": "unit_test",
                        "leakage_group_key": "n/a",
                        "required_for": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                        "allowed_stages": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _write_full_checkpoint(path: Path, *, dirty: bool = False) -> None:
    backend = MicaModelBackendAdapter(
        MicaModel(
            text_vector_dim=TEXT_VECTOR_DIM,
            dense_feature_dim=len(DENSE_FEATURE_NAMES),
            hidden_dim=16,
            kmax=4,
            use_null_slot=True,
            use_pairwise_bias=True,
            assignment_temperature=0.7,
            count_pb_coupling_strength=0.0,
        )
    )
    payload = build_model_checkpoint_payload(
        stage="stage1",
        backend=backend,
        optimizer_state={"lr": 1e-3},
        scheduler_state={"step": 1},
        model_config={
            "text_vector_dim": TEXT_VECTOR_DIM,
            "dense_feature_dim": len(DENSE_FEATURE_NAMES),
            "hidden_dim": 16,
            "kmax": 4,
            "use_null_slot": True,
            "use_pairwise_bias": True,
            "assignment_temperature": 0.7,
            "count_pb_coupling_strength": 0.0,
        },
        training_state={"epoch": 1, "global_step": 1, "seed": 7},
        threshold_version="candidate_v1",
        data_manifest_hashes={"stage1_dev": "abc"},
        git_commit="deadbeef",
        git_provenance={"git_commit": "deadbeef", "dirty": dirty, "scope": "repo_filtered"},
        environment={"python_version": "3.11.0", "platform": "unit-test"},
    )
    save_checkpoint(path, payload)


def _write_stage0_readiness(path: Path, *, formal_ready: bool = True, kmax_frozen: bool = True, exact_multi_intent_rows: int = 2) -> None:
    path.write_text(
        json.dumps(
            {
                "formal_ready": formal_ready,
                "Kmax_protocol_frozen": kmax_frozen,
                "kmax_coverage_report": {
                    "train_dev_selection_basis": {
                        "exact_real_multi_intent_row_count": exact_multi_intent_rows,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_stage1_official_validation_execute_path_requires_all_formal_gates_and_sets_official_status(
    tmp_path,
) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    manifest = tmp_path / "manifest.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps({"threshold_status": "frozen_dev_thresholds_v1", "approved_threshold_version": "frozen_dev_thresholds_v1"}),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=True, kmax_frozen=True, exact_multi_intent_rows=2)
    _write_formal_asset_manifest(
        k1_dev,
        split="dev",
        rows=[
            {
                "sample_id": "k1_dev_1",
                "repo": "acme/repo-a",
                "source_sha": "a1",
                "split": "dev",
                "source_type": "step1_high_conf_single",
                "cardinality_label_type": "exact_k1_gold",
                "gold_provenance_status": "strict_unique_atomic",
                "leakage_group": "sha:a1",
                "construction_group": "atomic:a1",
                "gold_count": 1,
                "edit_units": [
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
                    }
                ],
                "gold_unit_to_intent": {"u1": "intent_0"},
                "gold_hunk_to_intent": {"h1": "intent_0"},
            }
        ],
    )
    _write_formal_asset_manifest(
        k2_dev,
        split="dev",
        rows=[
            {
                "sample_id": "k2_dev_1",
                "repo": "acme/repo-b",
                "source_sha": "b1",
                "split": "dev",
                "source_type": "strict_synthetic",
                "cardinality_label_type": "exact_k2_gold",
                "gold_provenance_status": "synthetic_construction_gold",
                "leakage_group": "sha:b1|c1",
                "construction_group": "synthetic:b1|c1",
                "gold_count": 2,
                "edit_units": [
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
                    },
                    {
                        "unit_id": "u2",
                        "hunk_id": "h2",
                        "file_path": "tests/auth_test.py",
                        "file_role": "test",
                        "language": "python",
                        "patch_text": "@@",
                        "added_lines": ["+ assert auth"],
                        "deleted_lines": [],
                        "changed_identifiers": ["auth"],
                    },
                ],
                "gold_unit_to_intent": {"u1": "intent_0", "u2": "intent_1"},
                "gold_hunk_to_intent": {"h1": "intent_0", "h2": "intent_1"},
            }
        ],
    )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "stage1_official_final_test",
                "split": "test",
                "formal_ready": True,
                "summary": {
                    "record_count": 2,
                    "repo_count": 2,
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": read_json(k1_dev)["rows"] + read_json(k2_dev)["rows"],
                "schedule_candidate": "naive_balanced_mixed_large_scale",
            }
        ),
        encoding="utf-8",
    )
    _write_full_checkpoint(checkpoint)
    _write_formal_registry(registry, k1_dev=k1_dev, k2_dev=k2_dev, stage1_dev=None, stage1_final_test=manifest, stage1_checkpoint=checkpoint)

    result = run_stage1_official_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        asset_registry_path=registry,
        checkpoint_path=checkpoint,
        stage0_readiness_path=stage0_readiness,
        output_root=tmp_path / "out",
        execute=True,
        advisor_approved=True,
    )

    saved = read_json(tmp_path / "out" / "stage1_official_validation_manifest.json")
    predictions = read_jsonl(tmp_path / "out" / "stage1_official_validation_predictions.jsonl")
    metrics = read_json(tmp_path / "out" / "stage1_official_validation_metrics.json")
    readiness = read_json(tmp_path / "out" / "stage1_official_validation_readiness.json")
    aggregate = read_json(tmp_path / "out" / "stage1_official_validation_aggregate_metrics.json")
    assert result["official_validation_executed"] is True
    assert result["completion_status"] == "executed_official"
    assert result["final_paper_ready"] is False
    assert result["paper_ready"] is False
    assert saved["official_validation_executed"] is True
    assert saved["thresholds_applied_to_pass_fail"] is True
    assert saved["checkpoint_valid"] is True
    assert saved["metadata"]["registry_schema_version"] == "mica-data-asset-registry-v2"
    assert saved["metadata"]["checkpoint_metadata"]["checkpoint_kind"] == "full_model_state"
    assert saved["metadata"]["input_asset_hashes"]["stage1_checkpoint_input"]
    assert saved["metadata"]["input_asset_hashes"]["stage1_official_final_test"]
    assert saved["metadata"]["output_paths"]["predictions"] == "stage1_official_validation_predictions.jsonl"
    assert saved["metadata"]["output_paths"]["metrics"] == "stage1_official_validation_metrics.json"
    assert saved["metadata"]["sample_counts"]["manifest_rows"] == 2
    assert saved["metadata"]["sample_counts"]["prediction_rows"] == 2
    assert saved["metadata"]["sample_counts"]["prediction_export_errors"] == 0
    assert saved["metadata"]["excluded_counts"]["excluded_manifest_rows"] == 0
    assert len(predictions) == 2
    assert metrics["prediction_metrics"]["sample_count"] == 2
    assert aggregate["official_validation_executed"] is True
    assert aggregate["paper_ready"] is False
    assert readiness["official_validation_executed"] is True
    assert readiness["completion_status"] == "executed_official"


def test_stage1_official_validation_execute_populates_unit_accuracy_gain_when_bound_is_requested(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    manifest = tmp_path / "manifest.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps(
            {
                "threshold_status": "frozen_dev_thresholds_v1",
                "approved_threshold_version": "frozen_dev_thresholds_v1",
                "unit_accuracy_gain_over_all_one_min": -1.0,
            }
        ),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=True, kmax_frozen=True, exact_multi_intent_rows=2)
    _write_formal_asset_manifest(
        k1_dev,
        split="dev",
        rows=[
            {
                "sample_id": "k1_dev_1",
                "repo": "acme/repo-a",
                "source_sha": "a1",
                "split": "dev",
                "source_type": "step1_high_conf_single",
                "cardinality_label_type": "exact_k1_gold",
                "gold_provenance_status": "strict_unique_atomic",
                "leakage_group": "sha:a1",
                "construction_group": "atomic:a1",
                "gold_count": 1,
                "edit_units": [
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
                    }
                ],
                "gold_unit_to_intent": {"u1": "intent_0"},
                "gold_hunk_to_intent": {"h1": "intent_0"},
            }
        ],
    )
    _write_formal_asset_manifest(
        k2_dev,
        split="dev",
        rows=[
            {
                "sample_id": "k2_dev_1",
                "repo": "acme/repo-b",
                "source_sha": "b1",
                "split": "dev",
                "source_type": "strict_synthetic",
                "cardinality_label_type": "exact_k2_gold",
                "gold_provenance_status": "synthetic_construction_gold",
                "leakage_group": "sha:b1|c1",
                "construction_group": "synthetic:b1|c1",
                "gold_count": 2,
                "edit_units": [
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
                    },
                    {
                        "unit_id": "u2",
                        "hunk_id": "h2",
                        "file_path": "tests/auth_test.py",
                        "file_role": "test",
                        "language": "python",
                        "patch_text": "@@",
                        "added_lines": ["+ assert auth"],
                        "deleted_lines": [],
                        "changed_identifiers": ["auth"],
                    },
                ],
                "gold_unit_to_intent": {"u1": "intent_0", "u2": "intent_1"},
                "gold_hunk_to_intent": {"h1": "intent_0", "h2": "intent_1"},
            }
        ],
    )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "stage1_official_final_test",
                "split": "test",
                "formal_ready": True,
                "summary": {
                    "record_count": 2,
                    "repo_count": 2,
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": read_json(k1_dev)["rows"] + read_json(k2_dev)["rows"],
            }
        ),
        encoding="utf-8",
    )
    _write_full_checkpoint(checkpoint)
    _write_formal_registry(registry, k1_dev=k1_dev, k2_dev=k2_dev, stage1_dev=None, stage1_final_test=manifest, stage1_checkpoint=checkpoint)

    run_stage1_official_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        asset_registry_path=registry,
        checkpoint_path=checkpoint,
        stage0_readiness_path=stage0_readiness,
        output_root=tmp_path / "out",
        execute=True,
        advisor_approved=True,
    )

    aggregate = read_json(tmp_path / "out" / "stage1_official_validation_aggregate_metrics.json")
    assert aggregate["official_gate_results"]["unit_accuracy_gain_over_all_one"]["observed"] is not None


def test_stage1_official_validation_execute_rejects_manifest_not_matching_registry_frozen_final_test_manifest(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    frozen_manifest = tmp_path / "frozen_stage1_final_test.json"
    mismatched_manifest = tmp_path / "mismatched_stage1_final_test.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps({"threshold_status": "frozen_dev_thresholds_v1", "approved_threshold_version": "frozen_dev_thresholds_v1"}),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=True, kmax_frozen=True, exact_multi_intent_rows=2)
    rows = [
        {
            "sample_id": "k1_dev_1",
            "repo": "acme/repo-a",
            "source_sha": "a1",
            "split": "test",
            "source_type": "step1_high_conf_single",
            "cardinality_label_type": "exact_k1_gold",
            "gold_provenance_status": "strict_unique_atomic",
            "leakage_group": "sha:a1",
            "construction_group": "atomic:a1",
            "gold_count": 1,
            "edit_units": [],
            "gold_unit_to_intent": {},
            "gold_hunk_to_intent": {},
        },
        {
            "sample_id": "k2_dev_1",
            "repo": "acme/repo-b",
            "source_sha": "b1",
            "split": "test",
            "source_type": "strict_synthetic",
            "cardinality_label_type": "exact_k2_gold",
            "gold_provenance_status": "synthetic_construction_gold",
            "leakage_group": "sha:b1|c1",
            "construction_group": "synthetic:b1|c1",
            "gold_count": 2,
            "edit_units": [],
            "gold_unit_to_intent": {},
            "gold_hunk_to_intent": {},
        },
    ]
    _write_formal_asset_manifest(k1_dev, split="dev", rows=[rows[0]])
    _write_formal_asset_manifest(k2_dev, split="dev", rows=[rows[1]])
    _write_formal_asset_manifest(frozen_manifest, split="test", rows=rows)
    _write_formal_asset_manifest(mismatched_manifest, split="test", rows=list(reversed(rows)))
    _write_full_checkpoint(checkpoint)
    _write_formal_registry(
        registry,
        k1_dev=k1_dev,
        k2_dev=k2_dev,
        stage1_dev=None,
        stage1_final_test=frozen_manifest,
        stage1_checkpoint=checkpoint,
    )

    with pytest.raises(ValueError, match="stage1_official_final_test"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=mismatched_manifest,
            asset_registry_path=registry,
            checkpoint_path=checkpoint,
            stage0_readiness_path=stage0_readiness,
            output_root=tmp_path / "out",
            execute=True,
            advisor_approved=True,
        )


def test_stage1_official_validation_execute_rejects_unregistered_checkpoint_even_if_path_is_supplied(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    manifest = tmp_path / "manifest.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps({"threshold_status": "frozen_dev_thresholds_v1", "approved_threshold_version": "frozen_dev_thresholds_v1"}),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=True, kmax_frozen=True, exact_multi_intent_rows=2)
    _write_formal_asset_manifest(k1_dev, split="dev", rows=[])
    _write_formal_asset_manifest(k2_dev, split="dev", rows=[])
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "stage1_official_final_test",
                "split": "test",
                "formal_ready": True,
                "summary": {
                    "record_count": 0,
                    "repo_count": 0,
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": [],
                "schedule_candidate": "naive_balanced_mixed_large_scale",
            }
        ),
        encoding="utf-8",
    )
    _write_full_checkpoint(checkpoint)
    _write_formal_registry(registry, k1_dev=k1_dev, k2_dev=k2_dev, stage1_dev=None, stage1_final_test=manifest, stage1_checkpoint=None)

    with pytest.raises(ValueError, match="stage1_checkpoint_input"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            asset_registry_path=registry,
            checkpoint_path=checkpoint,
            stage0_readiness_path=stage0_readiness,
            output_root=tmp_path / "out",
            execute=True,
            advisor_approved=True,
        )


def test_stage1_official_validation_execute_rejects_dirty_checkpoint_provenance(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    manifest = tmp_path / "manifest.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps({"threshold_status": "frozen_dev_thresholds_v1", "approved_threshold_version": "frozen_dev_thresholds_v1"}),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=True, kmax_frozen=True, exact_multi_intent_rows=2)
    _write_formal_asset_manifest(k1_dev, split="dev", rows=[])
    _write_formal_asset_manifest(k2_dev, split="dev", rows=[])
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "stage1_official_final_test",
                "split": "test",
                "formal_ready": True,
                "summary": {
                    "record_count": 0,
                    "repo_count": 0,
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": [],
                "schedule_candidate": "naive_balanced_mixed_large_scale",
            }
        ),
        encoding="utf-8",
    )
    _write_full_checkpoint(checkpoint, dirty=True)
    _write_formal_registry(registry, k1_dev=k1_dev, k2_dev=k2_dev, stage1_dev=None, stage1_final_test=manifest, stage1_checkpoint=checkpoint)

    with pytest.raises(ValueError, match="dirty_checkpoint_provenance"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            asset_registry_path=registry,
            checkpoint_path=checkpoint,
            stage0_readiness_path=stage0_readiness,
            output_root=tmp_path / "out",
            execute=True,
            advisor_approved=True,
        )


def test_stage1_official_validation_execute_rejects_when_stage0_gates_not_frozen(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    stage0_readiness = tmp_path / "stage0_readiness.json"
    manifest = tmp_path / "manifest.json"
    registry = tmp_path / "registry.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    _write_protocol_spec(spec, approved=True)
    thresholds.write_text(
        json.dumps({"threshold_status": "candidate_selected_pending_approval", "approved_threshold_version": None}),
        encoding="utf-8",
    )
    _write_stage0_readiness(stage0_readiness, formal_ready=False, kmax_frozen=False, exact_multi_intent_rows=0)
    _write_formal_asset_manifest(k1_dev, split="dev", rows=[])
    _write_formal_asset_manifest(k2_dev, split="dev", rows=[])
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "stage1_official_final_test",
                "split": "test",
                "formal_ready": True,
                "summary": {
                    "record_count": 0,
                    "repo_count": 0,
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": [],
                "schedule_candidate": "naive_balanced_mixed_large_scale",
            }
        ),
        encoding="utf-8",
    )
    _write_full_checkpoint(checkpoint)
    _write_formal_registry(registry, k1_dev=k1_dev, k2_dev=k2_dev, stage1_dev=None, stage1_final_test=manifest, stage1_checkpoint=checkpoint)

    with pytest.raises(ValueError, match="thresholds_pending_approval"):
        run_stage1_official_validation(
            protocol_spec_path=spec,
            metric_thresholds_path=thresholds,
            manifest_path=manifest,
            asset_registry_path=registry,
            checkpoint_path=checkpoint,
            stage0_readiness_path=stage0_readiness,
            output_root=tmp_path / "out",
            execute=True,
            advisor_approved=True,
        )
