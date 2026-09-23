#!/usr/bin/env python3
"""Continuously discover new repos, mine M-like candidates, and fetch real diffs.

This runner orchestrates the existing discovery and mining scripts and maintains
its own state file so it can resume after interruption without starting over.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_repo_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_repo_list(path: Path, repos: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(repos) + ("\n" if repos else ""), encoding="utf-8")


def load_seen_repos(paths: list[Path]) -> set[str]:
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for row in read_csv(path):
            repo = (row.get("repo") or "").strip().lower()
            if repo:
                seen.add(repo)
    return seen


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def ensure_token(token_path: Path) -> str:
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"token file is empty: {token_path}")
    return token


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    print("RUN " + " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def filter_novel_targets(source_txt: Path, output_txt: Path, seen_repos: set[str]) -> list[str]:
    targets = read_repo_list(source_txt)
    novel = [repo for repo in targets if repo.lower() not in seen_repos]
    write_repo_list(output_txt, novel)
    return novel


def build_round_state(batch: str, round_index: int, data_dir: Path) -> dict:
    discover_csv = data_dir / f"{batch}_repo_discovery.csv"
    discover_txt = data_dir / f"{batch}_repo_targets.txt"
    discover_summary = data_dir / f"{batch}_repo_discovery_summary.json"
    novel_txt = data_dir / f"{batch}_repo_targets_novel.txt"
    candidates_csv = data_dir / f"{batch}_api_filelist_candidates.csv"
    candidates_jsonl = data_dir / f"{batch}_api_filelist_candidates.jsonl"
    candidates_summary = data_dir / f"{batch}_api_filelist_candidates_summary.json"
    candidates_repo_status = data_dir / f"{batch}_api_filelist_candidates_repo_status.jsonl"
    remote_csv = data_dir / f"{batch}_api_filelist_candidates_remote_diff.csv"
    remote_jsonl = data_dir / f"{batch}_api_filelist_candidates_remote_diff.jsonl"
    remote_summary = data_dir / f"{batch}_api_filelist_candidates_remote_diff_summary.json"
    return {
        "batch": batch,
        "round_index": round_index,
        "stage": "initialized",
        "started_at_utc": utc_now(),
        "discover_csv": str(discover_csv),
        "discover_txt": str(discover_txt),
        "discover_summary": str(discover_summary),
        "novel_txt": str(novel_txt),
        "candidates_csv": str(candidates_csv),
        "candidates_jsonl": str(candidates_jsonl),
        "candidates_summary": str(candidates_summary),
        "candidates_repo_status": str(candidates_repo_status),
        "remote_csv": str(remote_csv),
        "remote_jsonl": str(remote_jsonl),
        "remote_summary": str(remote_summary),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continuously crawl new M candidates with resume support.")
    parser.add_argument("--token-file", type=Path, default=Path("../.github_token"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--state-file", type=Path, default=Path("data/continuous_m_crawl_state.json"))
    parser.add_argument("--sleep-seconds", type=int, default=900)
    parser.add_argument("--max-empty-rounds", type=int, default=6)
    parser.add_argument("--discover-limit", type=int, default=120)
    parser.add_argument("--discover-per-query", type=int, default=40)
    parser.add_argument("--discover-pages", type=int, default=2)
    parser.add_argument("--query-file", type=Path, default=None)
    parser.add_argument("--extra-targets-file", type=Path, default=None)
    parser.add_argument("--candidate-limit-repos", type=int, default=40)
    parser.add_argument("--candidate-max-total", type=int, default=120)
    parser.add_argument("--candidate-top-per-repo", type=int, default=3)
    parser.add_argument("--candidate-per-page", type=int, default=50)
    parser.add_argument("--candidate-pages-per-repo", type=int, default=2)
    parser.add_argument("--min-base-score", type=float, default=18.0)
    parser.add_argument("--candidate-timeout", type=int, default=35)
    parser.add_argument("--candidate-sleep-sec", type=float, default=0.1)
    parser.add_argument("--diff-timeout", type=int, default=120)
    parser.add_argument("--diff-attempts", type=int, default=3)
    parser.add_argument("--diff-fetch-max-bytes", type=int, default=25_000_000)
    parser.add_argument("--diff-max-files", type=int, default=120)
    parser.add_argument("--diff-workers", type=int, default=8)
    parser.add_argument("--one-round", action="store_true", help="Run exactly one round and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    scripts_dir = root / "scripts"
    data_dir = root / args.data_dir
    token_path = (root / args.token_file).resolve()
    state_path = root / args.state_file

    token = ensure_token(token_path)
    env = dict(os.environ)
    env["GITHUB_TOKEN"] = token

    state = load_state(state_path)
    state.setdefault("created_at_utc", utc_now())
    state.setdefault("round_index", 0)
    state.setdefault("empty_rounds", 0)
    state.setdefault("rounds", [])
    save_state(state_path, state)

    while True:
        if state.get("current_round"):
            round_state = dict(state["current_round"])
            round_index = int(round_state.get("round_index") or (int(state.get("round_index", 0)) + 1))
            batch = str(round_state["batch"])
        else:
            round_index = int(state.get("round_index", 0)) + 1
            stamp = stamp_now()
            batch = f"continuous_{stamp}_r{round_index:04d}"
            round_state = build_round_state(batch, round_index, data_dir)
            state["current_round"] = round_state
            save_state(state_path, state)

        discover_txt = Path(round_state["discover_txt"])
        discover_csv = Path(round_state["discover_csv"])
        discover_summary = Path(round_state["discover_summary"])
        novel_txt = Path(round_state["novel_txt"])
        candidates_csv = Path(round_state["candidates_csv"])
        candidates_jsonl = Path(round_state["candidates_jsonl"])
        candidates_summary = Path(round_state["candidates_summary"])
        candidates_repo_status = Path(round_state["candidates_repo_status"])
        remote_csv = Path(round_state["remote_csv"])
        remote_jsonl = Path(round_state["remote_jsonl"])
        remote_summary = Path(round_state["remote_summary"])
        stage = str(round_state.get("stage") or "initialized")

        if stage in {"initialized", "discovering"} or not discover_txt.exists() or not discover_csv.exists():
            round_state["stage"] = "discovering"
            state["current_round"] = round_state
            save_state(state_path, state)
            discover_cmd = [
                sys.executable,
                str(scripts_dir / "discover_high_star_repos.py"),
                "--output-txt",
                str(discover_txt),
                "--output-csv",
                str(discover_csv),
                "--summary",
                str(discover_summary),
                "--repos-dir",
                str(data_dir / "nonexistent_repos_dir"),
                "--limit",
                str(args.discover_limit),
                "--per-query",
                str(args.discover_per_query),
                "--pages-per-query",
                str(args.discover_pages),
                "--timeout",
                "30",
                "--sleep-sec",
                "0.1",
                "--code-like-only",
            ]
            if args.query_file is not None:
                discover_cmd.extend(["--query-file", str(args.query_file)])
            if args.extra_targets_file is not None:
                discover_cmd.extend(["--extra-targets-file", str(args.extra_targets_file)])
            run_cmd(discover_cmd, cwd=root, env=env)
            seen_repos = load_seen_repos(
                [
                    data_dir / "usable_m_with_real_diff.csv",
                    data_dir / "gitlog_current_m_candidates.csv",
                ]
                + sorted(data_dir.glob("*_remote_diff.csv"))
            )
            novel_targets = filter_novel_targets(discover_txt, novel_txt, seen_repos)
            round_state["stage"] = "discovered"
            state["current_round"] = round_state
            save_state(state_path, state)
        else:
            novel_targets = read_repo_list(novel_txt)
            if not novel_targets and discover_txt.exists():
                seen_repos = load_seen_repos(
                    [
                        data_dir / "usable_m_with_real_diff.csv",
                        data_dir / "gitlog_current_m_candidates.csv",
                    ]
                    + sorted(data_dir.glob("*_remote_diff.csv"))
                )
                novel_targets = filter_novel_targets(discover_txt, novel_txt, seen_repos)

        if not novel_targets:
            state["round_index"] = round_index
            state["empty_rounds"] = int(state.get("empty_rounds", 0)) + 1
            round_state["ended_at_utc"] = utc_now()
            round_state["novel_target_count"] = 0
            round_state["status"] = "no_novel_targets"
            round_state["stage"] = "completed"
            state["rounds"].append(round_state)
            state.pop("current_round", None)
            save_state(state_path, state)
            if args.one_round:
                break
            if int(state["empty_rounds"]) >= args.max_empty_rounds:
                print(f"Reached max empty rounds={args.max_empty_rounds}, sleeping {args.sleep_seconds}s before continuing.", flush=True)
            time.sleep(args.sleep_seconds)
            continue

        round_state["novel_target_count"] = len(novel_targets)
        state["current_round"] = round_state
        save_state(state_path, state)

        if stage not in {"mined", "enriching"} or not candidates_csv.exists():
            round_state["stage"] = "mining"
            state["current_round"] = round_state
            save_state(state_path, state)
            run_cmd(
                [
                    sys.executable,
                    str(scripts_dir / "mine_github_api_filelist_candidates.py"),
                    "--targets",
                    str(novel_txt),
                    "--labels-dir",
                    str(data_dir / "nonexistent_labels_dir"),
                    "--output-csv",
                    str(candidates_csv),
                    "--output-jsonl",
                    str(candidates_jsonl),
                    "--summary",
                    str(candidates_summary),
                    "--repo-status-jsonl",
                    str(candidates_repo_status),
                    "--limit-repos",
                    str(min(args.candidate_limit_repos, len(novel_targets))),
                    "--pages-per-repo",
                    str(args.candidate_pages_per_repo),
                    "--per-page",
                    str(args.candidate_per_page),
                    "--top-per-repo",
                    str(args.candidate_top_per_repo),
                    "--max-total",
                    str(args.candidate_max_total),
                    "--min-base-score",
                    str(args.min_base_score),
                    "--max-files",
                    str(args.diff_max_files),
                    "--timeout",
                    str(args.candidate_timeout),
                    "--sleep-sec",
                    str(args.candidate_sleep_sec),
                    "--incremental",
                    "--resume",
                ],
                cwd=root,
                env=env,
            )
            round_state["stage"] = "mined"
            state["current_round"] = round_state
            save_state(state_path, state)

        candidate_rows = read_csv(candidates_csv) if candidates_csv.exists() else []
        round_state["candidate_row_count"] = len(candidate_rows)

        if not candidate_rows:
            state["round_index"] = round_index
            state["empty_rounds"] = int(state.get("empty_rounds", 0)) + 1
            round_state["ended_at_utc"] = utc_now()
            round_state["status"] = "no_candidates"
            round_state["stage"] = "completed"
            state["rounds"].append(round_state)
            state.pop("current_round", None)
            save_state(state_path, state)
            if args.one_round:
                break
            time.sleep(args.sleep_seconds)
            continue

        if stage != "completed" or not remote_csv.exists():
            round_state["stage"] = "enriching"
            state["current_round"] = round_state
            save_state(state_path, state)
            run_cmd(
                [
                    sys.executable,
                    str(scripts_dir / "enrich_candidates_remote_diff.py"),
                    "--input-csv",
                    str(candidates_csv),
                    "--output-csv",
                    str(remote_csv),
                    "--output-jsonl",
                    str(remote_jsonl),
                    "--summary",
                    str(remote_summary),
                    "--diff-max-chars",
                    "0",
                    "--timeout",
                    str(args.diff_timeout),
                    "--attempts",
                    str(args.diff_attempts),
                    "--max-files",
                    str(args.diff_max_files),
                    "--fetch-max-bytes",
                    str(args.diff_fetch_max_bytes),
                    "--workers",
                    str(args.diff_workers),
                    "--incremental",
                    "--resume",
                ],
                cwd=root,
                env=env,
            )

        remote_rows = read_csv(remote_csv) if remote_csv.exists() else []
        diff_ok = sum(1 for row in remote_rows if row.get("diff_status") == "ok" and "diff --git " in (row.get("git_diff") or ""))

        state["round_index"] = round_index
        state["empty_rounds"] = 0 if diff_ok > 0 else int(state.get("empty_rounds", 0)) + 1
        round_state["ended_at_utc"] = utc_now()
        round_state["remote_row_count"] = len(remote_rows)
        round_state["diff_ok_count"] = diff_ok
        round_state["status"] = "completed"
        round_state["stage"] = "completed"
        state["last_successful_batch"] = batch
        state["rounds"].append(round_state)
        state.pop("current_round", None)
        save_state(state_path, state)

        if args.one_round:
            break

        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    main()
