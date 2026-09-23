from __future__ import annotations

import json
from pathlib import Path

from code.mica.io_utils import write_json, write_jsonl
from code.mica.stage1_v2.materialization import (
    audit_atomic_source_pool,
    build_annotation_readiness_report,
    build_blinded_alignment_packages,
    build_real_count_candidate_assets,
    materialize_family_safe_synthetic_assets,
)


def test_atomic_source_quality_audit_sends_ambiguous_rows_to_manual_review(tmp_path: Path) -> None:
    csv_path = tmp_path / "atomic.csv"
    csv_path.write_text(
        "\n".join(
            [
                "commit_url,conservative_tier,git_diff,message,model_prob,model_tier,passed_rule_refilter,repo,rule_label,rule_weight,selection_reason,selection_strategy,sha,source_confidence,subject,tau_a,tau_b,type",
                "https://example.com/c1,A,\"diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-a\n+b\",m,1.0,A,true,acme/repo,A,1,ok,rule,aaa,1.0,feat: add parser,0.1,0.2,feat",
                "https://example.com/c2,A,\"diff --git a/vendor/a.min.js b/vendor/a.min.js\n@@ -1 +1 @@\n-a\n+b\",m,1.0,A,true,acme/repo,A,1,ok,rule,aab,1.0,chore: vendor sync,0.1,0.2,chore",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = audit_atomic_source_pool(
        source_csv=csv_path,
        output_root=tmp_path / "audit",
        creation_git_sha="deadbeef",
        protocol_version="stage1-v2-protocol",
        created_at="2026-07-24T00:00:00+00:00",
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    accepted = Path(result["accepted_path"]).read_text(encoding="utf-8").splitlines()
    manual = Path(result["manual_review_path"]).read_text(encoding="utf-8").splitlines()

    assert report["accepted_count"] == 1
    assert report["manual_review_count"] == 1
    assert len(accepted) == 1
    assert len(manual) == 1


def test_materialize_family_safe_synthetic_assets_writes_split_manifests(monkeypatch, tmp_path: Path) -> None:
    accepted_rows = [
        {
            "sample_id": "atomic::acme/repo@a1",
            "commit_id": "a1",
            "repository": "acme/repo",
            "repo": "acme/repo",
            "source_atomic_commit_id": "acme/repo@a1",
            "source_atomic_commit_ids": ["acme/repo@a1"],
            "normalized_diff_hash": "diff-a1",
            "edit_unit_fingerprint": "fp-a1",
            "construction_group": "atomic_source::acme/repo@a1",
            "git_diff": "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-a\n+b",
            "subject": "feat: a1",
            "type": "feat",
            "file_count": 1,
            "hunk_count": 1,
            "changed_lines": 2,
            "path_roles": ["source"],
            "unit_count": 1,
        },
        {
            "sample_id": "atomic::acme/repo@a2",
            "commit_id": "a2",
            "repository": "acme/repo",
            "repo": "acme/repo",
            "source_atomic_commit_id": "acme/repo@a2",
            "source_atomic_commit_ids": ["acme/repo@a2"],
            "normalized_diff_hash": "diff-a2",
            "edit_unit_fingerprint": "fp-a2",
            "construction_group": "atomic_source::acme/repo@a2",
            "git_diff": "diff --git a/src/b.py b/src/b.py\n@@ -1 +1 @@\n-a\n+b",
            "subject": "fix: a2",
            "type": "fix",
            "file_count": 1,
            "hunk_count": 1,
            "changed_lines": 2,
            "path_roles": ["source"],
            "unit_count": 1,
        },
        {
            "sample_id": "atomic::acme/other@b1",
            "commit_id": "b1",
            "repository": "acme/other",
            "repo": "acme/other",
            "source_atomic_commit_id": "acme/other@b1",
            "source_atomic_commit_ids": ["acme/other@b1"],
            "normalized_diff_hash": "diff-b1",
            "edit_unit_fingerprint": "fp-b1",
            "construction_group": "atomic_source::acme/other@b1",
            "git_diff": "diff --git a/src/c.py b/src/c.py\n@@ -1 +1 @@\n-a\n+b",
            "subject": "test: b1",
            "type": "test",
            "file_count": 1,
            "hunk_count": 1,
            "changed_lines": 2,
            "path_roles": ["test"],
            "unit_count": 1,
        },
    ]
    accepted_path = tmp_path / "accepted.jsonl"
    write_jsonl(accepted_path, accepted_rows)

    def fake_run(*, source_csv, output_dir, target_count, split_seed, split_name):
        del source_csv, target_count, split_seed
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        sample = {
            "sample_id": f"{split_name}_0001",
            "repo": "acme/repo",
            "intent_k": 2,
            "construction_type": "same_repo_multi_round_robin_v1",
            "sources": [
                {"repo": "acme/repo", "sha": f"{split_name}_sha1"},
                {"repo": "acme/repo", "sha": f"{split_name}_sha2"},
            ],
            "edit_to_intent": [0, 1],
            "intent_subjects": ["feat: add parser", "test: add case"],
            "intent_types": ["feat", "test"],
            "synthetic_diff": (
                "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-a\n+b\n"
                "diff --git a/tests/test_a.py b/tests/test_a.py\n@@ -1 +1 @@\n-a\n+b"
            ),
            "final_sample_weight": 1.0,
        }
        step3 = output_dir / "synthetic_samples_step3_ready.jsonl"
        rejected = output_dir / "synthetic_samples_precheck_rejected.jsonl"
        write_jsonl(step3, [sample])
        write_jsonl(rejected, [])
        return step3, rejected

    monkeypatch.setattr(
        "code.mica.stage1_v2.materialization._run_step2_construction_for_split",
        fake_run,
    )

    result = materialize_family_safe_synthetic_assets(
        accepted_atomic_source_path=accepted_path,
        output_root=tmp_path / "synthetic",
        creation_git_sha="deadbeef",
        protocol_version="stage1-v2-protocol",
        created_at="2026-07-24T00:00:00+00:00",
        synthetic_target_counts={"train": 1, "dev": 1, "synthetic_control_test": 1},
    )

    assert Path(result["family_map_path"]).exists()
    assert Path(result["split_paths"]["train"]).exists()
    assert Path(result["split_paths"]["dev"]).exists()
    assert Path(result["split_paths"]["synthetic_control_test"]).exists()
    leakage = json.loads(Path(result["leakage_path"]).read_text(encoding="utf-8"))
    assert leakage["list_overlap"]["atomic_source_overlap"]["overlap_count"] == 0


def test_real_count_candidate_assets_exclude_stage1_v1_final_test_and_keep_exact_k_empty(tmp_path: Path) -> None:
    accepted_path = tmp_path / "accepted.jsonl"
    write_jsonl(
        accepted_path,
        [
            {
                "sample_id": "atomic::acme/repo@keep1",
                "commit_id": "keep1",
                "repository": "acme/repo",
                "normalized_diff_hash": "hash-keep1",
                "git_diff": "diff --git a/src/a.py b/src/a.py\n@@ -1 +1 @@\n-a\n+b",
                "edit_units": [],
                "path_roles": ["source"],
                "file_count": 1,
                "hunk_count": 1,
                "changed_lines": 2,
            },
            {
                "sample_id": "atomic::acme/repo@blocked1",
                "commit_id": "blocked1",
                "repository": "acme/repo",
                "normalized_diff_hash": "hash-blocked1",
                "git_diff": "diff --git a/src/b.py b/src/b.py\n@@ -1 +1 @@\n-a\n+b",
                "edit_units": [],
                "path_roles": ["source"],
                "file_count": 1,
                "hunk_count": 1,
                "changed_lines": 2,
            },
        ],
    )
    m_csv = tmp_path / "m.csv"
    m_csv.write_text(
        "\n".join(
            [
                "repo,sha,git_diff,llm_intent_count_estimate,file_count,hunk_count,changed_lines,path_roles,top_dirs,changed_files,dir_count",
                "\"acme/m\",m1,\"diff --git a/src/m.py b/src/m.py\n@@ -1 +1 @@\n-a\n+b\",3,2,2,10,source|test,src|tests,src/m.py|tests/test_m.py,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hard_b_csv = tmp_path / "hard_b.csv"
    hard_b_csv.write_text(
        "\n".join(
            [
                "repo,sha,git_diff,file_count,hunk_count,changed_lines,path_roles,top_dirs,changed_files,dir_count",
                "\"acme/h\",h1,\"diff --git a/src/h.py b/src/h.py\n@@ -1 +1 @@\n-a\n+b\",1,1,2,source,src,src/h.py,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    blocked_manifest = tmp_path / "blocked.json"
    write_json(
        blocked_manifest,
        {
            "rows": [
                {
                    "repository": "acme/repo",
                    "commit_id": "blocked1",
                    "source_atomic_commit_ids": ["acme/repo@blocked1"],
                }
            ]
        },
    )

    result = build_real_count_candidate_assets(
        accepted_atomic_source_path=accepted_path,
        m_verified_csv=m_csv,
        hard_b_csv=hard_b_csv,
        stage1_v1_final_test_manifest=blocked_manifest,
        output_root=tmp_path / "real_count",
        creation_git_sha="deadbeef",
        protocol_version="stage1-v2-protocol",
        created_at="2026-07-24T00:00:00+00:00",
        pilot_target=3,
    )

    pool = [json.loads(line) for line in Path(result["pool_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    excluded = [json.loads(line) for line in Path(result["exclusions_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["commit_id"] for row in pool} == {"keep1", "h1", "m1"}
    assert any(item["reason"] == "stage1_v1_official_final_test_blocklist" for item in excluded)
    assert all(row["annotator_a_exact_k"] is None for row in pool)
    assert all(row["adjudicated_exact_k"] is None for row in pool)


def test_blinded_alignment_packages_hide_commit_message_and_model_fields() -> None:
    rows = [
        {
            "sample_id": "cand1",
            "commit_id": "abc123",
            "repository": "acme/repo",
            "normalized_diff": "diff --git a/src/a.py b/src/a.py",
            "edit_units": [{"unit_id": "u1", "file_path": "src/a.py"}],
            "source_fields": {"language": "python"},
        }
    ]
    annotator_a, annotator_b, adjudicator_template, blinding_map = build_blinded_alignment_packages(
        rows,
        guideline_version="guideline-v1",
        annotation_version="v1",
    )

    assert "commit_message" not in annotator_a[0]
    assert "weak_label" not in annotator_a[0]
    assert "predicted_k" not in annotator_a[0]
    assert "annotation_a" not in annotator_a[0]
    assert "annotation_b" not in annotator_b[0]
    assert adjudicator_template[0]["annotation_a"] is None
    assert blinding_map["rows"][0]["commit_id"] == "abc123"


def test_annotation_readiness_stays_false_without_human_results(tmp_path: Path) -> None:
    protocol = {"protocol_version": "stage1-v2-protocol"}
    registry = {
        "assets": {
            "stage1_v2_real_count_candidate_pool": {"status": "candidate_materialized"},
            "stage1_v2_real_alignment_candidate_pool": {"status": "candidate_materialized"},
        }
    }
    count_queue = tmp_path / "count.jsonl"
    alignment_queue = tmp_path / "alignment.jsonl"
    background_queue = tmp_path / "background.jsonl"
    write_jsonl(count_queue, [{"sample_id": "c1", "annotation_status": "pending"}])
    write_jsonl(alignment_queue, [{"sample_id": "a1", "annotation_status": "pending"}])
    write_jsonl(background_queue, [{"sample_id": "b1", "annotation_status": "pending"}])

    readiness = build_annotation_readiness_report(
        protocol_spec=protocol,
        asset_registry=registry,
        real_count_queue_path=count_queue,
        real_adjudicated_pilot_path=alignment_queue,
        background_queue_path=background_queue,
    )

    assert readiness["real_count_pilot_queue_ready"] is True
    assert readiness["alignment_pilot_queue_ready"] is True
    assert readiness["annotation_assets_formal_ready"] is False
    assert readiness["stage1_v2_training_allowed"] is False
    assert readiness["stage2_entry_allowed"] is False
