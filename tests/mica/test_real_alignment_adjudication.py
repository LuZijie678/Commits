from __future__ import annotations

from code.mica.annotation.adjudication import (
    build_adjudication_item,
    summarize_adjudication_status,
    validate_adjudicated_annotation,
)


def test_build_adjudication_item_marks_disagreement_units() -> None:
    rows = [
        {
            "sample_id": "s1",
            "annotator_id": "a1",
            "intent_count": 1,
            "unit_to_intent": {"u1": "i1", "u2": "i1"},
        },
        {
            "sample_id": "s1",
            "annotator_id": "a2",
            "intent_count": 2,
            "unit_to_intent": {"u1": "j1", "u2": "j2"},
        },
    ]

    item = build_adjudication_item(rows)

    assert item["requires_adjudication"] is True
    assert sorted(item["disagreement_units"]) == ["u1", "u2"]
    assert item["count_disagreement"] is True


def test_validate_adjudicated_annotation_requires_adjudicator() -> None:
    row = {
        "sample_id": "s1",
        "annotation_status": "adjudicated",
        "intent_count": 1,
        "intent_groups": [["u1"]],
        "unit_to_intent": {"u1": "i1"},
    }

    result = validate_adjudicated_annotation(row)

    assert result["valid"] is False
    assert "missing_adjudicator_id" in result["errors"]


def test_summarize_adjudication_status_counts_states() -> None:
    summary = summarize_adjudication_status(
        [
            {"sample_id": "s1", "annotation_status": "single_annotated"},
            {"sample_id": "s2", "annotation_status": "double_annotated"},
            {"sample_id": "s3", "annotation_status": "adjudicated"},
        ]
    )

    assert summary["annotation_status_counts"]["single_annotated"] == 1
    assert summary["annotation_status_counts"]["double_annotated"] == 1
    assert summary["annotation_status_counts"]["adjudicated"] == 1
