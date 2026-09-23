#!/usr/bin/env python3
"""Filter Step1 candidate pool against Step2-used commits.

Default behavior excludes SHA overlap.
Optional stricter mode also excludes repo overlap.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

CSV_FIELD_SIZE_LIMIT = 2**31 - 1

try:
    csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)
except OverflowError:
    csv.field_size_limit(sys.maxsize)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True, help="Step1 candidate pool csv.")
    parser.add_argument("--step2-source-csv", required=True, help="Step2 used source csv.")
    parser.add_argument(
        "--additional-exclusion-csv",
        action="append",
        default=[],
        help="Additional csvs whose SHA/Repo should also be excluded. Can be passed multiple times.",
    )
    parser.add_argument("--output-csv", required=True, help="Filtered Step1 candidate pool csv.")
    parser.add_argument("--report-json", default="", help="Optional filter report json path.")
    parser.add_argument(
        "--exclude-repo-overlap",
        action="store_true",
        help="Also exclude candidates whose repo overlaps with Step2 source repos.",
    )
    return parser.parse_args()


def normalize_repo(value: object) -> str:
    text = str(value or "").strip().lower().strip("/")
    if text.startswith("https://github.com/"):
        text = text.removeprefix("https://github.com/")
    return text


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def read_exclusion_sets(paths: list[str]) -> tuple[set[str], set[str], int]:
    sha_set: set[str] = set()
    repo_set: set[str] = set()
    file_count = 0
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise SystemExit(f"additional exclusion csv not found: {path}")
        rows, _ = read_csv_rows(path)
        file_count += 1
        for row in rows:
            sha = str(row.get("sha", "") or "").strip()
            repo = normalize_repo(row.get("repo", "") or row.get("resolved_repo", ""))
            if sha:
                sha_set.add(sha)
            if repo:
                repo_set.add(repo)
    return sha_set, repo_set, file_count


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_csv)
    step2_path = Path(args.step2_source_csv)
    output_path = Path(args.output_csv)
    report_path = Path(args.report_json) if args.report_json else None

    if not input_path.exists():
        raise SystemExit(f"input csv not found: {input_path}")
    if not step2_path.exists():
        raise SystemExit(f"step2 source csv not found: {step2_path}")

    input_rows, input_fields = read_csv_rows(input_path)
    step2_rows, _ = read_csv_rows(step2_path)
    additional_sha_set, additional_repo_set, additional_file_count = read_exclusion_sets(
        args.additional_exclusion_csv
    )

    step2_sha_set = {str(row.get("sha", "") or "").strip() for row in step2_rows if str(row.get("sha", "") or "").strip()}
    step2_repo_set = {normalize_repo(row.get("repo", "")) for row in step2_rows if normalize_repo(row.get("repo", ""))}
    excluded_sha_set = step2_sha_set | additional_sha_set
    excluded_repo_set = step2_repo_set | additional_repo_set

    kept: list[dict[str, str]] = []
    excluded_sha_overlap = 0
    excluded_repo_overlap = 0

    for row in input_rows:
        sha = str(row.get("sha", "") or "").strip()
        repo = normalize_repo(row.get("repo", "") or row.get("resolved_repo", ""))
        if sha and sha in excluded_sha_set:
            excluded_sha_overlap += 1
            continue
        if args.exclude_repo_overlap and repo and repo in excluded_repo_set:
            excluded_repo_overlap += 1
            continue
        kept.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=input_fields)
        writer.writeheader()
        writer.writerows(kept)

    payload = {
        "input_csv": input_path.as_posix(),
        "step2_source_csv": step2_path.as_posix(),
        "output_csv": output_path.as_posix(),
        "input_row_count": len(input_rows),
        "output_row_count": len(kept),
        "step2_row_count": len(step2_rows),
        "additional_exclusion_csv_count": additional_file_count,
        "excluded_sha_overlap_count": excluded_sha_overlap,
        "excluded_repo_overlap_count": excluded_repo_overlap,
        "exclude_repo_overlap": bool(args.exclude_repo_overlap),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
