import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


CSV_FIELD_SIZE_LIMIT = 2**31 - 1
DEFAULT_BATCH_SIZE = 5000


@dataclass(frozen=True)
class RepoRecord:
    order_index: int
    repo_url: str
    repo_name: str
    mirror_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone CCS repos locally and backfill repo + diff for allcommits.csv."
    )
    parser.add_argument(
        "--repo-list-csv",
        default=r"external\conventional-commit-classification\RQ1\data\116_repos_adopted_CCS.csv",
    )
    parser.add_argument(
        "--allcommits-csv",
        default=r"external\conventional-commit-classification\Dataset\allcommits.csv",
    )
    parser.add_argument(
        "--work-root",
        default=r"full_experiment\step1\offline_backfill\workdir",
    )
    parser.add_argument(
        "--output-dir",
        default=r"full_experiment\step1\offline_backfill\outputs\allcommits_local_backfill",
    )
    parser.add_argument("--repo-offset", type=int, default=0)
    parser.add_argument("--repo-limit", type=int, default=0)
    parser.add_argument("--commit-offset", type=int, default=0)
    parser.add_argument("--commit-limit", type=int, default=0)
    parser.add_argument(
        "--skip-clone", action="store_true", help="Skip mirror cloning phase."
    )
    parser.add_argument(
        "--skip-index", action="store_true", help="Skip local SHA indexing phase."
    )
    parser.add_argument(
        "--skip-backfill", action="store_true", help="Skip dataset backfill phase."
    )
    parser.add_argument(
        "--refresh-indexed-repos",
        action="store_true",
        help="Rebuild SHA index for repos already marked indexed.",
    )
    parser.add_argument(
        "--refresh-backfill",
        action="store_true",
        help="Delete previous backfill outputs and rerun from scratch.",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_csv_rows(path: Path) -> list[dict]:
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def repo_name_from_url(repo_url: str) -> str:
    parsed = urlparse(repo_url.strip())
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    pieces = [piece for piece in path.split("/") if piece]
    if len(pieces) < 2:
        raise ValueError(f"Invalid GitHub repo URL: {repo_url}")
    return "/".join(pieces[:2])


def mirror_dir_name(repo_name: str) -> str:
    return repo_name.replace("/", "__") + ".git"


def load_repo_records(
    repo_list_csv: Path,
    mirrors_root: Path,
    repo_offset: int,
    repo_limit: int,
) -> list[RepoRecord]:
    rows = load_csv_rows(repo_list_csv)
    repo_urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        repo_url = (row.get("repo") or "").strip()
        if not repo_url or repo_url in seen:
            continue
        seen.add(repo_url)
        repo_urls.append(repo_url)
    indexed_repo_urls = list(enumerate(repo_urls))
    if repo_offset > 0:
        indexed_repo_urls = indexed_repo_urls[repo_offset:]
    if repo_limit > 0:
        indexed_repo_urls = indexed_repo_urls[:repo_limit]
    records: list[RepoRecord] = []
    for order_index, repo_url in indexed_repo_urls:
        repo_name = repo_name_from_url(repo_url)
        mirror_path = mirrors_root / mirror_dir_name(repo_name)
        records.append(
            RepoRecord(
                order_index=order_index,
                repo_url=repo_url,
                repo_name=repo_name,
                mirror_path=mirror_path,
            )
        )
    return records


def open_db(db_path: Path) -> sqlite3.Connection:
    ensure_dir(db_path.parent)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repos (
            repo_name TEXT PRIMARY KEY,
            repo_url TEXT NOT NULL,
            mirror_path TEXT NOT NULL,
            repo_order INTEGER NOT NULL,
            clone_status TEXT NOT NULL DEFAULT 'pending',
            clone_error TEXT NOT NULL DEFAULT '',
            indexed INTEGER NOT NULL DEFAULT 0,
            indexed_commit_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commit_repo (
            sha TEXT NOT NULL,
            repo_name TEXT NOT NULL,
            PRIMARY KEY (sha, repo_name)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_commit_repo_sha ON commit_repo (sha)"
    )
    conn.commit()
    return conn


def sync_repo_table(conn: sqlite3.Connection, repo_records: list[RepoRecord]) -> None:
    conn.executemany(
        """
        INSERT INTO repos (repo_name, repo_url, mirror_path, repo_order)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(repo_name) DO UPDATE SET
            repo_url=excluded.repo_url,
            mirror_path=excluded.mirror_path,
            repo_order=excluded.repo_order
        """,
        [
            (record.repo_name, record.repo_url, str(record.mirror_path), record.order_index)
            for record in repo_records
        ],
    )
    conn.commit()


def run_command(command: list[str], log_path: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    ensure_dir(log_path.parent)
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(command) + "\n")
        if result.stdout:
            handle.write(result.stdout)
            if not result.stdout.endswith("\n"):
                handle.write("\n")
        if result.stderr:
            handle.write(result.stderr)
            if not result.stderr.endswith("\n"):
                handle.write("\n")
        handle.write(f"[exit_code] {result.returncode}\n\n")
    return result


def clone_repositories(
    conn: sqlite3.Connection,
    repo_records: list[RepoRecord],
    clone_logs_root: Path,
) -> tuple[int, int]:
    cloned = 0
    failed = 0
    for index, record in enumerate(repo_records, start=1):
        row = conn.execute(
            "SELECT clone_status FROM repos WHERE repo_name = ?",
            (record.repo_name,),
        ).fetchone()
        clone_status = row[0] if row else "pending"
        if record.mirror_path.exists() and clone_status == "cloned":
            print(
                f"[clone {index}/{len(repo_records)}] skip existing {record.repo_name}",
                flush=True,
            )
            continue
        if record.mirror_path.exists() and clone_status != "cloned":
            conn.execute(
                "UPDATE repos SET clone_status = 'cloned', clone_error = '' WHERE repo_name = ?",
                (record.repo_name,),
            )
            conn.commit()
            print(
                f"[clone {index}/{len(repo_records)}] mark existing {record.repo_name}",
                flush=True,
            )
            continue
        ensure_dir(record.mirror_path.parent)
        log_path = clone_logs_root / f"{mirror_dir_name(record.repo_name)}.log"
        print(f"[clone {index}/{len(repo_records)}] {record.repo_name}", flush=True)
        result = run_command(
            [
                "git",
                "clone",
                "--mirror",
                record.repo_url,
                str(record.mirror_path),
            ],
            log_path=log_path,
        )
        if result.returncode == 0:
            conn.execute(
                "UPDATE repos SET clone_status = 'cloned', clone_error = '' WHERE repo_name = ?",
                (record.repo_name,),
            )
            cloned += 1
        else:
            conn.execute(
                "UPDATE repos SET clone_status = 'failed', clone_error = ? WHERE repo_name = ?",
                ((result.stderr or result.stdout or "").strip()[:2000], record.repo_name),
            )
            failed += 1
        conn.commit()
    return cloned, failed


def iter_rev_list(git_dir: Path) -> Iterable[str]:
    process = subprocess.Popen(
        ["git", f"--git-dir={git_dir}", "rev-list", "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        sha = line.strip()
        if sha:
            yield sha
    stderr_text = ""
    if process.stderr is not None:
        stderr_text = process.stderr.read()
    exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError(
            f"git rev-list failed for {git_dir}: {stderr_text.strip() or exit_code}"
        )


def index_repositories(
    conn: sqlite3.Connection,
    repo_records: list[RepoRecord],
    index_logs_root: Path,
    refresh_indexed_repos: bool,
) -> tuple[int, int]:
    indexed = 0
    skipped = 0
    for index, record in enumerate(repo_records, start=1):
        status_row = conn.execute(
            "SELECT clone_status, indexed FROM repos WHERE repo_name = ?",
            (record.repo_name,),
        ).fetchone()
        if not status_row:
            continue
        clone_status, is_indexed = status_row
        if clone_status != "cloned":
            print(
                f"[index {index}/{len(repo_records)}] skip uncloned {record.repo_name}",
                flush=True,
            )
            skipped += 1
            continue
        if is_indexed and not refresh_indexed_repos:
            print(
                f"[index {index}/{len(repo_records)}] skip indexed {record.repo_name}",
                flush=True,
            )
            skipped += 1
            continue
        if refresh_indexed_repos:
            conn.execute(
                "DELETE FROM commit_repo WHERE repo_name = ?",
                (record.repo_name,),
            )
            conn.execute(
                "UPDATE repos SET indexed = 0, indexed_commit_count = 0 WHERE repo_name = ?",
                (record.repo_name,),
            )
            conn.commit()
        print(f"[index {index}/{len(repo_records)}] {record.repo_name}", flush=True)
        log_path = index_logs_root / f"{mirror_dir_name(record.repo_name)}.log"
        ensure_dir(log_path.parent)
        count = 0
        batch: list[tuple[str, str]] = []
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[index_start] {record.repo_name}\n")
            try:
                for sha in iter_rev_list(record.mirror_path):
                    batch.append((sha, record.repo_name))
                    count += 1
                    if len(batch) >= DEFAULT_BATCH_SIZE:
                        conn.executemany(
                            "INSERT OR IGNORE INTO commit_repo (sha, repo_name) VALUES (?, ?)",
                            batch,
                        )
                        conn.commit()
                        batch.clear()
                if batch:
                    conn.executemany(
                        "INSERT OR IGNORE INTO commit_repo (sha, repo_name) VALUES (?, ?)",
                        batch,
                    )
                    conn.commit()
                    batch.clear()
                conn.execute(
                    "UPDATE repos SET indexed = 1, indexed_commit_count = ? WHERE repo_name = ?",
                    (count, record.repo_name),
                )
                conn.commit()
                handle.write(f"[index_done] commits={count}\n\n")
                indexed += 1
            except Exception as exc:
                conn.execute(
                    "UPDATE repos SET indexed = 0, indexed_commit_count = 0 WHERE repo_name = ?",
                    (record.repo_name,),
                )
                conn.commit()
                handle.write(f"[index_failed] {exc}\n\n")
                raise
    return indexed, skipped


def load_processed_sha_set(metadata_csv: Path) -> set[str]:
    if not metadata_csv.exists() or metadata_csv.stat().st_size == 0:
        return set()
    rows = load_csv_rows(metadata_csv)
    return {row.get("sha", "") for row in rows if row.get("sha")}


def reset_backfill_outputs(output_dir: Path) -> None:
    for name in [
        "resolved_metadata.csv",
        "resolved_commit_texts.jsonl",
        "unresolved_metadata.csv",
        "summary.json",
    ]:
        target = output_dir / name
        if target.exists():
            target.unlink()


def ensure_csv_with_header(path: Path, fieldnames: list[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()


def append_csv_row(path: Path, fieldnames: list[str], row: dict) -> None:
    ensure_csv_with_header(path, fieldnames)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerow(row)


def append_jsonl_row(path: Path, row: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_diff_from_mirror(mirror_path: Path, sha: str) -> str:
    result = subprocess.run(
        [
            "git",
            f"--git-dir={mirror_path}",
            "--no-pager",
            "show",
            "--format=",
            "--no-color",
            "--no-ext-diff",
            sha,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"git show failed for {sha}")
    return result.stdout


def resolve_sha(conn: sqlite3.Connection, sha: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT cr.repo_name, r.mirror_path
        FROM commit_repo cr
        JOIN repos r ON r.repo_name = cr.repo_name
        WHERE cr.sha = ?
        ORDER BY r.repo_order ASC, cr.repo_name ASC
        """,
        (sha,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def backfill_dataset(
    conn: sqlite3.Connection,
    allcommits_csv: Path,
    output_dir: Path,
    commit_offset: int,
    commit_limit: int,
    refresh_backfill: bool,
) -> dict:
    ensure_dir(output_dir)
    if refresh_backfill:
        reset_backfill_outputs(output_dir)
    resolved_csv = output_dir / "resolved_metadata.csv"
    unresolved_csv = output_dir / "unresolved_metadata.csv"
    commit_texts_jsonl = output_dir / "resolved_commit_texts.jsonl"
    processed = load_processed_sha_set(resolved_csv) | load_processed_sha_set(unresolved_csv)
    rows = load_csv_rows(allcommits_csv)
    if commit_offset > 0:
        rows = rows[commit_offset:]
    if commit_limit > 0:
        rows = rows[:commit_limit]

    resolved_fields = [
        "sha",
        "type",
        "commit_message",
        "resolved_repo",
        "commit_url",
        "resolution_status",
        "repo_candidate_count",
        "candidate_repos",
        "diff_line_count",
        "diff_char_count",
        "diff_error",
    ]
    unresolved_fields = [
        "sha",
        "type",
        "commit_message",
        "resolution_status",
        "repo_candidate_count",
        "candidate_repos",
        "diff_error",
    ]
    counts = {
        "input_rows": len(rows),
        "already_processed": 0,
        "resolved": 0,
        "no_local_repo": 0,
        "diff_error": 0,
    }
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        sha = (row.get("sha") or "").strip()
        if not sha:
            continue
        if sha in processed:
            counts["already_processed"] += 1
            if index % 100 == 0 or index == total:
                print(
                    f"[backfill {index}/{total}] skip processed={counts['already_processed']}",
                    flush=True,
                )
            continue
        matches = resolve_sha(conn, sha)
        candidate_repos = [match[0] for match in matches]
        if not matches:
            append_csv_row(
                unresolved_csv,
                unresolved_fields,
                {
                    "sha": sha,
                    "type": row.get("type", ""),
                    "commit_message": row.get("commit_message", ""),
                    "resolution_status": "no_local_repo",
                    "repo_candidate_count": 0,
                    "candidate_repos": "",
                    "diff_error": "",
                },
            )
            counts["no_local_repo"] += 1
            processed.add(sha)
            if index % 50 == 0 or index == total:
                print(
                    f"[backfill {index}/{total}] no_local_repo={counts['no_local_repo']} resolved={counts['resolved']}",
                    flush=True,
                )
            continue
        resolved_repo, mirror_path_text = matches[0]
        diff_error = ""
        try:
            git_diff = fetch_diff_from_mirror(Path(mirror_path_text), sha)
            diff_line_count = git_diff.count("\n") + (1 if git_diff else 0)
            diff_char_count = len(git_diff)
            append_csv_row(
                resolved_csv,
                resolved_fields,
                {
                    "sha": sha,
                    "type": row.get("type", ""),
                    "commit_message": row.get("commit_message", ""),
                    "resolved_repo": resolved_repo,
                    "commit_url": f"https://github.com/{resolved_repo}/commit/{sha}",
                    "resolution_status": "resolved_local",
                    "repo_candidate_count": len(candidate_repos),
                    "candidate_repos": ",".join(candidate_repos),
                    "diff_line_count": diff_line_count,
                    "diff_char_count": diff_char_count,
                    "diff_error": "",
                },
            )
            append_jsonl_row(
                commit_texts_jsonl,
                {
                    "sha": sha,
                    "repo": resolved_repo,
                    "type": row.get("type", ""),
                    "commit_message": row.get("commit_message", ""),
                    "git_diff": git_diff,
                },
            )
            counts["resolved"] += 1
        except Exception as exc:
            diff_error = str(exc)[:2000]
            append_csv_row(
                unresolved_csv,
                unresolved_fields,
                {
                    "sha": sha,
                    "type": row.get("type", ""),
                    "commit_message": row.get("commit_message", ""),
                    "resolution_status": "diff_error",
                    "repo_candidate_count": len(candidate_repos),
                    "candidate_repos": ",".join(candidate_repos),
                    "diff_error": diff_error,
                },
            )
            counts["diff_error"] += 1
        processed.add(sha)
        if index % 25 == 0 or index == total:
            print(
                (
                    f"[backfill {index}/{total}] resolved={counts['resolved']} "
                    f"no_local_repo={counts['no_local_repo']} diff_error={counts['diff_error']}"
                ),
                flush=True,
            )
    (output_dir / "summary.json").write_text(
        json.dumps(counts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return counts


def main() -> int:
    args = parse_args()
    work_root = Path(args.work_root)
    output_dir = Path(args.output_dir)
    mirrors_root = work_root / "mirrors"
    logs_root = work_root / "logs"
    clone_logs_root = logs_root / "clone"
    index_logs_root = logs_root / "index"
    db_path = work_root / "sha_index.sqlite"

    ensure_dir(work_root)
    ensure_dir(output_dir)
    repo_records = load_repo_records(
        repo_list_csv=Path(args.repo_list_csv),
        mirrors_root=mirrors_root,
        repo_offset=args.repo_offset,
        repo_limit=args.repo_limit,
    )
    print(f"[setup] repos={len(repo_records)} work_root={work_root}", flush=True)

    conn = open_db(db_path)
    try:
        sync_repo_table(conn, repo_records)

        if not args.skip_clone:
            cloned, failed = clone_repositories(
                conn=conn,
                repo_records=repo_records,
                clone_logs_root=clone_logs_root,
            )
            print(f"[clone_done] cloned_now={cloned} failed_now={failed}", flush=True)

        if not args.skip_index:
            indexed, skipped = index_repositories(
                conn=conn,
                repo_records=repo_records,
                index_logs_root=index_logs_root,
                refresh_indexed_repos=args.refresh_indexed_repos,
            )
            print(f"[index_done] indexed_now={indexed} skipped={skipped}", flush=True)

        if not args.skip_backfill:
            counts = backfill_dataset(
                conn=conn,
                allcommits_csv=Path(args.allcommits_csv),
                output_dir=output_dir,
                commit_offset=args.commit_offset,
                commit_limit=args.commit_limit,
                refresh_backfill=args.refresh_backfill,
            )
            print(f"[backfill_done] {json.dumps(counts, ensure_ascii=False)}", flush=True)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
