from __future__ import annotations

import pytest
import torch

from code.mica.decoding import decode_active_slot_assignments


def test_decode_uses_p_count_for_k_hat_and_topk_existence_for_active_slots() -> None:
    decoded = decode_active_slot_assignments(
        count_probs=torch.tensor([0.1, 0.8, 0.1]),
        slot_exist_probs=torch.tensor([0.2, 0.9, 0.7]),
        assignment_probs=torch.tensor(
            [
                [0.70, 0.10],
                [0.20, 0.60],
                [0.10, 0.20],
            ],
            dtype=torch.float32,
        ),
        null_assignment_probs=torch.tensor([0.0, 0.1], dtype=torch.float32),
        unit_mask=torch.tensor([True, True]),
        unit_ids=["u1", "u2"],
    )

    assert decoded.predicted_count == 2
    assert decoded.active_slot_indices == [1, 2]
    assert set(decoded.unit_assignment_scores["u1"]) == {"slot_2", "slot_3", "slot_null"}
    assert decoded.unit_to_slot["u1"] == "slot_2"
    assert decoded.unit_to_slot["u2"] == "slot_2"
    assert decoded.diagnostics["predicted_count_source"] == "argmax_count_probs"


def test_decode_renormalizes_active_slots_plus_null_only() -> None:
    decoded = decode_active_slot_assignments(
        count_probs=torch.tensor([0.9, 0.1]),
        slot_exist_probs=torch.tensor([0.8, 0.2]),
        assignment_probs=torch.tensor([[0.20], [0.70]], dtype=torch.float32),
        null_assignment_probs=torch.tensor([0.10], dtype=torch.float32),
        unit_mask=torch.tensor([True]),
        unit_ids=["u1"],
    )

    assert decoded.predicted_count == 1
    assert decoded.active_slot_indices == [0]
    assert decoded.unit_assignment_scores["u1"]["slot_1"] == pytest.approx(2.0 / 3.0)
    assert decoded.unit_assignment_scores["u1"]["slot_null"] == pytest.approx(1.0 / 3.0)


def test_decode_masks_inactive_padded_units() -> None:
    decoded = decode_active_slot_assignments(
        count_probs=torch.tensor([0.9, 0.1]),
        slot_exist_probs=torch.tensor([0.8, 0.2]),
        assignment_probs=torch.tensor([[0.60, 0.40], [0.30, 0.50]], dtype=torch.float32),
        null_assignment_probs=torch.tensor([0.10, 0.10], dtype=torch.float32),
        unit_mask=torch.tensor([True, False]),
        unit_ids=["u1", "pad"],
    )

    assert decoded.unit_to_slot == {"u1": "slot_1"}
    assert "pad" not in decoded.unit_assignment_scores
