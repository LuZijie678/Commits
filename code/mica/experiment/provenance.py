from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_GIT_PROVENANCE_EXCLUDES = (
    "outputs/**",
    "artifacts/**",
    "configs/mica/*.local.json",
    "m_existing_diff_package/data/continuous_m_crawl.launchd.log",
)


def capture_git_provenance(repo_root: str, *, exclude_paths: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    root = Path(repo_root)
    excluded = list(exclude_paths or DEFAULT_GIT_PROVENANCE_EXCLUDES)
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        status_lines = _git_output_lines(root, "status", "--short", "--untracked-files=all", "--", ".", *_exclude_pathspecs(excluded))
        diff_text = _git_output_text(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--", ".", *_exclude_pathspecs(excluded))
        status_text = "\n".join(status_lines)
        return {
            "git_commit": commit,
            "dirty": bool(status_lines),
            "repo_root": str(root),
            "excluded_paths": excluded,
            "status_lines": status_lines,
            "status_hash": hashlib.sha256(status_text.encode("utf-8")).hexdigest(),
            "git_diff_hash": hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
            "scope": "repo_filtered",
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "git_commit": None,
            "dirty": None,
            "repo_root": str(root),
            "excluded_paths": excluded,
            "error": str(exc),
        }


def capture_asset_provenance(asset_registry: dict[str, Any]) -> dict[str, Any]:
    assets = dict(asset_registry.get("assets", {}))
    payload = {}
    for asset_name, asset in assets.items():
        payload[asset_name] = {
            "path": asset.get("path"),
            "eval_only": bool(asset.get("eval_only", False)),
            "required_for": list(asset.get("required_for", [])),
            "allowed_stages": list(asset.get("allowed_stages", [])),
        }
    return {
        "asset_count": len(payload),
        "assets": payload,
    }


def capture_runtime_environment() -> dict[str, Any]:
    return {
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
    }


def _exclude_pathspecs(paths: list[str]) -> list[str]:
    return [f":(exclude){path}" for path in paths]


def _git_output_lines(root: Path, *args: str) -> list[str]:
    output = subprocess.check_output(["git", "-C", str(root), *args], text=True)
    return [line for line in output.splitlines() if line.strip()]


def _git_output_text(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True)
