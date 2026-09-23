from __future__ import annotations

from pathlib import Path

from code.mica.train.validate_stage1_t2_scaleup import (
    build_scaleup_report,
    build_stage1_t2_scaleup_scales,
    build_stage1_t2_scaleup_settings,
    epoch_phase_for_scaleup_setting,
    scaleup_passes_thresholds,
)


def test_scale_runner_builds_scale_a_b_c() -> None:
    scales = {scale["scale_name"]: scale for scale in build_stage1_t2_scaleup_scales()}

    assert scales["scale_a_sanity_reference"]["k1_train"] == 100
    assert scales["scale_b_medium"]["k2_train"] == 300
    assert scales["scale_c_larger"]["k1_dev"] in {125, 200}


def test_each_scale_has_naive_and_t2_settings() -> None:
    settings = {setting["setting_name"]: setting for setting in build_stage1_t2_scaleup_settings()}

    assert set(settings) == {"naive_balanced_mixed", "T2_replay_protected_mixed"}
    assert settings["naive_balanced_mixed"]["uses_replay"] is False
    assert settings["T2_replay_protected_mixed"]["uses_replay"] is True


def test_t2_phase1_excludes_k1_and_phase2_replay_ratio_is_at_least_half() -> None:
    setting = next(
        item for item in build_stage1_t2_scaleup_settings() if item["setting_name"] == "T2_replay_protected_mixed"
    )

    phase1 = epoch_phase_for_scaleup_setting(setting, epoch_index=0)
    phase2 = epoch_phase_for_scaleup_setting(setting, epoch_index=8)

    assert phase1["train_scope"] == "k2_only"
    assert phase1["resolved_lambda_count"] == 0.2
    assert phase1["resolved_lambda_exist"] == 0.2
    assert phase2["train_scope"] == "mixed_with_replay"
    assert phase2["k2_replay_ratio"] >= 0.5
    assert phase2["resolved_lambda_count"] == 0.5
    assert phase2["resolved_lambda_exist"] == 0.5


def test_naive_baseline_uses_mixed_training_without_replay() -> None:
    setting = next(item for item in build_stage1_t2_scaleup_settings() if item["setting_name"] == "naive_balanced_mixed")
    phase = epoch_phase_for_scaleup_setting(setting, epoch_index=0)

    assert phase["train_scope"] == "mixed"
    assert phase["k2_replay_ratio"] == 0.0
    assert setting["uses_replay"] is False


def test_report_records_fallback_reason_and_delta_metrics() -> None:
    rows = [
        {
            "scale_name": "scale_b_medium",
            "setting_name": "naive_balanced_mixed",
            "k2_split_recall_mixed": 0.10,
            "second_slot_gold_recall_mixed": 0.10,
            "unit_accuracy_gain_over_all_one_mixed": 0.01,
            "slot_collapse_rate_mixed": 0.70,
            "count_accuracy_mixed": 0.60,
            "over_split_rate_on_k1_mixed": 0.40,
        },
        {
            "scale_name": "scale_b_medium",
            "setting_name": "T2_replay_protected_mixed",
            "k2_split_recall_mixed": 0.60,
            "second_slot_gold_recall_mixed": 0.45,
            "unit_accuracy_gain_over_all_one_mixed": 0.04,
            "slot_collapse_rate_mixed": 0.20,
            "count_accuracy_mixed": 0.70,
            "over_split_rate_on_k1_mixed": 0.30,
        },
    ]
    payload = build_scaleup_report(
        settings=rows,
        data_audits=[
            {
                "scale_name": "scale_b_medium",
                "fallback_applied": True,
                "fallback_reason": ["relax_random_threshold"],
            }
        ],
        output_root=Path("outputs/not_tracked"),
        seed=42,
    )

    comparison = payload["t2_vs_naive_comparison"]["scale_b_medium"]
    assert comparison["delta_second_slot_gold_recall"] > 0
    assert comparison["delta_slot_collapse_rate"] < 0
    assert payload["data_audits"][0]["fallback_reason"] == ["relax_random_threshold"]


def test_threshold_helper_requires_t2_scaleup_conditions() -> None:
    passing = {
        "k2_split_recall_mixed": 0.50,
        "second_slot_gold_recall_mixed": 0.40,
        "unit_accuracy_gain_over_all_one_mixed": 0.031,
        "slot_collapse_rate_mixed": 0.45,
        "count_accuracy_mixed": 0.55,
        "over_split_rate_on_k1_mixed": 0.45,
    }
    failing = dict(passing, second_slot_gold_recall_mixed=0.39)

    assert scaleup_passes_thresholds(passing) is True
    assert scaleup_passes_thresholds(failing) is False


def test_scaleup_module_stays_stage1_only() -> None:
    source = Path("code/mica/train/validate_stage1_t2_scaleup.py").read_text(encoding="utf-8")

    assert "hard_b" not in source
    assert "RealDomainBinary" not in source
    assert "M weak" not in source
    assert "outputs/**" not in source


def test_runner_resets_torch_seed_for_each_setting() -> None:
    source = Path("code/mica/train/validate_stage1_t2_scaleup.py").read_text(encoding="utf-8")

    assert "torch.manual_seed(seed)" in source
