from __future__ import annotations

import torch

from code.mica.models.slot_decoder import SlotDecoder


def test_pairwise_relation_features_change_assignment_output() -> None:
    torch.manual_seed(0)
    decoder = SlotDecoder(hidden_dim=8, kmax=4, use_pairwise_bias=True)
    unit_embeddings = torch.randn(1, 3, 8)
    unit_mask = torch.tensor([[True, True, True]])
    pairwise_a = torch.zeros(1, 3, 3)
    pairwise_b = torch.tensor([[[0.0, 1.0, 0.0], [1.0, 0.0, 2.0], [0.0, 2.0, 0.0]]], dtype=torch.float32)

    _, _, probs_a, _, _ = decoder(unit_embeddings, unit_mask, pairwise_a)
    _, _, probs_b, _, _ = decoder(unit_embeddings, unit_mask, pairwise_b)

    assert probs_a.shape == probs_b.shape
    assert not torch.allclose(probs_a, probs_b)


def test_padding_relation_does_not_affect_valid_unit_assignments() -> None:
    torch.manual_seed(0)
    decoder = SlotDecoder(hidden_dim=8, kmax=4, use_pairwise_bias=True)
    unit_embeddings = torch.randn(1, 3, 8)
    unit_mask = torch.tensor([[True, True, False]])
    pairwise_a = torch.zeros(1, 3, 3)
    pairwise_b = pairwise_a.clone()
    pairwise_b[:, 2, :] = 100.0
    pairwise_b[:, :, 2] = 100.0

    _, _, probs_a, _, _ = decoder(unit_embeddings, unit_mask, pairwise_a)
    _, _, probs_b, _, _ = decoder(unit_embeddings, unit_mask, pairwise_b)

    assert probs_a.shape == probs_b.shape
    assert torch.allclose(probs_a[:, :, :2], probs_b[:, :, :2], atol=1e-6)
