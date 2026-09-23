#!/usr/bin/env python3
"""Mine likely M commits from known GitHub projects without cloning.

This is a fallback for environments where ``git clone`` is unstable but HTTPS
requests to GitHub API and commit ``.diff`` URLs still work. It emits the same
core enrichment fields as the local git-log pipeline so the existing DeepSeek
labeler and usable-diff builder can consume the output.
"""

from __future__ import annotations

import argparse
import csv
import json
import http.client
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

ACTION_VERBS = {
    "add", "adds", "added", "allow", "avoid", "change", "clean", "clear",
    "correct", "dedupe", "disable", "enable", "expose", "fix", "fixes",
    "fixed", "handle", "implement", "improve", "include", "inline", "make",
    "migrate", "move", "optimize", "prevent", "reduce", "refactor", "remove",
    "rename", "replace", "restore", "split", "support", "switch", "update",
    "use", "validate", "create", "introduce",
}
VERB_RE = r"(add|adds|added|fix|fixes|fixed|remove|removes|removed|update|updates|updated|refactor|replace|restore|support|enable|disable|clear|prevent|allow|use|make|move|rename|split|handle|improve|change|create|created|introduce|introduced)"
NOISE = re.compile(r"\b(revert|merge pull request|merge branch|auto merge|rollup|release|changelog|bump|deps|dependency|dependencies|typo|formatting only)\b", re.I)

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


def load_targets(path: Path) -> list[str]:
    repos: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            repos.append(line)
    return repos


def load_blocklist(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.startswith("#")}


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


def load_labeled(labels_dir: Path) -> set[tuple[str, str]]:
    labeled: set[tuple[str, str]] = set()
    if not labels_dir.exists():
        return labeled
    for path in labels_dir.glob("*_labeled.csv"):
        try:
            rows = read_csv(path)
        except Exception:
            continue
        for row in rows:
            repo, sha = row.get("repo", ""), row.get("sha", "")
            if repo and sha:
                labeled.add((repo, sha))
    return labeled


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

    if re.search(r"\b(fix|fixed|fixes)\b", lower_subject) and re.search(r"\b(add|adds|support|enable|implement)\b", lower_subject):
        score += 9
        reasons.append("subject_mixes_fix_and_feature")
    if re.search(r"\b(refactor|cleanup|rename|move)\b", lower_subject) and re.search(r"\b(fix|add|support|enable|remove)\b", lower_subject):
        score += 7
        reasons.append("subject_mixes_refactor_with_other_action")
    if NOISE.search(subject):
        score -= 20
        reasons.append("noise_downweight")
    return max(score, 0.0), reasons


def score_precision(subject: str, message: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    clauses = [part.strip() for part in re.split(r";|\band\b|\balso\b|\bplus\b", subject, flags=re.I) if part.strip()]
    action_clauses = [part for part in clauses if re.search(r"\b" + VERB_RE + r"\b", part, re.I)]
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
    action_bullets = [b for b in bullets if re.search(r"\b" + VERB_RE + r"\b", b, re.I)]
    if len(action_bullets) >= 3:
        score += min(18, len(action_bullets) * 3)
        reasons.append(f"multiple_action_bullets={len(action_bullets)}")
    if re.search(r"\bvarious\b|\bmultiple\b|\bseveral\b", subject, re.I) and len(action_clauses) >= 2:
        score += 12
        reasons.append("explicit_various_multiple")
    if NOISE.search(subject):
        score -= 35
        reasons.append("noise_downweight")
    return max(score, 0.0), reasons


def request_json(url: str, timeout: int, token: str = "") -> tuple[object, dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "multi-intent-research-github-api",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8")), dict(response.headers)


def fetch_commits(repo: str, pages: int, per_page: int, timeout: int, token: str) -> tuple[list[dict], list[str], dict[str, str]]:
    commits: list[dict] = []
    errors: list[str] = []
    last_headers: dict[str, str] = {}
    quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in repo.split("/", 1))
    for page in range(1, pages + 1):
        url = f"https://api.github.com/repos/{quoted_repo}/commits?per_page={per_page}&page={page}"
        try:
            data, headers = request_json(url, timeout, token)
            last_headers = headers
            if not isinstance(data, list):
                errors.append(f"unexpected_response_page_{page}")
                break
            commits.extend(data)
            if len(data) < per_page:
                break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    return commits, errors, last_headers


def fetch_diff(repo: str, sha: str, timeout: int, attempts: int) -> tuple[str, str]:
    url = f"https://github.com/{repo}/commit/{sha}.diff"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "multi-intent-research-diff"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
            if "diff --git " in text:
                return text, ""
            last_error = "no_diff_marker"
        except http.client.IncompleteRead as exc:
            partial = exc.partial or b""
            if isinstance(partial, bytes):
                text = partial.decode("utf-8", errors="replace")
            else:
                text = str(partial)
            if "diff --git " in text:
                return text, f"IncompleteRead_partial_used: {exc}"
            last_error = f"IncompleteRead: {exc}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            time.sleep(min(2 * attempt, 6))
    return "", last_error


def classify_path(path: str) -> str:
    if GENERATED_OR_VENDOR.search(path):
        return "generated_or_vendor"
    for role, pattern in PATH_ROLE_PATTERNS:
        if pattern.search(path):
            return role
    return "other"


def parse_diff_files(diff: str) -> tuple[list[str], str, Counter[str], list[str]]:
    files: list[str] = []
    insertions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            if match:
                files.append(match.group(2))
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    roles = Counter(classify_path(path) for path in files)
    top_dirs = sorted({path.split("/", 1)[0] for path in files if "/" in path})[:12]
    shortstat = f"{len(files)} files changed, {insertions} insertions(+), {deletions} deletions(-)"
    return files, shortstat, roles, top_dirs


def compact_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.70)
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]


def row_from_commit(repo: str, item: dict) -> dict[str, str] | None:
    sha = str(item.get("sha") or "")
    commit = item.get("commit") or {}
    message = str(commit.get("message") or "")
    subject = message.splitlines()[0].strip() if message else ""
    if not sha or not subject or NOISE.search(subject):
        return None
    date = str(((commit.get("committer") or {}).get("date")) or ((commit.get("author") or {}).get("date")) or "")
    message_score, message_reasons = score_message(subject, message)
    precision_score, precision_reasons = score_precision(subject, message)
    base = max(message_score, precision_score)
    if base <= 0:
        return None
    return {
        "repo": repo,
        "sha": sha,
        "commit_url": f"https://github.com/{repo}/commit/{sha}",
        "language": "",
        "commit_date": date,
        "subject": subject,
        "commit_message": message,
        "message_score": f"{message_score:.3f}",
        "message_reasons": "; ".join(message_reasons),
        "precision_score": f"{precision_score:.3f}",
        "precision_reasons": "; ".join(precision_reasons),
        "_base_score": f"{base:.3f}",
    }


def enrich_candidate(row: dict[str, str], diff_max_chars: int, timeout: int, attempts: int, max_files: int) -> dict[str, str] | None:
    diff, error = fetch_diff(row["repo"], row["sha"], timeout, attempts)
    if not diff:
        out = dict(row)
        out.update({"git_diff": "", "diff_status": "missing_diff", "diff_error": error, "evidence_mode": "missing_diff"})
        return out
    files, shortstat, roles, top_dirs = parse_diff_files(diff)
    if not files or len(files) > max_files:
        return None
    base_score = float(row.get("_base_score") or 0.0)
    reasons = [row.get("precision_reasons") or row.get("message_reasons") or ""]
    if len(files) >= 4:
        base_score += min(8, len(files) / 3)
        reasons.append(f"file_count={len(files)}")
    if len(roles) >= 3:
        base_score += 6
        reasons.append("cross_file_roles=" + "+".join(sorted(roles)))
    elif len(roles) == 2:
        base_score += 3
        reasons.append("cross_file_roles=" + "+".join(sorted(roles)))
    if "source" in roles and "test" in roles and len(roles) >= 3:
        base_score += 2
        reasons.append("source_test_plus_extra_role")
    if len(top_dirs) >= 3:
        base_score += 4
        reasons.append(f"multi_top_dirs={len(top_dirs)}")
    if roles.get("generated_or_vendor", 0) >= max(3, len(files) // 2):
        base_score -= 10
        reasons.append("many_generated_or_vendor_files")

    out = dict(row)
    out.update({
        "candidate_layer": "github_api_remote_diff_enriched",
        "m_candidate_score": f"{base_score:.3f}",
        "m_candidate_reasons": "; ".join(part for part in reasons if part),
        "file_count": str(len(files)),
        "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
        "top_dirs": "+".join(top_dirs),
        "changed_files": "\n".join(files[:120]),
        "shortstat": shortstat,
        "git_diff": compact_text(diff, diff_max_chars),
        "diff_status": "ok",
        "diff_error": error,
        "evidence_mode": "diff",
    })
    return {field: out.get(field, "") for field in OUTPUT_FIELDS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine GitHub API commits and public .diff URLs.")
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit-repos", type=int, default=45)
    parser.add_argument("--pages-per-repo", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--top-per-repo", type=int, default=3)
    parser.add_argument("--max-total", type=int, default=100)
    parser.add_argument("--min-base-score", type=float, default=18.0)
    parser.add_argument("--diff-max-chars", type=int, default=30000)
    parser.add_argument("--max-files", type=int, default=220)
    parser.add_argument("--api-timeout", type=int, default=90)
    parser.add_argument("--diff-timeout", type=int, default=120)
    parser.add_argument("--diff-attempts", type=int, default=3)
    parser.add_argument("--github-token-env", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    blocklist = load_blocklist(args.blocklist)
    labeled = load_labeled(args.labels_dir)
    token = os.environ.get(args.github_token_env, "").strip() if args.github_token_env else ""
    targets = [repo for repo in load_targets(args.targets) if repo.lower() not in blocklist]
    if args.limit_repos > 0:
        targets = targets[: args.limit_repos]

    candidate_rows: list[dict[str, str]] = []
    repo_summaries: list[dict] = []
    for repo in targets:
        commits, errors, headers = fetch_commits(repo, args.pages_per_repo, args.per_page, args.api_timeout, token)
        rows: list[dict[str, str]] = []
        for item in commits:
            row = row_from_commit(repo, item)
            if not row:
                continue
            if (row["repo"], row["sha"]) in labeled:
                continue
            if float(row.get("_base_score") or 0.0) < args.min_base_score:
                continue
            rows.append(row)
        rows.sort(key=lambda item: float(item.get("_base_score") or 0.0), reverse=True)
        kept = rows[: args.top_per_repo]
        candidate_rows.extend(kept)
        summary = {
            "repo": repo,
            "commits_seen": len(commits),
            "candidates": len(rows),
            "kept": len(kept),
            "errors": errors,
            "rate_remaining": headers.get("X-RateLimit-Remaining", ""),
            "rate_reset": headers.get("X-RateLimit-Reset", ""),
        }
        repo_summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        time.sleep(0.25)

    candidate_rows.sort(key=lambda item: float(item.get("_base_score") or 0.0), reverse=True)
    if args.max_total > 0:
        candidate_rows = candidate_rows[: args.max_total]

    enriched: list[dict[str, str]] = []
    skipped = 0
    for index, row in enumerate(candidate_rows, start=1):
        out = enrich_candidate(row, args.diff_max_chars, args.diff_timeout, args.diff_attempts, args.max_files)
        if out is None:
            skipped += 1
        else:
            enriched.append(out)
        if index % 10 == 0:
            print(f"diff_enriched={len(enriched)} skipped={skipped} index={index}/{len(candidate_rows)}", flush=True)

    enriched.sort(key=lambda item: float(item.get("m_candidate_score") or 0.0), reverse=True)
    write_csv(args.output_csv, enriched)
    write_jsonl(args.output_jsonl, enriched)
    summary = {
        "created_at_utc": utc_now(),
        "targets": len(targets),
        "repo_summaries": repo_summaries,
        "candidate_rows": len(candidate_rows),
        "enriched_rows": len(enriched),
        "skipped_after_diff": skipped,
        "diff_ok": sum(1 for row in enriched if row.get("diff_status") == "ok"),
        "diff_missing": sum(1 for row in enriched if row.get("diff_status") != "ok"),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
