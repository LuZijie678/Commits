from __future__ import annotations

import torch

from code.mica.losses.consistency_losses import high_confidence_consistency_loss


def test_consistency_ablation_respects_gates_and_uses_teacher_stop_gradient() -> None:
    student = {
        "count_probs": torch.tensor([[0.2, 0.8]], dtype=torch.float32),
        "slot_exist_probs": torch.tensor([[0.7, 0.2]], dtype=torch.float32),
        "assignment_probs": torch.tensor([[[0.9], [0.1]]], dtype=torch.float32),
    }
    teacher = {
        "count_probs": torch.tensor([[0.7, 0.3]], dtype=torch.float32, requires_grad=True),
        "slot_exist_probs": torch.tensor([[0.6, 0.3]], dtype=torch.float32, requires_grad=True),
        "assignment_probs": torch.tensor([[[0.8], [0.2]]], dtype=torch.float32, requires_grad=True),
    }
    spec = {
        "consistency": {
            "enabled": True,
            "enable_after_fraction": 0.3,
            "min_teacher_confidence": 0.7,
            "max_assignment_entropy": 0.6,
            "stable_under_aug": True,
            "teacher_confidence": 0.8,
            "assignment_entropy": 0.2,
            "step": 50,
            "total_steps": 100,
        }
    }

    enabled = high_confidence_consistency_loss(student, teacher, spec)
    disabled = high_confidence_consistency_loss(student, teacher, {"consistency": {"enabled": False}})

    assert float(enabled["loss_total"]) > 0.0
    assert enabled["enabled"] is True
    assert enabled["teacher_stop_gradient"] is True
    assert float(disabled["loss_total"]) == 0.0

