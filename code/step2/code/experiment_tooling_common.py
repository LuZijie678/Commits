#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from formal_assets import summarize_formal_assets


MODULE_PATH = Path(__file__).resolve().with_name("construct_simple_two_intent.py")
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", MODULE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CORE)


SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password)", flags=re.IGNORECASE)
DATASET_SHA_KEYS = ("sha", "commit_sha", "source_sha")
DATASET_REPO_KEYS = ("repo", "resolved_repo", "repository")
DATASET_URL_KEYS = ("commit_url",)
COMMIT_URL_RE = re.compile(
    r"https?://[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/commit/(?P<sha>[0-9a-fA-F]{6,64})/?$"
)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_strip(value: Any) -> str:
    return CORE.safe_strip(value)


def canonical_repo(repo: str) -> str:
    return CORE.canonical_repo(repo)


def nearest_rank_percentile(values: list[int | float], p: float) -> float:
    return CORE.nearest_rank_percentile(values, p)


def redact_argv(argv: list[str]) -> list[str]:
    return CORE.redact_argv(argv)


def canonical_json_hash(payload: Any) -> str:
    return CORE.canonical_json_hash(payload)


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def read_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not path.exists() or not path.is_file():
        warnings.append(f"missing_file:{path}")
        return rows, warnings
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                warnings.append(f"jsonl_parse_error:{path.name}:{line_no}:{exc.msg}")
                continue
            if not isinstance(payload, dict):
                warnings.append(f"jsonl_non_object:{path.name}:{line_no}")
                continue
            rows.append(payload)
    return rows, warnings


def read_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not path.exists() or not path.is_file():
        warnings.append(f"missing_file:{path}")
        return rows, warnings
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    return rows, warnings


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def infer_generation_attempted(row: dict[str, Any]) -> bool:
    meta = row.get("message_meta", {}) or {}
    if "llm_generation_attempted" in meta:
        return bool(meta.get("llm_generation_attempted"))
    status = safe_strip(row.get("generation_status"))
    return status in {"generated", "generation_failed", "judge_failed", "scoring_failed"}


def is_generated_and_scored(row: dict[str, Any]) -> bool:
    return (
        safe_strip(row.get("generation_status")) == "generated"
        and row.get("message_status") in {"pass", "fallback", "reject"}
    )


def is_step3_ready_row(row: dict[str, Any]) -> bool:
    subject = safe_strip(row.get("synthetic_subject"))
    return bool(
        safe_strip(row.get("generation_status")) == "generated"
        and row.get("message_status") in {"pass", "fallback"}
        and row.get("precheck_status") in {"pass", "warn"}
        and subject
        and safe_float(row.get("final_sample_weight")) > 0.0
    )


def recursive_redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if safe_strip(key) == "argv" and isinstance(value, list):
                redacted[key] = redact_argv([str(item) for item in value])
                continue
            if SENSITIVE_KEY_RE.search(safe_strip(key)):
                redacted[key] = "[REDACTED]"
                continue
            redacted[key] = recursive_redact(value)
        return redacted
    if isinstance(payload, list):
        return [recursive_redact(item) for item in payload]
    return payload


def summarize_input_path(path: Path, *, kind: str = "file") -> dict[str, Any]:
    resolved = path.expanduser()
    exists = resolved.exists()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": bool(exists),
    }
    if not exists:
        payload["sha256"] = None
        payload["kind"] = kind
        return payload
    if resolved.is_file():
        payload["kind"] = "file"
        payload["sha256"] = compute_sha256(resolved)
        payload["size_bytes"] = resolved.stat().st_size
        return payload
    payload["kind"] = "directory"
    entries = []
    for child in sorted(resolved.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
            continue
        entries.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size_bytes": child.stat().st_size if child.is_file() else None,
            }
        )
        if len(entries) >= 50:
            break
    payload["entries_sample"] = entries
    payload["sha256"] = canonical_json_hash(entries)
    return payload


def detect_pool_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".sqlite", ".db"}:
        return "sqlite"
    if suffix == ".csv":
        return "csv"
    if suffix == ".jsonl":
        return "jsonl"
    return "unknown"


def load_config_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def get_git_info(project_root: Path) -> dict[str, Any]:
    def run_git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(project_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git_failed")
        return result.stdout.strip()

    try:
        commit = run_git("rev-parse", "HEAD")
        branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
        dirty = bool(run_git("status", "--porcelain"))
        return {"commit": commit or "unknown", "branch": branch or "unknown", "dirty": dirty}
    except Exception:
        return {"commit": "unknown", "branch": "unknown", "dirty": None}


def infer_run_valid_for_paper(run_purpose: str, config: dict[str, Any]) -> bool:
    if safe_strip(run_purpose) != "formal":
        return False
    if not bool(config.get("message_stage_enabled", True)):
        return False
    if not bool(config.get("message_gate_enabled", True)):
        return False
    if not bool(config.get("fewshot_enabled", True)):
        return False
    if safe_strip(config.get("generator_mode", "api")) == "mock":
        return False
    return True


def build_protocol_blockers(
    run_purpose: str,
    config: dict[str, Any],
    source_info: dict[str, Any],
    fewshot_info: dict[str, Any],
    formal_assets: dict[str, Any] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not config:
        blockers.append("config_missing_or_unreadable")
    if not source_info.get("exists", False):
        blockers.append("source_data_missing")
    if safe_strip(run_purpose) == "formal" and not fewshot_info.get("exists", False):
        blockers.append("fewshot_pool_missing")
    if safe_strip(run_purpose) == "formal" and not bool(config.get("message_stage_enabled", True)):
        blockers.append("message_stage_disabled")
    if safe_strip(run_purpose) == "formal" and not bool(config.get("message_gate_enabled", True)):
        blockers.append("message_gate_disabled")
    if safe_strip(run_purpose) == "formal" and not bool(config.get("fewshot_enabled", True)):
        blockers.append("fewshot_disabled")
    if isinstance(formal_assets, dict):
        for blocker in formal_assets.get("blockers", []) or []:
            blockers.append(safe_strip(blocker))
    return blockers


def summarize_offline_formal_assets(
    *,
    config: dict[str, Any],
    source_data_path: Path,
    fewshot_pool_path: Path,
    source_manifest_path: Path | None,
    fewshot_build_manifest_path: Path | None,
    run_purpose: str,
) -> dict[str, Any]:
    return summarize_formal_assets(
        source_data_path=source_data_path,
        source_manifest_path=source_manifest_path or config.get("source_manifest_path", ""),
        fewshot_pool_path=fewshot_pool_path,
        fewshot_build_manifest_path=fewshot_build_manifest_path or config.get("fewshot_build_manifest_path", ""),
        require_source_manifest=safe_strip(run_purpose) == "formal",
        require_fewshot_build_manifest=safe_strip(run_purpose) == "formal",
    )


def make_run_id(run_purpose: str, output_dir: Path, config_path: Path, random_seed: int) -> str:
    base = {
        "run_purpose": safe_strip(run_purpose) or "analysis",
        "output_dir": str(output_dir),
        "config_path": str(config_path),
        "random_seed": int(random_seed),
    }
    digest = canonical_json_hash(base)[:12]
    stem = output_dir.name or "run"
    return f"{safe_strip(run_purpose) or 'analysis'}_{stem}_{digest}"


def extract_repo_from_url(value: str) -> str:
    text = safe_strip(value)
    if not text:
        return ""
    match = COMMIT_URL_RE.match(text)
    if match:
        return canonical_repo(f"{match.group('owner')}/{match.group('repo')}")
    if "github.com/" in text:
        fragment = text.split("github.com/", 1)[1].strip("/")
        parts = fragment.split("/")
        if len(parts) >= 2:
            return canonical_repo(f"{parts[0]}/{parts[1]}")
    return ""


def extract_sha_from_url(value: str) -> str:
    text = safe_strip(value)
    if not text:
        return ""
    match = COMMIT_URL_RE.match(text)
    if match:
        return safe_strip(match.group("sha")).lower()
    if "/commit/" in text:
        return safe_strip(text.rsplit("/commit/", 1)[-1].strip("/")).lower()
    return ""


def dataset_repo_value(row: dict[str, Any]) -> str:
    for key in DATASET_REPO_KEYS:
        value = safe_strip(row.get(key))
        if value:
            return canonical_repo(value)
    for key in DATASET_URL_KEYS:
        repo = extract_repo_from_url(row.get(key, ""))
        if repo:
            return repo
    return ""


def dataset_sha_value(row: dict[str, Any]) -> str:
    for key in DATASET_SHA_KEYS:
        value = safe_strip(row.get(key))
        if value:
            return value.lower()
    for key in DATASET_URL_KEYS:
        sha = extract_sha_from_url(row.get(key, ""))
        if sha:
            return sha.lower()
    return ""


def read_dataset_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return read_jsonl_rows(path)
    rows, read_warnings = read_csv_rows(path)
    warnings.extend(read_warnings)
    return rows, warnings


def stratified_sample(rows: list[dict[str, Any]], n: int, seed: int, group_keys: list[str]) -> list[dict[str, Any]]:
    import random

    if n <= 0 or not rows:
        return []
    rng = random.Random(seed)
    if not group_keys:
        copied = list(rows)
        rng.shuffle(copied)
        return copied[: min(n, len(copied))]

    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(safe_strip(row.get(field)) for field in group_keys)
        grouped.setdefault(key, []).append(row)
    for bucket in grouped.values():
        rng.shuffle(bucket)
    keys = list(grouped.keys())
    rng.shuffle(keys)
    selected: list[dict[str, Any]] = []
    while len(selected) < n:
        progressed = False
        for key in keys:
            bucket = grouped[key]
            if not bucket:
                continue
            selected.append(bucket.pop())
            progressed = True
            if len(selected) >= n:
                break
        if not progressed:
            break
    return selected


def diff_excerpt(text: str, *, max_lines: int = 24, max_chars: int = 1200) -> str:
    lines = text.splitlines()
    excerpt = "\n".join(lines[:max_lines])
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    elif len(lines) > max_lines:
        excerpt = excerpt.rstrip() + "\n..."
    return excerpt


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def relative_or_abs(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except Exception:
        return str(path)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
