from __future__ import annotations

import json

from code.mica.stage1_v2.reviewed_diagnostic import analyze_reviewed_diagnostic_markings
from code.mica.stage1_v2.reviewed_diagnostic import write_reviewed_diagnostic_outputs


def _reviewed_row(sample_id: str, *, exact_k, exact_k_status: str, assignments: list[dict], notes=None) -> dict:
    return {
        "schema_version": "mica-stage1-v2-human-reviewed-llm-marking-v1",
        "sample_id": sample_id,
        "human_verified": True,
        "formal_human_evidence": False,
        "formal_evidence_blocker": "not_independent_double_annotation_or_adjudication",
        "codex_marking": {
            "sample_id": sample_id,
            "actor_type": "llm",
            "human_verified": False,
            "formal_human_evidence": False,
            "exact_k": exact_k,
            "exact_k_status": exact_k_status,
            "unit_assignments": assignments,
            "review_notes": list(notes or []),
        },
    }


def test_reviewed_diagnostic_analysis_keeps_formal_gates_blocked() -> None:
    rows = [
        _reviewed_row(
            "calibration_round_2_0001",
            exact_k=5,
            exact_k_status="proposed_over_kmax",
            assignments=[{"label": "foreground", "selector": "u0000", "intent_id": "intent_1"}],
        ),
        _reviewed_row(
            "calibration_round_2_0002",
            exact_k=2,
            exact_k_status="proposed_needs_close_review",
            assignments=[
                {"label": "foreground", "selector": "u0000", "intent_id": "intent_1"},
                {"label": "shared_support", "selector": "u0001", "intent_ids": ["intent_1", "intent_2"]},
            ],
            notes=["Check split boundary."],
        ),
        _reviewed_row(
            "calibration_round_2_0003",
            exact_k=1,
            exact_k_status="proposed",
            assignments=[
                {"label": "foreground", "selector": "u0000", "intent_id": "intent_1"},
                {"label": "background", "selector": "u0001", "background_type": "lockfile"},
            ],
        ),
    ]
    blinding_map = {
        "rows": [
            {"sample_id": "calibration_round_2_0001", "repository": "r/a", "provisional_tags": ["probable_k4_or_complex"]},
            {"sample_id": "calibration_round_2_0002", "repository": "r/b", "provisional_tags": ["ambiguous_boundary"]},
            {"sample_id": "calibration_round_2_0003", "repository": "r/c", "provisional_tags": ["probable_k1_regular"]},
        ]
    }

    report, queue, draft = analyze_reviewed_diagnostic_markings(rows, blinding_map=blinding_map, created_at="2026-07-27T00:00:00Z")

    assert report["formal_human_evidence"] is False
    assert report["stage1_v2_training_allowed"] is False
    assert report["stage2_entry_allowed"] is False
    assert report["gate_interpretation"]["pre_adjudication_agreement_usable"] is False
    assert report["priority_distribution"]["p0_blocking_review"] == 1
    assert report["priority_distribution"]["p1_guideline_review"] == 1
    assert report["priority_distribution"]["p2_secondary_review"] == 1
    assert [row["priority"] for row in queue] == ["p0_blocking_review", "p1_guideline_review", "p2_secondary_review"]
    assert all(row["formal_human_evidence"] is False for row in queue)
    assert "not a final frozen guideline" in draft


def test_reviewed_diagnostic_runner_outputs_are_non_formal(tmp_path) -> None:
    reviewed_path = tmp_path / "reviewed.jsonl"
    blinding_path = tmp_path / "blinding.json"
    report_path = tmp_path / "report.json"
    queue_path = tmp_path / "queue.jsonl"
    draft_path = tmp_path / "draft.md"

    row = _reviewed_row(
        "calibration_round_2_0001",
        exact_k=None,
        exact_k_status="overflow_gt_kmax_or_ambiguous",
        assignments=[{"label": "uncertain", "selector": "u0000"}],
    )
    reviewed_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    blinding_path.write_text(json.dumps({"rows": [{"sample_id": "calibration_round_2_0001"}]}), encoding="utf-8")

    result = write_reviewed_diagnostic_outputs(
        reviewed_markings_path=reviewed_path,
        blinding_map_path=blinding_path,
        report_path=report_path,
        followup_queue_path=queue_path,
        guideline_revision_draft_path=draft_path,
        created_at="2026-07-27T00:00:00Z",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    queue = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert result["followup_queue_count"] == 1
    assert report["formal_human_evidence"] is False
    assert report["highest_priority_sample_ids"] == ["calibration_round_2_0001"]
    assert queue[0]["blocked_use"] == [
        "formal_pre_adjudication_agreement",
        "adjudicated_gold",
        "training",
        "stage2_entry",
    ]
    assert "revision_draft_only" in draft_path.read_text(encoding="utf-8")
