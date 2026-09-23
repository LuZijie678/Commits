from __future__ import annotations

from collections import Counter
from typing import Any


def assign_ood_slices(row: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    slices: list[str] = []
    repo = str(row.get("repo", ""))
    if bool(row.get("shared_file", False)) or int(row.get("file_count", 0) or 0) == 1:
        slices.append("shared_file")
    if bool(row.get("cross_project", False)) or repo:
        slices.append("cross_project")
    if row.get("cross_time"):
        slices.append("cross_time")
    file_count = int(row.get("file_count", len(row.get("edit_units", [])) or 0) or 0)
    if file_count <= int(spec.get("file_count_low_max", 1)):
        slices.append("file_count_low")
    elif file_count <= int(spec.get("file_count_medium_max", 3)):
        slices.append("file_count_medium")
    else:
        slices.append("file_count_high")
    diff_size = int(row.get("diff_size", len(row.get("edit_units", [])) or 0) or 0)
    if diff_size <= int(spec.get("diff_size_low_max", 2)):
        slices.append("diff_size_low")
    elif diff_size <= int(spec.get("diff_size_medium_max", 5)):
        slices.append("diff_size_medium")
    else:
        slices.append("diff_size_high")
    if int(row.get("gold_count", 0) or 0) >= 3:
        slices.append("k_ge_3_stress")
    if float(row.get("identifier_overlap", 0.0) or 0.0) >= float(spec.get("identifier_overlap_high_min", 0.6)):
        slices.append("identifier_overlap_high")
    if float(row.get("path_diversity", 0.0) or 0.0) >= float(spec.get("path_diversity_high_min", 2.0)):
        slices.append("path_diversity_high")
    return sorted(set(slices))


def build_ood_slice_manifest(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    manifest_rows = [{"sample_id": row.get("sample_id"), "slices": assign_ood_slices(row, spec)} for row in rows]
    return {"row_count": len(rows), "rows": manifest_rows}


def aggregate_slice_metrics(rows: list[dict[str, Any]], metric_keys: list[str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for slice_name in row.get("slices", []):
            grouped.setdefault(str(slice_name), []).append(row)
    payload: dict[str, Any] = {}
    for slice_name, group_rows in grouped.items():
        payload[slice_name] = {
            key: (sum(float(item.get(key, 0.0)) for item in group_rows) / len(group_rows)) if group_rows else 0.0
            for key in metric_keys
        }
        payload[slice_name]["n"] = len(group_rows)
    return payload


def build_ood_stress_report(slice_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "slice_count": len(slice_metrics),
        "slice_metrics": slice_metrics,
        "thresholds_applied_to_pass_fail": False,
    }


def build_ood_slices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sliced_rows: list[dict[str, Any]] = []
    for row in rows:
        slices = _infer_slices(row)
        for slice_name in slices:
            copied = dict(row)
            copied["ood_slice"] = slice_name
            sliced_rows.append(copied)
    return sliced_rows


def summarize_ood_slices(rows: list[dict[str, Any]]) -> dict[str, Any]:
    slice_counter = Counter(str(row.get("ood_slice", "unspecified")) for row in rows)
    return {
        "row_count": len({str(row.get("sample_id", index)) for index, row in enumerate(rows)}),
        "ood_slice_distribution": dict(slice_counter),
        "readiness_only": False,
    }


def _infer_slices(row: dict[str, Any]) -> list[str]:
    return assign_ood_slices(row, {})
