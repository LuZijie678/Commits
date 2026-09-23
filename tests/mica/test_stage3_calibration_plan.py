from __future__ import annotations

from code.mica.stages.stage3_real_alignment_calibration import build_stage3_calibration_plan, build_stage3_freeze_plan


def _spec() -> dict:
    return {
        "stage": "stage3_real_alignment_calibration",
        "advisor_stage3_approved": False,
        "freeze_base_encoder": True,
        "strict_replay_required": True,
        "trainable_components": ["slot_decoder_adapter", "count_head", "existence_head", "thresholds"],
    }


def test_stage3_plan_keeps_base_encoder_frozen_and_requires_replay() -> None:
    plan = build_stage3_calibration_plan(_spec(), {"row_count": 10})
    freeze = build_stage3_freeze_plan(_spec())

    assert plan.metadata["strict_replay_required"] is True
    assert "base_encoder" in freeze.frozen_components
    assert "slot_decoder_adapter" not in freeze.trainable_components
    assert freeze.trainable_components == ["count_temperature", "existence_temperature"]
    assert freeze.metadata["stage3_core_default"] is True


def test_stage3_plus_freeze_plan_enables_only_low_rank_assignment_adapter() -> None:
    spec = {**_spec(), "stage3_plus": {"enabled": True, "lambda_drift": 0.1}}
    plan = build_stage3_calibration_plan(spec, {"row_count": 10})
    freeze = build_stage3_freeze_plan(spec)

    assert plan.metadata["stage3_plus_enabled"] is True
    assert "low_rank_assignment_adapter" in freeze.trainable_components
    assert "slot_decoder_adapter" not in freeze.trainable_components
    assert "base_assignment_scorer" in freeze.frozen_components
