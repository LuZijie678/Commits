from __future__ import annotations

import json

import pytest

from code.mica.io_utils import write_jsonl
from code.mica.runners.run_stage3_alignment_calibration import run_stage3_alignment_calibration


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _spec(*, approved: bool = False) -> dict:
    return {
        "stage": "stage3_real_alignment_calibration",
        "advisor_stage3_approved": approved,
        "default_mode": "dry_run",
        "m_final_test_forbidden": True,
        "strict_replay_required": True,
        "freeze_base_encoder": True,
        "trainable_components": ["slot_decoder_adapter", "count_head", "existence_head", "thresholds"],
    }


def _alignment_row(sample_id: str) -> dict:
    unit_id = f"{sample_id}_u1"
    return {
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


def _strict_replay_row(sample_id: str) -> dict:
    unit_id = f"{sample_id}_u1"
    return {
        "sample_id": sample_id,
        "gold_count": 1,
        "edit_units": [{"unit_id": unit_id, "file_path": "tests/auth_test.py", "patch_text": "+ test"}],
        "gold_unit_to_intent": {unit_id: "I1"},
    }


def test_stage3_runner_execute_check_requires_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    rows = tmp_path / "align.jsonl"
    _write_json(spec, _spec(approved=False))
    replay.write_text("[]", encoding="utf-8")
    write_jsonl(rows, [_alignment_row("a1")])

    with pytest.raises(ValueError, match="advisor_stage3_approved=true"):
        run_stage3_alignment_calibration(
            stage3_spec_path=spec,
            alignment_jsonl=rows,
            strict_replay_manifest=replay,
            output_root=tmp_path / "out",
            train=True,
            implementation_check_only=True,
        )


def test_stage3_runner_implementation_check_only_executes_guarded_backend(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    rows = tmp_path / "align.jsonl"
    _write_json(spec, _spec(approved=True))
    _write_json(replay, [_strict_replay_row("replay")])
    write_jsonl(rows, [_alignment_row("a1")])

    result = run_stage3_alignment_calibration(
        stage3_spec_path=spec,
        alignment_jsonl=rows,
        strict_replay_manifest=replay,
        output_root=tmp_path / "out",
        train=True,
        implementation_check_only=True,
        advisor_approved=True,
    )

    assert result["training_executed"] is True
    assert result["implementation_check_only"] is True
    assert result["trainer_backend_executed"] is True
    assert result["trainer_backend_type"] == "MicaModelBackendAdapter"
    assert result["toy_backend_used"] is False
    assert result["epoch"]["step_count"] > 0
    assert result["metadata"]["experiment_manifest"]["runner_name"] == "run_stage3_alignment_calibration"
    assert result["metadata"]["experiment_manifest"]["stage"] == "stage3"


def test_stage3_runner_train_rejects_missing_edit_units(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    rows = tmp_path / "align.jsonl"
    _write_json(spec, _spec(approved=True))
    replay.write_text("[]", encoding="utf-8")
    invalid = _alignment_row("a1")
    invalid["edit_units"] = []
    write_jsonl(rows, [invalid])

    with pytest.raises(ValueError, match="missing_edit_units"):
        run_stage3_alignment_calibration(
            stage3_spec_path=spec,
            alignment_jsonl=rows,
            strict_replay_manifest=replay,
            output_root=tmp_path / "out",
            train=True,
            implementation_check_only=True,
            advisor_approved=True,
        )
