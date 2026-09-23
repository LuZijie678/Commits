from __future__ import annotations

from code.mica.paper_tables.real_domain_table import (
    build_real_domain_paper_table,
    build_real_domain_selective_paper_table,
    build_real_domain_split_paper_table,
)


def test_build_real_domain_paper_table_groups_seed_rows() -> None:
    table = build_real_domain_paper_table(
        [
            {"model_name": "mica", "split": "test", "seed": 1, "auroc": 0.8, "auprc": 0.7, "balanced_accuracy": 0.75, "hard_b_fpr": 0.2, "m_recall": 0.65, "ece": 0.1},
            {"model_name": "mica", "split": "test", "seed": 2, "auroc": 0.9, "auprc": 0.8, "balanced_accuracy": 0.8, "hard_b_fpr": 0.25, "m_recall": 0.7, "ece": 0.08},
        ]
    )

    assert table["table_name"] == "real_domain_main"
    assert table["rows"][0]["metrics"]["auroc"]["value"] == 0.85
    assert table["rows"][0]["metrics"]["hard_b_fpr"]["higher_is_better"] is False


def test_build_real_domain_split_and_selective_tables() -> None:
    split_table = build_real_domain_split_paper_table(
        [{"model_name": "mica", "split": "test", "auroc": 0.9, "auprc": 0.8, "balanced_accuracy": 0.75, "ece": 0.1, "hard_b_fpr": 0.2}]
    )
    selective_table = build_real_domain_selective_paper_table(
        [
            {
                "model_name": "mica",
                "split": "test",
                "coverage": 0.8,
                "risk_at_coverage": 0.1,
                "aurc": 0.2,
                "abstention_precision": 0.9,
                "false_abstention_on_in_scope": 0.05,
                "missed_overflow_rate": 0.1,
            }
        ]
    )

    assert split_table["table_name"] == "real_domain_split"
    assert selective_table["table_name"] == "real_domain_selective"
    assert selective_table["rows"][0]["metrics"]["risk_at_coverage"]["higher_is_better"] is False
