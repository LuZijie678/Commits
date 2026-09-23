#!/usr/bin/env python3
"""Enrich an existing candidate CSV by fetching public GitHub commit .diff URLs."""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def compact_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.70)
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]


def read_limited(response, max_bytes: int) -> tuple[bytes, bool]:
    if max_bytes <= 0:
        return response.read(), False
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while total < max_bytes:
        chunk = response.read(min(65536, max_bytes - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total >= max_bytes:
        truncated = True
    return b"".join(chunks), truncated


def fetch_diff(repo: str, sha: str, timeout: int, attempts: int, fetch_max_bytes: int) -> tuple[str, str]:
    url = f"https://github.com/{repo}/commit/{sha}.diff"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "multi-intent-research-diff-enrich"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload, truncated = read_limited(response, fetch_max_bytes)
                text = payload.decode("utf-8", errors="replace")
            if "diff --git " in text:
                return text, "fetch_truncated_for_labeling" if truncated else ""
            last_error = "no_diff_marker"
        except http.client.IncompleteRead as exc:
            partial = exc.partial or b""
            text = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else str(partial)
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


def parse_diff(diff: str) -> tuple[list[str], str, Counter[str], list[str]]:
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


def base_score(row: dict[str, str]) -> float:
    for field in ("_selection_score", "precision_score", "message_score", "m_candidate_score"):
        try:
            value = float(row.get(field) or 0.0)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return str(row.get("repo") or ""), str(row.get("sha") or "")


def enrich_row(row: dict[str, str], diff_max_chars: int, timeout: int, attempts: int, max_files: int, fetch_max_bytes: int) -> dict[str, str] | None:
    repo, sha = row.get("repo", ""), row.get("sha", "")
    diff, error = fetch_diff(repo, sha, timeout, attempts, fetch_max_bytes)
    if not diff:
        out = dict(row)
        out.update({"git_diff": "", "diff_status": "missing_diff", "diff_error": error, "evidence_mode": "missing_diff"})
        return {field: out.get(field, "") for field in OUTPUT_FIELDS}
    files, shortstat, roles, top_dirs = parse_diff(diff)
    if not files or len(files) > max_files:
        return None
    score = base_score(row)
    reasons = [row.get("precision_reasons") or row.get("message_reasons") or row.get("m_candidate_reasons") or ""]
    if len(files) >= 4:
        score += min(8, len(files) / 3)
        reasons.append(f"file_count={len(files)}")
    if len(roles) >= 3:
        score += 6
        reasons.append("cross_file_roles=" + "+".join(sorted(roles)))
    elif len(roles) == 2:
        score += 3
        reasons.append("cross_file_roles=" + "+".join(sorted(roles)))
    if "source" in roles and "test" in roles and len(roles) >= 3:
        score += 2
        reasons.append("source_test_plus_extra_role")
    if len(top_dirs) >= 3:
        score += 4
        reasons.append(f"multi_top_dirs={len(top_dirs)}")
    if roles.get("generated_or_vendor", 0) >= max(3, len(files) // 2):
        score -= 10
        reasons.append("many_generated_or_vendor_files")
    out = dict(row)
    out.update({
        "candidate_layer": "candidate_csv_remote_diff_enriched",
        "m_candidate_score": f"{score:.3f}",
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


def enrich_rows(
    rows: list[dict[str, str]],
    args: argparse.Namespace,
    existing_keys: set[tuple[str, str]],
    on_result=None,
) -> tuple[list[dict[str, str]], int]:
    pending: list[tuple[int, dict[str, str]]] = []
    seen_keys = set(existing_keys)
    for index, row in enumerate(rows):
        key = row_key(row)
        if not key[0] or not key[1] or key in seen_keys:
            continue
        pending.append((index, row))
        seen_keys.add(key)

    skipped = 0
    if not pending:
        return [], skipped

    def run_one(row: dict[str, str]) -> dict[str, str] | None:
        return enrich_row(row, args.diff_max_chars, args.timeout, args.attempts, args.max_files, args.fetch_max_bytes)

    if int(getattr(args, "workers", 1) or 1) <= 1:
        ordered: list[dict[str, str]] = []
        for _, row in pending:
            out = run_one(row)
            if out is None:
                skipped += 1
                continue
            ordered.append(out)
            if on_result is not None:
                on_result(out, len(ordered), skipped)
        return ordered, skipped

    ordered_by_index: dict[int, dict[str, str]] = {}
    workers = max(1, int(getattr(args, "workers", 1) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {executor.submit(run_one, row): index for index, row in pending}
        completed = 0
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            out = future.result()
            completed += 1
            if out is None:
                skipped += 1
                continue
            ordered_by_index[index] = out
            if on_result is not None:
                on_result(out, completed - skipped, skipped)
    ordered = [ordered_by_index[index] for index, _ in pending if index in ordered_by_index]
    return ordered, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich candidate rows with remote GitHub .diff evidence.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--diff-max-chars", type=int, default=30000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=220)
    parser.add_argument("--fetch-max-bytes", type=int, default=500000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--incremental", action="store_true", help="Append enriched rows as soon as they are produced.")
    parser.add_argument("--resume", action="store_true", help="Skip commit rows already present in --output-csv.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_csv(args.input_csv)
    rows.sort(key=base_score, reverse=True)
    if args.limit > 0:
        rows = rows[: args.limit]
    existing_rows = read_csv(args.output_csv) if args.resume and args.output_csv.exists() else []
    output_keys = load_output_keys(args.output_csv) if args.resume else set()
    selected_keys: set[tuple[str, str]] = set()
    resume_skipped = 0
    dedupe_skipped = 0
    for row in rows:
        key = row_key(row)
        if key in output_keys:
            resume_skipped += 1
            continue
        if key in selected_keys:
            dedupe_skipped += 1
            continue
        if key[0] and key[1]:
            selected_keys.add(key)

    progress = {"completed": 0}

    def on_result(row: dict[str, str], completed: int, skipped: int) -> None:
        if args.incremental:
            append_csv_row(args.output_csv, row)
            append_jsonl_row(args.output_jsonl, row)
        progress["completed"] = completed + skipped
        if progress["completed"] % 10 == 0:
            total = len(selected_keys)
            print(
                f"enriched={completed} skipped={skipped} resume_skipped={resume_skipped} dedupe_skipped={dedupe_skipped} index={progress['completed']}/{total}",
                flush=True,
            )

    new_rows, skipped = enrich_rows(rows, args, output_keys, on_result=on_result)
    if args.incremental:
        enriched = list(existing_rows) + new_rows
    else:
        enriched = list(existing_rows) + new_rows
    if not args.incremental:
        enriched.sort(key=lambda row: float(row.get("m_candidate_score") or 0.0), reverse=True)
        write_csv(args.output_csv, enriched)
        write_jsonl(args.output_jsonl, enriched)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "selected": len(rows),
        "enriched": len(enriched),
        "new_enriched_rows": len(new_rows),
        "skipped": skipped,
        "resume_skipped": resume_skipped,
        "dedupe_skipped": dedupe_skipped,
        "diff_ok": sum(1 for row in enriched if row.get("diff_status") == "ok"),
        "diff_missing": sum(1 for row in enriched if row.get("diff_status") != "ok"),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
        "incremental": args.incremental,
        "resume": args.resume,
        "workers": int(getattr(args, "workers", 1) or 1),
    }
    if args.incremental:
        current_rows = read_csv(args.output_csv) if args.output_csv.exists() else []
        summary["diff_ok"] = sum(1 for row in current_rows if row.get("diff_status") == "ok")
        summary["diff_missing"] = sum(1 for row in current_rows if row.get("diff_status") != "ok")
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
