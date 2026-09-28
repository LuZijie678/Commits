from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from code.mica.data.asset_registry import compute_file_sha256
from code.mica.data.edit_unit import parse_unified_diff_to_edit_units
from code.mica.features.file_role import infer_file_role
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl
from code.mica.stage1_v2.family_split import (
    assign_atomic_family_and_split_components,
    build_family_safe_synthetic_split,
    canonicalize_candidate_row,
)
from code.mica.stage1_v2.leakage import audit_stage1_v2_leakage, fingerprint_text

from code.step2.code import construct_simple_two_intent as step2_constructor


ATOMIC_SOURCE_AUDIT_SCHEMA_VERSION = "mica-stage1-v2-atomic-source-audit-v1"
SYNTHETIC_MANIFEST_SCHEMA_VERSION = "mica-stage1-v2-synthetic-manifest-v1"
REAL_COUNT_CANDIDATE_SCHEMA_VERSION = "mica-stage1-v2-real-count-candidate-v1"
REAL_ADJUDICATED_CANDIDATE_SCHEMA_VERSION = "mica-stage1-v2-real-adjudicated-candidate-v1"
REAL_ALIGNMENT_PILOT_PACKAGE_SCHEMA_VERSION = "mica-stage1-v2-real-alignment-pilot-package-v1"
BACKGROUND_QUEUE_SCHEMA_VERSION = "mica-stage1-v2-background-annotation-queue-v1"
QUALIFICATION_RECORD_SCHEMA_VERSION = "mica-stage1-v2-qualification-record-v1"
ANNOTATION_READINESS_SCHEMA_VERSION = "mica-stage1-v2-annotation-readiness-v1"
FAMILY_MAP_SCHEMA_VERSION = "mica-stage1-v2-atomic-family-map-v1"
DEFAULT_SYNTHETIC_COUNTS = {
    "train": 1000,
    "dev": 250,
    "synthetic_control_test": 250,
}
DEFAULT_PILOT_GUIDELINE_VERSION = "stage1-v2-alignment-guideline-pilot-v1"
DEFAULT_COUNT_GUIDELINE_VERSION = "stage1-v2-count-guideline-pilot-v1"
DEFAULT_ANNOTATION_VERSION = "stage1-v2-pilot-v1"
DEFAULT_PROTOCOL_VERSION = "stage1-v2-protocol"
DEFAULT_QUALIFICATION_SIZE = 20
DEFAULT_REAL_COUNT_PILOT_TARGET = 200
DEFAULT_REAL_ADJUDICATED_PILOT_TARGET = 100
DEFAULT_REAL_ADJUDICATED_FINAL_POOL_TARGET = 1800
ATOMIC_SOURCE_REJECTION_PATTERNS = (
    "merge branch",
    "merge pull request",
    "release ",
    "chore(release)",
)
ATOMIC_SOURCE_MANUAL_REVIEW_PATTERNS = (
    "revert",
    "backport",
    "cherry-pick",
    "vendor",
    "generated",
)
BACKGROUND_PATH_MARKERS = ("lock", "vendor", "generated", "snapshot", "package-lock", "yarn.lock", "pnpm-lock")
DEFAULT_REAL_ADJUDICATED_PILOT_STRATA = {
    "probable_k1_regular": 15,
    "probable_k1_hard_single": 15,
    "probable_k2": 35,
    "probable_k3": 20,
    "probable_k4_or_complex": 15,
}
SYNTHETIC_SPLIT_NAMES = ("train", "dev", "synthetic_control_test")
SYNTHETIC_MANIFEST_FILE_NAMES = {
    "train": "synthetic_train.jsonl",
    "dev": "synthetic_dev.jsonl",
    "synthetic_control_test": "synthetic_control_test.jsonl",
}
STEP2_RUNTIME_CONFIG_PATH = Path("code/step2/configs/step2_runtime_config.json")
STEP2_FEWSHOT_DB_PATH = Path("datasets/step2/delivery/current/fewshot_pool.db")
STEP2_FEWSHOT_BUILD_MANIFEST_PATH = Path("datasets/step2/delivery/current/build_manifest.json")


@dataclass(frozen=True)
class CandidateExclusion:
    sample_id: str
    reason: str
    source_asset: str
    repository: str
    commit_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "sample_id": self.sample_id,
            "reason": self.reason,
            "source_asset": self.source_asset,
            "repository": self.repository,
            "commit_id": self.commit_id,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _set_large_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def read_large_csv_rows(path: str | Path) -> list[dict[str, str]]:
    _set_large_csv_field_limit()
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def stable_hash(parts: Iterable[object], *, prefix: str) -> str:
    text = "|".join(str(part) for part in parts if str(part) != "")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def summarize_numeric(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "max": None, "mean": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "min": ordered[0],
        "median": median,
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered), 6),
    }


def build_annotation_state_history_entry(
    *,
    actor: str,
    action: str,
    status_from: str,
    status_to: str,
    timestamp: str,
    annotation_version: str,
    guideline_version: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "actor": actor,
        "action": action,
        "status_from": status_from,
        "status_to": status_to,
        "timestamp": timestamp,
        "annotation_version": annotation_version,
        "guideline_version": guideline_version,
        "details": dict(details or {}),
    }


def normalize_atomic_source_row(raw: dict[str, Any], *, source_pool_path: str | Path) -> dict[str, Any]:
    repo = str(raw.get("repo") or raw.get("repository") or "").strip()
    sha = str(raw.get("sha") or raw.get("commit_id") or "").strip()
    sample_id = f"atomic::{repo}@{sha}" if repo and sha else f"atomic::{sha or 'missing_sha'}"
    diff_text = str(raw.get("git_diff") or "")
    edit_units = parse_unified_diff_to_edit_units(diff_text, repo=repo, sample_id=sample_id)
    path_roles = sorted({str(unit.file_role or infer_file_role(unit.file_path) or "unknown") for unit in edit_units})
    file_paths = [str(unit.file_path) for unit in edit_units]
    file_count = len(set(file_paths))
    hunk_count = len(edit_units)
    changed_lines = sum(len(unit.added_lines) + len(unit.deleted_lines) for unit in edit_units)
    normalized = canonicalize_candidate_row(
        {
            **raw,
            "sample_id": sample_id,
            "repo": repo,
            "repository": repo,
            "sha": sha,
            "source_atomic_commit_ids": [f"{repo}@{sha}"] if repo and sha else [],
            "normalized_diff_hash": fingerprint_text(diff_text),
            "edit_unit_fingerprint": fingerprint_text(
                json.dumps(
                    [
                        {
                            "file_path": unit.file_path,
                            "patch_text": unit.patch_text,
                        }
                        for unit in edit_units
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
            "construction_group": f"atomic_source::{repo}@{sha}" if repo and sha else sample_id,
        }
    )
    return {
        **normalized,
        "schema_version": ATOMIC_SOURCE_AUDIT_SCHEMA_VERSION,
        "source_pool_path": str(source_pool_path),
        "commit_id": sha,
        "source_atomic_commit_id": f"{repo}@{sha}" if repo and sha else "",
        "subject": str(raw.get("subject") or ""),
        "message": str(raw.get("message") or ""),
        "type": str(raw.get("type") or ""),
        "file_count": file_count,
        "hunk_count": hunk_count,
        "changed_lines": changed_lines,
        "path_roles": path_roles,
        "edit_units": [
            {
                "unit_id": unit.unit_id,
                "hunk_id": unit.hunk_id,
                "file_path": unit.file_path,
                "file_role": unit.file_role,
                "language": unit.language,
                "patch_text": unit.patch_text,
                "added_lines": list(unit.added_lines),
                "deleted_lines": list(unit.deleted_lines),
                "changed_identifiers": list(unit.identifiers),
            }
            for unit in edit_units
        ],
        "unit_count": len(edit_units),
        "git_diff": diff_text,
    }


def classify_atomic_source_row(
    row: dict[str, Any],
    *,
    seen_repo_sha: set[str],
    seen_normalized_diff_hash: dict[str, str],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    repo = str(row.get("repository") or row.get("repo") or "")
    sha = str(row.get("commit_id") or row.get("sha") or "")
    repo_sha = f"{repo}@{sha}" if repo and sha else ""
    subject = f"{row.get('subject', '')}\n{row.get('message', '')}".lower()
    path_roles = {str(item) for item in list(row.get("path_roles") or [])}
    normalized_diff_hash = str(row.get("normalized_diff_hash") or "")

    if not repo or not sha:
        return "rejected", ["missing_repo_or_sha"]
    if not str(row.get("git_diff") or "").strip():
        return "rejected", ["missing_git_diff"]
    if int(row.get("unit_count") or 0) <= 0:
        return "rejected", ["unparseable_or_empty_diff"]
    if repo_sha in seen_repo_sha:
        return "rejected", ["duplicate_repo_sha"]
    if normalized_diff_hash and normalized_diff_hash in seen_normalized_diff_hash:
        reasons.append("duplicate_normalized_diff_requires_manual_review")
    if any(pattern in subject for pattern in ATOMIC_SOURCE_REJECTION_PATTERNS):
        return "rejected", ["non_atomic_subject_pattern"]
    if any(pattern in subject for pattern in ATOMIC_SOURCE_MANUAL_REVIEW_PATTERNS):
        reasons.append("manual_review_subject_pattern")
    if int(row.get("file_count") or 0) > 4:
        reasons.append("high_file_count")
    if int(row.get("hunk_count") or 0) > 6:
        reasons.append("high_hunk_count")
    if int(row.get("changed_lines") or 0) > 160:
        reasons.append("high_changed_lines")
    if not str(row.get("type") or "").strip():
        reasons.append("missing_type")
    if any(marker in subject for marker in ("generated", "vendor", "snapshot", "lockfile")):
        reasons.append("possible_generated_or_vendor_change")
    if path_roles and path_roles.issubset({"docs", "config", "vendor", "generated", "lockfile", "unknown"}):
        reasons.append("non_semantic_or_background_heavy_only")
    if any(marker in path.lower() for path in _iter_file_paths(row) for marker in BACKGROUND_PATH_MARKERS):
        reasons.append("background_marker_in_path")
    if reasons:
        return "manual_review", sorted(set(reasons))
    seen_repo_sha.add(repo_sha)
    if normalized_diff_hash:
        seen_normalized_diff_hash[normalized_diff_hash] = repo_sha
    return "accepted", []


def audit_atomic_source_pool(
    *,
    source_csv: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    rows = [normalize_atomic_source_row(row, source_pool_path=source_csv) for row in read_large_csv_rows(source_csv)]
    seen_repo_sha: set[str] = set()
    seen_normalized_diff_hash: dict[str, str] = {}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        status, reasons = classify_atomic_source_row(
            row,
            seen_repo_sha=seen_repo_sha,
            seen_normalized_diff_hash=seen_normalized_diff_hash,
        )
        record = {
            "schema_version": ATOMIC_SOURCE_AUDIT_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "creation_git_sha": creation_git_sha,
            "created_at": created_at_value,
            "sample_id": row["sample_id"],
            "repository": row["repository"],
            "commit_id": row["commit_id"],
            "sha": row["commit_id"],
            "source_atomic_commit_id": row["source_atomic_commit_id"],
            "normalized_diff_hash": row["normalized_diff_hash"],
            "edit_unit_fingerprint": row["edit_unit_fingerprint"],
            "subject": row["subject"],
            "message": row["message"],
            "type": row["type"],
            "file_count": row["file_count"],
            "hunk_count": row["hunk_count"],
            "changed_lines": row["changed_lines"],
            "path_roles": list(row["path_roles"]),
            "unit_count": row["unit_count"],
            "status": status,
            "reasons": list(reasons),
            "source_quality_status": "source_quality_unverified" if status != "accepted" else "candidate_accepted",
            "requires_manual_review": status == "manual_review",
        }
        for reason in reasons:
            reason_counts[reason] += 1
        if status == "accepted":
            accepted.append({**record, "git_diff": row["git_diff"]})
        elif status == "manual_review":
            manual_review.append(record)
        else:
            rejected.append(record)

    accepted_sorted = sorted(accepted, key=lambda item: (item["repository"], item["commit_id"]))
    manual_review_sorted = sorted(manual_review, key=lambda item: (item["repository"], item["commit_id"]))
    rejected_sorted = sorted(rejected, key=lambda item: (item["repository"], item["commit_id"]))

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    accepted_path = output_root_path / "accepted_atomic_sources.jsonl"
    rejected_path = output_root_path / "rejected_atomic_sources.jsonl"
    manual_review_path = output_root_path / "manual_review_queue.jsonl"
    report_path = output_root_path / "atomic_source_quality_report.json"
    write_jsonl(accepted_path, accepted_sorted)
    write_jsonl(rejected_path, rejected_sorted)
    write_jsonl(manual_review_path, manual_review_sorted)
    report = {
        "schema_version": ATOMIC_SOURCE_AUDIT_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "source_pool_path": str(source_csv),
        "total_rows": len(rows),
        "accepted_count": len(accepted_sorted),
        "manual_review_count": len(manual_review_sorted),
        "rejected_count": len(rejected_sorted),
        "reason_counts": dict(sorted(reason_counts.items())),
        "status_counts": {
            "accepted": len(accepted_sorted),
            "manual_review": len(manual_review_sorted),
            "rejected": len(rejected_sorted),
        },
        "accepted_path": str(accepted_path),
        "manual_review_path": str(manual_review_path),
        "rejected_path": str(rejected_path),
        "accepted_file_count_summary": summarize_numeric([int(row["file_count"]) for row in accepted_sorted]),
        "accepted_hunk_count_summary": summarize_numeric([int(row["hunk_count"]) for row in accepted_sorted]),
        "accepted_changed_lines_summary": summarize_numeric([int(row["changed_lines"]) for row in accepted_sorted]),
        "formal_ready": False,
        "source_quality_status": "source_quality_unverified",
    }
    write_json(report_path, report)
    return {
        "report": report,
        "report_path": str(report_path),
        "accepted_path": str(accepted_path),
        "manual_review_path": str(manual_review_path),
        "rejected_path": str(rejected_path),
    }


def strip_large_source_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"git_diff", "edit_units", "message"}
    }


def materialize_family_safe_synthetic_assets(
    *,
    accepted_atomic_source_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
    split_seed: int = 42,
    synthetic_target_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    target_counts = dict(DEFAULT_SYNTHETIC_COUNTS)
    target_counts.update(dict(synthetic_target_counts or {}))
    raw_sources = read_jsonl(accepted_atomic_source_path)
    if not raw_sources:
        raise ValueError("Accepted atomic source pool is empty.")
    split_payload = build_family_safe_synthetic_split(
        [
            {
                **row,
                "source_type": "strict_atomic_source",
                "cardinality_label_type": "exact_k1_gold",
            }
            for row in raw_sources
        ],
        split_seed=split_seed,
    )
    source_rows_by_split = split_payload["rows_by_split"]
    family_map_rows = _build_atomic_family_assignment_rows(
        source_rows_by_split=source_rows_by_split,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
        created_at=created_at_value,
    )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    family_map_path = output_root_path / "atomic_family_map.jsonl"
    write_jsonl(family_map_path, family_map_rows)

    combined_manifest_rows: list[dict[str, Any]] = []
    construction_errors: list[dict[str, Any]] = []
    used_source_ids: set[str] = set()
    runtime_root = Path(tempfile.mkdtemp(prefix="mica_stage1_v2_synth_"))
    for split_name in SYNTHETIC_SPLIT_NAMES:
        split_rows = list(source_rows_by_split.get(split_name) or [])
        if not split_rows:
            continue
        csv_path = runtime_root / f"{split_name}_sources.csv"
        runtime_output = runtime_root / split_name
        _write_atomic_source_csv(split_rows, csv_path)
        try:
            step3_path, precheck_path = _run_step2_construction_for_split(
                source_csv=csv_path,
                output_dir=runtime_output,
                target_count=int(target_counts.get(split_name, 0)),
                split_seed=split_seed,
                split_name=split_name,
            )
        except Exception as exc:
            construction_errors.append(
                {
                    "split": split_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        split_manifest_rows = build_synthetic_manifest_rows(
            step3_ready_path=step3_path,
            split_name=split_name,
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            created_at=created_at_value,
        )
        for row in split_manifest_rows:
            used_source_ids.update(str(item) for item in list(row.get("source_atomic_commit_ids") or []))
        for precheck_row in read_jsonl(precheck_path):
            construction_errors.append(
                {
                    "split": split_name,
                    "error_type": "source_pair_precheck_skip",
                    "sample_id": str(precheck_row.get("sample_id") or ""),
                    "source_atomic_commit_ids": [
                        f"{item.get('repo', precheck_row.get('repo', ''))}@{item.get('sha', '')}"
                        for item in list(precheck_row.get("sources") or [])
                        if isinstance(item, dict) and item.get("sha")
                    ],
                }
            )
        combined_manifest_rows.extend(split_manifest_rows)

    enriched_rows = assign_atomic_family_and_split_components(combined_manifest_rows)
    final_rows_by_split: dict[str, list[dict[str, Any]]] = {name: [] for name in SYNTHETIC_SPLIT_NAMES}
    for row in enriched_rows:
        final_rows_by_split[str(row["split"])].append(row)
    leakage_report = audit_stage1_v2_leakage(
        final_rows_by_split,
        near_duplicate_limit=250_000,
    )
    split_summary = _summarize_materialized_synthetic_splits(final_rows_by_split)
    excluded_records = [
        {
            "sample_id": row["sample_id"],
            "repository": row["repository"],
            "commit_id": row["commit_id"],
            "source_atomic_commit_id": row["source_atomic_commit_id"],
            "reason": "accepted_source_not_selected_into_current_synthetic_target_set",
        }
        for row in raw_sources
        if str(row.get("source_atomic_commit_id") or "") not in used_source_ids
    ]
    split_paths: dict[str, str] = {}
    for split_name in SYNTHETIC_SPLIT_NAMES:
        rows = list(final_rows_by_split.get(split_name) or [])
        target = output_root_path / SYNTHETIC_MANIFEST_FILE_NAMES[split_name]
        split_paths[split_name] = str(target)
        write_jsonl(target, sorted(rows, key=lambda item: str(item.get("sample_id") or "")))
    leakage_path = output_root_path / "cross_split_leakage_report.json"
    summary_path = output_root_path / "split_summary.json"
    excluded_path = output_root_path / "excluded_records.jsonl"
    construction_errors_path = output_root_path / "construction_errors.jsonl"
    write_json(leakage_path, leakage_report)
    write_json(summary_path, split_summary)
    write_jsonl(excluded_path, excluded_records)
    write_jsonl(construction_errors_path, construction_errors)
    return {
        "schema_version": SYNTHETIC_MANIFEST_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "family_map_path": str(family_map_path),
        "split_paths": split_paths,
        "leakage_path": str(leakage_path),
        "summary_path": str(summary_path),
        "excluded_path": str(excluded_path),
        "construction_errors_path": str(construction_errors_path),
        "construction_error_count": len(construction_errors),
        "fatal_construction_error_count": sum(
            1 for item in construction_errors if str(item.get("error_type") or "") != "source_pair_precheck_skip"
        ),
        "split_summary": split_summary,
        "leakage_clean": bool(leakage_report.get("leakage_clean")),
    }


def build_real_count_candidate_assets(
    *,
    accepted_atomic_source_path: str | Path,
    m_verified_csv: str | Path,
    hard_b_csv: str | Path,
    stage1_v1_final_test_manifest: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
    pilot_target: int = DEFAULT_REAL_COUNT_PILOT_TARGET,
    guideline_version: str = DEFAULT_COUNT_GUIDELINE_VERSION,
    annotation_version: str = DEFAULT_ANNOTATION_VERSION,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    blocked_ids = _load_stage1_v1_blocked_commit_ids(stage1_v1_final_test_manifest)
    exclusions: list[CandidateExclusion] = []
    pool: list[dict[str, Any]] = []
    seen_repo_sha: set[str] = set()
    seen_diff_hash: set[str] = set()

    for row in read_jsonl(accepted_atomic_source_path):
        candidate = _build_real_count_candidate_from_atomic_source(
            row,
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            created_at=created_at_value,
        )
        _append_real_candidate(
            pool,
            candidate,
            exclusions=exclusions,
            blocked_ids=blocked_ids,
            seen_repo_sha=seen_repo_sha,
            seen_diff_hash=seen_diff_hash,
            source_asset="accepted_atomic_sources",
        )
    for row in read_large_csv_rows(hard_b_csv):
        candidate = _build_real_count_candidate_from_real_csv_row(
            row,
            source_type="hard_b",
            current_weak_label="hard_single",
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            created_at=created_at_value,
        )
        _append_real_candidate(
            pool,
            candidate,
            exclusions=exclusions,
            blocked_ids=blocked_ids,
            seen_repo_sha=seen_repo_sha,
            seen_diff_hash=seen_diff_hash,
            source_asset="hard_b",
        )
    for row in read_large_csv_rows(m_verified_csv):
        candidate = _build_real_count_candidate_from_real_csv_row(
            row,
            source_type="m_weak",
            current_weak_label=str(row.get("llm_intent_count_estimate") or "censored_k_ge_2"),
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            created_at=created_at_value,
        )
        _append_real_candidate(
            pool,
            candidate,
            exclusions=exclusions,
            blocked_ids=blocked_ids,
            seen_repo_sha=seen_repo_sha,
            seen_diff_hash=seen_diff_hash,
            source_asset="m_weak",
        )

    pool_sorted = sorted(pool, key=lambda item: (item["repository"], item["commit_id"]))
    pool_with_split = _assign_train_dev_candidate_splits(pool_sorted)
    pilot_rows = sample_real_count_pilot_queue(pool_with_split, target_count=pilot_target)
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    pool_path = output_root_path / "real_count_candidate_pool.jsonl"
    queue_path = output_root_path / "real_count_annotation_queue_pilot.jsonl"
    summary_path = output_root_path / "real_count_candidate_summary.json"
    leakage_path = output_root_path / "real_count_leakage_report.json"
    exclusions_path = output_root_path / "real_count_exclusions.jsonl"
    write_jsonl(pool_path, pool_with_split)
    write_jsonl(queue_path, pilot_rows)
    leakage_report = audit_stage1_v2_leakage(
        {
            "train": [row for row in pool_with_split if row["split_candidate"] == "train"],
            "dev": [row for row in pool_with_split if row["split_candidate"] == "dev"],
        }
    )
    summary = {
        "schema_version": REAL_COUNT_CANDIDATE_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "pool_row_count": len(pool_with_split),
        "pilot_row_count": len(pilot_rows),
        "repository_count": len({row["repository"] for row in pool_with_split}),
        "source_type_counts": dict(sorted(Counter(row["source_type"] for row in pool_with_split).items())),
        "split_counts": dict(sorted(Counter(row["split_candidate"] for row in pool_with_split).items())),
        "probable_strata_counts": dict(
            sorted(Counter(tag for row in pool_with_split for tag in row.get("provisional_tags", [])).items())
        ),
        "formal_ready": False,
    }
    write_json(summary_path, summary)
    write_json(leakage_path, leakage_report)
    write_jsonl(exclusions_path, [item.to_dict() for item in exclusions])
    return {
        "pool_path": str(pool_path),
        "pilot_queue_path": str(queue_path),
        "summary_path": str(summary_path),
        "leakage_path": str(leakage_path),
        "exclusions_path": str(exclusions_path),
        "summary": summary,
    }


def build_real_adjudicated_assets(
    *,
    real_count_candidate_pool_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
    pilot_target: int = DEFAULT_REAL_ADJUDICATED_PILOT_TARGET,
    final_pool_target: int = DEFAULT_REAL_ADJUDICATED_FINAL_POOL_TARGET,
    guideline_version: str = DEFAULT_PILOT_GUIDELINE_VERSION,
    annotation_version: str = DEFAULT_ANNOTATION_VERSION,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    candidates = read_jsonl(real_count_candidate_pool_path)
    pilot_candidates = sample_real_adjudicated_pilot_candidates(candidates, target_count=pilot_target)
    final_pool = sample_real_adjudicated_final_candidate_pool(candidates, target_count=final_pool_target)
    pilot_rows_with_diff = [_inflate_real_candidate_for_annotation(row) for row in pilot_candidates]
    annotator_a_package, annotator_b_package, adjudicator_template, blinding_map = build_blinded_alignment_packages(
        pilot_rows_with_diff,
        guideline_version=guideline_version,
        annotation_version=annotation_version,
    )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    candidate_pool_path = output_root_path / "real_adjudicated_candidate_pool.jsonl"
    provisional_sampling_report_path = output_root_path / "provisional_sampling_report.json"
    uncovered_strata_report_path = output_root_path / "uncovered_strata_report.json"
    repository_concentration_report_path = output_root_path / "repository_concentration_report.json"
    pilot_candidates_path = output_root_path / "real_adjudicated_pilot_candidates.jsonl"
    annotator_a_path = output_root_path / "annotator_a_package.jsonl"
    annotator_b_path = output_root_path / "annotator_b_package.jsonl"
    adjudicator_path = output_root_path / "adjudicator_package_template.jsonl"
    blinding_map_path = output_root_path / "pilot_blinding_map.json"
    pilot_sampling_report_path = output_root_path / "pilot_sampling_report.json"
    pilot_leakage_report_path = output_root_path / "pilot_leakage_report.json"
    pilot_exclusions_path = output_root_path / "pilot_exclusions.jsonl"
    write_jsonl(candidate_pool_path, final_pool)
    write_jsonl(pilot_candidates_path, pilot_rows_with_diff)
    write_jsonl(annotator_a_path, annotator_a_package)
    write_jsonl(annotator_b_path, annotator_b_package)
    write_jsonl(adjudicator_path, adjudicator_template)
    write_json(blinding_map_path, blinding_map)
    provisional_sampling_report = build_real_adjudicated_candidate_summary(final_pool)
    uncovered_strata_report = _build_uncovered_strata_report(final_pool)
    repository_concentration_report = _build_repository_concentration_report(final_pool)
    pilot_leakage_report = audit_stage1_v2_leakage({"pilot": pilot_rows_with_diff})
    pilot_sampling_report = build_real_adjudicated_candidate_summary(pilot_rows_with_diff)
    pilot_exclusions = [
        {
            "sample_id": row["sample_id"],
            "reason": "not_selected_into_100_commit_pilot",
            "repository": row["repository"],
            "commit_id": row["commit_id"],
        }
        for row in final_pool
        if row["sample_id"] not in {item["sample_id"] for item in pilot_rows_with_diff}
    ]
    write_json(provisional_sampling_report_path, provisional_sampling_report)
    write_json(uncovered_strata_report_path, uncovered_strata_report)
    write_json(repository_concentration_report_path, repository_concentration_report)
    write_json(pilot_sampling_report_path, pilot_sampling_report)
    write_json(pilot_leakage_report_path, pilot_leakage_report)
    write_jsonl(pilot_exclusions_path, pilot_exclusions)
    return {
        "candidate_pool_path": str(candidate_pool_path),
        "pilot_candidates_path": str(pilot_candidates_path),
        "annotator_a_path": str(annotator_a_path),
        "annotator_b_path": str(annotator_b_path),
        "adjudicator_path": str(adjudicator_path),
        "blinding_map_path": str(blinding_map_path),
        "pilot_sampling_report_path": str(pilot_sampling_report_path),
        "pilot_leakage_report_path": str(pilot_leakage_report_path),
        "pilot_exclusions_path": str(pilot_exclusions_path),
        "provisional_sampling_report_path": str(provisional_sampling_report_path),
        "uncovered_strata_report_path": str(uncovered_strata_report_path),
        "repository_concentration_report_path": str(repository_concentration_report_path),
    }


def build_background_annotation_assets(
    *,
    real_adjudicated_candidate_pool_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
    target_count: int = 120,
    guideline_version: str = DEFAULT_PILOT_GUIDELINE_VERSION,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    candidates = read_jsonl(real_adjudicated_candidate_pool_path)
    ranked = [
        row
        for row in candidates
        if any(tag in set(row.get("provisional_tags") or []) for tag in ("background_heavy", "source_docs_config", "large_commit"))
    ]
    selected = [_inflate_real_candidate_for_annotation(row) for row in ranked[:target_count]]
    queue = []
    for row in selected:
        queue.append(
            {
                "schema_version": BACKGROUND_QUEUE_SCHEMA_VERSION,
                "protocol_version": protocol_version,
                "creation_git_sha": creation_git_sha,
                "created_at": created_at_value,
                "sample_id": row["sample_id"],
                "commit_id": row["commit_id"],
                "repository": row["repository"],
                "guideline_version": guideline_version,
                "annotation_status": "pending",
                "edit_units": list(row["edit_units"]),
                "candidate_background_types": list(_infer_background_candidate_types_from_row(row)),
                "background_unit_labels": {},
                "notes": None,
            }
        )
    distribution = Counter(
        background_type
        for row in queue
        for background_type in list(row.get("candidate_background_types") or [])
    )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    queue_path = output_root_path / "background_annotation_queue_pilot.jsonl"
    distribution_path = output_root_path / "background_candidate_distribution.json"
    write_jsonl(queue_path, queue)
    write_json(
        distribution_path,
        {
            "schema_version": BACKGROUND_QUEUE_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "creation_git_sha": creation_git_sha,
            "created_at": created_at_value,
            "row_count": len(queue),
            "background_candidate_distribution": dict(sorted(distribution.items())),
            "formal_ready": False,
        },
    )
    return {
        "queue_path": str(queue_path),
        "distribution_path": str(distribution_path),
    }


def build_qualification_materials(
    *,
    synthetic_control_test_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str | None = None,
    sample_count: int = DEFAULT_QUALIFICATION_SIZE,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    rows = read_jsonl(synthetic_control_test_path)
    selected = sorted(rows, key=lambda row: str(row.get("sample_id") or ""))[:sample_count]
    examples = []
    answer_key = []
    for index, row in enumerate(selected, start=1):
        public_id = f"qual_{index:04d}"
        example = {
            "schema_version": QUALIFICATION_RECORD_SCHEMA_VERSION,
            "qualification_id": public_id,
            "commit_id": row["commit_id"],
            "repository": row["repository"],
            "normalized_diff": row.get("synthetic_diff_preview") or _render_diff_preview_from_units(row.get("edit_units", [])),
            "edit_units": list(row.get("edit_units") or []),
            "notes": "qualification_only_controlled_synthetic_example",
        }
        examples.append(example)
        answer_key.append(
            {
                "qualification_id": public_id,
                "exact_k": int(row.get("gold_k") or row.get("gold_count") or 2),
                "unit_to_intent": dict(row.get("gold_unit_to_intent") or {}),
                "background_units": [],
                "source": "synthetic_control_test",
            }
        )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    examples_path = output_root_path / "annotator_examples.jsonl"
    qualification_test_path = output_root_path / "qualification_test.jsonl"
    answer_key_path = output_root_path / "qualification_answer_key_private.jsonl"
    write_jsonl(examples_path, examples)
    write_jsonl(qualification_test_path, examples)
    write_jsonl(answer_key_path, answer_key)
    return {
        "examples_path": str(examples_path),
        "qualification_test_path": str(qualification_test_path),
        "answer_key_path": str(answer_key_path),
        "qualification_gate": {
            "exact_k_accuracy_min": 0.85,
            "pairwise_partition_f1_min": 0.80,
            "background_classification_f1_min": 0.85,
        },
        "created_at": created_at_value,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
    }


def build_annotation_readiness_report(
    *,
    protocol_spec: dict[str, Any],
    asset_registry: dict[str, Any],
    real_count_queue_path: str | Path | None = None,
    real_adjudicated_pilot_path: str | Path | None = None,
    background_queue_path: str | Path | None = None,
    blind_review_asset_path: str | Path | None = None,
    synthetic_scale_gap_report_path: str | Path | None = None,
    required_atomic_sources_path: str | Path | None = None,
    role_conflict_report_path: str | Path | None = None,
    qualification_result_path: str | Path | None = None,
    calibration_result_path: str | Path | None = None,
    calibration_agreement_report_path: str | Path | None = None,
    campaign_progress_path: str | Path | None = None,
) -> dict[str, Any]:
    real_count_rows = read_jsonl(real_count_queue_path) if real_count_queue_path and Path(real_count_queue_path).exists() else []
    real_adjudicated_rows = read_jsonl(real_adjudicated_pilot_path) if real_adjudicated_pilot_path and Path(real_adjudicated_pilot_path).exists() else []
    background_rows = read_jsonl(background_queue_path) if background_queue_path and Path(background_queue_path).exists() else []
    blind_review_rows = read_json(blind_review_asset_path) if blind_review_asset_path and Path(blind_review_asset_path).exists() else {}
    synthetic_scale_gap = read_json(synthetic_scale_gap_report_path) if synthetic_scale_gap_report_path and Path(synthetic_scale_gap_report_path).exists() else {}
    required_atomic_sources = read_jsonl(required_atomic_sources_path) if required_atomic_sources_path and Path(required_atomic_sources_path).exists() else []
    role_conflict_report = read_json(role_conflict_report_path) if role_conflict_report_path and Path(role_conflict_report_path).exists() else {}
    qualification_result = read_json(qualification_result_path) if qualification_result_path and Path(qualification_result_path).exists() else {}
    calibration_result = read_json(calibration_result_path) if calibration_result_path and Path(calibration_result_path).exists() else {}
    calibration_agreement_report = read_json(calibration_agreement_report_path) if calibration_agreement_report_path and Path(calibration_agreement_report_path).exists() else {}
    campaign_progress = read_json(campaign_progress_path) if campaign_progress_path and Path(campaign_progress_path).exists() else {}
    real_count_status = Counter(str(row.get("annotation_status") or "missing") for row in real_count_rows)
    real_adjudicated_status = Counter(str(row.get("annotation_status") or "missing") for row in real_adjudicated_rows)
    blind_review_complete = False
    if isinstance(blind_review_rows, dict):
        blind_review_complete = bool(blind_review_rows.get("completed"))
    synthetic_scale_sufficient = bool(synthetic_scale_gap.get("synthetic_scale_sufficient"))
    required_atomic_sources_human_verified = bool(required_atomic_sources) and all(bool(row.get("human_verified")) for row in required_atomic_sources)
    human_staffing_incomplete = bool(role_conflict_report.get("human_staffing_incomplete", True))
    annotation_staffing_complete = bool(role_conflict_report) and not human_staffing_incomplete
    annotators_qualified = bool(qualification_result.get("passes")) if qualification_result else False
    calibration_round_complete = bool(calibration_result.get("completed")) if calibration_result else False
    calibration_agreement_passed = bool(calibration_agreement_report.get("guideline_status") == "pilot_ready") if calibration_agreement_report else False
    pilot_double_annotation_complete = bool(real_adjudicated_rows) and all(
        str(row.get("annotation_status") or "") in {"agreement", "adjudication_pending", "adjudicated", "quality_reviewed", "eligible_for_asset"}
        for row in real_adjudicated_rows
    )
    pilot_adjudication_complete = bool(real_adjudicated_rows) and all(
        str(row.get("annotation_status") or "") in {"adjudicated", "quality_reviewed", "eligible_for_asset"}
        for row in real_adjudicated_rows
    )
    pilot_guideline_frozen = False
    pilot_quality_gates_passed = calibration_agreement_passed and pilot_adjudication_complete and blind_review_complete
    return {
        "schema_version": ANNOTATION_READINESS_SCHEMA_VERSION,
        "protocol_version": str(protocol_spec.get("protocol_version") or DEFAULT_PROTOCOL_VERSION),
        "real_count_candidate_pool_ready": bool(_asset_has_status(asset_registry, "stage1_v2_real_count_candidate_pool", {"candidate_materialized", "annotation_pending", "pilot_in_progress", "eligible_for_freeze", "frozen"})),
        "real_count_pilot_queue_ready": bool(real_count_rows),
        "real_count_double_annotation_rate": _rate(real_count_rows, {"independently_double_annotated", "agreement", "conflict", "adjudication_pending", "adjudicated", "quality_reviewed", "eligible_for_asset"}),
        "real_count_adjudication_rate": _rate(real_count_rows, {"adjudicated", "quality_reviewed", "eligible_for_asset"}),
        "real_count_agreement_metrics": {
            "status_counts": dict(sorted(real_count_status.items())),
        },
        "Kmax_asset_ready": False,
        "real_adjudicated_candidate_pool_ready": bool(_asset_has_status(asset_registry, "stage1_v2_real_alignment_candidate_pool", {"candidate_materialized", "annotation_pending", "pilot_in_progress", "eligible_for_freeze", "frozen"})),
        "alignment_pilot_queue_ready": bool(real_adjudicated_rows),
        "alignment_double_annotation_rate": _rate(real_adjudicated_rows, {"independently_double_annotated", "agreement", "conflict", "adjudication_pending", "adjudicated", "quality_reviewed", "eligible_for_asset"}),
        "alignment_adjudication_rate": _rate(real_adjudicated_rows, {"adjudicated", "quality_reviewed", "eligible_for_asset"}),
        "alignment_agreement_metrics": {},
        "blind_review_complete": blind_review_complete,
        "benchmark_strata_provisional": bool(real_adjudicated_rows),
        "benchmark_strata_adjudicated": False,
        "background_annotation_ready": bool(background_rows),
        "guideline_pilot_version": DEFAULT_PILOT_GUIDELINE_VERSION,
        "guideline_final_frozen": False,
        "synthetic_scale_sufficient": synthetic_scale_sufficient,
        "required_atomic_sources_human_verified": required_atomic_sources_human_verified,
        "annotation_staffing_complete": annotation_staffing_complete,
        "human_staffing_incomplete": human_staffing_incomplete,
        "annotators_qualified": annotators_qualified,
        "calibration_round_complete": calibration_round_complete,
        "calibration_agreement_passed": calibration_agreement_passed,
        "pilot_guideline_frozen": pilot_guideline_frozen,
        "pilot_double_annotation_complete": pilot_double_annotation_complete,
        "pilot_adjudication_complete": pilot_adjudication_complete,
        "pilot_quality_gates_passed": pilot_quality_gates_passed,
        "annotation_campaign_blocked": bool(role_conflict_report.get("annotation_campaign_blocked", True)),
        "annotation_assets_formal_ready": False,
        "stage1_v2_training_allowed": False,
        "stage2_entry_allowed": False,
        "campaign_progress": campaign_progress,
    }


def _asset_has_status(asset_registry: dict[str, Any], asset_name: str, statuses: set[str]) -> bool:
    assets = dict(asset_registry.get("assets") or {})
    payload = dict(assets.get(asset_name) or {})
    return str(payload.get("status") or "") in statuses


def _rate(rows: list[dict[str, Any]], eligible_statuses: set[str]) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if str(row.get("annotation_status") or "") in eligible_statuses) / len(rows), 6)


def _build_atomic_family_assignment_rows(
    *,
    source_rows_by_split: dict[str, list[dict[str, Any]]],
    creation_git_sha: str,
    protocol_version: str,
    created_at: str,
) -> list[dict[str, Any]]:
    rows = []
    for split_name, split_rows in sorted(source_rows_by_split.items()):
        for row in split_rows:
            rows.append(
                {
                    "schema_version": FAMILY_MAP_SCHEMA_VERSION,
                    "protocol_version": protocol_version,
                    "creation_git_sha": creation_git_sha,
                    "created_at": created_at,
                    "sample_id": row["sample_id"],
                    "repository": row["repository"],
                    "commit_id": row["commit_id"],
                    "source_atomic_commit_ids": list(row.get("source_atomic_commit_ids") or []),
                    "atomic_family_id": row["atomic_family_id"],
                    "split_component_id": row["split_component_id"],
                    "split": split_name,
                }
            )
    return sorted(rows, key=lambda item: (item["split"], item["repository"], item["commit_id"]))


def _write_atomic_source_csv(rows: list[dict[str, Any]], path: Path) -> None:
    stripped_rows = []
    for row in rows:
        payload = dict(row)
        payload.pop("edit_units", None)
        payload["sha"] = str(payload.get("sha") or payload.get("commit_id") or "")
        payload["message"] = str(payload.get("message") or "")
        conservative_tier = str(payload.get("conservative_tier") or payload.get("manual_label") or "A")
        payload["conservative_tier"] = conservative_tier
        payload["manual_label"] = str(payload.get("manual_label") or conservative_tier)
        stripped_rows.append(payload)
    fieldnames = sorted({key for row in stripped_rows for key in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    _set_large_csv_field_limit()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in stripped_rows:
            writer.writerow(row)


def _run_step2_construction_for_split(
    *,
    source_csv: str | Path,
    output_dir: str | Path,
    target_count: int,
    split_seed: int,
    split_name: str,
) -> tuple[Path, Path]:
    if not STEP2_RUNTIME_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Required Step2 runtime config is missing: {STEP2_RUNTIME_CONFIG_PATH}"
        )
    if not STEP2_FEWSHOT_DB_PATH.exists():
        raise FileNotFoundError(
            f"Required Step2 few-shot DB is missing: {STEP2_FEWSHOT_DB_PATH}"
        )
    if not STEP2_FEWSHOT_BUILD_MANIFEST_PATH.exists():
        raise FileNotFoundError(
            "Required Step2 few-shot build manifest is missing: "
            f"{STEP2_FEWSHOT_BUILD_MANIFEST_PATH}"
        )
    args = step2_constructor.parse_args(
        [
            "--config",
            str(STEP2_RUNTIME_CONFIG_PATH),
            "--source-csv",
            str(source_csv),
            "--output-dir",
            str(output_dir),
            "--run-purpose",
            "debug",
            "--intent-k",
            "2",
            "--target-count",
            str(target_count),
            "--seed",
            str(split_seed),
            "--skip-message-stage",
            "--disable-message-gate",
            "--debug-allow-skip-message-stage",
            "--debug-allow-disable-message-gate",
            "--review-samples",
            "0",
            "--selection-quality-priority",
            "legacy",
            "--fewshot-db",
            str(STEP2_FEWSHOT_DB_PATH),
            "--fewshot-build-manifest-path",
            str(STEP2_FEWSHOT_BUILD_MANIFEST_PATH),
        ]
    )
    result = step2_constructor.run_single(args, enforce_gates=False)
    step3_path = Path(result["output_dir"]) / "synthetic_samples_step3_ready.jsonl"
    precheck_path = Path(result["output_dir"]) / "synthetic_samples_precheck_rejected.jsonl"
    if not step3_path.exists():
        raise FileNotFoundError(f"Step2 construction did not produce step3_ready JSONL for split={split_name}")
    if not precheck_path.exists():
        precheck_path.write_text("", encoding="utf-8")
    return step3_path, precheck_path


def build_synthetic_manifest_rows(
    *,
    step3_ready_path: str | Path,
    split_name: str,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str,
) -> list[dict[str, Any]]:
    rows = []
    for raw in read_jsonl(step3_ready_path):
        source_ids = [
            f"{item.get('repo', raw.get('repo', ''))}@{item.get('sha', '')}"
            for item in list(raw.get("sources") or [])
            if isinstance(item, dict) and item.get("sha")
        ]
        gold_alignment = [int(item) for item in list(raw.get("edit_to_intent") or [])]
        step2_sample_id = str(raw.get("sample_id") or "missing_sample_id")
        sample_id = f"{split_name}::{step2_sample_id}"
        synthetic_diff = str(raw.get("synthetic_diff") or "")
        edit_units = parse_unified_diff_to_edit_units(
            synthetic_diff,
            repo=str(raw.get("repo") or ""),
            sample_id=sample_id,
            gold_intent_ids=gold_alignment,
        )
        if not edit_units:
            continue
        construction_group = stable_hash(
            [str(raw.get("construction_type") or raw.get("construction_route") or "route"), *sorted(source_ids)],
            prefix="cg",
        )
        normalized_diff_hash = fingerprint_text(synthetic_diff)
        edit_unit_fingerprint = fingerprint_text(
            json.dumps(
                [
                    {
                        "file_path": unit.file_path,
                        "hunk_id": unit.hunk_id,
                        "patch_text": unit.patch_text,
                    }
                    for unit in edit_units
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        rows.append(
            {
                "schema_version": SYNTHETIC_MANIFEST_SCHEMA_VERSION,
                "protocol_version": protocol_version,
                "creation_git_sha": creation_git_sha,
                "created_at": created_at,
                "sample_id": sample_id,
                "step2_sample_id": step2_sample_id,
                "synthetic_id": sample_id,
                "commit_id": sample_id,
                "repo": str(raw.get("repo") or ""),
                "repository": str(raw.get("repo") or ""),
                "split": split_name,
                "source_type": "strict_synthetic",
                "source_kind": "strict_synthetic_split_internal_construction",
                "source_commit_shas": source_ids,
                "source_atomic_commit_ids": sorted(source_ids),
                "construction_group": construction_group,
                "construction_version": str(raw.get("construction_type") or raw.get("construction_route") or "same_repo_multi_round_robin_v1"),
                "normalized_diff_hash": normalized_diff_hash,
                "edit_unit_fingerprint": edit_unit_fingerprint,
                "pr_id": None,
                "repository_mirror_id": None,
                "cherry_pick_fingerprint": None,
                "backport_fingerprint": None,
                "revert_fingerprint": None,
                "gold_k": int(raw.get("intent_k") or raw.get("intent_count") or 2),
                "gold_provenance_status": "synthetic_construction_gold",
                "gold_count": int(raw.get("intent_k") or raw.get("intent_count") or 2),
                "gold_unit_to_intent": {unit.unit_id: f"intent_{int(unit.gold_intent_id or 0)}" for unit in edit_units},
                "gold_hunk_to_intent": {unit.hunk_id: f"intent_{int(unit.gold_intent_id or 0)}" for unit in edit_units},
                "edit_units": [
                    {
                        "unit_id": unit.unit_id,
                        "hunk_id": unit.hunk_id,
                        "file_path": unit.file_path,
                        "file_role": unit.file_role,
                        "language": unit.language,
                        "patch_text": unit.patch_text,
                        "added_lines": list(unit.added_lines),
                        "deleted_lines": list(unit.deleted_lines),
                        "changed_identifiers": list(unit.identifiers),
                    }
                    for unit in edit_units
                ],
                "intent_subjects": [str(item) for item in list(raw.get("intent_subjects") or [])],
                "intent_types": [str(item) for item in list(raw.get("intent_types") or [])],
                "sample_weight": float(raw.get("final_sample_weight") or raw.get("pair_quality_weight") or 1.0),
                "controlled_synthetic_evaluation_only": split_name == "synthetic_control_test",
                "real_paper_main_test": False,
                "synthetic_diff_preview": _render_diff_preview(synthetic_diff),
            }
        )
    return rows


def _render_diff_preview(diff_text: str, *, max_lines: int = 40) -> str:
    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text
    preview = "\n".join(lines[:max_lines])
    return preview + "\n... [truncated]"


def _render_diff_preview_from_units(edit_units: list[dict[str, Any]], *, max_units: int = 8) -> str:
    lines: list[str] = []
    for unit in edit_units[:max_units]:
        lines.append(f"{unit.get('file_path')}: {unit.get('patch_text', '')}")
    return "\n".join(lines)


def _summarize_materialized_synthetic_splits(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for split_name, rows in sorted(rows_by_split.items()):
        summary[split_name] = {
            "record_count": len(rows),
            "repository_count": len({str(row.get("repository") or "") for row in rows}),
            "atomic_family_count": len({str(row.get("atomic_family_id") or "") for row in rows}),
            "construction_group_count": len({str(row.get("construction_group") or "") for row in rows}),
            "gold_k_distribution": dict(sorted(Counter(int(row.get("gold_k") or 0) for row in rows).items())),
            "controlled_synthetic_evaluation_only": split_name == "synthetic_control_test",
            "real_paper_main_test": False,
        }
    return summary


def _load_stage1_v1_blocked_commit_ids(path: str | Path) -> set[str]:
    payload = read_json(path)
    rows = list(payload.get("rows") or [])
    blocked: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        repo = str(row.get("repository") or row.get("repo") or "")
        commit_id = str(row.get("commit_id") or row.get("source_sha") or "")
        if repo and commit_id:
            blocked.add(f"{repo}@{commit_id}")
        for source_id in list(row.get("source_atomic_commit_ids") or []):
            if str(source_id):
                blocked.add(str(source_id))
    return blocked


def _build_real_count_candidate_from_atomic_source(
    row: dict[str, Any],
    *,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str,
) -> dict[str, Any]:
    diff_text = str(row.get("git_diff") or "")
    return {
        "schema_version": REAL_COUNT_CANDIDATE_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at,
        "sample_id": str(row["sample_id"]),
        "commit_id": str(row["commit_id"]),
        "repository": str(row["repository"]),
        "diff_reference": {
            "repo": str(row["repository"]),
            "sha": str(row["commit_id"]),
            "source_asset": "accepted_atomic_sources",
        },
        "normalized_diff_hash": str(row.get("normalized_diff_hash") or fingerprint_text(diff_text)),
        "current_weak_label": "probable_k1_atomic",
        "source_type": "real_candidate",
        "annotation_status": "pending",
        "annotator_a_exact_k": None,
        "annotator_b_exact_k": None,
        "adjudicated_exact_k": None,
        "annotator_a_id": None,
        "annotator_b_id": None,
        "adjudicator_id": None,
        "adjudication_status": "pending",
        "guideline_version": DEFAULT_COUNT_GUIDELINE_VERSION,
        "annotation_version": DEFAULT_ANNOTATION_VERSION,
        "leakage_group": f"repo_sha:{row['repository']}::{row['commit_id']}",
        "provisional_tags": ["probable_k1_regular", *_infer_candidate_tags_from_edit_units(row.get("edit_units") or [])],
        "source_fields": {
            "file_count": int(row.get("file_count") or 0),
            "hunk_count": int(row.get("hunk_count") or 0),
            "changed_lines": int(row.get("changed_lines") or 0),
            "path_roles": list(row.get("path_roles") or []),
        },
        "git_diff": diff_text,
        "edit_units": list(row.get("edit_units") or []),
    }


def _build_real_count_candidate_from_real_csv_row(
    row: dict[str, Any],
    *,
    source_type: str,
    current_weak_label: str,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str,
) -> dict[str, Any]:
    repo = str(row.get("repo") or "")
    sha = str(row.get("sha") or "")
    diff_text = str(row.get("git_diff") or "")
    normalized_diff_hash = fingerprint_text(diff_text)
    path_roles = _split_pipe_or_json_field(row.get("path_roles"))
    file_count = _safe_int(row.get("file_count"))
    hunk_count = _safe_int(row.get("hunk_count"))
    changed_lines = _safe_int(row.get("changed_lines"))
    provisional_tags: list[str]
    if source_type == "hard_b":
        provisional_tags = ["probable_k1_hard_single"]
    else:
        estimate = _safe_int(row.get("llm_intent_count_estimate"))
        if estimate >= 4:
            provisional_tags = ["probable_k4_or_complex"]
        elif estimate == 3:
            provisional_tags = ["probable_k3"]
        else:
            provisional_tags = ["probable_k2"]
    provisional_tags.extend(_infer_candidate_tags_from_fields(path_roles, file_count, hunk_count, changed_lines, row))
    return {
        "schema_version": REAL_COUNT_CANDIDATE_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at,
        "sample_id": f"{source_type}::{repo}@{sha}",
        "commit_id": sha,
        "repository": repo,
        "diff_reference": {"repo": repo, "sha": sha, "source_asset": source_type},
        "normalized_diff_hash": normalized_diff_hash,
        "current_weak_label": current_weak_label,
        "source_type": source_type,
        "annotation_status": "pending",
        "annotator_a_exact_k": None,
        "annotator_b_exact_k": None,
        "adjudicated_exact_k": None,
        "annotator_a_id": None,
        "annotator_b_id": None,
        "adjudicator_id": None,
        "adjudication_status": "pending",
        "guideline_version": DEFAULT_COUNT_GUIDELINE_VERSION,
        "annotation_version": DEFAULT_ANNOTATION_VERSION,
        "leakage_group": f"repo_sha:{repo}::{sha}",
        "provisional_tags": list(dict.fromkeys(tag for tag in provisional_tags if tag)),
        "source_fields": {
            "file_count": file_count,
            "hunk_count": hunk_count,
            "changed_lines": changed_lines,
            "path_roles": path_roles,
            "language": str(row.get("language") or ""),
            "dir_count": _safe_int(row.get("dir_count")),
            "top_dirs": str(row.get("top_dirs") or ""),
            "changed_files": str(row.get("changed_files") or ""),
        },
        "git_diff": diff_text,
    }


def _append_real_candidate(
    pool: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    exclusions: list[CandidateExclusion],
    blocked_ids: set[str],
    seen_repo_sha: set[str],
    seen_diff_hash: set[str],
    source_asset: str,
) -> None:
    repo = str(candidate.get("repository") or "")
    commit_id = str(candidate.get("commit_id") or "")
    repo_sha = f"{repo}@{commit_id}" if repo and commit_id else ""
    if not repo or not commit_id:
        exclusions.append(CandidateExclusion(candidate["sample_id"], "missing_repo_or_commit_id", source_asset, repo, commit_id))
        return
    if repo_sha in blocked_ids:
        exclusions.append(CandidateExclusion(candidate["sample_id"], "stage1_v1_official_final_test_blocklist", source_asset, repo, commit_id))
        return
    if repo_sha in seen_repo_sha:
        exclusions.append(CandidateExclusion(candidate["sample_id"], "duplicate_repo_sha", source_asset, repo, commit_id))
        return
    diff_hash = str(candidate.get("normalized_diff_hash") or "")
    if diff_hash and diff_hash in seen_diff_hash:
        exclusions.append(CandidateExclusion(candidate["sample_id"], "duplicate_normalized_diff_hash", source_asset, repo, commit_id))
        return
    if source_asset in {"m_weak", "hard_b"} and not str(candidate.get("git_diff") or "").strip():
        exclusions.append(CandidateExclusion(candidate["sample_id"], "missing_diff", source_asset, repo, commit_id))
        return
    seen_repo_sha.add(repo_sha)
    if diff_hash:
        seen_diff_hash.add(diff_hash)
    pool.append(candidate)


def _assign_train_dev_candidate_splits(rows: list[dict[str, Any]], *, seed: int = 42) -> list[dict[str, Any]]:
    repositories = sorted({str(row["repository"]) for row in rows})
    ranked = sorted(repositories, key=lambda repo: hashlib.sha1(f"{seed}:{repo}".encode("utf-8")).hexdigest())
    dev_cutoff = max(1, round(len(ranked) * 0.2))
    dev_repos = set(ranked[:dev_cutoff])
    payload = []
    for row in rows:
        split_candidate = "dev" if row["repository"] in dev_repos else "train"
        payload.append({**row, "split_candidate": split_candidate})
    return payload


def sample_real_count_pilot_queue(rows: list[dict[str, Any]], *, target_count: int) -> list[dict[str, Any]]:
    target_buckets = [
        ("probable_k1_regular", 50),
        ("probable_k1_hard_single", 40),
        ("probable_k2", 55),
        ("probable_k3", 30),
        ("probable_k4_or_complex", 25),
    ]
    selected: list[dict[str, Any]] = []
    used_sample_ids: set[str] = set()
    bucket_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for tag in row.get("provisional_tags", []):
            bucket_lookup[str(tag)].append(row)
    for tag, quota in target_buckets:
        for row in bucket_lookup.get(tag, []):
            if row["sample_id"] in used_sample_ids:
                continue
            inflated = _inflate_real_count_row_for_annotation(row)
            selected.append(inflated)
            used_sample_ids.add(row["sample_id"])
            if sum(1 for item in selected if tag in item.get("provisional_tags", [])) >= quota:
                break
    if len(selected) < target_count:
        for row in rows:
            if row["sample_id"] in used_sample_ids:
                continue
            selected.append(_inflate_real_count_row_for_annotation(row))
            used_sample_ids.add(row["sample_id"])
            if len(selected) >= target_count:
                break
    return sorted(selected[:target_count], key=lambda item: (item["split_candidate"], item["repository"], item["commit_id"]))


def _inflate_real_count_row_for_annotation(row: dict[str, Any]) -> dict[str, Any]:
    diff_text = str(row.get("git_diff") or "")
    sample_id = str(row["sample_id"])
    edit_units = list(row.get("edit_units") or [])
    if not edit_units and diff_text:
        parsed = parse_unified_diff_to_edit_units(diff_text, repo=str(row["repository"]), sample_id=sample_id)
        edit_units = [
            {
                "unit_id": unit.unit_id,
                "hunk_id": unit.hunk_id,
                "file_path": unit.file_path,
                "file_role": unit.file_role,
                "language": unit.language,
                "patch_text": unit.patch_text,
                "added_lines": list(unit.added_lines),
                "deleted_lines": list(unit.deleted_lines),
                "changed_identifiers": list(unit.identifiers),
            }
            for unit in parsed
        ]
    return {
        **row,
        "normalized_diff": _render_diff_preview(diff_text, max_lines=120),
        "edit_units": edit_units,
        "annotator_a_exact_k": None,
        "annotator_b_exact_k": None,
        "adjudicated_exact_k": None,
        "adjudicator_id": None,
        "adjudication_status": "pending",
        "annotation_history": [],
    }


def sample_real_adjudicated_pilot_candidates(rows: list[dict[str, Any]], *, target_count: int) -> list[dict[str, Any]]:
    bucket_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for tag in row.get("provisional_tags", []):
            bucket_rows[tag].append(row)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag, quota in DEFAULT_REAL_ADJUDICATED_PILOT_STRATA.items():
        count = 0
        for row in bucket_rows.get(tag, []):
            if row["sample_id"] in seen:
                continue
            selected.append(row)
            seen.add(row["sample_id"])
            count += 1
            if count >= quota:
                break
    for row in rows:
        if len(selected) >= target_count:
            break
        if row["sample_id"] in seen:
            continue
        selected.append(row)
        seen.add(row["sample_id"])
    return sorted(selected[:target_count], key=lambda item: (item["repository"], item["commit_id"]))


def sample_real_adjudicated_final_candidate_pool(rows: list[dict[str, Any]], *, target_count: int) -> list[dict[str, Any]]:
    limited = []
    per_repo_counts: Counter[str] = Counter()
    for row in sorted(rows, key=lambda item: (item["repository"], item["commit_id"])):
        repo = str(row["repository"])
        if per_repo_counts[repo] >= 25:
            continue
        limited.append(row)
        per_repo_counts[repo] += 1
        if len(limited) >= target_count:
            break
    return limited


def _inflate_real_candidate_for_annotation(row: dict[str, Any]) -> dict[str, Any]:
    diff_text = str(row.get("git_diff") or "")
    sample_id = str(row["sample_id"])
    parsed = parse_unified_diff_to_edit_units(diff_text, repo=str(row["repository"]), sample_id=sample_id)
    edit_units = [
        {
            "unit_id": unit.unit_id,
            "hunk_id": unit.hunk_id,
            "file_path": unit.file_path,
            "file_role": unit.file_role,
            "language": unit.language,
            "patch_text": unit.patch_text,
            "added_lines": list(unit.added_lines),
            "deleted_lines": list(unit.deleted_lines),
            "changed_identifiers": list(unit.identifiers),
        }
        for unit in parsed
    ]
    return {
        **row,
        "normalized_diff": _render_diff_preview(diff_text, max_lines=120),
        "edit_units": edit_units,
    }


def build_blinded_alignment_packages(
    rows: list[dict[str, Any]],
    *,
    guideline_version: str,
    annotation_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    annotator_a: list[dict[str, Any]] = []
    annotator_b: list[dict[str, Any]] = []
    adjudicator_template: list[dict[str, Any]] = []
    blinding_map_rows: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(rows, key=lambda item: str(item["sample_id"])), start=1):
        public_id = f"pilot_{index:04d}"
        public_payload = {
            "schema_version": REAL_ALIGNMENT_PILOT_PACKAGE_SCHEMA_VERSION,
            "sample_id": public_id,
            "normalized_diff": row["normalized_diff"],
            "edit_units": list(row.get("edit_units") or []),
            "repository_language": str(dict(row.get("source_fields") or {}).get("language") or ""),
            "guideline_version": guideline_version,
            "annotation_version": annotation_version,
            "model_prediction_hidden": True,
            "commit_message_hidden": True,
            "split_hidden": True,
            "allowed_context": {
                "repository": row["repository"],
                "unit_count": len(list(row.get("edit_units") or [])),
            },
        }
        annotator_a.append({**public_payload, "package": "annotator_a"})
        annotator_b.append({**public_payload, "package": "annotator_b"})
        adjudicator_template.append(
            {
                "schema_version": REAL_ALIGNMENT_PILOT_PACKAGE_SCHEMA_VERSION,
                "sample_id": public_id,
                "guideline_version": guideline_version,
                "annotation_version": annotation_version,
                "annotation_a": None,
                "annotation_b": None,
                "adjudicated_annotation": None,
                "adjudication_reason": None,
            }
        )
        blinding_map_rows.append(
            {
                "sample_id": public_id,
                "original_sample_id": row["sample_id"],
                "commit_id": row["commit_id"],
                "repository": row["repository"],
            }
        )
    return annotator_a, annotator_b, adjudicator_template, {
        "schema_version": REAL_ALIGNMENT_PILOT_PACKAGE_SCHEMA_VERSION,
        "rows": blinding_map_rows,
    }


def build_real_adjudicated_candidate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    repo_counts = Counter(str(row.get("repository") or "") for row in rows)
    strata_counts = Counter(tag for row in rows for tag in row.get("provisional_tags", []))
    return {
        "schema_version": REAL_ADJUDICATED_CANDIDATE_SCHEMA_VERSION,
        "row_count": len(rows),
        "repository_count": len(repo_counts),
        "top5_repository_share": (sum(count for _repo, count in repo_counts.most_common(5)) / len(rows)) if rows else 0.0,
        "max_repository_share": (max(repo_counts.values()) / len(rows)) if rows and repo_counts else 0.0,
        "provisional_strata_counts": dict(sorted(strata_counts.items())),
        "formal_ready": False,
    }


def _build_uncovered_strata_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strata_counts = Counter(tag for row in rows for tag in row.get("provisional_tags", []))
    required = {
        "probable_k1_regular",
        "probable_k1_hard_single",
        "probable_k2",
        "probable_k3",
        "probable_k4_or_complex",
        "same_file_multi_intent",
        "background_heavy",
        "source_test",
        "source_docs_config",
        "cross_module",
        "ambiguous_boundary",
        "large_commit",
    }
    uncovered = sorted(tag for tag in required if strata_counts.get(tag, 0) == 0)
    return {"required_strata": sorted(required), "uncovered_strata": uncovered, "formal_ready": not uncovered}


def _build_repository_concentration_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    repo_counts = Counter(str(row.get("repository") or "") for row in rows)
    total = len(rows)
    max_repo_share = (max(repo_counts.values()) / total) if total and repo_counts else 0.0
    top5_share = (sum(count for _repo, count in repo_counts.most_common(5)) / total) if total else 0.0
    return {
        "repository_count": len(repo_counts),
        "max_repository_share": max_repo_share,
        "top5_repository_share": top5_share,
        "passes_single_repository_limit": max_repo_share <= 0.05 if total else False,
        "passes_top5_limit": top5_share <= 0.25 if total else False,
    }


def _infer_candidate_tags_from_edit_units(edit_units: list[dict[str, Any]]) -> list[str]:
    roles = {str(unit.get("file_role") or "unknown") for unit in edit_units}
    file_paths = [str(unit.get("file_path") or "") for unit in edit_units]
    file_count = len(set(file_paths))
    hunk_count = len(edit_units)
    changed_lines = sum(len(list(unit.get("added_lines") or [])) + len(list(unit.get("deleted_lines") or [])) for unit in edit_units)
    source_dirs = {path.split("/", 1)[0] for path in file_paths if "/" in path}
    tags = _infer_candidate_tags_from_fields(sorted(roles), file_count, hunk_count, changed_lines, {"top_dirs": "|".join(sorted(source_dirs))})
    return tags


def _infer_candidate_tags_from_fields(
    path_roles: list[str],
    file_count: int,
    hunk_count: int,
    changed_lines: int,
    row: dict[str, Any],
) -> list[str]:
    roles = {role for role in path_roles if role}
    tags: list[str] = []
    if "source" in roles and "test" in roles:
        tags.append("source_test")
    if "source" in roles and ("docs" in roles or "config" in roles):
        tags.append("source_docs_config")
    if file_count == 1 and hunk_count >= 2:
        tags.append("same_file_multi_intent")
    if any(role in roles for role in ("vendor", "generated", "lockfile")) or any(
        marker in str(row.get("changed_files") or row.get("top_dirs") or "").lower()
        for marker in BACKGROUND_PATH_MARKERS
    ):
        tags.append("background_heavy")
    if file_count >= 4 or hunk_count >= 6 or changed_lines >= 120:
        tags.append("large_commit")
    if _safe_int(row.get("dir_count")) >= 2 or len([item for item in str(row.get("top_dirs") or "").split("|") if item]) >= 2:
        tags.append("cross_module")
    if hunk_count >= 5 and file_count <= 2:
        tags.append("ambiguous_boundary")
    return tags


def _infer_background_candidate_types_from_row(row: dict[str, Any]) -> list[str]:
    tags = set()
    text = f"{row.get('normalized_diff', '')}\n{row.get('commit_id', '')}".lower()
    for marker, label in (
        ("package-lock", "lockfile"),
        ("yarn.lock", "lockfile"),
        ("pnpm-lock", "lockfile"),
        ("import ", "import_sorting"),
        ("generated", "generated"),
        ("vendor", "vendor"),
        ("snapshot", "mechanical_snapshot"),
        ("format", "formatting"),
    ):
        if marker in text:
            tags.add(label)
    if "background_heavy" in set(row.get("provisional_tags") or []):
        tags.add("formatting")
    return sorted(tags) or ["unspecified"]


def _iter_file_paths(row: dict[str, Any]) -> Iterable[str]:
    for unit in list(row.get("edit_units") or []):
        yield str(unit.get("file_path") or "")


def _split_pipe_or_json_field(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value)
    if text.startswith("[") and text.endswith("]"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item)]
    separators = "|" if "|" in text else ","
    return [item.strip() for item in text.split(separators) if item.strip()]


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0
