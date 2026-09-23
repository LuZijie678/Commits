from __future__ import annotations

from collections import defaultdict
from typing import Any


MANDATORY_EVAL_ONLY_ASSETS = {
    "hard_b_test": ("stage2_train", "stage2_calibration", "tuning"),
    "m_final_test": ("stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"),
    "real_domain_split_test": ("stage2_train", "stage3_train", "calibration", "tuning"),
    "real_domain_selective_test": ("stage2_train", "stage3_train", "calibration", "tuning"),
}


def check_asset_boundary(asset_registry: dict[str, Any]) -> dict[str, Any]:
    assets = asset_registry.get("assets", {})
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(assets, dict):
        return {"valid": False, "errors": [{"code": "missing_assets", "message": "Asset registry must define `assets`."}], "warnings": []}

    for asset_name, forbidden_stages in MANDATORY_EVAL_ONLY_ASSETS.items():
        payload = assets.get(asset_name)
        if not isinstance(payload, dict):
            errors.append({"code": "missing_mandatory_asset", "message": f"Missing mandatory asset `{asset_name}`."})
            continue
        if payload.get("eval_only") is not True:
            errors.append({"code": "eval_only_missing", "message": f"Asset `{asset_name}` must set eval_only=true."})
        observed_forbidden = set(payload.get("forbidden_stages", []))
        missing_forbidden = sorted(set(forbidden_stages) - observed_forbidden)
        if missing_forbidden:
            errors.append(
                {
                    "code": "forbidden_stage_missing",
                    "message": f"Asset `{asset_name}` is missing forbidden stages: {', '.join(missing_forbidden)}.",
                }
            )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def check_eval_only_assets(asset_registry: dict[str, Any]) -> dict[str, Any]:
    assets = asset_registry.get("assets", {})
    eval_only_assets = sorted(asset_name for asset_name, payload in assets.items() if isinstance(payload, dict) and payload.get("eval_only"))
    return {
        "eval_only_asset_count": len(eval_only_assets),
        "eval_only_assets": eval_only_assets,
    }


def check_cross_asset_overlap(
    loaded_asset_rows: dict[str, list[dict[str, Any]]],
    id_fields: tuple[str, ...] = ("sample_id", "sha", "synthetic_id"),
) -> dict[str, Any]:
    overlap_counts: dict[str, int] = {}
    for field in id_fields:
        seen_by_asset: dict[str, set[str]] = {}
        for asset_name, rows in loaded_asset_rows.items():
            seen_by_asset[asset_name] = {
                str(row.get(field))
                for row in rows
                if row.get(field) not in {None, ""}
            }
        overlap = 0
        asset_names = sorted(seen_by_asset)
        for index, left in enumerate(asset_names):
            for right in asset_names[index + 1 :]:
                overlap += len(seen_by_asset[left] & seen_by_asset[right])
        overlap_counts[f"{field}_overlap_count"] = overlap
    return overlap_counts


def build_global_leakage_report(
    asset_registry: dict[str, Any],
    loaded_asset_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    boundary = check_asset_boundary(asset_registry)
    eval_only = check_eval_only_assets(asset_registry)
    overlap = check_cross_asset_overlap(loaded_asset_rows)
    return {
        "compatibility_checked": True,
        "official_validation_executed": False,
        "training_executed": False,
        "stage2_allowed": False,
        "boundary_check": boundary,
        "eval_only_assets": eval_only["eval_only_assets"],
        "cross_asset_overlap": overlap,
    }
