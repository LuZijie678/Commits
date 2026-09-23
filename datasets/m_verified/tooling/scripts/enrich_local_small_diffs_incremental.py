#!/usr/bin/env python3
"""Incrementally enrich M candidates with local full diffs.

This variant is deliberately conservative: it writes each processed row as it
goes, skips large/slow commits, and never stores truncated diffs. Rows with
``diff_status=ok`` contain a complete local ``git show`` diff and can be used by
the strict usable-diff builder.
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
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return 124, out, (err + f"\nTIMEOUT after {timeout}s").strip()


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


def parse_shortstat(text: str) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    match = re.search(r"(\d+)\s+insertions?\(\+\)", text)
    if match:
        insertions = int(match.group(1))
    match = re.search(r"(\d+)\s+deletions?\(-\)", text)
    if match:
        deletions = int(match.group(1))
    return insertions, deletions


def output_row(row: dict[str, str], **updates: str) -> dict[str, str]:
    out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
    out.update(updates)
    return {field: out.get(field, "") for field in OUTPUT_FIELDS}


def append_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a" if exists else "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def append_jsonl(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_done(path: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            repo = str(data.get("repo") or "")
            sha = str(data.get("sha") or "")
            if repo and sha:
                done.add((repo, sha))
    return done


def enrich_row(row: dict[str, str], args: argparse.Namespace) -> dict[str, str]:
    repo = str(row.get("repo") or "")
    sha = str(row.get("sha") or "")
    repo_dir = repo_dir_for(args.repos_dir, repo)
    if not repo_dir.exists():
        return output_row(row, diff_status="missing_repo", diff_error=f"missing local repo: {repo_dir}", evidence_mode="missing_diff")

    code, name_only, err = run_git(repo_dir, ["show", "--format=", "--name-only", "--no-renames", sha], args.metadata_timeout)
    if code != 0:
        return output_row(row, diff_status="missing_filelist", diff_error=(err[-500:] or f"git_name_only_returncode={code}"), evidence_mode="missing_diff")
    files = [line.strip() for line in name_only.splitlines() if line.strip()]
    if not files:
        return output_row(row, diff_status="empty_filelist", diff_error="no changed files", evidence_mode="missing_diff")
    if len(files) > args.max_files:
        return output_row(
            row,
            file_count=str(len(files)),
            changed_files="\n".join(files[:120]),
            diff_status="skipped_too_many_files",
            diff_error=f"file_count={len(files)} > max_files={args.max_files}",
            evidence_mode="filelist_only",
        )

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

    code, shortstat, shortstat_err = run_git(repo_dir, ["show", "--format=", "--shortstat", "--no-renames", sha], args.metadata_timeout)
    if code != 0:
        shortstat = ""
    insertions, deletions = parse_shortstat(shortstat)
    changed_lines = insertions + deletions
    common_updates = {
        "candidate_layer": "gitlog_precision_local_full_diff_guarded",
        "m_candidate_score": f"{score:.3f}",
        "m_candidate_reasons": "; ".join(part for part in reasons if part),
        "file_count": str(len(files)),
        "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
        "top_dirs": "+".join(top_dirs),
        "changed_files": "\n".join(files[:120]),
        "shortstat": shortstat.strip(),
    }
    if changed_lines > args.max_changed_lines:
        return output_row(
            row,
            **common_updates,
            diff_status="skipped_too_many_changed_lines",
            diff_error=f"changed_lines={changed_lines} > max_changed_lines={args.max_changed_lines}",
            evidence_mode="filelist_only",
        )

    code, diff, diff_err = run_git(
        repo_dir,
        ["show", "--format=", "--no-ext-diff", "--no-color", "--no-renames", f"--unified={args.unified}", sha],
        args.diff_timeout,
    )
    if code != 0:
        return output_row(
            row,
            **common_updates,
            diff_status="missing_diff",
            diff_error=(diff_err[-500:] or f"git_show_returncode={code}"),
            evidence_mode="filelist_only",
        )
    if "diff --git " not in diff:
        return output_row(row, **common_updates, diff_status="missing_diff_marker", diff_error="no diff --git marker", evidence_mode="filelist_only")
    if len(diff) > args.max_diff_chars:
        return output_row(
            row,
            **common_updates,
            diff_status="skipped_diff_too_large",
            diff_error=f"diff_chars={len(diff)} > max_diff_chars={args.max_diff_chars}",
            evidence_mode="filelist_only",
        )
    return output_row(row, **common_updates, git_diff=diff, diff_status="ok", diff_error="", evidence_mode="diff")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally enrich candidates with guarded local full diffs.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--max-changed-lines", type=int, default=6000)
    parser.add_argument("--max-diff-chars", type=int, default=900000)
    parser.add_argument("--metadata-timeout", type=int, default=10)
    parser.add_argument("--diff-timeout", type=int, default=18)
    parser.add_argument("--unified", type=int, default=3)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input_csv)
    rows.sort(key=score_base, reverse=True)
    if args.limit > 0:
        rows = rows[: args.limit]
    done = set() if args.no_resume else load_done(args.output_jsonl)

    counts: Counter[str] = Counter()
    processed = 0
    skipped_done = 0
    for index, row in enumerate(rows, start=1):
        key = (str(row.get("repo") or ""), str(row.get("sha") or ""))
        if key in done:
            skipped_done += 1
            continue
        out = enrich_row(row, args)
        append_csv(args.output_csv, out)
        append_jsonl(args.output_jsonl, out)
        counts[out.get("diff_status", "")] += 1
        processed += 1
        if processed % 10 == 0:
            print(
                f"processed={processed} skipped_done={skipped_done} ok={counts.get('ok', 0)} "
                f"index={index}/{len(rows)}",
                flush=True,
            )

    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "selected": len(rows),
        "processed": processed,
        "skipped_done": skipped_done,
        "status_counts_this_run": dict(counts),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
