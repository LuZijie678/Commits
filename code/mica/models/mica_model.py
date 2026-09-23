from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import nn

from code.mica.losses.poisson_binomial import poisson_binomial_pmf
from code.mica.models.count_head import CountHead
from code.mica.models.encoder import EvidenceEncoder
from code.mica.models.slot_decoder import SlotDecoder, masked_mean


@dataclass(slots=True)
class MicaOutput:
    slot_logits: torch.Tensor
    slot_exist_probs: torch.Tensor
    assignment_logits: torch.Tensor
    assignment_probs: torch.Tensor
    count_logits: torch.Tensor
    count_probs: torch.Tensor
    pb_count_probs: torch.Tensor
    base_count_logits: torch.Tensor | None = None
    count_decode_protocol: str = "primary_p_count_no_pb_prior"
    null_assignment_logits: torch.Tensor | None = None
    null_assignment_probs: torch.Tensor | None = None


def combine_count_logits_with_pb_prior(
    base_count_logits: torch.Tensor,
    pb_count_probs: torch.Tensor,
    *,
    coupling_strength: float,
) -> torch.Tensor:
    return base_count_logits + coupling_strength * pb_count_probs.clamp_min(1e-6).log()


class MicaModel(nn.Module):
    def __init__(
        self,
        *,
        text_vector_dim: int,
        dense_feature_dim: int,
        hidden_dim: int = 64,
        kmax: int = 4,
        use_null_slot: bool = False,
        use_pairwise_bias: bool = True,
        assignment_temperature: float = 0.7,
        count_pb_coupling_strength: float = 0.0,
    ) -> None:
        super().__init__()
        self.kmax = kmax
        self.use_null_slot = use_null_slot
        self.count_pb_coupling_strength = count_pb_coupling_strength
        self.encoder = EvidenceEncoder(text_dim=text_vector_dim, dense_dim=dense_feature_dim, hidden_dim=hidden_dim)
        self.slot_decoder = SlotDecoder(
            hidden_dim=hidden_dim,
            kmax=kmax,
            use_pairwise_bias=use_pairwise_bias,
            assignment_temperature=assignment_temperature,
        )
        self.count_head = CountHead(hidden_dim=hidden_dim, kmax=kmax)
        self.count_temperature_log = nn.Parameter(torch.tensor(0.0))
        self.existence_temperature_log = nn.Parameter(torch.tensor(0.0))
        self.selective_risk_bias = nn.Parameter(torch.tensor(0.0))

    def forward(self, batch: dict[str, torch.Tensor]) -> MicaOutput:
        unit_embeddings = self.encoder(batch["text_features"], batch["dense_features"])
        slot_logits, assignment_logits, assignment_probs, null_assignment_logits, null_assignment_probs = self.slot_decoder(
            unit_embeddings,
            batch["unit_mask"],
            batch.get("pairwise_bias"),
        )
        slot_logits = slot_logits / self.existence_temperature_log.exp().clamp_min(1e-6)
        slot_exist_probs = torch.sigmoid(slot_logits)
        pooled_embeddings = masked_mean(unit_embeddings, batch["unit_mask"])
        base_count_logits = self.count_head(pooled_embeddings, slot_exist_probs)
        raw_pb_count_probs = poisson_binomial_pmf(slot_exist_probs.clamp(1e-4, 1 - 1e-4))
        pb_count_probs = raw_pb_count_probs[:, 1:]
        pb_count_probs = pb_count_probs / pb_count_probs.sum(dim=-1, keepdim=True).clamp_min(1e-6)
        if self.count_pb_coupling_strength:
            count_logits = combine_count_logits_with_pb_prior(
                base_count_logits,
                pb_count_probs,
                coupling_strength=self.count_pb_coupling_strength,
            )
            count_decode_protocol = "ablation_count_logits_with_pb_prior"
        else:
            count_logits = base_count_logits
            count_decode_protocol = "primary_p_count_no_pb_prior"
        count_logits = count_logits / self.count_temperature_log.exp().clamp_min(1e-6)
        count_probs = F.softmax(count_logits, dim=-1)
        return MicaOutput(
            slot_logits=slot_logits,
            slot_exist_probs=slot_exist_probs,
            assignment_logits=assignment_logits,
            assignment_probs=assignment_probs,
            null_assignment_logits=null_assignment_logits,
            null_assignment_probs=null_assignment_probs,
            count_logits=count_logits,
            count_probs=count_probs,
            pb_count_probs=pb_count_probs,
            base_count_logits=base_count_logits,
            count_decode_protocol=count_decode_protocol,
        )
