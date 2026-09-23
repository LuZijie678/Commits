from __future__ import annotations

from code.mica.release_decision import decide_release


def test_release_decision_decomposes_below_dev_frozen_threshold() -> None:
    decision = decide_release(risk_score=0.2, threshold=0.5)

    assert decision.decision == "decompose"
    assert decision.covered is True
    assert decision.abstention_reason is None
    assert decision.diagnostics["threshold_selection_split"] == "dev_only"
    assert decision.diagnostics["final_test_tuning"] == "forbidden"
    assert decision.diagnostics["single_operating_point_available"] is True
    assert decision.diagnostics["threshold_state"] == "dev_frozen"


def test_release_decision_without_threshold_reports_curve_only() -> None:
    decision = decide_release(risk_score=0.2, threshold=None)

    assert decision.decision == "coverage_risk_curve_only"
    assert decision.covered is False
    assert decision.threshold is None
    assert decision.abstention_reason == "dev_frozen_threshold_missing"
    assert decision.diagnostics["single_operating_point_available"] is False
    assert decision.diagnostics["threshold_state"] == "values_to_be_populated_by_dev_calibration_script"


def test_release_decision_abstains_above_threshold_without_overflow_labels() -> None:
    decision = decide_release(
        risk_score=0.8,
        threshold=0.5,
        overflow_evidence=["k_over_capacity"],
        overflow_labels_available=False,
    )

    assert decision.decision == "abstain"
    assert decision.covered is False
    assert decision.overflow_evidence == ["k_over_capacity"]
    assert decision.abstention_reason == "selective_risk_above_dev_frozen_threshold"
    assert decision.diagnostics["mvp_reject_option"] == "selective_abstention"


def test_release_decision_only_outputs_overflow_when_labels_are_available() -> None:
    decision = decide_release(
        risk_score=0.2,
        threshold=0.5,
        overflow_evidence=["manual_out_of_scope_label"],
        overflow_labels_available=True,
    )

    assert decision.decision == "overflow"
    assert decision.covered is False
    assert decision.diagnostics["overflow_labels_available"] is True
    assert decision.diagnostics["mvp_reject_option"] == "semantic_overflow_allowed"
