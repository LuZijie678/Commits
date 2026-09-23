#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CSV_FIELD_LIMIT = 10**9
csv.field_size_limit(CSV_FIELD_LIMIT)

SCRIPT_PATH = Path(__file__).resolve()
STEP2_CODE_DIR = SCRIPT_PATH.parent
STEP2_ROOT = STEP2_CODE_DIR.parent
REPO_ROOT = SCRIPT_PATH.parents[3]

DEFAULT_M_SOURCE_CSV = REPO_ROOT / "datasets" / "m_verified" / "canonical" / "usable_m_with_real_diff.csv"
DEFAULT_STEP2_SOURCE_CSV = REPO_ROOT / "datasets" / "derived" / "step2_bridge" / "current" / "step2_source_candidates_from_step1.csv"
DEFAULT_CANDIDATE_CSV = REPO_ROOT / "datasets" / "step2" / "candidate_sources" / "m_only_disjoint_candidates.csv"
DEFAULT_CANDIDATE_REPORT_JSON = REPO_ROOT / "datasets" / "step2" / "candidate_sources" / "m_only_disjoint_candidates_report.json"
DEFAULT_CANDIDATE_REPORT_MD = REPO_ROOT / "datasets" / "step2" / "candidate_sources" / "m_only_disjoint_candidates_report.md"
DEFAULT_REVIEW_SHEET_CSV = REPO_ROOT / "datasets" / "step2" / "review" / "m_only_review_sheet.csv"
DEFAULT_DELIVERY_DIR = REPO_ROOT / "datasets" / "step2" / "delivery" / "current"
DEFAULT_DB_FILENAME = "fewshot_pool.db"
DEFAULT_BUILD_MANIFEST_FILENAME = "build_manifest.json"
DEFAULT_AUDIT_FILENAME = "fewshot_audit.json"
DEFAULT_SELECTION_SUMMARY_FILENAME = "selection_summary.json"
DEFAULT_SELECTION_SUMMARY_MD_FILENAME = "selection_summary.md"
DEFAULT_DELIVERY_README_FILENAME = "README.md"
DEFAULT_PREFLIGHT_FILENAME = "preflight_report.json"
DEFAULT_PREFLIGHT_CONFIG = STEP2_ROOT / "configs" / "step2_runtime_config.json"

CONSTRUCT_MODULE_PATH = STEP2_CODE_DIR / "construct_simple_two_intent.py"
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", CONSTRUCT_MODULE_PATH)
CONSTRUCT = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CONSTRUCT)
PREFERRED_SIGNATURE_ALIASES = {
    CONSTRUCT.canonical_type_signature(CONSTRUCT.signature_types(signature)): signature
    for signature in CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES
}


REVIEW_REQUIRED_COLUMNS = [
    "review_decision",
    "verified_multi_intent",
    "type_signature_canonical",
    "intent_k",
    "subject_normalized",
    "fewshot_eligible",
    "quality_status",
    "message_status",
]


def safe_strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_int_or_none(value: Any) -> int | None:
    text = safe_strip(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"true", "yes", "y"}:
        return 1
    if lowered in {"false", "no", "n"}:
        return 0
    try:
        return int(float(text))
    except Exception:
        return None


def utc_now() -> str:
    return CONSTRUCT.dt.datetime.now(CONSTRUCT.dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable_rank(*parts: str) -> int:
    payload = "||".join(safe_strip(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def repo_rel(path: Path | str) -> str:
    text = safe_strip(path)
    if not text:
        return ""
    path_obj = Path(text)
    if not path_obj.is_absolute() and not text.startswith("."):
        return path_obj.as_posix()
    try:
        return str(path_obj.resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(path_obj)


def path_rel_to(base: Path, path: Path | str) -> str:
    path_obj = Path(str(path))
    try:
        return os.path.relpath(path_obj.resolve(), base.resolve())
    except Exception:
        return str(path_obj)


def repo_abs(path: Path | str) -> Path:
    text = safe_strip(path)
    path_obj = Path(text)
    if path_obj.is_absolute():
        return path_obj
    if text.startswith("."):
        return (STEP2_ROOT / path_obj).resolve()
    return (REPO_ROOT / path_obj).resolve()


@dataclass
class CandidateStats:
    total_rows: int
    strict_repo_sha_disjoint_rows: int
    repo_overlap_rows: int
    sha_overlap_rows: int
    style_clean_rows: int
    style_bad_rows: int
    source_repo_count: int
    source_sha_count: int
    candidate_repo_count: int
    style_reason_counts: dict[str, int]


@dataclass
class ReviewSummary:
    total_rows: int
    pending_rows: int
    accept_rows: int
    reject_rows: int
    invalid_accept_rows: int
    eligible_accept_rows: int
    min_final_required: int
    target_final_size: int
    max_final_size: int
    common_signature_coverage_all_eligible: dict[str, int]
    blockers: list[str]
    warnings: list[str]


def default_candidate_field_order() -> list[str]:
    return [
        "candidate_source",
        "repo",
        "sha",
        "commit_url",
        "subject",
        "commit_message",
        "git_diff",
        "language",
        "commit_date",
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
        "_source_file",
        "_evidence_mode",
        "_needs_diff_verify",
        "file_count",
        "path_roles",
        "top_dirs",
        "changed_files",
        "shortstat",
        "diff_status",
        "diff_error",
        "diff_source",
        "diff_char_count_original",
        "diff_truncated",
        "style_clean",
        "style_reasons",
        "style_char_count",
        "style_token_count",
        "sha_overlaps_step2_source",
        "repo_overlaps_step2_source",
        "strict_repo_sha_disjoint",
    ]


def default_review_field_order() -> list[str]:
    return [
        "review_decision",
        "verified_multi_intent",
        "type_signature_canonical",
        "type_signature_raw",
        "intent_k",
        "subject_normalized",
        "fewshot_eligible",
        "quality_status",
        "quality_score",
        "message_status",
        "reviewer",
        "review_round",
        "review_notes",
        "subject_original",
        "subject_normalized_suggested",
        "intent_k_suggested",
        "needs_subject_normalization",
        "style_clean",
        "style_reasons",
        "strict_repo_sha_disjoint",
        "sha_overlaps_step2_source",
        "repo_overlaps_step2_source",
        "repo",
        "sha",
        "commit_url",
        "subject",
        "commit_message",
        "git_diff",
        "language",
        "commit_date",
        "file_count",
        "path_roles",
        "top_dirs",
        "changed_files",
        "shortstat",
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
        "_source_file",
        "_evidence_mode",
        "_needs_diff_verify",
        "diff_status",
        "diff_error",
        "diff_source",
        "diff_char_count_original",
        "diff_truncated",
    ]


def render_candidate_report_md(stats: CandidateStats, input_csv: Path, step2_source_csv: Path, candidate_csv: Path, review_sheet_csv: Path) -> str:
    style_lines = [f"- `{reason}`: `{count}`" for reason, count in sorted(stats.style_reason_counts.items(), key=lambda item: (-item[1], item[0]))]
    if not style_lines:
        style_lines = ["- 无"]
    return "\n".join(
        [
            "# M-only Few-shot Candidate Preparation Report",
            "",
            "## Inputs",
            f"- source_csv: `{input_csv}`",
            f"- step2_source_csv: `{step2_source_csv}`",
            f"- candidate_csv: `{candidate_csv}`",
            f"- review_sheet_csv: `{review_sheet_csv}`",
            "",
            "## Summary",
            f"- total_rows: `{stats.total_rows}`",
            f"- strict_repo_sha_disjoint_rows: `{stats.strict_repo_sha_disjoint_rows}`",
            f"- repo_overlap_rows: `{stats.repo_overlap_rows}`",
            f"- sha_overlap_rows: `{stats.sha_overlap_rows}`",
            f"- style_clean_rows: `{stats.style_clean_rows}`",
            f"- style_bad_rows: `{stats.style_bad_rows}`",
            f"- candidate_repo_count: `{stats.candidate_repo_count}`",
            f"- step2_source_repo_count: `{stats.source_repo_count}`",
            f"- step2_source_sha_count: `{stats.source_sha_count}`",
            "",
            "## Style Reasons",
            *style_lines,
            "",
            "## Notes",
            "- 当前候选源仅来自 canonical M 数据。",
            "- review sheet 只预填严格 repo+sha 不泄露的候选。",
            "- type_signature_canonical / intent_k / subject_normalized 仍需人工复核，不在 prepare 阶段自动伪造。",
        ]
    ) + "\n"


def normalize_type_signature(raw_value: str) -> str:
    text = safe_strip(raw_value)
    if not text:
        return ""
    types = CONSTRUCT.signature_types(text)
    canonical = CONSTRUCT.canonical_type_signature(types)
    return safe_strip(PREFERRED_SIGNATURE_ALIASES.get(canonical, canonical))


def build_example_id(repo: str, sha: str) -> str:
    repo_key = repo.replace("/", "__")
    return f"mfs__{repo_key}__{sha}"


def build_candidate_rows(source_rows: list[dict[str, str]], step2_source_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], CandidateStats]:
    source_shas = {safe_strip(row.get("sha")) for row in step2_source_rows if safe_strip(row.get("sha"))}
    source_repos = {safe_strip(row.get("repo")) for row in step2_source_rows if safe_strip(row.get("repo"))}
    style_reason_counter: Counter[str] = Counter()
    candidate_rows: list[dict[str, Any]] = []
    strict_count = 0
    repo_overlap_rows = 0
    sha_overlap_rows = 0
    style_clean_rows = 0
    style_bad_rows = 0
    repos_seen: set[str] = set()

    for row in source_rows:
        repo = safe_strip(row.get("repo"))
        sha = safe_strip(row.get("sha"))
        subject = safe_strip(row.get("subject"))
        style = CONSTRUCT.analyze_fewshot_subject_style(subject)
        style_reasons = list(style.get("reasons", []))
        if style.get("clean", False):
            style_clean_rows += 1
        else:
            style_bad_rows += 1
            style_reason_counter.update(style_reasons)
        sha_overlap = int(sha in source_shas)
        repo_overlap = int(repo in source_repos)
        strict_disjoint = int((not sha_overlap) and (not repo_overlap))
        if sha_overlap:
            sha_overlap_rows += 1
        if repo_overlap:
            repo_overlap_rows += 1
        if strict_disjoint:
            strict_count += 1
        repos_seen.add(repo)
        candidate_rows.append(
            {
                "candidate_source": "canonical_m_only",
                **row,
                "commit_message": safe_strip(row.get("commit_message")),
                "style_clean": int(bool(style.get("clean", False))),
                "style_reasons": json_dumps(style_reasons),
                "style_char_count": int(style.get("char_count", 0)),
                "style_token_count": int(style.get("token_count", 0)),
                "sha_overlaps_step2_source": sha_overlap,
                "repo_overlaps_step2_source": repo_overlap,
                "strict_repo_sha_disjoint": strict_disjoint,
            }
        )

    stats = CandidateStats(
        total_rows=len(candidate_rows),
        strict_repo_sha_disjoint_rows=strict_count,
        repo_overlap_rows=repo_overlap_rows,
        sha_overlap_rows=sha_overlap_rows,
        style_clean_rows=style_clean_rows,
        style_bad_rows=style_bad_rows,
        source_repo_count=len(source_repos),
        source_sha_count=len(source_shas),
        candidate_repo_count=len(repos_seen),
        style_reason_counts=dict(style_reason_counter),
    )
    return candidate_rows, stats


def build_review_sheet_rows(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_rows: list[dict[str, Any]] = []
    for row in candidate_rows:
        if int(row.get("strict_repo_sha_disjoint", 0)) != 1:
            continue
        review_rows.append(
            {
                "review_decision": "pending",
                "verified_multi_intent": 1,
                "type_signature_canonical": "",
                "type_signature_raw": "",
                "intent_k": "",
                "subject_normalized": "",
                "fewshot_eligible": "",
                "quality_status": "",
                "quality_score": "",
                "message_status": "",
                "reviewer": "",
                "review_round": "",
                "review_notes": "",
                "subject_original": safe_strip(row.get("subject")),
                "subject_normalized_suggested": safe_strip(row.get("subject")) if int(row.get("style_clean", 0)) == 1 else "",
                "intent_k_suggested": safe_strip(row.get("llm_intent_count_estimate")),
                "needs_subject_normalization": 0 if int(row.get("style_clean", 0)) == 1 else 1,
                **row,
            }
        )
    return review_rows


def prepare_candidates(args: argparse.Namespace) -> None:
    source_rows = read_csv_rows(args.input_csv)
    step2_source_rows = read_csv_rows(args.step2_source_csv)
    candidate_rows, stats = build_candidate_rows(source_rows, step2_source_rows)
    review_rows = build_review_sheet_rows(candidate_rows)

    write_csv_rows(args.candidate_csv, default_candidate_field_order(), candidate_rows)
    write_csv_rows(args.review_sheet_csv, default_review_field_order(), review_rows)

    report_payload = {
        "generated_at_utc": utc_now(),
        "source_policy": "m_only_canonical",
        "input_csv": repo_rel(args.input_csv),
        "input_csv_sha256": compute_sha256(args.input_csv),
        "step2_source_csv": repo_rel(args.step2_source_csv),
        "step2_source_csv_sha256": compute_sha256(args.step2_source_csv),
        "candidate_csv": repo_rel(args.candidate_csv),
        "review_sheet_csv": repo_rel(args.review_sheet_csv),
        "stats": {
            "total_rows": stats.total_rows,
            "strict_repo_sha_disjoint_rows": stats.strict_repo_sha_disjoint_rows,
            "repo_overlap_rows": stats.repo_overlap_rows,
            "sha_overlap_rows": stats.sha_overlap_rows,
            "style_clean_rows": stats.style_clean_rows,
            "style_bad_rows": stats.style_bad_rows,
            "candidate_repo_count": stats.candidate_repo_count,
            "step2_source_repo_count": stats.source_repo_count,
            "step2_source_sha_count": stats.source_sha_count,
            "style_reason_counts": stats.style_reason_counts,
        },
        "notes": [
            "review sheet 仅包含 strict_repo_sha_disjoint=1 的候选。",
            "type_signature_canonical / intent_k / subject_normalized 需人工复核后填写。",
        ],
    }
    write_json(args.report_json, report_payload)
    write_text(
        args.report_md,
        render_candidate_report_md(stats, args.input_csv, args.step2_source_csv, args.candidate_csv, args.review_sheet_csv),
    )
    print(f"candidate_csv={repo_rel(args.candidate_csv)}")
    print(f"review_sheet_csv={repo_rel(args.review_sheet_csv)}")
    print(f"strict_repo_sha_disjoint_rows={stats.strict_repo_sha_disjoint_rows}")


def parse_review_decision(value: Any) -> str:
    text = safe_strip(value).lower()
    if text in {"", "pending", "review", "todo"}:
        return "pending"
    if text in {"accept", "accepted", "keep", "yes", "y", "1"}:
        return "accept"
    if text in {"reject", "rejected", "drop", "no", "n", "0"}:
        return "reject"
    return text


def canonical_review_row(row: dict[str, str]) -> dict[str, Any]:
    review_decision = parse_review_decision(row.get("review_decision"))
    verified_multi_intent = to_int_or_none(row.get("verified_multi_intent"))
    fewshot_eligible = to_int_or_none(row.get("fewshot_eligible"))
    strict_repo_sha_disjoint = to_int_or_none(row.get("strict_repo_sha_disjoint"))
    subject_normalized = safe_strip(row.get("subject_normalized"))
    subject_original = safe_strip(row.get("subject_original") or row.get("subject"))
    type_signature_canonical = normalize_type_signature(row.get("type_signature_canonical", ""))
    type_signature_raw = safe_strip(row.get("type_signature_raw")) or type_signature_canonical
    style = CONSTRUCT.analyze_fewshot_subject_style(subject_normalized)
    repo = safe_strip(row.get("repo"))
    sha = safe_strip(row.get("sha"))
    quality_score_text = safe_strip(row.get("quality_score"))
    try:
        quality_score = float(quality_score_text) if quality_score_text else 1.0
    except Exception:
        quality_score = 1.0
    intent_k = to_int_or_none(row.get("intent_k"))
    quality_status = safe_strip(row.get("quality_status")).lower()
    message_status = safe_strip(row.get("message_status")).lower()

    validation_errors: list[str] = []
    if review_decision == "accept":
        if strict_repo_sha_disjoint != 1:
            validation_errors.append("accept_requires_strict_repo_sha_disjoint")
        if verified_multi_intent != 1:
            validation_errors.append("accept_requires_verified_multi_intent_1")
        if fewshot_eligible != 1:
            validation_errors.append("accept_requires_fewshot_eligible_1")
        if not repo or not sha:
            validation_errors.append("accept_requires_repo_sha")
        if not type_signature_canonical:
            validation_errors.append("accept_requires_type_signature_canonical")
        if intent_k is None or intent_k < 2:
            validation_errors.append("accept_requires_intent_k_gte_2")
        if not subject_normalized:
            validation_errors.append("accept_requires_subject_normalized")
        if quality_status != "pass":
            validation_errors.append("accept_requires_quality_status_pass")
        if message_status != "pass":
            validation_errors.append("accept_requires_message_status_pass")
        if not bool(style.get("clean", False)):
            validation_errors.append("accept_requires_style_clean_subject")

    return {
        **row,
        "review_decision_normalized": review_decision,
        "verified_multi_intent_normalized": verified_multi_intent,
        "fewshot_eligible_normalized": fewshot_eligible,
        "strict_repo_sha_disjoint_normalized": strict_repo_sha_disjoint,
        "type_signature_canonical_normalized": type_signature_canonical,
        "type_signature_raw_normalized": type_signature_raw,
        "intent_k_normalized": intent_k,
        "subject_normalized_clean": int(bool(style.get("clean", False))),
        "subject_normalized_reasons": list(style.get("reasons", [])),
        "subject_normalized_char_count": int(style.get("char_count", 0)),
        "subject_normalized_token_count": int(style.get("token_count", 0)),
        "quality_status_normalized": quality_status,
        "message_status_normalized": message_status,
        "repo_normalized": repo,
        "sha_normalized": sha,
        "subject_original_normalized": subject_original,
        "subject_normalized_final": subject_normalized,
        "quality_score_normalized": quality_score,
        "validation_errors": validation_errors,
    }


def summarize_review_sheet(
    review_rows: list[dict[str, str]],
    *,
    min_final_size: int,
    target_final_size: int,
    max_final_size: int,
    min_per_common_signature: int,
) -> tuple[list[dict[str, Any]], ReviewSummary]:
    normalized_rows = [canonical_review_row(row) for row in review_rows]
    pending_rows = sum(1 for row in normalized_rows if row["review_decision_normalized"] == "pending")
    accept_rows = [row for row in normalized_rows if row["review_decision_normalized"] == "accept"]
    reject_rows = sum(1 for row in normalized_rows if row["review_decision_normalized"] == "reject")
    invalid_accept_rows = [row for row in accept_rows if row["validation_errors"]]
    eligible_accept_rows = [row for row in accept_rows if not row["validation_errors"]]
    coverage_counter = Counter(
        row["type_signature_canonical_normalized"]
        for row in eligible_accept_rows
        if row["type_signature_canonical_normalized"]
    )
    common_coverage = {
        signature: int(coverage_counter.get(signature, 0))
        for signature in CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES
    }
    blockers: list[str] = []
    warnings: list[str] = []
    if len(eligible_accept_rows) < min_final_size:
        blockers.append(
            f"accepted_rows_below_min_final(total={len(eligible_accept_rows)}, min_required={min_final_size})"
        )
    insufficient = [
        signature for signature, count in common_coverage.items() if count < min_per_common_signature
    ]
    if insufficient:
        blockers.append(
            "fewshot_common_signature_coverage_insufficient("
            f"min_per_signature={min_per_common_signature}, signatures={insufficient})"
        )
    if invalid_accept_rows:
        blockers.append(f"invalid_accept_rows(count={len(invalid_accept_rows)})")
    if pending_rows:
        warnings.append(f"pending_review_rows(count={pending_rows})")
    if len(eligible_accept_rows) > max_final_size:
        warnings.append(
            f"eligible_accept_rows_above_max_final(total={len(eligible_accept_rows)}, max_allowed={max_final_size})"
        )
    summary = ReviewSummary(
        total_rows=len(normalized_rows),
        pending_rows=pending_rows,
        accept_rows=len(accept_rows),
        reject_rows=reject_rows,
        invalid_accept_rows=len(invalid_accept_rows),
        eligible_accept_rows=len(eligible_accept_rows),
        min_final_required=min_final_size,
        target_final_size=target_final_size,
        max_final_size=max_final_size,
        common_signature_coverage_all_eligible=common_coverage,
        blockers=blockers,
        warnings=warnings,
    )
    return normalized_rows, summary


def render_review_summary_md(summary_payload: dict[str, Any]) -> str:
    common_lines = [
        f"- `{sig}`: `{count}`"
        for sig, count in sorted((summary_payload.get("common_signature_coverage_all_eligible") or {}).items())
    ]
    if not common_lines:
        common_lines = ["- 无"]
    blockers = summary_payload.get("blockers", []) or ["无"]
    warnings = summary_payload.get("warnings", []) or ["无"]
    return "\n".join(
        [
            "# Few-shot Review Summary",
            "",
            "## Counts",
            f"- total_rows: `{summary_payload.get('total_rows', 0)}`",
            f"- pending_rows: `{summary_payload.get('pending_rows', 0)}`",
            f"- accept_rows: `{summary_payload.get('accept_rows', 0)}`",
            f"- reject_rows: `{summary_payload.get('reject_rows', 0)}`",
            f"- invalid_accept_rows: `{summary_payload.get('invalid_accept_rows', 0)}`",
            f"- eligible_accept_rows: `{summary_payload.get('eligible_accept_rows', 0)}`",
            "",
            "## Common Signature Coverage",
            *common_lines,
            "",
            "## Blockers",
            *[f"- {item}" for item in blockers],
            "",
            "## Warnings",
            *[f"- {item}" for item in warnings],
        ]
    ) + "\n"


def report_review_sheet(args: argparse.Namespace) -> None:
    review_rows = read_csv_rows(args.review_sheet_csv)
    normalized_rows, summary = summarize_review_sheet(
        review_rows,
        min_final_size=args.min_final_size,
        target_final_size=args.target_final_size,
        max_final_size=args.max_final_size,
        min_per_common_signature=args.min_per_common_signature,
    )
    invalid_accept_examples = [
        {
            "repo": row.get("repo_normalized", ""),
            "sha": row.get("sha_normalized", ""),
            "validation_errors": row.get("validation_errors", []),
        }
        for row in normalized_rows
        if row.get("review_decision_normalized") == "accept" and row.get("validation_errors")
    ][:20]
    payload = {
        "generated_at_utc": utc_now(),
        "review_sheet_csv": repo_rel(args.review_sheet_csv),
        "total_rows": summary.total_rows,
        "pending_rows": summary.pending_rows,
        "accept_rows": summary.accept_rows,
        "reject_rows": summary.reject_rows,
        "invalid_accept_rows": summary.invalid_accept_rows,
        "eligible_accept_rows": summary.eligible_accept_rows,
        "min_final_required": summary.min_final_required,
        "target_final_size": summary.target_final_size,
        "max_final_size": summary.max_final_size,
        "common_signature_coverage_all_eligible": summary.common_signature_coverage_all_eligible,
        "blockers": summary.blockers,
        "warnings": summary.warnings,
        "invalid_accept_examples": invalid_accept_examples,
    }
    if args.output_json:
        write_json(args.output_json, payload)
    if args.output_md:
        write_text(args.output_md, render_review_summary_md(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not summary.blockers else 1)


def choose_rows_for_final_pool(
    eligible_rows: list[dict[str, Any]],
    *,
    target_final_size: int,
    min_per_common_signature: int,
) -> list[dict[str, Any]]:
    by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        by_signature[row["type_signature_canonical_normalized"]].append(row)
    repo_counter: Counter[str] = Counter()
    selected_keys: set[tuple[str, str]] = set()
    selected_rows: list[dict[str, Any]] = []

    def row_priority(row: dict[str, Any], context: str) -> tuple[Any, ...]:
        repo = row["repo_normalized"]
        sha = row["sha_normalized"]
        needed_norm = int(to_int_or_none(row.get("needs_subject_normalization")) or 0)
        return (
            repo_counter[repo],
            needed_norm,
            stable_rank(context, row["type_signature_canonical_normalized"], repo, sha),
        )

    for signature in CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES:
        candidates = list(by_signature.get(signature, []))
        candidates.sort(key=lambda row: row_priority(row, f"common::{signature}"))
        picks = candidates[:min_per_common_signature]
        if len(picks) < min_per_common_signature:
            raise RuntimeError(
                "Cannot satisfy common signature coverage during final selection: "
                f"{signature} has {len(candidates)} eligible rows"
            )
        for row in picks:
            key = (row["repo_normalized"], row["sha_normalized"])
            if key in selected_keys:
                continue
            selected_keys.add(key)
            selected_rows.append(row)
            repo_counter[row["repo_normalized"]] += 1

    remaining_rows = [
        row for row in eligible_rows if (row["repo_normalized"], row["sha_normalized"]) not in selected_keys
    ]
    while len(selected_rows) < target_final_size and remaining_rows:
        remaining_rows.sort(key=lambda row: row_priority(row, "global_fill"))
        row = remaining_rows.pop(0)
        key = (row["repo_normalized"], row["sha_normalized"])
        if key in selected_keys:
            continue
        selected_keys.add(key)
        selected_rows.append(row)
        repo_counter[row["repo_normalized"]] += 1
    return selected_rows


def build_notes_payload(row: dict[str, Any]) -> str:
    payload = {
        "source_dataset": "datasets/m_verified/canonical/usable_m_with_real_diff.csv",
        "subject_original": row.get("subject_original_normalized", ""),
        "subject_normalized": row.get("subject_normalized_final", ""),
        "review_notes": safe_strip(row.get("review_notes")),
        "reviewer": safe_strip(row.get("reviewer")),
        "review_round": safe_strip(row.get("review_round")),
        "commit_url": safe_strip(row.get("commit_url")),
        "llm_reason": safe_strip(row.get("llm_reason")),
        "llm_intent_summaries": safe_strip(row.get("llm_intent_summaries")),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def write_fewshot_db(path: Path, rows: list[dict[str, Any]], table: str) -> None:
    CONSTRUCT.validate_sql_identifier(table)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(
            f"""
            CREATE TABLE {table} (
                example_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                sha TEXT NOT NULL,
                type_pair TEXT,
                type_signature_raw TEXT,
                type_signature_canonical TEXT NOT NULL,
                intent_k INTEGER NOT NULL,
                subject TEXT NOT NULL,
                split TEXT NOT NULL DEFAULT 'train',
                verified_multi_intent INTEGER NOT NULL DEFAULT 1,
                fewshot_eligible INTEGER NOT NULL DEFAULT 1,
                quality_score REAL,
                quality_status TEXT,
                message_status TEXT,
                notes TEXT
            )
            """
        )
        conn.executemany(
            f"""
            INSERT INTO {table} (
                example_id, repo, sha, type_pair, type_signature_raw,
                type_signature_canonical, intent_k, subject, split,
                verified_multi_intent, fewshot_eligible, quality_score,
                quality_status, message_status, notes
            ) VALUES (
                :example_id, :repo, :sha, :type_pair, :type_signature_raw,
                :type_signature_canonical, :intent_k, :subject, :split,
                :verified_multi_intent, :fewshot_eligible, :quality_score,
                :quality_status, :message_status, :notes
            )
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def build_audit_payload(db_path: Path, table: str, *, min_total: int, min_per_common_signature: int) -> dict[str, Any]:
    raw_rows = CONSTRUCT.load_fewshot_pool_rows(str(db_path), table)
    eligible_rows, retrieval_filter_stats = CONSTRUCT.filter_fewshot_pool_rows_for_retrieval(raw_rows)
    audit = CONSTRUCT.audit_fewshot_pool(
        raw_rows,
        min_total=min_total,
        min_per_common_signature=min_per_common_signature,
        strict_style=True,
    )
    retrieval_probe = CONSTRUCT.retrieve_fewshot_examples(
        db_path=str(db_path),
        table=table,
        type_signature_canonical="fix+test",
        current_repo="fewshot/preflight",
        k=1,
        seed=42,
        current_source_shas=set(),
    )
    retrieval_probe_ok = bool(eligible_rows) and retrieval_probe.get("retrieval_result_count", 0) >= 1
    return {
        "db_path": repo_rel(db_path),
        "table": table,
        "passed": bool(audit.get("audit_pass", False) and retrieval_probe_ok),
        "strict_style": True,
        "thresholds": {
            "min_total": int(min_total),
            "min_per_common_signature": int(min_per_common_signature),
            "probe_type_signature": "fix+test",
            "probe_k": 1,
        },
        "row_counts": {
            "raw_rows": len(raw_rows),
            "eligible_rows": len(eligible_rows),
        },
        "retrieval_filter_stats": retrieval_filter_stats,
        "retrieval_probe_ok": bool(retrieval_probe_ok),
        "retrieval_probe": retrieval_probe,
        "audit": audit,
        "common_signatures_checked": list(CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES),
        "eligibility_policy": CONSTRUCT.DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
    }


def default_preflight_stub(reason: str) -> dict[str, Any]:
    return {
        "attempted": False,
        "passed": False,
        "reason": reason,
        "report_path": "",
        "stdout": "",
        "stderr": "",
    }


def run_step2_preflight(
    *,
    preflight_config: Path,
    fewshot_db: Path,
    build_manifest_path: Path,
    delivery_dir: Path,
) -> dict[str, Any]:
    if not preflight_config.exists() or not preflight_config.is_file():
        return default_preflight_stub(f"preflight_config_missing:{preflight_config}")

    command = [
        sys.executable,
        str(path_rel_to(STEP2_ROOT, STEP2_CODE_DIR / "construct_simple_two_intent.py")),
        "--preflight",
        "--config",
        str(path_rel_to(STEP2_ROOT, preflight_config)),
        "--fewshot-db",
        str(path_rel_to(STEP2_ROOT, fewshot_db)),
        "--fewshot-build-manifest-path",
        str(path_rel_to(STEP2_ROOT, build_manifest_path)),
        "--output-dir",
        str(path_rel_to(STEP2_ROOT, delivery_dir)),
    ]
    proc = subprocess.run(command, cwd=str(STEP2_ROOT), capture_output=True, text=True)
    report_path = ""
    for line in proc.stdout.splitlines():
        text = safe_strip(line)
        if text.endswith("preflight_report.json"):
            report_path = text
    payload: dict[str, Any] = {
        "attempted": True,
        "passed": proc.returncode == 0,
        "reason": "",
        "report_path": repo_rel(report_path) if report_path else "",
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
        "command": command,
    }
    if report_path:
        report_file = repo_abs(report_path)
        if report_file.exists() and report_file.is_file():
            try:
                payload["report"] = json.loads(report_file.read_text(encoding="utf-8"))
            except Exception as exc:
                payload["reason"] = f"preflight_report_parse_error:{exc}"
        else:
            payload["reason"] = f"preflight_report_missing:{report_path}"
    elif not payload["passed"]:
        payload["reason"] = "preflight_command_failed_without_report_path"
    return payload


def build_manifest_payload(
    *,
    db_path: Path,
    input_csv: Path,
    review_sheet_csv: Path,
    selected_rows: list[dict[str, Any]],
    audit_payload: dict[str, Any],
    preflight_payload: dict[str, Any],
    min_final_size: int,
    target_final_size: int,
    max_final_size: int,
    audit_min_total: int,
    min_per_common_signature: int,
) -> dict[str, Any]:
    common_coverage = (audit_payload.get("audit", {}) or {}).get("common_signature_coverage", {}) or {}
    preflight_report_path = safe_strip(preflight_payload.get("report_path"))
    if preflight_report_path:
        preflight_report_path_obj = Path(preflight_report_path)
        if preflight_report_path_obj.is_absolute():
            try:
                preflight_report_path = str(preflight_report_path_obj.resolve().relative_to(REPO_ROOT))
            except Exception:
                preflight_report_path = safe_strip(preflight_payload.get("report_path"))
    try:
        db_path_repo_rel = str(db_path.resolve().relative_to(REPO_ROOT))
    except Exception:
        db_path_repo_rel = str(db_path)
    try:
        manifest_path_repo_rel = str((db_path.parent / DEFAULT_BUILD_MANIFEST_FILENAME).resolve().relative_to(REPO_ROOT))
    except Exception:
        manifest_path_repo_rel = str(db_path.parent / DEFAULT_BUILD_MANIFEST_FILENAME)
    return {
        "asset_name": "fewshot_pool_formal_m_only",
        "asset_version": "v1",
        "build_date_utc": utc_now(),
        "builder": "codex",
        "db_filename": db_path.name,
        "schema_table": "fewshot_examples",
        "source_datasets": [
            {
                "name": "canonical_m_only",
                "path": repo_rel(input_csv),
                "sha256": compute_sha256(input_csv),
                "rows_in": len(read_csv_rows(input_csv)),
                "rows_selected": len(selected_rows),
                "selection_rule": "review_decision=accept and verified_multi_intent=1 and fewshot_eligible=1 and quality_status=pass and message_status=pass and strict_repo_sha_disjoint=1",
            },
            {
                "name": "manual_review_sheet",
                "path": repo_rel(review_sheet_csv),
                "sha256": compute_sha256(review_sheet_csv),
                "rows_in": len(read_csv_rows(review_sheet_csv)),
                "rows_selected": len(selected_rows),
                "selection_rule": "final reviewed pool source of truth",
            },
        ],
        "source_policy": "m_only",
        "subject_policy": "manual_normalized_with_traceability",
        "leakage_policy": {
            "sha_disjoint_from_step2_source": True,
            "repo_disjoint_from_step2_source": True,
            "sha_disjoint_from_step3_eval_test": False,
            "repo_disjoint_from_step3_eval_test_if_required": False,
            "notes": "step3_eval_leakage_status=pending_missing_frozen_eval_assets",
        },
        "target_size": {
            "target_final_size": int(target_final_size),
            "accepted_size_range": [int(min_final_size), int(max_final_size)],
            "final_selected_count": len(selected_rows),
        },
        "total_rows_train": len(selected_rows),
        "eligible_rows_train": len(selected_rows),
        "verified_rows_train": len(selected_rows),
        "common_signature_coverage": common_coverage,
        "style_cleaning_policy": {
            "strict_style": True,
            "max_subject_chars": int(CONSTRUCT.DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_CHARS),
            "max_subject_tokens": int(CONSTRUCT.DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_TOKENS),
            "blocked_reasons": [
                "double_prefix",
                "label_template",
                "bullet_list",
                "numbered_list",
                "mechanical_semicolon",
                "overlong_subject",
                "generic_subject",
            ],
        },
        "thresholds": {
            "min_total": int(audit_min_total),
            "min_per_common_signature": int(min_per_common_signature),
            "probe_type_signature": "fix+test",
            "probe_k": 1,
        },
        "validation": {
            "audit_command": f"python3 code/step2/code/audit_fewshot_pool.py --db {db_path_repo_rel} --json",
            "audit_pass": bool((audit_payload.get("audit", {}) or {}).get("audit_pass", False)),
            "retrieval_probe_ok": bool(audit_payload.get("retrieval_probe_ok", False)),
            "preflight_command": (
                "python3 code/step2/code/construct_simple_two_intent.py --preflight "
                "--config code/step2/configs/step2_runtime_config.json "
                f"--fewshot-db {db_path_repo_rel} "
                f"--fewshot-build-manifest-path {manifest_path_repo_rel}"
            ),
            "preflight_passed": bool(preflight_payload.get("passed", False)),
            "preflight_report_path": preflight_report_path,
        },
        "build_inputs": {
            "generator_script": "code/step2/code/build_formal_fewshot_pool.py",
            "audit_script": "code/step2/code/audit_fewshot_pool.py",
            "protocol_doc": "code/step2/docs/plan-1-step2-experiment-protocol.md",
            "review_sheet_csv": repo_rel(review_sheet_csv),
        },
        "step3_target": {
            "purpose": "Support Step2 formal generation of synthetic_samples_step3_ready.jsonl.",
            "expected_step2_ready_file": "synthetic_samples_step3_ready.jsonl",
            "step3_eval_leakage_status": "pending_missing_frozen_eval_assets",
        },
        "notes": "Final formal-ready acceptance still requires frozen Step3 eval/test leakage audit once those assets exist.",
    }


def materialize_fewshot_pool(args: argparse.Namespace) -> None:
    review_rows = read_csv_rows(args.review_sheet_csv)
    normalized_rows, summary = summarize_review_sheet(
        review_rows,
        min_final_size=args.min_final_size,
        target_final_size=args.target_final_size,
        max_final_size=args.max_final_size,
        min_per_common_signature=args.min_per_common_signature,
    )
    if summary.blockers:
        payload = {
            "generated_at_utc": utc_now(),
            "review_sheet_csv": repo_rel(args.review_sheet_csv),
            "blockers": summary.blockers,
            "warnings": summary.warnings,
            "eligible_accept_rows": summary.eligible_accept_rows,
            "common_signature_coverage_all_eligible": summary.common_signature_coverage_all_eligible,
        }
        write_json(args.delivery_dir / DEFAULT_SELECTION_SUMMARY_FILENAME, payload)
        write_text(args.delivery_dir / DEFAULT_SELECTION_SUMMARY_MD_FILENAME, render_review_summary_md({
            "total_rows": summary.total_rows,
            "pending_rows": summary.pending_rows,
            "accept_rows": summary.accept_rows,
            "reject_rows": summary.reject_rows,
            "invalid_accept_rows": summary.invalid_accept_rows,
            "eligible_accept_rows": summary.eligible_accept_rows,
            "common_signature_coverage_all_eligible": summary.common_signature_coverage_all_eligible,
            "blockers": summary.blockers,
            "warnings": summary.warnings,
        }))
        raise SystemExit("review sheet not formal-ready; see selection_summary.json for blockers")

    eligible_accept_rows = [
        row
        for row in normalized_rows
        if row["review_decision_normalized"] == "accept" and not row["validation_errors"]
    ]
    selected_count_target = min(args.target_final_size, len(eligible_accept_rows))
    if selected_count_target < args.min_final_size:
        raise SystemExit(
            f"eligible reviewed rows below min_final_size: {selected_count_target} < {args.min_final_size}"
        )
    selected_rows = choose_rows_for_final_pool(
        eligible_accept_rows,
        target_final_size=selected_count_target,
        min_per_common_signature=args.min_per_common_signature,
    )
    if len(selected_rows) > args.max_final_size:
        selected_rows = selected_rows[: args.max_final_size]
    db_rows = []
    for row in selected_rows:
        canonical = row["type_signature_canonical_normalized"]
        db_rows.append(
            {
                "example_id": build_example_id(row["repo_normalized"], row["sha_normalized"]),
                "repo": row["repo_normalized"],
                "sha": row["sha_normalized"],
                "type_pair": canonical,
                "type_signature_raw": row["type_signature_raw_normalized"] or canonical,
                "type_signature_canonical": canonical,
                "intent_k": int(row["intent_k_normalized"] or 2),
                "subject": row["subject_normalized_final"],
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": float(row["quality_score_normalized"]),
                "quality_status": "pass",
                "message_status": "pass",
                "notes": build_notes_payload(row),
            }
        )

    args.delivery_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.delivery_dir / DEFAULT_DB_FILENAME
    write_fewshot_db(db_path, db_rows, args.table)

    audit_payload = build_audit_payload(
        db_path,
        args.table,
        min_total=args.audit_min_total,
        min_per_common_signature=args.min_per_common_signature,
    )
    write_json(args.delivery_dir / DEFAULT_AUDIT_FILENAME, audit_payload)

    provisional_manifest = build_manifest_payload(
        db_path=db_path,
        input_csv=args.input_csv,
        review_sheet_csv=args.review_sheet_csv,
        selected_rows=selected_rows,
        audit_payload=audit_payload,
        preflight_payload=default_preflight_stub("preflight_not_run_yet"),
        min_final_size=args.min_final_size,
        target_final_size=args.target_final_size,
        max_final_size=args.max_final_size,
        audit_min_total=args.audit_min_total,
        min_per_common_signature=args.min_per_common_signature,
    )
    build_manifest_path = args.delivery_dir / DEFAULT_BUILD_MANIFEST_FILENAME
    write_json(build_manifest_path, provisional_manifest)

    if args.run_preflight:
        preflight_payload = run_step2_preflight(
            preflight_config=args.preflight_config,
            fewshot_db=db_path,
            build_manifest_path=build_manifest_path,
            delivery_dir=args.delivery_dir,
        )
    else:
        preflight_payload = default_preflight_stub("preflight_skipped_by_flag")
    write_json(args.delivery_dir / DEFAULT_PREFLIGHT_FILENAME, preflight_payload)

    manifest_payload = build_manifest_payload(
        db_path=db_path,
        input_csv=args.input_csv,
        review_sheet_csv=args.review_sheet_csv,
        selected_rows=selected_rows,
        audit_payload=audit_payload,
        preflight_payload=preflight_payload,
        min_final_size=args.min_final_size,
        target_final_size=args.target_final_size,
        max_final_size=args.max_final_size,
        audit_min_total=args.audit_min_total,
        min_per_common_signature=args.min_per_common_signature,
    )
    write_json(build_manifest_path, manifest_payload)

    final_coverage = Counter(row["type_signature_canonical_normalized"] for row in selected_rows)
    summary_payload = {
        "generated_at_utc": utc_now(),
        "input_csv": repo_rel(args.input_csv),
        "review_sheet_csv": repo_rel(args.review_sheet_csv),
        "delivery_dir": repo_rel(args.delivery_dir),
        "selection_policy": "common_signature_cover_first_then_repo_diverse_fill",
        "min_final_size": args.min_final_size,
        "target_final_size": args.target_final_size,
        "max_final_size": args.max_final_size,
        "selected_count": len(selected_rows),
        "eligible_accept_rows": len(eligible_accept_rows),
        "pending_rows": summary.pending_rows,
        "invalid_accept_rows": summary.invalid_accept_rows,
        "audit_pass": bool((audit_payload.get("audit", {}) or {}).get("audit_pass", False)),
        "retrieval_probe_ok": bool(audit_payload.get("retrieval_probe_ok", False)),
        "preflight_attempted": bool(preflight_payload.get("attempted", False)),
        "preflight_passed": bool(preflight_payload.get("passed", False)),
        "common_signature_coverage_selected": {
            signature: int(final_coverage.get(signature, 0))
            for signature in CONSTRUCT.DEFAULT_FEWSHOT_COMMON_SIGNATURES
        },
        "style_policy": "subject_normalized must pass strict style",
        "step3_eval_leakage_status": "pending_missing_frozen_eval_assets",
        "blockers": [],
        "warnings": [],
        "artifacts": {
            "fewshot_db": repo_rel(db_path),
            "build_manifest": repo_rel(build_manifest_path),
            "fewshot_audit": repo_rel(args.delivery_dir / DEFAULT_AUDIT_FILENAME),
            "preflight_report": repo_rel(args.delivery_dir / DEFAULT_PREFLIGHT_FILENAME),
        },
    }
    if not summary_payload["preflight_passed"]:
        summary_payload["warnings"].append("step2_preflight_not_passed_or_not_attempted")
    if not bool((audit_payload.get("audit", {}) or {}).get("audit_pass", False)):
        summary_payload["blockers"].append("fewshot_audit_not_passed")
    if not bool(audit_payload.get("retrieval_probe_ok", False)):
        summary_payload["blockers"].append("fewshot_retrieval_probe_not_passed")
    write_json(args.delivery_dir / DEFAULT_SELECTION_SUMMARY_FILENAME, summary_payload)
    write_text(args.delivery_dir / DEFAULT_SELECTION_SUMMARY_MD_FILENAME, render_review_summary_md({
        "total_rows": summary.total_rows,
        "pending_rows": summary.pending_rows,
        "accept_rows": summary.accept_rows,
        "reject_rows": summary.reject_rows,
        "invalid_accept_rows": summary.invalid_accept_rows,
        "eligible_accept_rows": len(eligible_accept_rows),
        "common_signature_coverage_all_eligible": summary_payload["common_signature_coverage_selected"],
        "blockers": summary_payload["blockers"],
        "warnings": summary_payload["warnings"],
    }))

    delivery_readme = "\n".join(
        [
            "# Formal-ready Few-shot Delivery",
            "",
            "## Artifacts",
            f"- fewshot_pool.db: `{repo_rel(db_path)}`",
            f"- build_manifest.json: `{repo_rel(build_manifest_path)}`",
            f"- fewshot_audit.json: `{repo_rel(args.delivery_dir / DEFAULT_AUDIT_FILENAME)}`",
            f"- preflight_report.json: `{repo_rel(args.delivery_dir / DEFAULT_PREFLIGHT_FILENAME)}`",
            f"- selection_summary.json: `{repo_rel(args.delivery_dir / DEFAULT_SELECTION_SUMMARY_FILENAME)}`",
            "",
            "## Summary",
            f"- selected_count: `{len(selected_rows)}`",
            f"- audit_pass: `{bool((audit_payload.get('audit', {}) or {}).get('audit_pass', False))}`",
            f"- retrieval_probe_ok: `{bool(audit_payload.get('retrieval_probe_ok', False))}`",
            f"- preflight_attempted: `{bool(preflight_payload.get('attempted', False))}`",
            f"- preflight_passed: `{bool(preflight_payload.get('passed', False))}`",
            "",
            "## Notes",
            "- 本交付使用 canonical M-only 数据源。",
            "- repo+sha 去泄露对象是当前 Step2 正式 source CSV。",
            "- Step3 eval/test 泄露审计仍待冻结资产后补做。",
        ]
    ) + "\n"
    write_text(args.delivery_dir / DEFAULT_DELIVERY_README_FILENAME, delivery_readme)
    print(f"fewshot_db={db_path}")
    print(f"selected_count={len(selected_rows)}")
    print(f"audit_pass={int(bool((audit_payload.get('audit', {}) or {}).get('audit_pass', False)))}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and materialize formal-ready Step2 few-shot assets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Build M-only disjoint candidate CSV and manual review sheet.")
    prepare.add_argument("--input-csv", type=Path, default=DEFAULT_M_SOURCE_CSV)
    prepare.add_argument("--step2-source-csv", type=Path, default=DEFAULT_STEP2_SOURCE_CSV)
    prepare.add_argument("--candidate-csv", type=Path, default=DEFAULT_CANDIDATE_CSV)
    prepare.add_argument("--review-sheet-csv", type=Path, default=DEFAULT_REVIEW_SHEET_CSV)
    prepare.add_argument("--report-json", type=Path, default=DEFAULT_CANDIDATE_REPORT_JSON)
    prepare.add_argument("--report-md", type=Path, default=DEFAULT_CANDIDATE_REPORT_MD)

    report = subparsers.add_parser("report", help="Summarize reviewed few-shot sheet and expose blockers.")
    report.add_argument("--review-sheet-csv", type=Path, default=DEFAULT_REVIEW_SHEET_CSV)
    report.add_argument("--min-final-size", type=int, default=120)
    report.add_argument("--target-final-size", type=int, default=130)
    report.add_argument("--max-final-size", type=int, default=150)
    report.add_argument(
        "--min-per-common-signature",
        type=int,
        default=CONSTRUCT.DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
    )
    report.add_argument("--output-json", type=Path, default=None)
    report.add_argument("--output-md", type=Path, default=None)

    materialize = subparsers.add_parser("materialize", help="Build the final few-shot DB and delivery artifacts.")
    materialize.add_argument("--input-csv", type=Path, default=DEFAULT_M_SOURCE_CSV)
    materialize.add_argument("--review-sheet-csv", type=Path, default=DEFAULT_REVIEW_SHEET_CSV)
    materialize.add_argument("--delivery-dir", type=Path, default=DEFAULT_DELIVERY_DIR)
    materialize.add_argument("--table", default="fewshot_examples")
    materialize.add_argument("--min-final-size", type=int, default=120)
    materialize.add_argument("--target-final-size", type=int, default=130)
    materialize.add_argument("--max-final-size", type=int, default=150)
    materialize.add_argument(
        "--min-per-common-signature",
        type=int,
        default=CONSTRUCT.DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
    )
    materialize.add_argument("--audit-min-total", type=int, default=CONSTRUCT.DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES)
    materialize.add_argument("--preflight-config", type=Path, default=DEFAULT_PREFLIGHT_CONFIG)
    materialize.add_argument("--run-preflight", dest="run_preflight", action="store_true")
    materialize.add_argument("--skip-preflight", dest="run_preflight", action="store_false")
    materialize.set_defaults(run_preflight=True)
    return parser


def validate_paths(args: argparse.Namespace) -> None:
    if getattr(args, "command", "") == "prepare":
        if not args.input_csv.is_file():
            raise SystemExit(f"invalid input_csv: {args.input_csv}")
        if not args.step2_source_csv.is_file():
            raise SystemExit(f"invalid step2_source_csv: {args.step2_source_csv}")
    if getattr(args, "command", "") in {"report", "materialize"}:
        if not args.review_sheet_csv.is_file():
            raise SystemExit(f"invalid review_sheet_csv: {args.review_sheet_csv}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_paths(args)
    if args.command == "prepare":
        prepare_candidates(args)
        return
    if args.command == "report":
        report_review_sheet(args)
        return
    if args.command == "materialize":
        materialize_fewshot_pool(args)
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
