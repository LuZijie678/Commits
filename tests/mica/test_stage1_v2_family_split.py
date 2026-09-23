from __future__ import annotations

from code.mica.stage1_v2.family_split import (
    assign_atomic_family_and_split_components,
    build_family_safe_synthetic_split,
)
from code.mica.stage1_v2.leakage import audit_stage1_v2_leakage


def _row(sample_id: str, sources: list[str], **extra: object) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "repo": "acme/demo",
        "source_atomic_commit_ids": sources,
        "construction_group": extra.get("construction_group", sample_id),
        "normalized_diff_hash": extra.get("normalized_diff_hash", f"diff::{sample_id}"),
        "edit_unit_fingerprint": extra.get("edit_unit_fingerprint", f"fp::{sample_id}"),
        "pr_id": extra.get("pr_id"),
    }


def test_shared_atomic_source_samples_stay_in_same_split() -> None:
    rows = [
        _row("s1", ["repo@a", "repo@b"]),
        _row("s2", ["repo@b"]),
        _row("s3", ["repo@c"]),
        _row("s4", ["repo@d"]),
    ]

    result = build_family_safe_synthetic_split(rows, split_ratios=(0.5, 0.25, 0.25), split_seed=7)

    split_by_sample = {
        row["sample_id"]: split
        for split, split_rows in result["rows_by_split"].items()
        for row in split_rows
    }
    assert split_by_sample["s1"] == split_by_sample["s2"]


def test_transitive_atomic_components_are_collapsed_into_one_family() -> None:
    rows = [
        _row("s1", ["repo@a", "repo@b"]),
        _row("s2", ["repo@b", "repo@c"]),
        _row("s3", ["repo@c", "repo@d"]),
        _row("s4", ["repo@z"]),
    ]

    assigned = assign_atomic_family_and_split_components(rows)
    family_by_sample = {row["sample_id"]: row["atomic_family_id"] for row in assigned}
    split_component_by_sample = {row["sample_id"]: row["split_component_id"] for row in assigned}

    assert family_by_sample["s1"] == family_by_sample["s2"] == family_by_sample["s3"]
    assert split_component_by_sample["s1"] == split_component_by_sample["s2"] == split_component_by_sample["s3"]
    assert family_by_sample["s4"] != family_by_sample["s1"]


def test_atomic_family_overlap_fails_closed() -> None:
    report = audit_stage1_v2_leakage(
        {
            "train": [_row("s1", ["repo@a"], normalized_diff_hash="diff1", edit_unit_fingerprint="fp1",)],
            "dev": [_row("s2", ["repo@a"], normalized_diff_hash="diff2", edit_unit_fingerprint="fp2",)],
        }
    )

    assert report["leakage_clean"] is False
    assert report["list_overlap"]["atomic_source_overlap"]["overlap_count"] == 1


def test_normalized_diff_overlap_fails_closed() -> None:
    report = audit_stage1_v2_leakage(
        {
            "train": [_row("s1", ["repo@a"], normalized_diff_hash="same-diff", edit_unit_fingerprint="fp1")],
            "synthetic_control_test": [_row("s2", ["repo@b"], normalized_diff_hash="same-diff", edit_unit_fingerprint="fp2")],
        }
    )

    assert report["leakage_clean"] is False
    assert report["scalar_overlap"]["normalized_diff_overlap"]["overlap_count"] == 1
