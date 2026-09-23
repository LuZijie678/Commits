from __future__ import annotations

import torch

from code.mica.losses.type_loss import optional_type_loss


def test_optional_type_loss_is_zero_when_disabled_and_positive_when_enabled() -> None:
    logits = torch.tensor([[2.0, 0.1], [0.2, 1.5]], dtype=torch.float32)

    off = optional_type_loss(logits, ["refactor", "fix"], lambda_type=0.0)
    on = optional_type_loss(logits, ["refactor", "fix"], lambda_type=0.1)

    assert float(off["loss_total"]) == 0.0
    assert float(on["loss_total"]) > 0.0
    assert on["included_in_hungarian_cost"] is False

