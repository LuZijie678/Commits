#!/usr/bin/env python3
"""Ingest completed remote-diff rounds into formal M and hard-B assets."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REAL_DIFF_MARKER = "diff --git "

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def has_real_diff(text: str) -> bool:
    return REAL_DIFF_MARKER in (text or "")


def load_existing_label_keys(paths: list[Path]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            continue
        try:
            rows = read_csv(path)
        except (OSError, csv.Error):
            continue
        for row in rows:
            repo = str(row.get("repo") or "")
            sha = str(row.get("sha") or "")
            if repo and sha:
                keys.add((repo, sha))
    return keys


def collect_unlabeled_rows(
    input_paths: list[Path],
    existing_keys: set[tuple[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set(existing_keys)
    for path in input_paths:
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in read_csv(path):
            repo = str(row.get("repo") or "")
            sha = str(row.get("sha") or "")
            key = (repo, sha)
            if not repo or not sha or key in seen:
                continue
            if row.get("diff_status") not in {"", "ok"}:
                continue
            if not has_real_diff(str(row.get("git_diff") or "")):
                continue
            rows.append(row)
            seen.add(key)
    return rows


def discover_input_paths(root: Path, input_csvs: list[Path], input_globs: list[str]) -> list[Path]:
    discovered: list[Path] = []
    for path in input_csvs:
        if path.exists():
            discovered.append(path)
    for pattern in input_globs:
        discovered.extend(path for path in root.glob(pattern) if path.is_file())
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(discovered):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print("RUN " + " ".join(str(part) for part in cmd), flush=True)
    result = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command_failed[{result.returncode}]: {' '.join(str(part) for part in cmd)}")


def parse_args() -> argparse.Namespace:
    root = repo_root()
    m_workspace = root / "archive" / "datasets" / "m_verified" / "workspace"
    hard_b_workspace = root / "archive" / "datasets" / "hard_b" / "workspace" / "recovery_batches"
    parser = argparse.ArgumentParser(description="Ingest completed remote-diff rounds into formal assets.")
    parser.add_argument("--input-csv", type=Path, action="append", default=[])
    parser.add_argument(
        "--input-glob",
        action="append",
        default=[],
    )
    parser.add_argument("--labels-dir", type=Path, default=m_workspace / "label_snapshots")
    parser.add_argument("--work-dir", type=Path, default=m_workspace / "recovery_batches")
    parser.add_argument("--combined-csv", type=Path, default=m_workspace / "label_snapshots" / "gitlog_all_pilot_labels_combined.csv")
    parser.add_argument("--m-candidates-csv", type=Path, default=m_workspace / "candidates" / "gitlog_current_m_candidates.csv")
    parser.add_argument("--crawl-root", type=Path, default=root / "archive" / "crawl_rounds" / "m_verified")
    parser.add_argument("--evidence-root", type=Path, default=m_workspace)
    parser.add_argument("--repos-dir", type=Path, default=m_workspace / "repos")
    parser.add_argument("--blocklist", type=Path, default=root / "m_mining_feasibility" / "used_repo_blocklist.txt")
    parser.add_argument("--batch-name", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label-model", default="gpt-4.1-mini")
    parser.add_argument("--label-endpoint", default="https://api.openai.com/v1/chat/completions")
    parser.add_argument("--label-api-key-file", type=Path, default=root / ".llm_api_key")
    parser.add_argument("--label-workers", type=int, default=4)
    parser.add_argument("--label-timeout", type=int, default=90)
    parser.add_argument("--label-attempts", type=int, default=3)
    parser.add_argument("--label-diff-max-chars", type=int, default=16000)
    parser.add_argument("--m-output-csv", type=Path, default=root / "datasets" / "m_verified" / "canonical" / "usable_m_with_real_diff.csv")
    parser.add_argument("--m-output-jsonl", type=Path, default=root / "datasets" / "m_verified" / "canonical" / "usable_m_with_real_diff.jsonl")
    parser.add_argument("--m-missing-csv", type=Path, default=m_workspace / "recovery_batches" / "m_missing_real_diff_to_recover.csv")
    parser.add_argument("--m-manifest", type=Path, default=root / "datasets" / "m_verified" / "manifest" / "usable_m_with_real_diff_manifest.json")
    parser.add_argument("--hard-b-out-dir", type=Path, default=hard_b_workspace)
    parser.add_argument("--hard-b-output-csv", type=Path, default=root / "datasets" / "hard_b" / "canonical" / "usable_hard_b_with_real_diff.csv")
    parser.add_argument("--hard-b-output-jsonl", type=Path, default=root / "datasets" / "hard_b" / "canonical" / "usable_hard_b_with_real_diff.jsonl")
    parser.add_argument("--hard-b-manifest", type=Path, default=root / "datasets" / "hard_b" / "manifest" / "usable_hard_b_with_real_diff_manifest.json")
    parser.add_argument("--hard-b-need-diff-csv", type=Path, default=hard_b_workspace / "hard_b_need_full_diff.csv")
    parser.add_argument("--hard-b-candidates-csv", type=Path, default=hard_b_workspace / "hard_b_candidates_labeled.csv")
    parser.add_argument("--hard-b-review-sample-csv", type=Path, default=root / "datasets" / "hard_b" / "review" / "hard_b_review_sample.csv")
    parser.add_argument("--hard-b-checklist-md", type=Path, default=root / "datasets" / "hard_b" / "review" / "hard_b_checklist.md")
    parser.add_argument("--hard-b-max-need-diff", type=int, default=0)
    parser.add_argument("--summary", type=Path, default=m_workspace / "recovery_batches" / "latest_ingest_summary.json")
    args = parser.parse_args()
    if not args.input_csv and not args.input_glob:
        args.input_glob = ["archive/crawl_rounds/m_verified/**/*_remote_diff.csv"]
    return args


def main() -> None:
    args = parse_args()
    root = repo_root()
    scripts_dir = Path(__file__).resolve().parent
    hard_b_script = root / "datasets" / "hard_b" / "tooling" / "scripts" / "build_hard_b_pool.py"

    input_paths = discover_input_paths(root, args.input_csv, args.input_glob)
    existing_keys = load_existing_label_keys(
        [args.combined_csv]
        + sorted(args.labels_dir.rglob("*_labeled.csv"))
    )
    unlabeled_rows = collect_unlabeled_rows(input_paths, existing_keys)
    if args.limit > 0:
        unlabeled_rows = unlabeled_rows[: args.limit]

    batch_name = args.batch_name or f"ingest_{stamp_now()}"
    label_input_csv = args.work_dir / f"{batch_name}_label_input.csv"
    label_output_csv = args.labels_dir / f"{batch_name}_labeled.csv"
    label_output_jsonl = args.labels_dir / f"{batch_name}_labeled.jsonl"
    label_summary = args.work_dir / f"{batch_name}_label_summary.json"
    combine_summary = args.labels_dir / "gitlog_all_pilot_labels_combined_summary.json"

    label_written = 0
    if unlabeled_rows:
        fieldnames = list(unlabeled_rows[0].keys())
        write_csv(label_input_csv, unlabeled_rows, fieldnames)
        run_cmd(
            [
                sys.executable,
                scripts_dir / "label_m_candidate_batches.py",
                "--input-csv",
                label_input_csv,
                "--output-csv",
                label_output_csv,
                "--output-jsonl",
                label_output_jsonl,
                "--summary",
                label_summary,
                "--model",
                args.label_model,
                "--endpoint",
                args.label_endpoint,
                "--api-key-file",
                args.label_api_key_file,
                "--workers",
                args.label_workers,
                "--timeout",
                args.label_timeout,
                "--attempts",
                args.label_attempts,
                "--diff-max-chars",
                args.label_diff_max_chars,
            ],
            cwd=root,
        )
        label_written = len(read_csv(label_output_csv)) if label_output_csv.exists() else 0

    run_cmd(
        [
            sys.executable,
            scripts_dir / "combine_gitlog_labels.py",
            "--labels-dir",
            args.labels_dir,
            "--raw-dir",
            args.crawl_root,
            "--output-combined",
            args.combined_csv,
            "--output-m",
            args.m_candidates_csv,
            "--summary",
            combine_summary,
        ],
        cwd=root,
    )

    run_cmd(
        [
            sys.executable,
            scripts_dir / "build_usable_m_diff_dataset.py",
            "--m-candidates-csv",
            args.m_candidates_csv,
            "--labels-dir",
            args.labels_dir,
            "--raw-dir",
            args.evidence_root,
            "--repos-dir",
            args.repos_dir,
            "--output-csv",
            args.m_output_csv,
            "--output-jsonl",
            args.m_output_jsonl,
            "--missing-csv",
            args.m_missing_csv,
            "--manifest",
            args.m_manifest,
            "--diff-max-chars",
            "0",
            *sum((["--extra-csv", str(path)] for path in input_paths), []),
        ],
        cwd=root,
    )

    run_cmd(
        [
            sys.executable,
            hard_b_script,
            "--combined-csv",
            args.combined_csv,
            "--labels-dir",
            args.labels_dir,
            "--raw-dir",
            args.evidence_root,
            "--m-csv",
            args.m_output_csv,
            "--blocklist",
            args.blocklist,
            "--out-dir",
            args.hard_b_out_dir,
            "--candidates-csv",
            args.hard_b_candidates_csv,
            "--need-diff-csv",
            args.hard_b_need_diff_csv,
            "--output-csv",
            args.hard_b_output_csv,
            "--output-jsonl",
            args.hard_b_output_jsonl,
            "--manifest",
            args.hard_b_manifest,
            "--review-sample-csv",
            args.hard_b_review_sample_csv,
            "--checklist-md",
            args.hard_b_checklist_md,
            "--max-need-diff",
            args.hard_b_max_need_diff,
            "--diff-max-chars",
            "0",
            *sum((["--extra-csv", str(path)] for path in input_paths), []),
        ],
        cwd=root,
    )

    summary = {
        "created_at_utc": utc_now(),
        "batch_name": batch_name,
        "input_paths": [str(path) for path in input_paths],
        "input_file_count": len(input_paths),
        "existing_labeled_keys": len(existing_keys),
        "new_unlabeled_rows": len(unlabeled_rows),
        "new_label_rows_written": label_written,
        "label_input_csv": str(label_input_csv) if unlabeled_rows else "",
        "label_output_csv": str(label_output_csv) if unlabeled_rows else "",
        "combined_csv": str(args.combined_csv),
        "m_candidates_csv": str(args.m_candidates_csv),
        "m_output_csv": str(args.m_output_csv),
        "hard_b_output_csv": str(args.hard_b_output_csv),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
