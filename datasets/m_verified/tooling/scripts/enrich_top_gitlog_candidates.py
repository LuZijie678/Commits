#!/usr/bin/env python3
"""Enrich top message-only candidates with file roles and compact diffs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PATH_ROLE_PATTERNS = [
    ("test", re.compile(r"(^|/)(test|tests|spec|specs|__tests__|fixtures?)(/|$)|\.(test|spec)\.", re.I)),
    ("docs", re.compile(r"(^|/)(docs?|documentation|examples?)(/|$)|(^|/)readme|\.md$|\.rst$", re.I)),
    ("ci", re.compile(r"(^|/)(\.github|\.gitlab|ci|buildkite|jenkins)(/|$)|\.ya?ml$", re.I)),
    ("config", re.compile(r"(^|/)(config|configs)(/|$)|(^|/)(package\.json|tsconfig|eslint|prettier|webpack|vite|rollup|babel|cargo\.toml|go\.mod|pom\.xml|build\.gradle)$", re.I)),
    ("build", re.compile(r"(^|/)(build|scripts?|tools?)(/|$)|makefile|cmake|dockerfile", re.I)),
    ("source", re.compile(r"\.(py|js|jsx|ts|tsx|go|rs|java|c|cc|cpp|h|hpp|cs|rb|php|swift|kt|scala)$", re.I)),
]
GENERATED_OR_VENDOR = re.compile(r"(^|/)(vendor|vendors|dist|build|out|target|node_modules|third_party|generated)(/|$)|\.lock$", re.I)

OUTPUT_FIELDS = [
    "repo", "sha", "commit_url", "language", "commit_date", "subject", "commit_message",
    "candidate_layer", "m_candidate_score", "m_candidate_reasons", "message_score",
    "message_reasons", "file_count", "path_roles", "top_dirs", "shortstat", "git_diff",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_dir_for(repos_dir: Path, repo: str) -> Path:
    return repos_dir / repo.replace("/", "__")


def run_git(repo_dir: Path, args: list[str], timeout: int = 90) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def classify_path(path: str) -> str:
    if GENERATED_OR_VENDOR.search(path):
        return "generated_or_vendor"
    for role, pattern in PATH_ROLE_PATTERNS:
        if pattern.search(path):
            return role
    return "other"


def compact_diff(diff: str, max_chars: int) -> str:
    if max_chars <= 0 or len(diff) <= max_chars:
        return diff
    head = int(max_chars * 0.65)
    tail = max_chars - head
    omitted = len(diff) - max_chars
    return diff[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + diff[-tail:]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def enrich_row(row: dict, repos_dir: Path, diff_max_chars: int, timeout: int) -> dict | None:
    repo = str(row.get("repo", ""))
    sha = str(row.get("sha", ""))
    repo_dir = repo_dir_for(repos_dir, repo)
    if not repo or not sha or not repo_dir.exists():
        return None
    try:
        name_only = run_git(repo_dir, ["show", "--format=", "--name-only", "--no-renames", sha], timeout=timeout)
        shortstat = run_git(repo_dir, ["show", "--format=", "--shortstat", "--no-renames", sha], timeout=timeout).strip()
    except Exception:
        return None
    files = [line.strip() for line in name_only.splitlines() if line.strip()]
    if not files or len(files) > 160:
        return None
    roles = Counter(classify_path(path) for path in files)
    role_keys = sorted(roles)
    top_dirs = sorted({path.split("/", 1)[0] for path in files if "/" in path})[:12]

    score = float(row.get("message_score") or 0.0)
    reasons = [str(row.get("message_reasons") or "").strip()]
    if len(files) >= 4:
        score += min(8, len(files) / 3)
        reasons.append(f"file_count={len(files)}")
    if len(role_keys) >= 3:
        score += 6
        reasons.append("cross_file_roles=" + "+".join(role_keys))
    elif len(role_keys) == 2:
        score += 3
        reasons.append("cross_file_roles=" + "+".join(role_keys))
    if "source" in roles and "test" in roles and len(role_keys) >= 3:
        score += 2
        reasons.append("source_test_plus_extra_role")
    if len(top_dirs) >= 3:
        score += 4
        reasons.append(f"multi_top_dirs={len(top_dirs)}")
    if roles.get("generated_or_vendor", 0) >= max(3, len(files) // 2):
        score -= 10
        reasons.append("many_generated_or_vendor_files")

    try:
        diff = run_git(
            repo_dir,
            ["show", "--format=", "--no-ext-diff", "--no-color", "--no-renames", "--unified=1", sha],
            timeout=timeout,
        )
    except Exception:
        diff = ""

    out = dict(row)
    out.update({
        "language": row.get("language", ""),
        "candidate_layer": "gitlog_precision_enriched",
        "m_candidate_score": f"{score:.3f}",
        "m_candidate_reasons": "; ".join(part for part in reasons if part),
        "file_count": str(len(files)),
        "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
        "top_dirs": "+".join(top_dirs),
        "shortstat": shortstat,
        "git_diff": compact_diff(diff, diff_max_chars),
    })
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich top message candidates with compact git diff.")
    parser.add_argument("--input-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_message_candidates.csv"))
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--output-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--diff-max-chars", type=int, default=9000)
    parser.add_argument("--timeout", type=int, default=70)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repos_dir = args.repos_dir.resolve()
    rows = read_csv(args.input_csv)
    rows.sort(key=lambda row: float(row.get("message_score") or 0.0), reverse=True)
    selected = rows[: args.limit]
    enriched: list[dict] = []
    errors = 0
    for index, row in enumerate(selected, start=1):
        out = enrich_row(row, repos_dir, args.diff_max_chars, args.timeout)
        if out is None:
            errors += 1
        else:
            enriched.append(out)
        if index % 20 == 0:
            print(f"enriched={len(enriched)} errors={errors} index={index}/{len(selected)}", flush=True)
    enriched.sort(key=lambda row: float(row.get("m_candidate_score") or 0.0), reverse=True)

    output_dir = args.output_dir.resolve()
    csv_path = output_dir / "gitlog_enriched_top_candidates.csv"
    jsonl_path = output_dir / "gitlog_enriched_top_candidates.jsonl"
    index_path = output_dir / "gitlog_enriched_top_candidates_index.csv"
    summary_path = output_dir / "gitlog_enriched_top_summary.json"
    write_csv(csv_path, enriched, OUTPUT_FIELDS)
    write_jsonl(jsonl_path, enriched)
    index_fields = [field for field in OUTPUT_FIELDS if field not in {"commit_message", "git_diff"}]
    write_csv(index_path, [{k: v for k, v in row.items() if k in index_fields} for row in enriched], index_fields)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv.resolve()),
        "selected": len(selected),
        "enriched": len(enriched),
        "errors_or_skipped": errors,
        "diff_max_chars": args.diff_max_chars,
        "output_csv": str(csv_path),
        "output_jsonl": str(jsonl_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
