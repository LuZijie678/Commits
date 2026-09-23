from __future__ import annotations

from code.mica.data.split_guards import (
    assert_no_final_test_in_training,
    check_cross_split_overlap,
    check_forbidden_assets_for_stage,
    summarize_split_usage,
)


def test_final_test_rows_are_flagged_by_split_guard() -> None:
    rows = [
        {"sample_id": "s1", "split": "train"},
        {"sample_id": "s2", "split": "M-final-test"},
    ]

    result = assert_no_final_test_in_training(rows)

    assert result["error_count"] == 1
    assert "M-final-test" in result["forbidden_split_values"]


def test_cross_split_overlap_reports_hard_leakage_and_repo_overlap_warning() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "sha": "a1", "repo": "repo-a"},
        {"sample_id": "s1", "split": "dev", "sha": "a2", "repo": "repo-a"},
        {"sample_id": "s2", "split": "test", "sha": "a1", "repo": "repo-b"},
    ]

    result = check_cross_split_overlap(rows)

    assert result["hard_leakage"]["sample_id_overlap_count"] == 1
    assert result["hard_leakage"]["sha_overlap_count"] == 1
    assert result["repo_overlap_count"] == 1
    assert result["error_count"] == 2
    assert result["warning_count"] == 1


def test_forbidden_training_assets_are_detected_for_stage() -> None:
    registry = {
        "assets": {
            "hard_b_test": {
                "path": "/tmp/hard_b_test.jsonl",
                "stage_use": ["final_eval_only"],
                "forbidden_for_training": True,
            }
        }
    }

    result = check_forbidden_assets_for_stage(registry, stage="stage2_train")

    assert result["error_count"] == 1
    assert result["errors"][0]["code"] == "forbidden_asset_for_stage"


def test_split_usage_summary_counts_rows_per_split() -> None:
    rows = [
        {"sample_id": "s1", "split": "train"},
        {"sample_id": "s2", "split": "train"},
        {"sample_id": "s3", "split": "dev"},
    ]

    result = summarize_split_usage(rows)

    assert result["split_counts"]["train"] == 2
    assert result["row_count"] == 3

