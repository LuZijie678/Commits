from __future__ import annotations

import json
from pathlib import Path

from code.mica.data.asset_registry import load_asset_registry, resolve_asset_path
from code.mica.io_utils import read_json, read_jsonl
from code.mica.runners.run_kmax_exact_count_audit import run_kmax_exact_count_audit
from code.mica.runners.run_stage1_candidate_validation import run_stage1_candidate_validation
from code.mica.runners.run_stage1_formal_training import run_stage1_formal_training
from code.mica.runners.run_stage1_threshold_selection import run_stage1_threshold_selection


def _stage1_protocol_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "stage": "stage1",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "advisor_stage1_validation_approved": False,
                "stage2_allowed": False,
                "schedule": {
                    "epochs": 1,
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                },
                "assignment_schedule": {"tau_start": 1.5, "tau_end": 0.7},
                "dual_cardinality": {"alpha_pb": 0.5},
                "null_slot": {"enabled": False},
                "evidence_graph": {"use_attention_bias": True},
            }
        ),
        encoding="utf-8",
    )


def _thresholds(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "threshold_status": "candidate_sanity_thresholds_pending_advisor_confirmation",
                "k2_split_recall_min": 0.0,
                "second_slot_gold_recall_min": 0.0,
                "unit_accuracy_gain_over_all_one_min": -1.0,
                "slot_collapse_rate_max": 1.0,
                "count_accuracy_min": 0.0,
                "over_split_rate_on_k1_max": 1.0,
            }
        ),
        encoding="utf-8",
    )


def _manifest_row(*, sample_id: str, split: str, source_kind: str, source_type: str, gold_count: int, repo: str) -> dict:
    if gold_count == 1:
        return {
            "sample_id": sample_id,
            "commit_id": sample_id,
            "repo": repo,
            "split": split,
            "source_kind": source_kind,
            "source_type": source_type,
            "cardinality_label_type": "exact_k1_gold",
            "gold_provenance_status": "strict_unique_atomic",
            "leakage_group": f"{repo}:{sample_id}",
            "construction_group": f"{repo}:{sample_id}",
            "gold_count": 1,
            "sample_weight": 1.0,
            "edit_units": [
                {
                    "unit_id": f"{sample_id}_u1",
                    "hunk_id": f"{sample_id}_h1",
                    "file_path": "src/auth.py",
                    "file_role": "source",
                    "language": "python",
                    "patch_text": "@@",
                    "added_lines": ["+ auth = 1"],
                    "deleted_lines": [],
                    "changed_identifiers": ["auth"],
                }
            ],
            "gold_unit_to_intent": {f"{sample_id}_u1": "intent_0"},
            "gold_hunk_to_intent": {f"{sample_id}_h1": "intent_0"},
        }
    return {
        "sample_id": sample_id,
        "commit_id": sample_id,
        "repo": repo,
        "split": split,
        "source_kind": source_kind,
        "source_type": source_type,
        "cardinality_label_type": "exact_k2_gold",
        "gold_provenance_status": "synthetic_construction_gold",
        "leakage_group": f"{repo}:{sample_id}",
        "construction_group": f"{repo}:{sample_id}",
        "gold_count": 2,
        "sample_weight": 1.0,
        "edit_units": [
            {
                "unit_id": f"{sample_id}_u1",
                "hunk_id": f"{sample_id}_h1",
                "file_path": "src/auth.py",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ auth = 1"],
                "deleted_lines": [],
                "changed_identifiers": ["auth"],
            },
            {
                "unit_id": f"{sample_id}_u2",
                "hunk_id": f"{sample_id}_h2",
                "file_path": "tests/auth_test.py",
                "file_role": "test",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ assert auth"],
                "deleted_lines": [],
                "changed_identifiers": ["auth"],
            },
        ],
        "gold_unit_to_intent": {
            f"{sample_id}_u1": "intent_0",
            f"{sample_id}_u2": "intent_1",
        },
        "gold_hunk_to_intent": {
            f"{sample_id}_h1": "intent_0",
            f"{sample_id}_h2": "intent_1",
        },
    }


def _write_formal_asset(path: Path, *, split: str, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": path.stem,
                "split": split,
                "formal_ready": True,
                "summary": {
                    "record_count": len(rows),
                    "repo_count": len({row.get("repo") for row in rows}),
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def _write_registry(path: Path, *, assets: dict[str, dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-data-asset-registry-v2",
                "registry_status": "formal_assets_populated",
                "assets": assets,
            }
        ),
        encoding="utf-8",
    )


def _asset_entry(path: Path | None, *, split: str, source_pool: str, schema_version: str = "mica-formal-asset-manifest-v1", status: str | None = None) -> dict:
    return {
        "path": str(path) if path is not None else None,
        "status": status or ("frozen" if path is not None else "pending_generation"),
        "schema_version": schema_version,
        "source_pool": source_pool,
        "split": split,
        "record_count": 1 if path is not None else None,
        "checksum": "placeholder" if path is not None else None,
        "created_by": "unit_test",
        "leakage_group_key": "leakage_group",
        "required_for": [],
        "allowed_stages": [],
        "forbidden_stages": [],
        "eval_only": False,
    }


def _stage0_readiness(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "formal_ready": False,
                "Kmax_protocol_frozen": False,
                "kmax_coverage_report": {
                    "train_dev_selection_basis": {
                        "exact_real_multi_intent_row_count": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_formal_training_threshold_selection_and_candidate_validation_chain(tmp_path: Path) -> None:
    spec = tmp_path / "stage1_protocol_spec.json"
    thresholds = tmp_path / "stage1_metric_thresholds.json"
    registry = tmp_path / "data_asset_registry.json"
    stage0 = tmp_path / "stage0_readiness.json"
    _stage1_protocol_spec(spec)
    _thresholds(thresholds)
    _stage0_readiness(stage0)

    k1_train = tmp_path / "k1_train.json"
    k2_train = tmp_path / "k2_train.json"
    k1_dev = tmp_path / "k1_dev.json"
    k2_dev = tmp_path / "k2_dev.json"
    stage1_dev = tmp_path / "stage1_official_dev.json"
    _write_formal_asset(k1_train, split="train", rows=[_manifest_row(sample_id="k1_train", split="train", source_kind="atomic_k1", source_type="step1_high_conf_single", gold_count=1, repo="acme/a")])
    _write_formal_asset(k2_train, split="train", rows=[_manifest_row(sample_id="k2_train", split="train", source_kind="strict_replay", source_type="strict_synthetic", gold_count=2, repo="acme/b")])
    _write_formal_asset(k1_dev, split="dev", rows=[_manifest_row(sample_id="k1_dev", split="dev", source_kind="atomic_k1", source_type="step1_high_conf_single", gold_count=1, repo="acme/c")])
    _write_formal_asset(k2_dev, split="dev", rows=[_manifest_row(sample_id="k2_dev", split="dev", source_kind="strict_replay", source_type="strict_synthetic", gold_count=2, repo="acme/d")])
    _write_formal_asset(stage1_dev, split="dev", rows=read_json(k1_dev)["rows"] + read_json(k2_dev)["rows"])
    _write_registry(
        registry,
        assets={
            "step1_high_conf_single_train": {
                **_asset_entry(k1_train, split="train", source_pool="atomic_pool"),
                "required_for": ["stage1_train"],
                "allowed_stages": ["stage1_train"],
            },
            "strict_synthetic_train": {
                **_asset_entry(k2_train, split="train", source_pool="synthetic_pool"),
                "required_for": ["stage1_train"],
                "allowed_stages": ["stage1_train"],
            },
            "step1_high_conf_single_dev": {
                **_asset_entry(k1_dev, split="dev", source_pool="atomic_pool"),
                "required_for": ["stage1_validation"],
                "allowed_stages": ["stage1_validation"],
            },
            "strict_synthetic_dev": {
                **_asset_entry(k2_dev, split="dev", source_pool="synthetic_pool"),
                "required_for": ["stage1_validation"],
                "allowed_stages": ["stage1_validation"],
            },
            "stage1_official_validation_dev": {
                **_asset_entry(stage1_dev, split="dev", source_pool="combined_stage1_dev_assets"),
                "required_for": ["stage1_candidate_validation", "stage1_threshold_selection"],
                "allowed_stages": ["stage1_candidate_validation", "stage1_threshold_selection"],
            },
            "stage1_official_final_test": {
                **_asset_entry(None, split="test", source_pool="combined_stage1_test_assets", status="pending_generation"),
                "required_for": ["stage1_validation_execute"],
                "allowed_stages": ["stage1_validation_execute"],
                "eval_only": True,
            },
            "stage1_checkpoint_input": {
                **_asset_entry(None, split="n/a", source_pool="stage1_formal_training_runtime", schema_version="mica-checkpoint-v2", status="pending_generation"),
                "required_for": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                "allowed_stages": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
            },
        },
    )

    training_result = run_stage1_formal_training(
        protocol_spec_path=spec,
        asset_registry_path=registry,
        output_root=tmp_path / "stage1_train_out",
        execute=True,
        register_checkpoint=True,
    )
    assert training_result["full_model_checkpoint_written"] is True
    assert training_result["checkpoint_roundtrip_valid"] is True
    updated_registry = load_asset_registry(registry)
    checkpoint_path = Path(resolve_asset_path(updated_registry, "stage1_checkpoint_input") or "")
    assert checkpoint_path.exists()
    assert updated_registry["assets"]["stage1_checkpoint_input"]["path"] is None
    assert updated_registry["assets"]["stage1_checkpoint_input"]["status"] == "candidate_validated"

    threshold_result = run_stage1_threshold_selection(
        asset_registry_path=registry,
        metric_thresholds_path=thresholds,
        output_root=tmp_path / "stage1_threshold_out",
        execute=True,
    )
    assert threshold_result["threshold_candidate_selected"] is True
    updated_thresholds = read_json(thresholds)
    assert updated_thresholds["threshold_status"] == "candidate_selected_pending_approval"
    assert updated_thresholds["selected_checkpoint_hash"]
    assert updated_thresholds["selected_dev_manifest_hash"]

    candidate_result = run_stage1_candidate_validation(
        asset_registry_path=registry,
        metric_thresholds_path=thresholds,
        output_root=tmp_path / "stage1_candidate_out",
        stage0_readiness_path=stage0,
        execute=True,
    )
    assert candidate_result["validation_run_executed"] is True
    assert candidate_result["official_validation_executed"] is False
    assert candidate_result["execution_tier"] == "candidate_nonformal"
    predictions = read_jsonl(tmp_path / "stage1_candidate_out" / "stage1_candidate_validation_predictions.jsonl")
    assert len(predictions) == 2
    readiness = read_json(tmp_path / "stage1_candidate_out" / "stage1_candidate_validation_readiness.json")
    assert "thresholds_pending_approval" in readiness["official_blockers"]
    assert "kmax_coverage_not_frozen" in readiness["official_blockers"]


def test_kmax_exact_count_audit_exports_pending_annotation_queue(tmp_path: Path) -> None:
    registry = tmp_path / "data_asset_registry.json"
    exact_k1 = tmp_path / "hard_b_train.json"
    mweak = tmp_path / "m_weak_train.json"
    _write_formal_asset(
        exact_k1,
        split="train",
        rows=[_manifest_row(sample_id="hardb_1", split="train", source_kind="hard_b", source_type="hard_b", gold_count=1, repo="acme/hardb")],
    )
    _write_formal_asset(
        mweak,
        split="train",
        rows=[
            {
                "sample_id": "mweak_1",
                "commit_id": "mweak_1",
                "repo": "acme/mweak",
                "split": "train",
                "source_kind": "m_weak",
                "source_type": "m_weak",
                "cardinality_label_type": "censored_k_ge_2",
                "weak_label": "censored_k_ge_2",
                "leakage_group": "acme/mweak:mweak_1",
                "edit_units": [],
            }
        ],
    )
    _write_registry(
        registry,
        assets={
            "hard_b_train": _asset_entry(exact_k1, split="train", source_pool="hard_b_pool"),
            "m_weak_train": _asset_entry(mweak, split="train", source_pool="m_weak_pool"),
        },
    )

    result = run_kmax_exact_count_audit(
        asset_registry_path=registry,
        output_root=tmp_path / "kmax_out",
        execute=True,
    )

    assert result["blocked_by_missing_asset"] is True
    report = read_json(tmp_path / "kmax_out" / "kmax_exact_count_report.json")
    queue = read_jsonl(tmp_path / "kmax_out" / "kmax_exact_count_annotation_queue.jsonl")
    assert report["selected_Kmax"]["status"] == "implementation_default_not_final_boundary"
    assert report["annotation_queue_row_count"] == 2
    assert queue[0]["annotation_fields"]["exact_k"] is None
