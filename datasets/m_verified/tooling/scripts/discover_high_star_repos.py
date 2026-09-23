#!/usr/bin/env python3
"""Discover high-star GitHub repositories for M mining coverage.

The output is filtered against the Step1/Step2 repo blocklist and, by default,
against repos already cloned in the current M-mining pilot. This script only
discovers targets; it does not clone or fetch diffs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SEARCH_QUERIES = [
    "stars:>50000 fork:false archived:false",
    "stars:20000..50000 fork:false archived:false language:Python",
    "stars:5000..20000 fork:false archived:false language:Python",
    "stars:20000..50000 fork:false archived:false language:JavaScript",
    "stars:5000..20000 fork:false archived:false language:JavaScript",
    "stars:20000..50000 fork:false archived:false language:TypeScript",
    "stars:5000..20000 fork:false archived:false language:TypeScript",
    "stars:15000..50000 fork:false archived:false language:Go",
    "stars:5000..15000 fork:false archived:false language:Go",
    "stars:10000..50000 fork:false archived:false language:Rust",
    "stars:3000..10000 fork:false archived:false language:Rust",
    "stars:15000..50000 fork:false archived:false language:Java",
    "stars:5000..15000 fork:false archived:false language:Java",
    "stars:10000..50000 fork:false archived:false language:C++",
    "stars:3000..10000 fork:false archived:false language:C++",
    "stars:10000..50000 fork:false archived:false language:C",
    "stars:3000..10000 fork:false archived:false language:C",
    "stars:5000..50000 fork:false archived:false language:C#",
    "stars:5000..50000 fork:false archived:false language:PHP",
    "stars:5000..50000 fork:false archived:false language:Ruby",
    "stars:5000..50000 fork:false archived:false language:Swift",
    "stars:3000..50000 fork:false archived:false language:Kotlin",
    "stars:3000..50000 fork:false archived:false language:Dart",
    "stars:10000..50000 fork:false archived:false topic:database",
    "stars:5000..50000 fork:false archived:false topic:cli",
    "stars:5000..50000 fork:false archived:false topic:web-framework",
    "stars:5000..50000 fork:false archived:false topic:machine-learning",
]

CLASSIC_REPOS = [
    "torvalds/linux",
    "git/git",
    "python/cpython",
    "nodejs/node",
    "llvm/llvm-project",
    "curl/curl",
    "openssl/openssl",
    "redis/redis",
    "postgres/postgres",
    "mysql/mysql-server",
    "mongodb/mongo",
    "apache/httpd",
    "apache/spark",
    "apache/flink",
    "apache/arrow",
    "apache/beam",
    "apache/kafka",
    "kubernetes/kubernetes",
    "tensorflow/tensorflow",
    "django/django",
    "rails/rails",
    "laravel/framework",
    "symfony/symfony",
    "php/php-src",
    "ruby/ruby",
    "vim/vim",
    "neovim/neovim",
    "bitcoin/bitcoin",
    "godotengine/godot",
    "grpc/grpc",
    "opencv/opencv",
    "numpy/numpy",
    "pandas-dev/pandas",
    "scikit-learn/scikit-learn",
    "psf/requests",
]

FIELDS = [
    "repo",
    "stars",
    "language",
    "description",
    "created_at",
    "pushed_at",
    "source",
    "query",
]

NOISE_RE = re.compile(
    r"(^|[-_/])(awesome|roadmap|interview|interviews|tutorial|tutorials|book|books|guide|guides|"
    r"cheatsheet|cheatsheets|course|courses|learn|learning|list|lists|resources?|examples?|30-days|"
    r"jobs?|internships?|public-apis)([-_/]|$)",
    re.I,
)
DESCRIPTION_NOISE_RE = re.compile(
    r"\b(awesome|curated list|roadmap|interview questions|tutorial|book|guide|cheatsheet|course|"
    r"learning resource|collection of|public apis|jobs|internships)\b",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_lines(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.startswith("#")}


def load_entries(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def resolve_search_queries(query_file: Path | None) -> list[str]:
    queries = list(SEARCH_QUERIES)
    seen = {query.strip() for query in queries}
    for query in load_entries(query_file):
        if query not in seen:
            queries.append(query)
            seen.add(query)
    return queries


def load_extra_target_rows(
    targets_file: Path | None,
    excluded: set[str],
    existing: set[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set(existing)
    for repo in load_entries(targets_file):
        repo_key = repo.lower()
        if not repo_key or repo_key in excluded or repo_key in seen:
            continue
        rows.append(
            {
                "repo": repo,
                "stars": "",
                "language": "",
                "description": "",
                "created_at": "",
                "pushed_at": "",
                "source": "extra_targets_file",
                "query": "",
            }
        )
        seen.add(repo_key)
    return rows


def is_code_like(row: dict[str, str]) -> bool:
    repo = row.get("repo", "")
    description = row.get("description", "")
    language = row.get("language", "")
    if NOISE_RE.search(repo) or DESCRIPTION_NOISE_RE.search(description):
        return False
    if not language and row.get("source") != "curated_classic":
        return False
    return True


def load_local_repos(repos_dir: Path) -> set[str]:
    if not repos_dir.exists():
        return set()
    repos = set()
    for path in repos_dir.iterdir():
        if path.is_dir() and "__" in path.name:
            repos.add(path.name.replace("__", "/").lower())
    return repos


def request_json(url: str, token: str, timeout: int) -> tuple[object, dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "multi-intent-research-high-star-discovery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8")), dict(response.headers)


def is_retryable_search_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {403, 429} or 500 <= exc.code <= 599
    return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))


def search_repos(
    query: str,
    per_page: int,
    page: int,
    token: str,
    timeout: int,
    attempts: int = 3,
    retry_sleep_sec: float = 2.0,
) -> tuple[list[dict], dict[str, str], str, int]:
    params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": per_page, "page": page})
    url = "https://api.github.com/search/repositories?" + params
    max_attempts = max(1, int(attempts))
    last_error = ""
    last_headers: dict[str, str] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            data, headers = request_json(url, token, timeout)
            if not isinstance(data, dict):
                return [], headers, "unexpected_response", attempt
            return list(data.get("items") or []), headers, "", attempt
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, urllib.error.HTTPError):
                last_headers = dict(exc.headers or {})
            if attempt >= max_attempts or not is_retryable_search_error(exc):
                return [], last_headers, last_error, attempt
            if retry_sleep_sec > 0:
                time.sleep(min(retry_sleep_sec * attempt, max(retry_sleep_sec, 6.0)))
    return [], last_headers, last_error, max_attempts


def row_from_item(item: dict, source: str, query: str) -> dict[str, str]:
    return {
        "repo": str(item.get("full_name") or ""),
        "stars": str(item.get("stargazers_count") or ""),
        "language": str(item.get("language") or ""),
        "description": str(item.get("description") or ""),
        "created_at": str(item.get("created_at") or ""),
        "pushed_at": str(item.get("pushed_at") or ""),
        "source": source,
        "query": query,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover high-star repos for M mining.")
    parser.add_argument("--output-txt", type=Path, default=Path("m_mining_gitlog_pilot/repo_targets_high_star_new.txt"))
    parser.add_argument("--output-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/high_star_repo_discovery.csv"))
    parser.add_argument("--summary", type=Path, default=Path("m_mining_gitlog_pilot/raw/high_star_repo_discovery_summary.json"))
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--per-query", type=int, default=80)
    parser.add_argument("--pages-per-query", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep-sec", type=float, default=6.2)
    parser.add_argument("--search-attempts", type=int, default=3)
    parser.add_argument("--search-retry-sleep-sec", type=float, default=2.0)
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--include-local", action="store_true")
    parser.add_argument("--exclude-list", type=Path, action="append", default=[])
    parser.add_argument("--query-file", type=Path, default=None)
    parser.add_argument("--extra-targets-file", type=Path, default=None)
    parser.add_argument("--code-like-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get(args.github_token_env, "").strip() if args.github_token_env else ""
    blocklist = load_lines(args.blocklist)
    extra_excluded = set()
    for path in args.exclude_list:
        extra_excluded |= load_lines(path)
    local_repos = set() if args.include_local else load_local_repos(args.repos_dir)
    excluded = blocklist | local_repos | extra_excluded
    rows_by_repo: dict[str, dict[str, str]] = {}
    query_summaries: list[dict[str, str | int]] = []

    search_queries = resolve_search_queries(args.query_file)
    for query in search_queries:
        for page in range(1, max(1, args.pages_per_query) + 1):
            items, headers, error, attempts_used = search_repos(
                query,
                args.per_query,
                page,
                token,
                args.timeout,
                attempts=args.search_attempts,
                retry_sleep_sec=args.search_retry_sleep_sec,
            )
            kept = 0
            for item in items:
                row = row_from_item(item, "github_search", query)
                repo_key = row["repo"].lower()
                if not repo_key or repo_key in excluded:
                    continue
                if args.code_like_only and not is_code_like(row):
                    continue
                if repo_key not in rows_by_repo:
                    rows_by_repo[repo_key] = row
                    kept += 1
            query_summaries.append(
                {
                    "query": query,
                    "page": page,
                    "items": len(items),
                    "kept_new": kept,
                    "attempts": attempts_used,
                    "error": error,
                    "rate_remaining": headers.get("X-RateLimit-Remaining", ""),
                }
            )
            print(json.dumps(query_summaries[-1], ensure_ascii=False, sort_keys=True), flush=True)
            if error or len(items) < args.per_query:
                break
            if not token and args.sleep_sec > 0:
                time.sleep(args.sleep_sec)

    for repo in CLASSIC_REPOS:
        repo_key = repo.lower()
        if repo_key in excluded or repo_key in rows_by_repo:
            continue
        rows_by_repo[repo_key] = {
            "repo": repo,
            "stars": "",
            "language": "",
            "description": "",
            "created_at": "",
            "pushed_at": "",
            "source": "curated_classic",
            "query": "",
        }

    extra_rows = load_extra_target_rows(args.extra_targets_file, excluded, set(rows_by_repo))
    ranked_rows = list(rows_by_repo.values())
    ranked_rows.sort(key=lambda row: (0 if row.get("stars") else 1, -(int(row["stars"]) if row.get("stars", "").isdigit() else 0), row["repo"].lower()))
    rows = extra_rows + ranked_rows
    if args.limit > 0:
        rows = rows[: args.limit]

    args.output_txt.parent.mkdir(parents=True, exist_ok=True)
    args.output_txt.write_text("\n".join(row["repo"] for row in rows) + "\n", encoding="utf-8")
    write_csv(args.output_csv, rows)
    summary = {
        "created_at_utc": utc_now(),
        "output_txt": str(args.output_txt),
        "output_csv": str(args.output_csv),
        "repo_count": len(rows),
        "blocklist_count": len(blocklist),
        "excluded_local_count": len(local_repos),
        "token_used": bool(token),
        "search_query_count": len(search_queries),
        "extra_target_count": len(extra_rows),
        "query_file": str(args.query_file) if args.query_file else "",
        "extra_targets_file": str(args.extra_targets_file) if args.extra_targets_file else "",
        "query_summaries": query_summaries,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
