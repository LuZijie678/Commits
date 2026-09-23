from __future__ import annotations

from typing import Any

from code.mica.eval.consumer_metrics import aggregate_consumer_records
from code.mica.eval.consumer_records import ConsumerRunComparisonRecord


def compare_consumer_runs(
    predicted_records: list[dict[str, Any]],
    oracle_records: list[dict[str, Any]],
) -> dict[str, Any]:
    predicted_by_commit = _index_by_commit_id(predicted_records, label="predicted")
    oracle_by_commit = _index_by_commit_id(oracle_records, label="oracle")
    paired_ids = sorted(set(predicted_by_commit) & set(oracle_by_commit))
    predicted_only = sorted(set(predicted_by_commit) - set(oracle_by_commit))
    oracle_only = sorted(set(oracle_by_commit) - set(predicted_by_commit))

    per_sample_deltas: list[dict[str, Any]] = []
    excluded_pairs: list[dict[str, Any]] = []
    for commit_id in paired_ids:
        predicted = predicted_by_commit[commit_id]
        oracle = oracle_by_commit[commit_id]
        if not bool(predicted.get("verification_eligible", False)) or not bool(oracle.get("verification_eligible", False)):
            excluded_pairs.append(
                {
                    "commit_id": commit_id,
                    "predicted_excluded_reason": predicted.get("excluded_reason"),
                    "oracle_excluded_reason": oracle.get("excluded_reason"),
                }
            )
            continue
        per_sample_deltas.append(
            {
                "commit_id": commit_id,
                "intent_coverage_delta": _delta(_metric(predicted, "intent_coverage"), _metric(oracle, "intent_coverage")),
                "missing_intent_indicator_delta": _delta(
                    _missing_intent_indicator(predicted),
                    _missing_intent_indicator(oracle),
                ),
                "fallback_indicator_delta": _delta(_fallback_indicator(predicted), _fallback_indicator(oracle)),
                "fallback_level_delta": _delta(_fallback_level(predicted), _fallback_level(oracle)),
                "rejection_indicator_delta": _delta(_rejection_indicator(predicted), _rejection_indicator(oracle)),
                "unsupported_claim_indicator_delta": _delta(
                    _unsupported_claim_indicator(predicted),
                    _unsupported_claim_indicator(oracle),
                ),
                "entity_grounding_precision_delta": _delta(
                    _metric(predicted, "entity_grounding_precision"),
                    _metric(oracle, "entity_grounding_precision"),
                ),
                "background_mention_indicator_delta": _delta(
                    _background_mention_indicator(predicted),
                    _background_mention_indicator(oracle),
                ),
                "format_compliance_delta": _delta(
                    _format_compliance_indicator(predicted),
                    _format_compliance_indicator(oracle),
                ),
            }
        )

    return ConsumerRunComparisonRecord(
        paired_sample_count=len(per_sample_deltas),
        predicted_only_count=len(predicted_only),
        oracle_only_count=len(oracle_only),
        duplicate_commit_ids=[],
        excluded_pairs=excluded_pairs,
        aggregate_predicted_metrics=aggregate_consumer_records(predicted_records),
        aggregate_oracle_metrics=aggregate_consumer_records(oracle_records),
        paired_deltas=_aggregate_deltas(per_sample_deltas),
        per_sample_deltas=per_sample_deltas,
    ).to_dict()


def _index_by_commit_id(rows: list[dict[str, Any]], *, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        commit_id = str(row.get("commit_id") or row.get("sample_id") or "").strip()
        if not commit_id:
            raise ValueError(f"{label} record is missing commit_id/sample_id")
        if commit_id in indexed:
            duplicates.add(commit_id)
        indexed[commit_id] = row
    if duplicates:
        raise ValueError(f"duplicate commit ids in {label} records: {sorted(duplicates)!r}")
    return indexed


def _metric(row: dict[str, Any], name: str) -> float | None:
    verification = dict(row.get("verification", {}))
    if name == "intent_coverage":
        payload = dict(verification.get("slot_coverage", {}))
        value = payload.get("intent_coverage_rate")
    elif name == "entity_grounding_precision":
        payload = dict(verification.get("entity_grounding", {}))
        value = payload.get("entity_grounding_precision")
    else:
        value = None
    return float(value) if value is not None else None


def _missing_intent_indicator(row: dict[str, Any]) -> float | None:
    value = _metric(row, "intent_coverage")
    return None if value is None else float(value < 1.0)


def _fallback_indicator(row: dict[str, Any]) -> float:
    return float(bool(dict(row.get("fallback", {})).get("fallback_used")))


def _fallback_level(row: dict[str, Any]) -> float | None:
    value = dict(row.get("fallback", {})).get("fallback_level")
    return float(value) if value is not None else None


def _rejection_indicator(row: dict[str, Any]) -> float:
    return float(str(row.get("status")) == "rejected")


def _unsupported_claim_indicator(row: dict[str, Any]) -> float:
    payload = dict(dict(row.get("verification", {})).get("unsupported_claims", {}))
    return float(bool(list(payload.get("unsupported_claims", []))))


def _background_mention_indicator(row: dict[str, Any]) -> float:
    payload = dict(dict(row.get("verification", {})).get("background_exclusion", {}))
    return float(bool(list(payload.get("background_mentions", []))))


def _format_compliance_indicator(row: dict[str, Any]) -> float | None:
    payload = dict(dict(row.get("verification", {})).get("format", {}))
    value = payload.get("valid")
    return float(bool(value)) if value is not None else None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _aggregate_deltas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    metrics = [key for key in rows[0] if key != "commit_id"]
    return {
        key: (
            sum(value for value in (row.get(key) for row in rows) if value is not None)
            / len([row for row in rows if row.get(key) is not None])
            if any(row.get(key) is not None for row in rows)
            else None
        )
        for key in metrics
    }
