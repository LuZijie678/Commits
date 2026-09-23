from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl
from code.mica.stage1_v2.family_split import build_family_safe_synthetic_split, canonicalize_candidate_row
from code.mica.stage1_v2.leakage import audit_stage1_v2_leakage
from code.mica.stage1_v2.materialization import utc_now_iso


SYNTHETIC_SCALE_AUDIT_SCHEMA_VERSION = "mica-stage1-v2-synthetic-scale-audit-v1"
SYNTHETIC_TARGET_PLAN_SCHEMA_VERSION = "mica-stage1-v2-synthetic-target-plan-v1"
SYNTHETIC_COMPOSITION_PLAN_SCHEMA_VERSION = "mica-stage1-v2-synthetic-composition-plan-v1"
ATOMIC_SOURCE_REVIEW_QUEUE_SCHEMA_VERSION = "mica-stage1-v2-atomic-source-review-queue-v1"
DEFAULT_FORMAL_SYNTHETIC_TARGETS = {
    "train": {"minimum": 3000, "target_range": [5000, 8000]},
    "dev": {"minimum": 400, "target_range": [500, 800]},
    "synthetic_control_test": {"minimum": 400, "target_range": [500, 800]},
}
DEFAULT_SYNTHETIC_K_SUGGESTION = {"2": 0.6, "3": 0.25, "4": 0.15}
DEFAULT_SYNTHETIC_SOURCE_REUSE_CAP = 3
DEFAULT_SYNTHETIC_REPOSITORY_LIMITS = {
    "train_single_repository_max_fraction": 0.10,
    "dev_single_repository_max_fraction": 0.05,
    "synthetic_control_test_single_repository_max_fraction": 0.05,
}
DEFAULT_ATOMIC_FAMILY_LIMITS = {
    "train_max_fraction": 0.10,
    "dev_max_fraction": 0.05,
    "synthetic_control_test_max_fraction": 0.05,
}


def load_materialized_synthetic_rows(
    *,
    train_path: str | Path,
    dev_path: str | Path,
    control_path: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "train": [canonicalize_candidate_row(row) for row in read_jsonl(train_path)],
        "dev": [canonicalize_candidate_row(row) for row in read_jsonl(dev_path)],
        "synthetic_control_test": [canonicalize_candidate_row(row) for row in read_jsonl(control_path)],
    }


def build_synthetic_scale_audit(
    *,
    rows_by_split: dict[str, list[dict[str, Any]]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    per_split = {split: _summarize_synthetic_rows(rows) for split, rows in sorted(rows_by_split.items())}
    overall_rows = [row for rows in rows_by_split.values() for row in rows]
    overall = _summarize_synthetic_rows(overall_rows)
    representativeness = _build_representativeness_report(rows_by_split)
    return {
        "schema_version": SYNTHETIC_SCALE_AUDIT_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "current_status": {
            "candidate_materialized": True,
            "pipeline_validation_complete": True,
            "scale_insufficient_for_formal_training": True,
            "not_frozen_training_asset": True,
        },
        "overall": overall,
        "per_split": per_split,
        "representativeness": representativeness,
    }


def build_synthetic_scale_gap_report(
    *,
    synthetic_scale_audit: dict[str, Any],
    formal_target_plan: dict[str, Any],
) -> dict[str, Any]:
    per_split_gap: dict[str, Any] = {}
    scale_sufficient = True
    for split_name, policy in dict(formal_target_plan.get("proposed_split_targets") or {}).items():
        current = int(dict(synthetic_scale_audit.get("per_split") or {}).get(split_name, {}).get("record_count") or 0)
        minimum = int(policy.get("minimum") or 0)
        target_range = list(policy.get("target_range") or [minimum, minimum])
        lower_target = int(target_range[0]) if target_range else minimum
        upper_target = int(target_range[-1]) if target_range else minimum
        gap = {
            "current_record_count": current,
            "minimum_required": minimum,
            "target_range": [lower_target, upper_target],
            "missing_to_minimum": max(minimum - current, 0),
            "missing_to_lower_target": max(lower_target - current, 0),
            "missing_to_upper_target": max(upper_target - current, 0),
            "meets_minimum": current >= minimum,
        }
        scale_sufficient = scale_sufficient and gap["meets_minimum"]
        per_split_gap[split_name] = gap
    return {
        "schema_version": SYNTHETIC_SCALE_AUDIT_SCHEMA_VERSION,
        "protocol_version": str(formal_target_plan.get("protocol_version") or ""),
        "current_status": dict(synthetic_scale_audit.get("current_status") or {}),
        "per_split_gap": per_split_gap,
        "synthetic_scale_sufficient": scale_sufficient and not bool(formal_target_plan.get("formal_scale_freeze_blocked")),
        "formal_scale_freeze_blocked": bool(formal_target_plan.get("formal_scale_freeze_blocked")),
        "blocking_reasons": list(formal_target_plan.get("blocking_reasons") or []),
    }


def build_synthetic_formal_target_plan(
    *,
    protocol_spec: dict[str, Any],
    synthetic_scale_audit: dict[str, Any],
    accepted_source_rows: list[dict[str, Any]],
    manual_review_source_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    total_targets = _load_formal_scale_targets(protocol_spec)
    accepted_count = len(accepted_source_rows)
    manual_count = len(manual_review_source_rows)
    current_constructor_supported_k = [2]
    unsupported_required_k = [3, 4]
    accepted_only_capacity = (accepted_count * DEFAULT_SYNTHETIC_SOURCE_REUSE_CAP) // 2
    full_pool_capacity = ((accepted_count + manual_count) * DEFAULT_SYNTHETIC_SOURCE_REUSE_CAP) // 2
    planned_minimum_total = sum(int(item["minimum"]) for item in total_targets.values())
    blocking_reasons = []
    if accepted_only_capacity < planned_minimum_total:
        blocking_reasons.append("accepted_only_atomic_source_capacity_below_minimum_target")
    if unsupported_required_k:
        blocking_reasons.append("k3_k4_construction_not_implemented")
    blocking_reasons.append("required_atomic_sources_need_human_verification")
    return {
        "schema_version": SYNTHETIC_TARGET_PLAN_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "status": "candidate_plan_pending_human_confirmation",
        "current_status": dict(synthetic_scale_audit.get("current_status") or {}),
        "proposed_split_targets": total_targets,
        "proposed_materialization_counts": {
            split: int(policy["minimum"]) for split, policy in total_targets.items()
        },
        "source_reuse_policy": {
            "max_samples_per_atomic_source_per_split": DEFAULT_SYNTHETIC_SOURCE_REUSE_CAP,
            "atomic_family_fraction_caps": dict(DEFAULT_ATOMIC_FAMILY_LIMITS),
            "repository_concentration_limits": dict(DEFAULT_SYNTHETIC_REPOSITORY_LIMITS),
        },
        "suggested_k_distribution": {
            "status": "pending_human_confirmation",
            "suggested_mix": dict(DEFAULT_SYNTHETIC_K_SUGGESTION),
        },
        "same_file_cross_file_policy": {
            "status": "pending_human_confirmation",
            "required_reporting": True,
        },
        "context_mix_policy": {
            "source_test": "pending_human_confirmation",
            "source_docs_config": "pending_human_confirmation",
        },
        "capacity_estimate": {
            "accepted_source_count": accepted_count,
            "manual_review_source_count": manual_count,
            "accepted_only_pair_capacity_at_reuse_cap": accepted_only_capacity,
            "accepted_plus_manual_pair_capacity_at_reuse_cap": full_pool_capacity,
            "planned_minimum_total_samples": planned_minimum_total,
        },
        "constructor_support": {
            "supported_gold_k": current_constructor_supported_k,
            "unsupported_required_gold_k": unsupported_required_k,
            "formal_scale_freeze_blocked": bool(unsupported_required_k),
        },
        "formal_scale_freeze_blocked": True,
        "blocking_reasons": blocking_reasons,
    }


def build_formal_synthetic_composition_plan(
    *,
    accepted_source_rows: list[dict[str, Any]],
    manual_review_source_rows: list[dict[str, Any]],
    formal_target_plan: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    source_rows = [_normalize_source_review_row(row, quality_status="candidate_accepted") for row in accepted_source_rows]
    source_rows.extend(_normalize_source_review_row(row, quality_status="source_quality_unverified") for row in manual_review_source_rows)
    target_counts = dict(formal_target_plan.get("proposed_materialization_counts") or {})
    total_target = sum(int(value) for value in target_counts.values())
    if total_target <= 0:
        raise ValueError("formal_target_plan must define positive proposed_materialization_counts")
    split_ratios = (
        int(target_counts.get("train") or 0) / total_target,
        int(target_counts.get("dev") or 0) / total_target,
        int(target_counts.get("synthetic_control_test") or 0) / total_target,
    )
    source_split = build_family_safe_synthetic_split(source_rows, split_ratios=split_ratios, split_seed=20260724)
    rows_by_split = dict(source_split.get("rows_by_split") or {})
    source_cap = int(dict(formal_target_plan.get("source_reuse_policy") or {}).get("max_samples_per_atomic_source_per_split") or DEFAULT_SYNTHETIC_SOURCE_REUSE_CAP)
    family_caps = dict(dict(formal_target_plan.get("source_reuse_policy") or {}).get("atomic_family_fraction_caps") or DEFAULT_ATOMIC_FAMILY_LIMITS)
    plan_rows_by_split: dict[str, list[dict[str, Any]]] = {}
    required_source_usage: dict[str, dict[str, Any]] = {}
    unresolved_rows: list[dict[str, Any]] = []
    for split_name, split_rows in rows_by_split.items():
        target = int(target_counts.get(split_name) or 0)
        cap_fraction = float(family_caps.get(f"{split_name}_max_fraction") or 0.1)
        family_cap = max(3, int(math.ceil(target * cap_fraction)))
        plan_rows = _build_split_composition_plan(
            split_name=split_name,
            split_rows=split_rows,
            target_count=target,
            max_source_reuse=source_cap,
            family_sample_cap=family_cap,
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            created_at=created_at_value,
        )
        plan_rows_by_split[split_name] = plan_rows
        for row in plan_rows:
            blocking_reasons = list(row.get("blocking_reasons") or [])
            for source_id, quality_status in zip(list(row.get("source_atomic_commit_ids") or []), list(row.get("source_quality_statuses") or [])):
                payload = required_source_usage.setdefault(
                    source_id,
                    {
                        "source_atomic_commit_id": source_id,
                        "atomic_family_id": None,
                        "repositories": set(),
                        "target_splits": set(),
                        "planned_usage_count": 0,
                        "blocking_asset_ids": [],
                        "required_strata": set(),
                        "current_quality_status": quality_status,
                        "manual_review_status": "pending",
                        "human_verified": False,
                    },
                )
                payload["repositories"].add(str(row.get("repository") or ""))
                payload["target_splits"].add(split_name)
                payload["planned_usage_count"] += 1
                payload["blocking_asset_ids"].append(str(row["plan_sample_id"]))
                for strata in list(row.get("required_strata") or []):
                    payload["required_strata"].add(str(strata))
                if quality_status != "candidate_accepted":
                    payload["current_quality_status"] = quality_status
                if quality_status != "human_verified":
                    blocking_reasons.append("source_not_human_verified")
            if row.get("requires_human_source_review"):
                unresolved_rows.append(row)
    projected_summary = _build_projected_split_summary(plan_rows_by_split)
    projected_leakage = audit_stage1_v2_leakage(plan_rows_by_split, near_duplicate_limit=250_000)
    required_atomic_sources = []
    unresolved_atomic_sources = []
    for source_id, payload in sorted(required_source_usage.items()):
        normalized = {
            "schema_version": ATOMIC_SOURCE_REVIEW_QUEUE_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "creation_git_sha": creation_git_sha,
            "created_at": created_at_value,
            "source_atomic_commit_id": source_id,
            "repository": sorted(payload["repositories"])[0] if payload["repositories"] else "",
            "atomic_family_id": payload["atomic_family_id"],
            "current_quality_status": payload["current_quality_status"],
            "planned_usage_count": int(payload["planned_usage_count"]),
            "target_splits": sorted(payload["target_splits"]),
            "required_strata": sorted(payload["required_strata"]),
            "blocking_asset_ids": sorted(payload["blocking_asset_ids"]),
            "manual_review_status": payload["manual_review_status"],
            "reviewer_id": None,
            "review_decision": None,
            "review_reason": None,
            "review_version": "stage1-v2-source-review-v1",
            "human_verified": False,
        }
        required_atomic_sources.append(normalized)
        unresolved_atomic_sources.append(normalized)
    return {
        "schema_version": SYNTHETIC_COMPOSITION_PLAN_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "status": "candidate_plan_pending_human_source_review",
        "formal_synthetic_plan_frozen": False,
        "plan_rows_by_split": plan_rows_by_split,
        "projected_split_summary": projected_summary,
        "projected_leakage_report": projected_leakage,
        "required_atomic_sources": required_atomic_sources,
        "unresolved_atomic_sources": unresolved_atomic_sources,
    }


def build_atomic_source_review_priority_queues(
    *,
    accepted_source_rows: list[dict[str, Any]],
    manual_review_source_rows: list[dict[str, Any]],
    materialized_synthetic_rows_by_split: dict[str, list[dict[str, Any]]],
    formal_composition_plan: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    current_usage = Counter(
        source_id
        for rows in materialized_synthetic_rows_by_split.values()
        for row in rows
        for source_id in list(row.get("source_atomic_commit_ids") or [])
    )
    required_source_rows = {row["source_atomic_commit_id"]: row for row in list(formal_composition_plan.get("required_atomic_sources") or [])}
    all_rows = [_normalize_source_review_row(row, quality_status="candidate_accepted") for row in accepted_source_rows]
    all_rows.extend(_normalize_source_review_row(row, quality_status="source_quality_unverified") for row in manual_review_source_rows)
    critical: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    priority_counts = Counter()
    for row in sorted(all_rows, key=lambda item: str(item.get("source_atomic_commit_id") or "")):
        source_id = str(row.get("source_atomic_commit_id") or "")
        planned = dict(required_source_rows.get(source_id) or {})
        planned_usage_count = int(planned.get("planned_usage_count") or 0)
        current_materialized_usage = int(current_usage.get(source_id, 0))
        priority, blocking_asset_ids = _classify_review_priority(
            current_materialized_usage=current_materialized_usage,
            planned_usage_count=planned_usage_count,
            ambiguity_reasons=list(row.get("reasons") or []),
            required_strata=list(planned.get("required_strata") or []),
        )
        payload = {
            "schema_version": ATOMIC_SOURCE_REVIEW_QUEUE_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "creation_git_sha": creation_git_sha,
            "created_at": created_at_value,
            "source_atomic_commit_id": source_id,
            "atomic_family_id": row.get("atomic_family_id"),
            "repository": str(row.get("repository") or ""),
            "current_quality_status": str(row.get("source_quality_status") or row.get("current_quality_status") or "source_quality_unverified"),
            "planned_usage_count": planned_usage_count,
            "current_materialized_usage_count": current_materialized_usage,
            "target_splits": list(planned.get("target_splits") or []),
            "required_strata": list(planned.get("required_strata") or []),
            "ambiguity_reasons": list(row.get("reasons") or []),
            "review_priority": priority,
            "blocking_asset_ids": blocking_asset_ids,
            "manual_review_status": "pending",
            "reviewer_id": None,
            "review_decision": None,
            "review_reason": None,
            "review_version": "stage1-v2-source-review-v1",
            "human_verified": False,
        }
        priority_counts[priority] += 1
        if priority.startswith("critical"):
            critical.append(payload)
        else:
            deferred.append(payload)
    return {
        "critical_rows": critical,
        "deferred_rows": deferred,
        "summary": {
            "schema_version": ATOMIC_SOURCE_REVIEW_QUEUE_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "creation_git_sha": creation_git_sha,
            "created_at": created_at_value,
            "critical_count": len(critical),
            "deferred_count": len(deferred),
            "priority_counts": dict(sorted(priority_counts.items())),
            "required_atomic_sources_human_verified": False,
        },
    }


def materialize_synthetic_scale_and_review_assets(
    *,
    protocol_spec: dict[str, Any],
    train_path: str | Path,
    dev_path: str | Path,
    control_path: str | Path,
    accepted_atomic_sources_path: str | Path,
    manual_review_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    protocol_version = str(protocol_spec.get("protocol_version") or "stage1-v2-protocol")
    rows_by_split = load_materialized_synthetic_rows(train_path=train_path, dev_path=dev_path, control_path=control_path)
    accepted_rows = [canonicalize_candidate_row(row) for row in read_jsonl(accepted_atomic_sources_path)]
    manual_review_rows = [canonicalize_candidate_row(row) for row in read_jsonl(manual_review_path)]
    synthetic_scale_audit = build_synthetic_scale_audit(
        rows_by_split=rows_by_split,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at_value,
    )
    target_plan = build_synthetic_formal_target_plan(
        protocol_spec=protocol_spec,
        synthetic_scale_audit=synthetic_scale_audit,
        accepted_source_rows=accepted_rows,
        manual_review_source_rows=manual_review_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at_value,
    )
    gap_report = build_synthetic_scale_gap_report(
        synthetic_scale_audit=synthetic_scale_audit,
        formal_target_plan=target_plan,
    )
    composition_plan = build_formal_synthetic_composition_plan(
        accepted_source_rows=accepted_rows,
        manual_review_source_rows=manual_review_rows,
        formal_target_plan=target_plan,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at_value,
    )
    review_queues = build_atomic_source_review_priority_queues(
        accepted_source_rows=accepted_rows,
        manual_review_source_rows=manual_review_rows,
        materialized_synthetic_rows_by_split=rows_by_split,
        formal_composition_plan=composition_plan,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at_value,
    )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    audit_path = output_root_path / "synthetic_scale_audit.json"
    gap_path = output_root_path / "synthetic_scale_gap_report.json"
    target_path = output_root_path / "synthetic_formal_target_plan.json"
    composition_plan_path = output_root_path / "formal_synthetic_composition_plan.jsonl"
    required_sources_path = output_root_path / "required_atomic_sources.jsonl"
    unresolved_sources_path = output_root_path / "unresolved_atomic_sources.jsonl"
    projected_summary_path = output_root_path / "projected_split_summary.json"
    projected_leakage_path = output_root_path / "projected_leakage_report.json"
    critical_review_path = output_root_path.parent / "atomic_source_pool" / "atomic_source_review_critical.jsonl"
    deferred_review_path = output_root_path.parent / "atomic_source_pool" / "atomic_source_review_deferred.jsonl"
    review_summary_path = output_root_path.parent / "atomic_source_pool" / "atomic_source_review_priority_summary.json"
    write_json(audit_path, synthetic_scale_audit)
    write_json(gap_path, gap_report)
    write_json(target_path, target_plan)
    write_jsonl(composition_plan_path, _flatten_plan_rows(composition_plan["plan_rows_by_split"]))
    write_jsonl(required_sources_path, composition_plan["required_atomic_sources"])
    write_jsonl(unresolved_sources_path, composition_plan["unresolved_atomic_sources"])
    write_json(projected_summary_path, composition_plan["projected_split_summary"])
    write_json(projected_leakage_path, composition_plan["projected_leakage_report"])
    write_jsonl(critical_review_path, review_queues["critical_rows"])
    write_jsonl(deferred_review_path, review_queues["deferred_rows"])
    write_json(review_summary_path, review_queues["summary"])
    return {
        "synthetic_scale_audit_path": str(audit_path),
        "synthetic_scale_gap_report_path": str(gap_path),
        "synthetic_formal_target_plan_path": str(target_path),
        "formal_synthetic_composition_plan_path": str(composition_plan_path),
        "required_atomic_sources_path": str(required_sources_path),
        "unresolved_atomic_sources_path": str(unresolved_sources_path),
        "projected_split_summary_path": str(projected_summary_path),
        "projected_leakage_report_path": str(projected_leakage_path),
        "critical_review_path": str(critical_review_path),
        "deferred_review_path": str(deferred_review_path),
        "review_summary_path": str(review_summary_path),
        "synthetic_scale_audit": synthetic_scale_audit,
        "synthetic_formal_target_plan": target_plan,
        "review_summary": review_queues["summary"],
    }


def _summarize_synthetic_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(
        source_id
        for row in rows
        for source_id in list(row.get("source_atomic_commit_ids") or [])
    )
    family_counts = Counter(str(row.get("atomic_family_id") or "") for row in rows if str(row.get("atomic_family_id") or ""))
    repository_counts = Counter(str(row.get("repository") or "") for row in rows)
    language_counts = Counter()
    file_role_counts = Counter()
    same_file_count = 0
    cross_file_count = 0
    source_test_count = 0
    source_docs_config_count = 0
    construction_template_counts = Counter(str(row.get("construction_version") or row.get("construction_group") or "unknown") for row in rows)
    edit_unit_counts: list[int] = []
    k_counts = Counter(str(row.get("gold_k") or row.get("gold_count") or "unknown") for row in rows)
    for row in rows:
        roles = set()
        languages = set()
        file_paths = set()
        units = list(row.get("edit_units") or [])
        edit_unit_counts.append(len(units))
        for unit in units:
            if not isinstance(unit, dict):
                continue
            role = str(unit.get("file_role") or "unknown")
            language = str(unit.get("language") or "").strip()
            file_path = str(unit.get("file_path") or "")
            roles.add(role)
            file_paths.add(file_path)
            if language:
                languages.add(language)
        if len(file_paths) <= 1:
            same_file_count += 1
        else:
            cross_file_count += 1
        if "source" in roles and "test" in roles:
            source_test_count += 1
        if "source" in roles and roles.intersection({"docs", "config"}):
            source_docs_config_count += 1
        for role in roles:
            file_role_counts[role] += 1
        for language in languages:
            language_counts[language] += 1
    return {
        "record_count": len(rows),
        "unique_atomic_source_count": len(source_counts),
        "unique_atomic_family_count": len(family_counts),
        "repository_count": len(repository_counts),
        "gold_k_distribution": dict(sorted(k_counts.items())),
        "language_distribution": dict(sorted(language_counts.items())),
        "file_role_composition": dict(sorted(file_role_counts.items())),
        "same_file_count": same_file_count,
        "cross_file_count": cross_file_count,
        "source_test_count": source_test_count,
        "source_docs_config_count": source_docs_config_count,
        "source_reuse_degree": _counter_summary(source_counts),
        "atomic_family_reuse_degree": _counter_summary(family_counts),
        "max_samples_per_atomic_source": max(source_counts.values()) if source_counts else 0,
        "max_samples_per_atomic_family": max(family_counts.values()) if family_counts else 0,
        "construction_template_distribution": dict(sorted(construction_template_counts.items())),
        "edit_unit_count_distribution": _numeric_distribution(edit_unit_counts),
        "top5_repository_share": (sum(count for _repo, count in repository_counts.most_common(5)) / len(rows)) if rows else 0.0,
        "max_repository_share": (max(repository_counts.values()) / len(rows)) if rows and repository_counts else 0.0,
    }


def _build_representativeness_report(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    pairs = {}
    split_names = sorted(rows_by_split)
    for index, left_split in enumerate(split_names):
        left_summary = _summarize_synthetic_rows(rows_by_split[left_split])
        for right_split in split_names[index + 1 :]:
            right_summary = _summarize_synthetic_rows(rows_by_split[right_split])
            pair_key = f"{left_split}__vs__{right_split}"
            pairs[pair_key] = {
                "k_distribution_tvd": _distribution_tvd(
                    dict(left_summary.get("gold_k_distribution") or {}),
                    dict(right_summary.get("gold_k_distribution") or {}),
                ),
                "language_distribution_tvd": _distribution_tvd(
                    dict(left_summary.get("language_distribution") or {}),
                    dict(right_summary.get("language_distribution") or {}),
                ),
                "file_role_tvd": _distribution_tvd(
                    dict(left_summary.get("file_role_composition") or {}),
                    dict(right_summary.get("file_role_composition") or {}),
                ),
                "same_file_fraction_delta": round(
                    _safe_fraction(int(left_summary.get("same_file_count") or 0), int(left_summary.get("record_count") or 0))
                    - _safe_fraction(int(right_summary.get("same_file_count") or 0), int(right_summary.get("record_count") or 0)),
                    6,
                ),
                "source_test_fraction_delta": round(
                    _safe_fraction(int(left_summary.get("source_test_count") or 0), int(left_summary.get("record_count") or 0))
                    - _safe_fraction(int(right_summary.get("source_test_count") or 0), int(right_summary.get("record_count") or 0)),
                    6,
                ),
            }
    return {
        "pairwise_split_representativeness": pairs,
    }


def _load_formal_scale_targets(protocol_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    custom = dict(protocol_spec.get("synthetic_formal_scale_targets") or {})
    if custom:
        return custom
    return {split: dict(value) for split, value in DEFAULT_FORMAL_SYNTHETIC_TARGETS.items()}


def _normalize_source_review_row(row: dict[str, Any], *, quality_status: str) -> dict[str, Any]:
    payload = canonicalize_candidate_row(row)
    payload["source_quality_status"] = str(payload.get("source_quality_status") or quality_status)
    payload["source_atomic_commit_id"] = str(
        payload.get("source_atomic_commit_id")
        or next(iter(list(payload.get("source_atomic_commit_ids") or [])), "")
    )
    return payload


def _build_split_composition_plan(
    *,
    split_name: str,
    split_rows: list[dict[str, Any]],
    target_count: int,
    max_source_reuse: int,
    family_sample_cap: int,
    creation_git_sha: str,
    protocol_version: str,
    created_at: str,
) -> list[dict[str, Any]]:
    expanded = []
    for row in sorted(split_rows, key=lambda item: str(item.get("source_atomic_commit_id") or item.get("sample_id") or "")):
        for slot in range(max_source_reuse):
            expanded.append(
                {
                    **row,
                    "_reuse_slot": slot,
                    "_rank": hashlib.sha1(f"{split_name}:{row.get('source_atomic_commit_id')}:{slot}".encode("utf-8")).hexdigest(),
                }
            )
    expanded.sort(key=lambda item: str(item["_rank"]))
    family_usage = Counter()
    source_usage = Counter()
    plan_rows: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for left_index, left in enumerate(expanded):
        if len(plan_rows) >= target_count:
            break
        if left_index in consumed:
            continue
        left_source = str(left.get("source_atomic_commit_id") or "")
        left_family = str(left.get("atomic_family_id") or "")
        if source_usage[left_source] >= max_source_reuse:
            continue
        if left_family and family_usage[left_family] >= family_sample_cap:
            continue
        partner_index = _find_partner_index(
            expanded,
            left_index=left_index,
            consumed=consumed,
            source_usage=source_usage,
            family_usage=family_usage,
            max_source_reuse=max_source_reuse,
            family_sample_cap=family_sample_cap,
            preferred_family=str(left.get("atomic_family_id") or ""),
        )
        if partner_index is None:
            continue
        right = expanded[partner_index]
        consumed.add(left_index)
        consumed.add(partner_index)
        left_source = str(left.get("source_atomic_commit_id") or "")
        right_source = str(right.get("source_atomic_commit_id") or "")
        left_family = str(left.get("atomic_family_id") or "")
        right_family = str(right.get("atomic_family_id") or "")
        source_usage[left_source] += 1
        source_usage[right_source] += 1
        if left_family:
            family_usage[left_family] += 1
        if right_family:
            family_usage[right_family] += 1
        required_strata = sorted(_infer_source_review_strata([left, right]))
        plan_rows.append(
            {
                "schema_version": SYNTHETIC_COMPOSITION_PLAN_SCHEMA_VERSION,
                "protocol_version": protocol_version,
                "creation_git_sha": creation_git_sha,
                "created_at": created_at,
                "plan_sample_id": f"{split_name}::formal_plan::{len(plan_rows) + 1:06d}",
                "split": split_name,
                "repository": str(left.get("repository") or right.get("repository") or ""),
                "source_atomic_commit_ids": sorted({left_source, right_source}),
                "atomic_family_ids": sorted({family for family in (left_family, right_family) if family}),
                "source_quality_statuses": [
                    str(left.get("source_quality_status") or "source_quality_unverified"),
                    str(right.get("source_quality_status") or "source_quality_unverified"),
                ],
                "planned_gold_k": 2,
                "planned_construction_template": "same_repo_multi_round_robin_v1_candidate",
                "required_strata": required_strata,
                "requires_human_source_review": True,
                "blocking_reasons": [
                    "source_not_human_verified",
                    "current_constructor_supports_only_k2",
                ],
                "source_reuse_slots": {
                    left_source: source_usage[left_source],
                    right_source: source_usage[right_source],
                },
            }
        )
    return plan_rows


def _find_partner_index(
    expanded: list[dict[str, Any]],
    *,
    left_index: int,
    consumed: set[int],
    source_usage: Counter[str],
    family_usage: Counter[str],
    max_source_reuse: int,
    family_sample_cap: int,
    preferred_family: str,
) -> int | None:
    left = expanded[left_index]
    left_source = str(left.get("source_atomic_commit_id") or "")
    candidates: list[int] = []
    fallback: list[int] = []
    for right_index in range(left_index + 1, len(expanded)):
        if right_index in consumed:
            continue
        right = expanded[right_index]
        right_source = str(right.get("source_atomic_commit_id") or "")
        right_family = str(right.get("atomic_family_id") or "")
        if not right_source or right_source == left_source:
            continue
        if source_usage[right_source] >= max_source_reuse:
            continue
        if right_family and family_usage[right_family] >= family_sample_cap:
            continue
        if preferred_family and right_family and right_family != preferred_family:
            candidates.append(right_index)
        else:
            fallback.append(right_index)
    if candidates:
        return candidates[0]
    if fallback:
        return fallback[0]
    return None


def _classify_review_priority(
    *,
    current_materialized_usage: int,
    planned_usage_count: int,
    ambiguity_reasons: list[str],
    required_strata: list[str],
) -> tuple[str, list[str]]:
    if current_materialized_usage > 0 and planned_usage_count > 0:
        return "critical_current_and_formal", []
    if current_materialized_usage > 0:
        return "critical_current_materialized_use", []
    if planned_usage_count > 0:
        return "critical_formal_scale_required", []
    if required_strata:
        return "critical_strata_support", []
    if ambiguity_reasons:
        return "critical_high_ambiguity", []
    return "deferred_not_currently_blocking", []


def _flatten_plan_rows(rows_by_split: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for split in sorted(rows_by_split) for row in rows_by_split[split]]


def _build_projected_split_summary(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summary = {}
    for split_name, rows in sorted(rows_by_split.items()):
        repo_counts = Counter(str(row.get("repository") or "") for row in rows)
        summary[split_name] = {
            "planned_record_count": len(rows),
            "repository_count": len(repo_counts),
            "max_repository_share": (max(repo_counts.values()) / len(rows)) if rows and repo_counts else 0.0,
            "top5_repository_share": (sum(count for _repo, count in repo_counts.most_common(5)) / len(rows)) if rows else 0.0,
            "planned_k_distribution": dict(sorted(Counter(str(row.get("planned_gold_k") or "") for row in rows).items())),
            "required_strata_counts": dict(sorted(Counter(tag for row in rows for tag in row.get("required_strata", [])).items())),
            "supports_only_k2": True,
        }
    return summary


def _infer_source_review_strata(rows: list[dict[str, Any]]) -> set[str]:
    strata: set[str] = set()
    roles = set()
    file_paths = set()
    for row in rows:
        roles.update(str(role) for role in list(row.get("path_roles") or []) if str(role))
        for unit in list(row.get("edit_units") or []):
            if isinstance(unit, dict):
                roles.add(str(unit.get("file_role") or ""))
                file_paths.add(str(unit.get("file_path") or ""))
    if "source" in roles and "test" in roles:
        strata.add("source_test")
    if "source" in roles and roles.intersection({"docs", "config"}):
        strata.add("source_docs_config")
    if len(file_paths) > 1:
        strata.add("cross_file")
    if len(file_paths) == 1:
        strata.add("same_file")
    if roles.intersection({"generated", "vendor", "lockfile"}):
        strata.add("background_or_support_risk")
    return strata


def _counter_summary(counter: Counter[str]) -> dict[str, Any]:
    counts = list(counter.values())
    return {
        "unique_count": len(counter),
        "max": max(counts) if counts else 0,
        "mean": round(sum(counts) / len(counts), 6) if counts else 0.0,
        "top10": [
            {"key": key, "count": count}
            for key, count in counter.most_common(10)
        ],
    }


def _numeric_distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None, "mean": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "count": len(values),
        "min": ordered[0],
        "median": median,
        "max": ordered[-1],
        "mean": round(sum(values) / len(values), 6),
    }


def _distribution_tvd(left: dict[str, Any], right: dict[str, Any]) -> float:
    keys = sorted(set(left) | set(right))
    left_total = sum(float(left.get(key) or 0.0) for key in keys)
    right_total = sum(float(right.get(key) or 0.0) for key in keys)
    if left_total <= 0.0 or right_total <= 0.0:
        return 1.0
    return round(
        0.5
        * sum(
            abs((float(left.get(key) or 0.0) / left_total) - (float(right.get(key) or 0.0) / right_total))
            for key in keys
        ),
        6,
    )


def _safe_fraction(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return value / total
