from __future__ import annotations

import torch

from code.mica.losses.consistency_losses import high_confidence_consistency_loss, should_enable_consistency


def test_consistency_is_disabled_by_default() -> None:
    spec = {"consistency": {"enabled": False, "enable_after_fraction": 0.3}}

    assert should_enable_consistency(40, 100, spec, teacher_confidence=0.95, assignment_entropy=0.1, stable_under_aug=True) is False


def test_consistency_requires_warmup_confidence_entropy_and_stability() -> None:
    spec = {
        "consistency": {
            "enabled": True,
            "enable_after_fraction": 0.3,
            "min_teacher_confidence": 0.8,
            "max_assignment_entropy": 0.5,
        }
    }

    assert should_enable_consistency(40, 100, spec, teacher_confidence=0.9, assignment_entropy=0.2, stable_under_aug=True) is True
    assert should_enable_consistency(20, 100, spec, teacher_confidence=0.9, assignment_entropy=0.2, stable_under_aug=True) is False
    assert should_enable_consistency(40, 100, spec, teacher_confidence=0.5, assignment_entropy=0.2, stable_under_aug=True) is False


def test_high_confidence_consistency_loss_uses_stop_gradient_and_can_stay_disabled() -> None:
    spec = {"consistency": {"enabled": False}}
    student = {"count_probs": torch.tensor([[0.2, 0.8]], dtype=torch.float32)}
    teacher = {"count_probs": torch.tensor([[0.7, 0.3]], dtype=torch.float32, requires_grad=True)}

    result = high_confidence_consistency_loss(student, teacher, spec)

    assert float(result["loss_total"]) == 0.0
    assert result["enabled"] is False
    assert result["teacher_stop_gradient"] is True
