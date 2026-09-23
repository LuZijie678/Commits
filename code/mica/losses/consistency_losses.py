from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F


def should_enable_consistency(
    step: int,
    total_steps: int,
    spec: dict[str, Any],
    teacher_confidence: float,
    assignment_entropy: float,
    stable_under_aug: bool,
) -> bool:
    cfg = _cfg(spec)
    if not bool(cfg.get("enabled", False)):
        return False
    warmup_fraction = float(cfg.get("enable_after_fraction", 0.3))
    min_teacher_confidence = float(cfg.get("min_teacher_confidence", 0.8))
    max_assignment_entropy = float(cfg.get("max_assignment_entropy", 0.5))
    if total_steps <= 0:
        return False
    if (step / total_steps) < warmup_fraction:
        return False
    if teacher_confidence < min_teacher_confidence:
        return False
    if assignment_entropy > max_assignment_entropy:
        return False
    if not stable_under_aug:
        return False
    return True


def high_confidence_consistency_loss(student_outputs: dict[str, Any], teacher_outputs: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(spec)
    enabled = bool(cfg.get("enabled", False))
    teacher_count = _to_tensor(teacher_outputs.get("count_probs", []))
    teacher_slot = _to_tensor(teacher_outputs.get("slot_exist_probs", []))
    teacher_assignment = _to_tensor(teacher_outputs.get("assignment_probs", []))
    if not enabled:
        return {
            "loss_total": torch.tensor(0.0),
            "enabled": False,
            "teacher_stop_gradient": True,
            "diagnostics": {
                "consistency_enabled_in_spec": False,
                "requires_ema_teacher": bool(cfg.get("requires_ema_teacher", True)),
            },
        }

    teacher_confidence = float(cfg.get("teacher_confidence", teacher_count.max().item() if teacher_count.numel() else 0.0))
    assignment_entropy = float(cfg.get("assignment_entropy", _assignment_entropy(student_outputs.get("assignment_probs", []))))
    stable_under_aug = bool(cfg.get("stable_under_aug", False))
    step = int(cfg.get("step", 0))
    total_steps = int(cfg.get("total_steps", 0))
    if not should_enable_consistency(
        step,
        total_steps,
        spec,
        teacher_confidence=teacher_confidence,
        assignment_entropy=assignment_entropy,
        stable_under_aug=stable_under_aug,
    ):
        return {
            "loss_total": torch.tensor(0.0),
            "enabled": False,
            "teacher_stop_gradient": True,
            "diagnostics": {
                "consistency_enabled_in_spec": True,
                "requires_ema_teacher": bool(cfg.get("requires_ema_teacher", True)),
                "teacher_confidence": teacher_confidence,
                "assignment_entropy": assignment_entropy,
                "stable_under_aug": stable_under_aug,
            },
        }

    student_count = _to_tensor(student_outputs.get("count_probs", []))
    student_slot = _to_tensor(student_outputs.get("slot_exist_probs", []))
    student_assignment = _to_tensor(student_outputs.get("assignment_probs", []))
    loss_count = _distribution_alignment_loss(student_count, teacher_count.detach())
    loss_slot = torch.mean((student_slot - teacher_slot.detach()) ** 2) if teacher_slot.numel() and student_slot.numel() else torch.tensor(0.0)
    loss_assignment = _distribution_alignment_loss(student_assignment, teacher_assignment.detach())
    loss_total = loss_count + loss_slot + loss_assignment
    return {
        "loss_total": loss_total,
        "enabled": True,
        "teacher_stop_gradient": True,
        "diagnostics": {
            "consistency_enabled_in_spec": True,
            "requires_ema_teacher": bool(cfg.get("requires_ema_teacher", True)),
            "teacher_confidence": teacher_confidence,
            "assignment_entropy": assignment_entropy,
            "stable_under_aug": stable_under_aug,
        },
    }


def _cfg(spec: dict[str, Any]) -> dict[str, Any]:
    return dict(spec.get("consistency", spec))


def _to_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    if value in (None, []):
        return torch.tensor([], dtype=torch.float32)
    return torch.tensor(value, dtype=torch.float32)


def _distribution_alignment_loss(student: torch.Tensor, teacher: torch.Tensor) -> torch.Tensor:
    if not teacher.numel() or not student.numel():
        return torch.tensor(0.0)
    teacher_probs = teacher.clamp_min(1e-6)
    student_probs = student.clamp_min(1e-6)
    teacher_probs = teacher_probs / teacher_probs.sum(dim=-1, keepdim=True).clamp_min(1e-6)
    student_probs = student_probs / student_probs.sum(dim=-1, keepdim=True).clamp_min(1e-6)
    return F.kl_div(student_probs.log(), teacher_probs, reduction="batchmean")


def _assignment_entropy(value: Any) -> float:
    probs = _to_tensor(value)
    if probs.numel() == 0:
        return 0.0
    if probs.ndim == 3:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum(dim=1).mean()
    elif probs.ndim == 2:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum(dim=-1).mean()
    else:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum()
    return float(entropy.item())
