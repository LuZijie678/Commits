from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any

from code.mica.eval.attribution_metrics import pairwise_f1_from_assignments
from code.mica.stage1_v2.real_adjudicated import (
    summarize_real_adjudicated_agreement,
    validate_real_adjudicated_record,
)
from code.mica.stage1_v2.real_count import quadratic_weighted_kappa, summarize_real_count_agreement


ANNOTATION_STATE_SCHEMA_VERSION = "mica-stage1-v2-annotation-workflow-v1"
ANNOTATION_STATES = [
    "pending",
    "annotated_a",
    "annotated_b",
    "independently_double_annotated",
    "agreement",
    "conflict",
    "adjudication_pending",
    "adjudicated",
    "quality_reviewed",
    "eligible_for_asset",
]


def import_annotation_a(
    rows: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    *,
    annotator_id: str,
    guideline_version: str,
    annotation_version: str,
    timestamp: str,
) -> dict[str, Any]:
    return _import_annotation(
        rows,
        annotations,
        annotator_slot="a",
        annotator_id=annotator_id,
        guideline_version=guideline_version,
        annotation_version=annotation_version,
        timestamp=timestamp,
    )


def import_annotation_b(
    rows: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    *,
    annotator_id: str,
    guideline_version: str,
    annotation_version: str,
    timestamp: str,
) -> dict[str, Any]:
    return _import_annotation(
        rows,
        annotations,
        annotator_slot="b",
        annotator_id=annotator_id,
        guideline_version=guideline_version,
        annotation_version=annotation_version,
        timestamp=timestamp,
    )


def validate_independent_annotations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    updated = copy.deepcopy(rows)
    counts = Counter()
    conflicts: list[str] = []
    for row in updated:
        status = str(row.get("annotation_status") or "pending")
        if not _has_a_and_b(row):
            counts[status] += 1
            continue
        before = status
        row["annotation_status"] = "independently_double_annotated"
        _append_history(
            row,
            actor="system",
            action="validate_independent_annotations",
            status_from=before,
            status_to="independently_double_annotated",
            timestamp="validation",
            annotation_version=str(row.get("annotation_version") or ""),
            guideline_version=str(row.get("guideline_version") or ""),
            details={"compare_mode": _row_task_type(row)},
        )
        if _annotations_match(row):
            row["annotation_status"] = "agreement"
            counts["agreement"] += 1
            _append_history(
                row,
                actor="system",
                action="agreement_detected",
                status_from="independently_double_annotated",
                status_to="agreement",
                timestamp="validation",
                annotation_version=str(row.get("annotation_version") or ""),
                guideline_version=str(row.get("guideline_version") or ""),
            )
        else:
            row["annotation_status"] = "conflict"
            counts["conflict"] += 1
            conflicts.append(str(row.get("sample_id") or ""))
            _append_history(
                row,
                actor="system",
                action="conflict_detected",
                status_from="independently_double_annotated",
                status_to="conflict",
                timestamp="validation",
                annotation_version=str(row.get("annotation_version") or ""),
                guideline_version=str(row.get("guideline_version") or ""),
            )
    return {
        "schema_version": ANNOTATION_STATE_SCHEMA_VERSION,
        "rows": updated,
        "status_counts": dict(sorted(counts.items())),
        "conflict_sample_ids": sorted(conflicts),
    }


def compute_pre_adjudication_agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count_rows = [row for row in rows if _row_task_type(row) == "real_count"]
    alignment_rows = [row for row in rows if _row_task_type(row) == "real_alignment"]
    payload: dict[str, Any] = {"schema_version": ANNOTATION_STATE_SCHEMA_VERSION}
    if count_rows:
        normalized = []
        for row in count_rows:
            normalized.append(
                {
                    "annotator_a_count": row.get("annotator_a_exact_k"),
                    "annotator_b_count": row.get("annotator_b_exact_k"),
                    "annotation_status": row.get("annotation_status"),
                    "adjudicated_exact_k": row.get("adjudicated_exact_k"),
                    "annotator_a_id": row.get("annotator_a_id"),
                    "annotator_b_id": row.get("annotator_b_id"),
                    "adjudicator_id": row.get("adjudicator_id"),
                    "source_type": row.get("source_type"),
                    "current_weak_label": row.get("current_weak_label"),
                    "schema_version": row.get("schema_version"),
                    "sample_id": row.get("sample_id"),
                    "commit_id": row.get("commit_id"),
                    "repository": row.get("repository"),
                    "diff_reference": row.get("diff_reference"),
                    "split_candidate": row.get("split_candidate"),
                    "guideline_version": row.get("guideline_version"),
                    "annotation_version": row.get("annotation_version"),
                    "leakage_group": row.get("leakage_group"),
                    "normalized_diff_hash": row.get("normalized_diff_hash"),
                }
            )
        payload["real_count"] = summarize_real_count_agreement(normalized)
    if alignment_rows:
        payload["real_alignment"] = summarize_real_adjudicated_agreement(alignment_rows)
    return payload


def export_adjudication_queue(rows: list[dict[str, Any]], *, timestamp: str) -> dict[str, Any]:
    updated = copy.deepcopy(rows)
    queue: list[dict[str, Any]] = []
    for row in updated:
        if str(row.get("annotation_status") or "") != "conflict":
            continue
        before = "conflict"
        row["annotation_status"] = "adjudication_pending"
        _append_history(
            row,
            actor="system",
            action="export_adjudication_queue",
            status_from=before,
            status_to="adjudication_pending",
            timestamp=timestamp,
            annotation_version=str(row.get("annotation_version") or ""),
            guideline_version=str(row.get("guideline_version") or ""),
        )
        queue.append(
            {
                "sample_id": row.get("sample_id"),
                "commit_id": row.get("commit_id"),
                "repository": row.get("repository"),
                "guideline_version": row.get("guideline_version"),
                "annotation_version": row.get("annotation_version"),
                "annotation_a": _annotation_payload(row, "a"),
                "annotation_b": _annotation_payload(row, "b"),
                "task_type": _row_task_type(row),
            }
        )
    return {"schema_version": ANNOTATION_STATE_SCHEMA_VERSION, "rows": updated, "adjudication_queue": queue}


def import_adjudicated_annotations(
    rows: list[dict[str, Any]],
    adjudications: list[dict[str, Any]],
    *,
    adjudicator_id: str,
    guideline_version: str,
    annotation_version: str,
    timestamp: str,
) -> dict[str, Any]:
    updated = copy.deepcopy(rows)
    by_sample = {str(row.get("sample_id") or ""): row for row in updated}
    imported = 0
    for payload in adjudications:
        sample_id = str(payload.get("sample_id") or "").strip()
        if not sample_id:
            raise ValueError("adjudication payload requires sample_id")
        row = by_sample.get(sample_id)
        if row is None:
            raise ValueError(f"unknown sample_id for adjudication: {sample_id}")
        if str(row.get("guideline_version") or "") != guideline_version:
            raise ValueError(f"guideline_version mismatch for sample {sample_id}")
        if str(row.get("annotation_version") or "") != annotation_version:
            raise ValueError(f"annotation_version mismatch for sample {sample_id}")
        if str(row.get("annotation_status") or "") not in {"adjudication_pending", "agreement", "conflict"}:
            raise ValueError(f"sample {sample_id} is not ready for adjudication")
        before = str(row.get("annotation_status") or "")
        task_type = _row_task_type(row)
        if task_type == "real_count":
            exact_k = payload.get("adjudicated_exact_k")
            if exact_k is None:
                raise ValueError(f"count adjudication for sample {sample_id} requires adjudicated_exact_k")
            row["adjudicated_exact_k"] = int(exact_k)
            row["adjudicator_id"] = adjudicator_id
            row["adjudication_status"] = "adjudicated"
        else:
            annotation = payload.get("adjudicated_annotation")
            if not isinstance(annotation, dict):
                raise ValueError(f"alignment adjudication for sample {sample_id} requires adjudicated_annotation")
            row["adjudicated_annotation"] = annotation
            row["adjudicator_id"] = adjudicator_id
            row["adjudication_reason"] = payload.get("adjudication_reason")
        row["annotation_status"] = "adjudicated"
        _append_history(
            row,
            actor=adjudicator_id,
            action="import_adjudicated_annotation",
            status_from=before,
            status_to="adjudicated",
            timestamp=timestamp,
            annotation_version=annotation_version,
            guideline_version=guideline_version,
        )
        imported += 1
    return {"schema_version": ANNOTATION_STATE_SCHEMA_VERSION, "rows": updated, "imported_count": imported}


def build_adjudicated_asset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = []
    for row in copy.deepcopy(rows):
        if str(row.get("annotation_status") or "") not in {"adjudicated", "quality_reviewed", "eligible_for_asset"}:
            continue
        if _row_task_type(row) == "real_count":
            if row.get("adjudicated_exact_k") is None or not row.get("adjudicator_id"):
                continue
        else:
            if row.get("adjudicated_annotation") is None or not row.get("adjudicator_id"):
                continue
        before = str(row.get("annotation_status") or "")
        row["annotation_status"] = "eligible_for_asset"
        _append_history(
            row,
            actor="system",
            action="build_adjudicated_asset",
            status_from=before,
            status_to="eligible_for_asset",
            timestamp="asset_build",
            annotation_version=str(row.get("annotation_version") or ""),
            guideline_version=str(row.get("guideline_version") or ""),
        )
        eligible.append(row)
    return {
        "schema_version": ANNOTATION_STATE_SCHEMA_VERSION,
        "task_type": _row_task_type(eligible[0]) if eligible else None,
        "row_count": len(eligible),
        "rows": eligible,
    }


def export_independent_blind_review_sample(
    rows: list[dict[str, Any]],
    *,
    fraction: float,
    seed: int,
) -> dict[str, Any]:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [0,1]")
    eligible = [row for row in rows if str(row.get("annotation_status") or "") in {"adjudicated", "quality_reviewed", "eligible_for_asset"}]
    ranked = sorted(
        eligible,
        key=lambda row: hashlib.sha1(f"{seed}:{row.get('sample_id')}".encode("utf-8")).hexdigest(),
    )
    sample_count = max(1, round(len(ranked) * fraction)) if ranked and fraction > 0 else 0
    selected = ranked[:sample_count]
    return {
        "schema_version": ANNOTATION_STATE_SCHEMA_VERSION,
        "fraction": fraction,
        "seed": seed,
        "completed": False,
        "row_count": len(selected),
        "rows": [
            {
                "sample_id": row.get("sample_id"),
                "commit_id": row.get("commit_id"),
                "repository": row.get("repository"),
                "task_type": _row_task_type(row),
                "blind_review_status": "pending",
            }
            for row in selected
        ],
    }


def compute_post_adjudication_quality_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("annotation_status") or "missing") for row in rows)
    pre = compute_pre_adjudication_agreement(rows)
    eligible_count = sum(1 for row in rows if str(row.get("annotation_status") or "") in {"eligible_for_asset", "quality_reviewed"})
    adjudicated_count = sum(1 for row in rows if str(row.get("annotation_status") or "") in {"adjudicated", "eligible_for_asset", "quality_reviewed"})
    return {
        "schema_version": ANNOTATION_STATE_SCHEMA_VERSION,
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "adjudicated_count": adjudicated_count,
        "eligible_for_asset_count": eligible_count,
        "agreement_metrics": pre,
    }


def score_qualification_submission(
    *,
    answers: list[dict[str, Any]],
    answer_key: list[dict[str, Any]],
) -> dict[str, Any]:
    key_by_id = {str(row.get("qualification_id") or ""): row for row in answer_key}
    exact_total = 0
    exact_hit = 0
    pairwise_scores: list[float] = []
    background_scores: list[float] = []
    for answer in answers:
        qualification_id = str(answer.get("qualification_id") or "")
        gold = key_by_id.get(qualification_id)
        if not gold:
            continue
        exact_total += 1
        if int(answer.get("exact_k") or 0) == int(gold.get("exact_k") or 0):
            exact_hit += 1
        pairwise_scores.append(
            pairwise_f1_from_assignments(
                dict(answer.get("unit_to_intent") or {}),
                dict(gold.get("unit_to_intent") or {}),
            )["pairwise_f1"]
        )
        background_scores.append(
            _background_classification_f1(
                predicted=set(str(item) for item in list(answer.get("background_units") or [])),
                gold=set(str(item) for item in list(gold.get("background_units") or [])),
                foreground_unit_ids=set(str(item) for item in dict(gold.get("unit_to_intent") or {}).keys()),
            )
        )
    exact_accuracy = (exact_hit / exact_total) if exact_total else 0.0
    pairwise_partition_f1 = (sum(pairwise_scores) / len(pairwise_scores)) if pairwise_scores else 0.0
    background_classification_f1 = (sum(background_scores) / len(background_scores)) if background_scores else 0.0
    return {
        "schema_version": ANNOTATION_STATE_SCHEMA_VERSION,
        "exact_k_accuracy": round(exact_accuracy, 6),
        "pairwise_partition_f1": round(pairwise_partition_f1, 6),
        "background_classification_f1": round(background_classification_f1, 6),
        "passes": bool(exact_total)
        and exact_accuracy >= 0.85
        and pairwise_partition_f1 >= 0.80
        and background_classification_f1 >= 0.85,
    }


def _import_annotation(
    rows: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    *,
    annotator_slot: str,
    annotator_id: str,
    guideline_version: str,
    annotation_version: str,
    timestamp: str,
) -> dict[str, Any]:
    if annotator_slot not in {"a", "b"}:
        raise ValueError("annotator_slot must be 'a' or 'b'")
    updated = copy.deepcopy(rows)
    by_sample = {str(row.get("sample_id") or ""): row for row in updated}
    imported = 0
    for payload in annotations:
        sample_id = str(payload.get("sample_id") or "").strip()
        if not sample_id:
            raise ValueError("annotation payload requires sample_id")
        row = by_sample.get(sample_id)
        if row is None:
            raise ValueError(f"unknown sample_id: {sample_id}")
        if str(row.get("guideline_version") or "") != guideline_version:
            raise ValueError(f"guideline_version mismatch for sample {sample_id}")
        if str(row.get("annotation_version") or "") != annotation_version:
            raise ValueError(f"annotation_version mismatch for sample {sample_id}")
        _apply_annotation_payload(
            row,
            payload=payload,
            annotator_slot=annotator_slot,
            annotator_id=annotator_id,
            timestamp=timestamp,
            guideline_version=guideline_version,
            annotation_version=annotation_version,
        )
        imported += 1
    return {"schema_version": ANNOTATION_STATE_SCHEMA_VERSION, "rows": updated, "imported_count": imported}


def _apply_annotation_payload(
    row: dict[str, Any],
    *,
    payload: dict[str, Any],
    annotator_slot: str,
    annotator_id: str,
    timestamp: str,
    guideline_version: str,
    annotation_version: str,
) -> None:
    task_type = _row_task_type(row)
    status_before = str(row.get("annotation_status") or "pending")
    if task_type == "real_count":
        field = f"annotator_{annotator_slot}_exact_k"
        actor_field = f"annotator_{annotator_slot}_id"
        if row.get(field) is not None:
            raise ValueError(f"sample {row.get('sample_id')} already has annotation_{annotator_slot}")
        other_actor_field = f"annotator_{'b' if annotator_slot == 'a' else 'a'}_id"
        if row.get(other_actor_field) == annotator_id:
            raise ValueError(f"sample {row.get('sample_id')} cannot use the same annotator for A and B")
        if payload.get("exact_k") is None:
            raise ValueError(f"real_count annotation for sample {row.get('sample_id')} requires exact_k")
        row[field] = int(payload["exact_k"])
        row[f"annotator_{annotator_slot}_count"] = int(payload["exact_k"])
        row[actor_field] = annotator_id
    else:
        field = f"annotation_{annotator_slot}"
        actor_field = f"annotator_{annotator_slot}_id"
        if row.get(field) is not None:
            raise ValueError(f"sample {row.get('sample_id')} already has annotation_{annotator_slot}")
        other_actor_field = f"annotator_{'b' if annotator_slot == 'a' else 'a'}_id"
        if row.get(other_actor_field) == annotator_id:
            raise ValueError(f"sample {row.get('sample_id')} cannot use the same annotator for A and B")
        annotation = payload.get("annotation")
        if not isinstance(annotation, dict):
            raise ValueError(f"real_alignment annotation for sample {row.get('sample_id')} requires annotation dict")
        row[field] = annotation
        row[actor_field] = annotator_id
        validation = validate_real_adjudicated_record(
            {
                **row,
                "annotation_status": row.get("annotation_status"),
                "annotation_a": row.get("annotation_a"),
                "annotation_b": row.get("annotation_b"),
                "adjudicated_annotation": row.get("adjudicated_annotation"),
            }
        )
        if not validation["valid"]:
            raise ValueError(f"invalid annotation for sample {row.get('sample_id')}: {validation['errors']}")
    if _has_a_and_b(row):
        status_after = "independently_double_annotated"
    else:
        status_after = "annotated_a" if annotator_slot == "a" else "annotated_b"
    row["annotation_status"] = status_after
    _append_history(
        row,
        actor=annotator_id,
        action=f"import_annotation_{annotator_slot}",
        status_from=status_before,
        status_to=status_after,
        timestamp=timestamp,
        annotation_version=annotation_version,
        guideline_version=guideline_version,
    )


def _annotation_payload(row: dict[str, Any], annotator_slot: str) -> Any:
    if _row_task_type(row) == "real_count":
        return row.get(f"annotator_{annotator_slot}_exact_k")
    return row.get(f"annotation_{annotator_slot}")


def _annotations_match(row: dict[str, Any]) -> bool:
    if _row_task_type(row) == "real_count":
        return row.get("annotator_a_exact_k") == row.get("annotator_b_exact_k")
    left = json.dumps(row.get("annotation_a"), ensure_ascii=False, sort_keys=True)
    right = json.dumps(row.get("annotation_b"), ensure_ascii=False, sort_keys=True)
    return left == right


def _has_a_and_b(row: dict[str, Any]) -> bool:
    if _row_task_type(row) == "real_count":
        return row.get("annotator_a_exact_k") is not None and row.get("annotator_b_exact_k") is not None
    return isinstance(row.get("annotation_a"), dict) and isinstance(row.get("annotation_b"), dict)


def _row_task_type(row: dict[str, Any]) -> str:
    if "annotator_a_exact_k" in row or "adjudicated_exact_k" in row:
        return "real_count"
    return "real_alignment"


def _append_history(
    row: dict[str, Any],
    *,
    actor: str,
    action: str,
    status_from: str,
    status_to: str,
    timestamp: str,
    annotation_version: str,
    guideline_version: str,
    details: dict[str, Any] | None = None,
) -> None:
    history = list(row.get("annotation_history") or [])
    history.append(
        {
            "actor": actor,
            "action": action,
            "status_from": status_from,
            "status_to": status_to,
            "timestamp": timestamp,
            "annotation_version": annotation_version,
            "guideline_version": guideline_version,
            "details": dict(details or {}),
        }
    )
    row["annotation_history"] = history


def _background_classification_f1(
    *,
    predicted: set[str],
    gold: set[str],
    foreground_unit_ids: set[str],
) -> float:
    universe = sorted(predicted | gold | foreground_unit_ids)
    if not universe:
        return 1.0
    tp = sum(1 for unit_id in universe if unit_id in predicted and unit_id in gold)
    fp = sum(1 for unit_id in universe if unit_id in predicted and unit_id not in gold)
    fn = sum(1 for unit_id in universe if unit_id not in predicted and unit_id in gold)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
