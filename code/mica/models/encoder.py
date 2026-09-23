from __future__ import annotations

import torch
from torch import nn


class EvidenceEncoder(nn.Module):
    def __init__(self, *, text_dim: int, dense_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(text_dim + dense_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

    def forward(self, text_features: torch.Tensor, dense_features: torch.Tensor) -> torch.Tensor:
        return self.network(torch.cat([text_features, dense_features], dim=-1))
