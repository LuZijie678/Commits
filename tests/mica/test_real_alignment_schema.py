from __future__ import annotations

from code.mica.annotation.real_alignment_schema import (
    annotation_to_gold_maps,
    normalize_alignment_annotation,
    summarize_annotation_rows,
    validate_alignment_annotation,
)
from code.mica.data.real_alignment import validate_real_alignment_rows


def _annotation_row() -> dict:
    return {
        "sample_id": "s1",
        "repo": "repo/a",
        "sha": "abc123",
        "split": "calib",
        "scope_status": "in_scope",
        "annotator_id": "ann1",
        "annotation_round": 1,
        "edit_units": [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}],
        "intent_groups": [["u1", "u2"], ["u3"]],
        "intents": [
            {"intent_id": "intent_1", "action": "fix", "object": "auth validation", "scope": "auth", "unit_ids": ["u1", "u2"]},
            {"intent_id": "intent_2", "action": "update", "object": "auth docs", "scope": "docs", "unit_ids": ["u3"]},
        ],
        "intent_count": 2,
        "unit_to_intent": {"u1": "intent_1", "u2": "intent_1", "u3": "intent_2"},
        "hunk_to_intent": {"h1": "intent_1"},
        "major_minor_flags": {"intent_1": "major", "intent_2": "minor"},
        "annotator_confidence": 0.8,
        "uncertain_units": ["u3"],
        "shared_support_units": [],
        "mixed_units": [],
        "background_units": [],
        "notes": "fixture",
        "created_at": "2026-06-19T12:00:00Z",
        "schema_version": "v1",
    }


def test_normalize_alignment_annotation_and_maps() -> None:
    normalized = normalize_alignment_annotation(_annotation_row())
    payload = annotation_to_gold_maps(normalized)

    assert normalized["annotation_status"] == "single_annotated"
    assert payload["gold_unit_to_intent"]["u1"] == "intent_1"
    assert "u3" not in payload["gold_unit_to_intent"]
    assert payload["excluded_alignment_unit_ids"] == ["u3"]
    assert payload["alignment_mask_protocol"] == "exclude_uncertain_shared_support_mixed_from_primary_alignment"


def test_validate_alignment_annotation_detects_group_mismatch() -> None:
    row = _annotation_row()
    row["unit_to_intent"]["u2"] = "intent_2"

    result = validate_alignment_annotation(row)

    assert result["valid"] is False
    assert "intent_group_mismatch" in result["errors"]


def test_summarize_annotation_rows_tracks_status_and_confidence() -> None:
    adjudicated = _annotation_row()
    adjudicated["annotator_id"] = "adj1"
    adjudicated["adjudicator_id"] = "judge1"
    adjudicated["annotation_status"] = "adjudicated"
    summary = summarize_annotation_rows([_annotation_row(), adjudicated])

    assert summary["row_count"] == 2
    assert summary["annotation_status_counts"]["single_annotated"] == 1
    assert summary["annotation_status_counts"]["adjudicated"] == 1
    assert summary["mean_annotator_confidence"] == 0.8


def _runner_alignment_row() -> dict:
    return {
        "sample_id": "s1",
        "split": "train",
        "scope_status": "in_scope",
        "gold_count": 2,
        "edit_units": [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}],
        "gold_unit_to_intent": {"u1": "I1", "u2": "I1", "u3": "I2"},
        "intents": [
            {"intent_id": "I1", "action": "fix", "object": "auth validation", "unit_ids": ["u1", "u2"]},
            {"intent_id": "I2", "action": "update", "object": "auth docs", "unit_ids": ["u3"]},
        ],
        "background_units": [],
        "shared_support_units": [],
        "uncertain_units": [],
        "mixed_units": [],
        "annotation_status": "adjudicated",
        "adjudicator_id": "judge1",
    }


def test_validate_real_alignment_rows_accepts_closed_action_object_ontology() -> None:
    result = validate_real_alignment_rows([_runner_alignment_row()])

    assert result["valid"] is True
    assert result["ontology_valid"] is True
    assert result["gold_count_mismatch_count"] == 0
    assert result["excluded_unit_overlap_count"] == 0


def test_validate_real_alignment_rows_rejects_untraceable_and_overlapping_units() -> None:
    row = _runner_alignment_row()
    row["gold_unit_to_intent"]["u4"] = "I2"
    row["intents"][1]["unit_ids"].append("u4")
    row["background_units"] = ["u2"]
    row["uncertain_units"] = ["u2"]

    result = validate_real_alignment_rows([row])

    assert result["valid"] is False
    assert result["ontology_valid"] is False
    assert result["gold_unit_not_in_edit_units_count"] == 1
    assert result["intent_unit_not_in_edit_units_count"] == 1
    assert result["excluded_unit_overlap_count"] == 1


def test_validate_real_alignment_rows_requires_in_scope_gold_count_to_match_intents() -> None:
    row = _runner_alignment_row()
    row["gold_count"] = 3

    result = validate_real_alignment_rows([row])

    assert result["valid"] is False
    assert result["gold_count_mismatch_count"] == 1


def test_validate_real_alignment_rows_rejects_out_of_scope_gold_alignment() -> None:
    row = _runner_alignment_row()
    row["scope_status"] = "out_of_scope"

    result = validate_real_alignment_rows([row])

    assert result["valid"] is False
    assert result["out_of_scope_with_gold_alignment_count"] == 1
