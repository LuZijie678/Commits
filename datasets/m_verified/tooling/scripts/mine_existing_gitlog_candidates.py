#!/usr/bin/env python3
"""Mine likely multi-intent commits from local git repositories.

This script is intentionally lightweight: it ranks commits by message-level
compound-intent signals first, then extracts file metadata and compact diffs only
for the highest-ranked commits. It is meant for scaling the Step1-style M mining
workflow without depending on GitHub Search API limits.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"

ACTION_VERBS = {
    "add",
    "adds",
    "added",
    "allow",
    "avoid",
    "change",
    "clean",
    "clear",
    "correct",
    "dedupe",
    "disable",
    "enable",
    "expose",
    "fix",
    "fixes",
    "fixed",
    "handle",
    "implement",
    "improve",
    "include",
    "inline",
    "make",
    "migrate",
    "move",
    "optimize",
    "prevent",
    "reduce",
    "refactor",
    "remove",
    "rename",
    "replace",
    "restore",
    "split",
    "support",
    "switch",
    "update",
    "use",
    "validate",
}

WEAK_SINGLE_PURPOSE_HINTS = {
    "bump",
    "deps",
    "dependency",
    "dependencies",
    "version",
    "changelog",
    "release",
    "snapshot",
    "lockfile",
    "format",
    "lint",
}

PATH_ROLE_PATTERNS = [
    ("test", re.compile(r"(^|/)(test|tests|spec|specs|__tests__|fixtures?)(/|$)|\.(test|spec)\.", re.I)),
    ("docs", re.compile(r"(^|/)(docs?|documentation|examples?)(/|$)|(^|/)readme|\.md$|\.rst$", re.I)),
    ("ci", re.compile(r"(^|/)(\.github|\.gitlab|ci|buildkite|jenkins)(/|$)|\.ya?ml$", re.I)),
    ("config", re.compile(r"(^|/)(config|configs)(/|$)|(^|/)(package\.json|tsconfig|eslint|prettier|webpack|vite|rollup|babel|cargo\.toml|go\.mod|pom\.xml|build\.gradle)$", re.I)),
    ("build", re.compile(r"(^|/)(build|scripts?|tools?)(/|$)|makefile|cmake|dockerfile", re.I)),
    ("source", re.compile(r"\.(py|js|jsx|ts|tsx|go|rs|java|c|cc|cpp|h|hpp|cs|rb|php|swift|kt|scala)$", re.I)),
]

GENERATED_OR_VENDOR = re.compile(r"(^|/)(vendor|vendors|dist|build|out|target|node_modules|third_party|generated)(/|$)|\.lock$", re.I)

CSV_FIELDS = [
    "repo",
    "sha",
    "commit_url",
    "language",
    "commit_date",
    "subject",
    "commit_message",
    "candidate_layer",
    "m_candidate_score",
    "m_candidate_reasons",
    "file_count",
    "path_roles",
    "top_dirs",
    "shortstat",
    "git_diff",
]


@dataclass
class LogCommit:
    repo: str
    repo_dir: Path
    sha: str
    date: str
    subject: str
    message: str
    message_score: float
    message_reasons: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def repo_name_from_dir(path: Path) -> str:
    return path.name.replace("__", "/")


def load_blocklist(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()}


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", text.lower())


def count_action_verbs(text: str) -> int:
    return sum(1 for word in normalize_words(text) if word in ACTION_VERBS)


def score_message(subject: str, message: str) -> tuple[float, list[str]]:
    text = f"{subject}\n{message}".strip()
    lower_subject = subject.lower()
    lower_text = text.lower()
    reasons: list[str] = []
    score = 0.0

    if ";" in subject:
        score += 14
        reasons.append("subject_has_semicolon")
    if re.search(r"\b(also|additionally|plus|as well)\b", lower_text):
        score += 10
        reasons.append("message_has_also_signal")
    if re.search(r"\b(and|&)\b", lower_subject) and count_action_verbs(subject) >= 2:
        score += 9
        reasons.append("subject_and_links_actions")
    if re.search(r"[,/]\s*\w+[:,]", subject) or re.search(r"^[^:]{1,40},\s*[^:]{1,40}:", subject):
        score += 5
        reasons.append("subject_multiple_scopes")

    verb_count_subject = count_action_verbs(subject)
    verb_count_message = count_action_verbs(message)
    if verb_count_subject >= 3:
        score += 8
        reasons.append(f"many_subject_action_verbs={verb_count_subject}")
    elif verb_count_subject == 2:
        score += 4
        reasons.append("two_subject_action_verbs")
    if verb_count_message >= 8:
        score += 7
        reasons.append(f"many_message_action_verbs={verb_count_message}")
    elif verb_count_message >= 5:
        score += 4
        reasons.append(f"message_action_verbs={verb_count_message}")

    bullet_count = len(re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )", message))
    if bullet_count >= 4:
        score += 6
        reasons.append(f"message_has_list_items={bullet_count}")
    elif bullet_count >= 2:
        score += 3
        reasons.append(f"message_has_list_items={bullet_count}")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", message) if p.strip()]
    action_paragraphs = sum(1 for p in paragraphs if count_action_verbs(p) >= 2)
    if action_paragraphs >= 2:
        score += 5
        reasons.append(f"multiple_action_paragraphs={action_paragraphs}")

    if re.search(r"\b(fix|fixed|fixes)\b", lower_subject) and re.search(r"\b(add|adds|support|enable|implement)\b", lower_subject):
        score += 8
        reasons.append("subject_mixes_fix_and_feature")
    if re.search(r"\b(refactor|cleanup|rename|move)\b", lower_subject) and re.search(r"\b(fix|add|support|enable|remove)\b", lower_subject):
        score += 6
        reasons.append("subject_mixes_refactor_with_other_action")

    weak_hits = sorted({word for word in normalize_words(subject) if word in WEAK_SINGLE_PURPOSE_HINTS})
    if weak_hits and score < 18:
        score -= 5
        reasons.append("weak_single_purpose_hint=" + "+".join(weak_hits))

    if re.search(r"\b(revert|merge branch|auto merge|rollup|update snapshots?)\b", lower_subject):
        score -= 10
        reasons.append("likely_noise_or_merge_like")

    return max(score, 0.0), reasons


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


def parse_log_records(raw: str, repo: str, repo_dir: Path) -> Iterable[LogCommit]:
    for record in raw.split(RECORD_SEP):
        record = record.strip("\n\r\x00")
        if not record:
            continue
        fields = record.split(FIELD_SEP, 3)
        if len(fields) != 4:
            continue
        sha, date, subject, body = fields
        subject = subject.strip().replace("\n", " ")
        body = body.strip()
        score, reasons = score_message(subject, body)
        if score <= 0:
            continue
        yield LogCommit(repo, repo_dir, sha.strip(), date.strip(), subject, body, score, reasons)


def extract_commit_row(commit: LogCommit, diff_max_chars: int, show_timeout: int) -> dict | None:
    try:
        name_only = run_git(commit.repo_dir, ["show", "--format=", "--name-only", "--no-renames", commit.sha], timeout=show_timeout)
        shortstat = run_git(commit.repo_dir, ["show", "--format=", "--shortstat", "--no-renames", commit.sha], timeout=show_timeout).strip()
    except Exception:
        return None

    files = [line.strip() for line in name_only.splitlines() if line.strip()]
    if not files:
        return None
    if len(files) > 180:
        return None

    roles = Counter(classify_path(path) for path in files)
    role_keys = sorted(roles)
    top_dirs = sorted({path.split("/", 1)[0] for path in files if "/" in path})[:12]

    score = commit.message_score
    reasons = list(commit.message_reasons)
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
            commit.repo_dir,
            [
                "show",
                "--format=",
                "--no-ext-diff",
                "--no-color",
                "--no-renames",
                "--unified=1",
                commit.sha,
            ],
            timeout=show_timeout,
        )
    except Exception:
        diff = ""
    diff = compact_diff(diff, diff_max_chars)

    return {
        "repo": commit.repo,
        "sha": commit.sha,
        "commit_url": f"https://github.com/{commit.repo}/commit/{commit.sha}",
        "language": "",
        "commit_date": commit.date,
        "subject": commit.subject,
        "commit_message": commit.message,
        "candidate_layer": "gitlog_precision",
        "m_candidate_score": f"{score:.3f}",
        "m_candidate_reasons": "; ".join(reasons),
        "file_count": str(len(files)),
        "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
        "top_dirs": "+".join(top_dirs),
        "shortstat": shortstat,
        "git_diff": diff,
    }


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine M-like candidates from local git repositories.")
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--log-limit", type=int, default=10000)
    parser.add_argument("--preselect-per-repo", type=int, default=180)
    parser.add_argument("--keep-per-repo", type=int, default=60)
    parser.add_argument("--diff-max-chars", type=int, default=9000)
    parser.add_argument("--show-timeout", type=int, default=90)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repos_dir = args.repos_dir.resolve()
    blocklist = load_blocklist(args.blocklist)
    output_dir = args.output_dir.resolve()
    rows: list[dict] = []
    summary: dict = {
        "created_at_utc": utc_now(),
        "repos_dir": str(repos_dir),
        "log_limit": args.log_limit,
        "preselect_per_repo": args.preselect_per_repo,
        "keep_per_repo": args.keep_per_repo,
        "diff_max_chars": args.diff_max_chars,
        "repos": [],
    }

    for repo_dir in sorted(path for path in repos_dir.iterdir() if path.is_dir()):
        repo = repo_name_from_dir(repo_dir)
        repo_summary = {"repo": repo, "repo_dir": str(repo_dir), "status": "pending"}
        if repo.lower() in blocklist:
            repo_summary["status"] = "skipped_blocklisted"
            summary["repos"].append(repo_summary)
            continue
        try:
            run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"], timeout=20)
            raw_log = run_git(
                repo_dir,
                [
                    "log",
                    "--all",
                    "--no-merges",
                    f"-n{args.log_limit}",
                    "--date=iso-strict",
                    f"--pretty=format:%H{FIELD_SEP}%ad{FIELD_SEP}%s{FIELD_SEP}%B{RECORD_SEP}",
                ],
                timeout=180,
            )
        except Exception as exc:
            repo_summary["status"] = "error"
            repo_summary["error"] = str(exc)
            summary["repos"].append(repo_summary)
            continue

        commits = list(parse_log_records(raw_log, repo, repo_dir))
        commits.sort(key=lambda item: item.message_score, reverse=True)
        selected = commits[: args.preselect_per_repo]
        extracted: list[dict] = []
        for commit in selected:
            row = extract_commit_row(commit, args.diff_max_chars, args.show_timeout)
            if row is not None:
                extracted.append(row)
        extracted.sort(key=lambda row: float(row["m_candidate_score"]), reverse=True)
        kept = extracted[: args.keep_per_repo]
        rows.extend(kept)
        repo_summary.update(
            {
                "status": "ok",
                "scored_message_candidates": len(commits),
                "preselected": len(selected),
                "extracted": len(extracted),
                "kept": len(kept),
                "top_score": kept[0]["m_candidate_score"] if kept else None,
            }
        )
        summary["repos"].append(repo_summary)
        print(json.dumps(repo_summary, ensure_ascii=False, sort_keys=True), flush=True)

    rows.sort(key=lambda row: float(row["m_candidate_score"]), reverse=True)
    csv_path = output_dir / "gitlog_existing_candidates.csv"
    jsonl_path = output_dir / "gitlog_existing_candidates.jsonl"
    index_path = output_dir / "gitlog_existing_candidates_index.csv"
    summary_path = output_dir / "gitlog_existing_summary.json"

    write_csv(csv_path, rows)
    write_jsonl(jsonl_path, rows)
    index_fields = [field for field in CSV_FIELDS if field not in {"git_diff", "commit_message"}]
    index_rows = [{key: value for key, value in row.items() if key in index_fields} for row in rows]
    write_csv(index_path, index_rows, index_fields)
    summary["candidate_count"] = len(rows)
    summary["repo_count_ok"] = sum(1 for item in summary["repos"] if item.get("status") == "ok")
    summary["repo_count_skipped_blocklisted"] = sum(1 for item in summary["repos"] if item.get("status") == "skipped_blocklisted")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"candidate_count": len(rows), "csv": str(csv_path), "summary": str(summary_path)}, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
