from __future__ import annotations

import json

import pytest

from code.mica.runners.run_stage2_calibration import run_stage2_calibration


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _spec(*, approved: bool = False) -> dict:
    return {
        "stage": "stage2_real_domain_count_calibration",
        "advisor_stage2_approved": approved,
        "strict_replay_required": True,
        "hard_b_test_forbidden": True,
        "m_final_test_forbidden": True,
        "real_domain_split_test_forbidden": True,
        "real_domain_selective_test_forbidden": True,
        "m_weak_label_semantics": "censored_k_ge_2",
        "mixture_weights": {"strict_replay": 0.55, "hard_b": 0.3, "m_weak": 0.15},
        "loss_weights": {"lambda_replay": 0.5, "lambda_hard": 0.5, "lambda_M": 0.5, "lambda_real": 0.0, "lambda_cons": 0.0},
        "freeze_strategy": {
            "first_half": {"freeze_lower_encoder": True, "train_heads": True, "renderer_lr": 0.0},
            "second_half": {"unfreeze_top_encoder_layers": True, "encoder_lr_multiplier": 0.1, "renderer_lr": 0.0},
        },
        "consistency": {"enabled": False},
    }


def _strict_replay_row(sample_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "gold_count": 1,
        "edit_units": [{"unit_id": f"{sample_id}_u1", "file_path": "src/auth.py", "patch_text": "+ guard"}],
        "gold_unit_to_intent": {f"{sample_id}_u1": "i1"},
    }


def _hard_b_row(sample_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "edit_units": [{"unit_id": f"{sample_id}_u1", "file_path": "src/auth.py", "patch_text": "+ guard"}],
    }


def _m_weak_row(sample_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "edit_units": [{"unit_id": f"{sample_id}_u1", "file_path": "src/cache.py", "patch_text": "+ cache"}],
    }


def test_stage2_runner_rejects_train_without_approval_even_with_implementation_check(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    _write_json(spec, _spec(approved=False))
    for name in ("replay", "hb_train", "hb_dev", "m_train", "m_dev"):
        _write_json(tmp_path / f"{name}.json", [{"sample_id": name}])

    with pytest.raises(ValueError, match="advisor_stage2_approved=true"):
        run_stage2_calibration(
            stage2_spec_path=spec,
            strict_replay_manifest=tmp_path / "replay.json",
            hard_b_train_path=tmp_path / "hb_train.json",
            hard_b_dev_path=tmp_path / "hb_dev.json",
            m_weak_train_path=tmp_path / "m_train.json",
            m_weak_dev_path=tmp_path / "m_dev.json",
            output_root=tmp_path / "out",
            train=True,
            implementation_check_only=True,
        )


def test_stage2_runner_train_implementation_check_executes_guarded_backend(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    _write_json(spec, _spec(approved=True))
    _write_json(tmp_path / "replay.json", [_strict_replay_row("replay")])
    _write_json(tmp_path / "hb_train.json", [_hard_b_row("hb_train")])
    _write_json(tmp_path / "hb_dev.json", [_hard_b_row("hb_dev")])
    _write_json(tmp_path / "m_train.json", [_m_weak_row("m_train")])
    _write_json(tmp_path / "m_dev.json", [_m_weak_row("m_dev")])

    result = run_stage2_calibration(
        stage2_spec_path=spec,
        strict_replay_manifest=tmp_path / "replay.json",
        hard_b_train_path=tmp_path / "hb_train.json",
        hard_b_dev_path=tmp_path / "hb_dev.json",
        m_weak_train_path=tmp_path / "m_train.json",
        m_weak_dev_path=tmp_path / "m_dev.json",
        output_root=tmp_path / "out",
        train=True,
        implementation_check_only=True,
        advisor_approved=True,
    )

    assert result["training_executed"] is True
    assert result["implementation_check_only"] is True
    assert result["trainer_backend_executed"] is True
    assert result["epoch"]["step_count"] > 0
    assert result["metadata"]["experiment_manifest"]["runner_name"] == "run_stage2_calibration"
    assert result["metadata"]["experiment_manifest"]["stage"] == "stage2"


def test_stage2_runner_train_rejects_missing_edit_units(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    _write_json(spec, _spec(approved=True))
    _write_json(tmp_path / "replay.json", [{"sample_id": "replay", "gold_count": 1, "gold_unit_to_intent": {"u1": "i1"}}])
    _write_json(tmp_path / "hb_train.json", [_hard_b_row("hb_train")])
    _write_json(tmp_path / "hb_dev.json", [_hard_b_row("hb_dev")])
    _write_json(tmp_path / "m_train.json", [_m_weak_row("m_train")])
    _write_json(tmp_path / "m_dev.json", [_m_weak_row("m_dev")])

    with pytest.raises(ValueError, match="missing_edit_units"):
        run_stage2_calibration(
            stage2_spec_path=spec,
            strict_replay_manifest=tmp_path / "replay.json",
            hard_b_train_path=tmp_path / "hb_train.json",
            hard_b_dev_path=tmp_path / "hb_dev.json",
            m_weak_train_path=tmp_path / "m_train.json",
            m_weak_dev_path=tmp_path / "m_dev.json",
            output_root=tmp_path / "out",
            train=True,
            implementation_check_only=True,
            advisor_approved=True,
        )
