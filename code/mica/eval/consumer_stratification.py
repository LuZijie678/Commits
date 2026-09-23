from __future__ import annotations

from typing import Any

from code.mica.eval.consumer_metrics import aggregate_consumer_records


SUPPORTED_GROUPING_KEYS = {
    "predicted_k",
    "gold_k",
    "decision",
    "plan_source",
    "background_contract.evidence_complete",
    "fallback_level",
    "file_role_composition",
    "source_type",
    "hard_b_flag",
    "multi_intent",
    "background_assignment_type",
}


def stratify_consumer_records(
    records: list[dict[str, Any]],
    *,
    group_by: str,
) -> list[dict[str, Any]]:
    if group_by not in SUPPORTED_GROUPING_KEYS:
        raise ValueError(f"unsupported group_by {group_by!r}")
    groups: dict[str, list[dict[str, Any]]] = {}
    raw_values: dict[str, Any] = {}
    for row in records:
        value = _group_value(row, group_by)
        key = repr(value)
        raw_values[key] = value
        groups.setdefault(key, []).append(row)
    summaries: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda item: str(raw_values[item])):
        group_rows = groups[key]
        aggregate = aggregate_consumer_records(group_rows)
        summaries.append(
            {
                "group_by": group_by,
                "group_value": raw_values[key],
                "sample_count": aggregate["sample_counts"]["sample_count"],
                "included_count": aggregate["sample_counts"]["included_count"],
                "excluded_count": aggregate["sample_counts"]["excluded_count"],
                "success_count": aggregate["sample_counts"]["success_count"],
                "rejected_count": aggregate["sample_counts"]["rejected_count"],
                "aggregate_metrics": aggregate["aggregate_metrics"],
                "denominators": aggregate["denominators"],
                "excluded_reasons": aggregate["excluded_reasons"],
            }
        )
    return summaries


def _group_value(row: dict[str, Any], group_by: str) -> Any:
    if group_by == "background_contract.evidence_complete":
        contract = dict(row.get("background_contract", {}))
        if "evidence_complete" in contract:
            return bool(contract.get("evidence_complete"))
        return not bool(contract.get("evidence_incomplete", False))
    strata = dict(row.get("strata", {}))
    if group_by in strata:
        return strata[group_by]
    if group_by == "fallback_level":
        return dict(row.get("fallback", {})).get("fallback_level")
    return row.get(group_by)
