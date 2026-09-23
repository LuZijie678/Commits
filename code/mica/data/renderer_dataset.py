from __future__ import annotations

from collections import Counter
from typing import Any


REQUIRED_RENDERER_FIELDS = ("sample_id", "structured_intent_plan", "assigned_evidence", "target_message", "source_kind")


def validate_renderer_dataset_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing = {field: 0 for field in REQUIRED_RENDERER_FIELDS}
    raw_full_diff_present_count = 0
    for row in rows:
        for field in REQUIRED_RENDERER_FIELDS:
            if row.get(field) is None:
                missing[field] += 1
        if row.get("raw_full_diff") not in {None, ""}:
            raw_full_diff_present_count += 1
    return {
        "row_count": len(rows),
        "required_fields_present": all(value == 0 for value in missing.values()),
        "missing_field_counts": missing,
        "raw_full_diff_present_count": raw_full_diff_present_count,
    }


def build_renderer_training_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows:
        evidence_terms = _extract_evidence_terms(list(row.get("assigned_evidence", [])))
        samples.append(
            {
                "sample_id": row.get("sample_id"),
                "structured_intent_plan": row.get("structured_intent_plan"),
                "assigned_evidence": row.get("assigned_evidence", []),
                "target_message": row.get("target_message", ""),
                "source_kind": row.get("source_kind"),
                "evidence_terms": evidence_terms,
            }
        )
    return samples


def summarize_renderer_dataset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counter = Counter(str(row.get("source_kind", "unknown")) for row in rows)
    return {
        "row_count": len(rows),
        "source_kind_distribution": dict(source_counter),
        "validation": validate_renderer_dataset_rows(rows),
    }


def _extract_evidence_terms(assigned_evidence: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for item in assigned_evidence:
        file_path = item.get("file_path")
        if file_path:
            terms.extend(str(file_path).replace("/", " ").replace(".", " ").split())
        for identifier in item.get("changed_identifiers", []) or []:
            terms.extend(str(identifier).split("_"))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped
