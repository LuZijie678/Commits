from __future__ import annotations

from code.mica.reporting import (
    build_stage2_calibration_report,
    build_stage2_tradeoff_report,
    build_stage3_alignment_calibration_report,
)


def test_stage2_and_stage3_report_builders_return_expected_contracts() -> None:
    stage2_tradeoff = build_stage2_tradeoff_report([{"hard_b_fpr": 0.1, "m_recall": 0.8}])
    stage2_calibration = build_stage2_calibration_report([{"mean_abs_gap": 0.2}])
    stage3_alignment = build_stage3_alignment_calibration_report([{"pairwise_f1": 0.7, "ari": 0.5}])

    assert stage2_tradeoff["table_name"] == "stage2_tradeoff"
    assert stage2_calibration["table_name"] == "stage2_calibration"
    assert stage3_alignment["table_name"] == "stage3_alignment_calibration"
    assert stage2_tradeoff["status"] == "protocol_defined"
    assert "advisor_pending" not in stage2_tradeoff
    assert "hard_b_top1_retained_foreground_mass" in stage2_tradeoff["required_columns"]
    assert "hard_b_residual_foreground_mass" in stage2_tradeoff["required_columns"]
    assert "hard_b_background_swallowing_rate" in stage2_tradeoff["required_columns"]
