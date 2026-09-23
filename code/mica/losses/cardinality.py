from __future__ import annotations

from typing import Any

import torch

from code.mica.losses.poisson_binomial import poisson_binomial_pmf


def poisson_binomial_distribution(slot_exist_probs: Any, max_k: int) -> torch.Tensor:
    probs = _as_tensor(slot_exist_probs)
    if probs.ndim == 1:
        probs = probs.unsqueeze(0)
    pmf = poisson_binomial_pmf(probs)
    expected_width = max_k + 1
    if pmf.size(-1) < expected_width:
        pad = torch.zeros(*pmf.shape[:-1], expected_width - pmf.size(-1), dtype=pmf.dtype, device=pmf.device)
        pmf = torch.cat([pmf, pad], dim=-1)
    return pmf[..., :expected_width]


def count_loss_with_pb(
    p_count: Any,
    p_pb: Any,
    gold_count: int | list[int] | torch.Tensor,
    alpha_pb: float = 0.5,
    lambda_cal: float = 0.0,
    stopgrad_count_for_kl: bool = True,
) -> dict[str, Any]:
    count_probs = _normalize_probs(_as_tensor(p_count))
    pb_probs = _normalize_probs(_as_tensor(p_pb))
    if count_probs.ndim == 1:
        count_probs = count_probs.unsqueeze(0)
    if pb_probs.ndim == 1:
        pb_probs = pb_probs.unsqueeze(0)
    gather_index = _gold_indices(gold_count, count_probs.size(0), count_probs.size(-1), device=count_probs.device)
    loss_count = -torch.log(torch.gather(count_probs, dim=-1, index=gather_index).clamp_min(1e-6)).mean()
    loss_pb = alpha_pb * (-torch.log(torch.gather(pb_probs, dim=-1, index=gather_index).clamp_min(1e-6)).mean())
    p_multi = count_probs[..., 1:].sum(dim=-1)
    if lambda_cal > 0.0:
        target = count_probs.detach() if stopgrad_count_for_kl and hasattr(count_probs, "detach") else count_probs
        loss_cal = lambda_cal * torch.sum(target * (torch.log(target.clamp_min(1e-6)) - torch.log(pb_probs.clamp_min(1e-6))), dim=-1).mean()
    else:
        loss_cal = torch.tensor(0.0, dtype=count_probs.dtype, device=count_probs.device)
    return {
        "loss_total": loss_count + loss_pb + loss_cal,
        "loss_count": loss_count,
        "loss_pb": loss_pb,
        "loss_cal": loss_cal,
        "p_multi": p_multi,
        "alpha_pb": alpha_pb,
        "lambda_cal": lambda_cal,
        "stopgrad_count_for_kl": stopgrad_count_for_kl,
        "uses_independent_multi_loss": False,
    }


def _gold_indices(gold_count: int | list[int] | torch.Tensor, batch_size: int, limit: int, *, device: torch.device) -> torch.Tensor:
    if isinstance(gold_count, torch.Tensor):
        values = [int(item) for item in gold_count.reshape(-1).tolist()]
    elif isinstance(gold_count, list):
        values = [int(item) for item in gold_count]
    else:
        values = [int(gold_count)] * batch_size
    if len(values) == 1 and batch_size > 1:
        values = values * batch_size
    clipped = [max(min(value - 1, limit - 1), 0) for value in values[:batch_size]]
    return torch.tensor(clipped, dtype=torch.long, device=device).view(batch_size, 1)


def _normalize_probs(value: torch.Tensor) -> torch.Tensor:
    if value.numel() == 0:
        return value
    sums = value.sum(dim=-1, keepdim=True).clamp_min(1e-6)
    return value / sums


def _as_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)
