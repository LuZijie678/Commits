from __future__ import annotations

from code.mica.renderers.trainable_reranker import (
    load_candidate_reranker_checkpoint,
    score_candidates_with_checkpoint,
    train_candidate_reranker,
)


def _rows() -> list[dict]:
    return [
        {
            "sample_id": "r1",
            "structured_intent_plan": {
                "sample_id": "r1",
                "decision": "decompose",
                "predicted_k": 1,
                "intents": [
                    {
                        "slot_id": "slot_1",
                        "slot_confidence": 0.9,
                        "assigned_unit_ids": ["u1"],
                        "assigned_hunk_ids": ["h1"],
                        "files": ["src/auth.py"],
                        "changed_symbols": ["validate_token"],
                        "changed_identifiers": ["auth", "token"],
                        "file_roles": ["source"],
                        "evidence": [
                            {
                                "unit_id": "u1",
                                "hunk_id": "h1",
                                "file_path": "src/auth.py",
                                "file_role": "source",
                                "language": "python",
                                "enclosing_symbol": "validate_token",
                                "patch_text": "@@",
                                "added_lines": ["+ validate_token(token)"],
                                "deleted_lines": ["- token"],
                                "changed_identifiers": ["auth", "token"],
                            }
                        ],
                        "action": "update",
                        "object": "auth validation",
                        "scope": "auth",
                    }
                ],
                "background_units": [],
                "uncertain_units": [],
                "metadata": {},
            },
            "assigned_evidence": [{"file_path": "src/auth.py", "changed_identifiers": ["auth"]}],
            "target_message": "update auth validation",
            "source_kind": "synthetic",
            "evidence_terms": ["auth", "validate_token", "token"],
        }
    ]


def test_trainable_reranker_checkpoint_can_be_loaded_and_replayed() -> None:
    checkpoint, rendered, metrics = train_candidate_reranker(
        rows=_rows(),
        spec={"reranker_epochs": 3, "reranker_learning_rate": 0.05, "llm_api_enabled": False},
    )

    loaded = load_candidate_reranker_checkpoint(checkpoint)
    scored = score_candidates_with_checkpoint(
        rows=_rows(),
        checkpoint_payload=checkpoint,
    )

    assert checkpoint["schema_version"] == "mica-trainable-reranker-checkpoint-v1"
    assert checkpoint["training_schema_version"] == "mica-trainable-reranker-training-v1"
    assert checkpoint["feature_names"]
    assert loaded.input_dim == len(checkpoint["feature_names"])
    assert metrics["feature_names"] == checkpoint["feature_names"]
    assert scored["schema_version"] == "mica-trainable-reranker-preview-v1"
    assert scored["rows"][0]["winner"]["subject"] == rendered[0].subject
    assert len(scored["rows"][0]["candidates"]) >= 1
