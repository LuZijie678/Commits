from __future__ import annotations

from code.mica.paper_tables.ablation_table import build_ablation_paper_table


def test_build_ablation_table_preserves_pending_rows() -> None:
    table = build_ablation_paper_table(
        [
            {"variant_name": "full_mica_v3", "status": "measured", "pairwise_f1": 0.8},
            {"variant_name": "direct_generation_no_intent_plan", "status": "pending_experiment"},
        ]
    )

    assert table["rows"][1]["status"] == "pending_experiment"
    assert table["rows"][1]["metrics"] == {}
