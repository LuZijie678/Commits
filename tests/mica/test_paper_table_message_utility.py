from __future__ import annotations

from code.mica.paper_tables.message_utility_table import build_message_utility_paper_table


def test_build_message_utility_table_marks_proxy_metrics() -> None:
    table = build_message_utility_paper_table(
        [
            {
                "model_name": "det",
                "rendering_mode": "predicted_slots",
                "seed": 1,
                "intent_coverage": 0.8,
                "missing_intent_rate": 0.2,
                "extra_intent_rate": 0.1,
                "hallucination_proxy": 0.05,
                "faithfulness_proxy": 0.9,
                "specificity": 0.7,
            },
            {
                "model_name": "det",
                "rendering_mode": "oracle_slots",
                "seed": 1,
                "intent_coverage": 1.0,
                "missing_intent_rate": 0.0,
                "extra_intent_rate": 0.0,
                "hallucination_proxy": 0.0,
                "faithfulness_proxy": 1.0,
                "specificity": 0.8,
            },
        ]
    )

    row = table["rows"][0]
    assert row["proxy_not_human_eval"] is True
    assert row["metrics"]["hallucination_proxy"]["is_proxy_metric"] is True
    assert {row["comparison_group"] for row in table["rows"]} == {"oracle_slots", "predicted_slots"}
