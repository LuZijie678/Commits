from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str]) -> list[str]:
    return subprocess.check_output(args, cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).splitlines()


def classify_tracked_file(rel: str) -> str:
    if rel.startswith("outputs/"):
        if "/reports/" in rel and Path(rel).suffix in {".md", ".json"}:
            return "manual_review_required"
        return "likely_temporary_outputs"
    if rel.startswith("datasets/hard_b/canonical/") or rel.startswith("datasets/m_verified/canonical/"):
        return "likely_formal_data_assets"
    if rel.startswith("datasets/") and Path(rel).suffix in {".csv", ".jsonl", ".json"}:
        return "likely_formal_data_assets"
    if rel.startswith("archive/"):
        return "manual_review_required"
    return "manual_review_required"


def _file_size(repo_root: Path, rel: str) -> int:
    path = repo_root / rel
    return path.stat().st_size if path.exists() and path.is_file() else 0


def _experiment_root(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 and parts[0] == "outputs" else ""


def _parse_lfs_path(line: str) -> str:
    parts = line.split()
    return parts[-1] if parts else ""


def audit_tracking(
    *,
    tracked_files: list[str],
    lfs_lines: list[str],
    gitattributes_text: str,
    gitignore_text: str,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    tracked_outputs = [rel for rel in tracked_files if rel.startswith("outputs/")]
    lfs_paths = [_parse_lfs_path(line) for line in lfs_lines if _parse_lfs_path(line)]
    classifications: dict[str, list[str]] = {
        "likely_temporary_outputs": [],
        "likely_formal_data_assets": [],
        "manual_review_required": [],
    }
    for rel in tracked_files:
        classifications.setdefault(classify_tracked_file(rel), []).append(rel)

    top_large_files = sorted(
        [{"path": rel, "bytes": _file_size(repo_root, rel)} for rel in tracked_files],
        key=lambda row: row["bytes"],
        reverse=True,
    )[:100]
    outputs_by_root: dict[str, dict[str, int]] = defaultdict(lambda: {"file_count": 0, "total_bytes": 0})
    for rel in tracked_outputs:
        root = _experiment_root(rel) or "outputs"
        outputs_by_root[root]["file_count"] += 1
        outputs_by_root[root]["total_bytes"] += _file_size(repo_root, rel)

    ignored_patterns = [line.strip() for line in gitignore_text.splitlines() if line.strip() and not line.strip().startswith("#")]
    files_tracked_despite_gitignore = [
        rel
        for rel in tracked_files
        if rel.startswith("outputs/llm_generation_pilot_")
        or rel.startswith("outputs/llm_generation_canary_")
        or rel.startswith("outputs/step3_")
    ]
    return {
        "schema_version": "git_lfs_tracking_audit_v1",
        "tracked_file_count": len(tracked_files),
        "tracked_output_file_count": len(tracked_outputs),
        "tracked_output_total_bytes": sum(_file_size(repo_root, rel) for rel in tracked_outputs),
        "lfs_file_count": len(lfs_paths),
        "lfs_total_local_bytes": sum(_file_size(repo_root, rel) for rel in lfs_paths),
        "top_large_files": top_large_files,
        "tracked_files_by_top_level_dir": dict(Counter(rel.split("/", 1)[0] for rel in tracked_files)),
        "tracked_outputs_by_experiment_root": dict(sorted(outputs_by_root.items())),
        "gitattributes_rules": [line for line in gitattributes_text.splitlines() if line.strip()],
        "gitignore_rules": [line for line in gitignore_text.splitlines() if line.strip()],
        "files_tracked_despite_gitignore": files_tracked_despite_gitignore,
        "likely_temporary_outputs": sorted(classifications["likely_temporary_outputs"]),
        "likely_formal_data_assets": sorted(classifications["likely_formal_data_assets"]),
        "manual_review_required": sorted(classifications["manual_review_required"]),
        "lfs_paths": sorted(lfs_paths),
        "policy_interpretation": {
            "outputs_lfs_rule_present": any("outputs/" in line for line in gitattributes_text.splitlines()),
            "global_jsonl_lfs_rule_present": any(line.strip().startswith("*.jsonl") for line in gitattributes_text.splitlines()),
            "history_cleanup_required_for_existing_lfs_objects": "unknown_without_remote_push_audit",
        },
        "ignored_pattern_count": len(ignored_patterns),
    }


def write_audit_reports(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "git_lfs_tracking_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / "tracked_outputs_inventory.csv", report["likely_temporary_outputs"], ["path", "bytes"], lambda path: {"path": path, "bytes": _file_size(REPO_ROOT, path)})
    _write_csv(output_dir / "lfs_inventory.csv", report["lfs_paths"], ["path", "bytes"], lambda path: {"path": path, "bytes": _file_size(REPO_ROOT, path)})
    lines = [
        "# Git LFS Tracking Audit",
        "",
        f"- Tracked files: `{report['tracked_file_count']}`",
        f"- Tracked output files: `{report['tracked_output_file_count']}`",
        f"- Tracked output bytes: `{report['tracked_output_total_bytes']}`",
        f"- LFS files: `{report['lfs_file_count']}`",
        f"- LFS local bytes: `{report['lfs_total_local_bytes']}`",
        f"- outputs/** LFS rule present: `{report['policy_interpretation']['outputs_lfs_rule_present']}`",
        f"- global *.jsonl LFS rule present: `{report['policy_interpretation']['global_jsonl_lfs_rule_present']}`",
        "",
        "## Interpretation",
        "",
        "Runtime `outputs/**` directories are timestamped experiment artifacts and should not be versioned. Existing LFS objects under `datasets/**` and `archive/**` are historical/formal data assets and are not rewritten by this audit.",
        "",
        "## Largest Tracked Files",
        "",
    ]
    for row in report["top_large_files"][:20]:
        lines.append(f"- `{row['path']}`: `{row['bytes']}` bytes")
    (output_dir / "git_lfs_tracking_audit.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[str], fieldnames: list[str], row_fn: Any) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            writer.writerow(row_fn(item))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    gitattributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8") if (REPO_ROOT / ".gitattributes").exists() else ""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8") if (REPO_ROOT / ".gitignore").exists() else ""
    report = audit_tracking(
        tracked_files=_run(["git", "ls-files"]),
        lfs_lines=_run(["git", "lfs", "ls-files"]),
        gitattributes_text=gitattributes,
        gitignore_text=gitignore,
    )
    write_audit_reports(report, REPO_ROOT / args.output_dir)
    print(json.dumps({key: report[key] for key in ["tracked_output_file_count", "lfs_file_count", "tracked_output_total_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
