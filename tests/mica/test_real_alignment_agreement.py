from __future__ import annotations

from code.mica.annotation.agreement import (
    pairwise_agreement_between_annotators,
    summarize_double_annotation_agreement,
)


def _row(sample_id: str, annotator_id: str, mapping: dict[str, str], count: int = 2) -> dict:
    return {
        "sample_id": sample_id,
        "annotator_id": annotator_id,
        "intent_count": count,
        "unit_to_intent": mapping,
        "annotation_status": "double_annotated",
    }


def test_pairwise_agreement_between_annotators_uses_shared_metrics() -> None:
    left = _row("s1", "a1", {"u1": "i1", "u2": "i1", "u3": "i2"})
    right = _row("s1", "a2", {"u1": "j1", "u2": "j1", "u3": "j2"})

    result = pairwise_agreement_between_annotators(left, right)

    assert result["pairwise_f1"] == 1.0
    assert result["ari"] == 1.0
    assert result["nmi"] == 1.0
    assert result["count_match"] is True


def test_summarize_double_annotation_agreement_detects_count_disagreement() -> None:
    rows = [
        _row("s1", "a1", {"u1": "i1", "u2": "i1"}, count=1),
        _row("s1", "a2", {"u1": "j1", "u2": "j2"}, count=2),
    ]

    summary = summarize_double_annotation_agreement(rows)

    assert summary["double_annotated_sample_count"] == 1
    assert summary["count_agreement_rate"] == 0.0
    assert summary["mean_pairwise_f1"] < 1.0
