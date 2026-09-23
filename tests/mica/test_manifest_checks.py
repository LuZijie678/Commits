from __future__ import annotations

from code.mica.eval.manifest_checks import (
    check_edit_units_compatibility,
    check_prediction_compatibility,
    check_stage1_manifest_compatibility,
    summarize_split_distribution,
)


def test_manifest_check_detects_duplicate_and_cross_split_overlap() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "gold_count": 1, "source_kind": "atomic_k1", "repo": "r1", "sha": "a1"},
        {"sample_id": "s2", "split": "train", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "r1", "sha": "a2", "synthetic_id": "syn2"},
        {"sample_id": "s2", "split": "dev", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "r2", "sha": "a3", "synthetic_id": "syn2"},
    ]
    protocol_spec = {"repo_overlap_allowed_for_stage1_synthetic": True}

    result = check_stage1_manifest_compatibility(rows, protocol_spec)

    assert result["compatibility_checked"] is True
    assert result["hard_leakage"]["sample_id_overlap_count"] == 1
    assert result["hard_leakage"]["synthetic_id_overlap_count"] == 1
    assert result["training_executed"] is False
    assert result["stage2_allowed"] is False


def test_manifest_check_warns_for_repo_overlap_when_allowed() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "same/repo", "sha": "a1", "synthetic_id": "syn1"},
        {"sample_id": "s2", "split": "dev", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "same/repo", "sha": "a2", "synthetic_id": "syn2"},
    ]
    protocol_spec = {"repo_overlap_allowed_for_stage1_synthetic": True}

    result = check_stage1_manifest_compatibility(rows, protocol_spec)

    warning_codes = {item["code"] for item in result["warnings"]}
    error_codes = {item["code"] for item in result["errors"]}
    assert "repo_overlap_detected" in warning_codes
    assert "repo_overlap_forbidden" not in error_codes


def test_manifest_check_errors_when_repo_overlap_forbidden() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "same/repo", "sha": "a1", "synthetic_id": "syn1"},
        {"sample_id": "s2", "split": "test", "gold_count": 2, "source_kind": "synthetic_k2", "repo": "same/repo", "sha": "a2", "synthetic_id": "syn2"},
    ]
    protocol_spec = {"repo_overlap_allowed_for_stage1_synthetic": False}

    result = check_stage1_manifest_compatibility(rows, protocol_spec)
    assert "repo_overlap_forbidden" in {item["code"] for item in result["errors"]}


def test_manifest_check_reports_missing_required_fields() -> None:
    rows = [{"sample_id": "s1", "split": "train"}]
    result = check_stage1_manifest_compatibility(rows, {"repo_overlap_allowed_for_stage1_synthetic": True})
    assert "missing_required_field_gold_count" in {item["code"] for item in result["errors"]}
    assert "missing_required_field_source_kind" in {item["code"] for item in result["errors"]}


def test_split_distribution_counts_k1_k2() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "gold_count": 1},
        {"sample_id": "s2", "split": "train", "gold_count": 2},
        {"sample_id": "s3", "split": "dev", "gold_count": 2},
    ]
    summary = summarize_split_distribution(rows)
    assert summary["split_counts"]["train"] == 2
    assert summary["count_distribution_by_split"]["train"]["1"] == 1
    assert summary["count_distribution_by_split"]["train"]["2"] == 1


def test_prediction_and_edit_unit_compatibility_basic_checks() -> None:
    prediction_rows = [{"sample_id": "s1", "predicted_count": 1, "active_slots": [], "unit_to_slot": {}}]
    edit_unit_rows = [{"sample_id": "s1", "edit_units": [{"unit_id": "u1"}]}]

    prediction_summary = check_prediction_compatibility(prediction_rows)
    edit_unit_summary = check_edit_units_compatibility(edit_unit_rows)

    assert prediction_summary["compatibility_checked"] is True
    assert edit_unit_summary["compatibility_checked"] is True
