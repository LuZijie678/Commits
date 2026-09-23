from __future__ import annotations

import copy

import pytest

from code.mica.eval.consumer_records import ConsumerRunComparisonRecord
from code.mica.eval.compare_consumer_runs import compare_consumer_runs


def _record(sample_id: str, *, plan_source: str, status: str = "success", fallback_level: int | None = 0) -> dict[str, object]:
    return {
        "schema_version": "mica-consumer-eval-row-v1",
        "sample_id": sample_id,
        "commit_id": sample_id,
        "plan_source": plan_source,
        "status": status,
        "verification_eligible": True,
        "excluded_reason": None,
        "fallback": {"fallback_used": bool(fallback_level), "fallback_level": fallback_level},
        "verification": {
            "slot_coverage": {"intent_coverage_rate": 1.0 if status == "success" else 0.0},
            "unsupported_claims": {"unsupported_claims": [] if status == "success" else ["performance"]},
            "entity_grounding": {"entity_grounding_precision": 1.0 if status == "success" else None},
            "background_exclusion": {"background_mentions": [] if status == "success" else ["lockfile"]},
            "format": {"valid": status == "success"},
        },
    }


def test_compare_consumer_runs_reports_paired_and_unmatched_counts() -> None:
    result = compare_consumer_runs(
        predicted_records=[_record("c1", plan_source="predicted"), _record("c2", plan_source="predicted")],
        oracle_records=[_record("c1", plan_source="oracle"), _record("c3", plan_source="oracle")],
    )

    assert result["paired_sample_count"] == 1
    assert result["predicted_only_count"] == 1
    assert result["oracle_only_count"] == 1


def test_compare_consumer_runs_raises_on_duplicate_commit_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        compare_consumer_runs(
            predicted_records=[_record("c1", plan_source="predicted"), _record("c1", plan_source="predicted")],
            oracle_records=[_record("c1", plan_source="oracle")],
        )


def test_compare_consumer_runs_handles_null_metrics_and_does_not_mutate_inputs() -> None:
    predicted = [_record("c1", plan_source="predicted", status="rejected", fallback_level=None)]
    oracle = [_record("c1", plan_source="oracle")]
    predicted_copy = copy.deepcopy(predicted)
    oracle_copy = copy.deepcopy(oracle)

    result = compare_consumer_runs(predicted_records=predicted, oracle_records=oracle)

    assert result["per_sample_deltas"][0]["entity_grounding_precision_delta"] is None
    assert predicted == predicted_copy
    assert oracle == oracle_copy


def test_compare_consumer_runs_round_trip_record() -> None:
    result = compare_consumer_runs(
        predicted_records=[_record("c1", plan_source="predicted")],
        oracle_records=[_record("c1", plan_source="oracle")],
    )

    reloaded = ConsumerRunComparisonRecord.from_dict(result)

    assert reloaded.to_dict() == result
