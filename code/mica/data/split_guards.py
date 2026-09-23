from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


DEFAULT_FINAL_SPLIT_NAMES = (
    "test",
    "final-test",
    "final_test",
    "m-final-test",
    "hard_b-test",
    "realdomainbinary-test",
)


def assert_no_final_test_in_training(rows: list[dict[str, Any]], final_split_names: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    disallowed = {item.lower() for item in (final_split_names or DEFAULT_FINAL_SPLIT_NAMES)}
    offending = [str(row.get("split")) for row in rows if str(row.get("split", "")).lower() in disallowed]
    errors = []
    if offending:
        errors.append({"code": "final_test_in_training_rows", "message": "Final-test rows are not allowed in training-calibration inputs."})
    return {
        "row_count": len(rows),
        "forbidden_split_values": sorted(set(offending)),
        "error_count": len(errors),
        "errors": errors,
    }


def summarize_split_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts = Counter(str(row.get("split", "missing")) for row in rows)
    final_like = [split for split in split_counts if split.lower() in {item.lower() for item in DEFAULT_FINAL_SPLIT_NAMES}]
    return {
        "row_count": len(rows),
        "split_counts": dict(split_counts),
        "final_like_splits": sorted(final_like),
    }


def check_cross_split_overlap(rows: list[dict[str, Any]], id_fields: tuple[str, ...] = ("sample_id", "sha", "synthetic_id")) -> dict[str, Any]:
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_split[str(row.get("split", "missing"))].append(row)

    hard_leakage: dict[str, int] = {}
    errors: list[dict[str, Any]] = []
    for field in id_fields:
        overlap_count = _cross_split_overlap(by_split, field)
        hard_leakage[f"{field}_overlap_count"] = overlap_count
        if overlap_count > 0:
            errors.append({"code": f"{field}_overlap_detected", "message": f"Cross-split overlap detected for `{field}`."})

    repo_overlap_count = _cross_split_overlap(by_split, "repo")
    warnings: list[dict[str, Any]] = []
    if repo_overlap_count > 0:
        warnings.append({"code": "repo_overlap_detected", "message": "Repo overlap detected across splits."})

    return {
        "hard_leakage": hard_leakage,
        "repo_overlap_count": repo_overlap_count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def check_forbidden_assets_for_stage(registry: dict[str, Any], stage: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    assets = registry.get("assets", {})
    if not isinstance(assets, dict):
        return {"error_count": 1, "warning_count": 0, "errors": [{"code": "missing_assets_dict", "message": "Registry has no assets."}], "warnings": []}

    training_like_stage = not (stage.startswith("eval") or "final" in stage)
    if training_like_stage:
        for asset_name, payload in assets.items():
            if not isinstance(payload, dict):
                continue
            if payload.get("forbidden_for_training") and payload.get("path"):
                errors.append({"code": "forbidden_asset_for_stage", "message": f"Asset `{asset_name}` is forbidden for training-stage use."})
    else:
        warnings.append({"code": "eval_only_stage", "message": f"Stage `{stage}` is treated as eval-only."})

    return {"error_count": len(errors), "warning_count": len(warnings), "errors": errors, "warnings": warnings}


def _cross_split_overlap(by_split: dict[str, list[dict[str, Any]]], field: str) -> int:
    seen: dict[str, set[str]] = {}
    for split, split_rows in by_split.items():
        seen[split] = {str(row.get(field)) for row in split_rows if row.get(field) not in {None, ""}}
    overlap = 0
    split_names = sorted(seen)
    for index, left in enumerate(split_names):
        for right in split_names[index + 1 :]:
            overlap += len(seen[left] & seen[right])
    return overlap
