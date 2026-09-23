from __future__ import annotations

from typing import Any

import torch


def assignment_entropy_loss(assignments: Any, coeff: float) -> dict[str, Any]:
    probs = _as_tensor(assignments)
    if probs.numel() == 0 or coeff == 0.0:
        zero = torch.tensor(0.0, dtype=torch.float32)
        return {"loss_total": zero, "entropy_mean": zero, "coeff": coeff}
    if probs.ndim == 3:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum(dim=1).mean()
    elif probs.ndim == 2:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum(dim=-1).mean()
    else:
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log()).sum()
    loss_total = -float(coeff) * entropy
    return {"loss_total": loss_total, "entropy_mean": entropy, "coeff": float(coeff)}


def _as_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)

