from __future__ import annotations

from code.mica.eval.kmax_coverage import build_kmax_coverage_report


def test_kmax_coverage_report_uses_train_dev_for_selection_and_reports_test_only() -> None:
    rows = [
        {"sample_id": "tr1", "split": "train", "gold_count": 1, "cardinality_label_type": "exact_k1_gold", "source_type": "hard_b"},
        {"sample_id": "tr2", "split": "train", "gold_count": 5, "cardinality_label_type": "exact_k5_gold", "source_type": "manual_real"},
        {"sample_id": "dv1", "split": "dev", "intent_count": 4, "cardinality_label_type": "exact_k4_gold", "source_type": "manual_real"},
        {"sample_id": "ts1", "split": "test", "gold_count": 6, "cardinality_label_type": "exact_k6_gold", "source_type": "manual_real"},
        {"sample_id": "syn1", "split": "train", "intent_k": 2, "source_kind": "strict_synthetic", "cardinality_label_type": "exact_k2_gold"},
        {"sample_id": "cens1", "split": "dev", "cardinality_label_type": "censored_k_ge_2", "source_kind": "m_weak"},
        {"sample_id": "missing", "split": "dev"},
    ]

    report = build_kmax_coverage_report(rows, kmax=4, tau=0.9)

    assert report["status"] == "protocol_defined"
    assert report["selected_Kmax"]["status"] == "implementation_default_not_final_boundary"
    assert report["train_dev_selection_basis"]["sample_count"] == 3
    assert report["train_dev_selection_basis"]["coverage_at_kmax"] == 2 / 3
    assert report["train_dev_selection_basis"]["final_test_used_for_selection"] is False
    assert report["train_dev_selection_basis"]["exact_real_multi_intent_row_count"] == 2
    assert report["coverage_at_Kmax"]["test"]["coverage_at_kmax"] == 0.0
    assert report["coverage_at_Kmax"]["test"]["overflow_rate"] == 1.0
    assert report["missing_count_rows"] == 3
    assert report["eligibility_summary"]["excluded_rows_by_reason"]["synthetic_excluded"] == 1
    assert report["eligibility_summary"]["excluded_rows_by_reason"]["censored_count_excluded"] == 1
    assert report["eligibility_summary"]["excluded_rows_by_reason"]["missing_exact_count"] == 1
    assert report["synthetic_distribution_usage"]["can_alone_justify_Kmax"] is False
    assert report["paper_readiness"] == "not_final_paper_ready_until_exact_real_train_dev_multi_intent_coverage_stats_are_populated_and_frozen"


def test_kmax_coverage_report_marks_missing_stats_without_fake_values() -> None:
    report = build_kmax_coverage_report([{"sample_id": "s1", "split": "train"}], kmax=4)

    assert report["status"] == "protocol_defined_but_stats_not_populated"
    assert report["selected_Kmax"]["status"] == "implementation_default_not_final_boundary"
    assert report["train_dev_selection_basis"]["coverage_at_kmax"] is None
    assert report["paper_readiness"] == "not_final_paper_ready_until_exact_real_train_dev_multi_intent_coverage_stats_are_populated_and_frozen"


def test_kmax_coverage_report_requires_predeclared_tau_before_freeze() -> None:
    rows = [
        {"sample_id": "tr1", "split": "train", "gold_count": 2, "cardinality_label_type": "exact_k2_gold", "source_type": "manual_real"},
        {"sample_id": "dv1", "split": "dev", "gold_count": 4, "cardinality_label_type": "exact_k4_gold", "source_type": "manual_real"},
    ]

    report = build_kmax_coverage_report(rows, kmax=4, tau=None)

    assert report["train_dev_selection_basis"]["coverage_computed"] is True
    assert report["train_dev_selection_basis"]["tau_predeclared"] is False
    assert report["train_dev_selection_basis"]["freeze_supported"] is False
    assert report["selected_Kmax"]["status"] == "implementation_default_not_final_boundary"


def test_kmax_coverage_report_requires_exact_real_multi_intent_rows_for_freeze() -> None:
    rows = [
        {"sample_id": "tr1", "split": "train", "gold_count": 1, "cardinality_label_type": "exact_k1_gold", "source_type": "step1_high_conf_single"},
        {"sample_id": "dv1", "split": "dev", "gold_count": 1, "cardinality_label_type": "exact_k1_gold", "source_type": "hard_b"},
    ]

    report = build_kmax_coverage_report(rows, kmax=4, tau=0.95)

    assert report["status"] == "protocol_defined_but_real_multi_intent_counts_not_populated"
    assert report["train_dev_selection_basis"]["coverage_at_kmax"] == 1.0
    assert report["train_dev_selection_basis"]["exact_real_multi_intent_row_count"] == 0
    assert report["train_dev_selection_basis"]["freeze_supported"] is False
    assert report["selected_Kmax"]["status"] == "implementation_default_not_final_boundary"
