from __future__ import annotations

from pathlib import Path

from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.data.asset_registry import (
    load_asset_registry,
    register_local_materialization,
    resolve_asset_path,
    summarize_assets,
    validate_asset_registry,
)
from code.mica.io_utils import write_json
from code.mica.models.mica_model import MicaModel
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import build_checkpoint_payload, build_model_checkpoint_payload, save_checkpoint


def _registry() -> dict:
    return {
        "registry_status": "template_only",
        "assets": {
            "strict_replay_manifest": {
                "path": None,
                "stage_use": ["stage2_replay"],
                "required": True,
            },
            "hard_b_test": {
                "path": None,
                "stage_use": ["final_eval_only"],
                "required": False,
                "forbidden_for_training": True,
            },
        },
    }


def test_asset_registry_template_validation_does_not_crash_on_missing_paths(tmp_path) -> None:
    path = tmp_path / "registry.json"
    write_json(path, _registry())

    registry = load_asset_registry(path)
    validation = validate_asset_registry(registry)

    assert registry["registry_status"] == "template_only"
    assert validation["valid"] is True
    assert "strict_replay_manifest" in validation["required_missing_paths"]


def test_resolve_asset_path_returns_none_for_unset_path() -> None:
    assert resolve_asset_path(_registry(), "strict_replay_manifest") is None


def test_summarize_assets_reports_required_and_forbidden_counts() -> None:
    summary = summarize_assets(_registry())

    assert summary["asset_count"] == 2
    assert summary["required_count"] == 1
    assert summary["forbidden_for_training_count"] == 1


def test_asset_registry_validation_distinguishes_schema_materialization_content_and_formal_ready(tmp_path) -> None:
    manifest = tmp_path / "strict_replay_train.json"
    write_json(
        manifest,
        {
            "schema_version": "mica-formal-asset-manifest-v1",
            "asset_name": "strict_replay",
            "split": "train",
            "formal_ready": True,
            "summary": {
                "record_count": 1,
                "repo_count": 1,
                "duplicate_count": 0,
                "leakage_group_overlap_count": 0,
            },
            "rows": [
                {
                    "sample_id": "s1",
                    "split": "train",
                    "repo": "acme/repo",
                    "source_sha": "abc123",
                    "source_type": "strict_synthetic",
                    "cardinality_label_type": "exact_k2_gold",
                    "gold_provenance_status": "synthetic_construction_gold",
                    "leakage_group": "sha:abc123",
                    "construction_group": "synthetic:abc123",
                    "gold_count": 2,
                    "edit_units": [],
                    "gold_unit_to_intent": {},
                    "gold_hunk_to_intent": {},
                }
            ],
        },
    )
    registry = {
        "schema_version": "mica-data-asset-registry-v2",
        "registry_status": "formal_assets_populated",
        "assets": {
            "strict_replay": {
                "path": str(manifest),
                "status": "frozen",
                "schema_version": "mica-formal-asset-manifest-v1",
                "source_pool": "datasets/source.jsonl",
                "split": "train",
                "record_count": 1,
                "checksum": "to_be_filled_by_validator",
                "created_by": "unit_test",
                "leakage_group_key": "leakage_group",
                "required_for": ["stage2_train"],
                "allowed_stages": ["stage2_replay"],
                "forbidden_stages": [],
                "eval_only": False,
            }
        },
    }

    validation = validate_asset_registry(registry)

    assert validation["schema_valid"] is True
    assert validation["assets_materialized"] is True
    assert validation["assets_content_valid"] is True
    assert validation["formal_ready"] is True
    assert validation["asset_status"]["strict_replay"]["file_exists"] is True
    assert validation["asset_status"]["strict_replay"]["content_valid"] is True


def test_asset_registry_required_missing_assets_block_formal_ready(tmp_path) -> None:
    manifest = tmp_path / "strict_replay_train.json"
    write_json(
        manifest,
        {
            "schema_version": "mica-formal-asset-manifest-v1",
            "asset_name": "strict_replay",
            "split": "train",
            "formal_ready": True,
            "summary": {
                "record_count": 1,
                "repo_count": 1,
                "duplicate_count": 0,
                "leakage_group_overlap_count": 0,
            },
            "rows": [
                {
                    "sample_id": "s1",
                    "split": "train",
                    "repo": "acme/repo",
                    "source_sha": "abc123",
                    "source_type": "strict_synthetic",
                    "cardinality_label_type": "exact_k2_gold",
                    "gold_provenance_status": "synthetic_construction_gold",
                    "leakage_group": "sha:abc123",
                    "construction_group": "synthetic:abc123",
                    "gold_count": 2,
                    "edit_units": [],
                    "gold_unit_to_intent": {},
                    "gold_hunk_to_intent": {},
                }
            ],
        },
    )
    registry = {
        "schema_version": "mica-data-asset-registry-v2",
        "registry_status": "formal_assets_populated",
        "assets": {
            "strict_replay": {
                "path": str(manifest),
                "status": "frozen",
                "schema_version": "mica-formal-asset-manifest-v1",
                "source_pool": "datasets/source.jsonl",
                "split": "train",
                "record_count": 1,
                "checksum": "to_be_filled_by_validator",
                "created_by": "unit_test",
                "leakage_group_key": "leakage_group",
                "required_for": ["stage2_train"],
                "allowed_stages": ["stage2_replay"],
                "forbidden_stages": [],
                "eval_only": False,
            },
            "real_alignment_dev": {
                "path": None,
                "status": "pending_annotation",
                "schema_version": "mica-formal-asset-manifest-v1",
                "source_pool": None,
                "split": "dev",
                "record_count": None,
                "checksum": None,
                "created_by": "unit_test",
                "leakage_group_key": "leakage_group",
                "required_for": ["stage3_calibration"],
                "allowed_stages": ["stage3_calibration"],
                "forbidden_stages": [],
                "eval_only": False,
            },
        },
    }

    validation = validate_asset_registry(registry)

    assert validation["schema_valid"] is True
    assert validation["required_missing_paths"] == ["real_alignment_dev"]
    assert validation["assets_materialized"] is True
    assert validation["assets_content_valid"] is True
    assert validation["formal_ready"] is False


def _write_full_checkpoint(path: Path) -> None:
    backend = MicaModelBackendAdapter(
        MicaModel(
            text_vector_dim=TEXT_VECTOR_DIM,
            dense_feature_dim=len(DENSE_FEATURE_NAMES),
            hidden_dim=16,
            kmax=4,
            use_null_slot=True,
            use_pairwise_bias=True,
            assignment_temperature=0.7,
            count_pb_coupling_strength=0.0,
        )
    )
    payload = build_model_checkpoint_payload(
        stage="stage1",
        backend=backend,
        optimizer_state={"lr": 1e-3},
        scheduler_state={"step": 1},
        model_config={
            "text_vector_dim": TEXT_VECTOR_DIM,
            "dense_feature_dim": len(DENSE_FEATURE_NAMES),
            "hidden_dim": 16,
            "kmax": 4,
            "use_null_slot": True,
            "use_pairwise_bias": True,
            "assignment_temperature": 0.7,
            "count_pb_coupling_strength": 0.0,
        },
        training_state={"epoch": 1, "global_step": 1, "seed": 7},
        threshold_version="candidate_v1",
        data_manifest_hashes={"stage1_dev": "abc"},
        git_commit="deadbeef",
    )
    save_checkpoint(path, payload)


def test_asset_registry_validates_full_model_stage1_checkpoint_entries(tmp_path) -> None:
    checkpoint = tmp_path / "stage1.ckpt.pt"
    _write_full_checkpoint(checkpoint)
    registry = {
        "schema_version": "mica-data-asset-registry-v2",
        "registry_status": "formal_assets_populated",
        "assets": {
            "stage1_checkpoint_input": {
                "path": str(checkpoint),
                "status": "frozen",
                "schema_version": "mica-checkpoint-v2",
                "source_pool": None,
                "split": "n/a",
                "record_count": None,
                "checksum": "placeholder",
                "created_by": "unit_test",
                "leakage_group_key": "n/a",
                "required_for": ["stage1_validation_execute"],
                "allowed_stages": ["stage1_validation_execute"],
                "forbidden_stages": [],
                "eval_only": False,
            }
        },
    }

    validation = validate_asset_registry(registry)

    assert validation["asset_status"]["stage1_checkpoint_input"]["content_valid"] is True
    assert validation["asset_status"]["stage1_checkpoint_input"]["formal_ready"] is True
    assert validation["readiness_by_requirement"]["stage1_validation_execute"]["ready"] is True


def test_asset_registry_rejects_metadata_only_stage1_checkpoint_entries(tmp_path) -> None:
    checkpoint = tmp_path / "metadata_only.ckpt.json"
    payload = build_checkpoint_payload(
        stage="stage1",
        spec_snapshot={"kmax": 4},
        asset_registry_snapshot={"assets": {}},
        seed=7,
        epoch=1,
        metrics={"loss": 1.0},
        trainable_components=["slot_decoder"],
        frozen_components=["base_encoder"],
        forbidden_assets_not_used=[],
        backend_state={"note": "metadata only"},
    )
    save_checkpoint(checkpoint, payload)
    registry = {
        "schema_version": "mica-data-asset-registry-v2",
        "registry_status": "formal_assets_populated",
        "assets": {
            "stage1_checkpoint_input": {
                "path": str(checkpoint),
                "status": "frozen",
                "schema_version": "mica-checkpoint-v2",
                "source_pool": None,
                "split": "n/a",
                "record_count": None,
                "checksum": "placeholder",
                "created_by": "unit_test",
                "leakage_group_key": "n/a",
                "required_for": ["stage1_validation_execute"],
                "allowed_stages": ["stage1_validation_execute"],
                "forbidden_stages": [],
                "eval_only": False,
            }
        },
    }

    validation = validate_asset_registry(registry)

    assert validation["asset_status"]["stage1_checkpoint_input"]["content_valid"] is False
    assert "checkpoint_missing_model_state" in validation["asset_status"]["stage1_checkpoint_input"]["errors"]
    assert validation["readiness_by_requirement"]["stage1_validation_execute"]["ready"] is False


def test_current_config_asset_registry_is_populated_and_schema_valid() -> None:
    registry = load_asset_registry("configs/mica/data_asset_registry.json")
    validation = validate_asset_registry(registry)

    assert registry["schema_version"] == "mica-data-asset-registry-v2"
    assert registry["registry_status"] == "formal_assets_populated"
    assert resolve_asset_path(registry, "strict_synthetic_train") == "datasets/mica/formal_assets/stage1/strict_synthetic_train.json"
    assert resolve_asset_path(registry, "step1_high_conf_single_dev") == "datasets/mica/formal_assets/stage1/step1_high_conf_single_dev.json"
    assert resolve_asset_path(registry, "strict_replay") == "datasets/mica/formal_assets/stage2/strict_replay.json"
    assert resolve_asset_path(registry, "hard_b_dev") == "datasets/mica/formal_assets/stage2/hard_b_dev.json"
    assert resolve_asset_path(registry, "m_weak_dev") == "datasets/mica/formal_assets/stage2/m_weak_dev.json"
    assert registry["assets"]["stage1_checkpoint_input"]["status"] == "frozen"
    assert registry["assets"]["stage1_checkpoint_input"]["path"] is None
    assert registry["assets"]["stage1_checkpoint_input"]["artifact_id"]
    assert registry["assets"]["stage1_checkpoint_input"]["local_materialization_required"] is True
    resolved_checkpoint = resolve_asset_path(registry, "stage1_checkpoint_input")
    if resolved_checkpoint is not None:
        assert resolved_checkpoint.endswith(".pt")
    assert registry["assets"]["stage1_official_final_test"]["status"] == "frozen"
    assert registry["assets"]["m_align_calib"]["status"] == "pending_annotation"
    assert registry["assets"]["real_alignment_dev"]["status"] == "pending_annotation"
    assert registry["assets"]["real_domain_split_test"]["status"] == "pending_generation"
    assert registry["assets"]["m_final_test"]["eval_only"] is True
    assert validation["schema_valid"] is True
    assert validation["formal_ready"] is False
    assert validation["readiness_by_requirement"]["stage1_candidate_validation"]["ready"] is True
    assert validation["readiness_by_requirement"]["stage1_threshold_selection"]["ready"] is True
    assert validation["readiness_by_requirement"]["stage3_calibration"]["ready"] is False
    assert validation["readiness_by_requirement"]["final_eval"]["ready"] is False


def test_asset_registry_resolves_artifact_backed_checkpoint_via_local_materialization(tmp_path) -> None:
    checkpoint = tmp_path / "stage1.ckpt.pt"
    _write_full_checkpoint(checkpoint)
    registry_path = tmp_path / "data_asset_registry.json"
    write_json(
        registry_path,
        {
            "schema_version": "mica-data-asset-registry-v2",
            "registry_status": "formal_assets_populated",
            "assets": {
                "stage1_checkpoint_input": {
                    "path": None,
                    "artifact_id": "stage1_candidate_clean",
                    "status": "candidate_validated",
                    "schema_version": "mica-checkpoint-v2",
                    "source_pool": "stage1_formal_training_runtime",
                    "split": "n/a",
                    "record_count": 1,
                    "sha256": "placeholder",
                    "checksum": "placeholder",
                    "created_by": "unit_test",
                    "leakage_group_key": "n/a",
                    "required_for": ["stage1_validation_execute"],
                    "allowed_stages": ["stage1_validation_execute"],
                    "forbidden_stages": [],
                    "eval_only": False,
                }
            },
        },
    )
    register_local_materialization(
        registry_path=tmp_path / "data_asset_materializations.local.json",
        artifact_id="stage1_candidate_clean",
        path=checkpoint,
        sha256="placeholder",
        created_by="unit_test",
        git_commit="deadbeef",
    )

    registry = load_asset_registry(registry_path)
    validation = validate_asset_registry(registry)

    assert resolve_asset_path(registry, "stage1_checkpoint_input") == str(checkpoint)
    assert validation["asset_status"]["stage1_checkpoint_input"]["file_exists"] is True
    assert validation["asset_status"]["stage1_checkpoint_input"]["content_valid"] is True


def test_asset_registry_reports_missing_artifact_materialization(tmp_path) -> None:
    registry_path = tmp_path / "data_asset_registry.json"
    write_json(
        registry_path,
        {
            "schema_version": "mica-data-asset-registry-v2",
            "registry_status": "formal_assets_populated",
            "assets": {
                "stage1_checkpoint_input": {
                    "path": None,
                    "artifact_id": "stage1_candidate_missing",
                    "status": "candidate_validated",
                    "schema_version": "mica-checkpoint-v2",
                    "source_pool": "stage1_formal_training_runtime",
                    "split": "n/a",
                    "record_count": 1,
                    "sha256": "placeholder",
                    "checksum": "placeholder",
                    "created_by": "unit_test",
                    "leakage_group_key": "n/a",
                    "required_for": ["stage1_validation_execute"],
                    "allowed_stages": ["stage1_validation_execute"],
                    "forbidden_stages": [],
                    "eval_only": False,
                }
            },
        },
    )

    validation = validate_asset_registry(load_asset_registry(registry_path))

    assert "asset_not_materialized" in validation["asset_status"]["stage1_checkpoint_input"]["errors"]


def test_asset_registry_rejects_artifact_materialization_hash_mismatch(tmp_path) -> None:
    checkpoint = tmp_path / "stage1.ckpt.pt"
    _write_full_checkpoint(checkpoint)
    registry_path = tmp_path / "data_asset_registry.json"
    write_json(
        registry_path,
        {
            "schema_version": "mica-data-asset-registry-v2",
            "registry_status": "formal_assets_populated",
            "assets": {
                "stage1_checkpoint_input": {
                    "path": None,
                    "artifact_id": "stage1_candidate_mismatch",
                    "status": "candidate_validated",
                    "schema_version": "mica-checkpoint-v2",
                    "source_pool": "stage1_formal_training_runtime",
                    "split": "n/a",
                    "record_count": 1,
                    "sha256": "deadbeef",
                    "checksum": "deadbeef",
                    "created_by": "unit_test",
                    "leakage_group_key": "n/a",
                    "required_for": ["stage1_validation_execute"],
                    "allowed_stages": ["stage1_validation_execute"],
                    "forbidden_stages": [],
                    "eval_only": False,
                }
            },
        },
    )
    register_local_materialization(
        registry_path=tmp_path / "data_asset_materializations.local.json",
        artifact_id="stage1_candidate_mismatch",
        path=checkpoint,
        sha256="deadbeef",
        created_by="unit_test",
        git_commit="deadbeef",
    )

    validation = validate_asset_registry(load_asset_registry(registry_path))

    assert "checksum_mismatch" in validation["asset_status"]["stage1_checkpoint_input"]["errors"]
