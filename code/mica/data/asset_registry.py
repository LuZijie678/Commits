from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json
from code.mica.training.checkpointing import load_checkpoint, validate_checkpoint_payload


CHECKSUM_PLACEHOLDERS = {"", "placeholder", "to_be_filled_by_validator", "null"}
UNMATERIALIZED_STATUSES = {"missing", "pending_generation"}
MATERIALIZED_STATUSES = {
    "candidate",
    "candidate_materialized",
    "candidate_validated",
    "annotation_pending",
    "pilot_in_progress",
    "adjudication_pending",
    "quality_review_pending",
    "eligible_for_freeze",
    "frozen",
}
READY_STATUSES = {"candidate_validated", "frozen"}
DEFAULT_LOCAL_MATERIALIZATION_REGISTRY = "configs/mica/data_asset_materializations.local.json"
LOCAL_MATERIALIZATION_SCHEMA_VERSION = "mica-local-asset-materialization-v1"


def load_asset_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Asset registry must be a JSON object.")
    local_registry_path = _default_local_materialization_registry_path(registry_path)
    local_registry = load_local_materialization_registry(local_registry_path) if local_registry_path.exists() else {
        "schema_version": LOCAL_MATERIALIZATION_SCHEMA_VERSION,
        "artifacts": {},
    }
    payload["_runtime_registry_path"] = str(registry_path)
    payload["_runtime_local_materialization_registry_path"] = str(local_registry_path)
    payload["_runtime_local_materializations"] = dict(local_registry.get("artifacts", {}))
    return payload


def validate_asset_registry(registry: dict[str, Any]) -> dict[str, Any]:
    assets = registry.get("assets")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required_missing_paths: list[str] = []
    schema_version = str(registry.get("schema_version") or "")
    schema_enforced = bool(schema_version)
    asset_status: dict[str, dict[str, Any]] = {}

    if not isinstance(assets, dict):
        errors.append({"code": "missing_assets_dict", "message": "Asset registry must define an `assets` object."})
        assets = {}

    for asset_name, payload in assets.items():
        if not isinstance(payload, dict):
            errors.append({"code": "invalid_asset_entry", "message": f"Asset `{asset_name}` must be an object."})
            continue
        entry_errors: list[str] = []
        entry_warnings: list[str] = []
        required = bool(payload.get("required")) or bool(payload.get("required_for"))
        status = str(payload.get("status") or "unknown")
        artifact_id = str(payload.get("artifact_id") or "")
        resolved_path = resolve_asset_path(registry, str(asset_name))
        if required and not resolved_path:
            required_missing_paths.append(str(asset_name))
        if payload.get("stage_use") is not None and not isinstance(payload.get("stage_use"), list):
            errors.append({"code": "invalid_stage_use", "message": f"Asset `{asset_name}` has non-list stage_use."})
        if payload.get("allowed_stages") is not None and not isinstance(payload.get("allowed_stages"), list):
            errors.append({"code": "invalid_allowed_stages", "message": f"Asset `{asset_name}` has non-list allowed_stages."})
        if payload.get("forbidden_stages") is not None and not isinstance(payload.get("forbidden_stages"), list):
            errors.append({"code": "invalid_forbidden_stages", "message": f"Asset `{asset_name}` has non-list forbidden_stages."})
        if (payload.get("forbidden_for_training") or payload.get("eval_only")) and resolved_path is None:
            warnings.append({"code": "forbidden_asset_unset", "message": f"Forbidden asset `{asset_name}` is currently unset."})
        requires_created_at = (
            str(registry.get("protocol_version") or "") == "stage1-v2-protocol"
            or str(asset_name).startswith("stage1_v2_")
        )
        if schema_enforced:
            required_fields = [
                "status",
                "schema_version",
                "source_pool",
                "split",
                "record_count",
                "checksum",
                "created_by",
                "leakage_group_key",
            ]
            if requires_created_at:
                required_fields.append("created_at")
            for field_name in required_fields:
                if field_name not in payload:
                    entry_errors.append(f"missing_{field_name}")
        file_exists = bool(resolved_path) and Path(str(resolved_path)).exists()
        if status in MATERIALIZED_STATUSES and not resolved_path:
            entry_errors.append("asset_not_materialized")
        if status in MATERIALIZED_STATUSES and resolved_path and not file_exists:
            entry_errors.append("materialized_asset_path_missing")
        if status in UNMATERIALIZED_STATUSES and payload.get("path") is not None:
            entry_errors.append("missing_asset_must_not_define_path")
        content_validation = _validate_asset_content(
            asset_name=str(asset_name),
            payload=payload,
            path=Path(str(resolved_path)) if resolved_path else None,
        )
        entry_errors.extend(content_validation["errors"])
        entry_warnings.extend(content_validation["warnings"])
        checksum_match = content_validation["checksum_match"]
        if status in READY_STATUSES and not content_validation["content_valid"]:
            entry_errors.append("content_invalid")
        asset_status[str(asset_name)] = {
            "status": status,
            "artifact_id": artifact_id or None,
            "path": str(resolved_path) if resolved_path else None,
            "file_exists": file_exists,
            "schema_valid": not any(item.startswith("missing_") for item in entry_errors),
            "content_valid": content_validation["content_valid"],
            "formal_ready": status in READY_STATUSES and file_exists and content_validation["content_valid"],
            "checksum_match": checksum_match,
            "errors": sorted(set(entry_errors)),
            "warnings": sorted(set(entry_warnings)),
        }

    frozen_assets = [item for item in asset_status.values() if item["status"] in READY_STATUSES]
    assets_materialized = bool(frozen_assets) and all(item["file_exists"] for item in frozen_assets)
    assets_content_valid = bool(frozen_assets) and all(item["content_valid"] for item in frozen_assets)
    schema_valid = len(errors) == 0 and all(item["schema_valid"] for item in asset_status.values())
    required_assets_ready = len(required_missing_paths) == 0
    readiness_by_requirement = _build_requirement_readiness(assets, asset_status)
    return {
        "valid": len(errors) == 0 and all(not item["errors"] for item in asset_status.values()),
        "schema_valid": schema_valid,
        "registry_status": registry.get("registry_status", "unknown"),
        "required_missing_paths": sorted(required_missing_paths),
        "required_assets_ready": required_assets_ready,
        "readiness_by_requirement": readiness_by_requirement,
        "asset_status": asset_status,
        "assets_materialized": assets_materialized,
        "assets_content_valid": assets_content_valid,
        "formal_ready": bool(frozen_assets)
        and assets_materialized
        and assets_content_valid
        and required_assets_ready
        and len(errors) == 0
        and all(not item["errors"] for item in asset_status.values()),
        "warnings": warnings,
        "errors": errors,
    }


def resolve_asset_path(registry: dict[str, Any], asset_name: str) -> str | None:
    assets = registry.get("assets", {})
    payload = assets.get(asset_name, {})
    if not isinstance(payload, dict):
        return None
    path = payload.get("path")
    if path:
        return str(path)
    artifact_id = str(payload.get("artifact_id") or "")
    if not artifact_id:
        return None
    local_materializations = dict(registry.get("_runtime_local_materializations", {}))
    materialized = local_materializations.get(artifact_id, {})
    if isinstance(materialized, dict) and materialized.get("path"):
        return str(materialized["path"])
    return None


def summarize_assets(registry: dict[str, Any]) -> dict[str, Any]:
    assets = registry.get("assets", {})
    if not isinstance(assets, dict):
        return {"asset_count": 0, "required_count": 0, "configured_count": 0, "forbidden_for_training_count": 0}
    return {
        "asset_count": len(assets),
        "required_count": sum(
            1
            for payload in assets.values()
            if isinstance(payload, dict) and (payload.get("required") or payload.get("required_for"))
        ),
        "configured_count": sum(1 for payload in assets.values() if isinstance(payload, dict) and payload.get("path")),
        "artifact_backed_count": sum(1 for payload in assets.values() if isinstance(payload, dict) and payload.get("artifact_id")),
        "forbidden_for_training_count": sum(
            1
            for payload in assets.values()
            if isinstance(payload, dict)
            and (payload.get("forbidden_for_training") or bool(payload.get("forbidden_stages")) or payload.get("eval_only"))
        ),
    }


def compute_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_asset_content(
    *,
    asset_name: str,
    payload: dict[str, Any],
    path: Path | None,
) -> dict[str, Any]:
    if path is None:
        return {"schema_valid": True, "content_valid": False, "checksum_match": None, "errors": [], "warnings": []}
    if not path.exists():
        return {"schema_valid": True, "content_valid": False, "checksum_match": False, "errors": ["path_not_found"], "warnings": []}
    warnings: list[str] = []
    errors: list[str] = []
    content_valid = True
    expected_checksum = payload.get("sha256") or payload.get("checksum")
    observed_checksum = compute_file_sha256(path)
    checksum_match = None
    if expected_checksum not in {None, *CHECKSUM_PLACEHOLDERS}:
        checksum_match = str(expected_checksum) == observed_checksum
        if not checksum_match:
            errors.append("checksum_mismatch")
    elif expected_checksum in CHECKSUM_PLACEHOLDERS:
        warnings.append("checksum_placeholder")

    schema_version = str(payload.get("schema_version") or "")
    if schema_version == "mica-formal-asset-manifest-v1":
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"schema_valid": False, "content_valid": False, "checksum_match": checksum_match, "errors": ["invalid_json"], "warnings": warnings}
        if not isinstance(content, dict):
            errors.append("manifest_not_object")
        else:
            for field_name in ("schema_version", "asset_name", "split", "formal_ready", "summary", "rows"):
                if field_name not in content:
                    errors.append(f"manifest_missing_{field_name}")
            if not isinstance(content.get("rows"), list):
                errors.append("manifest_rows_not_list")
            if isinstance(content.get("summary"), dict):
                summary = content["summary"]
                for field_name in ("record_count", "repo_count", "duplicate_count", "leakage_group_overlap_count"):
                    if field_name not in summary:
                        errors.append(f"summary_missing_{field_name}")
            else:
                errors.append("manifest_summary_not_object")
        content_valid = len(errors) == 0 and bool(content.get("formal_ready", False))
    elif schema_version == "mica-checkpoint-v2":
        try:
            payload = load_checkpoint(path)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            return {
                "schema_valid": False,
                "content_valid": False,
                "checksum_match": checksum_match,
                "errors": ["invalid_checkpoint_payload"],
                "warnings": warnings,
            }
        validation = validate_checkpoint_payload(payload, require_full_model_state=True)
        if not validation["valid"]:
            errors.extend(f"checkpoint_{item}" for item in validation["errors"])
        content_valid = validation["valid"]
    return {
        "schema_valid": True,
        "content_valid": content_valid,
        "checksum_match": checksum_match,
        "errors": errors,
        "warnings": warnings,
    }


def load_local_materialization_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {"schema_version": LOCAL_MATERIALIZATION_SCHEMA_VERSION, "artifacts": {}}
    payload = read_json(registry_path)
    if not isinstance(payload, dict):
        raise ValueError("Local materialization registry must be a JSON object.")
    artifacts = payload.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ValueError("Local materialization registry must define an `artifacts` object.")
    return payload


def write_local_materialization_registry(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register_local_materialization(
    *,
    registry_path: str | Path,
    artifact_id: str,
    path: str | Path,
    sha256: str,
    created_by: str,
    git_commit: str | None,
) -> dict[str, Any]:
    local_registry = load_local_materialization_registry(registry_path)
    artifacts = dict(local_registry.get("artifacts", {}))
    artifacts[artifact_id] = {
        "path": str(path),
        "sha256": str(sha256),
        "created_by": created_by,
        "git_commit": git_commit,
    }
    local_registry["schema_version"] = LOCAL_MATERIALIZATION_SCHEMA_VERSION
    local_registry["artifacts"] = artifacts
    write_local_materialization_registry(registry_path, local_registry)
    return local_registry


def _build_requirement_readiness(
    assets: dict[str, Any],
    asset_status: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    requirements: dict[str, list[str]] = {}
    for asset_name, payload in assets.items():
        if not isinstance(payload, dict):
            continue
        for requirement in payload.get("required_for", []) or []:
            key = str(requirement)
            requirements.setdefault(key, []).append(str(asset_name))

    readiness: dict[str, dict[str, Any]] = {}
    for requirement, asset_names in sorted(requirements.items()):
        unique_assets = sorted(set(asset_names))
        missing_assets = [name for name in unique_assets if not asset_status.get(name, {}).get("formal_ready", False)]
        readiness[requirement] = {
            "required_assets": unique_assets,
            "missing_assets": missing_assets,
            "ready_asset_count": len(unique_assets) - len(missing_assets),
            "required_asset_count": len(unique_assets),
            "ready": len(unique_assets) > 0 and len(missing_assets) == 0,
        }
    return readiness


def _default_local_materialization_registry_path(registry_path: Path) -> Path:
    return registry_path.with_name(Path(DEFAULT_LOCAL_MATERIALIZATION_REGISTRY).name)
