from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ReleaseDecision:
    decision: str
    risk_score: float
    threshold: float | None
    covered: bool
    overflow_evidence: list[str]
    abstention_reason: str | None
    diagnostics: dict[str, Any]


def decide_release(
    *,
    risk_score: float,
    threshold: float | None,
    overflow_evidence: list[str] | None = None,
    overflow_labels_available: bool = False,
    abstention_reason: str | None = None,
) -> ReleaseDecision:
    """Apply the frozen MICA-v3 selective release protocol for one sample."""
    evidence = [str(item) for item in (overflow_evidence or []) if str(item)]
    risk_value = float(risk_score)
    threshold_value = None if threshold is None else float(threshold)
    if threshold_value is None:
        return ReleaseDecision(
            decision="coverage_risk_curve_only",
            risk_score=risk_value,
            threshold=None,
            covered=False,
            overflow_evidence=evidence,
            abstention_reason=abstention_reason or "dev_frozen_threshold_missing",
            diagnostics={
                "release_protocol": "coverage_risk_curve_only_no_dev_frozen_threshold",
                "decision_schema": "decompose_abstain_overflow",
                "threshold_selection_split": "dev_only",
                "final_test_tuning": "forbidden",
                "overflow_labels_available": bool(overflow_labels_available),
                "mvp_reject_option": "selective_abstention" if not overflow_labels_available else "semantic_overflow_allowed",
                "overflow_evidence_present": bool(evidence),
                "single_operating_point_available": False,
                "threshold_state": "values_to_be_populated_by_dev_calibration_script",
            },
        )
    high_risk = risk_value > threshold_value

    if evidence and overflow_labels_available:
        decision = "overflow"
        covered = False
        reason = abstention_reason
    elif high_risk:
        decision = "abstain"
        covered = False
        reason = abstention_reason or _default_abstention_reason(risk_value, threshold_value)
    else:
        decision = "decompose"
        covered = True
        reason = None

    return ReleaseDecision(
        decision=decision,
        risk_score=risk_value,
        threshold=threshold_value,
        covered=covered,
        overflow_evidence=evidence,
        abstention_reason=reason,
        diagnostics={
            "release_protocol": "dev_frozen_threshold_selective_release",
            "decision_schema": "decompose_abstain_overflow",
            "threshold_selection_split": "dev_only",
            "final_test_tuning": "forbidden",
            "overflow_labels_available": bool(overflow_labels_available),
            "mvp_reject_option": "selective_abstention" if not overflow_labels_available else "semantic_overflow_allowed",
            "overflow_evidence_present": bool(evidence),
            "single_operating_point_available": True,
            "threshold_state": "dev_frozen",
        },
    )


def _default_abstention_reason(risk_score: float, threshold: float) -> str:
    if risk_score > threshold:
        return "selective_risk_above_dev_frozen_threshold"
    return "none"
