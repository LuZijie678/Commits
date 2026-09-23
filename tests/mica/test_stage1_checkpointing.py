from __future__ import annotations

import torch

from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.models.mica_model import MicaModel
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import (
    build_checkpoint_payload,
    build_model_checkpoint_payload,
    instantiate_backend_from_checkpoint,
    load_checkpoint,
    save_checkpoint,
    validate_checkpoint_payload,
)
from code.mica.training.trainer_types import TrainBatch


def _batch() -> TrainBatch:
    return TrainBatch(
        sample_ids=["s1"],
        source_kind="strict_replay",
        gold_count=1,
        gold_unit_to_intent={"u1": "intent_0"},
        edit_units=[
            {
                "unit_id": "u1",
                "hunk_id": "h1",
                "file_path": "src/auth.py",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ auth = 1"],
                "deleted_lines": [],
                "changed_identifiers": ["auth"],
            }
        ],
        metadata={"release_decision": "decompose"},
    )


def _backend() -> MicaModelBackendAdapter:
    model = MicaModel(
        text_vector_dim=TEXT_VECTOR_DIM,
        dense_feature_dim=len(DENSE_FEATURE_NAMES),
        hidden_dim=16,
        kmax=4,
        use_null_slot=True,
        use_pairwise_bias=True,
        assignment_temperature=0.7,
        count_pb_coupling_strength=0.0,
    )
    return MicaModelBackendAdapter(model)


def test_full_model_checkpoint_round_trip_restores_stage1_backend_predictions(tmp_path) -> None:
    backend = _backend()
    batch = _batch()
    before = backend.forward(batch)

    payload = build_model_checkpoint_payload(
        stage="stage1",
        backend=backend,
        optimizer_state={"lr": 1e-3},
        scheduler_state={"step": 3},
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
        training_state={"epoch": 1, "global_step": 3, "seed": 7},
        threshold_version="candidate_v1",
        data_manifest_hashes={"stage1_dev": "abc"},
        git_commit="deadbeef",
        git_provenance={"git_commit": "deadbeef", "dirty": False, "scope": "repo_filtered"},
        environment={"python_version": "3.11.0", "platform": "unit-test"},
    )
    checkpoint = tmp_path / "stage1_full.ckpt.pt"
    save_checkpoint(checkpoint, payload)

    loaded = load_checkpoint(checkpoint)
    assert validate_checkpoint_payload(loaded, require_full_model_state=True)["valid"] is True
    assert loaded["git_provenance"]["dirty"] is False
    assert loaded["environment"]["platform"] == "unit-test"

    restored_backend = instantiate_backend_from_checkpoint(loaded)
    after = restored_backend.forward(batch)

    assert before.assignments == after.assignments
    assert before.predicted_count == after.predicted_count
    assert torch.allclose(before.count_probs, after.count_probs, atol=1e-6)


def test_metadata_only_checkpoint_is_rejected_for_formal_stage1_execution(tmp_path) -> None:
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
    checkpoint = tmp_path / "metadata_only.ckpt.json"
    save_checkpoint(checkpoint, payload)

    loaded = load_checkpoint(checkpoint)
    validation = validate_checkpoint_payload(loaded, require_full_model_state=True)

    assert validation["valid"] is False
    assert "missing_model_state" in validation["errors"]
