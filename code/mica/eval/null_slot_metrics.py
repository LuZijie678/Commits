from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.model.null_slot import build_null_slot_mask


def compute_null_assignment_metrics(rows: list[dict[str, Any]], null_slot_id: str = "slot_null") -> dict[str, Any]:
    total_units = 0
    null_units = 0
    missing_by_role: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        mask = build_null_slot_mask(list(row.get("edit_units", [])), {})
        assignments = dict(row.get("unit_to_slot", {}))
        for unit in row.get("edit_units", []):
            unit_id = str(unit.get("unit_id"))
            role = str(unit.get("file_role", "unknown") or "unknown")
            assigned_null = assignments.get(unit_id) == null_slot_id
            total_units += 1
            if assigned_null:
                null_units += 1
            if not mask["eligible_by_unit_id"].get(unit_id, False):
                missing_by_role[role].append(1 if assigned_null else 0)
    return {
        "null_assignment_ratio": (null_units / total_units) if total_units else 0.0,
        "missing_intent_rate_by_file_role": {
            role: (sum(values) / len(values)) if values else 0.0 for role, values in missing_by_role.items()
        },
    }


def compute_gold_to_null_error(rows: list[dict[str, Any]], null_slot_id: str = "slot_null") -> dict[str, Any]:
    gold_units = 0
    gold_to_null = 0
    for row in rows:
        assignments = dict(row.get("unit_to_slot", {}))
        gold_map = dict(row.get("gold_unit_to_intent", {}))
        for unit_id in gold_map:
            gold_units += 1
            if assignments.get(str(unit_id)) == null_slot_id:
                gold_to_null += 1
    return {
        "gold_to_null_error_rate": (gold_to_null / gold_units) if gold_units else 0.0,
        "gold_to_null_count": gold_to_null,
    }


def compute_background_absorption_rate(rows: list[dict[str, Any]], null_slot_id: str = "slot_null") -> dict[str, Any]:
    eligible_background = 0
    absorbed = 0
    for row in rows:
        mask = build_null_slot_mask(list(row.get("edit_units", [])), {})
        assignments = dict(row.get("unit_to_slot", {}))
        for unit_id, eligible in mask["eligible_by_unit_id"].items():
            if not eligible:
                continue
            eligible_background += 1
            if assignments.get(unit_id) == null_slot_id:
                absorbed += 1
    return {
        "background_absorption_rate": (absorbed / eligible_background) if eligible_background else 0.0,
        "background_absorbed_count": absorbed,
    }


def compute_background_slot_audit_metrics(rows: list[dict[str, Any]], null_slot_id: str = "slot_null") -> dict[str, Any]:
    total_units = 0
    assigned_background = 0
    foreground_units = 0
    foreground_to_background = 0
    rule_background_units = 0
    rule_background_to_background = 0
    predicted_background_on_audited = 0
    missing_by_role: dict[str, list[int]] = defaultdict(list)
    excluded_unknown_units = 0

    for row in rows:
        assignments = {str(unit_id): str(slot_id) for unit_id, slot_id in dict(row.get("unit_to_slot", {})).items()}
        gold_foreground = {str(unit_id) for unit_id in dict(row.get("gold_unit_to_intent", {}))}
        uncertain_units = {str(unit_id) for unit_id in row.get("uncertain_units", [])}
        uncertain_units.update(str(unit_id) for unit_id in row.get("shared_support_units", []))
        uncertain_units.update(str(unit_id) for unit_id in row.get("mixed_units", []))
        background_units = _background_unit_ids(row)
        mask = build_null_slot_mask(list(row.get("edit_units", [])), {})
        rule_background = set(mask["eligible_unit_ids"])
        audited_background = background_units | rule_background

        for unit in row.get("edit_units", []):
            unit_id = str(unit.get("unit_id"))
            role = str(unit.get("file_role", "unknown") or "unknown")
            assigned_null = assignments.get(unit_id) == null_slot_id
            total_units += 1
            if assigned_null:
                assigned_background += 1
            if unit_id in uncertain_units:
                excluded_unknown_units += 1
                continue
            if unit_id in gold_foreground:
                foreground_units += 1
                missing_by_role[role].append(1 if assigned_null else 0)
                if assigned_null:
                    foreground_to_background += 1
            if unit_id in audited_background:
                rule_background_units += 1
                if assigned_null:
                    rule_background_to_background += 1
            if assigned_null and (unit_id in gold_foreground or unit_id in audited_background):
                predicted_background_on_audited += 1

    background_assignment_rate = assigned_background / total_units if total_units else 0.0
    foreground_to_background_error = foreground_to_background / foreground_units if foreground_units else 0.0
    background_recall = rule_background_to_background / rule_background_units if rule_background_units else 0.0
    background_precision = (
        rule_background_to_background / predicted_background_on_audited if predicted_background_on_audited else 0.0
    )
    return {
        "background_assignment_rate": background_assignment_rate,
        "foreground_evidence_swallowed_by_background": foreground_to_background_error,
        "foreground_to_background_error": foreground_to_background_error,
        "missing_intent_rate_by_file_role": {
            role: (sum(values) / len(values)) if values else 0.0 for role, values in missing_by_role.items()
        },
        "background_precision_on_rule_verified_background_units": background_precision,
        "background_recall_on_rule_verified_background_units": background_recall,
        "audit_denominators": {
            "total_units": total_units,
            "foreground_units": foreground_units,
            "rule_verified_background_units": rule_background_units,
            "predicted_background_on_audited_units": predicted_background_on_audited,
            "excluded_unknown_or_ambiguous_units": excluded_unknown_units,
        },
        "reporting_rules": {
            "background_errors_separate_from_foreground_attribution": True,
            "semantic_uncertainty_counted_as_correct_background": False,
            "unknown_background_labels_excluded_from_l_bg_denominators": True,
        },
    }


def _background_unit_ids(row: dict[str, Any]) -> set[str]:
    explicit = row.get("background_units", row.get("gold_background_units", []))
    if isinstance(explicit, dict):
        return {str(unit_id) for unit_id, value in explicit.items() if value}
    return {str(unit_id) for unit_id in explicit}
