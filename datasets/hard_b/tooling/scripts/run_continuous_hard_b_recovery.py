#!/usr/bin/env python3
"""Rebuild and recover the hard_b diff backlog from local labeled data."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))
LFS_POINTER_HEADER = "version https://git-lfs.github.com/spec/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def inspect_need_diff_file(path: Path) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "path": str(path),
        "status": "missing",
        "rows": 0,
        "sha256": "",
        "mtime": 0.0,
    }
    if not path.exists():
        return snapshot
    snapshot["mtime"] = path.stat().st_mtime
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline().strip()
    if first_line == LFS_POINTER_HEADER:
        snapshot["status"] = "lfs_pointer"
        return snapshot
    rows = count_csv_rows(path)
    snapshot["rows"] = rows
    if rows <= 0:
        snapshot["status"] = "empty"
        return snapshot
    snapshot["status"] = "ok"
    snapshot["sha256"] = file_sha256(path)
    return snapshot


def should_run_recovery(
    snapshot: dict[str, object],
    state: dict,
    output_csv: Path,
    output_jsonl: Path,
    summary: Path,
) -> bool:
    if snapshot.get("status") != "ok":
        return False
    if state.get("last_recovery_input_sha256") != snapshot.get("sha256"):
        return True
    if not output_csv.exists() or output_csv.stat().st_size == 0:
        return True
    if not output_jsonl.exists() or output_jsonl.stat().st_size == 0:
        return True
    if not summary.exists() or summary.stat().st_size == 0:
        return True
    return False


def open_child_output_stream(stack: contextlib.ExitStack, stream_name: str):
    stream = getattr(sys, stream_name, None) or getattr(sys, f"__{stream_name}__", None)
    if stream is not None:
        try:
            return stack.enter_context(os.fdopen(os.dup(stream.fileno()), "wb", closefd=True))
        except (AttributeError, OSError, ValueError):
            pass
    return stack.enter_context(open(os.devnull, "wb"))


def run_cmd(cmd: list[object], cwd: Path) -> None:
    printable = " ".join(str(part) for part in cmd)
    print(f"RUN {printable}", flush=True)
    with contextlib.ExitStack() as stack:
        child_stdout = open_child_output_stream(stack, "stdout")
        child_stderr = open_child_output_stream(stack, "stderr")
        subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=child_stdout,
            stderr=child_stderr,
            check=True,
        )


def run_build(args: argparse.Namespace, root: Path) -> None:
    script = root / "datasets" / "hard_b" / "tooling" / "scripts" / "build_hard_b_pool.py"
    run_cmd(
        [
            sys.executable,
            script,
            "--combined-csv",
            args.combined_csv,
            "--labels-dir",
            args.labels_dir,
            "--raw-dir",
            args.raw_dir,
            "--m-csv",
            args.m_csv,
            "--blocklist",
            args.blocklist,
            "--out-dir",
            args.out_dir,
            "--recovery-csv",
            args.recovery_output_csv,
            "--candidates-csv",
            args.candidates_csv,
            "--need-diff-csv",
            args.need_diff_csv,
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
            args.max_need_diff,
            "--diff-max-chars",
            "0",
        ],
        cwd=root,
    )


def run_recovery(args: argparse.Namespace, root: Path) -> None:
    script = root / "datasets" / "hard_b" / "tooling" / "scripts" / "recover_batch_diffs_remote.py"
    run_cmd(
        [
            sys.executable,
            script,
            "--input-csv",
            args.need_diff_csv,
            "--output-csv",
            args.recovery_output_csv,
            "--output-jsonl",
            args.recovery_output_jsonl,
            "--summary",
            args.recovery_summary,
            "--workers",
            args.recovery_workers,
            "--attempts",
            args.recovery_attempts,
            "--timeout",
            args.recovery_timeout,
            "--fetch-max-bytes",
            args.recovery_fetch_max_bytes,
            "--diff-max-chars",
            args.recovery_diff_max_chars,
        ],
        cwd=root,
    )


def run_loop_once(args: argparse.Namespace, root: Path, state: dict) -> dict:
    updated = dict(state)
    updated.setdefault("created_at_utc", utc_now())
    updated["last_loop_started_at_utc"] = utc_now()
    updated["last_loop_finished_at_utc"] = ""
    updated["last_error"] = ""
    updated["recovery_triggered"] = False
    updated["sleep_seconds"] = args.sleep_seconds
    try:
        updated["last_status"] = "building"
        updated["last_build_started_at_utc"] = utc_now()
        run_build(args, root)
        updated["last_build_finished_at_utc"] = utc_now()

        snapshot = inspect_need_diff_file(args.need_diff_csv)
        updated["need_diff_rows"] = int(snapshot["rows"])
        updated["need_diff_sha256"] = str(snapshot["sha256"])

        if snapshot["status"] == "missing":
            updated["last_status"] = "missing_backlog"
        elif snapshot["status"] == "lfs_pointer":
            updated["last_status"] = "lfs_pointer_backlog"
        elif snapshot["status"] == "empty":
            updated["last_status"] = "empty_backlog"
        elif should_run_recovery(snapshot, updated, args.recovery_output_csv, args.recovery_output_jsonl, args.recovery_summary):
            updated["last_status"] = "recovering"
            updated["last_recovery_started_at_utc"] = utc_now()
            run_recovery(args, root)
            updated["last_recovery_finished_at_utc"] = utc_now()
            updated["recovery_triggered"] = True
            updated["last_recovery_input_sha256"] = str(snapshot["sha256"])
            updated["last_recovery_input_rows"] = int(snapshot["rows"])
            updated["recovery_summary"] = read_json(args.recovery_summary)
            updated["last_status"] = "recovery_completed"
        else:
            updated["recovery_summary"] = read_json(args.recovery_summary)
            updated["last_status"] = "up_to_date"
    except Exception as exc:
        current_status = str(updated.get("last_status") or "")
        updated["last_error"] = f"{type(exc).__name__}: {exc}"
        if current_status == "recovering":
            updated["last_status"] = "recovery_error"
        else:
            updated["last_status"] = "build_error"
    updated["last_loop_finished_at_utc"] = utc_now()
    return updated


def parse_args() -> argparse.Namespace:
    root = repo_root()
    m_workspace = root / "archive" / "datasets" / "m_verified" / "workspace"
    hard_b_workspace = root / "archive" / "datasets" / "hard_b" / "workspace" / "recovery_batches"
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild and recover the hard_b diff backlog once by default. "
            "Pass --daemon to keep polling on a sleep loop."
        )
    )
    parser.add_argument("--combined-csv", type=Path, default=m_workspace / "label_snapshots" / "gitlog_all_pilot_labels_combined.csv")
    parser.add_argument("--labels-dir", type=Path, default=m_workspace / "label_snapshots")
    parser.add_argument("--raw-dir", type=Path, default=m_workspace)
    parser.add_argument("--m-csv", type=Path, default=root / "datasets" / "m_verified" / "canonical" / "usable_m_with_real_diff.csv")
    parser.add_argument("--blocklist", type=Path, default=root / "m_mining_feasibility" / "used_repo_blocklist.txt")
    parser.add_argument("--out-dir", type=Path, default=hard_b_workspace)
    parser.add_argument("--candidates-csv", type=Path, default=hard_b_workspace / "hard_b_candidates_labeled.csv")
    parser.add_argument("--need-diff-csv", type=Path, default=hard_b_workspace / "hard_b_need_full_diff.csv")
    parser.add_argument("--hard-b-output-csv", type=Path, default=root / "datasets" / "hard_b" / "canonical" / "usable_hard_b_with_real_diff.csv")
    parser.add_argument("--hard-b-output-jsonl", type=Path, default=root / "datasets" / "hard_b" / "canonical" / "usable_hard_b_with_real_diff.jsonl")
    parser.add_argument("--hard-b-manifest", type=Path, default=root / "datasets" / "hard_b" / "manifest" / "usable_hard_b_with_real_diff_manifest.json")
    parser.add_argument("--hard-b-review-sample-csv", type=Path, default=root / "datasets" / "hard_b" / "review" / "hard_b_review_sample.csv")
    parser.add_argument("--hard-b-checklist-md", type=Path, default=root / "datasets" / "hard_b" / "review" / "hard_b_checklist.md")
    parser.add_argument("--max-need-diff", type=int, default=240)
    parser.add_argument("--recovery-output-csv", type=Path, default=hard_b_workspace / "hard_b_full_diff_recovery_batch.csv")
    parser.add_argument("--recovery-output-jsonl", type=Path, default=hard_b_workspace / "hard_b_full_diff_recovery_batch.jsonl")
    parser.add_argument("--recovery-summary", type=Path, default=hard_b_workspace / "hard_b_full_diff_recovery_batch_summary.json")
    parser.add_argument("--recovery-workers", type=int, default=8)
    parser.add_argument("--recovery-attempts", type=int, default=3)
    parser.add_argument("--recovery-timeout", type=int, default=180)
    parser.add_argument("--recovery-fetch-max-bytes", type=int, default=25_000_000)
    parser.add_argument("--recovery-diff-max-chars", type=int, default=0)
    parser.add_argument("--state-file", type=Path, default=hard_b_workspace / "continuous_hard_b_recovery_state.json")
    parser.add_argument("--sleep-seconds", type=int, default=600)
    parser.add_argument("--daemon", action="store_true", help="Keep running the build/recovery loop with --sleep-seconds delays.")
    parser.add_argument("--one-round", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    state_path = args.state_file if args.state_file.is_absolute() else root / args.state_file

    run_once = args.one_round or not args.daemon
    while True:
        state = load_state(state_path)
        updated = run_loop_once(args, root, state)
        save_state(state_path, updated)
        print(json.dumps({k: updated.get(k) for k in ("last_status", "need_diff_rows", "recovery_triggered", "last_error")}, ensure_ascii=False, sort_keys=True), flush=True)
        if run_once:
            break
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    main()
