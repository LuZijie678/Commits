from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_stage3_alignment_calibration import run_stage3_alignment_calibration
from code.mica.training.checkpointing import load_checkpoint, validate_checkpoint_payload


def _write_spec(path: Path, *, approved: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "stage": "stage3_real_alignment_calibration",
                "advisor_stage3_approved": approved,
                "default_mode": "dry_run",
                "m_final_test_forbidden": True,
                "strict_replay_required": True,
                "freeze_base_encoder": True,
                "trainable_components": ["slot_decoder_adapter", "count_head", "existence_head", "thresholds"],
                "min_recommended_full_alignment_overall": 300,
                "min_recommended_final_test_aligned": 100,
                "min_recommended_double_annotated": 100,
            }
        ),
        encoding="utf-8",
    )


def _alignment_row(sample_id: str, *, annotator_id: str | None = None) -> dict:
    unit_id = f"{sample_id}_u1"
    row = {
        "sample_id": sample_id,
        "split": "train",
        "scope_status": "in_scope",
        "gold_count": 1,
        "edit_units": [{"unit_id": unit_id, "file_path": "src/auth.py", "patch_text": "+ guard"}],
        "gold_unit_to_intent": {unit_id: "I1"},
        "intents": [{"intent_id": "I1", "action": "fix", "object": "auth guard", "unit_ids": [unit_id]}],
        "background_units": [],
        "shared_support_units": [],
        "uncertain_units": [],
        "mixed_units": [],
    }
    if annotator_id is not None:
        row["annotator_id"] = annotator_id
    return row


def test_stage3_runner_rejects_training_without_advisor_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "alignment.jsonl"
    replay = tmp_path / "replay.json"
    _write_spec(spec, approved=False)
    write_jsonl(rows, [{"sample_id": "a1", "split": "train", "edit_units": [], "gold_count": 1, "gold_unit_to_intent": {}}])
    replay.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="advisor_stage3_approved=true"):
        run_stage3_alignment_calibration(
            stage3_spec_path=spec,
            alignment_jsonl=rows,
            strict_replay_manifest=replay,
            output_root=tmp_path / "out",
            train=True,
        )


def test_stage3_runner_forbids_m_final_test_input(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "alignment.jsonl"
    replay = tmp_path / "replay.json"
    forbidden = tmp_path / "m_final.jsonl"
    _write_spec(spec)
    write_jsonl(
        rows,
        [
            _alignment_row("a1", annotator_id="ann1"),
            _alignment_row("a1", annotator_id="ann2"),
        ],
    )
    replay.write_text("[]", encoding="utf-8")
    forbidden.write_text('{"sample_id":"mf1"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="M-final-test is forbidden"):
        run_stage3_alignment_calibration(
            stage3_spec_path=spec,
            alignment_jsonl=rows,
            strict_replay_manifest=replay,
            m_final_test_path=forbidden,
            output_root=tmp_path / "out_fail",
            dry_run=True,
        )

    result = run_stage3_alignment_calibration(
        stage3_spec_path=spec,
        alignment_jsonl=rows,
        strict_replay_manifest=replay,
        output_root=tmp_path / "out_ok",
        dry_run=True,
    )
    saved = read_json(tmp_path / "out_ok" / "stage3_alignment_calibration_manifest.json")
    alignment_report = read_json(tmp_path / "out_ok" / "stage3_alignment_calibration_report.json")
    asset_registry = read_json(tmp_path / "out_ok" / "stage3_runtime_asset_registry.json")
    asset_validation = read_json(tmp_path / "out_ok" / "stage3_asset_registry_validation.json")
    metrics_artifact = read_json(tmp_path / "out_ok" / "stage3_real_alignment_metrics_artifact.json")

    assert result["stage3_training_executed"] is False
    assert saved["m_final_test_used_for_calibration"] is False
    assert saved["freeze_base_encoder"] is True
    assert saved["real_alignment_metrics_status"] == "protocol_defined"
    assert saved["real_alignment_metrics_values_status"] == "values_to_be_populated_by_real_alignment_eval"
    assert asset_registry["registry_status"] == "runtime_paths_from_stage3_runner_args"
    assert asset_registry["assets"]["m_align_calib"]["path"] == str(rows)
    assert asset_registry["assets"]["strict_replay"]["path"] == str(replay)
    assert asset_validation["valid"] is True
    assert metrics_artifact["artifact_type"] == "stage3_real_alignment_metrics"
    assert metrics_artifact["status"] == "protocol_defined"
    assert metrics_artifact["values_status"] == "values_to_be_populated_by_real_alignment_eval"
    assert metrics_artifact["paper_readiness"] == "not_final_paper_ready_until_populated"
    assert metrics_artifact["metric_values_populated"] is False
    assert metrics_artifact["final_test_tuning"] == "forbidden"
    assert metrics_artifact["metrics"]["pairwise_f1"] is None
    assert alignment_report["table_name"] == "stage3_alignment_calibration"
    assert alignment_report["rows"][0]["status"] == "values_to_be_populated_by_real_alignment_eval"
    assert alignment_report["rows"][0]["paper_readiness"] == "not_final_paper_ready_until_populated"
    assert alignment_report["rows"][0]["final_test_tuning"] == "forbidden"


def test_stage3_runner_executes_guarded_train_path_when_approved(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "alignment.jsonl"
    replay = tmp_path / "replay.json"
    _write_spec(spec, approved=True)
    write_jsonl(rows, [_alignment_row("a1")])
    replay.write_text("[]", encoding="utf-8")

    result = run_stage3_alignment_calibration(
        stage3_spec_path=spec,
        alignment_jsonl=rows,
        strict_replay_manifest=replay,
        output_root=tmp_path / "out_runtime",
        train=True,
    )

    assert result["stage3_training_executed"] is True
    assert result["trainer_backend_executed"] is True
    assert result["trainer_backend_type"] == "MicaModelBackendAdapter"
    assert result["toy_backend_used"] is False
    assert result["epoch"]["gradient_step_count"] > 0
    assert result["checkpoint_written"] is True
    assert result["checkpoint_valid"] is True
    checkpoint = load_checkpoint(tmp_path / "out_runtime" / "checkpoints" / "stage3_epoch_1.ckpt.json")
    assert validate_checkpoint_payload(checkpoint)["valid"] is True
    assert checkpoint["stage"] == "stage3"
    assert checkpoint["backend_state"]["backend_type"] == "MicaModelBackendAdapter"
    assert "tensor weights require full model checkpoint implementation" in checkpoint["backend_state"]["note"]
