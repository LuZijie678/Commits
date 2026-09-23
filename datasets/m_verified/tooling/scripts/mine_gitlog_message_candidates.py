#!/usr/bin/env python3
"""Fast message-only mining of likely multi-intent commits from local repos."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"

ACTION_VERBS = {
    "add", "adds", "added", "allow", "avoid", "change", "clean", "clear",
    "correct", "dedupe", "disable", "enable", "expose", "fix", "fixes",
    "fixed", "handle", "implement", "improve", "include", "inline", "make",
    "migrate", "move", "optimize", "prevent", "reduce", "refactor", "remove",
    "rename", "replace", "restore", "split", "support", "switch", "update",
    "use", "validate",
}

WEAK_SINGLE_PURPOSE_HINTS = {
    "bump", "deps", "dependency", "dependencies", "version", "changelog",
    "release", "snapshot", "lockfile", "format", "lint",
}

CSV_FIELDS = [
    "repo", "sha", "commit_url", "commit_date", "subject", "commit_message",
    "message_score", "message_reasons",
]


@dataclass
class Candidate:
    repo: str
    sha: str
    date: str
    subject: str
    message: str
    score: float
    reasons: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_git(repo_dir: Path, args: list[str], timeout: int = 180) -> str:
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
        score += 16
        reasons.append("subject_has_semicolon")
    if re.search(r"\b(also|additionally|plus|as well)\b", lower_text):
        score += 11
        reasons.append("message_has_also_signal")
    if re.search(r"\b(and|&)\b", lower_subject) and count_action_verbs(subject) >= 2:
        score += 10
        reasons.append("subject_and_links_actions")
    if re.search(r"^[^:]{1,40},\s*[^:]{1,40}:", subject) or re.search(r"[,/]\s*\w+[:,]", subject):
        score += 5
        reasons.append("subject_multiple_scopes")

    verb_count_subject = count_action_verbs(subject)
    verb_count_message = count_action_verbs(message)
    if verb_count_subject >= 3:
        score += 9
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
        score += 9
        reasons.append("subject_mixes_fix_and_feature")
    if re.search(r"\b(refactor|cleanup|rename|move)\b", lower_subject) and re.search(r"\b(fix|add|support|enable|remove)\b", lower_subject):
        score += 7
        reasons.append("subject_mixes_refactor_with_other_action")

    weak_hits = sorted({word for word in normalize_words(subject) if word in WEAK_SINGLE_PURPOSE_HINTS})
    if weak_hits and score < 20:
        score -= 6
        reasons.append("weak_single_purpose_hint=" + "+".join(weak_hits))

    if re.search(r"\b(revert|merge branch|auto merge|rollup|update snapshots?)\b", lower_subject):
        score -= 12
        reasons.append("likely_noise_or_merge_like")

    return max(score, 0.0), reasons


def parse_records(raw: str, repo: str) -> Iterable[Candidate]:
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
        yield Candidate(repo, sha.strip(), date.strip(), subject, body, score, reasons)


def to_row(candidate: Candidate) -> dict:
    return {
        "repo": candidate.repo,
        "sha": candidate.sha,
        "commit_url": f"https://github.com/{candidate.repo}/commit/{candidate.sha}",
        "commit_date": candidate.date,
        "subject": candidate.subject,
        "commit_message": candidate.message,
        "message_score": f"{candidate.score:.3f}",
        "message_reasons": "; ".join(candidate.reasons),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine message-only M-like candidates from local git repos.")
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--log-limit", type=int, default=30000)
    parser.add_argument("--keep-per-repo", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repos_dir = args.repos_dir.resolve()
    blocklist = load_blocklist(args.blocklist)
    output_dir = args.output_dir.resolve()
    rows: list[dict] = []
    summary = {
        "created_at_utc": utc_now(),
        "repos_dir": str(repos_dir),
        "log_limit": args.log_limit,
        "keep_per_repo": args.keep_per_repo,
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
            raw = run_git(
                repo_dir,
                [
                    "log", "--all", "--no-merges", f"-n{args.log_limit}", "--date=iso-strict",
                    f"--pretty=format:%H{FIELD_SEP}%ad{FIELD_SEP}%s{FIELD_SEP}%B{RECORD_SEP}",
                ],
                timeout=240,
            )
        except Exception as exc:
            repo_summary["status"] = "error"
            repo_summary["error"] = str(exc)
            summary["repos"].append(repo_summary)
            print(json.dumps(repo_summary, ensure_ascii=False, sort_keys=True), flush=True)
            continue
        candidates = list(parse_records(raw, repo))
        candidates.sort(key=lambda item: item.score, reverse=True)
        kept = candidates[: args.keep_per_repo]
        rows.extend(to_row(item) for item in kept)
        repo_summary.update({
            "status": "ok",
            "message_candidates": len(candidates),
            "kept": len(kept),
            "top_score": f"{kept[0].score:.3f}" if kept else None,
        })
        summary["repos"].append(repo_summary)
        print(json.dumps(repo_summary, ensure_ascii=False, sort_keys=True), flush=True)

    rows.sort(key=lambda row: float(row["message_score"]), reverse=True)
    csv_path = output_dir / "gitlog_message_candidates.csv"
    jsonl_path = output_dir / "gitlog_message_candidates.jsonl"
    summary_path = output_dir / "gitlog_message_summary.json"
    write_csv(csv_path, rows)
    write_jsonl(jsonl_path, rows)
    summary["candidate_count"] = len(rows)
    summary["repo_count_ok"] = sum(1 for item in summary["repos"] if item.get("status") == "ok")
    summary["repo_count_skipped_blocklisted"] = sum(1 for item in summary["repos"] if item.get("status") == "skipped_blocklisted")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"candidate_count": len(rows), "csv": str(csv_path), "summary": str(summary_path)}, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
