from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


REQUIRED_FIELDS = (
    "sample_id",
    "repo",
    "sha",
    "split",
    "scope_status",
    "annotator_id",
    "annotation_round",
    "edit_units",
    "intent_count",
    "unit_to_intent",
    "intent_groups",
    "intents",
    "background_units",
    "shared_support_units",
    "uncertain_units",
    "mixed_units",
    "created_at",
    "schema_version",
)
VALID_SCOPE_STATUS = {"in_scope", "out_of_scope", "uncertain"}


def normalize_alignment_annotation(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["sample_id"] = str(row.get("sample_id", ""))
    normalized["repo"] = str(row.get("repo", ""))
    normalized["sha"] = str(row.get("sha", ""))
    normalized["split"] = str(row.get("split", ""))
    normalized["scope_status"] = str(row.get("scope_status", "in_scope"))
    normalized["annotator_id"] = str(row.get("annotator_id", ""))
    normalized["annotation_round"] = int(row.get("annotation_round", 1) or 1)
    normalized["edit_units"] = [dict(item) for item in row.get("edit_units", [])]
    normalized["unit_to_intent"] = {
        str(unit_id): str(intent_id) for unit_id, intent_id in dict(row.get("unit_to_intent", {})).items()
    }
    normalized["intent_groups"] = _normalize_intent_groups(
        row.get("intent_groups"),
        normalized["unit_to_intent"],
    )
    normalized["intent_count"] = int(row.get("intent_count", len(normalized["intent_groups"])) or len(normalized["intent_groups"]))
    normalized["hunk_to_intent"] = {
        str(hunk_id): str(intent_id) for hunk_id, intent_id in dict(row.get("hunk_to_intent", {})).items()
    }
    normalized["major_minor_flags"] = {
        str(intent_id): str(flag) for intent_id, flag in dict(row.get("major_minor_flags", {})).items()
    }
    normalized["intent_types"] = [str(item) for item in row.get("intent_types", [])]
    normalized["intent_subjects"] = [str(item) for item in row.get("intent_subjects", [])]
    normalized["intents"] = [_normalize_intent(item) for item in row.get("intents", [])]
    normalized["annotator_confidence"] = float(row.get("annotator_confidence", 0.0) or 0.0)
    normalized["uncertain_units"] = [str(item) for item in row.get("uncertain_units", [])]
    normalized["shared_support_units"] = [str(item) for item in row.get("shared_support_units", [])]
    normalized["mixed_units"] = [str(item) for item in row.get("mixed_units", [])]
    normalized["background_units"] = [str(item) for item in row.get("background_units", row.get("gold_background_units", []))]
    normalized["notes"] = str(row.get("notes", ""))
    normalized["created_at"] = str(row.get("created_at", ""))
    normalized["schema_version"] = str(row.get("schema_version", "v1"))
    if row.get("annotation_status"):
        normalized["annotation_status"] = str(row["annotation_status"])
    elif row.get("adjudicator_id"):
        normalized["annotation_status"] = "adjudicated"
    else:
        normalized["annotation_status"] = "single_annotated"
    if row.get("adjudicator_id") is not None:
        normalized["adjudicator_id"] = str(row.get("adjudicator_id"))
    return normalized


def validate_alignment_annotation(row: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_alignment_annotation(row)
    errors: list[str] = []
    warnings: list[str] = []
    for field in REQUIRED_FIELDS:
        value = normalized.get(field)
        if value in (None, "", []):
            errors.append(f"missing_{field}")

    group_map = _group_map(normalized["intent_groups"])
    unit_map = dict(normalized["unit_to_intent"])
    if group_map != unit_map:
        errors.append("intent_group_mismatch")
    if normalized["intent_count"] != len(normalized["intent_groups"]):
        errors.append("intent_count_mismatch")
    if normalized["scope_status"].lower() not in VALID_SCOPE_STATUS:
        errors.append("invalid_scope_status")
    if not normalized["intents"]:
        errors.append("missing_intents")
    for intent in normalized["intents"]:
        if not intent.get("action") or not intent.get("object"):
            errors.append("missing_action_object_intent")
            break
    if not normalized["hunk_to_intent"]:
        warnings.append("missing_hunk_to_intent")
    if normalized["split"].lower() in {"m-final-test", "m_final_test"}:
        errors.append("m_final_test_forbidden_for_calibration")
    valid = not errors
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "annotation_status": normalized["annotation_status"],
    }


def annotation_to_gold_maps(row: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_alignment_annotation(row)
    excluded_unit_ids = _excluded_alignment_unit_ids(normalized)
    foreground_unit_to_intent = {
        unit_id: intent_id
        for unit_id, intent_id in normalized["unit_to_intent"].items()
        if unit_id not in excluded_unit_ids
    }
    gold_intent_to_units: dict[str, list[str]] = defaultdict(list)
    for unit_id, intent_id in foreground_unit_to_intent.items():
        gold_intent_to_units[intent_id].append(unit_id)
    return {
        "gold_unit_to_intent": foreground_unit_to_intent,
        "gold_hunk_to_intent": {
            hunk_id: intent_id
            for hunk_id, intent_id in normalized["hunk_to_intent"].items()
            if hunk_id not in excluded_unit_ids
        },
        "gold_intent_to_units": {intent_id: sorted(unit_ids) for intent_id, unit_ids in gold_intent_to_units.items()},
        "excluded_alignment_unit_ids": sorted(excluded_unit_ids),
        "excluded_alignment_unit_count": len(excluded_unit_ids),
        "alignment_mask_protocol": "exclude_uncertain_shared_support_mixed_from_primary_alignment",
    }


def summarize_annotation_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_rows = [normalize_alignment_annotation(row) for row in rows]
    status_counts = Counter(row["annotation_status"] for row in normalized_rows)
    split_counts = Counter(row["split"] for row in normalized_rows)
    confidences = [row["annotator_confidence"] for row in normalized_rows]
    hunk_missing = sum(1 for row in normalized_rows if not row["hunk_to_intent"])
    return {
        "row_count": len(normalized_rows),
        "annotation_status_counts": dict(status_counts),
        "split_counts": dict(split_counts),
        "mean_annotator_confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
        "missing_hunk_to_intent_count": hunk_missing,
    }


def _normalize_intent_groups(raw_groups: Any, unit_to_intent: dict[str, str]) -> list[list[str]]:
    if raw_groups:
        return [sorted(str(unit_id) for unit_id in group) for group in raw_groups]
    by_intent: dict[str, list[str]] = defaultdict(list)
    for unit_id, intent_id in unit_to_intent.items():
        by_intent[intent_id].append(unit_id)
    return [sorted(unit_ids) for _, unit_ids in sorted(by_intent.items())]


def _normalize_intent(raw: Any) -> dict[str, Any]:
    item = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "intent_id": str(item.get("intent_id", "")),
        "action": str(item.get("action", "")),
        "object": str(item.get("object", "")),
        "scope": str(item.get("scope", "")),
        "unit_ids": [str(unit_id) for unit_id in item.get("unit_ids", [])],
    }


def _group_map(intent_groups: list[list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for index, group in enumerate(intent_groups, 1):
        intent_id = f"intent_{index}"
        for unit_id in group:
            mapping[str(unit_id)] = intent_id
    return mapping


def _excluded_alignment_unit_ids(row: dict[str, Any]) -> set[str]:
    excluded = {str(item) for item in row.get("uncertain_units", [])}
    excluded.update(str(item) for item in row.get("shared_support_units", []))
    excluded.update(str(item) for item in row.get("mixed_units", []))
    return excluded
