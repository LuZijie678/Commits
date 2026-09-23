from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any

from code.mica.annotation.real_alignment_schema import normalize_alignment_annotation, validate_alignment_annotation


def build_adjudication_item(sample_annotations: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [normalize_alignment_annotation(row) for row in sample_annotations]
    if not normalized:
        return {
            "requires_adjudication": False,
            "disagreement_units": [],
            "count_disagreement": False,
            "sample_id": None,
        }
    disagreement_units = set()
    count_disagreement = len({row["intent_count"] for row in normalized}) > 1
    shared_units = sorted(set.intersection(*(set(row["unit_to_intent"]) for row in normalized))) if len(normalized) >= 2 else []
    for left, right in combinations(normalized, 2):
        for unit_a, unit_b in combinations(shared_units, 2):
            left_same = left["unit_to_intent"][unit_a] == left["unit_to_intent"][unit_b]
            right_same = right["unit_to_intent"][unit_a] == right["unit_to_intent"][unit_b]
            if left_same != right_same:
                disagreement_units.update({unit_a, unit_b})
    return {
        "sample_id": normalized[0]["sample_id"],
        "annotators": [row["annotator_id"] for row in normalized],
        "requires_adjudication": bool(count_disagreement or disagreement_units),
        "count_disagreement": count_disagreement,
        "disagreement_units": sorted(disagreement_units),
    }


def validate_adjudicated_annotation(row: dict[str, Any]) -> dict[str, Any]:
    result = validate_alignment_annotation(row)
    errors = list(result["errors"])
    normalized = normalize_alignment_annotation(row)
    if normalized.get("annotation_status") == "adjudicated" and not normalized.get("adjudicator_id"):
        errors.append("missing_adjudicator_id")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": result["warnings"],
    }


def summarize_adjudication_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(normalize_alignment_annotation(row)["annotation_status"] for row in rows)
    return {
        "annotation_status_counts": dict(counts),
        "adjudicated_count": counts.get("adjudicated", 0),
    }
