import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


CSV_FIELD_SIZE_LIMIT = 2**31 - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover unresolved CCS commits when repo clues are available."
    )
    parser.add_argument(
        "--output-dir",
        default=r"full_experiment\step1\offline_backfill\outputs\allcommits_local_backfill",
    )
    parser.add_argument(
        "--annotated-dataset",
        default=r"external\conventional-commit-classification\Dataset\annotated_dataset.csv",
    )
    parser.add_argument(
        "--work-root",
        default=r"full_experiment\step1\offline_backfill\workdir",
    )
    parser.add_argument(
        "--keep-mirrors",
        action="store_true",
        help="Keep temporary recovery mirrors after the run.",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_csv_rows(path: Path) -> list[dict]:
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def append_jsonl_rows(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def repo_name_from_commit_url(commit_url: str) -> str:
    pieces = [piece for piece in urlparse(commit_url).path.strip("/").split("/") if piece]
    if len(pieces) < 4:
        raise ValueError(f"Invalid commit URL: {commit_url}")
    return "/".join(pieces[:2])


def mirror_dir_name(repo_name: str) -> str:
    return repo_name.replace("/", "__") + ".git"


def clone_repo(repo_name: str, target: Path) -> tuple[bool, str]:
    if (target / "HEAD").exists() and (target / "objects").exists():
        return True, ""
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    ensure_dir(target.parent)
    repo_url = f"https://github.com/{repo_name}.git"
    result = subprocess.run(
        ["git", "clone", "--mirror", repo_url, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "").strip()


def fetch_diff_from_mirror(mirror_path: Path, sha: str) -> tuple[str | None, str]:
    result = subprocess.run(
        [
            "git",
            f"--git-dir={mirror_path}",
            "-c",
            "core.pager=cat",
            "-c",
            "diff.external=",
            "--no-pager",
            "show",
            "--format=",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            sha,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout, ""
    return None, (result.stderr or result.stdout or "").strip()


def fetch_diff_from_commit_url(commit_url: str) -> tuple[str | None, str]:
    diff_url = commit_url + ".diff"
    request = Request(
        diff_url,
        headers={
            "User-Agent": "codex-recover-unresolved-commits",
            "Accept": "text/plain",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - network errors are environment-specific
        return None, str(exc)
    if not body.strip():
        return None, "empty diff response"
    if body.lstrip().startswith("<!DOCTYPE html") or body.lstrip().startswith("<html"):
        return None, "html response instead of diff"
    if "diff --git " not in body and not body.startswith("From "):
        return None, "response does not look like a git diff"
    return body, ""


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    annotated_dataset = Path(args.annotated_dataset)
    recovery_root = Path(args.work_root) / "recovery_mirrors"

    resolved_csv = output_dir / "resolved_metadata.csv"
    unresolved_csv = output_dir / "unresolved_metadata.csv"
    resolved_jsonl = output_dir / "resolved_commit_texts.jsonl"
    dedupe_script = output_dir.parent.parent / "dedupe_backfill_outputs.py"

    resolved_rows = load_csv_rows(resolved_csv)
    unresolved_rows = load_csv_rows(unresolved_csv)

    resolved_fields = list(resolved_rows[0].keys()) if resolved_rows else [
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
    unresolved_fields = list(unresolved_rows[0].keys()) if unresolved_rows else [
        "sha",
        "type",
        "commit_message",
        "resolution_status",
        "repo_candidate_count",
        "candidate_repos",
        "diff_error",
    ]

    annotated_by_sha: dict[str, dict] = {}
    for row in load_csv_rows(annotated_dataset):
        annotated_by_sha[row["sha"]] = row

    recovery_targets: list[dict] = []
    for row in unresolved_rows:
        repo_name = ""
        commit_url = ""
        source = ""
        if row.get("resolution_status") == "diff_error" and row.get("candidate_repos"):
            repo_name = row["candidate_repos"].split(",")[0].strip()
            commit_url = f"https://github.com/{repo_name}/commit/{row['sha']}"
            source = "diff_error_candidate_repo"
        elif row["sha"] in annotated_by_sha:
            commit_url = annotated_by_sha[row["sha"]].get("commit_url", "").strip()
            if commit_url:
                repo_name = repo_name_from_commit_url(commit_url)
                source = "annotated_commit_url"
        if repo_name:
            recovery_targets.append(
                {
                    "sha": row["sha"],
                    "type": row.get("type", ""),
                    "commit_message": row.get("commit_message", ""),
                    "repo_name": repo_name,
                    "commit_url": commit_url,
                    "source": source,
                    "old_status": row.get("resolution_status", ""),
                }
            )

    print(f"recovery_targets={len(recovery_targets)}")
    if not recovery_targets:
        return 0

    by_repo: dict[str, list[dict]] = {}
    for target in recovery_targets:
        by_repo.setdefault(target["repo_name"], []).append(target)

    recovered_rows: dict[str, dict] = {}
    recovered_jsonl: dict[str, dict] = {}
    failed: list[tuple[str, str, str]] = []

    for repo_name, targets in sorted(by_repo.items()):
        mirror_path = recovery_root / mirror_dir_name(repo_name)
        ok, clone_error = clone_repo(repo_name, mirror_path)
        print(f"[repo] {repo_name} targets={len(targets)} clone_ok={ok}")
        for target in targets:
            sha = target["sha"]
            git_diff = None
            error_parts: list[str] = []
            if ok:
                git_diff, err = fetch_diff_from_mirror(mirror_path, sha)
                if err:
                    error_parts.append(f"mirror:{err[:240]}")
            if git_diff is None and target["commit_url"]:
                git_diff, err = fetch_diff_from_commit_url(target["commit_url"])
                if err:
                    error_parts.append(f"url:{err[:240]}")
            if git_diff is None:
                failed.append((sha, repo_name, " | ".join(error_parts) or clone_error[:240]))
                continue
            diff_line_count = git_diff.count("\n") + (1 if git_diff else 0)
            diff_char_count = len(git_diff)
            recovered_rows[sha] = {
                "sha": sha,
                "type": target["type"],
                "commit_message": target["commit_message"],
                "resolved_repo": repo_name,
                "commit_url": target["commit_url"] or f"https://github.com/{repo_name}/commit/{sha}",
                "resolution_status": f"resolved_recovery_{target['source']}",
                "repo_candidate_count": 1,
                "candidate_repos": repo_name,
                "diff_line_count": diff_line_count,
                "diff_char_count": diff_char_count,
                "diff_error": "",
            }
            recovered_jsonl[sha] = {
                "sha": sha,
                "repo": repo_name,
                "type": target["type"],
                "commit_message": target["commit_message"],
                "git_diff": git_diff,
            }

    print(f"recovered={len(recovered_rows)}")
    print(f"failed={len(failed)}")
    for sha, repo_name, error_text in failed[:20]:
        print(f"FAILED {sha} {repo_name} {error_text}")

    if recovered_rows:
        resolved_by_sha = {row["sha"]: row for row in resolved_rows}
        unresolved_by_sha = {row["sha"]: row for row in unresolved_rows}

        for sha, row in recovered_rows.items():
            resolved_by_sha[sha] = row
            unresolved_by_sha.pop(sha, None)

        write_csv_rows(
            resolved_csv,
            resolved_fields,
            list(resolved_by_sha.values()),
        )
        write_csv_rows(
            unresolved_csv,
            unresolved_fields,
            list(unresolved_by_sha.values()),
        )
        append_jsonl_rows(resolved_jsonl, list(recovered_jsonl.values()))
        subprocess.run(
            [sys.executable, str(dedupe_script)],
            check=True,
        )

    if not args.keep_mirrors and recovery_root.exists():
        for child in recovery_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
