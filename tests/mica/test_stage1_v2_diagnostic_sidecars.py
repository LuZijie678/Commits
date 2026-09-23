from __future__ import annotations

import json
from pathlib import Path

from code.mica.stage1_v2.audit_log import compute_record_hash


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_ALIGNMENT = REPO_ROOT / "datasets" / "mica" / "stage1_v2" / "real_alignment"
CAMPAIGN = REPO_ROOT / "datasets" / "mica" / "stage1_v2" / "campaign"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_p1_human_review_receipt_stays_diagnostic_only() -> None:
    source_rows = {
        row["sample_id"]: row for row in _read_jsonl(REAL_ALIGNMENT / "calibration_round_2_p1_codex_review_filled.jsonl")
    }
    reviewed_rows = _read_jsonl(REAL_ALIGNMENT / "human_reviewed_calibration_round_2_p1_codex_review.jsonl")
    receipt = json.loads(
        (REAL_ALIGNMENT / "human_review_receipt_calibration_round_2_p1_codex_review.json").read_text(encoding="utf-8")
    )

    assert receipt["record_count"] == 5
    assert receipt["human_verified"] is True
    assert receipt["formal_human_evidence"] is False
    assert receipt["formal_evidence_blocker"] == "not_independent_double_annotation_or_adjudication"
    assert receipt["stage1_v2_training_allowed"] is False
    assert receipt["stage2_entry_allowed"] is False

    assert len(reviewed_rows) == 5
    assert {row["sample_id"] for row in reviewed_rows} == set(source_rows)
    for row in reviewed_rows:
        assert row["human_verified"] is True
        assert row["formal_human_evidence"] is False
        assert row["eligible_for_formal_calibration"] is False
        assert row["stage1_v2_training_allowed"] is False
        assert row["stage2_entry_allowed"] is False
        assert row["source_record_hash"] == compute_record_hash(source_rows[row["sample_id"]])


def test_p2_human_review_receipt_stays_diagnostic_only() -> None:
    rows = _read_jsonl(REAL_ALIGNMENT / "calibration_round_2_p2_codex_review_filled.jsonl")
    reviewed_rows = _read_jsonl(REAL_ALIGNMENT / "human_reviewed_calibration_round_2_p2_codex_review.jsonl")
    receipt = json.loads(
        (REAL_ALIGNMENT / "human_review_receipt_calibration_round_2_p2_codex_review.json").read_text(encoding="utf-8")
    )

    assert len(rows) == 14
    assert len({row["sample_id"] for row in rows}) == 14
    assert {row["review_decision"] for row in rows} == {"usable_k_le_4"}
    assert {row["actor_type"] for row in rows} == {"llm"}
    assert all(row["human_verified"] is False for row in rows)
    assert all(row["formal_human_evidence"] is False for row in rows)
    assert all(row["eligible_for_formal_calibration"] is False for row in rows)
    assert all(row["stage1_v2_training_allowed"] is False for row in rows)
    assert all(row["stage2_entry_allowed"] is False for row in rows)

    changed = {
        row["sample_id"]: (row["codex_exact_k"], row["reviewed_exact_k"])
        for row in rows
        if row["codex_exact_k"] != row["reviewed_exact_k"]
    }
    assert changed == {
        "calibration_round_2_0022": (4, 3),
        "calibration_round_2_0027": (4, 2),
    }

    assert receipt["record_count"] == 14
    assert receipt["human_verified"] is True
    assert receipt["formal_human_evidence"] is False
    assert receipt["stage1_v2_training_allowed"] is False
    assert receipt["stage2_entry_allowed"] is False
    assert len(reviewed_rows) == 14
    assert {row["sample_id"] for row in reviewed_rows} == {row["sample_id"] for row in rows}
    by_id = {row["sample_id"]: row for row in rows}
    for reviewed in reviewed_rows:
        assert reviewed["human_verified"] is True
        assert reviewed["formal_human_evidence"] is False
        assert reviewed["eligible_for_formal_calibration"] is False
        assert reviewed["stage1_v2_training_allowed"] is False
        assert reviewed["stage2_entry_allowed"] is False
        assert reviewed["source_record_hash"] == compute_record_hash(by_id[reviewed["sample_id"]])


def test_p3_human_review_receipt_stays_diagnostic_only() -> None:
    rows = _read_jsonl(REAL_ALIGNMENT / "calibration_round_2_p3_codex_review_filled.jsonl")
    reviewed_rows = _read_jsonl(REAL_ALIGNMENT / "human_reviewed_calibration_round_2_p3_codex_review.jsonl")
    receipt = json.loads(
        (REAL_ALIGNMENT / "human_review_receipt_calibration_round_2_p3_codex_review.json").read_text(encoding="utf-8")
    )
    audit_events = _read_jsonl(CAMPAIGN / "annotation_event_log.jsonl")

    assert len(rows) == 7
    assert len({row["sample_id"] for row in rows}) == 7
    assert {row["review_decision"] for row in rows} == {"accepted_low_risk_diagnostic"}
    assert {row["actor_type"] for row in rows} == {"llm"}
    assert all(row["human_verified"] is False for row in rows)
    assert all(row["formal_human_evidence"] is False for row in rows)
    assert all(row["eligible_for_formal_calibration"] is False for row in rows)
    assert all(row["stage1_v2_training_allowed"] is False for row in rows)
    assert all(row["stage2_entry_allowed"] is False for row in rows)
    assert {row["sample_id"]: row["reviewed_exact_k"] for row in rows} == {
        "calibration_round_2_0005": 1,
        "calibration_round_2_0011": 1,
        "calibration_round_2_0018": 1,
        "calibration_round_2_0021": 1,
        "calibration_round_2_0023": 1,
        "calibration_round_2_0025": 1,
        "calibration_round_2_0028": 3,
    }

    assert receipt["record_count"] == 7
    assert receipt["human_verified"] is True
    assert receipt["formal_human_evidence"] is False
    assert receipt["formal_evidence_blocker"] == "not_independent_double_annotation_or_adjudication"
    assert receipt["stage1_v2_training_allowed"] is False
    assert receipt["stage2_entry_allowed"] is False
    assert len(reviewed_rows) == 7
    assert {row["sample_id"] for row in reviewed_rows} == {row["sample_id"] for row in rows}
    by_id = {row["sample_id"]: row for row in rows}
    for reviewed in reviewed_rows:
        assert reviewed["human_verified"] is True
        assert reviewed["formal_human_evidence"] is False
        assert reviewed["eligible_for_formal_calibration"] is False
        assert reviewed["stage1_v2_training_allowed"] is False
        assert reviewed["stage2_entry_allowed"] is False
        assert reviewed["source_record_hash"] == compute_record_hash(by_id[reviewed["sample_id"]])

    p3_review_events = [
        event
        for event in audit_events
        if event["batch_id"] == "calibration_round_2_p3_review" and event["event_type"] == "reviewed"
    ]
    assert len(p3_review_events) == 7
    assert {event["sample_id"] for event in p3_review_events} == {row["sample_id"] for row in rows}


def test_annotation_readiness_remains_blocked_after_diagnostic_reviews() -> None:
    readiness = json.loads(
        (REPO_ROOT / "datasets" / "mica" / "stage1_v2" / "readiness" / "stage1_v2_annotation_readiness.json").read_text(
            encoding="utf-8"
        )
    )

    assert readiness["annotation_assets_formal_ready"] is False
    assert readiness["stage1_v2_training_allowed"] is False
    assert readiness["stage2_entry_allowed"] is False
    assert readiness["llm_annotation_track"]["p1_codex_review_filled"]["status"] == "human_reviewed_diagnostic_decisions"
    assert readiness["llm_annotation_track"]["p2_codex_review_filled"]["status"] == "human_reviewed_diagnostic_decisions"
    assert readiness["llm_annotation_track"]["p3_codex_review_filled"]["status"] == "human_reviewed_diagnostic_decisions"
