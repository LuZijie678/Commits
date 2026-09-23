from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from code.mica.eval.attribution_metrics import pairwise_f1_from_assignments
from code.mica.stage1_v2.audit_log import ANNOTATION_AUDIT_LOG_SCHEMA_VERSION
from code.mica.stage1_v2.materialization import (
    DEFAULT_ANNOTATION_VERSION,
    DEFAULT_COUNT_GUIDELINE_VERSION,
    DEFAULT_PILOT_GUIDELINE_VERSION,
    REAL_ALIGNMENT_PILOT_PACKAGE_SCHEMA_VERSION,
    utc_now_iso,
)
from code.mica.stage1_v2.real_adjudicated import summarize_real_adjudicated_agreement


ANNOTATION_OVERLAP_SCHEMA_VERSION = "mica-stage1-v2-annotation-overlap-v1"
UNIFIED_ANNOTATION_INDEX_SCHEMA_VERSION = "mica-stage1-v2-unified-annotation-index-v1"
ANNOTATOR_REGISTRY_SCHEMA_VERSION = "mica-stage1-v2-annotator-registry-v1"
ROLE_ASSIGNMENT_SCHEMA_VERSION = "mica-stage1-v2-role-assignment-v1"
ROLE_CONFLICT_SCHEMA_VERSION = "mica-stage1-v2-role-conflict-report-v1"
QUALIFICATION_EXECUTION_SCHEMA_VERSION = "mica-stage1-v2-qualification-execution-v1"
CALIBRATION_ROUND_SCHEMA_VERSION = "mica-stage1-v2-calibration-round-v1"
CALIBRATION_REPORT_SCHEMA_VERSION = "mica-stage1-v2-calibration-agreement-v1"
ANNOTATION_CAMPAIGN_SCHEMA_VERSION = "mica-stage1-v2-annotation-campaign-v1"
ANNOTATION_PROGRESS_SCHEMA_VERSION = "mica-stage1-v2-annotation-progress-v1"
ANNOTATION_AUDIT_LOG_TEMPLATE_SCHEMA_VERSION = "mica-stage1-v2-annotation-audit-log-template-v1"
FORMAL_ANNOTATION_ROLES = {"annotator_a", "annotator_b", "adjudicator", "independent_blind_reviewer"}
FORBIDDEN_ACTOR_TYPES = {"llm", "codex", "ai", "ai_agent", "model"}
BACKGROUND_ONLY_LABELS = {"background"}
UNCERTAIN_STYLE_LABELS = {"shared_support", "uncertain", "mixed"}
CALIBRATION_REQUIRED_TAGS = [
    "probable_k1_regular",
    "probable_k1_hard_single",
    "probable_k2",
    "probable_k3",
    "probable_k4_or_complex",
    "same_file_multi_intent",
    "source_test",
    "source_docs_config",
    "background_heavy",
    "ambiguous_boundary",
]
CALIBRATION_TARGET_SIZE = 30
REAL_COUNT_BATCH_SIZE = 50
REAL_ALIGNMENT_BATCH_SIZES = [35, 35]
BACKGROUND_BATCH_SIZE = 40
QUALIFICATION_THRESHOLDS = {
    "exact_k_accuracy": 0.85,
    "pairwise_partition_f1": 0.80,
    "background_classification_f1": 0.85,
}


def build_annotation_queue_overlap_report(
    *,
    real_count_rows: list[dict[str, Any]],
    real_alignment_rows: list[dict[str, Any]],
    background_rows: list[dict[str, Any]],
    atomic_source_review_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    queue_maps = {
        "real_count_pilot": _build_queue_index(real_count_rows, queue_name="real_count_pilot"),
        "real_alignment_pilot": _build_queue_index(real_alignment_rows, queue_name="real_alignment_pilot"),
        "background_pilot": _build_queue_index(background_rows, queue_name="background_pilot"),
        "atomic_source_review": _build_queue_index(atomic_source_review_rows, queue_name="atomic_source_review"),
    }
    pairwise_overlap: dict[str, Any] = {}
    queue_names = list(queue_maps)
    for index, left_name in enumerate(queue_names):
        left_keys = set(queue_maps[left_name]["commit_index"])
        for right_name in queue_names[index + 1 :]:
            right_keys = set(queue_maps[right_name]["commit_index"])
            overlap = sorted(left_keys & right_keys)
            pairwise_overlap[f"{left_name}__vs__{right_name}"] = {
                "overlap_count": len(overlap),
                "example_commit_keys": overlap[:10],
            }
    unique_commit_keys = sorted({key for queue in queue_maps.values() for key in queue["commit_index"]})
    raw_task_total = sum(int(queue["row_count"]) for queue in queue_maps.values())
    return {
        "schema_version": ANNOTATION_OVERLAP_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "queue_row_counts": {name: int(payload["row_count"]) for name, payload in queue_maps.items()},
        "queue_unique_commit_counts": {name: len(payload["commit_index"]) for name, payload in queue_maps.items()},
        "pairwise_commit_overlap": pairwise_overlap,
        "raw_task_total": raw_task_total,
        "unique_commit_count": len(unique_commit_keys),
        "unique_commit_keys": unique_commit_keys,
    }


def build_unified_pilot_annotation_index(
    *,
    real_count_rows: list[dict[str, Any]],
    real_alignment_rows: list[dict[str, Any]],
    background_rows: list[dict[str, Any]],
    atomic_source_review_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> list[dict[str, Any]]:
    created_at_value = created_at or utc_now_iso()
    grouped: dict[str, dict[str, Any]] = {}
    queue_rows = (
        ("real_count_pilot", real_count_rows),
        ("real_alignment_pilot", real_alignment_rows),
        ("background_pilot", background_rows),
        ("atomic_source_review", atomic_source_review_rows),
    )
    for queue_name, rows in queue_rows:
        for row in rows:
            commit_key = _commit_key(row)
            payload = grouped.setdefault(
                commit_key,
                {
                    "schema_version": UNIFIED_ANNOTATION_INDEX_SCHEMA_VERSION,
                    "protocol_version": protocol_version,
                    "creation_git_sha": creation_git_sha,
                    "created_at": created_at_value,
                    "unified_annotation_id": f"unified::{hashlib.sha1(commit_key.encode('utf-8')).hexdigest()[:16]}",
                    "commit_key": commit_key,
                    "commit_id": str(row.get("commit_id") or ""),
                    "repository": str(row.get("repository") or row.get("repo") or ""),
                    "queue_sample_ids": defaultdict(list),
                    "source_atomic_commit_ids": set(),
                    "derivable_assets": {
                        "real_count_exact_k": False,
                        "real_alignment_partition": False,
                        "background_evaluation": False,
                    },
                    "derivation_requirements": {
                        "real_count_exact_k": [
                            "human_double_annotation",
                            "human_adjudication",
                            "exact_k_entered_by_humans",
                        ],
                        "real_alignment_partition": [
                            "human_double_annotation",
                            "human_adjudication",
                            "unit_level_intent_labels_entered_by_humans",
                        ],
                        "background_evaluation": [
                            "human_double_annotation",
                            "human_adjudication",
                            "background_labels_entered_by_humans",
                        ],
                    },
                    "weak_labels_forbidden_as_gold": True,
                    "commit_message_forbidden_as_gold": True,
                    "annotation_status": "annotation_pending",
                },
            )
            payload["queue_sample_ids"][queue_name].append(str(row.get("sample_id") or row.get("source_atomic_commit_id") or commit_key))
            for source_id in list(row.get("source_atomic_commit_ids") or []):
                payload["source_atomic_commit_ids"].add(str(source_id))
            if queue_name == "real_alignment_pilot":
                payload["derivable_assets"]["real_alignment_partition"] = True
                payload["derivable_assets"]["real_count_exact_k"] = True
                payload["derivable_assets"]["background_evaluation"] = True
            elif queue_name == "real_count_pilot":
                payload["derivable_assets"]["real_count_exact_k"] = True
            elif queue_name == "background_pilot":
                payload["derivable_assets"]["background_evaluation"] = True
    normalized: list[dict[str, Any]] = []
    for commit_key, payload in sorted(grouped.items()):
        queue_sample_ids = {name: sorted(values) for name, values in payload["queue_sample_ids"].items()}
        normalized.append(
            {
                **payload,
                "queue_sample_ids": queue_sample_ids,
                "source_atomic_commit_ids": sorted(payload["source_atomic_commit_ids"]),
                "human_workload_group": _infer_workload_group(queue_sample_ids),
            }
        )
    return normalized


def build_deduplicated_human_workload_report(
    *,
    unified_index_rows: list[dict[str, Any]],
    overlap_report: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    raw_task_total = int(overlap_report.get("raw_task_total") or 0)
    full_alignment_anchor = [
        row for row in unified_index_rows if dict(row.get("derivable_assets") or {}).get("real_alignment_partition")
    ]
    count_reusable = sum(1 for row in full_alignment_anchor if dict(row.get("queue_sample_ids") or {}).get("real_count_pilot"))
    background_reusable = sum(1 for row in full_alignment_anchor if dict(row.get("queue_sample_ids") or {}).get("background_pilot"))
    atomic_review_tasks = sum(1 for row in unified_index_rows if dict(row.get("queue_sample_ids") or {}).get("atomic_source_review"))
    remaining_count_only = sum(1 for row in unified_index_rows if row.get("human_workload_group") == "count_only")
    remaining_background_only = sum(1 for row in unified_index_rows if row.get("human_workload_group") == "background_only")
    unique_real_commit_count = sum(
        1
        for row in unified_index_rows
        if dict(row.get("queue_sample_ids") or {}).get("real_count_pilot")
        or dict(row.get("queue_sample_ids") or {}).get("real_alignment_pilot")
        or dict(row.get("queue_sample_ids") or {}).get("background_pilot")
    )
    return {
        "schema_version": ANNOTATION_OVERLAP_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "raw_total_tasks": raw_task_total,
        "unique_commit_count": len(unified_index_rows),
        "unique_real_commit_annotation_count": unique_real_commit_count,
        "unique_atomic_source_review_count": atomic_review_tasks,
        "full_alignment_anchor_count": len(full_alignment_anchor),
        "count_reusable_from_full_alignment": count_reusable,
        "background_reusable_from_full_alignment": background_reusable,
        "remaining_count_only_tasks": remaining_count_only,
        "remaining_background_only_tasks": remaining_background_only,
        "deduplicated_real_annotation_count": len(full_alignment_anchor) + remaining_count_only + remaining_background_only,
        "human_workload_group_counts": dict(
            sorted(Counter(str(row.get("human_workload_group") or "unknown") for row in unified_index_rows).items())
        ),
    }


def build_annotator_registry_template(
    *,
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ANNOTATOR_REGISTRY_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at or utc_now_iso(),
        "registry_status": "human_staffing_incomplete",
        "allowed_roles": sorted(FORMAL_ANNOTATION_ROLES | {"source_reviewer"}),
        "forbidden_actor_types": sorted(FORBIDDEN_ACTOR_TYPES),
        "actors": [],
    }


def build_annotation_campaign_plan(
    *,
    real_count_rows: list[dict[str, Any]],
    real_alignment_rows: list[dict[str, Any]],
    background_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
    seed: int = 20260724,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    calibration = build_calibration_round_assets(
        pilot_rows=real_alignment_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at_value,
        seed=seed,
    )
    calibration_sample_ids = {str(row["original_sample_id"]) for row in calibration["blinding_map"]["rows"]}
    remaining_alignment = [
        row for row in _stable_order(real_alignment_rows, seed=seed + 1) if str(row.get("sample_id") or "") not in calibration_sample_ids
    ]
    alignment_batches = _chunk_rows(remaining_alignment, REAL_ALIGNMENT_BATCH_SIZES)
    real_count_batches = _chunk_rows(_stable_order(real_count_rows, seed=seed + 2), [REAL_COUNT_BATCH_SIZE] * 4)
    alignment_commit_keys = {_commit_key(row) for row in real_alignment_rows}
    background_unique_rows = []
    seen_background = set()
    for row in _stable_order(background_rows, seed=seed + 3):
        commit_key = _commit_key(row)
        if commit_key in alignment_commit_keys or commit_key in seen_background:
            continue
        background_unique_rows.append(row)
        seen_background.add(commit_key)
    background_batches = _chunk_rows(background_unique_rows, [BACKGROUND_BATCH_SIZE] * max(1, (len(background_unique_rows) + BACKGROUND_BATCH_SIZE - 1) // BACKGROUND_BATCH_SIZE))
    batches = [
        _build_batch_record(
            campaign_id="real_alignment_pilot",
            batch_id="calibration_round_1",
            rows=calibration["selected_rows"],
            guideline_version=DEFAULT_PILOT_GUIDELINE_VERSION,
            batch_type="calibration",
            required_roles=["annotator_a", "annotator_b", "adjudicator"],
        )
    ]
    for index, rows in enumerate(alignment_batches, start=2):
        batches.append(
            _build_batch_record(
                campaign_id="real_alignment_pilot",
                batch_id=f"pilot_batch_{index}",
                rows=rows,
                guideline_version=DEFAULT_PILOT_GUIDELINE_VERSION,
                batch_type="pilot_alignment",
                required_roles=["annotator_a", "annotator_b", "adjudicator"],
            )
        )
    for index, rows in enumerate(real_count_batches, start=1):
        batches.append(
            _build_batch_record(
                campaign_id="real_count_pilot",
                batch_id=f"pilot_batch_{index:02d}",
                rows=rows,
                guideline_version=DEFAULT_COUNT_GUIDELINE_VERSION,
                batch_type="pilot_count",
                required_roles=["annotator_a", "annotator_b", "adjudicator"],
            )
        )
    for index, rows in enumerate(background_batches, start=1):
        batches.append(
            _build_batch_record(
                campaign_id="background_pilot",
                batch_id=f"pilot_batch_{index:02d}",
                rows=rows,
                guideline_version=DEFAULT_PILOT_GUIDELINE_VERSION,
                batch_type="pilot_background",
                required_roles=["annotator_a", "annotator_b", "adjudicator"],
            )
        )
    batches.append(
        {
            "campaign_id": "real_alignment_blind_review",
            "batch_id": "blind_review_pending",
            "batch_type": "blind_review",
            "sample_count": 0,
            "sample_ids": [],
            "guideline_version": DEFAULT_PILOT_GUIDELINE_VERSION,
            "required_roles": ["independent_blind_reviewer"],
            "status": "pending_generation",
        }
    )
    total_samples = sum(
        int(batch.get("sample_count") or 0)
        for batch in batches
        if batch.get("batch_type") != "blind_review"
    )
    return {
        "schema_version": ANNOTATION_CAMPAIGN_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "campaign_id": "stage1_v2_annotation_campaign",
        "status": "pending_human_staffing",
        "batch_count": len(batches),
        "total_samples": total_samples,
        "completed_samples": 0,
        "blocked_reasons": [
            "human_staffing_incomplete",
            "annotators_not_qualified",
            "calibration_round_not_complete",
        ],
        "batches": batches,
        "calibration_sample_ids": sorted(calibration_sample_ids),
    }


def build_campaign_role_assignment(
    *,
    campaign_manifest: dict[str, Any],
    annotator_registry: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    _ = annotator_registry
    assignments = []
    for batch in list(campaign_manifest.get("batches") or []):
        assignments.append(
            {
                "campaign_id": str(batch.get("campaign_id") or ""),
                "batch_id": str(batch.get("batch_id") or ""),
                "required_roles": list(batch.get("required_roles") or []),
                "assignments": [
                    {
                        "role": role,
                        "assigned_actor_id": None,
                        "assignment_status": "pending_human_staffing",
                    }
                    for role in list(batch.get("required_roles") or [])
                ],
            }
        )
    return {
        "schema_version": ROLE_ASSIGNMENT_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at or utc_now_iso(),
        "campaign_assignments": assignments,
    }


def build_role_conflict_report(
    *,
    annotator_registry: dict[str, Any],
    role_assignment: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
    llm_annotation_amendment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    actor_by_id = {str(actor.get("actor_id") or ""): actor for actor in list(annotator_registry.get("actors") or [])}
    amendment_id = str((llm_annotation_amendment or {}).get("amendment_id") or "")
    amendment_permitted_ids = {
        str(actor_id)
        for actor_id in list((llm_annotation_amendment or {}).get("permitted_actor_ids") or [])
        if str(actor_id)
    }
    human_staffing_incomplete = False
    conflicts: list[dict[str, Any]] = []
    forbidden_assignments: list[dict[str, Any]] = []
    amendment_permitted_assignments: list[dict[str, Any]] = []
    for batch in list(role_assignment.get("campaign_assignments") or []):
        assigned: dict[str, str] = {}
        for assignment in list(batch.get("assignments") or []):
            role = str(assignment.get("role") or "")
            actor_id = assignment.get("assigned_actor_id")
            if not actor_id:
                human_staffing_incomplete = True
                continue
            actor_id_text = str(actor_id)
            actor = dict(actor_by_id.get(actor_id_text) or {})
            actor_type = str(actor.get("actor_type") or "").lower()
            nonhuman = (
                actor_type in FORBIDDEN_ACTOR_TYPES
                or any(token in actor_id_text.lower() for token in ("codex", "llm", "ai"))
                or (bool(actor) and actor_type != "human")
            )
            if nonhuman:
                record = {
                    "campaign_id": batch.get("campaign_id"),
                    "batch_id": batch.get("batch_id"),
                    "role": role,
                    "actor_id": actor_id_text,
                    "actor_type": actor_type or "unknown",
                }
                if amendment_id and actor_id_text in amendment_permitted_ids and actor_type == "llm":
                    amendment_permitted_assignments.append({**record, "amendment_id": amendment_id})
                else:
                    forbidden_assignments.append(record)
            assigned[role] = actor_id_text
        if assigned.get("annotator_a") and assigned.get("annotator_a") == assigned.get("annotator_b"):
            conflicts.append(
                {
                    "campaign_id": batch.get("campaign_id"),
                    "batch_id": batch.get("batch_id"),
                    "reason": "annotator_a_equals_annotator_b",
                    "actor_id": assigned["annotator_a"],
                }
            )
        for comparison_role in ("annotator_a", "annotator_b"):
            if assigned.get("adjudicator") and assigned.get("adjudicator") == assigned.get(comparison_role):
                conflicts.append(
                    {
                        "campaign_id": batch.get("campaign_id"),
                        "batch_id": batch.get("batch_id"),
                        "reason": "adjudicator_conflicts_with_independent_annotator",
                        "actor_id": assigned["adjudicator"],
                        "comparison_role": comparison_role,
                    }
                )
            if assigned.get("independent_blind_reviewer") and assigned.get("independent_blind_reviewer") == assigned.get(comparison_role):
                conflicts.append(
                    {
                        "campaign_id": batch.get("campaign_id"),
                        "batch_id": batch.get("batch_id"),
                        "reason": "blind_reviewer_conflicts_with_annotator",
                        "actor_id": assigned["independent_blind_reviewer"],
                        "comparison_role": comparison_role,
                    }
                )
    blocked = human_staffing_incomplete or bool(conflicts) or bool(forbidden_assignments)
    report = {
        "schema_version": ROLE_CONFLICT_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "human_staffing_incomplete": human_staffing_incomplete,
        "annotation_campaign_blocked": blocked,
        "conflicts": conflicts,
        "forbidden_assignments": forbidden_assignments,
        "staffing_complete": not human_staffing_incomplete,
    }
    if amendment_id:
        report["llm_annotation_track_active"] = bool(amendment_permitted_assignments)
        report["llm_annotation_amendment_id"] = amendment_id
        report["amendment_permitted_assignments"] = amendment_permitted_assignments
        report["human_annotation_evidence"] = False
    return report


def build_qualification_execution_assets(
    *,
    qualification_test_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    public_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"notes"}
        }
        for row in qualification_test_rows
    ]
    annotator_a_package = [{**row, "package_role": "annotator_a"} for row in public_rows]
    annotator_b_package = [{**row, "package_role": "annotator_b"} for row in public_rows]
    scoring_manifest = {
        "schema_version": QUALIFICATION_EXECUTION_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "thresholds": dict(QUALIFICATION_THRESHOLDS),
        "required_guideline_version": DEFAULT_PILOT_GUIDELINE_VERSION,
        "result_fields": ["qualification_id", "annotator_id", "exact_k", "unit_to_intent", "background_units"],
    }
    result_template = {
        "schema_version": QUALIFICATION_EXECUTION_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "submission_status": "pending_human_submission",
        "annotator_id": None,
        "guideline_version": DEFAULT_PILOT_GUIDELINE_VERSION,
        "results": [],
    }
    return {
        "annotator_a_package": annotator_a_package,
        "annotator_b_package": annotator_b_package,
        "scoring_manifest": scoring_manifest,
        "result_template": result_template,
    }


def build_calibration_round_assets(
    *,
    pilot_rows: list[dict[str, Any]],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
    seed: int = 20260724,
    target_size: int = CALIBRATION_TARGET_SIZE,
    round_label: str = "calibration_round_1",
    excluded_sample_ids: set[str] | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    if excluded_sample_ids:
        pilot_rows = [row for row in pilot_rows if str(row.get("sample_id") or "") not in excluded_sample_ids]
    selected_rows = _select_calibration_rows(pilot_rows, seed=seed, target_size=target_size)
    annotator_a: list[dict[str, Any]] = []
    annotator_b: list[dict[str, Any]] = []
    adjudication_template: list[dict[str, Any]] = []
    blinding_rows: list[dict[str, Any]] = []
    for index, row in enumerate(selected_rows, start=1):
        public_id = f"{round_label}_{index:04d}"
        public_payload = {
            "schema_version": CALIBRATION_ROUND_SCHEMA_VERSION,
            "sample_id": public_id,
            "normalized_diff": row["normalized_diff"],
            "edit_units": list(row.get("edit_units") or []),
            "repository_language": str(row.get("repository_language") or dict(row.get("source_fields") or {}).get("language") or ""),
            "guideline_version": str(row.get("guideline_version") or DEFAULT_PILOT_GUIDELINE_VERSION),
            "annotation_version": str(row.get("annotation_version") or DEFAULT_ANNOTATION_VERSION),
            "model_prediction_hidden": True,
            "commit_message_hidden": True,
            "split_hidden": True,
            "allowed_context": {
                "repository": row.get("repository"),
                "unit_count": len(list(row.get("edit_units") or [])),
            },
        }
        annotator_a.append({**public_payload, "package": "annotator_a"})
        annotator_b.append({**public_payload, "package": "annotator_b"})
        adjudication_template.append(
            {
                "schema_version": CALIBRATION_ROUND_SCHEMA_VERSION,
                "sample_id": public_id,
                "guideline_version": public_payload["guideline_version"],
                "annotation_version": public_payload["annotation_version"],
                "annotation_a": None,
                "annotation_b": None,
                "adjudicated_annotation": None,
                "adjudication_reason": None,
            }
        )
        blinding_rows.append(
            {
                "sample_id": public_id,
                "original_sample_id": row["sample_id"],
                "commit_id": row.get("commit_id"),
                "repository": row.get("repository"),
                "provisional_tags": list(row.get("candidate_tags") or row.get("provisional_tags") or []),
            }
        )
    result_template = {
        "schema_version": CALIBRATION_ROUND_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "campaign_id": "real_alignment_pilot",
        "batch_id": round_label,
        "completed": False,
        "sample_count": len(selected_rows),
        "guideline_status": "pending_human_execution",
    }
    sampling_report = {
        "schema_version": CALIBRATION_ROUND_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "sample_count": len(selected_rows),
        "selected_sample_ids": [row["sample_id"] for row in selected_rows],
        "tag_coverage": dict(
            sorted(Counter(tag for row in selected_rows for tag in list(row.get("candidate_tags") or row.get("provisional_tags") or [])).items())
        ),
    }
    return {
        "selected_rows": selected_rows,
        "annotator_a_package": annotator_a,
        "annotator_b_package": annotator_b,
        "adjudication_template": adjudication_template,
        "blinding_map": {
            "schema_version": CALIBRATION_ROUND_SCHEMA_VERSION,
            "rows": blinding_rows,
        },
        "result_template": result_template,
        "sampling_report": sampling_report,
    }


def analyze_calibration_round(
    *,
    adjudicated_rows: list[dict[str, Any]],
    agreement_thresholds: dict[str, float],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    agreement = summarize_real_adjudicated_agreement(adjudicated_rows)
    disagreements = _build_calibration_disagreement_queue(adjudicated_rows)
    gates = {
        "exact_k_weighted_kappa": _gate_metric(
            agreement.get("exact_k_weighted_kappa"), agreement_thresholds.get("exact_k_weighted_kappa_min")
        ),
        "split_no_split_kappa": _gate_metric(
            agreement.get("split_no_split_kappa"), agreement_thresholds.get("split_no_split_kappa_min")
        ),
        "foreground_background_agreement": _gate_metric(
            agreement.get("foreground_background_agreement"), agreement_thresholds.get("foreground_background_agreement_min")
        ),
        "bcubed_agreement": _gate_metric(
            agreement.get("mean_bcubed_f1"), agreement_thresholds.get("bcubed_agreement_min")
        ),
        "pairwise_unit_agreement": _gate_metric(
            agreement.get("mean_pairwise_f1"), agreement_thresholds.get("pairwise_unit_agreement_min")
        ),
    }
    guideline_status = "pilot_ready" if all(item["passed"] for item in gates.values()) else "revision_required"
    report = {
        "schema_version": CALIBRATION_REPORT_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "row_count": len(adjudicated_rows),
        "agreement": agreement,
        "agreement_gates": gates,
        "disagreement_category_counts": dict(
            sorted(Counter(category for row in disagreements for category in row.get("disagreement_categories", [])).items())
        ),
        "guideline_status": guideline_status,
    }
    return {
        "agreement_report": report,
        "disagreement_queue": disagreements,
        "guideline_revision_proposal": _build_guideline_revision_proposal(report, disagreements),
    }


def build_annotation_campaign_progress(
    *,
    campaign_manifest: dict[str, Any],
    role_conflict_report: dict[str, Any],
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    created_at_value = created_at or utc_now_iso()
    batches = list(campaign_manifest.get("batches") or [])
    total_samples = sum(int(batch.get("sample_count") or 0) for batch in batches if batch.get("batch_type") != "blind_review")
    return {
        "schema_version": ANNOTATION_PROGRESS_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at_value,
        "campaign_id": str(campaign_manifest.get("campaign_id") or ""),
        "batch_count": len(batches),
        "total_samples": total_samples,
        "completed_samples": 0,
        "double_annotated_samples": 0,
        "adjudicated_samples": 0,
        "blind_review_completed_samples": 0,
        "progress_fraction": 0.0,
        "annotation_campaign_blocked": bool(role_conflict_report.get("annotation_campaign_blocked")),
    }


def build_annotation_audit_log_template(
    *,
    protocol_version: str,
    creation_git_sha: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ANNOTATION_AUDIT_LOG_TEMPLATE_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "created_at": created_at or utc_now_iso(),
        "event_schema_version": ANNOTATION_AUDIT_LOG_SCHEMA_VERSION,
        "append_only": True,
        "event_count": 0,
    }


def _build_queue_index(rows: list[dict[str, Any]], *, queue_name: str) -> dict[str, Any]:
    index: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        index[_commit_key(row)].append(str(row.get("sample_id") or row.get("source_atomic_commit_id") or ""))
    return {
        "queue_name": queue_name,
        "row_count": len(rows),
        "commit_index": {key: sorted(values) for key, values in sorted(index.items())},
    }


def _commit_key(row: dict[str, Any]) -> str:
    repo = str(row.get("repository") or row.get("repo") or "")
    commit_id = str(row.get("commit_id") or row.get("sha") or row.get("source_atomic_commit_id") or row.get("sample_id") or "")
    return f"{repo}@{commit_id}" if repo and commit_id and "@" not in commit_id else commit_id


def _infer_workload_group(queue_sample_ids: dict[str, list[str]]) -> str:
    if queue_sample_ids.get("real_alignment_pilot"):
        return "full_alignment_anchor"
    if queue_sample_ids.get("real_count_pilot") and queue_sample_ids.get("background_pilot"):
        return "count_plus_background"
    if queue_sample_ids.get("real_count_pilot"):
        return "count_only"
    if queue_sample_ids.get("background_pilot"):
        return "background_only"
    if queue_sample_ids.get("atomic_source_review"):
        return "atomic_source_review_only"
    return "unknown"


def _stable_order(rows: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: hashlib.sha1(f"{seed}:{row.get('sample_id') or row.get('source_atomic_commit_id')}".encode("utf-8")).hexdigest(),
    )


def _select_calibration_rows(rows: list[dict[str, Any]], *, seed: int, target_size: int) -> list[dict[str, Any]]:
    ordered = _stable_order(rows, seed=seed)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    missing_tags = set(CALIBRATION_REQUIRED_TAGS)
    while missing_tags and len(selected) < target_size:
        best_row = None
        best_coverage: tuple[int, str] | None = None
        for row in ordered:
            sample_id = str(row.get("sample_id") or "")
            if sample_id in selected_ids:
                continue
            tags = set(row.get("candidate_tags") or row.get("provisional_tags") or [])
            coverage = len(tags & missing_tags)
            if coverage <= 0:
                continue
            rank = hashlib.sha1(f"{seed}:calibration:{sample_id}".encode("utf-8")).hexdigest()
            if best_coverage is None or (coverage, rank) > best_coverage:
                best_row = row
                best_coverage = (coverage, rank)
        if best_row is None:
            break
        selected.append(best_row)
        selected_ids.add(str(best_row.get("sample_id") or ""))
        missing_tags -= set(best_row.get("candidate_tags") or best_row.get("provisional_tags") or [])
    for row in ordered:
        if len(selected) >= target_size:
            break
        sample_id = str(row.get("sample_id") or "")
        if sample_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(sample_id)
    return selected[:target_size]


def _chunk_rows(rows: list[dict[str, Any]], batch_sizes: list[int]) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    offset = 0
    for size in batch_sizes:
        if offset >= len(rows):
            break
        if size <= 0:
            continue
        batches.append(rows[offset : offset + size])
        offset += size
    if offset < len(rows) and batches:
        batches[-1].extend(rows[offset:])
    elif offset < len(rows):
        batches.append(rows[offset:])
    return [batch for batch in batches if batch]


def _build_batch_record(
    *,
    campaign_id: str,
    batch_id: str,
    rows: list[dict[str, Any]],
    guideline_version: str,
    batch_type: str,
    required_roles: list[str],
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "batch_type": batch_type,
        "sample_count": len(rows),
        "sample_ids": [str(row.get("sample_id") or "") for row in rows],
        "guideline_version": guideline_version,
        "required_roles": required_roles,
        "status": "pending_human_staffing",
    }


def _build_calibration_disagreement_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in rows:
        annotation_a = row.get("annotation_a")
        annotation_b = row.get("annotation_b")
        if not isinstance(annotation_a, dict) or not isinstance(annotation_b, dict):
            continue
        categories = _categorize_alignment_disagreement(annotation_a, annotation_b)
        if not categories:
            continue
        queue.append(
            {
                "sample_id": str(row.get("sample_id") or ""),
                "commit_id": str(row.get("commit_id") or ""),
                "repository": str(row.get("repository") or ""),
                "disagreement_categories": categories,
                "annotation_a": annotation_a,
                "annotation_b": annotation_b,
            }
        )
    return queue


def _categorize_alignment_disagreement(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    left_k = int(left.get("exact_k") or 0)
    right_k = int(right.get("exact_k") or 0)
    if left_k != right_k:
        categories.append("exact_k_disagreement")
        if (left_k <= 1 < right_k) or (right_k <= 1 < left_k):
            categories.append("split_vs_no_split")
        else:
            categories.append("merge_vs_split")
    left_labels = {str(unit_id): str(dict(payload).get("label") or "") for unit_id, payload in dict(left.get("unit_labels") or {}).items()}
    right_labels = {str(unit_id): str(dict(payload).get("label") or "") for unit_id, payload in dict(right.get("unit_labels") or {}).items()}
    for unit_id in sorted(set(left_labels) | set(right_labels)):
        left_label = left_labels.get(unit_id, "")
        right_label = right_labels.get(unit_id, "")
        if left_label == right_label:
            continue
        if {left_label, right_label} <= BACKGROUND_ONLY_LABELS | {"foreground"}:
            categories.append("background_vs_foreground")
        elif left_label in UNCERTAIN_STYLE_LABELS or right_label in UNCERTAIN_STYLE_LABELS:
            categories.append("uncertain_shared_mixed_disagreement")
        else:
            categories.append("unit_label_disagreement")
    left_map = _foreground_map(left)
    right_map = _foreground_map(right)
    if pairwise_f1_from_assignments(left_map, right_map)["pairwise_f1"] < 1.0:
        categories.append("pairwise_partition_disagreement")
    return sorted(set(categories))


def _foreground_map(annotation: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for unit_id, payload in dict(annotation.get("unit_labels") or {}).items():
        info = dict(payload or {})
        if str(info.get("label") or "") == "foreground":
            mapping[str(unit_id)] = str(info.get("intent_id") or "")
    return mapping


def _gate_metric(value: float | None, threshold: float | None) -> dict[str, Any]:
    if value is None or threshold is None:
        return {"observed": value, "threshold": threshold, "passed": False}
    return {"observed": value, "threshold": threshold, "passed": float(value) >= float(threshold)}


def _build_guideline_revision_proposal(report: dict[str, Any], disagreements: list[dict[str, Any]]) -> str:
    lines = [
        "# Guideline Revision Proposal",
        "",
        f"- Guideline status: `{report['guideline_status']}`",
        f"- Sample count: `{report['row_count']}`",
        "",
        "## Agreement Gates",
    ]
    for metric_name, payload in sorted(dict(report.get("agreement_gates") or {}).items()):
        lines.append(
            f"- `{metric_name}`: observed={payload.get('observed')} threshold={payload.get('threshold')} passed={payload.get('passed')}"
        )
    lines.append("")
    lines.append("## Top Disagreement Categories")
    category_counts = Counter(category for row in disagreements for category in row.get("disagreement_categories", []))
    if not category_counts:
        lines.append("- none")
    else:
        for category, count in category_counts.most_common(10):
            lines.append(f"- `{category}`: {count}")
    lines.append("")
    lines.append("## Required Human Action")
    if report["guideline_status"] == "pilot_ready":
        lines.append("- Human reviewer should confirm the pilot guideline before batch 2 starts.")
    else:
        lines.append("- Human reviewer must revise the pilot guideline and rerun the calibration round.")
    return "\n".join(lines) + "\n"
