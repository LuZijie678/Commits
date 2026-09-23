from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize_split_distribution(manifest_rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts: Counter[str] = Counter()
    count_distribution_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    k1_count = 0
    k2_count = 0
    for row in manifest_rows:
        split = str(row.get("split", "missing"))
        split_counts[split] += 1
        gold_count = row.get("gold_count")
        if gold_count is not None:
            count_distribution_by_split[split][str(gold_count)] += 1
            if int(gold_count) == 1:
                k1_count += 1
            if int(gold_count) == 2:
                k2_count += 1
    return {
        "split_counts": dict(split_counts),
        "count_distribution_by_split": {split: dict(counter) for split, counter in count_distribution_by_split.items()},
        "k1_count": k1_count,
        "k2_count": k2_count,
    }


def check_stage1_manifest_compatibility(manifest_rows: list[dict[str, Any]], protocol_spec: dict[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    required_fields = ("sample_id", "split", "gold_count", "source_kind")
    for field in required_fields:
        if any(field not in row for row in manifest_rows):
            errors.append({"code": f"missing_required_field_{field}", "message": f"At least one manifest row is missing `{field}`."})

    split_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest_rows:
        split_buckets[str(row.get("split", "missing"))].append(row)

    hard_sample_overlap, hard_sha_overlap, hard_synthetic_overlap = _cross_split_overlap_counts(split_buckets)
    duplicate_sample_id_count = _duplicate_count([str(row.get("sample_id")) for row in manifest_rows if row.get("sample_id") is not None])
    duplicate_sha_count = _duplicate_count([str(row.get("sha")) for row in manifest_rows if row.get("sha") not in {None, ""}])
    duplicate_synthetic_id_count = _duplicate_count([str(row.get("synthetic_id")) for row in manifest_rows if row.get("synthetic_id") not in {None, ""}])

    repo_overlap_count = _cross_split_overlap_generic(split_buckets, "repo")
    if repo_overlap_count > 0:
        warnings.append({"code": "repo_overlap_detected", "message": f"Repo overlap detected across splits: {repo_overlap_count}"})
        if protocol_spec.get("repo_overlap_allowed_for_stage1_synthetic") is False:
            errors.append({"code": "repo_overlap_forbidden", "message": "Repo overlap is forbidden by protocol spec."})

    missing_field_stats = {
        "repo_missing_count": sum(1 for row in manifest_rows if not row.get("repo")),
        "sha_missing_count": sum(1 for row in manifest_rows if not row.get("sha")),
        "synthetic_id_missing_count": sum(1 for row in manifest_rows if not row.get("synthetic_id")),
    }

    summary = summarize_split_distribution(manifest_rows)
    return {
        "compatibility_checked": True,
        "official_validation_executed": False,
        "training_executed": False,
        "stage2_allowed": False,
        "hard_leakage": {
            "sample_id_overlap_count": hard_sample_overlap,
            "sha_overlap_count": hard_sha_overlap,
            "synthetic_id_overlap_count": hard_synthetic_overlap,
        },
        "duplicate_counts": {
            "sample_id": duplicate_sample_id_count,
            "sha": duplicate_sha_count,
            "synthetic_id": duplicate_synthetic_id_count,
        },
        "repo_overlap_count": repo_overlap_count,
        "missing_field_stats": missing_field_stats,
        "split_summary": summary,
        "warnings": warnings,
        "errors": errors,
    }


def check_prediction_compatibility(prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    duplicate_sample_id_count = _duplicate_count([str(row.get("sample_id")) for row in prediction_rows if row.get("sample_id") is not None])
    if any("sample_id" not in row for row in prediction_rows):
        errors.append({"code": "missing_required_field_sample_id", "message": "Prediction row missing sample_id."})
    if any("active_slots" in row and not isinstance(row["active_slots"], list) for row in prediction_rows):
        errors.append({"code": "invalid_active_slots_type", "message": "Prediction active_slots must be a list."})
    if any("unit_to_slot" in row and not isinstance(row["unit_to_slot"], dict) for row in prediction_rows):
        errors.append({"code": "invalid_unit_to_slot_type", "message": "Prediction unit_to_slot must be a dict."})
    if any("predicted_count" not in row for row in prediction_rows):
        warnings.append({"code": "missing_predicted_count", "message": "At least one prediction row is missing predicted_count."})
    return {
        "compatibility_checked": True,
        "official_validation_executed": False,
        "training_executed": False,
        "stage2_allowed": False,
        "row_count": len(prediction_rows),
        "duplicate_sample_id_count": duplicate_sample_id_count,
        "warnings": warnings,
        "errors": errors,
    }


def check_edit_units_compatibility(edit_unit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    duplicate_sample_id_count = _duplicate_count([str(row.get("sample_id")) for row in edit_unit_rows if row.get("sample_id") is not None])
    missing_edit_units_rows = sum(1 for row in edit_unit_rows if "edit_units" not in row or not isinstance(row.get("edit_units"), list))
    missing_unit_id_count = 0
    for row in edit_unit_rows:
        for unit in row.get("edit_units", []):
            if "unit_id" not in unit:
                missing_unit_id_count += 1
    if any("sample_id" not in row for row in edit_unit_rows):
        errors.append({"code": "missing_required_field_sample_id", "message": "Edit-unit row missing sample_id."})
    if missing_edit_units_rows:
        errors.append({"code": "missing_edit_units_list", "message": "At least one edit-unit row is missing a valid edit_units list."})
    if missing_unit_id_count:
        warnings.append({"code": "missing_unit_id", "message": f"Missing unit_id count: {missing_unit_id_count}"})
    return {
        "compatibility_checked": True,
        "official_validation_executed": False,
        "training_executed": False,
        "stage2_allowed": False,
        "row_count": len(edit_unit_rows),
        "duplicate_sample_id_count": duplicate_sample_id_count,
        "missing_unit_id_count": missing_unit_id_count,
        "warnings": warnings,
        "errors": errors,
    }


def _duplicate_count(values: list[str]) -> int:
    return sum(max(count - 1, 0) for count in Counter(values).values())


def _cross_split_overlap_counts(split_buckets: dict[str, list[dict[str, Any]]]) -> tuple[int, int, int]:
    return (
        _cross_split_overlap_generic(split_buckets, "sample_id"),
        _cross_split_overlap_generic(split_buckets, "sha"),
        _cross_split_overlap_generic(split_buckets, "synthetic_id"),
    )


def _cross_split_overlap_generic(split_buckets: dict[str, list[dict[str, Any]]], key: str) -> int:
    seen_by_split: dict[str, set[str]] = {}
    for split, rows in split_buckets.items():
        seen_by_split[split] = {str(row.get(key)) for row in rows if row.get(key) not in {None, ""}}
    overlap = 0
    split_names = sorted(seen_by_split)
    for index, left in enumerate(split_names):
        for right in split_names[index + 1 :]:
            overlap += len(seen_by_split[left] & seen_by_split[right])
    return overlap
