from __future__ import annotations

from pathlib import Path

from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl
from code.mica.stage1_v2.annotation_cli import (
    initialize_annotation_draft,
    sanitize_annotation_sample,
    submit_annotation_draft,
)
from code.mica.stage1_v2.campaign import (
    build_annotation_campaign_plan,
    build_annotation_campaign_progress,
    build_annotation_queue_overlap_report,
    build_annotator_registry_template,
    build_calibration_round_assets,
    build_campaign_role_assignment,
    build_deduplicated_human_workload_report,
    build_qualification_execution_assets,
    build_role_conflict_report,
    build_unified_pilot_annotation_index,
)


def _real_count_row(sample_id: str, commit_id: str) -> dict[str, object]:
    return {
        "schema_version": "mica-stage1-v2-real-count-candidate-v1",
        "sample_id": sample_id,
        "commit_id": commit_id,
        "repository": "acme/repo",
        "guideline_version": "stage1-v2-count-guideline-pilot-v1",
        "annotation_version": "stage1-v2-pilot-v1",
        "current_weak_label": "probable_k2",
        "annotator_a_exact_k": None,
        "annotator_b_exact_k": None,
        "adjudicated_exact_k": None,
        "annotation_status": "pending",
    }


def _alignment_row(sample_id: str, commit_id: str, *, tags: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "mica-stage1-v2-real-adjudicated-record-v1",
        "sample_id": sample_id,
        "commit_id": commit_id,
        "repository": "acme/repo",
        "guideline_version": "stage1-v2-alignment-guideline-pilot-v1",
        "annotation_version": "stage1-v2-pilot-v1",
        "normalized_diff": "diff --git a/src/main.py b/src/main.py",
        "edit_units": [{"unit_id": f"{sample_id}::u1", "file_path": "src/main.py", "file_role": "source"}],
        "candidate_tags": list(tags or []),
        "annotation_status": "pending",
        "model_prediction_hidden": True,
        "commit_message_hidden": True,
        "split_hidden": True,
    }


def _background_row(sample_id: str, commit_id: str) -> dict[str, object]:
    return {
        "schema_version": "mica-stage1-v2-background-annotation-queue-v1",
        "sample_id": sample_id,
        "commit_id": commit_id,
        "repository": "acme/repo",
        "guideline_version": "stage1-v2-alignment-guideline-pilot-v1",
        "annotation_status": "pending",
        "edit_units": [{"unit_id": f"{sample_id}::u1", "file_path": "src/main.py", "file_role": "source"}],
    }


def _atomic_review_row(source_id: str) -> dict[str, object]:
    repo, commit_id = source_id.split("@")
    return {
        "schema_version": "mica-stage1-v2-atomic-source-review-queue-v1",
        "source_atomic_commit_id": source_id,
        "commit_id": commit_id,
        "repository": repo,
        "sample_id": f"atomic::{source_id}",
        "human_verified": False,
    }


def test_full_alignment_rows_can_cover_count_and_background_work() -> None:
    overlap = build_annotation_queue_overlap_report(
        real_count_rows=[_real_count_row("count_1", "c1")],
        real_alignment_rows=[_alignment_row("align_1", "c1", tags=["probable_k2"])],
        background_rows=[_background_row("bg_1", "c1")],
        atomic_source_review_rows=[_atomic_review_row("acme/repo@c1")],
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    unified = build_unified_pilot_annotation_index(
        real_count_rows=[_real_count_row("count_1", "c1")],
        real_alignment_rows=[_alignment_row("align_1", "c1", tags=["probable_k2"])],
        background_rows=[_background_row("bg_1", "c1")],
        atomic_source_review_rows=[_atomic_review_row("acme/repo@c1")],
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    report = build_deduplicated_human_workload_report(
        unified_index_rows=unified,
        overlap_report=overlap,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    assert overlap["pairwise_commit_overlap"]["real_count_pilot__vs__real_alignment_pilot"]["overlap_count"] == 1
    assert unified[0]["derivable_assets"]["real_count_exact_k"] is True
    assert unified[0]["derivable_assets"]["background_evaluation"] is True
    assert unified[0]["weak_labels_forbidden_as_gold"] is True
    assert report["count_reusable_from_full_alignment"] == 1
    assert report["background_reusable_from_full_alignment"] == 1


def test_role_conflicts_and_non_human_assignments_block_campaign() -> None:
    registry = build_annotator_registry_template(
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    registry["actors"] = [
        {"actor_id": "ann-1", "actor_type": "human"},
        {"actor_id": "codex-bot", "actor_type": "llm"},
    ]
    manifest = {
        "batches": [
            {
                "campaign_id": "real_alignment_pilot",
                "batch_id": "calibration_round_1",
                "required_roles": ["annotator_a", "annotator_b", "adjudicator"],
            }
        ]
    }
    assignment = build_campaign_role_assignment(
        campaign_manifest=manifest,
        annotator_registry=registry,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    assignment["campaign_assignments"][0]["assignments"] = [
        {"role": "annotator_a", "assigned_actor_id": "ann-1", "assignment_status": "assigned"},
        {"role": "annotator_b", "assigned_actor_id": "ann-1", "assignment_status": "assigned"},
        {"role": "adjudicator", "assigned_actor_id": "codex-bot", "assignment_status": "assigned"},
    ]

    report = build_role_conflict_report(
        annotator_registry=registry,
        role_assignment=assignment,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    assert report["annotation_campaign_blocked"] is True
    assert report["human_staffing_incomplete"] is False
    assert any(item["reason"] == "annotator_a_equals_annotator_b" for item in report["conflicts"])
    assert any(item["actor_id"] == "codex-bot" for item in report["forbidden_assignments"])


def test_llm_annotation_amendment_permits_listed_llm_actors_without_flipping_human_evidence() -> None:
    registry = build_annotator_registry_template(
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    registry["actors"] = [
        {"actor_id": "claude_stage1_v2_annotator_a", "actor_type": "llm"},
        {"actor_id": "claude_stage1_v2_annotator_b", "actor_type": "llm"},
        {"actor_id": "claude_stage1_v2_adjudicator", "actor_type": "llm"},
        {"actor_id": "rogue-bot", "actor_type": "llm"},
    ]
    manifest = {
        "batches": [
            {
                "campaign_id": "real_alignment_pilot",
                "batch_id": "calibration_round_1",
                "required_roles": ["annotator_a", "annotator_b", "adjudicator"],
            }
        ]
    }
    assignment = build_campaign_role_assignment(
        campaign_manifest=manifest,
        annotator_registry=registry,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    assignment["campaign_assignments"][0]["assignments"] = [
        {"role": "annotator_a", "assigned_actor_id": "claude_stage1_v2_annotator_a", "assignment_status": "assigned"},
        {"role": "annotator_b", "assigned_actor_id": "claude_stage1_v2_annotator_b", "assignment_status": "assigned"},
        {"role": "adjudicator", "assigned_actor_id": "rogue-bot", "assignment_status": "assigned"},
    ]
    amendment = {
        "amendment_id": "stage1-v2-llm-annotation-amendment-v1",
        "permitted_actor_ids": [
            "claude_stage1_v2_annotator_a",
            "claude_stage1_v2_annotator_b",
            "claude_stage1_v2_adjudicator",
        ],
    }

    report = build_role_conflict_report(
        annotator_registry=registry,
        role_assignment=assignment,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
        llm_annotation_amendment=amendment,
    )

    permitted_ids = {item["actor_id"] for item in report["amendment_permitted_assignments"]}
    assert permitted_ids == {"claude_stage1_v2_annotator_a", "claude_stage1_v2_annotator_b"}
    assert any(item["actor_id"] == "rogue-bot" for item in report["forbidden_assignments"])
    assert report["annotation_campaign_blocked"] is True
    assert report["llm_annotation_track_active"] is True
    assert report["human_annotation_evidence"] is False
    assert not report["conflicts"]


def test_role_conflict_report_without_amendment_still_blocks_all_llm_actors() -> None:
    registry = build_annotator_registry_template(
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    registry["actors"] = [{"actor_id": "claude_stage1_v2_annotator_a", "actor_type": "llm"}]
    manifest = {
        "batches": [
            {
                "campaign_id": "real_alignment_pilot",
                "batch_id": "calibration_round_1",
                "required_roles": ["annotator_a"],
            }
        ]
    }
    assignment = build_campaign_role_assignment(
        campaign_manifest=manifest,
        annotator_registry=registry,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )
    assignment["campaign_assignments"][0]["assignments"] = [
        {"role": "annotator_a", "assigned_actor_id": "claude_stage1_v2_annotator_a", "assignment_status": "assigned"},
    ]

    report = build_role_conflict_report(
        annotator_registry=registry,
        role_assignment=assignment,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    assert report["annotation_campaign_blocked"] is True
    assert any(item["actor_id"] == "claude_stage1_v2_annotator_a" for item in report["forbidden_assignments"])
    assert "amendment_permitted_assignments" not in report


def test_calibration_round_assets_support_round_label_and_exclusion() -> None:
    pilot_rows = [
        {
            "sample_id": f"s{i:03d}",
            "normalized_diff": f"diff --git a/f{i}.py b/f{i}.py\n+x = {i}\n",
            "edit_units": [{"unit_id": f"s{i:03d}::u0000", "file_path": f"f{i}.py"}],
            "repository": "org/repo",
            "commit_id": f"c{i:03d}",
            "provisional_tags": ["probable_k1_regular"],
        }
        for i in range(10)
    ]
    excluded = {"s000", "s001", "s002"}
    assets = build_calibration_round_assets(
        pilot_rows=pilot_rows,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-26T00:00:00+00:00",
        seed=7,
        target_size=5,
        round_label="calibration_round_2",
        excluded_sample_ids=excluded,
    )
    selected = {row["sample_id"] for row in assets["selected_rows"]}
    assert not (selected & excluded)
    assert all(row["sample_id"].startswith("calibration_round_2_") for row in assets["annotator_a_package"])
    assert assets["result_template"]["batch_id"] == "calibration_round_2"


def test_qualification_packages_do_not_leak_private_answer_key() -> None:
    assets = build_qualification_execution_assets(
        qualification_test_rows=[
            {
                "schema_version": "mica-stage1-v2-qualification-record-v1",
                "qualification_id": "q1",
                "commit_id": "synthetic_control_test::1",
                "repository": "acme/repo",
                "normalized_diff": "diff",
                "edit_units": [],
            }
        ],
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    assert "unit_to_intent" not in assets["annotator_a_package"][0]
    assert "background_units" not in assets["annotator_a_package"][0]
    assert assets["result_template"]["submission_status"] == "pending_human_submission"


def test_calibration_packages_are_blinded_and_reproducible() -> None:
    rows = [
        _alignment_row("align_1", "c1", tags=["probable_k1_regular", "same_file_multi_intent"]),
        _alignment_row("align_2", "c2", tags=["probable_k1_hard_single", "background_heavy"]),
        _alignment_row("align_3", "c3", tags=["probable_k2", "source_test"]),
        _alignment_row("align_4", "c4", tags=["probable_k3", "source_docs_config"]),
        _alignment_row("align_5", "c5", tags=["probable_k4_or_complex", "ambiguous_boundary"]),
    ]
    first = build_calibration_round_assets(
        pilot_rows=rows,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
        seed=7,
        target_size=5,
    )
    second = build_calibration_round_assets(
        pilot_rows=rows,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
        seed=7,
        target_size=5,
    )

    assert [row["sample_id"] for row in first["annotator_a_package"]] == [row["sample_id"] for row in second["annotator_a_package"]]
    assert "commit_message_hidden" in first["annotator_a_package"][0]
    assert "candidate_tags" not in first["annotator_a_package"][0]
    assert "provisional_tags" not in first["annotator_a_package"][0]
    assert first["result_template"]["completed"] is False


def test_annotation_cli_submissions_are_immutable_and_append_only(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.jsonl"
    write_jsonl(queue_path, [_real_count_row("count_1", "c1")])
    audit_log_path = tmp_path / "campaign" / "annotation_event_log.jsonl"
    draft_path = tmp_path / "draft.json"
    submission_root = tmp_path / "submissions"

    draft = initialize_annotation_draft(
        queue_path=queue_path,
        sample_id="count_1",
        annotator_id="human-a",
        actor_role="annotator_a",
        campaign_id="real_count_pilot",
        batch_id="pilot_batch_01",
        output_path=draft_path,
        audit_log_path=audit_log_path,
    )
    assert "current_weak_label" not in sanitize_annotation_sample(_real_count_row("count_1", "c1"))
    draft["response"]["exact_k"] = 2
    write_json(draft_path, draft)

    first = submit_annotation_draft(
        draft_path=draft_path,
        submission_root=submission_root,
        audit_log_path=audit_log_path,
    )
    draft["response"]["exact_k"] = 3
    write_json(draft_path, draft)
    second = submit_annotation_draft(
        draft_path=draft_path,
        submission_root=submission_root,
        audit_log_path=audit_log_path,
    )

    first_payload = read_json(submission_root / "annotator_a" / "human-a" / "count_1" / "submission_r0001.json")
    second_payload = read_json(submission_root / "annotator_a" / "human-a" / "count_1" / "submission_r0002.json")
    audit_events = read_jsonl(audit_log_path)

    assert first["revision_index"] == 1
    assert second["revision_index"] == 2
    assert first_payload["response"]["exact_k"] == 2
    assert second_payload["response"]["exact_k"] == 3
    assert any(event["event_type"] == "submitted" for event in audit_events)
    assert any(event["event_type"] == "superseded" for event in audit_events)


def test_annotation_cli_sanitizes_operator_fields_from_public_sample() -> None:
    row = _real_count_row("count_1", "c1")
    row.update(
        {
            "split_candidate": "train",
            "provisional_tags": ["probable_k2"],
            "leakage_group": "repo::c1",
            "source_fields": {"changed_lines": 2},
            "source_type": "m_weak",
        }
    )

    sanitized = sanitize_annotation_sample(row)

    assert "current_weak_label" not in sanitized
    assert "split_candidate" not in sanitized
    assert "provisional_tags" not in sanitized
    assert "leakage_group" not in sanitized
    assert "source_fields" not in sanitized
    assert "source_type" not in sanitized


def test_codex_source_review_sidecar_is_nonhuman_and_keeps_queue_metadata() -> None:
    sidecar_rows = read_jsonl("datasets/mica/stage1_v2/atomic_source_pool/codex_atomic_source_review_batch_0001.jsonl")
    critical_rows = {
        str(row["source_atomic_commit_id"]): row
        for row in read_jsonl("datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_critical.jsonl")
    }

    assert len(sidecar_rows) == 10
    for row in sidecar_rows:
        source_id = str(row["source_atomic_commit_id"])
        queue_row = critical_rows[source_id]

        assert row["reviewer_id"] == "codex_stage1_v2_reviewer"
        assert row["human_verified"] is False
        assert row["manual_review_status"] == "reviewed"
        assert row["review_decision"] in {"accept_atomic", "reject_low_evidence"}
        assert row["atomic_family_id"] == queue_row["atomic_family_id"]
        assert row["current_quality_status"] == queue_row["current_quality_status"]
        assert row["planned_usage_count"] == queue_row["planned_usage_count"]
        assert row["target_splits"] == queue_row["target_splits"]
        assert row["required_strata"] == queue_row["required_strata"]
        assert row["review_priority"] == queue_row["review_priority"]
        assert row["blocking_asset_ids"] == queue_row["blocking_asset_ids"]


def test_campaign_manifest_and_progress_keep_stage2_blocked() -> None:
    real_count_rows = [_real_count_row(f"count_{idx}", f"count_commit_{idx}") for idx in range(1, 201)]
    real_alignment_rows = [
        _alignment_row(
            f"align_{idx}",
            f"align_commit_{idx}",
            tags=["probable_k2"] if idx % 2 else ["probable_k1_regular"],
        )
        for idx in range(1, 101)
    ]
    background_rows = [_background_row(f"bg_{idx}", f"bg_commit_{idx}") for idx in range(1, 31)]
    manifest = build_annotation_campaign_plan(
        real_count_rows=real_count_rows,
        real_alignment_rows=real_alignment_rows,
        background_rows=background_rows,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
        seed=7,
    )
    role_report = {"annotation_campaign_blocked": True}
    progress = build_annotation_campaign_progress(
        campaign_manifest=manifest,
        role_conflict_report=role_report,
        protocol_version="stage1-v2-protocol",
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    assert manifest["status"] == "pending_human_staffing"
    assert manifest["batch_count"] == len(manifest["batches"])
    assert manifest["total_samples"] == sum(
        int(batch.get("sample_count") or 0)
        for batch in manifest["batches"]
        if batch.get("batch_type") != "blind_review"
    )
    assert "human_staffing_incomplete" in manifest["blocked_reasons"]
    assert any(batch["batch_id"] == "calibration_round_1" for batch in manifest["batches"])
    assert progress["annotation_campaign_blocked"] is True
    assert progress["completed_samples"] == 0
