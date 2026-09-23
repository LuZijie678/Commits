from __future__ import annotations

from pathlib import Path

from code.mica.io_utils import write_jsonl
from code.mica.stage1_v2.synthetic_scale import materialize_synthetic_scale_and_review_assets


def _synthetic_row(sample_id: str, source_a: str, source_b: str, family_a: str, family_b: str, repository: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "repository": repository,
        "source_atomic_commit_ids": [source_a, source_b],
        "atomic_family_id": family_a,
        "construction_group": f"group::{sample_id}",
        "gold_k": 2,
        "edit_units": [
            {"file_path": "src/main.py", "file_role": "source", "language": "python"},
            {"file_path": "tests/test_main.py", "file_role": "test", "language": "python"},
        ],
    }


def _source_row(source_id: str, family_id: str, repository: str, *, manual: bool) -> dict[str, object]:
    return {
        "sample_id": f"atomic::{source_id}",
        "repository": repository,
        "commit_id": source_id.split("@")[-1],
        "source_atomic_commit_id": source_id,
        "source_atomic_commit_ids": [source_id],
        "atomic_family_id": family_id,
        "path_roles": ["source"],
        "edit_units": [{"file_path": "src/main.py", "file_role": "source"}],
        "reasons": ["high_file_count"] if manual else [],
        "source_quality_status": "source_quality_unverified" if manual else "candidate_accepted",
    }


def test_small_synthetic_materialization_stays_candidate_and_not_frozen(tmp_path: Path) -> None:
    protocol_spec = {"protocol_version": "stage1-v2-protocol"}
    synthetic_root = tmp_path / "synthetic"
    atomic_root = tmp_path / "atomic"
    synthetic_root.mkdir()
    atomic_root.mkdir()
    write_jsonl(
        synthetic_root / "synthetic_train.jsonl",
        [_synthetic_row("train_1", "repo@a1", "repo@a2", "fam_a", "fam_b", "acme/repo")],
    )
    write_jsonl(
        synthetic_root / "synthetic_dev.jsonl",
        [_synthetic_row("dev_1", "repo@b1", "repo@b2", "fam_c", "fam_d", "acme/repo")],
    )
    write_jsonl(
        synthetic_root / "synthetic_control_test.jsonl",
        [_synthetic_row("ctrl_1", "repo@c1", "repo@c2", "fam_e", "fam_f", "acme/repo")],
    )
    write_jsonl(
        atomic_root / "accepted_atomic_sources.jsonl",
        [
            _source_row("repo@a1", "fam_a", "acme/repo", manual=False),
            _source_row("repo@a2", "fam_b", "acme/repo", manual=False),
            _source_row("repo@b1", "fam_c", "acme/repo", manual=False),
        ],
    )
    write_jsonl(
        atomic_root / "manual_review_queue.jsonl",
        [_source_row("repo@c1", "fam_d", "acme/repo", manual=True)],
    )

    result = materialize_synthetic_scale_and_review_assets(
        protocol_spec=protocol_spec,
        train_path=synthetic_root / "synthetic_train.jsonl",
        dev_path=synthetic_root / "synthetic_dev.jsonl",
        control_path=synthetic_root / "synthetic_control_test.jsonl",
        accepted_atomic_sources_path=atomic_root / "accepted_atomic_sources.jsonl",
        manual_review_path=atomic_root / "manual_review_queue.jsonl",
        output_root=synthetic_root,
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    audit = result["synthetic_scale_audit"]
    target_plan = result["synthetic_formal_target_plan"]
    review_summary = result["review_summary"]

    assert audit["current_status"]["candidate_materialized"] is True
    assert audit["current_status"]["pipeline_validation_complete"] is True
    assert audit["current_status"]["scale_insufficient_for_formal_training"] is True
    assert audit["current_status"]["not_frozen_training_asset"] is True
    assert target_plan["formal_scale_freeze_blocked"] is True
    assert "required_atomic_sources_need_human_verification" in target_plan["blocking_reasons"]
    assert review_summary["required_atomic_sources_human_verified"] is False


def test_required_atomic_sources_are_deduplicated_between_current_and_formal_use(tmp_path: Path) -> None:
    protocol_spec = {"protocol_version": "stage1-v2-protocol"}
    synthetic_root = tmp_path / "synthetic"
    atomic_root = tmp_path / "atomic_source_pool"
    synthetic_root.mkdir()
    atomic_root.mkdir()
    shared_source = "repo@shared"
    write_jsonl(
        synthetic_root / "synthetic_train.jsonl",
        [_synthetic_row("train_1", shared_source, "repo@other", "fam_a", "fam_b", "acme/repo")],
    )
    write_jsonl(synthetic_root / "synthetic_dev.jsonl", [])
    write_jsonl(synthetic_root / "synthetic_control_test.jsonl", [])
    write_jsonl(
        atomic_root / "accepted_atomic_sources.jsonl",
        [
            _source_row(shared_source, "fam_a", "acme/repo", manual=False),
            _source_row("repo@other", "fam_b", "acme/repo", manual=False),
        ],
    )
    write_jsonl(
        atomic_root / "manual_review_queue.jsonl",
        [_source_row("repo@manual", "fam_c", "acme/repo", manual=True)],
    )

    result = materialize_synthetic_scale_and_review_assets(
        protocol_spec=protocol_spec,
        train_path=synthetic_root / "synthetic_train.jsonl",
        dev_path=synthetic_root / "synthetic_dev.jsonl",
        control_path=synthetic_root / "synthetic_control_test.jsonl",
        accepted_atomic_sources_path=atomic_root / "accepted_atomic_sources.jsonl",
        manual_review_path=atomic_root / "manual_review_queue.jsonl",
        output_root=synthetic_root,
        creation_git_sha="test-sha",
        created_at="2026-07-24T00:00:00+00:00",
    )

    critical_rows = list(Path(result["critical_review_path"]).read_text(encoding="utf-8").splitlines())
    assert len(critical_rows) == len(set(critical_rows))
