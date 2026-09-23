#!/usr/bin/env python3
"""Recover missing git diffs in an enrichment batch from GitHub commit .diff URLs."""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def compact_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.70)
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]


def read_limited(response, max_bytes: int) -> tuple[bytes, bool]:
    if max_bytes <= 0:
        return response.read(), False
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while total < max_bytes:
        chunk = response.read(min(65536, max_bytes - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total >= max_bytes:
        truncated = True
    return b"".join(chunks), truncated


def fetch_diff(repo: str, sha: str, timeout: int, attempts: int, fetch_max_bytes: int) -> tuple[str, str]:
    url = f"https://github.com/{repo}/commit/{sha}.diff"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "multi-intent-research-diff-recovery"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload, truncated = read_limited(response, fetch_max_bytes)
                text = payload.decode("utf-8", errors="replace")
            if truncated:
                return "", f"skipped_diff_too_large_or_slow: reached fetch_max_bytes={fetch_max_bytes}"
            if "diff --git " in text:
                return text, ""
            last_error = "no_diff_marker"
        except http.client.IncompleteRead as exc:
            partial = exc.partial or b""
            if isinstance(partial, bytes):
                text = partial.decode("utf-8", errors="replace")
            else:
                text = str(partial)
            if "diff --git " in text:
                return text, f"IncompleteRead_partial_used: {exc}"
            last_error = f"IncompleteRead: {exc}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts:
            time.sleep(min(2 * attempt, 6))
    return "", last_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover missing batch diffs through public GitHub .diff URLs.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--diff-max-chars", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--fetch-max-bytes", type=int, default=25_000_000)
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args()


def recover_one(row: dict[str, str], args: argparse.Namespace) -> dict[str, str]:
    out = dict(row)
    if out.get("diff_status") == "ok" and "diff --git " in (out.get("git_diff") or ""):
        out["evidence_mode"] = out.get("evidence_mode") or "diff"
        out["_recover_status"] = "already_ok"
        return out
    diff, error = fetch_diff(out.get("repo", ""), out.get("sha", ""), args.timeout, args.attempts, args.fetch_max_bytes)
    if diff:
        out["git_diff"] = compact_text(diff, args.diff_max_chars)
        out["diff_status"] = "ok"
        out["diff_error"] = out.get("diff_error", "")
        out["remote_diff_error"] = error
        out["evidence_mode"] = "diff"
        out["_recover_status"] = "recovered"
    else:
        out["remote_diff_error"] = error
        out["evidence_mode"] = out.get("evidence_mode") or "missing_diff"
        out["_recover_status"] = "failed"
    return out


def main() -> None:
    args = parse_args()
    rows, fields = read_csv(args.input_csv)
    for extra in ["git_diff", "diff_status", "diff_error", "evidence_mode", "remote_diff_error"]:
        if extra not in fields:
            fields.append(extra)

    recovered_rows: list[dict[str, str]] = []
    workers = max(1, args.workers)
    if workers == 1:
        for index, row in enumerate(rows, start=1):
            out = recover_one(row, args)
            recovered_rows.append(out)
            attempted_now = sum(1 for item in recovered_rows if item.get("_recover_status") != "already_ok")
            if attempted_now and attempted_now % 10 == 0:
                print(
                    f"attempted={attempted_now} recovered={sum(1 for item in recovered_rows if item.get('_recover_status') == 'recovered')} "
                    f"failed={sum(1 for item in recovered_rows if item.get('_recover_status') == 'failed')} index={index}/{len(rows)} workers={workers}",
                    flush=True,
                )
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(recover_one, row, args) for row in rows]
            for future in as_completed(futures):
                recovered_rows.append(future.result())
                attempted_now = sum(1 for item in recovered_rows if item.get("_recover_status") != "already_ok")
                if attempted_now and attempted_now % 10 == 0:
                    print(
                        f"attempted={attempted_now} recovered={sum(1 for item in recovered_rows if item.get('_recover_status') == 'recovered')} "
                        f"failed={sum(1 for item in recovered_rows if item.get('_recover_status') == 'failed')} completed={len(recovered_rows)}/{len(rows)} workers={workers}",
                        flush=True,
                    )
    order = {(row.get("repo", ""), row.get("sha", "")): index for index, row in enumerate(rows)}
    rows = sorted(recovered_rows, key=lambda row: order.get((row.get("repo", ""), row.get("sha", "")), 10**9))
    already_ok = sum(1 for row in rows if row.get("_recover_status") == "already_ok")
    attempted = sum(1 for row in rows if row.get("_recover_status") != "already_ok")
    recovered = sum(1 for row in rows if row.get("_recover_status") == "recovered")
    failed = sum(1 for row in rows if row.get("_recover_status") == "failed")
    for row in rows:
        row.pop("_recover_status", None)

    write_csv(args.output_csv, rows, fields)
    write_jsonl(args.output_jsonl, rows)
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
        "rows": len(rows),
        "already_ok": already_ok,
        "attempted": attempted,
        "recovered": recovered,
        "failed": failed,
        "workers": workers,
        "fetch_max_bytes": args.fetch_max_bytes,
        "diff_ok_final": sum(1 for row in rows if row.get("diff_status") == "ok" and "diff --git " in (row.get("git_diff") or "")),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
