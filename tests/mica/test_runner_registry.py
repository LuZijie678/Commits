from __future__ import annotations

from code.mica.runners.registry import build_runner_registry_markdown, get_runner_policy, list_mica_runners, validate_runner_policy


def test_runner_registry_lists_expected_runners_and_policies() -> None:
    names = {item["name"] for item in list_mica_runners()}

    assert {
        "run_stage0_protocol_freeze",
        "run_stage1_formal_training",
        "run_stage1_threshold_selection",
        "run_stage1_candidate_validation",
        "run_stage1_official_validation",
        "run_kmax_exact_count_audit",
        "run_stage2_calibration",
        "run_stage3_alignment_calibration",
        "run_stage4_renderer_training",
        "run_message_baseline_generation",
        "run_message_utility_eval",
    } <= names

    policy = get_runner_policy("run_stage2_calibration")
    validation = validate_runner_policy("run_stage2_calibration", policy)
    stage3_policy = get_runner_policy("run_stage3_alignment_calibration")

    assert policy["requires_advisor_approval"] is True
    assert policy["can_update_attribution"] is False
    assert policy["attribution_update_scope"] == "none_core_assignment_frozen"
    assert stage3_policy["can_update_attribution"] is False
    assert stage3_policy["attribution_update_scope"] == "core_assignment_frozen_stage3_plus_adapter_separately_gated"
    assert validation["valid"] is True


def test_runner_registry_markdown_mentions_advisor_gates() -> None:
    text = build_runner_registry_markdown()

    assert "requires_advisor_approval" in text
    assert "run_stage4_renderer_training" in text
    assert "run_message_baseline_generation" in text
