#!/usr/bin/env python3
"""Enrich candidates with file metadata and optional compact diffs.

Compared with enrich_top_gitlog_candidates.py, this variant can keep candidates
when diff extraction fails, using commit message + changed file list as fallback.
"""

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
    "candidate_layer", "m_candidate_score", "m_candidate_reasons", "message_score", "message_reasons",
    "precision_score", "precision_reasons", "file_count", "path_roles", "top_dirs", "changed_files",
    "shortstat", "git_diff", "diff_status", "diff_error",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_dir_for(repos_dir: Path, repo: str) -> Path:
    return repos_dir / repo.replace("/", "__")


def run_git(repo_dir: Path, args: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes): out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes): err = err.decode("utf-8", errors="replace")
        return 124, out, err + f"\nTIMEOUT after {timeout}s"


def classify_path(path: str) -> str:
    if GENERATED_OR_VENDOR.search(path): return "generated_or_vendor"
    for role, pattern in PATH_ROLE_PATTERNS:
        if pattern.search(path): return role
    return "other"


def compact_diff(diff: str, max_chars: int) -> str:
    if max_chars <= 0 or len(diff) <= max_chars: return diff
    head = int(max_chars * 0.65); tail = max_chars - head; omitted = len(diff) - max_chars
    return diff[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + diff[-tail:]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def enrich_row(row: dict, repos_dir: Path, diff_max_chars: int, timeout: int, max_files: int) -> dict | None:
    repo = row.get("repo", "") or ""; sha = row.get("sha", "") or ""
    repo_dir = repo_dir_for(repos_dir, repo)
    if not repo or not sha or not repo_dir.exists(): return None
    code, name_only, err = run_git(repo_dir, ["show", "--format=", "--name-only", "--no-renames", sha], timeout)
    if code != 0:
        return None
    files = [line.strip() for line in name_only.splitlines() if line.strip()]
    if not files or len(files) > max_files:
        return None
    code, shortstat, shortstat_err = run_git(repo_dir, ["show", "--format=", "--shortstat", "--no-renames", sha], timeout)
    if code != 0:
        shortstat = ""
    roles = Counter(classify_path(path) for path in files)
    role_keys = sorted(roles)
    top_dirs = sorted({path.split("/", 1)[0] for path in files if "/" in path})[:12]
    base_score = float(row.get("precision_score") or row.get("message_score") or 0.0)
    reasons = [row.get("precision_reasons") or row.get("message_reasons") or ""]
    if len(files) >= 4:
        base_score += min(8, len(files) / 3); reasons.append(f"file_count={len(files)}")
    if len(role_keys) >= 3:
        base_score += 6; reasons.append("cross_file_roles=" + "+".join(role_keys))
    elif len(role_keys) == 2:
        base_score += 3; reasons.append("cross_file_roles=" + "+".join(role_keys))
    if "source" in roles and "test" in roles and len(role_keys) >= 3:
        base_score += 2; reasons.append("source_test_plus_extra_role")
    if len(top_dirs) >= 3:
        base_score += 4; reasons.append(f"multi_top_dirs={len(top_dirs)}")
    if roles.get("generated_or_vendor", 0) >= max(3, len(files) // 2):
        base_score -= 10; reasons.append("many_generated_or_vendor_files")
    code, diff, diff_err = run_git(repo_dir, ["show", "--format=", "--no-ext-diff", "--no-color", "--no-renames", "--unified=1", sha], timeout)
    diff_status = "ok" if code == 0 else "missing_diff"
    diff_error = "" if code == 0 else (diff_err[-500:] or f"git_show_returncode={code}")
    out = dict(row)
    out.update({
        "language": row.get("language", ""),
        "candidate_layer": "gitlog_precision_filelist_enriched",
        "m_candidate_score": f"{base_score:.3f}",
        "m_candidate_reasons": "; ".join(part for part in reasons if part),
        "file_count": str(len(files)),
        "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
        "top_dirs": "+".join(top_dirs),
        "changed_files": "\n".join(files[:120]),
        "shortstat": shortstat.strip(),
        "git_diff": compact_diff(diff, diff_max_chars) if code == 0 else "",
        "diff_status": diff_status,
        "diff_error": diff_error,
    })
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich candidates with file list and optional compact diff.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--diff-max-chars", type=int, default=9000)
    parser.add_argument("--timeout", type=int, default=50)
    parser.add_argument("--max-files", type=int, default=220)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input_csv)
    rows.sort(key=lambda row: float(row.get("_selection_score") or row.get("precision_score") or row.get("message_score") or 0.0), reverse=True)
    if args.limit > 0:
        rows = rows[: args.limit]
    enriched=[]; skipped=0
    for idx,row in enumerate(rows, start=1):
        out = enrich_row(row, args.repos_dir.resolve(), args.diff_max_chars, args.timeout, args.max_files)
        if out is None: skipped += 1
        else: enriched.append(out)
        if idx % 25 == 0:
            print(f"enriched={len(enriched)} skipped={skipped} index={idx}/{len(rows)}", flush=True)
    enriched.sort(key=lambda row: float(row.get("m_candidate_score") or 0.0), reverse=True)
    write_csv(args.output_csv, enriched, OUTPUT_FIELDS)
    write_jsonl(args.output_jsonl, enriched)
    summary={"created_at_utc":utc_now(),"input_csv":str(args.input_csv),"selected":len(rows),"enriched":len(enriched),"skipped":skipped,"diff_ok":sum(1 for r in enriched if r.get('diff_status')=='ok'),"diff_missing":sum(1 for r in enriched if r.get('diff_status')!='ok'),"output_csv":str(args.output_csv),"output_jsonl":str(args.output_jsonl)}
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
