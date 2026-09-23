from __future__ import annotations

import torch
import torch.nn.functional as F


def binary_dice_loss(probs: torch.Tensor, targets: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    probs = probs.reshape(-1)
    targets = targets.reshape(-1)
    intersection = (probs * targets).sum()
    denom = probs.sum() + targets.sum()
    dice = (2.0 * intersection + eps) / (denom + eps)
    return 1.0 - dice


def dice_bce_cost(probs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    dice = binary_dice_loss(probs, targets)
    bce = F.binary_cross_entropy(probs.clamp(1e-6, 1 - 1e-6), targets, reduction="mean")
    return dice + bce
