from __future__ import annotations

from code.mica.augmentations.diff_augmentations import (
    context_line_dropout_batch,
    file_order_permute_batch,
    identifier_mask_batch,
    path_mask_batch,
)
from code.mica.training.trainer_types import TrainBatch


def _batch() -> TrainBatch:
    return TrainBatch(
        sample_ids=["s1"],
        source_kind="strict_replay",
        edit_units=[
            {"unit_id": "u1", "file_path": "src/auth.py", "changed_identifiers": ["token"], "context_lines": ["def auth():"]},
            {"unit_id": "u2", "file_path": "tests/test_auth.py", "changed_identifiers": ["token"], "context_lines": ["def test_auth():"]},
        ],
        gold_count=2,
        gold_unit_to_intent={"u1": "i1", "u2": "i2"},
    )


def test_diff_augmentations_preserve_sample_id_and_gold_labels() -> None:
    batch = _batch()

    masked = path_mask_batch(batch, {})
    identifiers = identifier_mask_batch(batch, {})
    permuted = file_order_permute_batch(batch, seed=7)
    dropped = context_line_dropout_batch(batch, {"drop_fraction": 1.0})

    assert masked.sample_ids == batch.sample_ids
    assert identifiers.gold_unit_to_intent == batch.gold_unit_to_intent
    assert {unit["unit_id"] for unit in permuted.edit_units} == {"u1", "u2"}
    assert dropped.edit_units[0]["context_lines"] == []

