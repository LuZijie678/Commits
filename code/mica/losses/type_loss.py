from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F


def optional_type_loss(pred_type_logits: Any, gold_types: list[Any], lambda_type: float = 0.1) -> dict[str, Any]:
    if lambda_type <= 0.0 or not gold_types:
        zero = torch.tensor(0.0, dtype=torch.float32)
        return {
            "loss_total": zero,
            "included_in_hungarian_cost": False,
            "enabled": False,
        }
    logits = _as_tensor(pred_type_logits)
    labels = _label_tensor(gold_types, num_classes=logits.size(-1))
    loss_raw = F.cross_entropy(logits, labels, reduction="mean")
    return {
        "loss_total": float(lambda_type) * loss_raw,
        "loss_raw": loss_raw,
        "lambda_type": float(lambda_type),
        "included_in_hungarian_cost": False,
        "enabled": True,
    }


def _label_tensor(gold_types: list[Any], num_classes: int) -> torch.Tensor:
    if all(isinstance(item, int) for item in gold_types):
        return torch.tensor(gold_types, dtype=torch.long)
    label_to_index = {label: index for index, label in enumerate(sorted({str(item) for item in gold_types}))}
    labels = torch.tensor([label_to_index[str(item)] for item in gold_types], dtype=torch.long)
    if labels.max().item() >= num_classes:
        raise ValueError("pred_type_logits has fewer classes than gold type labels.")
    return labels


def _as_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)

