from __future__ import annotations

from pathlib import Path

from code.mica.train.compare_stage1_candidate_schedules import (
    build_candidate_comparison_report,
    build_candidate_schedule_settings,
    build_comparison_scales,
    candidate_passes_thresholds,
    choose_candidate_schedule,
    summarize_schedule_runs,
)


def _row(schedule: str, seed: int, *, passed: bool, second: float, unit_gain: float, collapse: float) -> dict[str, float | int | str | bool]:
    return {
        "seed": seed,
        "schedule_name": schedule,
        "k2_split_recall_mixed": 0.70 if passed else 0.20,
        "second_slot_gold_recall_mixed": second,
        "unit_accuracy_gain_over_all_one_mixed": unit_gain,
        "slot_collapse_rate_mixed": collapse,
        "count_accuracy_mixed": 0.80 if passed else 0.40,
        "over_split_rate_on_k1_mixed": 0.20 if passed else 0.80,
    }


def test_runner_builds_only_naive_and_t2() -> None:
    settings = {setting["setting_name"]: setting for setting in build_candidate_schedule_settings()}

    assert set(settings) == {"naive_balanced_mixed", "T2_replay_protected_mixed"}
    assert settings["naive_balanced_mixed"]["uses_replay"] is False
    assert settings["T2_replay_protected_mixed"]["uses_replay"] is True


def test_scale_c_is_primary_comparison_scale() -> None:
    scales = build_comparison_scales(include_scale_b=False)

    assert len(scales) == 1
    assert scales[0]["scale_name"] == "scale_c_larger"
    assert scales[0]["k1_train"] == 500
    assert scales[0]["k2_dev"] == 125


def test_pass_rate_and_summary_statistics_are_computed() -> None:
    rows = [
        _row("naive_balanced_mixed", 13, passed=True, second=0.50, unit_gain=0.08, collapse=0.10),
        _row("naive_balanced_mixed", 42, passed=False, second=0.30, unit_gain=0.02, collapse=0.50),
        _row("naive_balanced_mixed", 2026, passed=True, second=0.70, unit_gain=0.10, collapse=0.20),
    ]

    summary = summarize_schedule_runs(rows)

    assert summary["naive_balanced_mixed"]["pass_count"] == 2
    assert summary["naive_balanced_mixed"]["pass_rate"] == 2 / 3
    metric = summary["naive_balanced_mixed"]["metrics"]["second_slot_gold_recall_mixed"]
    assert metric["mean"] == 0.5
    assert metric["min"] == 0.30
    assert metric["max"] == 0.70
    assert "std" in metric


def test_candidate_judgment_selects_naive_when_it_dominates() -> None:
    summary = {
        "naive_balanced_mixed": {
            "pass_rate": 1.0,
            "metrics": {
                "second_slot_gold_recall_mixed": {"mean": 0.55, "std": 0.01},
                "unit_accuracy_gain_over_all_one_mixed": {"mean": 0.09, "std": 0.01},
                "slot_collapse_rate_mixed": {"mean": 0.10, "std": 0.01},
            },
        },
        "T2_replay_protected_mixed": {
            "pass_rate": 0.67,
            "metrics": {
                "second_slot_gold_recall_mixed": {"mean": 0.45, "std": 0.01},
                "unit_accuracy_gain_over_all_one_mixed": {"mean": 0.06, "std": 0.01},
                "slot_collapse_rate_mixed": {"mean": 0.20, "std": 0.01},
            },
        },
    }

    judgment = choose_candidate_schedule(summary)

    assert judgment["candidate_schedule_validated"] == "naive"
    assert judgment["next_step"] == "freeze naive larger-scale Stage 1 candidate protocol"


def test_candidate_judgment_reports_unstable_when_both_pass_without_dominance() -> None:
    summary = {
        "naive_balanced_mixed": {
            "pass_rate": 0.67,
            "metrics": {
                "second_slot_gold_recall_mixed": {"mean": 0.50, "std": 0.20},
                "unit_accuracy_gain_over_all_one_mixed": {"mean": 0.05, "std": 0.02},
                "slot_collapse_rate_mixed": {"mean": 0.20, "std": 0.12},
            },
        },
        "T2_replay_protected_mixed": {
            "pass_rate": 0.67,
            "metrics": {
                "second_slot_gold_recall_mixed": {"mean": 0.51, "std": 0.20},
                "unit_accuracy_gain_over_all_one_mixed": {"mean": 0.05, "std": 0.02},
                "slot_collapse_rate_mixed": {"mean": 0.19, "std": 0.12},
            },
        },
    }

    judgment = choose_candidate_schedule(summary)

    assert judgment["candidate_schedule_validated"] == "unstable"


def test_candidate_pass_thresholds_match_scaleup_gate() -> None:
    passing = {
        "k2_split_recall_mixed": 0.50,
        "second_slot_gold_recall_mixed": 0.40,
        "unit_accuracy_gain_over_all_one_mixed": 0.031,
        "slot_collapse_rate_mixed": 0.45,
        "count_accuracy_mixed": 0.55,
        "over_split_rate_on_k1_mixed": 0.45,
    }
    failing = dict(passing, unit_accuracy_gain_over_all_one_mixed=0.03)

    assert candidate_passes_thresholds(passing) is True
    assert candidate_passes_thresholds(failing) is False


def test_report_contains_summary_and_stage1_only_flags() -> None:
    rows = [
        _row("naive_balanced_mixed", 42, passed=True, second=0.55, unit_gain=0.08, collapse=0.10),
        _row("T2_replay_protected_mixed", 42, passed=False, second=0.30, unit_gain=0.02, collapse=0.50),
    ]
    payload = build_candidate_comparison_report(
        runs=rows,
        scale_audits=[{"scale_name": "scale_c_larger", "medium_candidate_count_available": 3599}],
        seeds=[42],
        seed_count_downgraded=True,
        downgrade_reason="test runtime",
        output_root=Path("outputs/not_tracked"),
    )

    assert payload["uses_only_stage1_sources"] is True
    assert payload["uses_forbidden_stage2_sources"] is False
    assert payload["seed_count_downgraded"] is True
    assert "mean" in payload["schedule_summary"]["naive_balanced_mixed"]["metrics"]["k2_split_recall_mixed"]


def test_comparison_module_stays_stage1_only() -> None:
    source = Path("code/mica/train/compare_stage1_candidate_schedules.py").read_text(encoding="utf-8")

    assert "hard_b" not in source
    assert "RealDomainBinary" not in source
    assert "M weak" not in source
    assert "outputs/**" not in source
