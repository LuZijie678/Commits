from __future__ import annotations

from code.mica.eval.baseline_metrics import (
    direct_generation_baseline_placeholder,
    llm_prompting_baseline_placeholder,
)


def test_generation_and_llm_baseline_placeholders_do_not_pretend_to_be_implemented() -> None:
    for payload in (
        direct_generation_baseline_placeholder(),
        llm_prompting_baseline_placeholder(),
    ):
        assert payload["implemented"] is True
        assert payload["executed"] is False
        assert payload["status"] == "not_run_in_this_stage"
        assert payload["benchmark_domain"] == "message_utility"
