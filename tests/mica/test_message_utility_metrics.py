from __future__ import annotations

from code.mica.eval.message_utility import extra_intent_rate, hallucination_proxy, intent_coverage, missing_intent_rate


def test_intent_coverage_uses_plan_subjects_as_proxy() -> None:
    plan = {
        "sample_id": "s1",
        "intents": [
            {"subject": "auth"},
            {"subject": "token"},
        ],
    }
    result = intent_coverage(plan, "update auth and token validation")

    assert result["covered_intent_fraction"] == 1.0
    assert result["proxy_only"] is True


def test_missing_and_extra_intent_rate_are_computable() -> None:
    rows = [
        {"intent_count": 2, "covered_intent_fraction": 0.5, "extra_intent_fraction": 0.0},
        {"intent_count": 1, "covered_intent_fraction": 1.0, "extra_intent_fraction": 1.0},
    ]

    assert missing_intent_rate(rows)["missing_intent_rate"] == 0.25
    assert extra_intent_rate(rows)["extra_intent_rate"] == 0.5


def test_hallucination_proxy_stays_marked_as_proxy() -> None:
    result = hallucination_proxy("update auth and cache", ["auth"])

    assert result["proxy_only"] is True
    assert result["unsupported_term_fraction"] > 0.0
