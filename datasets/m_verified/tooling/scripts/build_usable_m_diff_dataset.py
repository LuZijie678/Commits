#!/usr/bin/env python3
"""Build a usable M-commit dataset that requires real git diffs.

The label aggregation files intentionally keep only the model decision and
reasoning fields. Diff evidence lives in the enrichment batch files or can be
recovered from the local partial clones. This script joins those sources and
exports only M-labeled rows with a validated ``diff --git`` payload.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FALLBACK_PREFIX = "[Diff unavailable in blobless/local extraction."
REAL_DIFF_MARKER = "diff --git "

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

OUTPUT_FIELDS = [
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
    "llm_label",
    "llm_is_multi_intent",
    "llm_reason",
    "llm_intent_count_estimate",
    "llm_intent_summaries",
    "llm_evidence_from_message",
    "llm_evidence_from_diff",
    "llm_uncertainty",
    "llm_model",
    "llm_created_at_utc",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
    "file_count",
    "path_roles",
    "top_dirs",
    "changed_files",
    "shortstat",
    "git_diff",
    "diff_status",
    "diff_error",
    "diff_source",
    "diff_char_count_original",
    "diff_truncated",
]

MISSING_FIELDS = [
    "repo",
    "sha",
    "commit_url",
    "commit_date",
    "subject",
    "llm_label",
    "_evidence_mode",
    "_needs_diff_verify",
    "missing_reason",
    "git_error",
    "batch_sources_seen",
    "changed_files",
    "shortstat",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def iter_csv_paths(base: Path) -> list[Path]:
    if not base.exists():
        return []
    if base.is_file():
        return [base] if base.suffix.lower() == ".csv" else []
    return sorted(path for path in base.rglob("*.csv") if path.is_file())


def compact_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    original_len = len(text)
    if max_chars <= 0 or original_len <= max_chars:
        return text, False, original_len
    head = int(max_chars * 0.70)
    tail = max_chars - head
    omitted = original_len - max_chars
    compact = text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]
    return compact, True, original_len


def has_real_diff(text: str) -> bool:
    if not text:
        return False
    if text.lstrip().startswith(FALLBACK_PREFIX):
        return False
    return REAL_DIFF_MARKER in text


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
        return 124, out, err + f"\nTIMEOUT after {timeout}s"


def git_recover(row: dict[str, str], repos_dir: Path, timeout: int) -> dict[str, str]:
    repo = row.get("repo", "")
    sha = row.get("sha", "")
    repo_dir = repo_dir_for(repos_dir, repo)
    if not repo_dir.exists():
        return {"ok": "0", "error": f"repo_dir_missing: {repo_dir}"}

    code, diff, err = run_git(
        repo_dir,
        ["show", "--format=", "--no-ext-diff", "--no-color", "--no-renames", "--unified=1", sha],
        timeout,
    )
    if code != 0 or not has_real_diff(diff):
        return {
            "ok": "0",
            "error": (err[-1000:] if err else f"git_show_returncode={code}; no_real_diff_marker"),
        }

    _, files_out, _ = run_git(repo_dir, ["show", "--format=", "--name-only", "--no-renames", sha], timeout)
    _, shortstat, _ = run_git(repo_dir, ["show", "--format=", "--shortstat", "--no-renames", sha], timeout)
    changed_files = "\n".join(line.strip() for line in files_out.splitlines() if line.strip())
    return {
        "ok": "1",
        "git_diff": diff,
        "changed_files": changed_files,
        "shortstat": shortstat.strip(),
        "diff_status": "ok",
        "diff_error": "",
    }


def remote_diff_recover(row: dict[str, str], timeout: int, attempts: int) -> dict[str, str]:
    repo = row.get("repo", "")
    sha = row.get("sha", "")
    if not repo or not sha:
        return {"ok": "0", "error": "missing_repo_or_sha"}

    url = f"https://github.com/{repo}/commit/{sha}.diff"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "text/plain",
                    "User-Agent": "multi-intent-research-diff-recovery",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            diff = payload.decode("utf-8", errors="replace")
            if has_real_diff(diff):
                return {"ok": "1", "git_diff": diff, "url": url, "diff_status": "ok", "diff_error": ""}
            last_error = f"remote_diff_no_real_marker: {url}"
        except http.client.IncompleteRead as exc:
            partial = exc.partial or b""
            diff = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else str(partial)
            if has_real_diff(diff):
                return {
                    "ok": "1",
                    "git_diff": diff,
                    "url": url,
                    "diff_status": "ok",
                    "diff_error": f"IncompleteRead_partial_used: {exc}",
                }
            last_error = f"IncompleteRead: {exc}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            time.sleep(min(2 * attempt, 5))
    return {"ok": "0", "error": last_error or "remote_diff_failed", "url": url}


def discover_evidence_files(
    labels_dir: Path,
    raw_dir: Path,
    existing_output_csv: Path | None = None,
    extra_csvs: list[Path] | None = None,
) -> list[Path]:
    generated_names = {
        "usable_m_with_real_diff.csv",
        "m_missing_real_diff_to_recover.csv",
    }
    files: list[Path] = []
    for base in (labels_dir, raw_dir):
        for path in iter_csv_paths(base):
            name = path.name.lower()
            if name in generated_names:
                continue
            if "labeled" in name or "combined" in name or "current_m_candidates" in name:
                continue
            files.append(path)
    if existing_output_csv and existing_output_csv.exists():
        files.append(existing_output_csv)
    for path in extra_csvs or []:
        if path.exists():
            files.append(path)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def load_batch_evidence(paths: list[Path]) -> dict[tuple[str, str], list[dict[str, str]]]:
    evidence: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for path in paths:
        rows = read_csv(path)
        if not rows:
            continue
        fields = set(rows[0].keys())
        if not {"repo", "sha"}.issubset(fields):
            continue
        if not ({"git_diff", "changed_files", "shortstat"} & fields):
            continue
        for row in rows:
            repo = row.get("repo", "")
            sha = row.get("sha", "")
            if not repo or not sha:
                continue
            item = dict(row)
            item["_batch_source"] = str(path)
            evidence[(repo, sha)].append(item)
    return evidence


def choose_batch_real_diff(rows: list[dict[str, str]]) -> dict[str, str] | None:
    real = [
        row
        for row in rows
        if has_real_diff(row.get("git_diff", ""))
        and "fetch_truncated_for_labeling" not in (row.get("diff_error") or row.get("remote_diff_error") or "")
        and "[... truncated " not in row.get("git_diff", "")
    ]
    if not real:
        return None
    real.sort(key=lambda row: len(row.get("git_diff", "")), reverse=True)
    return real[0]


def choose_best_metadata(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}
    rows.sort(
        key=lambda row: (
            len(row.get("changed_files", "")),
            len(row.get("shortstat", "")),
            len(row.get("git_diff", "")),
        ),
        reverse=True,
    )
    return rows[0]


def merge_row(
    label_row: dict[str, str],
    diff_payload: str,
    metadata: dict[str, str],
    source: str,
    diff_error: str,
    max_diff_chars: int,
) -> dict[str, str]:
    compact_diff, truncated, original_len = compact_text(diff_payload, max_diff_chars)
    out = dict(label_row)
    for field in ("file_count", "path_roles", "top_dirs", "changed_files", "shortstat"):
        if metadata.get(field):
            out[field] = metadata.get(field, "")
    out.update(
        {
            "git_diff": compact_diff,
            "diff_status": "ok",
            "diff_error": diff_error,
            "diff_source": source,
            "diff_char_count_original": str(original_len),
            "diff_truncated": "1" if truncated else "0",
        }
    )
    return {field: out.get(field, "") for field in OUTPUT_FIELDS}


def build_dataset(args: argparse.Namespace) -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    label_rows = [row for row in read_csv(args.m_candidates_csv) if row.get("llm_label") == "M"]
    evidence_files = discover_evidence_files(args.labels_dir, args.raw_dir, args.output_csv, args.extra_csv)
    batch_evidence = load_batch_evidence(evidence_files)

    usable: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    source_counts: Counter[str] = Counter()
    initial_evidence_counts: Counter[str] = Counter(row.get("_evidence_mode", "") for row in label_rows)

    seen: set[tuple[str, str]] = set()
    for label_row in label_rows:
        key = (label_row.get("repo", ""), label_row.get("sha", ""))
        if key in seen:
            continue
        seen.add(key)
        repo, sha = key
        evidence_rows = batch_evidence.get(key, [])
        best_meta = choose_best_metadata(list(evidence_rows))

        batch_real = choose_batch_real_diff(evidence_rows)
        if batch_real:
            row = merge_row(
                label_row,
                batch_real.get("git_diff", ""),
                batch_real,
                "batch_csv_real_diff",
                "",
                args.diff_max_chars,
            )
            usable.append(row)
            source_counts[row["diff_source"]] += 1
            continue

        recovered = git_recover(label_row, args.repos_dir, args.timeout)
        if recovered.get("ok") == "1":
            metadata = dict(best_meta)
            if recovered.get("changed_files"):
                metadata["changed_files"] = recovered["changed_files"]
            if recovered.get("shortstat"):
                metadata["shortstat"] = recovered["shortstat"]
            row = merge_row(
                label_row,
                recovered["git_diff"],
                metadata,
                "local_git_show",
                "",
                args.diff_max_chars,
            )
            usable.append(row)
            source_counts[row["diff_source"]] += 1
            continue

        remote = remote_diff_recover(label_row, args.remote_timeout, args.remote_attempts) if args.allow_remote_diff else {"ok": "0", "error": "remote_diff_disabled"}
        if remote.get("ok") == "1":
            row = merge_row(
                label_row,
                remote["git_diff"],
                best_meta,
                "github_commit_diff_url",
                recovered.get("error", ""),
                args.diff_max_chars,
            )
            usable.append(row)
            source_counts[row["diff_source"]] += 1
            continue

        missing_row = {field: label_row.get(field, "") for field in MISSING_FIELDS}
        missing_row.update(
            {
                "missing_reason": "no_real_diff_from_local_git_remote_or_batch",
                "git_error": recovered.get("error", "") + ("\nremote_diff_error: " + remote.get("error", "") if remote.get("error") else ""),
                "batch_sources_seen": "\n".join(sorted({row.get("_batch_source", "") for row in evidence_rows if row.get("_batch_source")})),
                "changed_files": best_meta.get("changed_files", ""),
                "shortstat": best_meta.get("shortstat", ""),
            }
        )
        missing.append(missing_row)

    usable.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))
    missing.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))

    repo_counts = Counter(row["repo"] for row in usable)
    manifest = {
        "created_at_utc": utc_now(),
        "goal": "M-labeled commits with validated real git diff evidence for Step3 preparation",
        "m_candidates_csv": str(args.m_candidates_csv),
        "labels_dir": str(args.labels_dir),
        "raw_dir": str(args.raw_dir),
        "repos_dir": str(args.repos_dir),
        "evidence_files_scanned": [str(path) for path in evidence_files],
        "total_m_label_rows": len(label_rows),
        "unique_m_commits": len(seen),
        "usable_real_diff_count": len(usable),
        "missing_real_diff_count": len(missing),
        "initial_m_evidence_mode_counts": dict(initial_evidence_counts),
        "diff_source_counts": dict(source_counts),
        "usable_repo_count": len(repo_counts),
        "usable_repo_counts": dict(repo_counts.most_common()),
        "validation_rules": {
            "llm_label": "M",
            "git_diff_must_contain": REAL_DIFF_MARKER.strip(),
            "fallback_prefix_excluded": FALLBACK_PREFIX,
            "remote_diff_fallback": "GitHub public commit .diff URL, validated by the same marker rule",
        },
        "outputs": {
            "csv": str(args.output_csv),
            "jsonl": str(args.output_jsonl),
            "missing_csv": str(args.missing_csv),
            "manifest": str(args.manifest),
        },
    }
    return usable, missing, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a usable M dataset with real diffs only.")
    parser.add_argument("--m-candidates-csv", type=Path, default=Path("m_mining_gitlog_pilot/labels/gitlog_current_m_candidates.csv"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--raw-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--output-csv", type=Path, default=Path("m_mining_gitlog_pilot/labels/usable_m_with_real_diff.csv"))
    parser.add_argument("--output-jsonl", type=Path, default=Path("m_mining_gitlog_pilot/labels/usable_m_with_real_diff.jsonl"))
    parser.add_argument("--missing-csv", type=Path, default=Path("m_mining_gitlog_pilot/labels/m_missing_real_diff_to_recover.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("m_mining_gitlog_pilot/labels/usable_m_with_real_diff_manifest.json"))
    parser.add_argument("--extra-csv", type=Path, action="append", default=[])
    parser.add_argument("--diff-max-chars", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--allow-remote-diff", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--remote-timeout", type=int, default=90)
    parser.add_argument("--remote-attempts", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    usable, missing, manifest = build_dataset(args)
    write_csv(args.output_csv, usable, OUTPUT_FIELDS)
    write_jsonl(args.output_jsonl, usable)
    write_csv(args.missing_csv, missing, MISSING_FIELDS)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
