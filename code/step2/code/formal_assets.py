#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE_MANIFEST_REQUIRED_KEYS = {
    "total_selected",
    "sampling_plan",
    "label_schema",
    "paths",
}
FEWSHOT_BUILD_MANIFEST_REQUIRED_KEYS = {
    "asset_name",
    "asset_version",
    "build_date_utc",
    "db_filename",
    "validation",
    "thresholds",
}


def safe_strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def basename_any_path(value: str) -> str:
    text = safe_strip(value)
    if not text:
        return ""
    normalized = text.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def summarize_path(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": bool(path.exists() and path.is_file()),
    }
    if payload["exists"]:
        payload["sha256"] = compute_sha256(path)
        payload["size_bytes"] = path.stat().st_size
    else:
        payload["sha256"] = None
        payload["size_bytes"] = None
    return payload


def load_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists() or not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"json_parse_error:{exc}"
    if not isinstance(payload, dict):
        return None, "not_json_object"
    return payload, ""


def default_source_manifest_path(source_data_path: Path) -> Path:
    stem = source_data_path.stem
    if stem.endswith("_minimal"):
        return source_data_path.with_name(f"{stem[:-8]}_manifest.json")
    return source_data_path.with_name(f"{stem}_manifest.json")


def default_fewshot_build_manifest_path(fewshot_pool_path: Path) -> Path:
    return fewshot_pool_path.with_name("build_manifest.json")


def resolve_source_manifest_path(explicit_path: str | Path | None, source_data_path: str | Path) -> Path:
    text = safe_strip(explicit_path)
    if text:
        return Path(text)
    return default_source_manifest_path(Path(source_data_path))


def resolve_fewshot_build_manifest_path(explicit_path: str | Path | None, fewshot_pool_path: str | Path | None) -> Path:
    text = safe_strip(explicit_path)
    if text:
        return Path(text)
    pool_text = safe_strip(fewshot_pool_path)
    if pool_text:
        return default_fewshot_build_manifest_path(Path(pool_text))
    return Path("build_manifest.json")


def validate_source_manifest(path: Path, source_data_path: Path, *, required: bool) -> dict[str, Any]:
    info = summarize_path(path)
    info.update({"required": bool(required), "valid": False, "ready": False, "blockers": [], "detail": ""})
    payload, error = load_json_object(path)
    if payload is None:
        if required:
            info["blockers"].append("source_manifest_missing" if error == "missing" else "source_manifest_invalid")
        info["detail"] = error
        return info
    missing = sorted(SOURCE_MANIFEST_REQUIRED_KEYS - set(payload.keys()))
    if missing:
        if required:
            info["blockers"].append("source_manifest_missing_required_fields")
        info["detail"] = f"missing_fields={missing}"
        return info
    recorded_csv = safe_strip(((payload.get("paths") or {}).get("csv")))
    recorded_name = basename_any_path(recorded_csv)
    matches_source_csv = (not recorded_name) or recorded_name == source_data_path.name
    info["recorded_csv_path"] = recorded_csv
    info["matches_source_csv"] = bool(matches_source_csv)
    if required and not matches_source_csv:
        info["blockers"].append("source_manifest_csv_mismatch")
        info["detail"] = f"recorded_csv_name={recorded_name}, expected={source_data_path.name}"
        return info
    info["valid"] = True
    info["ready"] = True
    return info


def validate_fewshot_build_manifest(path: Path, fewshot_pool_path: Path | None, *, required: bool) -> dict[str, Any]:
    info = summarize_path(path)
    info.update({"required": bool(required), "valid": False, "ready": False, "blockers": [], "detail": ""})
    payload, error = load_json_object(path)
    if payload is None:
        if required:
            info["blockers"].append("fewshot_build_manifest_missing" if error == "missing" else "fewshot_build_manifest_invalid")
        info["detail"] = error
        return info
    missing = sorted(FEWSHOT_BUILD_MANIFEST_REQUIRED_KEYS - set(payload.keys()))
    if missing:
        if required:
            info["blockers"].append("fewshot_build_manifest_missing_required_fields")
        info["detail"] = f"missing_fields={missing}"
        return info
    db_filename = safe_strip(payload.get("db_filename"))
    expected_name = fewshot_pool_path.name if fewshot_pool_path else ""
    db_matches = (not expected_name) or (not db_filename) or db_filename == expected_name
    info["db_filename"] = db_filename
    info["matches_fewshot_pool"] = bool(db_matches)
    validation = payload.get("validation") or {}
    audit_pass = bool(validation.get("audit_pass", False))
    retrieval_probe_ok = bool(validation.get("retrieval_probe_ok", False))
    info["validation"] = {
        "audit_pass": audit_pass,
        "retrieval_probe_ok": retrieval_probe_ok,
        "preflight_passed": bool(validation.get("preflight_passed", False)),
    }
    if required and not db_matches:
        info["blockers"].append("fewshot_build_manifest_db_mismatch")
    if required and not audit_pass:
        info["blockers"].append("fewshot_build_manifest_audit_not_passed")
    if required and not retrieval_probe_ok:
        info["blockers"].append("fewshot_build_manifest_probe_not_passed")
    if info["blockers"]:
        info["detail"] = json.dumps(info["blockers"], ensure_ascii=False)
        return info
    info["valid"] = True
    info["ready"] = True
    return info


def summarize_formal_assets(
    *,
    source_data_path: str | Path,
    source_manifest_path: str | Path | None,
    fewshot_pool_path: str | Path | None,
    fewshot_build_manifest_path: str | Path | None,
    require_source_manifest: bool,
    require_fewshot_build_manifest: bool,
) -> dict[str, Any]:
    source_path = Path(source_data_path)
    source_manifest = validate_source_manifest(
        resolve_source_manifest_path(source_manifest_path, source_path),
        source_path,
        required=require_source_manifest,
    )
    resolved_pool_path = Path(safe_strip(fewshot_pool_path)) if safe_strip(fewshot_pool_path) else None
    fewshot_build_manifest = validate_fewshot_build_manifest(
        resolve_fewshot_build_manifest_path(fewshot_build_manifest_path, resolved_pool_path),
        resolved_pool_path,
        required=require_fewshot_build_manifest,
    )
    blockers = list(source_manifest.get("blockers", [])) + list(fewshot_build_manifest.get("blockers", []))
    formal_assets_ready = bool(source_manifest.get("ready", False) and fewshot_build_manifest.get("ready", False))
    return {
        "source_manifest": source_manifest,
        "fewshot_build_manifest": fewshot_build_manifest,
        "formal_assets_ready": bool(formal_assets_ready),
        "blockers": blockers,
    }
