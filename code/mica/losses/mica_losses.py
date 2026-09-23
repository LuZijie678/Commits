from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from code.mica.losses.cardinality import count_loss_with_pb
from code.mica.losses.dice_bce import dice_bce_cost
from code.mica.losses.hungarian_matching import solve_slot_matching
from code.mica.models.mica_model import MicaOutput


def compute_stage1_losses(
    output: MicaOutput,
    targets: dict[str, Any],
    *,
    lambda_align: float = 1.0,
    lambda_count: float = 0.5,
    lambda_exist: float = 0.5,
    alpha_pb: float = 0.5,
    lambda_stab: float = 0.0,
    k2_min_second_slot_mass_ratio: float = 0.20,
    lambda_cal: float = 0.0,
    lambda_bg: float = 0.0,
) -> dict[str, torch.Tensor]:
    gold_counts: torch.Tensor = targets["gold_counts"]
    gold_count_indices = (gold_counts - 1).clamp(min=0, max=output.count_logits.size(-1) - 1)
    gold_assignment_masks: list[torch.Tensor] = targets["gold_assignment_masks"]
    batch_align_terms: list[torch.Tensor] = []
    batch_exist_terms: list[torch.Tensor] = []
    batch_stab_terms: list[torch.Tensor] = []
    batch_bg_terms: list[torch.Tensor] = []

    for batch_index, gold_masks in enumerate(gold_assignment_masks):
        predicted_probs = output.assignment_probs[batch_index]
        slot_exist_probs = output.slot_exist_probs[batch_index]
        raw_unit_mask = targets.get("unit_mask")
        if raw_unit_mask is None:
            unit_mask = torch.ones(predicted_probs.size(-1), dtype=torch.bool, device=predicted_probs.device)
        else:
            unit_mask = raw_unit_mask[batch_index].to(device=predicted_probs.device, dtype=torch.bool)
        active_predicted_probs = predicted_probs[:, unit_mask]
        active_gold_masks = gold_masks[:, unit_mask]
        gold_slot_count = int(gold_masks.size(0))
        cost_rows = []
        for gold_index in range(gold_slot_count):
            cost_row = []
            for predicted_index in range(active_predicted_probs.size(0)):
                cost_row.append(dice_bce_cost(active_predicted_probs[predicted_index], active_gold_masks[gold_index]))
            cost_rows.append(torch.stack(cost_row))
        cost_matrix = torch.stack(cost_rows)
        matching = solve_slot_matching(cost_matrix)
        align_costs = [cost_matrix[gold_index, predicted_index] for gold_index, predicted_index in matching.matched_pairs]
        batch_align_terms.append(torch.stack(align_costs).mean())

        exist_targets = torch.zeros_like(slot_exist_probs)
        for _, predicted_index in matching.matched_pairs:
            exist_targets[predicted_index] = 1.0
        batch_exist_terms.append(
            F.binary_cross_entropy(slot_exist_probs.clamp(1e-6, 1 - 1e-6), exist_targets, reduction="mean")
        )

        if int(gold_counts[batch_index].item()) == 2:
            active_mass = active_predicted_probs.sum(dim=-1)
            matched_predicted = [predicted_index for _, predicted_index in matching.matched_pairs]
            matched_mass = active_mass[matched_predicted]
            normalized_mass = matched_mass / matched_mass.sum().clamp_min(1e-6)
            second_mass_ratio = normalized_mass.min()
            batch_stab_terms.append(F.relu(torch.tensor(k2_min_second_slot_mass_ratio, device=second_mass_ratio.device) - second_mass_ratio))
        if output.null_assignment_probs is not None:
            batch_bg_terms.append(
                _masked_background_loss(
                    output.null_assignment_probs[batch_index],
                    targets,
                    batch_index=batch_index,
                    unit_mask=unit_mask,
                )
            )

    loss_align = torch.stack(batch_align_terms).mean() if batch_align_terms else output.assignment_probs.sum() * 0.0
    loss_exist = torch.stack(batch_exist_terms).mean() if batch_exist_terms else output.slot_exist_probs.sum() * 0.0
    loss_stab = torch.stack(batch_stab_terms).mean() if batch_stab_terms else output.assignment_probs.sum() * 0.0
    loss_bg = torch.stack(batch_bg_terms).mean() if batch_bg_terms else output.assignment_probs.sum() * 0.0
    loss_count_components = count_loss_with_pb(
        output.count_probs,
        output.pb_count_probs,
        gold_counts,
        alpha_pb=alpha_pb,
        lambda_cal=lambda_cal,
        stopgrad_count_for_kl=True,
    )
    loss_count = loss_count_components["loss_count"] + loss_count_components["loss_pb"] + loss_count_components["loss_cal"]
    loss_main = lambda_align * loss_align + lambda_count * loss_count + lambda_exist * loss_exist + lambda_bg * loss_bg
    loss_total = loss_main + lambda_stab * loss_stab
    return {
        "loss_total": loss_total,
        "loss_main": loss_main,
        "loss_align": loss_align,
        "loss_count": loss_count,
        "loss_exist": loss_exist,
        "loss_stab": loss_stab,
        "loss_bg": loss_bg,
        "background_loss_used": torch.tensor(float(lambda_bg > 0.0 and bool(batch_bg_terms)), device=loss_bg.device),
    }


def _masked_background_loss(
    null_probs: torch.Tensor,
    targets: dict[str, Any],
    *,
    batch_index: int,
    unit_mask: torch.Tensor,
) -> torch.Tensor:
    device = null_probs.device
    dtype = null_probs.dtype
    bg_targets = targets.get("background_targets", targets.get("gold_background_targets"))
    bg_mask = targets.get("background_mask", targets.get("gold_background_mask"))
    if bg_targets is None or bg_mask is None:
        return null_probs.sum() * 0.0
    target_row = torch.as_tensor(bg_targets[batch_index], device=device, dtype=dtype)
    mask_row = torch.as_tensor(bg_mask[batch_index], device=device, dtype=dtype)
    if target_row.numel() != null_probs.numel() or mask_row.numel() != null_probs.numel():
        raise ValueError("background_targets and background_mask must match null assignment unit dimension.")
    active_mask = unit_mask.to(device=device, dtype=dtype)
    supervision_mask = mask_row * active_mask
    if float(supervision_mask.sum().detach().cpu().item()) <= 0.0:
        return null_probs.sum() * 0.0
    per_unit = F.binary_cross_entropy(null_probs.clamp(1e-6, 1 - 1e-6), target_row.clamp(0.0, 1.0), reduction="none")
    return (per_unit * supervision_mask).sum() / supervision_mask.sum().clamp_min(1.0)
