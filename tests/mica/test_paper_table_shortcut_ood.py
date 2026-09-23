from __future__ import annotations

from code.mica.paper_tables.shortcut_ood_table import build_shortcut_ood_paper_table


def test_build_shortcut_ood_table_keeps_slice_metrics() -> None:
    table = build_shortcut_ood_paper_table(
        [
            {"slice": "path_masked", "pairwise_f1": 0.7, "delta_pairwise_f1": -0.1},
            {"slice": "cross_project", "pairwise_f1": 0.6, "delta_pairwise_f1": -0.2},
        ]
    )

    assert table["rows"][0]["comparison_group"] == "shortcut_ood"
    assert table["rows"][0]["metrics"]["delta_pairwise_f1"]["higher_is_better"] is True
