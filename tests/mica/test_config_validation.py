from __future__ import annotations

from code.mica.config_validation import (
    validate_eval_spec,
    validate_stage2_spec,
    validate_stage3_spec,
    validate_stage4_spec,
    validate_threshold_spec,
)


def test_validate_stage2_spec_checks_required_guards() -> None:
    spec = {
        "advisor_stage2_approved": False,
        "m_final_test_forbidden": True,
        "hard_b_test_forbidden": True,
        "strict_replay_required": True,
        "m_weak_label_semantics": "censored_k_ge_2",
    }

    result = validate_stage2_spec(spec)

    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_stage3_stage4_and_eval_specs() -> None:
    stage3 = validate_stage3_spec(
        {
            "advisor_stage3_approved": False,
            "m_final_test_forbidden": True,
            "freeze_base_encoder": True,
        }
    )
    stage4 = validate_stage4_spec(
        {
            "advisor_stage4_approved": False,
            "advisor_stage4_trainable_renderer_approved": False,
            "stage4_scope": "deterministic_evidence_locked_renderer",
            "trainable_renderer_main_result": False,
            "attribution_frozen_required": True,
            "renderer_updates_attribution": False,
            "renderer_reads_only_plan_and_assigned_evidence": True,
            "raw_full_diff_forbidden_as_ungrounded_context": True,
        }
    )
    eval_result = validate_eval_spec(
        {
            "stage": "eval_alignment",
            "final_test_eval_only": True,
            "no_threshold_tuning_on_final_test": True,
        }
    )

    assert stage3["valid"] is True
    assert stage4["valid"] is True
    assert eval_result["valid"] is True


def test_validate_threshold_spec_accepts_candidate_threshold_payload() -> None:
    result = validate_threshold_spec(
        {
            "threshold_status": "candidate_sanity_thresholds_pending_advisor_confirmation",
            "k2_split_recall_min": 0.5,
            "second_slot_gold_recall_min": 0.4,
        }
    )

    assert result["valid"] is True


def test_validate_threshold_spec_requires_approved_version_for_frozen_thresholds() -> None:
    result = validate_threshold_spec(
        {
            "threshold_status": "frozen_dev_thresholds_v1",
            "k2_split_recall_min": 0.5,
            "second_slot_gold_recall_min": 0.4,
        }
    )

    assert result["valid"] is False
    assert "frozen threshold spec requires approved_threshold_version" in result["errors"]
