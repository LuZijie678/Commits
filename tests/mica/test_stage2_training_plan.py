from __future__ import annotations

from code.mica.stages.stage2_real_calibration import (
    build_stage2_freeze_plan,
    build_stage2_lr_plan,
    build_stage2_training_plan,
    validate_stage2_training_plan,
)


def _spec() -> dict:
    return {
        "stage": "stage2_real_domain_count_calibration",
        "advisor_stage2_approved": False,
        "loss_weights": {"lambda_replay": 0.5, "lambda_hard": 0.5, "lambda_M": 0.5, "lambda_real": 0.0, "lambda_cons": 0.0},
        "freeze_strategy": {
            "first_half": {"freeze_lower_encoder": True, "train_heads": True, "renderer_lr": 0.0},
            "second_half": {"unfreeze_top_encoder_layers": True, "encoder_lr_multiplier": 0.1, "renderer_lr": 0.0},
        },
    }


def test_stage2_training_plan_includes_mixture_and_disabled_renderer() -> None:
    plan = build_stage2_training_plan(_spec(), {"dataset_roles": {"strict_replay": {}, "hard_b": {}, "m_weak": {}}})

    assert plan.stage == "stage2_real_domain_count_calibration"
    assert plan.loss_weights["lambda_cons"] == 0.0
    assert plan.metadata["renderer_disabled"] is True
    assert plan.metadata["generation_loss_disabled"] is True


def test_stage2_freeze_and_lr_plans_cover_two_phases() -> None:
    freeze_first = build_stage2_freeze_plan(_spec(), phase="first_half")
    freeze_second = build_stage2_freeze_plan(_spec(), phase="second_half")
    lr_plan = build_stage2_lr_plan(_spec(), base_lr=1e-3)

    assert "encoder.lower" in freeze_first.frozen_components
    assert "encoder.top" not in freeze_second.trainable_components
    assert "assignment_decoder" in freeze_second.frozen_components
    assert "count_head" in freeze_second.trainable_components
    assert "selective_risk_calibration" in freeze_second.trainable_components
    assert lr_plan.component_lrs["renderer"] == 0.0
    assert lr_plan.component_lrs["encoder"] == 1e-4


def test_stage2_training_plan_validation_blocks_unapproved_train() -> None:
    plan = build_stage2_training_plan(_spec(), {"dataset_roles": {}})
    validation = validate_stage2_training_plan(plan)

    assert validation["valid"] is True
    assert validation["approved"] is False
