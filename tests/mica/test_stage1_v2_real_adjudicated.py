from __future__ import annotations

from code.mica.stage1_v2.real_adjudicated import (
    build_real_adjudicated_annotation_queue,
    sample_real_adjudicated_candidates,
    summarize_real_adjudicated_readiness,
    validate_real_adjudicated_record,
)


def _annotation(exact_k: int, unit_labels: dict[str, dict[str, str]], intents: list[dict[str, object]]) -> dict[str, object]:
    return {
        "exact_k": exact_k,
        "unit_labels": unit_labels,
        "intents": intents,
    }


def _row(sample_id: str, repo: str, *, exact_k: int, tags: list[str] | None = None, split_candidate: str = "test") -> dict[str, object]:
    annotation = _annotation(
        exact_k=exact_k,
        unit_labels={
            "u1": {"label": "foreground", "intent_id": "intent_1"},
            "u2": {"label": "background", "background_type": "formatting"},
        },
        intents=[{"intent_id": "intent_1", "action": "update", "object": "parser", "scope": "src"}] * exact_k,
    )
    return {
        "schema_version": "mica-stage1-v2-real-adjudicated-record-v1",
        "sample_id": sample_id,
        "commit_id": sample_id,
        "repository": repo,
        "diff_reference": {"repo": repo, "sha": sample_id, "source_asset": "fixture"},
        "split_candidate": split_candidate,
        "candidate_tags": list(tags or []),
        "annotation_status": "adjudicated",
        "blind_status": "hidden",
        "model_prediction_hidden": True,
        "commit_message_hidden": True,
        "split_hidden": True,
        "annotator_a_id": "ann-a",
        "annotator_b_id": "ann-b",
        "adjudicator_id": "adj-1",
        "annotation_a": annotation,
        "annotation_b": annotation,
        "agreement": {"count_match": True},
        "adjudicated_annotation": annotation,
        "adjudication_reason": "match",
        "blind_review": {"completed": True},
        "guideline_version": "guideline-v1",
        "annotation_version": "v1",
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/main.py"},
            {"unit_id": "u2", "file_path": "src/main.py"},
        ],
        "metadata": {"file_count": 1, "hunk_count": 2, "path_roles": ["source", "config"]},
    }


def test_unadjudicated_record_is_not_final_ready() -> None:
    row = {
        **_row("s1", "acme/demo", exact_k=1),
        "annotation_status": "needs_adjudication",
        "adjudicated_annotation": None,
        "adjudicator_id": None,
    }

    validation = validate_real_adjudicated_record(row)

    assert validation["valid"] is True
    readiness = summarize_real_adjudicated_readiness(
        [row],
        agreement_thresholds={
            "exact_k_weighted_kappa_min": 0.8,
            "split_no_split_kappa_min": 0.8,
            "foreground_background_agreement_min": 0.85,
            "bcubed_agreement_min": 0.8,
            "pairwise_unit_agreement_min": 0.8,
        },
        target_distribution={"k1_regular": 1, "k1_hard_single": 0, "k2": 1, "k3": 1, "k4": 1},
        strata_targets={"same_file_multi_intent": 1},
        repository_limits={"single_repository_max_fraction": 0.5, "top5_repository_max_fraction": 0.9},
    )

    assert readiness["adjudication_complete"] is False
    assert readiness["formal_ready"] is False


def test_benchmark_readiness_fails_on_repository_concentration_and_missing_k_strata() -> None:
    rows = [
        _row("s1", "acme/demo", exact_k=1, tags=["same_file_multi_intent", "background_heavy", "source_test", "source_docs_config", "cross_module", "large_commit", "ambiguous_boundary"]),
        _row("s2", "acme/demo", exact_k=2, tags=["same_file_multi_intent", "background_heavy", "source_test", "source_docs_config", "cross_module", "large_commit", "ambiguous_boundary"]),
    ]

    readiness = summarize_real_adjudicated_readiness(
        rows,
        agreement_thresholds={
            "exact_k_weighted_kappa_min": 0.8,
            "split_no_split_kappa_min": 0.8,
            "foreground_background_agreement_min": 0.85,
            "bcubed_agreement_min": 0.8,
            "pairwise_unit_agreement_min": 0.8,
        },
        target_distribution={"k1_regular": 1, "k1_hard_single": 0, "k2": 1, "k3": 1, "k4": 1},
        strata_targets={
            "same_file_multi_intent": 1,
            "background_heavy": 1,
            "source_test": 1,
            "source_docs_config": 1,
            "cross_module": 1,
            "large_commit": 1,
            "ambiguous_boundary": 1,
        },
        repository_limits={"single_repository_max_fraction": 0.49, "top5_repository_max_fraction": 0.8},
    )

    assert readiness["benchmark_strata"]["k_gates"]["k3"] is False
    assert readiness["benchmark_strata"]["k_gates"]["k4"] is False
    assert readiness["benchmark_strata"]["repository_concentration_passed"] is False
    assert readiness["formal_ready"] is False


def test_real_adjudicated_queue_is_created_as_pending() -> None:
    queue = build_real_adjudicated_annotation_queue(
        [{"sample_id": "cand1", "repo": "acme/demo", "sha": "aaa"}],
        guideline_version="guideline-v1",
        annotation_version="v1",
    )

    assert queue["row_count"] == 1
    assert queue["rows"][0]["annotation_status"] == "pending"
    assert queue["rows"][0]["annotation_a"] is None
    assert queue["rows"][0]["annotation_b"] is None


def test_real_adjudicated_sampler_respects_repository_cap() -> None:
    sampled = sample_real_adjudicated_candidates(
        [
            {"sample_id": "s1", "repo": "acme/demo", "sha": "a1"},
            {"sample_id": "s2", "repo": "acme/demo", "sha": "a2"},
            {"sample_id": "s3", "repo": "acme/other", "sha": "b1"},
        ],
        max_samples=3,
        max_per_repository=1,
        seed=7,
    )

    assert sampled["selected_sample_count"] == 2
    assert sampled["repository_count"] == 2
