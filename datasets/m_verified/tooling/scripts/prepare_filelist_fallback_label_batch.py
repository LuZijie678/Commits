#!/usr/bin/env python3
"""Prepare label batches where missing diffs fall back to changed-file evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
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


def fallback_evidence(row: dict) -> str:
    status = row.get("diff_status", "") or "unknown"
    shortstat = row.get("shortstat", "") or ""
    roles = row.get("path_roles", "") or ""
    top_dirs = row.get("top_dirs", "") or ""
    changed_files = row.get("changed_files", "") or ""
    existing_diff = row.get("git_diff", "") or ""
    if existing_diff.strip():
        return existing_diff
    parts = [
        "[Diff unavailable in blobless/local extraction. Use this changed-file evidence only.]",
        f"diff_status: {status}",
    ]
    if shortstat:
        parts.append(f"shortstat: {shortstat}")
    if roles:
        parts.append(f"path_roles: {roles}")
    if top_dirs:
        parts.append(f"top_dirs: {top_dirs}")
    if changed_files:
        parts.append("changed_files:\n" + changed_files)
    return "\n".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare fallback-evidence label batch for missing-diff candidates.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--missing-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labeled = load_labeled(args.labels_dir)
    rows = []
    for row in read_csv(args.input_csv):
        key = (row.get("repo", ""), row.get("sha", ""))
        if key in labeled:
            continue
        if args.missing_only and (row.get("diff_status") == "ok"):
            continue
        out = dict(row)
        out["git_diff"] = fallback_evidence(row)
        out["evidence_mode"] = "diff" if row.get("diff_status") == "ok" else "filelist_fallback"
        rows.append(out)
    rows.sort(key=lambda item: float(item.get("m_candidate_score") or item.get("precision_score") or item.get("message_score") or 0), reverse=True)
    if args.limit > 0:
        rows = rows[: args.limit]
    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(args.output_csv, rows, fieldnames)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
        "selected": len(rows),
        "missing_only": args.missing_only,
        "evidence_counts": {},
    }
    for row in rows:
        mode = row.get("evidence_mode", "")
        summary["evidence_counts"][mode] = summary["evidence_counts"].get(mode, 0) + 1
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
