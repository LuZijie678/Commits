#!/usr/bin/env python3
"""Run one high-throughput M mining round.

Pipeline:
1. Fast filelist-only enrichment from an existing precision candidate CSV.
2. Label a batch with DeepSeek, optionally with parallel workers.
3. Extract rows labeled M.
4. Recover full GitHub .diff only for M rows, skipping oversized diffs.
5. Rebuild combined labels and the strict usable full-diff M dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], cwd: Path, timeout: int) -> None:
    print("RUN " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(cwd), text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(cmd)}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def slice_csv(input_csv: Path, output_csv: Path, offset: int, limit: int) -> int:
    rows = read_csv(input_csv)
    selected = rows[offset : offset + limit if limit > 0 else None]
    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(output_csv, selected, fieldnames)
    return len(selected)


def extract_m_rows(labeled_csv: Path, output_csv: Path) -> int:
    rows = [row for row in read_csv(labeled_csv) if row.get("llm_label") == "M"]
    fieldnames = list(rows[0].keys()) if rows else list(read_csv(labeled_csv)[0].keys()) if labeled_csv.exists() and read_csv(labeled_csv) else []
    write_csv(output_csv, rows, fieldnames)
    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run high-throughput M mining round.")
    parser.add_argument("--round-name", required=True)
    parser.add_argument("--input-csv", type=Path, default=Path("m_mining_gitlog_pilot/raw/gitlog_round7_precision_unlabeled.csv"))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--label-limit", type=int, default=120)
    parser.add_argument("--max-files", type=int, default=140)
    parser.add_argument("--filelist-timeout", type=int, default=8)
    parser.add_argument("--label-workers", type=int, default=4)
    parser.add_argument("--recover-workers", type=int, default=4)
    parser.add_argument("--recover-timeout", type=int, default=90)
    parser.add_argument("--recover-attempts", type=int, default=1)
    parser.add_argument("--fetch-max-bytes", type=int, default=25_000_000)
    parser.add_argument("--api-key-file", type=Path, default=Path("api.txt"))
    parser.add_argument("--no-rebuild", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    labels_dir = root / "m_mining_gitlog_pilot" / "labels"
    work_dir = labels_dir / args.round_name
    work_dir.mkdir(parents=True, exist_ok=True)

    sliced_csv = work_dir / f"{args.round_name}_input_slice.csv"
    enriched_csv = work_dir / f"{args.round_name}_filelist_batch.csv"
    enriched_jsonl = work_dir / f"{args.round_name}_filelist_batch.jsonl"
    enriched_summary = work_dir / f"{args.round_name}_filelist_batch_summary.json"
    label_input_csv = work_dir / f"{args.round_name}_label_input.csv"
    labeled_csv = labels_dir / f"{args.round_name}_filelist_labeled.csv"
    labeled_jsonl = labels_dir / f"{args.round_name}_filelist_labeled.jsonl"
    m_need_diff_csv = labels_dir / f"{args.round_name}_m_need_full_diff.csv"
    recovered_csv = labels_dir / f"{args.round_name}_m_full_diff_recovery_batch.csv"
    recovered_jsonl = labels_dir / f"{args.round_name}_m_full_diff_recovery_batch.jsonl"
    recovered_summary = labels_dir / f"{args.round_name}_m_full_diff_recovery_batch_summary.json"
    run_summary = work_dir / f"{args.round_name}_run_summary.json"

    selected = slice_csv(root / args.input_csv, sliced_csv, args.offset, args.limit)
    run(
        [
            sys.executable,
            "m_mining_gitlog_pilot/scripts/enrich_local_filelist_only.py",
            "--input-csv",
            str(sliced_csv),
            "--repos-dir",
            "m_mining_gitlog_pilot/repos",
            "--labels-dir",
            "m_mining_gitlog_pilot/labels",
            "--output-csv",
            str(enriched_csv),
            "--output-jsonl",
            str(enriched_jsonl),
            "--summary",
            str(enriched_summary),
            "--limit",
            str(args.limit),
            "--max-files",
            str(args.max_files),
            "--timeout",
            str(args.filelist_timeout),
        ],
        root,
        timeout=max(120, args.limit * max(2, args.filelist_timeout // 2)),
    )
    enriched_rows = read_csv(enriched_csv)
    label_rows = enriched_rows[: args.label_limit if args.label_limit > 0 else None]
    write_csv(label_input_csv, label_rows, list(enriched_rows[0].keys()) if enriched_rows else [])

    run(
        [
            sys.executable,
            "full_experiment/real_world_testset/label_m_candidates_deepseek.py",
            "--input-csv",
            str(label_input_csv),
            "--output-csv",
            str(labeled_csv),
            "--output-jsonl",
            str(labeled_jsonl),
            "--api-key-file",
            str(args.api_key_file),
            "--workers",
            str(args.label_workers),
            "--no-resume",
        ],
        root,
        timeout=max(600, len(label_rows) * 30),
    )
    m_count = extract_m_rows(labeled_csv, m_need_diff_csv)

    if m_count:
        run(
            [
                sys.executable,
                "m_mining_gitlog_pilot/scripts/recover_batch_diffs_remote.py",
                "--input-csv",
                str(m_need_diff_csv),
                "--output-csv",
                str(recovered_csv),
                "--output-jsonl",
                str(recovered_jsonl),
                "--summary",
                str(recovered_summary),
                "--diff-max-chars",
                "0",
                "--timeout",
                str(args.recover_timeout),
                "--attempts",
                str(args.recover_attempts),
                "--fetch-max-bytes",
                str(args.fetch_max_bytes),
                "--workers",
                str(args.recover_workers),
            ],
            root,
            timeout=max(600, m_count * args.recover_timeout),
        )

    if not args.no_rebuild:
        run([sys.executable, "m_mining_gitlog_pilot/scripts/combine_gitlog_labels.py"], root, timeout=180)
        run(
            [
                sys.executable,
                "m_mining_gitlog_pilot/scripts/build_usable_m_diff_dataset.py",
                "--timeout",
                "20",
                "--no-allow-remote-diff",
                "--diff-max-chars",
                "0",
            ],
            root,
            timeout=240,
        )

    summary = {
        "created_at_utc": utc_now(),
        "round_name": args.round_name,
        "input_csv": str(args.input_csv),
        "offset": args.offset,
        "limit": args.limit,
        "selected_from_input": selected,
        "filelist_enriched": len(enriched_rows),
        "label_input_rows": len(label_rows),
        "m_labeled_rows": m_count,
        "paths": {
            "work_dir": str(work_dir),
            "labeled_csv": str(labeled_csv),
            "m_need_full_diff_csv": str(m_need_diff_csv),
            "recovered_csv": str(recovered_csv),
            "run_summary": str(run_summary),
        },
    }
    run_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
