from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from code.mica.stage1_v2.audit_log import (
    append_annotation_audit_event,
    verify_annotation_audit_log_chain,
)
from code.mica.stage1_v2.source_review import validate_source_review_sidecar_rows
from code.mica.stage1_v2.source_review import compute_source_review_record_hash
from code.mica.stage1_v2.source_review import compute_source_review_source_evidence_hash


def _append(log_path, sample_id: str) -> None:
    append_annotation_audit_event(
        log_path=log_path,
        campaign_id="real_alignment_pilot",
        batch_id="calibration_round_2",
        sample_id=sample_id,
        actor_id="claude_stage1_v2_annotator_a",
        actor_role="annotator_a",
        event_type="submitted",
        guideline_version="stage1-v2-count-guideline-pilot-v2",
        tool_version="stage1-v2-annotation-cli-v1",
        timestamp="2026-07-26T12:00:00+00:00",
        new_record_hash="abc",
    )


def test_audit_log_events_form_a_verifiable_hash_chain(tmp_path) -> None:
    log_path = tmp_path / "audit.jsonl"
    for sample_id in ("s1", "s2", "s3"):
        _append(log_path, sample_id)
    report = verify_annotation_audit_log_chain(log_path)
    assert report["total_events"] == 3
    assert report["chained_events"] == 3
    assert report["chain_valid"] is True


def test_concurrent_audit_log_appends_preserve_hash_chain(tmp_path) -> None:
    log_path = tmp_path / "audit.jsonl"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: _append(log_path, f"s{index}"), range(12)))
    report = verify_annotation_audit_log_chain(log_path)
    assert report["total_events"] == 12
    assert report["chained_events"] == 12
    assert report["chain_valid"] is True


def test_audit_log_chain_detects_tampering_and_deletion(tmp_path) -> None:
    log_path = tmp_path / "audit.jsonl"
    for sample_id in ("s1", "s2", "s3"):
        _append(log_path, sample_id)
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")

    tampered = json.loads(lines[1])
    tampered["sample_id"] = "s2-forged"
    log_path.write_text("\n".join([lines[0], json.dumps(tampered, sort_keys=True), lines[2]]) + "\n", encoding="utf-8")
    assert verify_annotation_audit_log_chain(log_path)["chain_valid"] is False

    log_path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    report = verify_annotation_audit_log_chain(log_path)
    assert report["chain_valid"] is False
    assert any(err["reason"] == "prev_event_hash_broken" for err in report["errors"])


def test_audit_log_chain_tolerates_legacy_unchained_events(tmp_path) -> None:
    log_path = tmp_path / "audit.jsonl"
    legacy = {"schema_version": "mica-stage1-v2-annotation-audit-log-v1", "event_type": "opened", "sample_id": "old"}
    log_path.write_text(json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8")
    _append(log_path, "s1")
    report = verify_annotation_audit_log_chain(log_path)
    assert report["unchained_legacy_events"] == 1
    assert report["chained_events"] == 1
    assert report["chain_valid"] is True


def _sidecar_row(reviewer_id: str, *, human_verified: bool = False) -> dict:
    row = {
        "schema_version": "mica-stage1-v2-source-review-sidecar-v1",
        "source_atomic_commit_id": "org/repo@deadbeef",
        "actor_id": reviewer_id,
        "actor_type": "llm" if "claude" in reviewer_id or "codex" in reviewer_id else "human",
        "review_decision": "accept_atomic",
        "review_reason": "Single action-object intent visible in the diff.",
        "reviewer_id": reviewer_id,
        "human_verified": human_verified,
        "evidence_source": "accepted_atomic_sources.jsonl:git_diff",
        "evidence_units": ["src/lib.rs::hunk_0000"],
        "review_version": "stage1-v2-source-review-pilot-v1",
        "reviewed_at": "2026-07-26T12:00:00+00:00",
    }
    row["source_evidence_hash"] = compute_source_review_source_evidence_hash(_source_pool_row())
    row["record_hash"] = compute_source_review_record_hash(row)
    return row


def _source_pool_row() -> dict:
    return {
        "source_atomic_commit_id": "org/repo@deadbeef",
        "normalized_diff_hash": "diff-hash",
        "edit_unit_fingerprint": "unit-hash",
    }


AMENDMENT = {
    "amendment_id": "stage1-v2-llm-annotation-amendment-v1",
    "permitted_actor_ids": ["claude_stage1_v2_source_reviewer"],
}


def test_source_review_validator_accepts_permitted_llm_reviewer() -> None:
    report = validate_source_review_sidecar_rows(
        [_sidecar_row("claude_stage1_v2_source_reviewer")],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[_source_pool_row()],
    )
    assert report["valid"] is True
    assert report["llm_reviewed_rows"] == 1


def test_source_review_validator_prefers_evidence_rich_duplicate_source_pool_row() -> None:
    scheduling_only_row = {"source_atomic_commit_id": "org/repo@deadbeef", "current_quality_status": "candidate_accepted"}

    report = validate_source_review_sidecar_rows(
        [_sidecar_row("claude_stage1_v2_source_reviewer")],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[_source_pool_row(), scheduling_only_row],
    )

    assert report["valid"] is True


def test_source_review_validator_rejects_nonhuman_reviewer_without_amendment() -> None:
    report = validate_source_review_sidecar_rows(
        [_sidecar_row("claude_stage1_v2_source_reviewer")],
        source_pool_rows=[_source_pool_row()],
    )
    assert report["valid"] is False
    assert any(err["reason"] == "nonhuman_reviewer_not_covered_by_amendment" for err in report["errors"])


def test_source_review_validator_blocks_llm_minted_human_verification() -> None:
    report = validate_source_review_sidecar_rows(
        [_sidecar_row("claude_stage1_v2_source_reviewer", human_verified=True)],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[_source_pool_row()],
    )
    assert report["valid"] is False
    assert any(err["reason"] == "nonhuman_reviewer_cannot_set_human_verified" for err in report["errors"])


def test_source_review_validator_rejects_duplicate_unknown_hash_mismatch_and_leakage() -> None:
    first = _sidecar_row("claude_stage1_v2_source_reviewer")
    duplicate = _sidecar_row("claude_stage1_v2_source_reviewer")
    unknown = _sidecar_row("claude_stage1_v2_source_reviewer")
    unknown["source_atomic_commit_id"] = "org/repo@unknown"
    unknown["record_hash"] = compute_source_review_record_hash(unknown)
    bad_hash = _sidecar_row("claude_stage1_v2_source_reviewer")
    bad_hash["source_atomic_commit_id"] = "org/repo@bad-hash"
    bad_hash["source_evidence_hash"] = "bad"
    bad_hash["record_hash"] = compute_source_review_record_hash(bad_hash)
    leaked = _sidecar_row("claude_stage1_v2_source_reviewer")
    leaked["source_atomic_commit_id"] = "org/repo@leaked"
    leaked["evidence_source"] = "commit_message"
    leaked["record_hash"] = compute_source_review_record_hash(leaked)

    report = validate_source_review_sidecar_rows(
        [first, duplicate, unknown, bad_hash, leaked],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[
            _source_pool_row(),
            {"source_atomic_commit_id": "org/repo@bad-hash", "normalized_diff_hash": "expected", "edit_unit_fingerprint": "unit"},
            {"source_atomic_commit_id": "org/repo@leaked", "normalized_diff_hash": "diff", "edit_unit_fingerprint": "unit"},
        ],
    )

    reasons = {err["reason"] for err in report["errors"]}
    assert "duplicate_active_source_record" in reasons
    assert "unknown_source_atomic_commit_id" in reasons
    assert "source_evidence_hash_mismatch" in reasons
    assert "forbidden_metadata_leakage" in reasons


def test_source_review_validator_rejects_missing_rationale_invalid_decision_and_bad_record_hash() -> None:
    row = _sidecar_row("claude_stage1_v2_source_reviewer")
    row["review_decision"] = "maybe_atomic"
    row["review_reason"] = ""
    row["record_hash"] = "bad"

    report = validate_source_review_sidecar_rows(
        [row],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[_source_pool_row()],
    )

    reasons = {err["reason"] for err in report["errors"]}
    assert "invalid_decision:maybe_atomic" in reasons
    assert "empty_review_reason" in reasons
    assert "record_hash_mismatch" in reasons


def test_source_review_validator_allows_supersession_chain() -> None:
    original = _sidecar_row("claude_stage1_v2_source_reviewer")
    original["manual_review_status"] = "superseded"
    original["record_hash"] = compute_source_review_record_hash(original)
    replacement = _sidecar_row("claude_stage1_v2_source_reviewer")
    replacement["review_decision"] = "reject_low_evidence"
    replacement["supersedes_record_hash"] = original["record_hash"]
    replacement["review_reason"] = "Reliable edit-unit evidence is missing."
    replacement["record_hash"] = compute_source_review_record_hash(replacement)
    original["superseded_by_record_hash"] = replacement["record_hash"]
    original["record_hash"] = compute_source_review_record_hash(original)
    replacement["supersedes_record_hash"] = original["record_hash"]
    replacement["record_hash"] = compute_source_review_record_hash(replacement)

    report = validate_source_review_sidecar_rows(
        [original, replacement],
        llm_annotation_amendment=AMENDMENT,
        source_pool_rows=[_source_pool_row()],
    )

    assert report["valid"] is True
    assert report["superseded_rows"] == 1
