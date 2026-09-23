from __future__ import annotations

import torch

from code.mica.losses.null_slot_losses import compute_gold_evidence_null_penalty, compute_null_slot_loss
from code.mica.training.trainer_types import TrainBatch


def _batch() -> TrainBatch:
    return TrainBatch(
        sample_ids=["s1"],
        source_kind="strict_replay",
        edit_units=[
            {"unit_id": "u1", "file_path": "src/auth.py", "file_role": "source", "changed_identifiers": ["token"]},
            {"unit_id": "u2", "file_path": "package-lock.json", "file_role": "lockfile", "changed_identifiers": []},
        ],
        gold_count=1,
        gold_unit_to_intent={"u1": "i1"},
    )


def test_gold_foreground_unit_assigned_to_null_is_penalized() -> None:
    outputs = {
        "assignment_scores": {
            "u1": {"slot_1": 0.2, "slot_null": 0.8},
            "u2": {"slot_1": 0.2, "slot_null": 0.8},
        },
        "assignments": {"u1": "slot_null", "u2": "slot_null"},
        "count_probs": torch.tensor([[0.8, 0.2]], dtype=torch.float32),
    }

    result = compute_gold_evidence_null_penalty(outputs, _batch(), {"null_slot": {"enabled": True}})

    assert float(result["loss_total"]) > 0.0
    assert result["diagnostics"]["gold_evidence_assigned_to_null"] == 1


def test_background_unit_assignment_to_null_is_counted_and_null_not_in_count() -> None:
    outputs = {
        "assignment_scores": {
            "u1": {"slot_1": 0.9, "slot_null": 0.1},
            "u2": {"slot_1": 0.2, "slot_null": 0.8},
        },
        "assignments": {"u1": "slot_1", "u2": "slot_null"},
        "count_probs": torch.tensor([[0.7, 0.3]], dtype=torch.float32),
        "slot_exist_probs": torch.tensor([[0.9, 0.1]], dtype=torch.float32),
    }

    result = compute_null_slot_loss(outputs, _batch(), {"null_slot": {"enabled": True}})

    assert result["diagnostics"]["background_units_assigned_to_null"] == 1
    assert result["diagnostics"]["foreground_units_assigned_to_null"] == 0
    assert 0.0 <= result["diagnostics"]["null_assignment_ratio"] <= 1.0

