from __future__ import annotations

import torch
from torch import nn


class CountHead(nn.Module):
    def __init__(self, *, hidden_dim: int, kmax: int) -> None:
        super().__init__()
        self.kmax = kmax
        self.network = nn.Sequential(
            nn.Linear(hidden_dim + kmax, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, kmax),
        )

    def forward(self, pooled_embeddings: torch.Tensor, slot_exist_probs: torch.Tensor) -> torch.Tensor:
        sorted_exist_probs, _ = torch.sort(slot_exist_probs, dim=-1, descending=True)
        return self.network(torch.cat([pooled_embeddings, sorted_exist_probs], dim=-1))
