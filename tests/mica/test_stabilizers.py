from __future__ import annotations

import torch

from code.mica.losses.stabilizers import assignment_entropy_loss


def test_assignment_entropy_loss_encourages_high_entropy_when_coeff_positive() -> None:
    assignments = torch.tensor([[[0.5, 0.5], [0.5, 0.5]]], dtype=torch.float32)

    result = assignment_entropy_loss(assignments, coeff=0.02)

    assert float(result["entropy_mean"]) > 0.0
    assert float(result["loss_total"]) < 0.0

