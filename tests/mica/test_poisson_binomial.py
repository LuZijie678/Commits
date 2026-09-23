from __future__ import annotations

import torch

from code.mica.losses.poisson_binomial import poisson_binomial_pmf


def test_poisson_binomial_matches_two_bernoulli_closed_form() -> None:
    probs = torch.tensor([[0.2, 0.8]], dtype=torch.float32)
    pmf = poisson_binomial_pmf(probs)

    expected = torch.tensor([[0.16, 0.68, 0.16]], dtype=torch.float32)
    assert torch.allclose(pmf, expected, atol=1e-6)
    assert torch.allclose(pmf.sum(dim=-1), torch.ones(1), atol=1e-6)
