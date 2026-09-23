#!/usr/bin/env python3
"""Build a stricter precision batch from focused message candidates."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["repo", "sha", "commit_url", "commit_date", "subject", "commit_message", "message_score", "message_reasons", "precision_score", "precision_reasons"]
VERB = r"(add|adds|added|fix|fixes|fixed|remove|removes|removed|update|updates|updated|refactor|replace|restore|support|enable|disable|clear|prevent|allow|use|make|move|rename|split|handle|improve|change|create|created|introduce|introduced)"
NOISE = re.compile(r"\b(revert|merge branch|auto merge|rollup|release|changelog|bump|deps|dependency|dependencies|typo|formatting only)\b", re.I)


def utc_now() -> str:
    return datetime.now().astimezone().isoformat()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def score(row: dict) -> tuple[float, list[str]]:
    subject = row.get("subject", "") or ""
    message = row.get("commit_message", "") or ""
    reasons: list[str] = []
    score = 0.0
    clauses = [part.strip() for part in re.split(r";|\band\b|\balso\b|\bplus\b", subject, flags=re.I) if part.strip()]
    action_clauses = [part for part in clauses if re.search(r"\b" + VERB + r"\b", part, re.I)]

    if ";" in subject and len(action_clauses) >= 2:
        score += 45
        reasons.append("semicolon_two_action_clauses")
    if re.search(r"\bfix(?:es|ed)?\b.*(?:;|\band\b).*(?:\badd|\bsupport|\benable|\bremove|\brestore|\bprevent|\brefactor)", subject, re.I):
        score += 35
        reasons.append("fix_plus_other_action")
    if re.search(r"\b(add|support|enable|introduce|create)\w*\b.*(?:;|\band\b).*\b(add|support|enable|introduce|create)\w*\b", subject, re.I):
        score += 30
        reasons.append("two_additive_actions")
    if re.search(r"^[^:]{1,35},\s*[^:]{1,35}:", subject) and (";" in subject or len(action_clauses) >= 2):
        score += 18
        reasons.append("multi_scope_compound")
    if re.search(r"\b(also|additionally|plus|as well)\b", message, re.I) and len(action_clauses) >= 1:
        score += 18
        reasons.append("body_has_explicit_additional_action")
    bullets = re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )(.+)$", message)
    action_bullets = [b for b in bullets if re.search(r"\b" + VERB + r"\b", b, re.I)]
    if len(action_bullets) >= 3:
        score += min(18, len(action_bullets) * 3)
        reasons.append(f"multiple_action_bullets={len(action_bullets)}")
    if re.search(r"\bvarious\b|\bmultiple\b|\bseveral\b", subject, re.I) and len(action_clauses) >= 2:
        score += 12
        reasons.append("explicit_various_multiple")
    if NOISE.search(subject):
        score -= 35
        reasons.append("noise_downweight")
    if not reasons or score < 35:
        return 0.0, reasons
    return max(score, 0.0), reasons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select strict high-precision message candidates.")
    parser.add_argument("--input-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_message_candidates.csv"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--output-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_precision_message_candidates_round3_31repos.csv"))
    parser.add_argument("--summary", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_precision_message_round3_31repos_summary.json"))
    parser.add_argument("--balanced-output", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_precision_balanced_message_round3_31repos.csv"))
    parser.add_argument("--top-per-repo", type=int, default=5)
    return parser.parse_args()


def load_labeled(labels_dir: Path) -> set[tuple[str, str]]:
    labeled = set()
    if labels_dir.exists():
        for path in labels_dir.glob("*_labeled.csv"):
            for row in read_csv(path):
                repo = row.get("repo", "")
                sha = row.get("sha", "")
                if repo and sha:
                    labeled.add((repo, sha))
    return labeled


def main() -> None:
    args = parse_args()
    labeled = load_labeled(args.labels_dir)
    selected = []
    for row in read_csv(args.input_csv):
        if (row.get("repo", ""), row.get("sha", "")) in labeled:
            continue
        precision_score, reasons = score(row)
        if precision_score <= 0:
            continue
        out = {field: row.get(field, "") for field in FIELDS}
        out["precision_score"] = f"{precision_score:.3f}"
        out["precision_reasons"] = "; ".join(reasons)
        selected.append(out)
    selected.sort(key=lambda item: float(item["precision_score"]), reverse=True)
    write_csv(args.output_csv, selected)

    by_repo = defaultdict(list)
    for row in selected:
        by_repo[row["repo"]].append(row)
    balanced = []
    for repo in sorted(by_repo):
        balanced.extend(by_repo[repo][: args.top_per_repo])
    balanced.sort(key=lambda item: (item["repo"], -float(item["precision_score"])))
    write_csv(args.balanced_output, balanced)

    summary = {
        "created_at": utc_now(),
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
        "balanced_output": str(args.balanced_output),
        "excluded_labeled": len(labeled),
        "precision_count": len(selected),
        "balanced_count": len(balanced),
        "repo_count": len(by_repo),
        "top_per_repo": args.top_per_repo,
        "top_repos": dict(Counter(row["repo"] for row in selected).most_common(30)),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
