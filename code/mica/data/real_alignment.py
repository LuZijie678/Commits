from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


REQUIRED_REAL_ALIGNMENT_FIELDS = (
    "sample_id",
    "split",
    "edit_units",
    "gold_count",
    "gold_unit_to_intent",
    "scope_status",
    "intents",
    "background_units",
    "shared_support_units",
    "uncertain_units",
    "mixed_units",
)
VALID_SCOPE_STATUS = {"in_scope", "out_of_scope", "uncertain"}


def validate_real_alignment_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing = {field: 0 for field in REQUIRED_REAL_ALIGNMENT_FIELDS}
    invalid_scope_status = 0
    missing_action_object = 0
    missing_adjudication_fields = 0
    empty_intent_unit_ids = 0
    intent_unit_not_in_edit_units = 0
    gold_unit_not_in_edit_units = 0
    gold_unit_missing_from_intents = 0
    background_unit_not_in_edit_units = 0
    excluded_unit_overlap = 0
    gold_count_mismatch = 0
    out_of_scope_with_gold_alignment = 0
    intent_id_mismatch = 0
    for row in rows:
        for field in REQUIRED_REAL_ALIGNMENT_FIELDS:
            if row.get(field) is None:
                missing[field] += 1
        scope_status = str(row.get("scope_status", "")).lower()
        if scope_status not in VALID_SCOPE_STATUS:
            invalid_scope_status += 1
        edit_unit_ids = _edit_unit_ids(row.get("edit_units", []))
        gold_unit_to_intent = {str(unit_id): str(intent_id) for unit_id, intent_id in dict(row.get("gold_unit_to_intent", {})).items()}
        intent_unit_ids: set[str] = set()
        intent_ids: set[str] = set()
        for intent in list(row.get("intents", []) or []):
            if not isinstance(intent, dict) or not intent.get("action") or not intent.get("object"):
                missing_action_object += 1
                continue
            intent_id = str(intent.get("intent_id", ""))
            if intent_id:
                intent_ids.add(intent_id)
            unit_ids = {str(unit_id) for unit_id in list(intent.get("unit_ids", []) or [])}
            if not unit_ids:
                empty_intent_unit_ids += 1
            intent_unit_ids.update(unit_ids)
            intent_unit_not_in_edit_units += len(unit_ids - edit_unit_ids)
        if row.get("annotation_status") == "adjudicated" and not row.get("adjudicator_id"):
            missing_adjudication_fields += 1
        gold_unit_not_in_edit_units += len(set(gold_unit_to_intent) - edit_unit_ids)
        gold_unit_missing_from_intents += len(set(gold_unit_to_intent) - intent_unit_ids)
        intent_id_mismatch += len(set(gold_unit_to_intent.values()) - intent_ids)
        background_units = _unit_id_set(row.get("background_units", []))
        shared_support_units = _unit_id_set(row.get("shared_support_units", []))
        uncertain_units = _unit_id_set(row.get("uncertain_units", []))
        mixed_units = _unit_id_set(row.get("mixed_units", []))
        background_unit_not_in_edit_units += len(background_units - edit_unit_ids)
        excluded_unit_overlap += _overlap_count(
            [
                set(gold_unit_to_intent),
                background_units,
                shared_support_units,
                uncertain_units,
                mixed_units,
            ]
        )
        if scope_status == "in_scope":
            expected_count = len(list(row.get("intents", []) or []))
            if int(row.get("gold_count", -1) or -1) != expected_count:
                gold_count_mismatch += 1
        elif gold_unit_to_intent:
            out_of_scope_with_gold_alignment += 1
    ontology_valid = (
        empty_intent_unit_ids == 0
        and intent_unit_not_in_edit_units == 0
        and gold_unit_not_in_edit_units == 0
        and gold_unit_missing_from_intents == 0
        and background_unit_not_in_edit_units == 0
        and excluded_unit_overlap == 0
        and gold_count_mismatch == 0
        and out_of_scope_with_gold_alignment == 0
        and intent_id_mismatch == 0
    )
    return {
        "row_count": len(rows),
        "required_fields_present": all(value == 0 for value in missing.values()),
        "missing_field_counts": missing,
        "invalid_scope_status_count": invalid_scope_status,
        "missing_action_object_intent_count": missing_action_object,
        "missing_adjudication_field_count": missing_adjudication_fields,
        "empty_intent_unit_ids_count": empty_intent_unit_ids,
        "intent_unit_not_in_edit_units_count": intent_unit_not_in_edit_units,
        "gold_unit_not_in_edit_units_count": gold_unit_not_in_edit_units,
        "gold_unit_missing_from_intents_count": gold_unit_missing_from_intents,
        "background_unit_not_in_edit_units_count": background_unit_not_in_edit_units,
        "excluded_unit_overlap_count": excluded_unit_overlap,
        "gold_count_mismatch_count": gold_count_mismatch,
        "out_of_scope_with_gold_alignment_count": out_of_scope_with_gold_alignment,
        "intent_id_mismatch_count": intent_id_mismatch,
        "ontology_valid": ontology_valid,
        "schema_protocol": "edit_unit_action_object_scope_background_shared_uncertain_mixed",
        "valid": (
            all(value == 0 for value in missing.values())
            and invalid_scope_status == 0
            and missing_action_object == 0
            and missing_adjudication_fields == 0
            and ontology_valid
        ),
    }


def summarize_real_alignment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counter = Counter(str(row.get("split", "unknown")) for row in rows)
    edit_unit_lengths = [len(list(row.get("edit_units", []))) for row in rows]
    gold_counter = Counter(int(row.get("gold_count", 0) or 0) for row in rows)
    scope_counter = Counter(str(row.get("scope_status", "missing")) for row in rows)
    return {
        "row_count": len(rows),
        "split_distribution": dict(split_counter),
        "scope_status_distribution": dict(scope_counter),
        "gold_count_distribution": dict(gold_counter),
        "avg_edit_units": (sum(edit_unit_lengths) / len(edit_unit_lengths)) if edit_unit_lengths else 0.0,
    }


def check_double_annotation_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    annotators_by_sample: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        sample_id = row.get("sample_id")
        annotator_id = row.get("annotator_id")
        if sample_id is None or annotator_id is None:
            continue
        annotators_by_sample[str(sample_id)].add(str(annotator_id))
    double_annotated = sum(1 for annotators in annotators_by_sample.values() if len(annotators) >= 2)
    total = len(annotators_by_sample)
    return {
        "double_annotated_sample_count": double_annotated,
        "single_annotated_sample_count": total - double_annotated,
        "double_annotation_coverage": (double_annotated / total) if total else 0.0,
    }


def _edit_unit_ids(raw_units: Any) -> set[str]:
    unit_ids: set[str] = set()
    for item in list(raw_units or []):
        if isinstance(item, dict):
            unit_id = item.get("unit_id")
        else:
            unit_id = item
        if unit_id is not None:
            unit_ids.add(str(unit_id))
    return unit_ids


def _unit_id_set(raw_units: Any) -> set[str]:
    return {str(item) for item in list(raw_units or [])}


def _overlap_count(groups: list[set[str]]) -> int:
    seen: set[str] = set()
    overlaps: set[str] = set()
    for group in groups:
        overlaps.update(seen & group)
        seen.update(group)
    return len(overlaps)
