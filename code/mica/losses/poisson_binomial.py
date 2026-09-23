from __future__ import annotations

import torch


def poisson_binomial_pmf(probs: torch.Tensor) -> torch.Tensor:
    if probs.dim() != 2:
        raise ValueError("poisson_binomial_pmf expects a [batch, slots] tensor")
    batch_size, slot_count = probs.shape
    pmf = torch.zeros(batch_size, slot_count + 1, dtype=probs.dtype, device=probs.device)
    pmf[:, 0] = 1.0
    for slot_index in range(slot_count):
        next_pmf = torch.zeros_like(pmf)
        slot_prob = probs[:, slot_index].clamp(1e-6, 1 - 1e-6)
        next_pmf[:, 0] = pmf[:, 0] * (1.0 - slot_prob)
        for count in range(1, slot_count + 1):
            next_pmf[:, count] = pmf[:, count] * (1.0 - slot_prob) + pmf[:, count - 1] * slot_prob
        pmf = next_pmf
    return pmf
