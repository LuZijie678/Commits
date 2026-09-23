from __future__ import annotations

from code.mica.io_utils import read_jsonl, write_jsonl
from code.mica.training.trainer_types import TrainBatch, TrainOutputs


def _train_batch() -> TrainBatch:
    return TrainBatch(
        sample_ids=["sample_backend"],
        source_kind="strict_replay",
        edit_units=[
            {
                "unit_id": "u_src",
                "hunk_id": "h_u_src",
                "file_path": "src/auth/token.py",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ validate_token(token)"],
                "deleted_lines": ["- token"],
                "changed_identifiers": ["token", "validate_token"],
                "gold_intent_id": "intent_secret",
                "metadata": {"enclosing_symbol_name": "validate_token"},
            },
            {
                "unit_id": "u_lock",
                "hunk_id": "h_u_lock",
                "file_path": "package-lock.json",
                "file_role": "lockfile",
                "language": "json",
                "patch_text": "@@",
                "added_lines": ["+ lockfile"],
                "deleted_lines": [],
                "changed_identifiers": ["lockfile"],
                "gold_intent_id": "intent_secret_background",
                "metadata": {},
            },
        ],
        metadata={
            "commit_id": "commit_backend",
            "commit_message": "forbidden commit message",
            "background_units": ["u_lock"],
        },
    )


def _train_outputs(*, include_release_decision: bool = True) -> TrainOutputs:
    diagnostics = {"selective_risk_score": 0.17}
    if include_release_decision:
        diagnostics["release_decision"] = "decompose"
    return TrainOutputs(
        count_logits=None,
        count_probs=[0.93, 0.07],
        pb_count_probs=[0.89, 0.11],
        slot_exist_probs=[0.95, 0.15],
        assignments={"u_src": "slot_1", "u_lock": "slot_null"},
        assignment_scores={
            "u_src": {"slot_1": 0.96, "slot_null": 0.01},
            "u_lock": {"slot_null": 0.99, "slot_1": 0.01},
        },
        slot_representations={},
        diagnostics=diagnostics,
        predicted_count=1,
        active_slot_indices=[0],
    )


def test_build_prediction_row_from_backend_strips_forbidden_fields_and_derives_slots() -> None:
    from code.mica.runners.export_stage1_predictions import (
        build_backend_snapshot_row,
        build_prediction_row_from_backend,
        validate_backend_snapshot_contract,
    )

    snapshot = build_backend_snapshot_row(
        batch=_train_batch(),
        outputs=_train_outputs(),
    )
    contract = validate_backend_snapshot_contract(snapshot)

    row = build_prediction_row_from_backend(
        batch=_train_batch(),
        outputs=_train_outputs(),
    )

    assert contract["valid"] is True
    assert snapshot["train_batch"]["metadata"]["commit_id"] == "commit_backend"
    assert "commit_message" not in snapshot["train_batch"]["metadata"]
    assert snapshot["train_batch"]["edit_units"][0].get("gold_intent_id") is None
    assert row["sample_id"] == "sample_backend"
    assert row["predicted_count"] == 1
    assert row["count_probs"] == {"1": 0.93, "2": 0.07}
    assert [slot["slot_id"] for slot in row["active_slots"]] == ["slot_1"]
    assert [slot["slot_id"] for slot in row["all_slots"]] == ["slot_1", "slot_2"]
    assert row["metadata"]["release_decision"] == "decompose"
    assert row["metadata"]["risk_score"] == 0.17
    assert row["metadata"]["commit_id"] == "commit_backend"
    assert row["metadata"]["background_units"] == ["u_lock"]
    assert row["metadata"]["background_unit_records"][0]["background_reason"] == "lockfile"
    assert row["unit_records"][0].get("gold_intent_id") is None
    assert "commit_message" not in row["metadata"]


def test_validate_backend_snapshot_contract_requires_single_sample_and_release_decision() -> None:
    from code.mica.runners.export_stage1_predictions import validate_backend_snapshot_contract

    snapshot = {
        "train_batch": {
            "sample_ids": ["sample_a", "sample_b"],
            "source_kind": "strict_replay",
            "edit_units": _train_batch().edit_units,
            "metadata": {"commit_id": "commit_backend"},
        },
        "train_outputs": {
            "count_probs": [0.93, 0.07],
            "slot_exist_probs": [0.95, 0.15],
            "assignments": {"u_src": "slot_1"},
            "assignment_scores": {"u_src": {"slot_1": 0.96}},
            "diagnostics": {},
        },
    }

    contract = validate_backend_snapshot_contract(snapshot)

    assert contract["valid"] is False
    assert "multi_sample_snapshot_not_exportable" in contract["errors"]
    assert "missing_release_decision" in contract["errors"]


def test_export_stage1_predictions_writes_rows_and_structured_errors(tmp_path) -> None:
    from code.mica.runners.export_stage1_predictions import export_stage1_predictions

    snapshot_jsonl = tmp_path / "backend_snapshots.jsonl"
    output_jsonl = tmp_path / "predictions.jsonl"
    error_jsonl = tmp_path / "prediction_errors.jsonl"
    write_jsonl(
        snapshot_jsonl,
        [
            {
                "train_batch": {
                    "sample_ids": ["sample_backend"],
                    "source_kind": "strict_replay",
                    "edit_units": _train_batch().edit_units,
                    "metadata": _train_batch().metadata,
                },
                "train_outputs": {
                    "count_probs": [0.93, 0.07],
                    "pb_count_probs": [0.89, 0.11],
                    "slot_exist_probs": [0.95, 0.15],
                    "assignments": {"u_src": "slot_1", "u_lock": "slot_null"},
                    "assignment_scores": {
                        "u_src": {"slot_1": 0.96, "slot_null": 0.01},
                        "u_lock": {"slot_null": 0.99, "slot_1": 0.01},
                    },
                    "diagnostics": {"release_decision": "decompose", "selective_risk_score": 0.17},
                    "predicted_count": 1,
                    "active_slot_indices": [0],
                },
            },
            {
                "train_batch": {
                    "sample_ids": ["sample_missing_decision"],
                    "source_kind": "strict_replay",
                    "edit_units": _train_batch().edit_units,
                    "metadata": {"commit_id": "commit_missing"},
                },
                "train_outputs": {
                    "count_probs": [0.93, 0.07],
                    "slot_exist_probs": [0.95, 0.15],
                    "assignments": {"u_src": "slot_1"},
                    "assignment_scores": {"u_src": {"slot_1": 0.96}},
                    "diagnostics": {"selective_risk_score": 0.17},
                    "predicted_count": 1,
                    "active_slot_indices": [0],
                },
            },
        ],
    )

    summary = export_stage1_predictions(
        backend_snapshot_jsonl=snapshot_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        strict=False,
    )

    exported = read_jsonl(output_jsonl)
    errors = read_jsonl(error_jsonl)
    assert summary["sample_counts"]["exported"] == 1
    assert summary["sample_counts"]["errors"] == 1
    assert summary["source_kind_distribution"] == {"strict_replay": 1}
    assert summary["release_decision_distribution"] == {"decompose": 1}
    assert summary["error_type_counts"] == {"schema_validation_error": 1}
    assert summary["exported_samples_preview"] == ["sample_backend"]
    assert exported[0]["metadata"]["release_decision"] == "decompose"
    assert exported[0]["source"] == "mica_model_backend_export"
    assert errors[0]["error_type"] == "schema_validation_error"
    assert "missing_release_decision" in errors[0]["message"]


def test_export_stage1_predictions_rejects_multi_sample_snapshots_with_structured_error(tmp_path) -> None:
    from code.mica.runners.export_stage1_predictions import export_stage1_predictions

    snapshot_jsonl = tmp_path / "backend_snapshots.jsonl"
    output_jsonl = tmp_path / "predictions.jsonl"
    error_jsonl = tmp_path / "prediction_errors.jsonl"
    batch = _train_batch()
    batch_payload = {
        "sample_ids": ["sample_backend", "sample_extra"],
        "source_kind": batch.source_kind,
        "edit_units": batch.edit_units,
        "metadata": {"commit_id": "commit_backend", "release_decision": "decompose"},
    }
    outputs = _train_outputs()
    write_jsonl(
        snapshot_jsonl,
        [
            {
                "train_batch": batch_payload,
                "train_outputs": {
                    "count_probs": outputs.count_probs,
                    "slot_exist_probs": outputs.slot_exist_probs,
                    "assignments": outputs.assignments,
                    "assignment_scores": outputs.assignment_scores,
                    "diagnostics": outputs.diagnostics,
                    "predicted_count": outputs.predicted_count,
                    "active_slot_indices": outputs.active_slot_indices,
                },
            }
        ],
    )

    summary = export_stage1_predictions(
        backend_snapshot_jsonl=snapshot_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        strict=False,
    )

    assert summary["sample_counts"]["exported"] == 0
    assert summary["sample_counts"]["errors"] == 1
    assert summary["error_type_counts"] == {"schema_validation_error": 1}
    assert read_jsonl(output_jsonl) == []
    errors = read_jsonl(error_jsonl)
    assert "multi_sample_snapshot_not_exportable" in errors[0]["message"]


def test_export_stage1_predictions_validate_only_writes_no_outputs(tmp_path) -> None:
    from code.mica.runners.export_stage1_predictions import export_stage1_predictions

    snapshot_jsonl = tmp_path / "backend_snapshots.jsonl"
    output_jsonl = tmp_path / "predictions.jsonl"
    error_jsonl = tmp_path / "prediction_errors.jsonl"
    write_jsonl(
        snapshot_jsonl,
        [
            {
                "train_batch": {
                    "sample_ids": ["sample_backend"],
                    "source_kind": "strict_replay",
                    "edit_units": _train_batch().edit_units,
                    "metadata": _train_batch().metadata,
                },
                "train_outputs": {
                    "count_probs": [0.93, 0.07],
                    "slot_exist_probs": [0.95, 0.15],
                    "assignments": {"u_src": "slot_1"},
                    "assignment_scores": {"u_src": {"slot_1": 0.96}},
                    "diagnostics": {"release_decision": "decompose", "selective_risk_score": 0.17},
                    "predicted_count": 1,
                    "active_slot_indices": [0],
                },
            }
        ],
    )

    summary = export_stage1_predictions(
        backend_snapshot_jsonl=snapshot_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        validate_only=True,
    )

    assert summary["validate_only"] is True
    assert output_jsonl.exists() is False
    assert error_jsonl.exists() is False
