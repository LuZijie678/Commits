from __future__ import annotations

import pytest

from code.mica.eval.baseline_registry import (
    assert_baseline_implemented_before_run,
    get_baseline_status,
    list_baselines,
)


def test_baseline_registry_lists_implemented_and_pending_baselines() -> None:
    names = {item["name"] for item in list_baselines()}

    assert {"all_one", "file_path", "random_gold_k", "size_heuristic_count"} <= names
    assert {"flat_classifier", "no_slot_decoder", "direct_generation", "llm_prompting", "pretrained_generation"} <= names


def test_external_reference_generation_baselines_are_registered_as_message_utility() -> None:
    llm_prompting = get_baseline_status("llm_prompting")
    pretrained_generation = get_baseline_status("pretrained_generation")

    assert llm_prompting["implemented"] is True
    assert llm_prompting["benchmark_domain"] == "message_utility"
    assert llm_prompting["execution_mode"] == "external_api"
    assert pretrained_generation["implemented"] is True
    assert pretrained_generation["benchmark_domain"] == "message_utility"
    assert pretrained_generation["execution_mode"] == "external_api"
    assert_baseline_implemented_before_run("llm_prompting")
    assert_baseline_implemented_before_run("pretrained_generation")


def test_implemented_baselines_are_allowed() -> None:
    assert get_baseline_status("all_one")["implemented"] is True
    assert get_baseline_status("flat_classifier")["implemented"] is True
    assert get_baseline_status("no_slot_decoder")["implemented"] is True
    assert get_baseline_status("direct_generation")["implemented"] is True
    assert_baseline_implemented_before_run("all_one")
    assert_baseline_implemented_before_run("flat_classifier")
    assert_baseline_implemented_before_run("no_slot_decoder")
    assert_baseline_implemented_before_run("direct_generation")
