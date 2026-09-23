from __future__ import annotations

from code.mica.eval.message_utility import build_renderer_ablation_summary, compare_oracle_vs_predicted_rendering


def test_renderer_ablation_compares_oracle_and_predicted_rows() -> None:
    oracle = [{"sample_id": "s1", "covered_intent_fraction": 1.0, "unsupported_term_fraction": 0.0}]
    predicted = [{"sample_id": "s1", "covered_intent_fraction": 0.5, "unsupported_term_fraction": 0.2}]

    comparison = compare_oracle_vs_predicted_rendering(oracle, predicted)
    summary = build_renderer_ablation_summary(predicted)

    assert comparison["paired_count"] == 1
    assert comparison["delta_covered_intent_fraction_mean"] < 0.0
    assert summary["proxy_not_human_eval"] is True

