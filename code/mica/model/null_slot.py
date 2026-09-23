from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import torch

from code.mica.features.file_role import infer_file_role


DEFAULT_LOCKFILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "cargo.lock",
}


def is_background_eligible_unit(edit_unit: dict[str, Any], spec: dict[str, Any]) -> bool:
    cfg = dict(spec.get("null_slot", spec))
    metadata = dict(edit_unit.get("metadata", {}))
    file_path = str(edit_unit.get("file_path", ""))
    role = str(edit_unit.get("file_role") or infer_file_role(file_path)).lower()
    name = PurePosixPath(file_path).name.lower()
    if metadata.get("generated_file") or role == "generated":
        return True
    if name in set(cfg.get("lockfile_names", DEFAULT_LOCKFILES)) or role == "lockfile":
        return True
    if metadata.get("large_generated_blob"):
        return True
    if _looks_like_format_only(edit_unit):
        return True
    if metadata.get("unknown_auxiliary") or role in {"auxiliary", "unknown_auxiliary"}:
        return True
    if _is_low_signal(edit_unit, role):
        return True
    return False


def build_null_slot_mask(edit_units: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    eligible_by_unit_id: dict[str, bool] = {}
    for unit in edit_units:
        unit_id = str(unit.get("unit_id", f"unit_{len(eligible_by_unit_id)}"))
        eligible_by_unit_id[unit_id] = is_background_eligible_unit(unit, spec)
    eligible_unit_ids = [unit_id for unit_id, eligible in eligible_by_unit_id.items() if eligible]
    foreground_unit_ids = [unit_id for unit_id, eligible in eligible_by_unit_id.items() if not eligible]
    return {
        "null_slot_id": str(spec.get("null_slot", {}).get("null_slot_id", "slot_null")),
        "eligible_by_unit_id": eligible_by_unit_id,
        "eligible_unit_ids": eligible_unit_ids,
        "foreground_unit_ids": foreground_unit_ids,
        "eligible_count": len(eligible_unit_ids),
        "total_units": len(eligible_by_unit_id),
    }


def append_null_slot_to_assignment_scores(scores: Any, spec: dict[str, Any]) -> Any:
    cfg = dict(spec.get("null_slot", spec))
    null_slot_id = str(cfg.get("null_slot_id", "slot_null"))
    default_score = float(cfg.get("default_score", cfg.get("default_logit", 0.0)))
    if isinstance(scores, dict):
        augmented: dict[str, dict[str, float]] = {}
        for unit_id, slot_scores in scores.items():
            row = {str(slot_id): float(value) for slot_id, value in dict(slot_scores).items()}
            row.setdefault(null_slot_id, default_score)
            augmented[str(unit_id)] = row
        return augmented
    if isinstance(scores, torch.Tensor):
        fill = torch.full((*scores.shape[:-1], 1), default_score, dtype=scores.dtype, device=scores.device)
        return torch.cat([scores, fill], dim=-1)
    raise TypeError(f"unsupported assignment score container: {type(scores)!r}")


def split_foreground_and_null_assignments(assignments: dict[str, str], null_slot_id: str = "slot_null") -> dict[str, Any]:
    foreground = {unit_id: slot_id for unit_id, slot_id in assignments.items() if slot_id != null_slot_id}
    null_assignments = {unit_id: slot_id for unit_id, slot_id in assignments.items() if slot_id == null_slot_id}
    return {
        "foreground_assignments": foreground,
        "null_assignments": null_assignments,
        "foreground_unit_ids": list(foreground.keys()),
        "null_unit_ids": list(null_assignments.keys()),
        "foreground_count": len(foreground),
        "null_count": len(null_assignments),
    }


def _looks_like_format_only(edit_unit: dict[str, Any]) -> bool:
    metadata = dict(edit_unit.get("metadata", {}))
    if metadata.get("format_only"):
        return True
    changed_identifiers = list(edit_unit.get("changed_identifiers", []) or [])
    if changed_identifiers:
        return False
    candidate_lines = []
    for key in ("added_lines", "deleted_lines"):
        candidate_lines.extend(str(line) for line in edit_unit.get(key, []) or [])
    if not candidate_lines:
        return False
    allowed = {"", "{", "}", "(", ")", "[", "]", ",", ";", ":"}
    normalized = [line.strip() for line in candidate_lines]
    return all(line in allowed for line in normalized)


def _is_low_signal(edit_unit: dict[str, Any], role: str) -> bool:
    if role in {"source", "test", "doc", "config", "build"}:
        return False
    identifiers = [item for item in list(edit_unit.get("changed_identifiers", []) or []) if str(item).strip()]
    patch_text = str(edit_unit.get("patch_text", ""))
    changed_lines = len([line for line in patch_text.splitlines() if line.strip()])
    return not identifiers and changed_lines <= 2

