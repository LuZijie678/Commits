#!/usr/bin/env python3
"""Export Step1 source rows into the Step2 source CSV schema.

Supported Step1 inputs:
1. Legacy `enriched/resolved_candidates.csv`
2. New `conservative_atomic_sources.csv`

Output:
    repo, sha, type, subject, message, git_diff, manual_label
plus optional conservative metadata columns when available.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_OUTPUT_FIELDS = ["repo", "sha", "type", "subject", "message", "git_diff", "manual_label"]
OPTIONAL_OUTPUT_FIELDS = [
    "source_confidence",
    "selection_strategy",
    "selection_reason",
    "conservative_tier",
    "model_tier",
    "model_prob",
    "tau_a",
    "tau_b",
    "rule_label",
    "rule_weight",
    "passed_rule_refilter",
    "commit_url",
]
DEFAULT_TYPES = {"fix", "feat", "refactor", "test", "perf"}
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
LEGACY_INPUT_FORMAT = "resolved_candidates"
CONSERVATIVE_INPUT_FORMAT = "conservative_atomic_sources"

try:
    csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)
except OverflowError:
    csv.field_size_limit(sys.maxsize)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Step1 source CSV to Step2 source CSV. New conservative format is preferred."
    )
    parser.add_argument(
        "--input",
        default="../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
        help="Path to Step1 conservative_atomic_sources.csv or legacy resolved_candidates.csv.",
    )
    parser.add_argument(
        "--output",
        default="../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv",
        help="Output Step2 source CSV path.",
    )
    parser.add_argument(
        "--manifest",
        default="../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json",
        help="Output Step2 source manifest JSON path.",
    )
    parser.add_argument(
        "--manual-label",
        default="A",
        choices=["A"],
        help="Step2 currently accepts only A-tier source commits.",
    )
    parser.add_argument(
        "--tier-field",
        default="tier",
        help="Legacy Step1 field used as the A-tier label source.",
    )
    parser.add_argument(
        "--required-tier",
        default="A",
        help="Required legacy tier value in the Step1 tier field.",
    )
    parser.add_argument(
        "--conservative-tier-field",
        default="conservative_tier",
        help="New Step1 field used as the conservative Tier-A label source.",
    )
    parser.add_argument(
        "--required-conservative-tier",
        default="A",
        help="Required conservative tier value for new Step1 source pool.",
    )
    parser.add_argument(
        "--min-diff-chars",
        type=int,
        default=20,
        help="Minimum non-whitespace git_diff length.",
    )
    parser.add_argument(
        "--allow-types",
        default=",".join(sorted(DEFAULT_TYPES)),
        help="Comma-separated commit types to keep. Empty means keep all types.",
    )
    parser.add_argument(
        "--allow-any-resolved-status",
        action="store_true",
        help="Do not require resolution_status to start with 'resolved' for legacy inputs.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap after filtering; 0 means no cap.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_header_key(raw_key: str) -> str:
    return (raw_key or "").replace("\ufeff", "").strip().strip('"').strip()


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_fields = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            rows.append({normalize_header_key(str(key or "")): value for key, value in row.items()})
        return rows, [normalize_header_key(field) for field in raw_fields]


def first_nonempty(row: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def subject_from_message(message: str) -> str:
    for line in str(message or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def normalize_repo(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    value = value.strip("/")
    parts = value.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return value


def is_lfs_pointer(text: str) -> bool:
    return str(text or "").lstrip().startswith("version https://git-lfs.github.com/spec")


def detect_input_format(input_fields: list[str]) -> str:
    field_set = set(input_fields)
    if "conservative_tier" in field_set:
        return CONSERVATIVE_INPUT_FORMAT
    return LEGACY_INPUT_FORMAT


def make_output_row(
    *,
    row: dict[str, str],
    repo: str,
    sha: str,
    commit_type: str,
    subject: str,
    message: str,
    git_diff: str,
    manual_label: str,
) -> dict[str, str]:
    output = {
        "repo": repo,
        "sha": sha,
        "type": commit_type,
        "subject": subject,
        "message": message,
        "git_diff": git_diff,
        "manual_label": manual_label,
    }
    for key in OPTIONAL_OUTPUT_FIELDS:
        value = str(row.get(key, "") or "").strip()
        output[key] = value
    return output


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)

    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")

    allowed_types = {item.strip() for item in str(args.allow_types).split(",") if item.strip()}
    rows, input_fields = load_rows(input_path)
    input_format = detect_input_format(input_fields)

    kept: list[dict[str, str]] = []
    reject_reasons: Counter[str] = Counter()
    seen_shas: set[str] = set()

    for row in rows:
        sha = first_nonempty(row, ["sha"])
        repo = normalize_repo(first_nonempty(row, ["resolved_repo", "repo"]))
        commit_type = first_nonempty(row, ["type"])
        message = first_nonempty(row, ["commit_message", "message"])
        subject = first_nonempty(row, ["subject"])
        if not subject:
            subject = subject_from_message(message)
        git_diff = str(row.get("git_diff", "") or "").strip()
        resolution_status = first_nonempty(row, ["resolution_status"])
        diff_error = first_nonempty(row, ["diff_error"])

        if input_format == CONSERVATIVE_INPUT_FORMAT:
            tier = first_nonempty(row, [args.conservative_tier_field])
            if tier != args.required_conservative_tier:
                reject_reasons["not_required_conservative_tier"] += 1
                continue
        else:
            tier = first_nonempty(row, [args.tier_field])
            if tier != args.required_tier:
                reject_reasons["not_required_tier"] += 1
                continue
            if resolution_status and not args.allow_any_resolved_status and not resolution_status.startswith("resolved"):
                reject_reasons["unresolved_status"] += 1
                continue

        if allowed_types and commit_type not in allowed_types:
            reject_reasons["type_not_allowed"] += 1
            continue
        if not sha:
            reject_reasons["missing_sha"] += 1
            continue
        if sha in seen_shas:
            reject_reasons["duplicate_sha"] += 1
            continue
        if not repo or "/" not in repo:
            reject_reasons["missing_or_invalid_repo"] += 1
            continue
        if not subject:
            reject_reasons["missing_subject"] += 1
            continue
        if not message:
            reject_reasons["missing_message"] += 1
            continue
        if not git_diff or len(git_diff) < int(args.min_diff_chars):
            reject_reasons["missing_or_short_diff"] += 1
            continue
        if is_lfs_pointer(git_diff):
            reject_reasons["git_diff_lfs_pointer"] += 1
            continue
        if diff_error and not git_diff:
            reject_reasons["diff_error_without_diff"] += 1
            continue

        kept.append(
            make_output_row(
                row=row,
                repo=repo,
                sha=sha,
                commit_type=commit_type,
                subject=subject,
                message=message,
                git_diff=git_diff,
                manual_label=args.manual_label,
            )
        )
        seen_shas.add(sha)
        if args.max_rows and len(kept) >= int(args.max_rows):
            break

    if not kept:
        raise SystemExit("no rows kept; check tier field, diff availability, and input path")

    output_fields = list(REQUIRED_OUTPUT_FIELDS) + list(OPTIONAL_OUTPUT_FIELDS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in output_fields} for row in kept])

    output_sha256 = sha256_file(output_path)
    type_distribution = dict(sorted(Counter(row["type"] for row in kept).items()))
    repo_count = len({row["repo"] for row in kept})

    input_path_key = (
        "step1_conservative_atomic_sources_csv"
        if input_format == CONSERVATIVE_INPUT_FORMAT
        else "step1_resolved_candidates_csv"
    )
    sampling_source = (
        "step1_conservative_atomic_sources"
        if input_format == CONSERVATIVE_INPUT_FORMAT
        else "step1_enriched_resolved_candidates"
    )

    manifest = {
        "total_selected": len(kept),
        "sampling_plan": [
            {
                "source": sampling_source,
                "pool": len(rows),
                "selected": len(kept),
                "required_tier": args.required_conservative_tier
                if input_format == CONSERVATIVE_INPUT_FORMAT
                else args.required_tier,
                "allowed_types": sorted(allowed_types),
            }
        ],
        "label_schema": {
            "A": "Step1 high-confidence single-intent source commit for Step2 construction"
        },
        "paths": {
            "csv": output_path.as_posix(),
            input_path_key: input_path.as_posix(),
        },
        "export": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "tool": "tools/export_step1_to_step2_source.py",
            "input_format": input_format,
            "input_sha256": sha256_file(input_path),
            "input_fields": input_fields,
            "input_rows": len(rows),
            "output_sha256": output_sha256,
            "output_fields": output_fields,
            "output_rows": len(kept),
            "manual_label": args.manual_label,
            "tier_field": args.tier_field,
            "required_tier": args.required_tier,
            "conservative_tier_field": args.conservative_tier_field,
            "required_conservative_tier": args.required_conservative_tier,
            "allowed_types": sorted(allowed_types),
            "filters": {
                "min_diff_chars": int(args.min_diff_chars),
                "require_resolution_status_prefix_resolved": not bool(args.allow_any_resolved_status),
                "max_rows": int(args.max_rows),
            },
            "reject_reasons": dict(sorted(reject_reasons.items())),
            "type_distribution": type_distribution,
            "repo_count": repo_count,
            "sha_unique_count": len({row["sha"] for row in kept}),
            "optional_output_fields_present": [field for field in OPTIONAL_OUTPUT_FIELDS if any(row.get(field, "") for row in kept)],
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"input_rows={len(rows)}")
    print(f"output_rows={len(kept)}")
    print(output_path.as_posix())
    print(manifest_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
