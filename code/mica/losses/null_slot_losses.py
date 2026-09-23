from __future__ import annotations

from collections import defaultdict
from typing import Any

import torch

from code.mica.model.null_slot import build_null_slot_mask


def compute_null_slot_loss(outputs: Any, batch: Any, spec: dict[str, Any]) -> dict[str, Any]:
    null_slot_id = str(spec.get("null_slot", {}).get("null_slot_id", "slot_null"))
    assignment_scores = _assignment_scores(outputs)
    assignments = _assignments(outputs, assignment_scores, null_slot_id=null_slot_id)
    mask = build_null_slot_mask(list(batch.edit_units), spec)
    background_losses: list[torch.Tensor] = []
    foreground_losses: list[torch.Tensor] = []
    diagnostics = _base_diagnostics(assignments, batch, mask, null_slot_id)
    for unit in batch.edit_units:
        unit_id = str(unit.get("unit_id"))
        null_prob = _null_probability(assignment_scores.get(unit_id, {}), null_slot_id)
        if mask["eligible_by_unit_id"].get(unit_id, False):
            background_losses.append(-torch.log(null_prob))
        elif _is_gold_foreground_unit(unit_id, batch):
            foreground_losses.append(-torch.log((1.0 - null_prob).clamp_min(1e-6)))
    background_loss = _mean_or_zero(background_losses)
    foreground_loss = _mean_or_zero(foreground_losses)
    loss_total = background_loss + foreground_loss
    return {
        "loss_total": loss_total,
        "background_null_loss": background_loss,
        "foreground_null_penalty": foreground_loss,
        "diagnostics": diagnostics,
    }


def compute_gold_evidence_null_penalty(outputs: Any, batch: Any, spec: dict[str, Any]) -> dict[str, Any]:
    null_slot_id = str(spec.get("null_slot", {}).get("null_slot_id", "slot_null"))
    assignment_scores = _assignment_scores(outputs)
    assignments = _assignments(outputs, assignment_scores, null_slot_id=null_slot_id)
    penalties: list[torch.Tensor] = []
    gold_to_null = 0
    for unit in batch.edit_units:
        unit_id = str(unit.get("unit_id"))
        if not _is_gold_foreground_unit(unit_id, batch):
            continue
        null_prob = _null_probability(assignment_scores.get(unit_id, {}), null_slot_id)
        penalties.append(-torch.log((1.0 - null_prob).clamp_min(1e-6)))
        if assignments.get(unit_id) == null_slot_id:
            gold_to_null += 1
    return {
        "loss_total": _mean_or_zero(penalties),
        "diagnostics": {
            "gold_evidence_assigned_to_null": gold_to_null,
            "null_slot_id": null_slot_id,
        },
    }


def _assignment_scores(outputs: Any) -> dict[str, dict[str, torch.Tensor]]:
    raw = outputs.get("assignment_scores") if isinstance(outputs, dict) else getattr(outputs, "assignment_scores", {})
    scores: dict[str, dict[str, torch.Tensor]] = {}
    for unit_id, slot_scores in dict(raw or {}).items():
        scores[str(unit_id)] = {str(slot_id): _to_tensor(value) for slot_id, value in dict(slot_scores).items()}
    return scores


def _assignments(outputs: Any, assignment_scores: dict[str, dict[str, torch.Tensor]], *, null_slot_id: str) -> dict[str, str]:
    raw = outputs.get("assignments") if isinstance(outputs, dict) else getattr(outputs, "assignments", {})
    if raw:
        return {str(unit_id): str(slot_id) for unit_id, slot_id in dict(raw).items()}
    assignments: dict[str, str] = {}
    for unit_id, slot_scores in assignment_scores.items():
        if not slot_scores:
            assignments[unit_id] = null_slot_id
            continue
        assignments[unit_id] = max(slot_scores.items(), key=lambda item: float(item[1]))[0]
    return assignments


def _null_probability(slot_scores: dict[str, torch.Tensor], null_slot_id: str) -> torch.Tensor:
    return _to_tensor(slot_scores.get(null_slot_id, 0.0)).clamp(1e-6, 1.0 - 1e-6)


def _base_diagnostics(assignments: dict[str, str], batch: Any, mask: dict[str, Any], null_slot_id: str) -> dict[str, Any]:
    total_units = len(batch.edit_units) or 1
    background_to_null = 0
    foreground_to_null = 0
    gold_to_null = 0
    missing_by_role: dict[str, list[int]] = defaultdict(list)
    for unit in batch.edit_units:
        unit_id = str(unit.get("unit_id"))
        role = str(unit.get("file_role", "unknown") or "unknown")
        assigned_null = assignments.get(unit_id) == null_slot_id
        if mask["eligible_by_unit_id"].get(unit_id, False) and assigned_null:
            background_to_null += 1
        if not mask["eligible_by_unit_id"].get(unit_id, False) and assigned_null:
            foreground_to_null += 1
            missing_by_role[role].append(1)
        elif not mask["eligible_by_unit_id"].get(unit_id, False):
            missing_by_role[role].append(0)
        if _is_gold_foreground_unit(unit_id, batch) and assigned_null:
            gold_to_null += 1
    return {
        "null_assignment_ratio": (background_to_null + foreground_to_null) / total_units,
        "gold_evidence_assigned_to_null": gold_to_null,
        "background_units_assigned_to_null": background_to_null,
        "foreground_units_assigned_to_null": foreground_to_null,
        "missing_intent_rate_by_file_role": {
            role: (sum(values) / len(values)) if values else 0.0 for role, values in missing_by_role.items()
        },
    }


def _is_gold_foreground_unit(unit_id: str, batch: Any) -> bool:
    if batch.gold_unit_to_intent and unit_id in batch.gold_unit_to_intent:
        return True
    for unit in batch.edit_units:
        if str(unit.get("unit_id")) == unit_id and unit.get("gold_intent_id") is not None:
            return True
    return False


def _mean_or_zero(values: list[torch.Tensor]) -> torch.Tensor:
    if not values:
        return torch.tensor(0.0, dtype=torch.float32)
    return torch.stack(values).mean()


def _to_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(float(value), dtype=torch.float32)

