from __future__ import annotations

import torch

from code.mica.losses.cardinality import count_loss_with_pb, poisson_binomial_distribution


def test_poisson_binomial_distribution_sums_to_one_and_matches_two_slot_case() -> None:
    probs = torch.tensor([[0.2, 0.3]], dtype=torch.float32)

    distribution = poisson_binomial_distribution(probs, max_k=2)

    assert torch.allclose(distribution.sum(dim=-1), torch.tensor([1.0], dtype=torch.float32))
    expected = torch.tensor([[0.56, 0.38, 0.06]], dtype=torch.float32)
    assert torch.allclose(distribution, expected, atol=1e-6)


def test_count_loss_with_pb_uses_alpha_pb_and_derives_multi_from_p_count_only() -> None:
    p_count = torch.tensor([[0.2, 0.7, 0.1]], dtype=torch.float32, requires_grad=True)
    p_pb = torch.tensor([[0.3, 0.6, 0.1]], dtype=torch.float32, requires_grad=True)

    low = count_loss_with_pb(p_count, p_pb, gold_count=2, alpha_pb=0.1, lambda_cal=0.0)
    high = count_loss_with_pb(p_count, p_pb, gold_count=2, alpha_pb=0.9, lambda_cal=0.0)

    assert float(high["loss_pb"].detach()) > float(low["loss_pb"].detach())
    assert torch.allclose(high["p_multi"], torch.tensor([0.8], dtype=torch.float32))
    assert high["uses_independent_multi_loss"] is False
