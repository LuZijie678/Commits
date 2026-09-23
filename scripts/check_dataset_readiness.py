#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "manifests" / "local_asset_status.json"
LFS_POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"


REQUIRED_ASSETS = [
    "datasets/step1/canonical/annotated_dataset.csv",
    "datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
    "datasets/step1/runtime_support/resolved_metadata.csv",
    "datasets/step1/runtime_support/resolved_commit_texts.jsonl",
    "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
    "datasets/derived/step1_source_pool/current/source_pool_metadata.json",
    "datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv",
    "datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json",
    "datasets/m_verified/canonical/usable_m_with_real_diff.csv",
    "datasets/step2/delivery/current/fewshot_pool.db",
    "datasets/step2/delivery/current/build_manifest.json",
    "datasets/step2/delivery/current/preflight_report.json",
]

WARN_ONLY_ASSETS = [
    "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.readline().strip() == LFS_POINTER_PREFIX
    except Exception:
        return False


def inspect_asset(repo_root: Path, rel_path: str, *, required: bool, warn_only: bool) -> dict[str, Any]:
    path = repo_root / rel_path
    payload: dict[str, Any] = {
        "path": rel_path,
        "required": required,
        "warn_only": warn_only,
    }
    if not path.exists():
        payload["status"] = "missing_required" if required else "missing_optional"
        payload["ready"] = not required
        return payload
    if path.is_dir():
        payload["status"] = "directory_present"
        payload["ready"] = True
        return payload
    if is_lfs_pointer(path):
        payload["status"] = "lfs_pointer_only_warn" if warn_only else "lfs_pointer_only"
        payload["ready"] = bool(warn_only)
        return payload
    payload["status"] = "materialized_local_file"
    payload["ready"] = True
    return payload


def collect_status(repo_root: Path) -> tuple[dict[str, Any], bool]:
    assets: dict[str, Any] = {}
    warning_count = 0
    error_count = 0

    for rel_path in REQUIRED_ASSETS:
        item = inspect_asset(repo_root, rel_path, required=True, warn_only=False)
        assets[rel_path] = item
        if not item["ready"]:
            error_count += 1

    for rel_path in WARN_ONLY_ASSETS:
        item = inspect_asset(repo_root, rel_path, required=False, warn_only=True)
        assets[rel_path] = item
        if item["status"] == "lfs_pointer_only_warn":
            warning_count += 1
        elif not item["ready"]:
            warning_count += 1

    payload = {
        "checked_at_utc": utc_now(),
        "repo_root": ".",
        "notes": [
            "required assets must be materialized locally for full Step1/Step2 runs.",
            "hard_b canonical is warning-only for the current Step1/Step2 main path; LFS pointer does not block readiness.",
            "this file is the current machine-readable dataset readiness summary.",
        ],
        "summary": {
            "ready": error_count == 0,
            "required_asset_count": len(REQUIRED_ASSETS),
            "warn_only_asset_count": len(WARN_ONLY_ASSETS),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "assets": assets,
    }
    return payload, error_count > 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether the repo-shipped datasets are ready for full Step1/Step2 runs.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, has_error = collect_status(args.repo_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"dataset_ready={int(payload['summary']['ready'])}")
    print(f"error_count={payload['summary']['error_count']}")
    print(f"warning_count={payload['summary']['warning_count']}")
    print(args.output)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
