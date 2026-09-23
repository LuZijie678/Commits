from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch


@dataclass(slots=True)
class DecodedIntentAssignments:
    predicted_count: int
    active_slot_indices: list[int]
    unit_to_slot: dict[str, str]
    unit_assignment_scores: dict[str, dict[str, float]]
    active_assignment_probs: torch.Tensor
    active_null_assignment_probs: torch.Tensor | None
    diagnostics: dict[str, Any]


def decode_active_slot_assignments(
    *,
    count_probs: torch.Tensor,
    slot_exist_probs: torch.Tensor,
    assignment_probs: torch.Tensor,
    unit_ids: list[str],
    unit_mask: torch.Tensor | None = None,
    null_assignment_probs: torch.Tensor | None = None,
    slot_id_prefix: str = "slot",
) -> DecodedIntentAssignments:
    """Decode one sample using the frozen MICA-v3 inference protocol."""
    if count_probs.ndim != 1:
        raise ValueError("count_probs must be a 1D tensor for one sample.")
    if slot_exist_probs.ndim != 1:
        raise ValueError("slot_exist_probs must be a 1D tensor for one sample.")
    if assignment_probs.ndim != 2:
        raise ValueError("assignment_probs must have shape (Kmax, units) for one sample.")
    if assignment_probs.size(0) != slot_exist_probs.numel():
        raise ValueError("assignment_probs slot dimension must match slot_exist_probs.")

    device = assignment_probs.device
    active_mask = _active_unit_mask(unit_mask, assignment_probs.size(1), device=device)
    k_hat = int(count_probs.argmax(dim=-1).item()) + 1
    k_select = max(1, min(k_hat, slot_exist_probs.numel()))
    active_slot_indices = torch.topk(slot_exist_probs, k=k_select).indices.tolist()

    selected_assignment = assignment_probs[active_slot_indices, :]
    if null_assignment_probs is None:
        selected_null = None
        denom = selected_assignment.sum(dim=0, keepdim=True).clamp_min(1e-6)
    else:
        selected_null = null_assignment_probs.to(device=device, dtype=assignment_probs.dtype)
        denom = (selected_assignment.sum(dim=0) + selected_null).clamp_min(1e-6).unsqueeze(0)
    renormalized_assignment = selected_assignment / denom
    renormalized_null = (selected_null / denom.squeeze(0)) if selected_null is not None else None
    renormalized_assignment = renormalized_assignment * active_mask.unsqueeze(0).to(renormalized_assignment.dtype)
    if renormalized_null is not None:
        renormalized_null = renormalized_null * active_mask.to(renormalized_null.dtype)

    unit_to_slot: dict[str, str] = {}
    unit_assignment_scores: dict[str, dict[str, float]] = {}
    effective_unit_count = min(len(unit_ids), assignment_probs.size(1))
    for unit_index in range(effective_unit_count):
        unit_id = unit_ids[unit_index]
        if not bool(active_mask[unit_index].item()):
            continue
        local_scores = renormalized_assignment[:, unit_index]
        local_slot_index = int(local_scores.argmax(dim=0).item())
        global_slot_index = active_slot_indices[local_slot_index]
        slot_id = f"{slot_id_prefix}_{global_slot_index + 1}"
        unit_to_slot[unit_id] = slot_id
        unit_assignment_scores[unit_id] = {
            f"{slot_id_prefix}_{global_index + 1}": float(local_scores[local_index].item())
            for local_index, global_index in enumerate(active_slot_indices)
        }
        if renormalized_null is not None:
            unit_assignment_scores[unit_id]["slot_null"] = float(renormalized_null[unit_index].item())

    diagnostics = {
        "decode_protocol": "p_count_argmax_topk_exist_active_plus_null_renormalization",
        "predicted_count_source": "argmax_count_probs",
        "active_slot_selection": "top_k_by_calibrated_slot_existence",
        "active_null_renormalization_used": null_assignment_probs is not None,
        "predicted_count": k_hat,
        "active_slot_indices": list(active_slot_indices),
        "active_unit_count": int(active_mask.sum().item()),
    }
    return DecodedIntentAssignments(
        predicted_count=k_hat,
        active_slot_indices=list(active_slot_indices),
        unit_to_slot=unit_to_slot,
        unit_assignment_scores=unit_assignment_scores,
        active_assignment_probs=renormalized_assignment,
        active_null_assignment_probs=renormalized_null,
        diagnostics=diagnostics,
    )


def _active_unit_mask(unit_mask: torch.Tensor | None, unit_count: int, *, device: torch.device) -> torch.Tensor:
    if unit_mask is None:
        return torch.ones(unit_count, dtype=torch.bool, device=device)
    if unit_mask.ndim != 1:
        raise ValueError("unit_mask must be 1D for one sample.")
    if unit_mask.numel() != unit_count:
        raise ValueError("unit_mask length must match assignment unit dimension.")
    return unit_mask.to(device=device, dtype=torch.bool)
