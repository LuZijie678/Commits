from __future__ import annotations

import pytest

from code.mica.eval.consumer_metrics import aggregate_consumer_records
from code.mica.eval.consumer_stratification import stratify_consumer_records


def _record(
    sample_id: str,
    *,
    status: str = "success",
    verification_eligible: bool = True,
    excluded_reason: str | None = None,
    predicted_k: int = 2,
    gold_k: int | None = None,
    plan_source: str = "predicted",
    fallback_level: int | None = 0,
    decision: str = "decompose",
    evidence_complete: bool = True,
    background_assignment_type: str = "model_assigned_background",
) -> dict[str, object]:
    return {
        "schema_version": "mica-consumer-eval-row-v1",
        "sample_id": sample_id,
        "commit_id": sample_id,
        "status": status,
        "decision": decision,
        "plan_source": plan_source,
        "predicted_k": predicted_k,
        "gold_k": gold_k,
        "verification_eligible": verification_eligible,
        "excluded_reason": excluded_reason,
        "verification": {
            "slot_coverage": {"intent_coverage_rate": 1.0 if status == "success" else 0.0},
            "unsupported_claims": {"unsupported_claims": [] if status == "success" else ["performance"]},
            "entity_grounding": {"entity_grounding_precision": 1.0 if status == "success" else 0.5},
            "background_exclusion": {"background_mentions": [] if status == "success" else ["lockfile"]},
            "format": {"valid": status == "success", "errors": [] if status == "success" else ["subject_too_long"]},
        },
        "fallback": {"fallback_used": bool(fallback_level), "fallback_level": fallback_level},
        "background_contract": {"evidence_complete": evidence_complete, "evidence_incomplete": not evidence_complete},
        "strata": {
            "predicted_k": predicted_k,
            "gold_k": gold_k,
            "decision": decision,
            "plan_source": plan_source,
            "background_contract.evidence_complete": evidence_complete,
            "fallback_level": fallback_level,
            "file_role_composition": "doc+source" if predicted_k > 1 else "source",
            "source_type": "stage1_prediction_adapter",
            "hard_b_flag": False,
            "multi_intent": predicted_k > 1 or (gold_k or 0) > 1,
            "background_assignment_type": background_assignment_type,
        },
    }


def test_aggregate_consumer_records_reports_null_for_empty_denominator() -> None:
    result = aggregate_consumer_records([_record("excluded", verification_eligible=False, excluded_reason="non_decompose")])

    assert result["aggregate_metrics"]["intent_coverage"] is None
    assert result["denominators"]["intent_coverage"]["denominator"] == 0


def test_aggregate_consumer_records_separates_micro_and_macro() -> None:
    records = [
        _record("s1", predicted_k=1, fallback_level=0),
        _record("s2", predicted_k=2, status="rejected", fallback_level=1),
        _record("s3", predicted_k=2, fallback_level=1),
    ]

    result = aggregate_consumer_records(records, macro_group_by="predicted_k")

    assert result["micro"]["success_rate"] != result["macro"]["success_rate"]
    assert result["sample_counts"]["included_count"] == 3


@pytest.mark.parametrize(
    "group_by",
    [
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
    ],
)
def test_stratify_consumer_records_supports_requested_grouping_keys(group_by: str) -> None:
    groups = stratify_consumer_records(
        [
            _record("s1", predicted_k=1, gold_k=1, background_assignment_type="rule_verified_background"),
            _record("s2", predicted_k=2, gold_k=2, background_assignment_type="model_assigned_background"),
        ],
        group_by=group_by,
    )

    assert groups
    assert all(group["group_by"] == group_by for group in groups)


def test_stratify_consumer_records_keeps_excluded_reason_counts() -> None:
    groups = stratify_consumer_records(
        [
            _record("s1", verification_eligible=False, excluded_reason="invalid_plan"),
            _record("s2"),
        ],
        group_by="plan_source",
    )

    predicted_group = next(group for group in groups if group["group_value"] == "predicted")
    assert predicted_group["excluded_count"] == 1
