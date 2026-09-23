from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from code.mica.config_loader import compute_config_family_hash, load_mica_config
from code.mica.data.asset_registry import load_asset_registry
from code.mica.experiment.provenance import capture_git_provenance, capture_runtime_environment
from code.mica.io_utils import REPO_ROOT
from code.mica.runners.registry import get_runner_policy


def build_experiment_manifest(
    *,
    stage: str,
    protocol_version: str,
    config_hash: str,
    asset_registry_hash: str,
    git_commit: str | None,
    dirty: bool,
    seed: int,
    advisor_approval_status: str,
    forbidden_assets_excluded: bool = True,
    runtime_output_policy: str = "no_repo_outputs",
) -> dict[str, Any]:
    return {
        "manifest_version": "mica-experiment-v1",
        "stage": stage,
        "protocol_version": protocol_version,
        "config_hash": config_hash,
        "asset_registry_hash": asset_registry_hash,
        "git_commit": git_commit,
        "dirty": bool(dirty),
        "seed": int(seed),
        "forbidden_assets_excluded": bool(forbidden_assets_excluded),
        "runtime_output_policy": runtime_output_policy,
        "advisor_approval_status": advisor_approval_status,
    }


def validate_experiment_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = [
        "manifest_version",
        "stage",
        "protocol_version",
        "config_hash",
        "asset_registry_hash",
        "git_commit",
        "dirty",
        "seed",
        "forbidden_assets_excluded",
        "runtime_output_policy",
        "advisor_approval_status",
    ]
    errors = [f"missing_{field}" for field in required if field not in manifest]
    warnings = []
    if manifest.get("dirty") is True:
        warnings.append("dirty_worktree_not_fully_reproducible")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def compute_manifest_hash(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_runner_experiment_manifest(
    runner_name: str,
    config_paths: list[str],
    asset_registry_path: str | None,
    seed: int | None,
    *,
    mode: str = "dry_run",
    advisor_approval: bool = False,
) -> dict[str, Any]:
    configs = {Path(path).stem: load_mica_config(path) for path in config_paths}
    config_hash = compute_config_family_hash(configs) if configs else ""
    asset_registry = load_asset_registry(asset_registry_path) if asset_registry_path else {"assets": {}}
    asset_registry_hash = hashlib.sha256(
        json.dumps(asset_registry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    git_info = capture_git_provenance(str(REPO_ROOT))
    policy = get_runner_policy(runner_name)
    manifest = build_experiment_manifest(
        stage=str(policy.get("stage", runner_name)),
        protocol_version="mica-runner-v1",
        config_hash=config_hash,
        asset_registry_hash=asset_registry_hash,
        git_commit=git_info.get("git_commit"),
        dirty=bool(git_info.get("dirty")),
        seed=int(seed or 0),
        advisor_approval_status="approved" if advisor_approval else "pending",
    )
    manifest.update(
        {
            "runner_name": runner_name,
            "mode": mode,
            "advisor_approval": bool(advisor_approval),
            "git_provenance": git_info,
            "final_test_usage": {"used": False, "threshold_tuning": False},
            "runtime_output_policy": "no_repo_outputs",
            "environment": capture_runtime_environment(),
            "api_policy": bool(policy.get("can_call_api", False)),
            "attribution_update_policy": bool(policy.get("can_update_attribution", False)),
            "attribution_update_scope": str(policy.get("attribution_update_scope", "policy_unspecified")),
        }
    )
    return manifest


def validate_runner_manifest_against_policy(manifest: dict[str, Any], runner_policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if manifest.get("stage") != runner_policy.get("stage"):
        errors.append("runner_stage_mismatch")
    if manifest.get("mode") in {"train", "execute"} and runner_policy.get("requires_advisor_approval") and not manifest.get("advisor_approval"):
        errors.append("advisor_approval_required")
    if runner_policy.get("can_update_attribution") is False and bool(manifest.get("attribution_update_policy")):
        errors.append("attribution_update_forbidden")
    final_test_usage = dict(manifest.get("final_test_usage", {}))
    if final_test_usage.get("threshold_tuning"):
        errors.append("final_test_threshold_tuning_forbidden")
    if final_test_usage.get("used") and not runner_policy.get("can_use_final_test", False):
        errors.append("final_test_usage_forbidden")
    if bool(manifest.get("api_policy")) and runner_policy.get("can_call_api") is False:
        errors.append("api_policy_forbidden")
    return {"valid": len(errors) == 0, "errors": errors}
