from __future__ import annotations

import torch
from torch import nn


def masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    mask_f = mask.to(values.dtype).unsqueeze(-1)
    denom = mask_f.sum(dim=1).clamp_min(1.0)
    return (values * mask_f).sum(dim=1) / denom


def couple_slot_existence_to_mass(
    raw_slot_logits: torch.Tensor,
    slot_mass: torch.Tensor,
    unit_counts: torch.Tensor,
    *,
    coupling_strength: float,
) -> torch.Tensor:
    normalized_slot_mass = slot_mass.squeeze(-1) / unit_counts.clamp_min(1.0)
    mass_log_prior = normalized_slot_mass.clamp_min(1e-6).log()
    coupled_logits = raw_slot_logits + coupling_strength * mass_log_prior
    return torch.sigmoid(coupled_logits)


class SlotDecoder(nn.Module):
    def __init__(
        self,
        *,
        hidden_dim: int,
        kmax: int,
        use_pairwise_bias: bool = True,
        assignment_temperature: float = 0.7,
        existence_mass_coupling_strength: float = 1.5,
        low_rank_adapter_rank: int = 4,
    ) -> None:
        super().__init__()
        self.kmax = kmax
        self.use_pairwise_bias = use_pairwise_bias
        self.assignment_temperature = assignment_temperature
        self.existence_mass_coupling_strength = existence_mass_coupling_strength
        self.low_rank_adapter_rank = low_rank_adapter_rank
        self.slot_queries = nn.Parameter(torch.randn(kmax, hidden_dim) * 0.02)
        self.null_query = nn.Parameter(torch.randn(hidden_dim) * 0.02)
        self.relation_fuse = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.exist_head = nn.Sequential(
            nn.Linear(hidden_dim * 3 + 1, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )
        self.evidence_fuse = nn.Linear(hidden_dim, hidden_dim)
        self.mass_fuse = nn.Linear(1, hidden_dim)
        self.low_rank_unit_adapter = nn.Linear(hidden_dim, low_rank_adapter_rank, bias=False)
        self.low_rank_slot_adapter = nn.Linear(hidden_dim, low_rank_adapter_rank, bias=False)
        self.low_rank_adapter_scale = nn.Parameter(torch.tensor(0.0))
        nn.init.normal_(self.low_rank_unit_adapter.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.low_rank_slot_adapter.weight, mean=0.0, std=0.02)

    def forward(
        self,
        unit_embeddings: torch.Tensor,
        unit_mask: torch.Tensor,
        pairwise_bias: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        decoder_units = unit_embeddings
        if self.use_pairwise_bias and pairwise_bias is not None:
            valid_pair_mask = unit_mask.unsqueeze(1) & unit_mask.unsqueeze(2)
            masked_pairwise = pairwise_bias.masked_fill(~valid_pair_mask, -1e4)
            relation_weights = torch.softmax(masked_pairwise, dim=-1)
            relation_weights = relation_weights * valid_pair_mask.to(dtype=unit_embeddings.dtype)
            relation_weights = relation_weights / relation_weights.sum(dim=-1, keepdim=True).clamp_min(1e-6)
            relation_context = torch.einsum("bij,bjh->bih", relation_weights, unit_embeddings)
            decoder_units = self.relation_fuse(torch.cat([unit_embeddings, relation_context], dim=-1))
            decoder_units = decoder_units * unit_mask.unsqueeze(-1).to(dtype=decoder_units.dtype)

        queries = self.slot_queries.unsqueeze(0).expand(unit_embeddings.size(0), -1, -1)
        assignment_logits = torch.einsum("buh,bkh->bku", decoder_units, queries)
        assignment_logits = assignment_logits + self.low_rank_assignment_delta(decoder_units, queries)
        null_query = self.null_query.unsqueeze(0).expand(unit_embeddings.size(0), -1)
        null_assignment_logits = torch.einsum("buh,bh->bu", decoder_units, null_query).unsqueeze(1)
        joint_assignment_logits = torch.cat([assignment_logits, null_assignment_logits], dim=1)
        joint_assignment_logits = joint_assignment_logits.masked_fill(~unit_mask.unsqueeze(1), -1e4)
        joint_assignment_probs = torch.softmax(joint_assignment_logits / self.assignment_temperature, dim=1)
        assignment_logits = joint_assignment_logits[:, : self.kmax, :]
        null_assignment_logits = joint_assignment_logits[:, self.kmax, :]
        assignment_probs = joint_assignment_probs[:, : self.kmax, :]
        null_assignment_probs = joint_assignment_probs[:, self.kmax, :]
        assignment_probs = assignment_probs * unit_mask.unsqueeze(1).to(assignment_logits.dtype)
        null_assignment_probs = null_assignment_probs * unit_mask.to(assignment_logits.dtype)
        slot_mass = assignment_probs.sum(dim=-1, keepdim=True)
        slot_summary = torch.einsum("bku,buh->bkh", assignment_probs, decoder_units) / slot_mass.clamp_min(1e-6)
        evidence_aware_slots = torch.layer_norm(
            queries + self.evidence_fuse(slot_summary) + self.mass_fuse(slot_mass),
            normalized_shape=(queries.size(-1),),
        )
        pooled = masked_mean(decoder_units, unit_mask)
        unit_counts = unit_mask.sum(dim=1, keepdim=True).to(decoder_units.dtype)
        normalized_slot_mass = (slot_mass.squeeze(-1) / unit_counts.clamp_min(1.0)).unsqueeze(-1)
        exist_features = torch.cat(
            [
                queries,
                evidence_aware_slots,
                pooled.unsqueeze(1).expand(-1, self.kmax, -1),
                normalized_slot_mass,
            ],
            dim=-1,
        )
        raw_slot_logits = self.exist_head(exist_features).squeeze(-1)
        slot_exist_probs = couple_slot_existence_to_mass(
            raw_slot_logits,
            slot_mass,
            unit_counts,
            coupling_strength=self.existence_mass_coupling_strength,
        )
        slot_logits = torch.logit(slot_exist_probs.clamp(1e-6, 1 - 1e-6))
        return slot_logits, assignment_logits, assignment_probs, null_assignment_logits, null_assignment_probs

    def low_rank_assignment_delta(self, decoder_units: torch.Tensor, queries: torch.Tensor) -> torch.Tensor:
        unit_low_rank = self.low_rank_unit_adapter(decoder_units)
        slot_low_rank = self.low_rank_slot_adapter(queries)
        return self.low_rank_adapter_scale * torch.einsum("bur,bkr->bku", unit_low_rank, slot_low_rank)
