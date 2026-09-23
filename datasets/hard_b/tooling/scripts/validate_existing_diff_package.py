#!/usr/bin/env python3
"""Validate the packaged hard-B real-diff dataset without rebuilding it."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def key_set(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    return {(row.get("repo", ""), row.get("sha", "")) for row in read_csv(path) if row.get("repo") and row.get("sha")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate packaged hard-B real-diff data.")
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--m-csv", type=Path, default=Path("D:/Multi-intent/m_mining_gitlog_pilot/labels/usable_m_with_real_diff.csv"))
    parser.add_argument("--blocklist", type=Path, default=Path("D:/Multi-intent/m_mining_feasibility/used_repo_blocklist.txt"))
    args = parser.parse_args()

    dataset = args.package_dir / "data" / "usable_hard_b_with_real_diff.csv"
    rows = read_csv(dataset)
    keys = [(row.get("repo", ""), row.get("sha", "")) for row in rows]
    m_keys = key_set(args.m_csv)
    blocklist = set()
    if args.blocklist.exists():
        blocklist = {line.strip().lower() for line in args.blocklist.read_text(encoding="utf-8").splitlines() if line.strip()}

    checks = {
        "dataset": str(dataset),
        "rows": len(rows),
        "repo_count": len({row.get("repo", "") for row in rows if row.get("repo", "")}),
        "unique_repo_sha": len(set(keys)),
        "non_b": sum(1 for row in rows if row.get("llm_label") != "B"),
        "missing_diff_marker": sum(1 for row in rows if "diff --git " not in (row.get("git_diff") or "")),
        "fallback_or_truncated_diff": sum(
            1
            for row in rows
            if (row.get("git_diff") or "").lstrip().startswith("[Diff unavailable")
            or "[... truncated " in (row.get("git_diff") or "")
        ),
        "duplicate_repo_sha": len(keys) - len(set(keys)),
        "m_csv": str(args.m_csv),
        "m_pool_rows_read": len(m_keys),
        "m_overlap": len(set(keys) & m_keys),
        "blocklist": str(args.blocklist),
        "blocklist_overlap": sum(1 for row in rows if row.get("repo", "").lower() in blocklist),
        "pilot_only_rows": sum(1 for row in rows if row.get("pilot_only") == "1"),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2, sort_keys=True))

    fatal = [
        "non_b",
        "missing_diff_marker",
        "fallback_or_truncated_diff",
        "duplicate_repo_sha",
        "m_overlap",
        "blocklist_overlap",
    ]
    if any(checks[name] for name in fatal):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
