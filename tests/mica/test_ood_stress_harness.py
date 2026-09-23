from __future__ import annotations

from code.mica.eval.ood_stress import build_ood_slices, summarize_ood_slices


def test_ood_stress_harness_builds_multiple_slices() -> None:
    rows = [
        {"sample_id": "s1", "repo": "r1", "file_count": 1, "edit_units": [1, 2], "gold_count": 1},
        {"sample_id": "s2", "repo": "r2", "file_count": 4, "edit_units": [1, 2, 3, 4, 5], "gold_count": 3},
    ]

    sliced = build_ood_slices(rows)
    summary = summarize_ood_slices(sliced)

    assert any("diff_size" in item["ood_slice"] for item in sliced)
    assert any("k_ge_3" in item["ood_slice"] for item in sliced)
    assert summary["row_count"] == 2
