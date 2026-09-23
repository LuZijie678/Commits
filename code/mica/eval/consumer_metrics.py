from __future__ import annotations

from typing import Any, Iterable


def aggregate_consumer_records(
    records: Iterable[dict[str, Any]],
    *,
    macro_group_by: str | None = None,
) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    included = [row for row in rows if bool(row.get("verification_eligible"))]
    excluded = [row for row in rows if not bool(row.get("verification_eligible"))]
    success = [row for row in included if row.get("status") == "success"]
    rejected = [row for row in included if row.get("status") == "rejected"]
    fallback_rows = [row for row in included if bool(dict(row.get("fallback", {})).get("fallback_used"))]

    coverage_values = [_slot_coverage(row) for row in included if _slot_coverage(row) is not None]
    entity_precision_values = [
        _entity_grounding_precision(row) for row in included if _entity_grounding_precision(row) is not None
    ]
    unsupported_flags = [_unsupported_claim_flag(row) for row in included if _unsupported_claim_flag(row) is not None]
    background_flags = [_background_mention_flag(row) for row in included if _background_mention_flag(row) is not None]
    format_flags = [_format_valid_flag(row) for row in included if _format_valid_flag(row) is not None]

    micro = {
        "success_rate": _rate(len(success), len(included)),
        "reject_rate": _rate(len(rejected), len(included)),
        "fallback_rate": _rate(len(fallback_rows), len(included)),
        "mean_intent_coverage": _mean(coverage_values),
        "missing_intent_rate": _mean([1.0 - value for value in coverage_values]) if coverage_values else None,
        "unsupported_claim_rate": _mean([float(value) for value in unsupported_flags]) if unsupported_flags else None,
        "entity_grounding_precision": _mean(entity_precision_values),
        "background_mention_rate": _mean([float(value) for value in background_flags]) if background_flags else None,
        "format_compliance": _mean([float(value) for value in format_flags]) if format_flags else None,
    }
    denominators = {
        "success_rate": {"definition": "success_count / included_count", "denominator": len(included)},
        "reject_rate": {"definition": "rejected_count / included_count", "denominator": len(included)},
        "fallback_rate": {"definition": "fallback_used / included_count", "denominator": len(included)},
        "intent_coverage": {"definition": "mean(intent_coverage_rate)", "denominator": len(coverage_values)},
        "missing_intent_rate": {"definition": "mean(1 - intent_coverage_rate)", "denominator": len(coverage_values)},
        "unsupported_claim_rate": {"definition": "mean(has_unsupported_claim)", "denominator": len(unsupported_flags)},
        "entity_grounding_precision": {
            "definition": "mean(entity_grounding_precision)",
            "denominator": len(entity_precision_values),
        },
        "background_mention_rate": {
            "definition": "mean(has_background_mention)",
            "denominator": len(background_flags),
        },
        "format_compliance": {"definition": "mean(format_valid)", "denominator": len(format_flags)},
    }
    sample_counts = {
        "sample_count": len(rows),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "success_count": len(success),
        "rejected_count": len(rejected),
    }
    excluded_reason_counts: dict[str, int] = {}
    for row in excluded:
        reason = str(row.get("excluded_reason") or "unknown")
        excluded_reason_counts[reason] = excluded_reason_counts.get(reason, 0) + 1

    macro: dict[str, Any] = {}
    if macro_group_by:
        from code.mica.eval.consumer_stratification import stratify_consumer_records

        grouped = stratify_consumer_records(rows, group_by=macro_group_by)
        macro = {
            key: _mean(
                [
                    group["aggregate_metrics"][key]
                    for group in grouped
                    if group["aggregate_metrics"].get(key) is not None
                ]
            )
            for key in micro
        }
    return {
        "sample_counts": sample_counts,
        "aggregate_metrics": {
            "success_rate": micro["success_rate"],
            "reject_rate": micro["reject_rate"],
            "fallback_rate": micro["fallback_rate"],
            "intent_coverage": micro["mean_intent_coverage"],
            "missing_intent_rate": micro["missing_intent_rate"],
            "unsupported_claim_rate": micro["unsupported_claim_rate"],
            "entity_grounding_precision": micro["entity_grounding_precision"],
            "background_mention_rate": micro["background_mention_rate"],
            "format_compliance": micro["format_compliance"],
        },
        "micro": micro,
        "macro": macro,
        "denominators": denominators,
        "excluded_reasons": excluded_reason_counts,
    }


def _slot_coverage(row: dict[str, Any]) -> float | None:
    payload = dict(row.get("verification", {})).get("slot_coverage", {})
    value = payload.get("intent_coverage_rate") if isinstance(payload, dict) else None
    return float(value) if value is not None else None


def _entity_grounding_precision(row: dict[str, Any]) -> float | None:
    payload = dict(row.get("verification", {})).get("entity_grounding", {})
    value = payload.get("entity_grounding_precision") if isinstance(payload, dict) else None
    return float(value) if value is not None else None


def _unsupported_claim_flag(row: dict[str, Any]) -> bool | None:
    payload = dict(row.get("verification", {})).get("unsupported_claims", {})
    unsupported = payload.get("unsupported_claims") if isinstance(payload, dict) else None
    if unsupported is None:
        return None
    return bool(list(unsupported))


def _background_mention_flag(row: dict[str, Any]) -> bool | None:
    payload = dict(row.get("verification", {})).get("background_exclusion", {})
    mentions = payload.get("background_mentions") if isinstance(payload, dict) else None
    if mentions is None:
        return None
    return bool(list(mentions))


def _format_valid_flag(row: dict[str, Any]) -> bool | None:
    payload = dict(row.get("verification", {})).get("format", {})
    value = payload.get("valid") if isinstance(payload, dict) else None
    return bool(value) if value is not None else None


def _rate(numerator: int, denominator: int) -> float | None:
    return (float(numerator) / float(denominator)) if denominator else None


def _mean(values: Iterable[float] | list[float]) -> float | None:
    seq = list(values)
    if not seq:
        return None
    return float(sum(seq)) / float(len(seq))
