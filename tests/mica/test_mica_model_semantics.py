from __future__ import annotations

import torch

from code.mica.models.mica_model import MicaModel, combine_count_logits_with_pb_prior
from code.mica.models.slot_decoder import SlotDecoder, couple_slot_existence_to_mass


def test_slot_decoder_assignment_probs_partition_active_units_across_slots() -> None:
    decoder = SlotDecoder(hidden_dim=8, kmax=4, use_pairwise_bias=False)
    unit_embeddings = torch.randn(2, 3, 8)
    unit_mask = torch.tensor([[True, True, False], [True, True, True]])

    (
        slot_logits,
        assignment_logits,
        assignment_probs,
        null_assignment_logits,
        null_assignment_probs,
    ) = decoder(unit_embeddings, unit_mask)

    assert slot_logits.shape == (2, 4)
    assert assignment_logits.shape == (2, 4, 3)
    assert assignment_probs.shape == (2, 4, 3)
    assert null_assignment_logits.shape == (2, 3)
    assert null_assignment_probs.shape == (2, 3)
    joint_mass = assignment_probs.sum(dim=1) + null_assignment_probs
    assert torch.allclose(joint_mass[0, :2], torch.tensor([1.0, 1.0]), atol=1e-5)
    assert torch.allclose(joint_mass[0, 2], torch.tensor(0.0), atol=1e-6)
    assert torch.allclose(assignment_probs[0, :, 2], torch.zeros(4), atol=1e-6)
    assert torch.allclose(null_assignment_probs[0, 2], torch.tensor(0.0), atol=1e-6)
    assert torch.allclose(joint_mass[1], torch.ones(3), atol=1e-5)


def test_mica_model_count_distributions_exclude_zero_count_class() -> None:
    model = MicaModel(text_vector_dim=16, dense_feature_dim=9, hidden_dim=12, kmax=4)
    batch = {
        "text_features": torch.randn(2, 3, 16),
        "dense_features": torch.randn(2, 3, 9),
        "pairwise_bias": torch.randn(2, 3, 3),
        "unit_mask": torch.tensor([[True, True, False], [True, True, True]]),
    }

    output = model(batch)

    assert output.count_logits.shape == (2, 4)
    assert output.count_probs.shape == (2, 4)
    assert output.pb_count_probs.shape == (2, 4)
    assert torch.allclose(output.count_probs.sum(dim=-1), torch.ones(2), atol=1e-5)
    assert torch.allclose(output.pb_count_probs.sum(dim=-1), torch.ones(2), atol=1e-5)


def test_slot_existence_coupling_penalizes_low_mass_slots() -> None:
    raw_slot_logits = torch.tensor([[1.0, 1.0, 1.0, 1.0]], dtype=torch.float32)
    slot_mass = torch.tensor([[[0.85], [0.10], [0.04], [0.01]]], dtype=torch.float32)
    unit_counts = torch.tensor([[10.0]], dtype=torch.float32)

    coupled_probs = couple_slot_existence_to_mass(raw_slot_logits, slot_mass, unit_counts, coupling_strength=4.0)

    assert coupled_probs.shape == (1, 4)
    assert coupled_probs[0, 0] > coupled_probs[0, 1] > coupled_probs[0, 2] > coupled_probs[0, 3]
    assert coupled_probs[0, 1] < 0.5


def test_count_logit_coupling_respects_pb_prior() -> None:
    base_count_logits = torch.tensor([[0.1, 0.2, -0.2, -0.5]], dtype=torch.float32)
    pb_count_probs = torch.tensor([[0.80, 0.15, 0.04, 0.01]], dtype=torch.float32)

    combined = combine_count_logits_with_pb_prior(base_count_logits, pb_count_probs, coupling_strength=2.0)

    assert combined.shape == (1, 4)
    assert int(combined.argmax(dim=-1).item()) == 0


def test_slot_decoder_low_rank_adapter_is_zero_effect_by_default() -> None:
    torch.manual_seed(0)
    decoder = SlotDecoder(hidden_dim=8, kmax=4, use_pairwise_bias=False)
    unit_embeddings = torch.randn(1, 3, 8)
    unit_mask = torch.tensor([[True, True, True]])
    queries = decoder.slot_queries.unsqueeze(0)
    base_logits = torch.einsum("buh,bkh->bku", unit_embeddings, queries)

    delta = decoder.low_rank_assignment_delta(unit_embeddings, queries)

    assert delta.shape == base_logits.shape
    assert torch.allclose(delta, torch.zeros_like(delta), atol=1e-7)
