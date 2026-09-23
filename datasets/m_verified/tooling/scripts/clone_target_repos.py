#!/usr/bin/env python3
"""Clone or update a target repo list for git-log M mining."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_targets(path: Path) -> list[str]:
    targets = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        targets.append(line)
    return targets


def load_blocklist(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()}


def repo_dir_for(repos_dir: Path, repo: str) -> Path:
    return repos_dir / repo.replace("/", "__")


def run(cmd: list[str], timeout: int, cwd: Path | None = None) -> tuple[int, str, str, float]:
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr, time.time() - start
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return 124, out, err + f"\nTIMEOUT after {timeout}s", time.time() - start


def is_valid_repo(path: Path) -> bool:
    if not path.exists():
        return False
    code, _, _, _ = run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], timeout=30)
    return code == 0


def short_head(path: Path) -> str:
    code, out, _, _ = run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], timeout=30)
    return out.strip() if code == 0 else ""


def commit_count(path: Path) -> int | None:
    code, out, _, _ = run(["git", "-C", str(path), "rev-list", "--count", "HEAD"], timeout=60)
    if code != 0:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone target repos for M mining.")
    parser.add_argument("--targets", type=Path, default=Path("m_mining_gitlog_pilot/repo_targets_round1.txt"))
    parser.add_argument("--repos-dir", type=Path, default=Path("m_mining_gitlog_pilot/repos"))
    parser.add_argument("--status-jsonl", type=Path, default=Path("m_mining_gitlog_pilot/raw/clone_round1_status.jsonl"))
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--depth", type=int, default=6000)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    targets = load_targets(args.targets)
    if args.limit > 0:
        targets = targets[: args.limit]
    blocklist = load_blocklist(args.blocklist)
    args.repos_dir.mkdir(parents=True, exist_ok=True)
    records = []

    for repo in targets:
        dest = repo_dir_for(args.repos_dir, repo)
        record = {
            "created_at_utc": utc_now(),
            "repo": repo,
            "dest": str(dest),
            "depth": args.depth,
        }
        if repo.lower() in blocklist:
            record["status"] = "skipped_blocklisted"
            append_jsonl(args.status_jsonl, record)
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
            records.append(record)
            continue
        if is_valid_repo(dest):
            record.update({"status": "already_valid", "head": short_head(dest), "commit_count": commit_count(dest)})
            append_jsonl(args.status_jsonl, record)
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
            records.append(record)
            continue
        if dest.exists():
            record["status"] = "exists_but_invalid_skip"
            append_jsonl(args.status_jsonl, record)
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
            records.append(record)
            continue
        url = f"https://github.com/{repo}.git"
        cmd = ["git", "-c", "protocol.version=2", "clone", "--filter=blob:none", "--no-checkout", "--single-branch", "--no-tags", "--depth", str(args.depth), url, str(dest)]
        code, out, err, elapsed = run(cmd, timeout=args.timeout)
        record["elapsed_sec"] = round(elapsed, 2)
        record["returncode"] = code
        if code == 0 and is_valid_repo(dest):
            record.update({"status": "cloned", "head": short_head(dest), "commit_count": commit_count(dest)})
        else:
            record["status"] = "clone_error"
            record["stderr_tail"] = err[-1000:]
        append_jsonl(args.status_jsonl, record)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
        records.append(record)

    summary = {
        "created_at_utc": utc_now(),
        "targets": len(targets),
        "cloned": sum(1 for r in records if r.get("status") == "cloned"),
        "already_valid": sum(1 for r in records if r.get("status") == "already_valid"),
        "clone_error": sum(1 for r in records if r.get("status") == "clone_error"),
        "skipped_blocklisted": sum(1 for r in records if r.get("status") == "skipped_blocklisted"),
        "exists_but_invalid_skip": sum(1 for r in records if r.get("status") == "exists_but_invalid_skip"),
        "status_jsonl": str(args.status_jsonl),
    }
    summary_path = args.status_jsonl.with_name("clone_round1_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

