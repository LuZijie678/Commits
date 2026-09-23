from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.stage1_v2.campaign import FORBIDDEN_ACTOR_TYPES
from code.mica.stage1_v2.audit_log import compute_record_hash


SOURCE_REVIEW_SIDECAR_SCHEMA_VERSION = "mica-stage1-v2-source-review-sidecar-v1"
VALID_SOURCE_REVIEW_DECISIONS = {
    "accept_atomic",
    "reject_multi_intent",
    "reject_mechanical_or_generated",
    "reject_low_evidence",
    "review_required",
}
_NONHUMAN_ID_TOKENS = ("codex", "llm", "ai", "gpt", "claude", "bot", "model")
_FORBIDDEN_EVIDENCE_TOKENS = (
    "commit_message",
    "commit message",
    "commit_subject",
    "pr_title",
    "pr title",
    "pull_request",
    "issue_text",
    "issue text",
    "issue_title",
    "issue title",
    "weak_label",
    "predicted_k",
    "model_prediction",
)
_REQUIRED_FIELDS = (
    "schema_version",
    "source_atomic_commit_id",
    "actor_id",
    "actor_type",
    "human_verified",
    "review_decision",
    "review_reason",
    "evidence_source",
    "evidence_units",
    "review_version",
    "reviewed_at",
    "source_evidence_hash",
    "record_hash",
)


def compute_source_review_source_evidence_hash(source_pool_row: dict[str, Any]) -> str:
    return compute_record_hash(
        {
            "source_atomic_commit_id": str(source_pool_row.get("source_atomic_commit_id") or ""),
            "normalized_diff_hash": str(source_pool_row.get("normalized_diff_hash") or ""),
            "edit_unit_fingerprint": str(source_pool_row.get("edit_unit_fingerprint") or ""),
        }
    )


def compute_source_review_record_hash(row: dict[str, Any]) -> str:
    payload = {key: value for key, value in row.items() if key != "record_hash"}
    return compute_record_hash(payload)


def validate_source_review_sidecar_rows(
    rows: list[dict[str, Any]],
    *,
    llm_annotation_amendment: dict[str, Any] | None = None,
    source_pool_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate source-review sidecar rows before they may influence any pool state.

    Enforces:
    - schema/decision vocabulary and non-empty review_reason;
    - a reviewer whose id looks non-human MUST be covered by an explicit
      llm-annotation amendment, otherwise the row is invalid;
    - any row from a non-human reviewer MUST carry human_verified=False —
      LLM review can never mint human verification.
    """
    amendment_id = str((llm_annotation_amendment or {}).get("amendment_id") or "")
    permitted_ids = {
        str(actor_id)
        for actor_id in list((llm_annotation_amendment or {}).get("permitted_actor_ids") or [])
        if str(actor_id)
    }
    source_pool_by_id = _build_source_pool_by_id(source_pool_rows)
    active_rows_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    record_hashes_by_source: dict[str, set[str]] = defaultdict(set)
    errors: list[dict[str, Any]] = []
    llm_reviewed = 0
    superseded_rows = 0
    for index, row in enumerate(rows):
        source_id = str(row.get("source_atomic_commit_id") or f"__row_{index}__")
        actor_id = str(row.get("actor_id") or row.get("reviewer_id") or "")
        actor_type = str(row.get("actor_type") or "").lower()
        if not actor_id:
            errors.append({"source_atomic_commit_id": source_id, "reason": "missing_actor_id"})
        for field in _REQUIRED_FIELDS:
            value = row.get(field)
            if value in (None, "", []):
                errors.append({"source_atomic_commit_id": source_id, "reason": f"missing_{field}"})
        if str(row.get("schema_version") or "") != SOURCE_REVIEW_SIDECAR_SCHEMA_VERSION:
            errors.append({"source_atomic_commit_id": source_id, "reason": "invalid_schema_version"})
        decision = str(row.get("review_decision") or "")
        if decision not in VALID_SOURCE_REVIEW_DECISIONS:
            errors.append({"source_atomic_commit_id": source_id, "reason": f"invalid_decision:{decision}"})
        if not str(row.get("review_reason") or "").strip():
            errors.append({"source_atomic_commit_id": source_id, "reason": "empty_review_reason"})
        if row.get("record_hash") and row.get("record_hash") != compute_source_review_record_hash(row):
            errors.append({"source_atomic_commit_id": source_id, "reason": "record_hash_mismatch"})
        if source_pool_rows is not None and source_id not in source_pool_by_id:
            errors.append({"source_atomic_commit_id": source_id, "reason": "unknown_source_atomic_commit_id"})
        if source_id in source_pool_by_id:
            expected_hash = compute_source_review_source_evidence_hash(source_pool_by_id[source_id])
            if str(row.get("source_evidence_hash") or "") != expected_hash:
                errors.append({"source_atomic_commit_id": source_id, "reason": "source_evidence_hash_mismatch"})
        if _contains_forbidden_evidence(row):
            errors.append({"source_atomic_commit_id": source_id, "reason": "forbidden_metadata_leakage"})
        looks_nonhuman = actor_type in FORBIDDEN_ACTOR_TYPES or any(
            token in actor_id.lower() for token in _NONHUMAN_ID_TOKENS
        )
        if looks_nonhuman:
            llm_reviewed += 1
            if not amendment_id or actor_id not in permitted_ids or actor_type != "llm":
                errors.append(
                    {
                        "source_atomic_commit_id": source_id,
                        "reason": "nonhuman_reviewer_not_covered_by_amendment",
                        "actor_id": actor_id,
                        "actor_type": actor_type or "unknown",
                    }
                )
            if row.get("human_verified") is not False:
                errors.append(
                    {
                        "source_atomic_commit_id": source_id,
                        "reason": "nonhuman_reviewer_cannot_set_human_verified",
                        "actor_id": actor_id,
                    }
                )
        if row.get("human_verified") not in (True, False):
            errors.append({"source_atomic_commit_id": source_id, "reason": "invalid_human_verified"})
        if row.get("manual_review_status") == "superseded" or row.get("superseded_by_record_hash"):
            superseded_rows += 1
        else:
            active_rows_by_source[source_id].append(row)
        if row.get("record_hash"):
            record_hashes_by_source[source_id].add(str(row["record_hash"]))
    for source_id, source_rows in active_rows_by_source.items():
        if len(source_rows) > 1:
            errors.append({"source_atomic_commit_id": source_id, "reason": "duplicate_active_source_record"})
    for row in rows:
        source_id = str(row.get("source_atomic_commit_id") or "")
        supersedes = str(row.get("supersedes_record_hash") or "")
        if supersedes and supersedes not in record_hashes_by_source.get(source_id, set()):
            errors.append({"source_atomic_commit_id": source_id, "reason": "supersession_chain_broken"})
    return {
        "schema_version": "mica-stage1-v2-source-review-validation-v1",
        "total_rows": len(rows),
        "llm_reviewed_rows": llm_reviewed,
        "superseded_rows": superseded_rows,
        "amendment_id": amendment_id or None,
        "valid": not errors,
        "errors": errors,
    }


def _contains_forbidden_evidence(row: dict[str, Any]) -> bool:
    evidence_fields = {
        "evidence_source": row.get("evidence_source"),
        "evidence_units": row.get("evidence_units"),
        "evidence_references": row.get("evidence_references"),
        "review_reason": row.get("review_reason"),
    }
    for key in row:
        if key in {
            "commit_message",
            "commit_subject",
            "message",
            "subject",
            "pr_title",
            "issue_text",
            "issue_title",
            "weak_label",
            "current_weak_label",
            "predicted_k",
            "model_prediction",
        }:
            return True
    lowered = str(evidence_fields).lower()
    return any(token in lowered for token in _FORBIDDEN_EVIDENCE_TOKENS)


def _build_source_pool_by_id(source_pool_rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in list(source_pool_rows or []):
        source_id = str(row.get("source_atomic_commit_id") or "")
        if not source_id:
            continue
        current = by_id.get(source_id)
        if current is None or _source_evidence_score(row) > _source_evidence_score(current):
            by_id[source_id] = row
    return by_id


def _source_evidence_score(row: dict[str, Any]) -> int:
    return int(bool(row.get("normalized_diff_hash"))) + int(bool(row.get("edit_unit_fingerprint")))


__all__ = [
    "SOURCE_REVIEW_SIDECAR_SCHEMA_VERSION",
    "VALID_SOURCE_REVIEW_DECISIONS",
    "compute_source_review_record_hash",
    "compute_source_review_source_evidence_hash",
    "validate_source_review_sidecar_rows",
]
