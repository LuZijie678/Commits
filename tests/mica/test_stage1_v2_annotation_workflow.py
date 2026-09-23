from __future__ import annotations

from code.mica.stage1_v2.annotation_workflow import (
    build_adjudicated_asset,
    compute_post_adjudication_quality_report,
    compute_pre_adjudication_agreement,
    export_adjudication_queue,
    export_independent_blind_review_sample,
    import_adjudicated_annotations,
    import_annotation_a,
    import_annotation_b,
    score_qualification_submission,
    validate_independent_annotations,
)


def _count_row(sample_id: str) -> dict[str, object]:
    return {
        "schema_version": "mica-stage1-v2-real-count-candidate-v1",
        "sample_id": sample_id,
        "commit_id": sample_id,
        "repository": "acme/demo",
        "diff_reference": {"repo": "acme/demo", "sha": sample_id},
        "split_candidate": "train",
        "source_type": "hard_b",
        "current_weak_label": "hard_single",
        "annotation_status": "pending",
        "annotator_a_exact_k": None,
        "annotator_b_exact_k": None,
        "adjudicated_exact_k": None,
        "annotator_a_id": None,
        "annotator_b_id": None,
        "adjudicator_id": None,
        "adjudication_status": None,
        "guideline_version": "count-guideline-v1",
        "annotation_version": "pilot-v1",
        "annotation_history": [],
    }


def _alignment_annotation(intent_object: str) -> dict[str, object]:
    return {
        "exact_k": 1,
        "unit_labels": {
            "u1": {"label": "foreground", "intent_id": "intent_1"},
            "u2": {"label": "background", "background_type": "formatting"},
        },
        "intents": [{"intent_id": "intent_1", "action": "update", "object": intent_object, "scope": "src"}],
    }


def _alignment_row(sample_id: str) -> dict[str, object]:
    return {
        "schema_version": "mica-stage1-v2-real-adjudicated-record-v1",
        "sample_id": sample_id,
        "commit_id": sample_id,
        "repository": "acme/demo",
        "diff_reference": {"repo": "acme/demo", "sha": sample_id},
        "split_candidate": "pilot",
        "annotation_status": "pending",
        "blind_status": "hidden",
        "model_prediction_hidden": True,
        "commit_message_hidden": True,
        "split_hidden": True,
        "annotation_a": None,
        "annotation_b": None,
        "adjudicated_annotation": None,
        "annotator_a_id": None,
        "annotator_b_id": None,
        "adjudicator_id": None,
        "adjudication_reason": None,
        "guideline_version": "align-guideline-v1",
        "annotation_version": "pilot-v1",
        "edit_units": [{"unit_id": "u1", "file_path": "src/main.py"}],
        "metadata": {"language": "python", "path_roles": ["source"], "hunk_count": 1},
        "annotation_history": [],
    }


def test_count_annotations_require_double_annotation_before_adjudication() -> None:
    rows = [_count_row("c1"), _count_row("c2")]
    imported_a = import_annotation_a(
        rows,
        [{"sample_id": "c1", "exact_k": 2}, {"sample_id": "c2", "exact_k": 2}],
        annotator_id="ann-a",
        guideline_version="count-guideline-v1",
        annotation_version="pilot-v1",
        timestamp="2026-07-24T10:00:00+00:00",
    )
    imported_ab = import_annotation_b(
        imported_a["rows"],
        [{"sample_id": "c1", "exact_k": 2}, {"sample_id": "c2", "exact_k": 3}],
        annotator_id="ann-b",
        guideline_version="count-guideline-v1",
        annotation_version="pilot-v1",
        timestamp="2026-07-24T10:05:00+00:00",
    )
    validated = validate_independent_annotations(imported_ab["rows"])
    queue = export_adjudication_queue(validated["rows"], timestamp="2026-07-24T10:10:00+00:00")

    assert validated["status_counts"]["agreement"] == 1
    assert validated["status_counts"]["conflict"] == 1
    assert len(queue["adjudication_queue"]) == 1
    assert queue["adjudication_queue"][0]["sample_id"] == "c2"


def test_alignment_adjudication_preserves_raw_annotations_and_builds_asset_after_adjudication() -> None:
    rows = [_alignment_row("a1")]
    imported_a = import_annotation_a(
        rows,
        [{"sample_id": "a1", "annotation": _alignment_annotation("parser")}],
        annotator_id="ann-a",
        guideline_version="align-guideline-v1",
        annotation_version="pilot-v1",
        timestamp="2026-07-24T11:00:00+00:00",
    )
    imported_ab = import_annotation_b(
        imported_a["rows"],
        [{"sample_id": "a1", "annotation": _alignment_annotation("token validator")}],
        annotator_id="ann-b",
        guideline_version="align-guideline-v1",
        annotation_version="pilot-v1",
        timestamp="2026-07-24T11:05:00+00:00",
    )
    validated = validate_independent_annotations(imported_ab["rows"])
    queue = export_adjudication_queue(validated["rows"], timestamp="2026-07-24T11:10:00+00:00")
    adjudicated = import_adjudicated_annotations(
        queue["rows"],
        [
            {
                "sample_id": "a1",
                "adjudicated_annotation": _alignment_annotation("token validator"),
                "adjudication_reason": "supporting test is background, parser rename is foreground",
            }
        ],
        adjudicator_id="adj-1",
        guideline_version="align-guideline-v1",
        annotation_version="pilot-v1",
        timestamp="2026-07-24T11:15:00+00:00",
    )
    asset = build_adjudicated_asset(adjudicated["rows"])

    row = asset["rows"][0]
    assert row["annotation_a"]["intents"][0]["object"] == "parser"
    assert row["annotation_b"]["intents"][0]["object"] == "token validator"
    assert row["adjudicated_annotation"]["intents"][0]["object"] == "token validator"
    assert row["annotation_status"] == "eligible_for_asset"


def test_unadjudicated_conflict_cannot_enter_adjudicated_asset() -> None:
    row = _alignment_row("a2")
    row["annotation_status"] = "conflict"
    row["annotation_a"] = _alignment_annotation("parser")
    row["annotation_b"] = _alignment_annotation("token validator")

    asset = build_adjudicated_asset([row])

    assert asset["row_count"] == 0


def test_blind_review_sampling_and_post_adjudication_quality_report() -> None:
    rows = []
    for sample_id in ("a1", "a2"):
        row = _alignment_row(sample_id)
        row["annotation_status"] = "adjudicated"
        row["annotation_a"] = _alignment_annotation("parser")
        row["annotation_b"] = _alignment_annotation("parser")
        row["adjudicated_annotation"] = _alignment_annotation("parser")
        row["annotator_a_id"] = "ann-a"
        row["annotator_b_id"] = "ann-b"
        row["adjudicator_id"] = "adj-1"
        rows.append(row)

    blind = export_independent_blind_review_sample(rows, fraction=0.5, seed=7)
    report = compute_post_adjudication_quality_report(rows)

    assert blind["row_count"] == 1
    assert blind["rows"][0]["blind_review_status"] == "pending"
    assert report["adjudicated_count"] == 2
    assert report["agreement_metrics"]["real_alignment"]["double_annotated_count"] == 2


def test_qualification_scoring_uses_private_answer_key_only() -> None:
    score = score_qualification_submission(
        answers=[
            {"qualification_id": "q1", "exact_k": 2},
            {"qualification_id": "q2", "exact_k": 1},
        ],
        answer_key=[
            {"qualification_id": "q1", "exact_k": 2},
            {"qualification_id": "q2", "exact_k": 3},
        ],
    )
    assert score["exact_k_accuracy"] == 0.5
    assert score["passes"] is False


def test_pre_adjudication_agreement_reports_real_count_kappa() -> None:
    rows = [
        {
            **_count_row("c1"),
            "annotation_status": "agreement",
            "annotator_a_exact_k": 1,
            "annotator_b_exact_k": 1,
            "annotator_a_id": "ann-a",
            "annotator_b_id": "ann-b",
            "leakage_group": "repo::c1",
            "normalized_diff_hash": "diff-c1",
        },
        {
            **_count_row("c2"),
            "annotation_status": "conflict",
            "annotator_a_exact_k": 2,
            "annotator_b_exact_k": 3,
            "annotator_a_id": "ann-a",
            "annotator_b_id": "ann-b",
            "leakage_group": "repo::c2",
            "normalized_diff_hash": "diff-c2",
        },
    ]

    agreement = compute_pre_adjudication_agreement(rows)

    assert agreement["real_count"]["double_annotated_count"] == 2
    assert agreement["real_count"]["weighted_kappa"] is not None
