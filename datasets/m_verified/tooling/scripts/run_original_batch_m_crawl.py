#!/usr/bin/env python3
"""Continuously crawl M-like commits using the original batch mine+diff flow."""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import runpy
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

AUTO_RELAXED_DISCOVERY_QUERIES = [
    "stars:8000..15000 fork:false archived:false language:Python",
    "stars:5000..8000 fork:false archived:false language:Python",
    "stars:8000..15000 fork:false archived:false language:JavaScript",
    "stars:5000..8000 fork:false archived:false language:JavaScript",
    "stars:8000..15000 fork:false archived:false language:TypeScript",
    "stars:5000..8000 fork:false archived:false language:TypeScript",
    "stars:8000..15000 fork:false archived:false language:Go",
    "stars:5000..8000 fork:false archived:false language:Go",
    "stars:6000..12000 fork:false archived:false language:Rust",
    "stars:3000..6000 fork:false archived:false language:Rust",
    "stars:8000..15000 fork:false archived:false language:Java",
    "stars:5000..8000 fork:false archived:false language:Java",
    "stars:6000..12000 fork:false archived:false language:C++",
    "stars:3000..6000 fork:false archived:false language:C++",
    "stars:5000..10000 fork:false archived:false language:C",
    "stars:3000..5000 fork:false archived:false language:C",
    "stars:5000..10000 fork:false archived:false language:Ruby",
    "stars:3000..5000 fork:false archived:false language:Ruby",
    "stars:5000..10000 fork:false archived:false language:PHP",
    "stars:3000..5000 fork:false archived:false language:PHP",
    "stars:4000..9000 fork:false archived:false language:Kotlin",
    "stars:3000..4000 fork:false archived:false language:Kotlin",
    "stars:4000..9000 fork:false archived:false language:Swift",
    "stars:3000..4000 fork:false archived:false language:Swift",
    "stars:3000..7000 fork:false archived:false topic:database",
    "stars:3000..7000 fork:false archived:false topic:testing",
    "stars:3000..7000 fork:false archived:false topic:api",
    "stars:3000..7000 fork:false archived:false topic:developer-tools",
    "stars:3000..7000 fork:false archived:false topic:compiler",
    "stars:3000..7000 fork:false archived:false topic:security",
    "stars:3000..7000 fork:false archived:false topic:observability",
    "stars:3000..7000 fork:false archived:false topic:networking",
]


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


def open_child_output_stream(stack: contextlib.ExitStack, stream_name: str):
    stream = getattr(sys, stream_name, None) or getattr(sys, f"__{stream_name}__", None)
    if stream is not None:
        try:
            return stack.enter_context(os.fdopen(os.dup(stream.fileno()), "wb", closefd=True))
        except (AttributeError, OSError, ValueError):
            pass
    return stack.enter_context(open(os.devnull, "wb"))


def run_python_script_in_process(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    script_path = Path(cmd[1]).resolve()
    original_argv = sys.argv[:]
    original_cwd = Path.cwd()
    original_env = os.environ.copy()
    try:
        sys.argv = [str(script_path), *cmd[2:]]
        os.chdir(cwd)
        os.environ.update(env)
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = original_argv
        os.chdir(original_cwd)
        os.environ.clear()
        os.environ.update(original_env)


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("RUN " + " ".join(cmd), flush=True)
    if len(cmd) >= 2 and Path(cmd[0]).resolve() == Path(sys.executable).resolve() and cmd[1].endswith(".py"):
        run_python_script_in_process(cmd, cwd, env)
        return
    with contextlib.ExitStack() as stack:
        child_stdout = open_child_output_stream(stack, "stdout")
        child_stderr = open_child_output_stream(stack, "stderr")
        subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=child_stdout,
            stderr=child_stderr,
            check=True,
        )


def count_csv_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    return len(read_csv(path))


def load_repo_status_repos(path: Path) -> set[str]:
    repos: set[str] = set()
    if not path.exists():
        return repos
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        repo = (item.get("repo") or "").strip().lower()
        if repo:
            repos.add(repo)
    return repos


def write_query_file(path: Path, queries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(queries) + ("\n" if queries else ""), encoding="utf-8")


def infer_empty_discovery_streak(state: dict) -> int:
    streak = 0
    for campaign in reversed(state.get("campaigns") or []):
        if int(campaign.get("target_count", 0) or 0) > 0:
            break
        streak += 1
    return streak


def infer_low_yield_discovery_streak(state: dict, threshold: int) -> int:
    streak = 0
    for campaign in reversed(state.get("campaigns") or []):
        if int(campaign.get("target_count", 0) or 0) > threshold:
            break
        streak += 1
    return streak


def resolve_discovery_query_file(args: argparse.Namespace, data_dir: Path, state: dict) -> tuple[Path | None, str]:
    if args.query_file is not None:
        return args.query_file, "explicit_query_file"
    empty_streak = int(state.get("empty_discovery_streak", infer_empty_discovery_streak(state)) or 0)
    low_yield_streak = int(
        state.get(
            "low_yield_discovery_streak",
            infer_low_yield_discovery_streak(state, int(args.low_yield_target_threshold)),
        )
        or 0
    )
    if (
        empty_streak < int(args.auto_relaxed_query_after_empty_streak)
        and low_yield_streak < int(args.auto_relaxed_query_after_low_yield_streak)
    ):
        return None, "default_queries"
    query_file = data_dir / "auto_relaxed_discovery_queries.txt"
    write_query_file(query_file, AUTO_RELAXED_DISCOVERY_QUERIES)
    return query_file, "auto_relaxed_query_file"


def build_seen_repo_file(data_dir: Path, output_path: Path) -> int:
    repos: set[str] = set()
    seed_paths = [
        data_dir / "20260525_newcrawl_seen_repos.txt",
        data_dir / "20260526_newcrawl_seen_repos_merged.txt",
        data_dir / "20260526_newcrawl_seen_repos_merged_v2.txt",
    ]
    for path in seed_paths:
        if path.exists():
            repos.update(line.strip().lower() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip())
    for path in [data_dir / "usable_m_with_real_diff.csv", data_dir / "gitlog_current_m_candidates.csv"]:
        if not path.exists():
            continue
        for row in read_csv(path):
            repo = (row.get("repo") or "").strip().lower()
            if repo:
                repos.add(repo)
    for path in sorted(data_dir.glob("*_remote_diff.csv")):
        for row in read_csv(path):
            repo = (row.get("repo") or "").strip().lower()
            if repo:
                repos.add(repo)
    for path in sorted(data_dir.glob("*_repo_status.jsonl")):
        repos |= load_repo_status_repos(path)
    output_path.write_text("\n".join(sorted(repos)) + ("\n" if repos else ""), encoding="utf-8")
    return len(repos)


def discover_campaign(args: argparse.Namespace, root: Path, scripts_dir: Path, data_dir: Path, env: dict[str, str], state: dict) -> dict:
    prefix = f"batchcrawl_{stamp_now()}"
    seen_path = data_dir / "original_batch_m_crawl_seen_repos.txt"
    seen_count = build_seen_repo_file(data_dir, seen_path)
    query_file, discovery_strategy = resolve_discovery_query_file(args, data_dir, state)
    output_txt = data_dir / f"{prefix}_repo_targets.txt"
    output_csv = data_dir / f"{prefix}_repo_discovery.csv"
    output_summary = data_dir / f"{prefix}_repo_discovery_summary.json"
    discover_cmd = [
        sys.executable,
        str(scripts_dir / "discover_high_star_repos.py"),
        "--output-txt",
        str(output_txt),
        "--output-csv",
        str(output_csv),
        "--summary",
        str(output_summary),
        "--repos-dir",
        str(data_dir / "nonexistent_repos_dir"),
        "--exclude-list",
        str(seen_path),
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
    if query_file is not None:
        discover_cmd.extend(["--query-file", str(query_file)])
    if args.extra_targets_file is not None:
        discover_cmd.extend(["--extra-targets-file", str(args.extra_targets_file)])
    run_cmd(discover_cmd, cwd=root, env=env)
    targets = read_repo_list(output_txt)
    campaign = {
        "prefix": prefix,
        "created_at_utc": utc_now(),
        "targets_txt": str(output_txt),
        "targets_csv": str(output_csv),
        "targets_summary": str(output_summary),
        "seen_repos_file": str(seen_path),
        "seen_repo_count": seen_count,
        "query_file": str(query_file) if query_file is not None else "",
        "discovery_strategy": discovery_strategy,
        "target_count": len(targets),
        "next_offset": 0,
    }
    state["current_campaign"] = campaign
    state.setdefault("campaigns", []).append(campaign)
    save_state(root / args.state_file, state)
    return campaign


def build_round_state(campaign: dict, data_dir: Path, round_index: int, batch_size: int) -> dict:
    prefix = str(campaign["prefix"])
    round_name = f"{prefix}_round{round_index:04d}"
    return {
        "round_name": round_name,
        "campaign_prefix": prefix,
        "created_at_utc": utc_now(),
        "offset": int(campaign["next_offset"]),
        "limit": batch_size,
        "stage": "initialized",
        "input_targets": str(campaign["targets_txt"]),
        "candidates_csv": str(data_dir / f"{round_name}_api_filelist_candidates.csv"),
        "candidates_jsonl": str(data_dir / f"{round_name}_api_filelist_candidates.jsonl"),
        "candidates_summary": str(data_dir / f"{round_name}_api_filelist_candidates_summary.json"),
        "repo_status_jsonl": str(data_dir / f"{round_name}_api_filelist_candidates_repo_status.jsonl"),
        "remote_csv": str(data_dir / f"{round_name}_api_filelist_candidates_remote_diff.csv"),
        "remote_jsonl": str(data_dir / f"{round_name}_api_filelist_candidates_remote_diff.jsonl"),
        "remote_summary": str(data_dir / f"{round_name}_api_filelist_candidates_remote_diff_summary.json"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continuously run the original batch M crawl flow.")
    parser.add_argument("--token-file", type=Path, default=Path("../.github_token"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--state-file", type=Path, default=Path("data/original_batch_m_crawl_state.json"))
    parser.add_argument("--sleep-seconds", type=int, default=300)
    parser.add_argument("--discover-limit", type=int, default=120)
    parser.add_argument("--discover-per-query", type=int, default=40)
    parser.add_argument("--discover-pages", type=int, default=2)
    parser.add_argument("--auto-relaxed-query-after-empty-streak", type=int, default=2)
    parser.add_argument("--auto-relaxed-query-after-low-yield-streak", type=int, default=2)
    parser.add_argument("--low-yield-target-threshold", type=int, default=1)
    parser.add_argument("--query-file", type=Path, default=None)
    parser.add_argument("--extra-targets-file", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--candidate-per-page", type=int, default=50)
    parser.add_argument("--candidate-pages-per-repo", type=int, default=2)
    parser.add_argument("--candidate-top-per-repo", type=int, default=3)
    parser.add_argument("--candidate-max-total", type=int, default=120)
    parser.add_argument("--min-base-score", type=float, default=18.0)
    parser.add_argument("--candidate-timeout", type=int, default=35)
    parser.add_argument("--candidate-sleep-sec", type=float, default=0.1)
    parser.add_argument("--diff-timeout", type=int, default=120)
    parser.add_argument("--diff-attempts", type=int, default=3)
    parser.add_argument("--diff-fetch-max-bytes", type=int, default=25_000_000)
    parser.add_argument("--diff-max-files", type=int, default=120)
    parser.add_argument("--diff-workers", type=int, default=8)
    parser.add_argument("--one-round", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    scripts_dir = root / "scripts"
    data_dir = root / args.data_dir
    state_path = root / args.state_file
    token_path = (root / args.token_file).resolve()

    token = ensure_token(token_path)
    env = dict(os.environ)
    env["GITHUB_TOKEN"] = token

    state = load_state(state_path)
    state.setdefault("created_at_utc", utc_now())
    state.setdefault("global_round_index", 0)
    state.setdefault("completed_rounds", [])
    state.setdefault("empty_discovery_streak", infer_empty_discovery_streak(state))
    state.setdefault(
        "low_yield_discovery_streak",
        infer_low_yield_discovery_streak(state, int(args.low_yield_target_threshold)),
    )
    save_state(state_path, state)

    while True:
        campaign = state.get("current_campaign")
        if not campaign or int(campaign.get("next_offset", 0)) >= int(campaign.get("target_count", 0)):
            campaign = discover_campaign(args, root, scripts_dir, data_dir, env, state)
            target_count = int(campaign.get("target_count", 0) or 0)
            if target_count == 0:
                state["empty_discovery_streak"] = int(state.get("empty_discovery_streak", 0) or 0) + 1
            else:
                state["empty_discovery_streak"] = 0
            if target_count <= int(args.low_yield_target_threshold):
                state["low_yield_discovery_streak"] = int(state.get("low_yield_discovery_streak", 0) or 0) + 1
            else:
                state["low_yield_discovery_streak"] = 0
            if target_count == 0:
                state["last_idle_at_utc"] = utc_now()
                save_state(state_path, state)
                if args.one_round:
                    break
                time.sleep(args.sleep_seconds)
                state = load_state(state_path)
                continue
            state["last_nonempty_discovery_at_utc"] = utc_now()
            save_state(state_path, state)

        targets = read_repo_list(Path(campaign["targets_txt"]))
        offset = int(campaign["next_offset"])
        batch_size = min(args.batch_size, max(0, len(targets) - offset))
        if batch_size <= 0:
            state["current_campaign"] = None
            save_state(state_path, state)
            state = load_state(state_path)
            continue

        round_state = state.get("current_round")
        if not round_state:
            round_index = int(state.get("global_round_index", 0)) + 1
            round_state = build_round_state(campaign, data_dir, round_index, batch_size)
            state["current_round"] = round_state
            save_state(state_path, state)
        else:
            round_index = int(str(round_state["round_name"]).rsplit("round", 1)[-1])

        candidates_csv = Path(round_state["candidates_csv"])
        candidates_jsonl = Path(round_state["candidates_jsonl"])
        candidates_summary = Path(round_state["candidates_summary"])
        repo_status_jsonl = Path(round_state["repo_status_jsonl"])
        remote_csv = Path(round_state["remote_csv"])
        remote_jsonl = Path(round_state["remote_jsonl"])
        remote_summary = Path(round_state["remote_summary"])
        stage = str(round_state.get("stage") or "initialized")

        if stage in {"initialized", "mining"} or not candidates_csv.exists():
            round_state["stage"] = "mining"
            state["current_round"] = round_state
            save_state(state_path, state)
            run_cmd(
                [
                    sys.executable,
                    str(scripts_dir / "mine_github_api_filelist_candidates.py"),
                    "--targets",
                    str(campaign["targets_txt"]),
                    "--labels-dir",
                    str(data_dir / "nonexistent_labels_dir"),
                    "--output-csv",
                    str(candidates_csv),
                    "--output-jsonl",
                    str(candidates_jsonl),
                    "--summary",
                    str(candidates_summary),
                    "--repo-status-jsonl",
                    str(repo_status_jsonl),
                    "--offset-repos",
                    str(round_state["offset"]),
                    "--limit-repos",
                    str(round_state["limit"]),
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

        candidate_rows = count_csv_rows(candidates_csv)
        round_state["candidate_row_count"] = candidate_rows
        state["current_round"] = round_state
        save_state(state_path, state)

        if candidate_rows > 0 and (stage in {"initialized", "mining", "mined", "enriching"} or not remote_csv.exists()):
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

        round_state["remote_row_count"] = count_csv_rows(remote_csv)
        round_state["stage"] = "completed"
        round_state["completed_at_utc"] = utc_now()
        state["completed_rounds"].append(round_state)
        state["global_round_index"] = int(state.get("global_round_index", 0)) + 1
        campaign["next_offset"] = int(round_state["offset"]) + int(round_state["limit"])
        state["current_campaign"] = campaign if campaign["next_offset"] < int(campaign["target_count"]) else None
        state.pop("current_round", None)
        state["last_completed_round"] = round_state["round_name"]
        save_state(state_path, state)

        if args.one_round:
            break

        time.sleep(1)
        state = load_state(state_path)


if __name__ == "__main__":
    main()
