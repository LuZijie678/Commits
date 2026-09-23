#!/usr/bin/env python3
"""Select focused and balanced M-like candidates from message-only git-log output."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

VERBS = r"(add|adds|added|fix|fixes|fixed|remove|removes|removed|update|updates|updated|refactor|replace|restore|support|enable|disable|clear|prevent|allow|use|make|move|rename|split|handle|improve|change)"
NOISE = re.compile(r"\b(revert|merge branch|auto merge|rollup|release|changelog|bump|deps|dependency|dependencies)\b", re.I)
REVIEW_NOISE = re.compile(r"\b(address|review|feedback|follow-?up|nit|typo)\b", re.I)
FIELDS = ["repo", "sha", "commit_url", "commit_date", "subject", "commit_message", "message_score", "message_reasons"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_labeled(labels_dir: Path) -> set[tuple[str, str]]:
    labeled: set[tuple[str, str]] = set()
    if not labels_dir.exists():
        return labeled
    for path in labels_dir.glob("*_labeled.csv"):
        for row in read_csv(path):
            repo = row.get("repo", "")
            sha = row.get("sha", "")
            if repo and sha:
                labeled.add((repo, sha))
    return labeled


def focused_score(row: dict) -> tuple[float, list[str]]:
    subject = row.get("subject", "") or ""
    message = row.get("commit_message", "") or ""
    score = 0.0
    reasons: list[str] = []
    clauses = [part.strip() for part in re.split(r";|\band\b|\balso\b|\bplus\b", subject, flags=re.I) if part.strip()]
    verb_clauses = [part for part in clauses if re.search(r"\b" + VERBS + r"\b", part, re.I)]

    if ";" in subject and len(verb_clauses) >= 2:
        score += 35
        reasons.append("semicolon_splits_two_action_clauses")
    elif ";" in subject:
        score += 18
        reasons.append("subject_has_semicolon")
    if re.search(r"\bfix(?:es|ed)?\b.*\band\b.*\bfix(?:es|ed)?\b", subject, re.I):
        score += 28
        reasons.append("fix_and_fix_subject")
    if re.search(r"\bfix(?:es|ed)?\b.*\b(and|;)\b.*\b(add|support|enable|remove|restore|prevent)\b", subject, re.I):
        score += 24
        reasons.append("fix_plus_feature_or_cleanup_subject")
    if re.search(r"\b(add|support|enable)\b.*\b(and|;)\b.*\b(add|support|enable)\b", subject, re.I):
        score += 24
        reasons.append("two_additive_actions_subject")
    if re.search(r"^[^:]{1,35},\s*[^:]{1,35}:", subject) and (";" in subject or re.search(r"\band\b", subject, re.I)):
        score += 18
        reasons.append("multi_scope_compound_subject")
    if re.search(r"\b(also|additionally|plus|as well)\b", message, re.I) and verb_clauses:
        score += 14
        reasons.append("body_also_with_action_subject")
    body_bullets = len(re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )", message))
    if body_bullets >= 4 and re.search(r"\b" + VERBS + r"\b", message, re.I):
        score += min(12, body_bullets)
        reasons.append(f"body_bullet_actions={body_bullets}")
    if REVIEW_NOISE.search(message) and score < 45:
        score -= 10
        reasons.append("review_feedback_downweight")
    if NOISE.search(subject):
        score -= 20
        reasons.append("noise_downweight")
    return max(score, 0.0), reasons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select focused and balanced M-like message candidates.")
    parser.add_argument("--input-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_message_candidates.csv"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--output-focused", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_focused_message_candidates_round2_23repos.csv"))
    parser.add_argument("--output-balanced", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_balanced_focused_message_round2_23repos.csv"))
    parser.add_argument("--summary", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_round2_23repos_focused_summary.json"))
    parser.add_argument("--top-per-repo", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labeled = load_labeled(args.labels_dir)
    focused: list[dict] = []
    for row in read_csv(args.input_csv):
        if (row.get("repo", ""), row.get("sha", "")) in labeled:
            continue
        score, reasons = focused_score(row)
        if score <= 0:
            continue
        out = {field: row.get(field, "") for field in FIELDS}
        out["message_score"] = f"{score:.3f}"
        original_reasons = row.get("message_reasons") or ""
        out["message_reasons"] = "; ".join(reasons) + ("; original=" + original_reasons if original_reasons else "")
        focused.append(out)
    focused.sort(key=lambda item: float(item["message_score"]), reverse=True)

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in focused:
        by_repo[row["repo"]].append(row)
    balanced: list[dict] = []
    for repo in sorted(by_repo):
        balanced.extend(by_repo[repo][: args.top_per_repo])
    balanced.sort(key=lambda item: (item["repo"], -float(item["message_score"])))

    write_csv(args.output_focused, focused)
    write_csv(args.output_balanced, balanced)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "labels_dir": str(args.labels_dir),
        "excluded_labeled": len(labeled),
        "focused_count": len(focused),
        "balanced_count": len(balanced),
        "repo_count": len(by_repo),
        "top_per_repo": args.top_per_repo,
        "output_focused": str(args.output_focused),
        "output_balanced": str(args.output_balanced),
        "top_repos": dict(Counter(row["repo"] for row in focused).most_common(30)),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

