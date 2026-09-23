#!/usr/bin/env python3
"""Build the Step3 hard-B negative pool from existing pilot labels.

The script treats the LLM B label as a hard gate, joins back real diff evidence
from existing batch/recovery files, filters out easy/suspicious cases, and
exports both the usable real-diff pool and the missing-diff recovery batch.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REAL_DIFF_MARKER = "diff --git "
FALLBACK_PREFIX = "[Diff unavailable in blobless/local extraction."

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

OUTPUT_FIELDS = [
    "repo",
    "sha",
    "commit_url",
    "language",
    "commit_date",
    "subject",
    "commit_message",
    "candidate_layer",
    "m_candidate_score",
    "m_candidate_reasons",
    "llm_label",
    "llm_is_multi_intent",
    "llm_reason",
    "llm_intent_count_estimate",
    "llm_intent_summaries",
    "llm_evidence_from_message",
    "llm_evidence_from_diff",
    "llm_uncertainty",
    "llm_model",
    "llm_created_at_utc",
    "llm_error",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
    "file_count",
    "hunk_count",
    "changed_lines",
    "dir_count",
    "path_roles",
    "top_dirs",
    "changed_files",
    "shortstat",
    "hard_b_score",
    "hard_b_reasons",
    "exclusion_reasons",
    "pilot_only",
    "blocklist_overlap",
    "diff_source",
    "diff_status",
    "diff_error",
    "remote_diff_error",
    "diff_char_count_original",
    "diff_truncated",
    "git_diff",
]

NEED_DIFF_FIELDS = [
    "repo",
    "sha",
    "commit_url",
    "language",
    "commit_date",
    "subject",
    "commit_message",
    "candidate_layer",
    "m_candidate_score",
    "m_candidate_reasons",
    "llm_label",
    "llm_is_multi_intent",
    "llm_reason",
    "llm_intent_count_estimate",
    "llm_intent_summaries",
    "llm_evidence_from_message",
    "llm_evidence_from_diff",
    "llm_uncertainty",
    "llm_model",
    "llm_created_at_utc",
    "llm_error",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
    "file_count",
    "path_roles",
    "top_dirs",
    "changed_files",
    "shortstat",
    "hard_b_score",
    "hard_b_reasons",
    "exclusion_reasons",
    "pilot_only",
    "blocklist_overlap",
    "diff_status",
    "diff_error",
    "evidence_mode",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def iter_csv_paths(base: Path) -> list[Path]:
    if not base.exists():
        return []
    if base.is_file():
        return [base] if base.suffix.lower() == ".csv" else []
    return sorted(path for path in base.rglob("*.csv") if path.is_file())


def compact_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    original_len = len(text)
    if max_chars <= 0 or original_len <= max_chars:
        return text, False, original_len
    head = int(max_chars * 0.70)
    tail = max_chars - head
    omitted = original_len - max_chars
    compact = text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]
    return compact, True, original_len


def has_real_diff(text: str) -> bool:
    if not text:
        return False
    if text.lstrip().startswith(FALLBACK_PREFIX):
        return False
    if "[... truncated " in text:
        return False
    return REAL_DIFF_MARKER in text


def parse_int(value: str) -> int:
    if not value:
        return 0
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else 0


def split_paths(value: str) -> list[str]:
    if not value:
        return []
    paths: list[str] = []
    for chunk in re.split(r"[\n;|,]+", value):
        item = chunk.strip().strip('"')
        if item:
            paths.append(item)
    return paths


def infer_dirs(paths: Iterable[str]) -> set[str]:
    dirs: set[str] = set()
    for path in paths:
        clean = path.strip()
        if not clean:
            continue
        if clean.startswith("a/") or clean.startswith("b/"):
            clean = clean[2:]
        clean = clean.split(" => ")[-1].strip("{}")
        dirs.add(clean.split("/", 1)[0] if "/" in clean else ".")
    return dirs


def infer_roles(paths: Iterable[str]) -> set[str]:
    roles: set[str] = set()
    for path in paths:
        p = path.lower()
        name = p.rsplit("/", 1)[-1]
        if any(part in p for part in ("/test/", "/tests/", "__tests__", "spec/", ".test.", ".spec.")):
            roles.add("test")
        if any(part in p for part in ("/docs/", "readme", ".md", ".rst")):
            roles.add("docs")
        if any(part in p for part in (".github/", "/ci/", "workflow", "jenkins", "circleci")):
            roles.add("ci")
        if any(name.endswith(ext) for ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf")):
            roles.add("config")
        if any(part in p for part in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock")):
            roles.add("lock")
        if any(part in p for part in ("vendor/", "third_party/", "third-party/", "node_modules/", "dist/", "build/")):
            roles.add("vendor_or_generated")
        if not roles or not {"test", "docs", "ci", "config", "lock", "vendor_or_generated"} & roles:
            if any(name.endswith(ext) for ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".cs", ".cpp", ".c", ".h", ".rb", ".php", ".swift", ".scala")):
                roles.add("source")
    return roles


def diff_stats(diff: str) -> dict[str, object]:
    files: list[str] = []
    hunk_count = 0
    changed_lines = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 3:
                path = parts[2][2:] if parts[2].startswith("a/") else parts[2]
                files.append(path)
        elif line.startswith("@@"):
            hunk_count += 1
        elif (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---")):
            changed_lines += 1
    dirs = infer_dirs(files)
    return {
        "file_count": len(files),
        "hunk_count": hunk_count,
        "changed_lines": changed_lines,
        "dir_count": len(dirs),
        "changed_files": "\n".join(files),
        "top_dirs": ";".join(sorted(dirs)),
        "roles": infer_roles(files),
    }


def metadata_stats(row: dict[str, str]) -> dict[str, object]:
    paths = split_paths(row.get("changed_files", ""))
    file_count = parse_int(row.get("file_count", "")) or len(paths)
    shortstat = row.get("shortstat", "")
    changed = 0
    if shortstat:
        nums = [int(x) for x in re.findall(r"\d+", shortstat)]
        if len(nums) >= 3:
            changed = nums[-2] + nums[-1]
        elif len(nums) >= 2:
            changed = nums[-1]
    dirs = infer_dirs(paths)
    roles = set(filter(None, re.split(r"[+;,| ]+", row.get("path_roles", "")))) | infer_roles(paths)
    return {
        "file_count": file_count,
        "hunk_count": 0,
        "changed_lines": changed,
        "dir_count": len(dirs),
        "changed_files": "\n".join(paths),
        "top_dirs": row.get("top_dirs", "") or ";".join(sorted(dirs)),
        "roles": roles,
    }


def discover_evidence_files(labels_dir: Path, raw_dir: Path, extra_csvs: list[Path] | None = None) -> list[Path]:
    generated_names = {
        "usable_m_with_real_diff.csv",
        "usable_hard_b_with_real_diff.csv",
        "hard_b_candidates_labeled.csv",
        "hard_b_need_full_diff.csv",
        "hard_b_full_diff_recovery_batch.csv",
        "m_missing_real_diff_to_recover.csv",
    }
    files: list[Path] = []
    for base in (labels_dir, raw_dir):
        for path in iter_csv_paths(base):
            name = path.name.lower()
            if name in generated_names:
                continue
            if "labeled" in name or "combined" in name or "current_m_candidates" in name:
                continue
            files.append(path)
    for path in extra_csvs or []:
        if path.exists():
            files.append(path)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(path)
    return deduped


def load_evidence(paths: list[Path]) -> dict[tuple[str, str], list[dict[str, str]]]:
    evidence: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for path in paths:
        try:
            rows = read_csv(path)
        except (OSError, csv.Error):
            continue
        if not rows:
            continue
        fields = set(rows[0].keys())
        if not {"repo", "sha"}.issubset(fields):
            continue
        if not ({"git_diff", "changed_files", "shortstat"} & fields):
            continue
        for row in rows:
            repo = row.get("repo", "")
            sha = row.get("sha", "")
            if not repo or not sha:
                continue
            item = dict(row)
            item["_batch_source"] = str(path)
            evidence[(repo, sha)].append(item)
    return evidence


def choose_real_diff(rows: list[dict[str, str]]) -> dict[str, str] | None:
    real = [row for row in rows if has_real_diff(row.get("git_diff", ""))]
    if not real:
        return None
    real.sort(
        key=lambda row: (
            1 if row.get("diff_status") == "ok" else 0,
            len(row.get("git_diff", "")),
        ),
        reverse=True,
    )
    return real[0]


def diff_source_for(row: dict[str, str], recovery_csv: Path) -> str:
    source = row.get("_batch_source", "")
    try:
        if source and Path(source).resolve().match(str(recovery_csv.resolve())):
            return "github_commit_diff_url_recovered"
    except OSError:
        pass
    source_lc = source.replace("\\", "/").lower()
    if "hard_b_full_diff_recovery_batch" in source_lc:
        return "github_commit_diff_url_recovered"
    if row.get("remote_diff_error") or row.get("evidence_mode") == "diff":
        if "full_diff_recovery_batch" in source_lc:
            return "github_commit_diff_url_recovered"
    return "batch_csv_real_diff"


def choose_metadata(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}
    ranked = list(rows)
    ranked.sort(
        key=lambda row: (
            parse_int(row.get("file_count", "")),
            len(row.get("changed_files", "")),
            len(row.get("shortstat", "")),
            len(row.get("git_diff", "")),
        ),
        reverse=True,
    )
    return ranked[0]


EXCLUDE_SUBJECT_PATTERNS = [
    (re.compile(r"\bmerge\b", re.I), "merge"),
    (re.compile(r"\brevert\b", re.I), "revert"),
    (re.compile(r"\brelease\b|\bversion bump\b|\bchangelog\b", re.I), "release"),
    (re.compile(r"\bformat(ting)?\b|\bprettier\b|\bblack\b|\bgofmt\b|\brustfmt\b", re.I), "format_only_risk"),
    (re.compile(r"\bvendor\b|\bthird[-_ ]party\b|\bgenerated\b", re.I), "vendor_or_generated_risk"),
]

LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "gemfile.lock",
}


def exclusion_reasons(row: dict[str, str], stats: dict[str, object], allow_blocklist: bool) -> list[str]:
    reasons: list[str] = []
    text = f"{row.get('subject', '')}\n{row.get('commit_message', '')}".lower()
    subject = row.get("subject", "")
    for regex, reason in EXCLUDE_SUBJECT_PATTERNS:
        if regex.search(subject) or regex.search(row.get("commit_message", "")):
            reasons.append(reason)
    if row.get("llm_label") != "B":
        reasons.append("not_B_label")
    if row.get("llm_error"):
        reasons.append("llm_error")
    if row.get("llm_uncertainty", "").lower() not in {"", "low", "medium"}:
        reasons.append("high_uncertainty")
    if row.get("blocklist_overlap") == "1" and not allow_blocklist:
        reasons.append("blocklist_repo")
    file_count = int(stats.get("file_count") or 0)
    changed_lines = int(stats.get("changed_lines") or 0)
    hunk_count = int(stats.get("hunk_count") or 0)
    if file_count <= 1 and changed_lines < 40:
        reasons.append("too_small_or_single_file")
    paths = split_paths(str(stats.get("changed_files", "")))
    if paths:
        lock_paths = [path for path in paths if path.rsplit("/", 1)[-1].lower() in LOCKFILE_NAMES]
        if len(lock_paths) == len(paths):
            reasons.append("lockfile_only")
        vendor_paths = [
            path
            for path in paths
            if any(part in path.lower() for part in ("vendor/", "third_party/", "third-party/", "node_modules/", "dist/", "build/"))
        ]
        if len(vendor_paths) == len(paths):
            reasons.append("vendor_generated_only")
    if "format_only_risk" in reasons and changed_lines > 200 and hunk_count <= max(2, file_count):
        reasons.append("likely_format_only")
    if any(word in text for word in ("typo", "spelling", "lint")) and changed_lines < 30:
        reasons.append("small_cleanup")
    return sorted(set(reasons))


def hard_b_score(row: dict[str, str], stats: dict[str, object]) -> tuple[int, list[str]]:
    file_count = int(stats.get("file_count") or 0)
    hunk_count = int(stats.get("hunk_count") or 0)
    changed_lines = int(stats.get("changed_lines") or 0)
    dir_count = int(stats.get("dir_count") or 0)
    roles = set(stats.get("roles") or [])
    score = 0
    reasons: list[str] = []
    if file_count >= 2:
        score += min(file_count, 10) * 5
        reasons.append(f"file_count={file_count}")
    if hunk_count >= 2:
        score += min(hunk_count, 20) * 3
        reasons.append(f"hunk_count={hunk_count}")
    if changed_lines >= 20:
        score += min(changed_lines // 10, 20) * 4
        reasons.append(f"changed_lines={changed_lines}")
    if dir_count >= 2:
        score += dir_count * 8
        reasons.append(f"cross_dirs={dir_count}")
    if len(roles) >= 2:
        score += len(roles) * 6
        reasons.append("roles=" + "+".join(sorted(roles)))
    try:
        candidate_score = float(row.get("m_candidate_score") or 0)
    except ValueError:
        candidate_score = 0.0
    if candidate_score:
        score += min(int(candidate_score // 5), 20)
        reasons.append(f"m_candidate_score={candidate_score:g}")
    if row.get("llm_uncertainty") == "low":
        score += 5
    return score, reasons


def is_complex_hard_b(stats: dict[str, object], score: int) -> bool:
    file_count = int(stats.get("file_count") or 0)
    hunk_count = int(stats.get("hunk_count") or 0)
    changed_lines = int(stats.get("changed_lines") or 0)
    dir_count = int(stats.get("dir_count") or 0)
    return (
        (file_count >= 3 and hunk_count >= 3 and changed_lines >= 20)
        or (file_count >= 2 and hunk_count >= 4 and changed_lines >= 30)
        or (file_count >= 4 and changed_lines >= 12)
        or (dir_count >= 2 and file_count >= 2 and changed_lines >= 20)
        or score >= 65
    )


def load_key_set(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for row in read_csv(path):
        repo = row.get("repo", "")
        sha = row.get("sha", "")
        if repo and sha:
            keys.add((repo, sha))
    return keys


def load_blocklist(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def cap_need_diff_rows(rows: list[dict[str, str]], max_need_diff: int) -> list[dict[str, str]]:
    if max_need_diff <= 0:
        return rows
    return rows[:max_need_diff]


def normalize_row(label_row: dict[str, str], metadata: dict[str, str], blocklist: set[str], allow_blocklist: bool) -> tuple[dict[str, str], dict[str, object]]:
    stats = metadata_stats(metadata)
    if not stats.get("changed_files"):
        stats = metadata_stats(label_row)
    out = dict(label_row)
    for field in ("file_count", "path_roles", "top_dirs", "changed_files", "shortstat", "diff_status", "diff_error", "evidence_mode"):
        if metadata.get(field):
            out[field] = metadata.get(field, "")
    repo_lc = out.get("repo", "").lower()
    out["blocklist_overlap"] = "1" if repo_lc in blocklist else "0"
    out["pilot_only"] = "1" if repo_lc in blocklist and allow_blocklist else "0"
    score, reasons = hard_b_score(out, stats)
    out["hard_b_score"] = str(score)
    out["hard_b_reasons"] = "; ".join(reasons)
    out["exclusion_reasons"] = "; ".join(exclusion_reasons(out, stats, allow_blocklist))
    return out, stats


def build(args: argparse.Namespace) -> dict[str, object]:
    combined_rows = read_csv(args.combined_csv)
    m_keys = load_key_set(args.m_csv)
    blocklist = load_blocklist(args.blocklist)
    recovery_csvs = sorted(args.out_dir.glob("hard_b_full_diff_recovery_batch*.csv"))
    if args.recovery_csv.exists() and args.recovery_csv not in recovery_csvs:
        recovery_csvs.append(args.recovery_csv)
    evidence_files = discover_evidence_files(args.labels_dir, args.raw_dir, recovery_csvs + args.extra_csv)
    evidence = load_evidence(evidence_files)

    candidates: list[dict[str, str]] = []
    need_diff: list[dict[str, str]] = []
    usable: list[dict[str, str]] = []
    skipped_counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    source_counts: Counter[str] = Counter()

    for label_row in combined_rows:
        key = (label_row.get("repo", ""), label_row.get("sha", ""))
        if not key[0] or not key[1]:
            skipped_counts["missing_key"] += 1
            continue
        if key in seen:
            skipped_counts["duplicate_label_row"] += 1
            continue
        seen.add(key)
        if label_row.get("llm_label") != "B":
            skipped_counts["not_B"] += 1
            continue
        if key in m_keys:
            skipped_counts["m_pool_overlap"] += 1
            continue

        evidence_rows = evidence.get(key, [])
        metadata = choose_metadata(evidence_rows)
        candidate_row, metadata_only_stats = normalize_row(label_row, metadata, blocklist, args.allow_blocklist)
        meta_score = parse_int(candidate_row.get("hard_b_score", ""))
        candidate_row["diff_source"] = ""
        candidate_row["remote_diff_error"] = metadata.get("remote_diff_error", "")

        real = choose_real_diff(evidence_rows)
        if real:
            stats = diff_stats(real.get("git_diff", ""))
            if not candidate_row.get("changed_files"):
                candidate_row["changed_files"] = str(stats.get("changed_files", ""))
            if not candidate_row.get("top_dirs"):
                candidate_row["top_dirs"] = str(stats.get("top_dirs", ""))
            if not candidate_row.get("path_roles"):
                candidate_row["path_roles"] = "+".join(sorted(stats.get("roles") or []))
            candidate_row["file_count"] = str(stats.get("file_count", ""))
            candidate_row["hunk_count"] = str(stats.get("hunk_count", ""))
            candidate_row["changed_lines"] = str(stats.get("changed_lines", ""))
            candidate_row["dir_count"] = str(stats.get("dir_count", ""))
            score, reasons = hard_b_score(candidate_row, stats)
            candidate_row["hard_b_score"] = str(score)
            candidate_row["hard_b_reasons"] = "; ".join(reasons)
            candidate_row["exclusion_reasons"] = "; ".join(exclusion_reasons(candidate_row, stats, args.allow_blocklist))
            candidate_row["diff_source"] = diff_source_for(real, args.recovery_csv)
            candidate_row["diff_status"] = real.get("diff_status") or "ok"
            candidate_row["diff_error"] = real.get("diff_error", "")
            candidate_row["remote_diff_error"] = real.get("remote_diff_error", "")
            candidate_row["diff_char_count_original"] = str(len(real.get("git_diff", "")))
            compact_diff, truncated, original_len = compact_text(real.get("git_diff", ""), args.diff_max_chars)
            candidate_row["git_diff"] = compact_diff
            candidate_row["diff_char_count_original"] = str(original_len)
            candidate_row["diff_truncated"] = "1" if truncated else "0"
            if is_complex_hard_b(stats, score) and not candidate_row["exclusion_reasons"]:
                usable.append({field: candidate_row.get(field, "") for field in OUTPUT_FIELDS})
                source_counts[candidate_row["diff_source"]] += 1
            else:
                for reason in candidate_row["exclusion_reasons"].split("; "):
                    if reason:
                        skipped_counts[reason] += 1
                if not is_complex_hard_b(stats, score):
                    skipped_counts["not_complex_enough"] += 1
        else:
            candidate_row["file_count"] = str(metadata_only_stats.get("file_count") or candidate_row.get("file_count", ""))
            candidate_row["hunk_count"] = str(metadata_only_stats.get("hunk_count") or "")
            candidate_row["changed_lines"] = str(metadata_only_stats.get("changed_lines") or "")
            candidate_row["dir_count"] = str(metadata_only_stats.get("dir_count") or "")
            if not candidate_row.get("path_roles"):
                candidate_row["path_roles"] = "+".join(sorted(metadata_only_stats.get("roles") or []))
            score = parse_int(candidate_row.get("hard_b_score", ""))
            if is_complex_hard_b(metadata_only_stats, score) and not candidate_row["exclusion_reasons"]:
                need_row = {field: candidate_row.get(field, "") for field in NEED_DIFF_FIELDS}
                need_row["diff_status"] = candidate_row.get("diff_status", "")
                need_row["diff_error"] = candidate_row.get("diff_error", "")
                need_row["evidence_mode"] = "missing_diff"
                need_diff.append(need_row)

        candidates.append({field: candidate_row.get(field, "") for field in OUTPUT_FIELDS if field != "git_diff"} | {"git_diff": ""})

    candidates.sort(key=lambda row: (parse_int(row.get("hard_b_score", "")), row.get("repo", ""), row.get("sha", "")), reverse=True)
    need_diff.sort(key=lambda row: (parse_int(row.get("hard_b_score", "")), row.get("repo", ""), row.get("sha", "")), reverse=True)
    usable.sort(key=lambda row: (parse_int(row.get("hard_b_score", "")), row.get("repo", ""), row.get("sha", "")), reverse=True)
    need_diff = cap_need_diff_rows(need_diff, args.max_need_diff)

    review_sample = balanced_review_sample(usable, args.review_sample_size)

    write_csv(args.candidates_csv, candidates, [field for field in OUTPUT_FIELDS if field != "git_diff"] + ["git_diff"])
    write_csv(args.need_diff_csv, need_diff, NEED_DIFF_FIELDS)
    write_csv(args.output_csv, usable, OUTPUT_FIELDS)
    write_jsonl(args.output_jsonl, usable)
    write_csv(args.review_sample_csv, review_sample, [field for field in OUTPUT_FIELDS if field != "git_diff"] + ["git_diff_excerpt"])

    repo_counts = Counter(row["repo"] for row in usable)
    blocklist_rows = [row for row in usable if row.get("blocklist_overlap") == "1"]
    manifest = {
        "created_at_utc": utc_now(),
        "goal": "Step3 hard B negative pool: B-labeled broad/complex single-purpose commits with validated real git diffs",
        "inputs": {
            "combined_csv": str(args.combined_csv),
            "m_positive_pool_csv": str(args.m_csv),
            "blocklist": str(args.blocklist),
            "recovery_csv": str(args.recovery_csv) if args.recovery_csv.exists() else "",
            "recovery_csvs": [str(path) for path in recovery_csvs],
        },
        "outputs": {
            "hard_b_candidates_labeled_csv": str(args.candidates_csv),
            "hard_b_need_full_diff_csv": str(args.need_diff_csv),
            "usable_hard_b_with_real_diff_csv": str(args.output_csv),
            "usable_hard_b_with_real_diff_jsonl": str(args.output_jsonl),
            "manifest": str(args.manifest),
            "review_sample_csv": str(args.review_sample_csv),
            "checklist_md": str(args.checklist_md),
        },
        "counts": {
            "combined_rows": len(combined_rows),
            "unique_seen": len(seen),
            "m_positive_pool_count": len(m_keys),
            "candidate_b_rows": len(candidates),
            "need_full_diff_rows": len(need_diff),
            "usable_real_diff_count": len(usable),
            "repo_count": len(repo_counts),
        },
        "repo_count": len(repo_counts),
        "usable_repo_counts": dict(repo_counts.most_common()),
        "diff_source": dict(source_counts),
        "diff_source_counts": dict(source_counts),
        "blocklist_overlap": {
            "count": len(blocklist_rows),
            "repos": sorted({row["repo"] for row in blocklist_rows}),
            "policy": "excluded unless --allow-blocklist is set; allowed rows are marked pilot_only=1",
        },
        "skipped_counts": dict(skipped_counts),
        "evidence_files_scanned": [str(path) for path in evidence_files],
        "validation_rules": {
            "label": "Every usable row must have llm_label == B.",
            "git_diff": "Every usable row must contain 'diff --git ' and must not be a fallback/truncated placeholder.",
            "dedupe": "Usable rows are unique by (repo, sha).",
            "m_overlap": "Usable rows exclude all (repo, sha) from the M positive pool.",
            "exclusions": "Merge/revert/release/vendor/generated/format-only/lockfile-only/small cases are excluded by rule-based filters.",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_checklist(args.checklist_md, manifest)
    return manifest


def balanced_review_sample(rows: list[dict[str, str]], size: int) -> list[dict[str, str]]:
    if size <= 0:
        return []
    sample: list[dict[str, str]] = []
    per_repo: Counter[str] = Counter()
    for row in rows:
        if per_repo[row["repo"]] >= 2:
            continue
        out = {field: row.get(field, "") for field in OUTPUT_FIELDS if field != "git_diff"}
        diff = row.get("git_diff", "")
        out["git_diff_excerpt"] = diff[:2000]
        sample.append(out)
        per_repo[row["repo"]] += 1
        if len(sample) >= size:
            break
    return sample


def write_checklist(path: Path, manifest: dict[str, object]) -> None:
    counts = manifest.get("counts", {})
    block = manifest.get("blocklist_overlap", {})
    lines = [
        "# Hard B Mining Checklist",
        "",
        "- [x] Output directory is `hard_b_mining_pilot/`.",
        "- [x] M positive files were used read-only for `(repo, sha)` exclusion.",
        "- [x] Final usable rows require `llm_label == B`.",
        "- [x] Final usable rows require real `git_diff` containing `diff --git`.",
        "- [x] Final usable rows are deduplicated by `(repo, sha)`.",
        "- [x] Final usable rows exclude `(repo, sha)` already present in the strict M pool.",
        "- [x] Merge/revert/release/vendor/generated/format-only/lockfile-only/small cases are filtered.",
        f"- [x] Usable hard B count: {counts.get('usable_real_diff_count', 0)}.",
        f"- [x] Usable repo count: {counts.get('repo_count', 0)}.",
        f"- [x] Blocklist overlap count: {block.get('count', 0)}.",
        "",
        "Notes:",
        "- `hard_b_need_full_diff.csv` is ranked for additional recovery if a larger pool is needed.",
        "- Rows from blocklisted repos are excluded by default; if included in a future pilot run, mark `pilot_only=1`.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build hard-B Step3 negative pool.")
    parser.add_argument("--combined-csv", type=Path, default=Path("m_mining_gitlog_pilot/labels/gitlog_all_pilot_labels_combined.csv"))
    parser.add_argument("--labels-dir", type=Path, default=Path("m_mining_gitlog_pilot/labels"))
    parser.add_argument("--raw-dir", type=Path, default=Path("m_mining_gitlog_pilot/raw"))
    parser.add_argument("--m-csv", type=Path, default=Path("m_mining_gitlog_pilot/labels/usable_m_with_real_diff.csv"))
    parser.add_argument("--blocklist", type=Path, default=Path("m_mining_feasibility/used_repo_blocklist.txt"))
    parser.add_argument("--out-dir", type=Path, default=Path("hard_b_mining_pilot"))
    parser.add_argument("--recovery-csv", type=Path, default=Path("hard_b_mining_pilot/hard_b_full_diff_recovery_batch.csv"))
    parser.add_argument("--extra-csv", type=Path, action="append", default=[])
    parser.add_argument("--diff-max-chars", type=int, default=0)
    parser.add_argument("--max-need-diff", type=int, default=240)
    parser.add_argument("--review-sample-size", type=int, default=40)
    parser.add_argument("--allow-blocklist", action="store_true")
    parser.add_argument("--candidates-csv", type=Path, default=None)
    parser.add_argument("--need-diff-csv", type=Path, default=None)
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--output-jsonl", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--review-sample-csv", type=Path, default=None)
    parser.add_argument("--checklist-md", type=Path, default=None)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.candidates_csv = args.candidates_csv or (args.out_dir / "hard_b_candidates_labeled.csv")
    args.need_diff_csv = args.need_diff_csv or (args.out_dir / "hard_b_need_full_diff.csv")
    args.output_csv = args.output_csv or (args.out_dir / "usable_hard_b_with_real_diff.csv")
    args.output_jsonl = args.output_jsonl or (args.out_dir / "usable_hard_b_with_real_diff.jsonl")
    args.manifest = args.manifest or (args.out_dir / "usable_hard_b_with_real_diff_manifest.json")
    args.review_sample_csv = args.review_sample_csv or (args.out_dir / "hard_b_review_sample.csv")
    args.checklist_md = args.checklist_md or (args.out_dir / "hard_b_checklist.md")
    return args


def main() -> None:
    manifest = build(parse_args())
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
