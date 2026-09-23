#!/usr/bin/env python3
"""Validate the packaged M real-diff dataset without rebuilding it."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
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
    parser = argparse.ArgumentParser(description="Validate packaged M real-diff data.")
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--blocklist", type=Path, default=Path("D:/Multi-intent/m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--hard-b-csv", type=Path, default=Path("D:/Multi-intent/hard_b_existing_diff_package/data/usable_hard_b_with_real_diff.csv"))
    args = parser.parse_args()

    dataset = args.package_dir / "data" / "usable_m_with_real_diff.csv"
    rows = read_csv(dataset)
    keys = [(row.get("repo", ""), row.get("sha", "")) for row in rows]

    blocklist = set()
    if args.blocklist.exists():
        blocklist = {line.strip().lower() for line in args.blocklist.read_text(encoding="utf-8").splitlines() if line.strip()}
    hard_b_keys = key_set(args.hard_b_csv)

    checks = {
        "dataset": str(dataset),
        "rows": len(rows),
        "repo_count": len({row.get("repo", "") for row in rows if row.get("repo", "")}),
        "unique_repo_sha": len(set(keys)),
        "non_m": sum(1 for row in rows if row.get("llm_label") != "M"),
        "missing_diff_marker": sum(1 for row in rows if "diff --git " not in (row.get("git_diff") or "")),
        "fallback_or_truncated_diff": sum(
            1
            for row in rows
            if (row.get("git_diff") or "").lstrip().startswith("[Diff unavailable")
            or "[... truncated " in (row.get("git_diff") or "")
        ),
        "duplicate_repo_sha": len(keys) - len(set(keys)),
        "blocklist": str(args.blocklist),
        "blocklist_overlap": sum(1 for row in rows if row.get("repo", "").lower() in blocklist),
        "hard_b_csv": str(args.hard_b_csv) if args.hard_b_csv.exists() else "",
        "hard_b_overlap": len(set(keys) & hard_b_keys),
        "diff_source_counts": dict(Counter(row.get("diff_source", "") for row in rows)),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2, sort_keys=True))

    fatal = [
        "non_m",
        "missing_diff_marker",
        "fallback_or_truncated_diff",
        "duplicate_repo_sha",
        "blocklist_overlap",
        "hard_b_overlap",
    ]
    if any(checks[name] for name in fatal):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
