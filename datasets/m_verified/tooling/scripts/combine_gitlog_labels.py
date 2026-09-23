#!/usr/bin/env python3
"""Combine all git-log pilot LLM label CSVs into current label artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

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
    "llm_error",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
]

GENERATED_EVIDENCE_NAMES = {
    "usable_m_with_real_diff.csv",
    "m_missing_real_diff_to_recover.csv",
    "gitlog_all_pilot_labels_combined.csv",
    "gitlog_current_m_candidates.csv",
}


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


def iter_csv_paths(base: Path) -> list[Path]:
    if not base.exists():
        return []
    if base.is_file():
        return [base] if base.suffix.lower() == ".csv" else []
    return sorted(path for path in base.rglob("*.csv") if path.is_file())


def discover_label_files(labels_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in labels_dir.rglob("*_labeled.csv")
            if path.name not in {"gitlog_all_pilot_labels_combined.csv", "gitlog_current_m_candidates.csv"}
        ],
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def discover_seed_label_files(output_combined: Path, explicit_paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    seed_paths: list[Path] = []
    for index, path in enumerate([output_combined, *explicit_paths]):
        if not path.exists():
            continue
        if index == 0 and path.suffix.lower() != ".csv":
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        seed_paths.append(path)
    return seed_paths


def discover_evidence_files(labels_dir: Path, raw_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for base in (labels_dir, raw_dir):
        for path in iter_csv_paths(base):
            name = path.name
            lower = name.lower()
            if name in GENERATED_EVIDENCE_NAMES:
                continue
            if "labeled" in lower or "combined" in lower or "current_m_candidates" in lower:
                continue
            paths.append(path)
    return paths


def load_evidence_modes(paths: list[Path]) -> dict[tuple[str, str], str]:
    modes: dict[tuple[str, str], str] = {}
    for path in paths:
        try:
            rows = read_csv(path)
        except Exception:
            continue
        if not rows:
            continue
        fields = set(rows[0].keys())
        if not {"repo", "sha"}.issubset(fields):
            continue
        has_evidence = {"git_diff", "diff_status", "evidence_mode", "changed_files"} & fields
        if not has_evidence:
            continue
        for row in rows:
            repo, sha = row.get("repo", ""), row.get("sha", "")
            if not repo or not sha:
                continue
            mode = ""
            if row.get("evidence_mode") == "filelist_fallback":
                mode = "filelist_fallback"
            elif row.get("diff_status") == "ok" or "diff --git " in (row.get("git_diff") or "") or row.get("evidence_mode") == "diff":
                mode = "diff_or_diff_preferred"
            elif row.get("changed_files"):
                mode = "filelist_fallback"
            if mode:
                key = (repo, sha)
                if modes.get(key) != "diff_or_diff_preferred":
                    modes[key] = mode
    return modes


def combine(args: argparse.Namespace) -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    label_files = discover_label_files(args.labels_dir)
    seed_label_files = discover_seed_label_files(args.output_combined, list(args.seed_label_csv))
    evidence_modes = load_evidence_modes(discover_evidence_files(args.labels_dir, args.raw_dir))
    by_key: dict[tuple[str, str], dict[str, str]] = {}

    for path in [*seed_label_files, *label_files]:
        for row in read_csv(path):
            repo, sha = row.get("repo", ""), row.get("sha", "")
            if not repo or not sha:
                continue
            key = (repo, sha)
            out = {field: row.get(field, "") for field in OUTPUT_FIELDS}
            out["_source_file"] = str(path)
            out["_evidence_mode"] = row.get("_evidence_mode") or evidence_modes.get(key, "unknown")
            out["_needs_diff_verify"] = "1" if out["_evidence_mode"] != "diff_or_diff_preferred" else "0"
            by_key[key] = out

    combined = list(by_key.values())
    combined.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))
    m_rows = [row for row in combined if row.get("llm_label") == "M"]

    label_counts = Counter(row.get("llm_label", "") for row in combined)
    evidence_counts = Counter(row.get("_evidence_mode", "") for row in combined)
    m_evidence_counts = Counter(row.get("_evidence_mode", "") for row in m_rows)
    repo_stats = []
    for repo, labeled_count in Counter(row["repo"] for row in combined).most_common():
        m_count = sum(1 for row in m_rows if row["repo"] == repo)
        if m_count:
            repo_stats.append({"repo": repo, "labeled": labeled_count, "m": m_count, "m_rate": m_count / labeled_count})
    repo_stats.sort(key=lambda item: (-item["m"], item["repo"]))
    summary = {
        "created_at_utc": utc_now(),
        "seed_label_files": [str(path) for path in seed_label_files],
        "label_files": [str(path) for path in label_files],
        "combined_csv": str(args.output_combined),
        "m_candidates_csv": str(args.output_m),
        "label_counts": dict(label_counts),
        "evidence_counts": dict(evidence_counts),
        "total_labeled_unique": len(combined),
        "m_count": len(m_rows),
        "m_rate": len(m_rows) / len(combined) if combined else 0,
        "m_repo_count": len({row["repo"] for row in m_rows}),
        "m_evidence_counts": dict(m_evidence_counts),
        "repo_count_labeled": len({row["repo"] for row in combined}),
        "repo_stats": repo_stats[:40],
    }
    return combined, m_rows, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine gitlog pilot labels.")
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--raw-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--seed-label-csv", type=Path, action="append", default=[])
    parser.add_argument("--output-combined", type=Path, default=Path("m_mining_gitlog_pilot/labels/gitlog_all_pilot_labels_combined.csv"))
    parser.add_argument("--output-m", type=Path, default=Path("m_mining_gitlog_pilot/labels/gitlog_current_m_candidates.csv"))
    parser.add_argument("--summary", type=Path, default=Path("m_mining_gitlog_pilot/labels/gitlog_all_pilot_labels_combined_summary.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    combined, m_rows, summary = combine(args)
    write_csv(args.output_combined, combined, OUTPUT_FIELDS)
    write_csv(args.output_m, m_rows, OUTPUT_FIELDS)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
