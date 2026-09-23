from __future__ import annotations

from code.mica.stage1_v2.real_count import (
    build_real_count_annotation_queue,
    build_real_count_kmax_asset,
    summarize_real_count_agreement,
)


def test_real_count_queue_keeps_exact_k_pending() -> None:
    queue = build_real_count_annotation_queue(
        [
            {"sample_id": "hb1", "repo": "acme/demo", "sha": "aaa", "source_type": "hard_b", "current_weak_label": "exact_k1_gold"},
            {"sample_id": "syn1", "repo": "acme/demo", "sha": "bbb", "source_type": "strict_synthetic", "current_weak_label": "exact_k2_gold"},
        ],
        guideline_version="real-count-guideline-v1",
        annotation_version="v1",
    )

    assert queue["row_count"] == 2
    assert all(row["annotation_status"] == "pending" for row in queue["rows"])
    assert all(row["adjudicated_exact_k"] is None for row in queue["rows"])


def test_synthetic_and_censored_rows_cannot_enter_real_count_kmax_asset() -> None:
    result = build_real_count_kmax_asset(
        [
            {
                "sample_id": "hb1",
                "commit_id": "aaa",
                "repository": "acme/demo",
                "split_candidate": "train",
                "source_type": "hard_b",
                "current_weak_label": "exact_k1_gold",
                "annotation_status": "adjudicated",
                "adjudicated_exact_k": 1,
                "annotator_a_id": "ann-a",
                "annotator_b_id": "ann-b",
                "adjudicator_id": "adj-1",
                "leakage_group": "repo::aaa",
                "normalized_diff_hash": "diff-a",
            },
            {
                "sample_id": "mw1",
                "commit_id": "bbb",
                "repository": "acme/demo",
                "split_candidate": "dev",
                "source_type": "m_weak",
                "current_weak_label": "censored_k_ge_2",
                "annotation_status": "adjudicated",
                "adjudicated_exact_k": 2,
                "annotator_a_id": "ann-a",
                "annotator_b_id": "ann-b",
                "adjudicator_id": "adj-1",
                "leakage_group": "repo::bbb",
                "normalized_diff_hash": "diff-b",
            },
            {
                "sample_id": "syn1",
                "commit_id": "ccc",
                "repository": "acme/demo",
                "split_candidate": "train",
                "source_type": "strict_synthetic",
                "current_weak_label": "exact_k2_gold",
                "annotation_status": "adjudicated",
                "adjudicated_exact_k": 2,
                "annotator_a_id": "ann-a",
                "annotator_b_id": "ann-b",
                "adjudicator_id": "adj-1",
                "leakage_group": "repo::ccc",
                "normalized_diff_hash": "diff-c",
            },
        ],
        tau=0.95,
    )

    assert result["eligible_row_count"] == 1
    assert result["excluded_rows_by_reason"]["censored_label"] == 1
    assert result["excluded_rows_by_reason"]["excluded_source_type"] == 1


def test_real_count_agreement_reports_weighted_kappa() -> None:
    summary = summarize_real_count_agreement(
        [
            {"annotator_a_count": 1, "annotator_b_count": 1, "annotation_status": "double_annotated"},
            {"annotator_a_count": 2, "annotator_b_count": 3, "annotation_status": "adjudicated"},
            {"annotator_a_count": 4, "annotator_b_count": 4, "annotation_status": "double_annotated"},
        ]
    )

    assert summary["double_annotated_count"] == 3
    assert summary["count_agreement_rate"] < 1.0
    assert summary["weighted_kappa"] is not None
