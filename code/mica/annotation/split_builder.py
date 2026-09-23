from __future__ import annotations

from collections import Counter
from typing import Any

from code.mica.annotation.real_alignment_schema import normalize_alignment_annotation


def build_alignment_split_manifest(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    normalized = [normalize_alignment_annotation(row) for row in rows]
    split_counts = Counter(row["split"] for row in normalized)
    status_counts = Counter(row["annotation_status"] for row in normalized)
    final_names = {str(item) for item in spec.get("final_test_split_names", ["final-test"])}
    final_test_count = sum(1 for row in normalized if row["split"] in final_names)
    return {
        "row_count": len(normalized),
        "split_counts": dict(split_counts),
        "annotation_status_counts": dict(status_counts),
        "final_test_count": final_test_count,
    }


def check_alignment_benchmark_requirements(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    manifest = build_alignment_split_manifest(rows, spec)
    normalized = [normalize_alignment_annotation(row) for row in rows]
    final_names = {str(item) for item in spec.get("final_test_split_names", ["final-test"])}
    overall = len({row["sample_id"] for row in normalized})
    final_test = len({row["sample_id"] for row in normalized if row["split"] in final_names})
    double_annotated = len({row["sample_id"] for row in normalized if row["annotation_status"] in {"double_annotated", "adjudicated"}})
    requirements = {
        "overall": overall >= int(spec.get("min_recommended_full_alignment_overall", 300)),
        "final_test": final_test >= int(spec.get("min_recommended_final_test_aligned", 100)),
        "double_annotated": double_annotated >= int(spec.get("min_recommended_double_annotated", 100)),
    }
    requirements_met = all(requirements.values())
    return {
        **manifest,
        "requirements_met": requirements_met,
        "claim_level": "full_alignment_benchmark_ready" if requirements_met else "preliminary_attribution_only",
        "overall_aligned_commit_count": overall,
        "final_test_aligned_commit_count": final_test,
        "double_annotated_commit_count": double_annotated,
        "requirements": requirements,
    }
