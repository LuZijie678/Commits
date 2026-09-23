from __future__ import annotations

from code.mica.paper_tables.metric_registry import list_metric_definitions, normalize_metric_key, validate_eval_metrics_against_paper_tables


def test_metric_registry_normalizes_known_aliases_and_validates_proxy_flags() -> None:
    assert normalize_metric_key("covered_intent_fraction") == "intent_coverage"
    assert normalize_metric_key("specificity_proxy") == "specificity_proxy"

    payload = {
        "intent_coverage": 0.8,
        "missing_intent_rate": 0.1,
        "extra_intent_rate": 0.1,
        "hallucination_proxy": 0.2,
        "faithfulness_proxy": 0.7,
        "specificity_proxy": 0.6,
        "proxy_not_human_eval": True,
    }
    result = validate_eval_metrics_against_paper_tables(payload, "message_utility_main")

    assert result["valid"] is True
    assert "message_utility_main" in list_metric_definitions()


def test_metric_registry_rejects_unknown_primary_metrics() -> None:
    result = validate_eval_metrics_against_paper_tables({"foo_score": 1.0}, "alignment_main")

    assert result["valid"] is False
    assert "unknown_metric_foo_score" in result["errors"]

