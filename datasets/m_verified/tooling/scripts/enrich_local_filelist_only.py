#!/usr/bin/env python3
"""Enrich candidates with local changed-file evidence only.

This is the fast screening stage for partial/blobless local repos. It avoids
full blob reads, so it does not trigger expensive promisor fetches. Rows emitted
here are suitable for candidate labeling but not for the strict full-diff set.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

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
    "candidate_layer", "m_candidate_score", "m_candidate_reasons", "message_score", "message_reasons",
    "precision_score", "precision_reasons", "file_count", "path_roles", "top_dirs", "changed_files",
    "shortstat", "git_diff", "diff_status", "diff_error", "evidence_mode",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def repo_dir_for(repos_dir: Path, repo: str) -> Path:
    return repos_dir / repo.replace("/", "__")


def run_git(repo_dir: Path, args: list[str], timeout: int) -> tuple[int, str, str]:
    try:
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
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        err = exc.stderr or ""
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return 124, "", (err + f"\nTIMEOUT after {timeout}s").strip()


def classify_path(path: str) -> str:
    if GENERATED_OR_VENDOR.search(path):
        return "generated_or_vendor"
    for role, pattern in PATH_ROLE_PATTERNS:
        if pattern.search(path):
            return role
    return "other"


def score_base(row: dict[str, str]) -> float:
    for field in ("_selection_score", "precision_score", "message_score", "m_candidate_score"):
        try:
            value = float(row.get(field) or 0.0)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def load_labeled(labels_dir: Path) -> set[tuple[str, str]]:
    labeled: set[tuple[str, str]] = set()
    if not labels_dir.exists():
        return labeled
    for path in labels_dir.glob("*_labeled.csv"):
        for row in read_csv(path):
            repo = str(row.get("repo") or "")
            sha = str(row.get("sha") or "")
            if repo and sha:
                labeled.add((repo, sha))
    return labeled


def fallback_evidence(row: dict[str, str]) -> str:
    parts = [
        "[Diff unavailable in fast filelist screening. Use this changed-file evidence only.]",
        "diff_status: filelist_only",
    ]
    if row.get("shortstat"):
        parts.append("shortstat: " + row["shortstat"])
    if row.get("path_roles"):
        parts.append("path_roles: " + row["path_roles"])
    if row.get("top_dirs"):
        parts.append("top_dirs: " + row["top_dirs"])
    if row.get("changed_files"):
        parts.append("changed_files:\n" + row["changed_files"])
    return "\n".join(parts)


def enrich_row(row: dict[str, str], repos_dir: Path, timeout: int, max_files: int) -> dict[str, str] | None:
    repo = str(row.get("repo") or "")
    sha = str(row.get("sha") or "")
    repo_dir = repo_dir_for(repos_dir, repo)
    if not repo or not sha or not repo_dir.exists():
        return None
    code, name_only, err = run_git(repo_dir, ["show", "--format=", "--name-only", "--no-renames", sha], timeout)
    if code != 0:
        return None
    files = [line.strip() for line in name_only.splitlines() if line.strip()]
    if not files or len(files) > max_files:
        return None
    roles = Counter(classify_path(path) for path in files)
    role_keys = sorted(roles)
    top_dirs = sorted({path.split("/", 1)[0] for path in files if "/" in path})[:12]
    score = score_base(row)
    reasons = [row.get("precision_reasons") or row.get("message_reasons") or row.get("m_candidate_reasons") or ""]
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

    out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
    out.update(
        {
            "candidate_layer": "gitlog_precision_filelist_only",
            "m_candidate_score": f"{score:.3f}",
            "m_candidate_reasons": "; ".join(part for part in reasons if part),
            "file_count": str(len(files)),
            "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
            "top_dirs": "+".join(top_dirs),
            "changed_files": "\n".join(files[:120]),
            "shortstat": "",
            "diff_status": "filelist_only",
            "diff_error": "",
            "evidence_mode": "filelist_fallback",
        }
    )
    out["git_diff"] = fallback_evidence(out)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast local filelist-only enrichment.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-files", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--include-labeled", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labeled = set() if args.include_labeled else load_labeled(args.labels_dir)
    rows = read_csv(args.input_csv)
    rows.sort(key=score_base, reverse=True)
    if args.limit > 0:
        rows = rows[: args.limit]
    enriched: list[dict[str, str]] = []
    skipped = 0
    skipped_labeled = 0
    for index, row in enumerate(rows, start=1):
        key = (str(row.get("repo") or ""), str(row.get("sha") or ""))
        if key in labeled:
            skipped_labeled += 1
            continue
        out = enrich_row(row, args.repos_dir, args.timeout, args.max_files)
        if out is None:
            skipped += 1
        else:
            enriched.append(out)
        if index % 50 == 0:
            print(f"enriched={len(enriched)} skipped={skipped} skipped_labeled={skipped_labeled} index={index}/{len(rows)}", flush=True)
    enriched.sort(key=lambda row: float(row.get("m_candidate_score") or 0.0), reverse=True)
    write_csv(args.output_csv, enriched)
    write_jsonl(args.output_jsonl, enriched)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "selected": len(rows),
        "enriched": len(enriched),
        "skipped": skipped,
        "skipped_labeled": skipped_labeled,
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
