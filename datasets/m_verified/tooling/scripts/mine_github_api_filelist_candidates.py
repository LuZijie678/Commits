#!/usr/bin/env python3
"""Mine M-like candidates from GitHub repos using API metadata and file lists.

This script is intended for broad repo coverage. It avoids cloning and avoids
full diffs. It fetches commit messages, scores likely multi-intent candidates,
then fetches per-commit file metadata only for the top candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

ACTION_VERBS = {
    "add", "adds", "added", "allow", "avoid", "change", "clean", "clear", "correct",
    "dedupe", "disable", "enable", "expose", "fix", "fixes", "fixed", "handle",
    "implement", "improve", "include", "inline", "make", "migrate", "move",
    "optimize", "prevent", "reduce", "refactor", "remove", "rename", "replace",
    "restore", "split", "support", "switch", "update", "use", "validate", "create",
    "created", "introduce", "introduced",
}
VERB_RE = r"(add|adds|added|fix|fixes|fixed|remove|removes|removed|update|updates|updated|refactor|replace|restore|support|enable|disable|clear|prevent|allow|use|make|move|rename|split|handle|improve|change|create|created|introduce|introduced)"
NOISE = re.compile(r"\b(revert|merge pull request|merge branch|auto merge|rollup|release|changelog|bump|deps|dependency|dependencies|typo|formatting only)\b", re.I)

PATH_ROLE_PATTERNS = [
    ("test", re.compile(r"(^|/)(test|tests|spec|specs|__tests__|fixtures?)(/|$)|\.(test|spec)\.", re.I)),
    ("docs", re.compile(r"(^|/)(docs?|documentation|examples?)(/|$)|(^|/)readme|\.md$|\.rst$", re.I)),
    ("ci", re.compile(r"(^|/)(\.github|\.gitlab|ci|buildkite|jenkins)(/|$)|\.ya?ml$", re.I)),
    ("config", re.compile(r"(^|/)(config|configs)(/|$)|(^|/)(package\.json|tsconfig|eslint|prettier|webpack|vite|rollup|babel|cargo\.toml|go\.mod|pom\.xml|build\.gradle)$", re.I)),
    ("build", re.compile(r"(^|/)(build|scripts?|tools?)(/|$)|makefile|cmake|dockerfile", re.I)),
    ("source", re.compile(r"\.(py|js|jsx|ts|tsx|go|rs|java|c|cc|cpp|h|hpp|cs|rb|php|swift|kt|scala|dart)$", re.I)),
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


def read_targets(path: Path) -> list[str]:
    repos: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            repos.append(line)
    return repos


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


def append_csv_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def append_jsonl_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl_object(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def load_output_keys(path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not path.exists() or path.stat().st_size == 0:
        return keys
    for row in read_csv(path):
        repo = str(row.get("repo") or "")
        sha = str(row.get("sha") or "")
        if repo and sha:
            keys.add((repo, sha))
    return keys


def load_completed_repos(path: Path) -> set[str]:
    repos: set[str] = set()
    if not path.exists() or path.stat().st_size == 0:
        return repos
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("status") == "done" and item.get("repo"):
                repos.add(str(item["repo"]))
    return repos


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


def request_json(url: str, token: str, timeout: int) -> tuple[object, dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
        "User-Agent": "multi-intent-research-api-filelist",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")), dict(response.headers)
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(min(attempt, 3))
    assert last_exc is not None
    raise last_exc


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
    bullets = len(re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )", message))
    if bullets >= 4:
        score += 6
        reasons.append(f"message_has_list_items={bullets}")
    elif bullets >= 2:
        score += 3
        reasons.append(f"message_has_list_items={bullets}")
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


def classify_path(path: str) -> str:
    if GENERATED_OR_VENDOR.search(path):
        return "generated_or_vendor"
    for role, pattern in PATH_ROLE_PATTERNS:
        if pattern.search(path):
            return role
    return "other"


def fallback_evidence(row: dict[str, str]) -> str:
    parts = [
        "[Diff unavailable in GitHub API broad repo screening. Use this changed-file evidence only.]",
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


def fetch_commits(repo: str, start_page: int, pages: int, per_page: int, token: str, timeout: int) -> tuple[list[dict], list[str], dict[str, str]]:
    commits: list[dict] = []
    errors: list[str] = []
    headers: dict[str, str] = {}
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in repo.split("/", 1))
    first_page = max(1, start_page)
    last_page = first_page + max(0, pages) - 1
    for page in range(first_page, last_page + 1):
        url = f"https://api.github.com/repos/{quoted}/commits?per_page={per_page}&page={page}"
        try:
            data, headers = request_json(url, token, timeout)
            if not isinstance(data, list):
                errors.append(f"unexpected_response_page_{page}")
                break
            commits.extend(data)
            if len(data) < per_page:
                break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    return commits, errors, headers


def fetch_commit_files(repo: str, sha: str, token: str, timeout: int) -> tuple[list[dict], str, dict[str, str]]:
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in repo.split("/", 1))
    url = f"https://api.github.com/repos/{quoted}/commits/{urllib.parse.quote(sha, safe='')}"
    try:
        data, headers = request_json(url, token, timeout)
        if not isinstance(data, dict):
            return [], "unexpected_response", headers
        return list(data.get("files") or []), "", headers
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}", {}


def candidate_from_commit(repo: str, item: dict) -> dict[str, str] | None:
    sha = str(item.get("sha") or "")
    commit = item.get("commit") or {}
    message = str(commit.get("message") or "")
    subject = message.splitlines()[0].strip() if message else ""
    if not sha or not subject or NOISE.search(subject):
        return None
    message_score, message_reasons = score_message(subject, message)
    precision_score, precision_reasons = score_precision(subject, message)
    base_score = max(message_score, precision_score)
    if base_score <= 0:
        return None
    date = str(((commit.get("committer") or {}).get("date")) or ((commit.get("author") or {}).get("date")) or "")
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
        "_base_score": f"{base_score:.3f}",
    }


def enrich_with_files(row: dict[str, str], files: list[dict], max_files: int) -> dict[str, str] | None:
    paths = [str(item.get("filename") or "") for item in files if item.get("filename")]
    if not paths or len(paths) > max_files:
        return None
    roles = Counter(classify_path(path) for path in paths)
    top_dirs = sorted({path.split("/", 1)[0] for path in paths if "/" in path})[:12]
    additions = sum(int(item.get("additions") or 0) for item in files)
    deletions = sum(int(item.get("deletions") or 0) for item in files)
    base_score = float(row.get("_base_score") or 0)
    reasons = [row.get("precision_reasons") or row.get("message_reasons") or ""]
    if len(paths) >= 4:
        base_score += min(8, len(paths) / 3)
        reasons.append(f"file_count={len(paths)}")
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
    if roles.get("generated_or_vendor", 0) >= max(3, len(paths) // 2):
        base_score -= 10
        reasons.append("many_generated_or_vendor_files")
    out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
    out.update(
        {
            "candidate_layer": "github_api_filelist_only",
            "m_candidate_score": f"{base_score:.3f}",
            "m_candidate_reasons": "; ".join(part for part in reasons if part),
            "file_count": str(len(paths)),
            "path_roles": "+".join(f"{role}:{count}" for role, count in sorted(roles.items())),
            "top_dirs": "+".join(top_dirs),
            "changed_files": "\n".join(paths[:120]),
            "shortstat": f"{len(paths)} files changed, {additions} insertions(+), {deletions} deletions(-)",
            "diff_status": "filelist_only",
            "diff_error": "",
            "evidence_mode": "filelist_fallback",
        }
    )
    out["git_diff"] = fallback_evidence(out)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine GitHub API filelist-only M candidates.")
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit-repos", type=int, default=40)
    parser.add_argument("--offset-repos", type=int, default=0)
    parser.add_argument("--start-page", type=int, default=1, help="First GitHub commits API page to scan for each repo.")
    parser.add_argument("--pages-per-repo", type=int, default=2)
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--top-per-repo", type=int, default=3)
    parser.add_argument("--max-total", type=int, default=120)
    parser.add_argument("--min-base-score", type=float, default=18.0)
    parser.add_argument("--max-files", type=int, default=180)
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--incremental", action="store_true", help="Append enriched rows as soon as they are found.")
    parser.add_argument("--resume", action="store_true", help="Skip commits already present in --output-csv and repos marked done in --repo-status-jsonl.")
    parser.add_argument("--repo-status-jsonl", type=Path, default=None, help="Repo-level progress log for incremental/resume runs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get(args.github_token_env, "").strip() if args.github_token_env else ""
    labeled = load_labeled(args.labels_dir)
    repo_status_path = args.repo_status_jsonl
    if repo_status_path is None:
        repo_status_path = args.summary.with_name(args.summary.stem + "_repo_status.jsonl")
    output_keys = load_output_keys(args.output_csv) if args.resume else set()
    completed_repos = load_completed_repos(repo_status_path) if args.resume else set()
    targets = read_targets(args.targets)
    if args.offset_repos > 0:
        targets = targets[args.offset_repos :]
    if args.limit_repos > 0:
        targets = targets[: args.limit_repos]

    repo_summaries: list[dict] = []
    enriched: list[dict[str, str]] = []
    file_errors = 0
    candidate_rows_seen = 0
    stopped_for_max_total = False
    for repo in targets:
        if repo in completed_repos:
            summary = {
                "repo": repo,
                "commits_seen": 0,
                "candidate_count": 0,
                "kept": 0,
                "enriched": 0,
                "file_errors": 0,
                "errors": [],
                "rate_remaining": "",
                "status": "skipped_resume_done",
            }
            repo_summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
            continue
        commits, errors, headers = fetch_commits(repo, args.start_page, args.pages_per_repo, args.per_page, token, args.timeout)
        rows: list[dict[str, str]] = []
        for item in commits:
            row = candidate_from_commit(repo, item)
            if not row:
                continue
            if (row["repo"], row["sha"]) in labeled:
                continue
            if (row["repo"], row["sha"]) in output_keys:
                continue
            if float(row.get("_base_score") or 0) < args.min_base_score:
                continue
            rows.append(row)
        rows.sort(key=lambda row: float(row.get("_base_score") or 0), reverse=True)
        kept = rows[: args.top_per_repo]
        repo_enriched = 0
        repo_file_errors = 0
        candidate_rows_seen += len(kept)
        for row in kept:
            if args.max_total > 0 and len(output_keys) >= args.max_total:
                stopped_for_max_total = True
                break
            files, error, file_headers = fetch_commit_files(row["repo"], row["sha"], token, args.timeout)
            if file_headers:
                headers = file_headers
            if error:
                file_errors += 1
                repo_file_errors += 1
            else:
                out = enrich_with_files(row, files, args.max_files)
                if out:
                    enriched.append(out)
                    output_keys.add((out["repo"], out["sha"]))
                    repo_enriched += 1
                    if args.incremental:
                        append_csv_row(args.output_csv, out)
                        append_jsonl_row(args.output_jsonl, out)
                        if len(enriched) % 20 == 0:
                            args.summary.parent.mkdir(parents=True, exist_ok=True)
                            args.summary.write_text(
                                json.dumps(
                                    {
                                        "created_at_utc": utc_now(),
                                        "targets": len(targets),
                                        "repo_summaries": repo_summaries,
                                        "candidate_rows": candidate_rows_seen,
                                        "enriched_rows": len(output_keys),
                                        "new_enriched_rows": len(enriched),
                                        "file_errors": file_errors,
                                        "token_used": bool(token),
                                        "output_csv": str(args.output_csv),
                                        "output_jsonl": str(args.output_jsonl),
                                        "repo_status_jsonl": str(repo_status_path),
                                        "incremental": args.incremental,
                                        "resume": args.resume,
                                        "partial": True,
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                    sort_keys=True,
                                ),
                                encoding="utf-8",
                            )
            if args.sleep_sec > 0:
                time.sleep(args.sleep_sec)
        summary = {
            "repo": repo,
            "start_page": args.start_page,
            "pages_per_repo": args.pages_per_repo,
            "commits_seen": len(commits),
            "candidate_count": len(rows),
            "kept": len(kept),
            "enriched": repo_enriched,
            "file_errors": repo_file_errors,
            "errors": errors,
            "rate_remaining": headers.get("X-RateLimit-Remaining", ""),
            "status": "max_total_reached" if stopped_for_max_total else "done",
        }
        repo_summaries.append(summary)
        if args.incremental:
            append_jsonl_object(repo_status_path, {**summary, "created_at_utc": utc_now()})
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        if stopped_for_max_total:
            break
        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    enriched.sort(key=lambda row: float(row.get("m_candidate_score") or 0), reverse=True)
    if not args.incremental:
        write_csv(args.output_csv, enriched)
        write_jsonl(args.output_jsonl, enriched)
    summary = {
        "created_at_utc": utc_now(),
        "targets": len(targets),
        "repo_summaries": repo_summaries,
        "candidate_rows": candidate_rows_seen,
        "enriched_rows": len(output_keys) if args.incremental else len(enriched),
        "new_enriched_rows": len(enriched),
        "file_errors": file_errors,
        "token_used": bool(token),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
        "repo_status_jsonl": str(repo_status_path),
        "incremental": args.incremental,
        "resume": args.resume,
        "stopped_for_max_total": stopped_for_max_total,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
