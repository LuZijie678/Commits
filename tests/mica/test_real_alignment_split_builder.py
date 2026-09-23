from __future__ import annotations

from code.mica.annotation.split_builder import (
    build_alignment_split_manifest,
    check_alignment_benchmark_requirements,
)


def test_build_alignment_split_manifest_tracks_split_counts() -> None:
    rows = [
        {"sample_id": "s1", "split": "train", "annotation_status": "double_annotated"},
        {"sample_id": "s2", "split": "final-test", "annotation_status": "adjudicated"},
    ]

    manifest = build_alignment_split_manifest(rows, {"final_test_split_names": ["final-test"]})

    assert manifest["split_counts"]["train"] == 1
    assert manifest["split_counts"]["final-test"] == 1


def test_check_alignment_benchmark_requirements_returns_preliminary_when_insufficient() -> None:
    rows = [{"sample_id": f"s{i}", "split": "train", "annotation_status": "double_annotated"} for i in range(10)]

    result = check_alignment_benchmark_requirements(
        rows,
        {
            "min_recommended_full_alignment_overall": 300,
            "min_recommended_final_test_aligned": 100,
            "min_recommended_double_annotated": 100,
            "final_test_split_names": ["final-test"],
        },
    )

    assert result["claim_level"] == "preliminary_attribution_only"
    assert result["requirements_met"] is False
