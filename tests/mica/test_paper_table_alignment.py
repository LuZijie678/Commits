from __future__ import annotations

from code.mica.paper_tables.alignment_table import build_alignment_paper_table


def test_build_alignment_paper_table_separates_oracle_and_predicted() -> None:
    table = build_alignment_paper_table(
        [
            {"model_name": "mica", "alignment_mode": "oracle_k", "seed": 1, "pairwise_f1": 0.9, "ari": 0.8, "nmi": 0.7, "bcubed_f1": 0.85, "hunk_micro_f1": 0.88, "count_exact": 1.0, "count_mae": 0.0, "over_segmentation_rate": 0.1, "under_segmentation_rate": 0.0},
            {"model_name": "mica", "alignment_mode": "predicted_k", "seed": 1, "pairwise_f1": 0.7, "ari": 0.6, "nmi": 0.5, "bcubed_f1": 0.65, "hunk_micro_f1": 0.68, "count_exact": 0.8, "count_mae": 0.2, "over_segmentation_rate": 0.2, "under_segmentation_rate": 0.1},
        ]
    )

    assert {row["comparison_group"] for row in table["rows"]} == {"oracle_k", "predicted_k"}
