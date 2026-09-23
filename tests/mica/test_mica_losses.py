from __future__ import annotations

import torch

from code.mica.losses.mica_losses import compute_stage1_losses
from code.mica.models.mica_model import MicaOutput


def test_stage1_losses_only_include_align_count_and_exist_terms() -> None:
    output = MicaOutput(
        slot_logits=torch.tensor([[2.5, -2.0, -3.0, -4.0]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.9, 0.1, 0.05, 0.01]], dtype=torch.float32),
        assignment_logits=torch.tensor(
            [[[3.0, -2.0], [-2.0, 3.0], [-4.0, -4.0], [-4.0, -4.0]]],
            dtype=torch.float32,
        ),
        assignment_probs=torch.tensor(
            [[[0.95, 0.05], [0.05, 0.95], [0.0, 0.0], [0.0, 0.0]]],
            dtype=torch.float32,
        ),
        count_logits=torch.tensor([[4.0, 1.0, -2.0, -3.0]], dtype=torch.float32),
        count_probs=torch.softmax(torch.tensor([[4.0, 1.0, -2.0, -3.0]], dtype=torch.float32), dim=-1),
        pb_count_probs=torch.tensor([[0.90, 0.06, 0.02, 0.02]], dtype=torch.float32),
    )
    targets = {
        "gold_counts": torch.tensor([1], dtype=torch.long),
        "gold_assignment_masks": [torch.tensor([[1.0, 0.0]], dtype=torch.float32)],
    }

    losses = compute_stage1_losses(output, targets, lambda_align=1.0, lambda_count=0.5, lambda_exist=0.5)

    assert {"loss_main", "loss_align", "loss_count", "loss_exist"} <= set(losses)
    assert "loss_multi" not in losses
    assert losses["loss_main"].item() > 0.0


def test_stage1_align_loss_ignores_padding_units() -> None:
    targets = {
        "gold_counts": torch.tensor([2], dtype=torch.long),
        "gold_assignment_masks": [torch.tensor([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=torch.float32)],
        "unit_mask": torch.tensor([[True, True, False]]),
    }
    base_output = MicaOutput(
        slot_logits=torch.tensor([[3.0, 3.0, -4.0, -4.0]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.95, 0.95, 0.01, 0.01]], dtype=torch.float32),
        assignment_logits=torch.zeros(1, 4, 3, dtype=torch.float32),
        assignment_probs=torch.tensor(
            [[[0.95, 0.05, 0.00], [0.05, 0.95, 0.00], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]],
            dtype=torch.float32,
        ),
        count_logits=torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32),
        count_probs=torch.softmax(torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32), dim=-1),
        pb_count_probs=torch.tensor([[0.10, 0.80, 0.05, 0.05]], dtype=torch.float32),
    )
    padded_output = MicaOutput(
        slot_logits=base_output.slot_logits,
        slot_exist_probs=base_output.slot_exist_probs,
        assignment_logits=base_output.assignment_logits,
        assignment_probs=torch.tensor(
            [[[0.95, 0.05, 1.00], [0.05, 0.95, 0.00], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]],
            dtype=torch.float32,
        ),
        count_logits=base_output.count_logits,
        count_probs=base_output.count_probs,
        pb_count_probs=base_output.pb_count_probs,
    )

    base_losses = compute_stage1_losses(base_output, targets)
    padded_losses = compute_stage1_losses(padded_output, targets)

    assert torch.allclose(base_losses["loss_align"], padded_losses["loss_align"], atol=1e-6)


def test_stage1_optional_k2_stabilizer_penalizes_collapsed_second_slot() -> None:
    output = MicaOutput(
        slot_logits=torch.tensor([[4.0, 3.5, -4.0, -4.0]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.98, 0.90, 0.01, 0.01]], dtype=torch.float32),
        assignment_logits=torch.zeros(1, 4, 3, dtype=torch.float32),
        assignment_probs=torch.tensor(
            [[[0.98, 0.97, 0.95], [0.02, 0.03, 0.05], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]],
            dtype=torch.float32,
        ),
        count_logits=torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32),
        count_probs=torch.softmax(torch.tensor([[0.0, 2.0, -2.0, -3.0]], dtype=torch.float32), dim=-1),
        pb_count_probs=torch.tensor([[0.10, 0.80, 0.05, 0.05]], dtype=torch.float32),
    )
    targets = {
        "gold_counts": torch.tensor([2], dtype=torch.long),
        "gold_assignment_masks": [torch.tensor([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=torch.float32)],
        "unit_mask": torch.tensor([[True, True, True]]),
    }

    losses = compute_stage1_losses(
        output,
        targets,
        lambda_stab=0.03,
        k2_min_second_slot_mass_ratio=0.20,
    )

    assert "loss_stab" in losses
    assert losses["loss_stab"].item() > 0.0
    assert losses["loss_total"].item() > losses["loss_main"].item()
