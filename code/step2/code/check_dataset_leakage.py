#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from experiment_tooling_common import dataset_repo_value, dataset_sha_value, read_dataset_rows, write_json


def load_dataset(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows, warnings = read_dataset_rows(path)
    return rows, warnings


def summarize_dataset(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    repos = {dataset_repo_value(row) for row in rows if dataset_repo_value(row)}
    shas = {dataset_sha_value(row) for row in rows if dataset_sha_value(row)}
    return {
        "name": name,
        "rows": len(rows),
        "sha_count": len(shas),
        "repo_count": len(repos),
    }


def build_leakage_report(
    *,
    dataset_specs: list[tuple[str, Path]],
    require_sha_disjoint: bool,
    require_repo_disjoint: bool,
    max_examples: int,
) -> dict[str, Any]:
    warnings: list[str] = []
    datasets: dict[str, list[dict[str, Any]]] = {}
    dataset_summary: dict[str, Any] = {}
    for name, path in dataset_specs:
        rows, row_warnings = load_dataset(path)
        warnings.extend([f"{name}:{item}" for item in row_warnings])
        datasets[name] = rows
        dataset_summary[name] = summarize_dataset(name, rows)
        if all(not dataset_sha_value(row) for row in rows):
            warnings.append(f"{name}:missing_sha_field")
        if all(not dataset_repo_value(row) for row in rows):
            warnings.append(f"{name}:missing_repo_field")

    pairwise: list[dict[str, Any]] = []
    passed = True
    for left_name, right_name in combinations([name for name, _ in dataset_specs], 2):
        left_rows = datasets[left_name]
        right_rows = datasets[right_name]
        left_shas = {dataset_sha_value(row) for row in left_rows if dataset_sha_value(row)}
        right_shas = {dataset_sha_value(row) for row in right_rows if dataset_sha_value(row)}
        left_repos = {dataset_repo_value(row) for row in left_rows if dataset_repo_value(row)}
        right_repos = {dataset_repo_value(row) for row in right_rows if dataset_repo_value(row)}
        sha_overlap = sorted(left_shas & right_shas)
        repo_overlap = sorted(left_repos & right_repos)
        record = {
            "left": left_name,
            "right": right_name,
            "sha_overlap_count": len(sha_overlap),
            "repo_overlap_count": len(repo_overlap),
            "sha_overlap_examples": sha_overlap[:max_examples],
            "repo_overlap_examples": repo_overlap[:max_examples],
        }
        pairwise.append(record)
        if require_sha_disjoint and sha_overlap:
            passed = False
        if require_repo_disjoint and repo_overlap:
            passed = False

    return {
        "datasets": dataset_summary,
        "pairwise": pairwise,
        "passed": passed,
        "policy": {
            "require_sha_disjoint": bool(require_sha_disjoint),
            "require_repo_disjoint": bool(require_repo_disjoint),
        },
        "warnings": warnings,
    }


def parse_dataset_specs(raw_values: list[str]) -> list[tuple[str, Path]]:
    specs: list[tuple[str, Path]] = []
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"Dataset spec must be name=path: {raw}")
        name, path = raw.split("=", 1)
        specs.append((name.strip(), Path(path.strip())))
    return specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check repo/SHA leakage across offline Step2-related datasets.")
    parser.add_argument("--dataset", action="append", required=True, help="Dataset spec in the form name=path.")
    parser.add_argument("--require-sha-disjoint", action="store_true")
    parser.add_argument("--require-repo-disjoint", action="store_true")
    parser.add_argument("--max-examples", type=int, default=10)
    parser.add_argument("--out", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    specs = parse_dataset_specs(args.dataset)
    payload = build_leakage_report(
        dataset_specs=specs,
        require_sha_disjoint=bool(args.require_sha_disjoint),
        require_repo_disjoint=bool(args.require_repo_disjoint),
        max_examples=max(1, int(args.max_examples)),
    )
    if args.out:
        write_json(Path(args.out), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
