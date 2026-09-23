from __future__ import annotations

import pytest
import torch

from code.mica.stages.stage3_real_alignment_calibration import compute_stage3_loss_for_batch
from code.mica.training.batch_adapters import adapt_real_alignment_batch, adapt_strict_replay_batch
from code.mica.training.trainer_types import TrainOutputs


def _outputs() -> TrainOutputs:
    return TrainOutputs(
        count_logits=[0.2, 0.8],
        count_probs=[0.3, 0.7],
        pb_count_probs=[0.25, 0.75],
        slot_exist_probs=[0.85, 0.15],
        assignments={"u1": "slot_1"},
        assignment_scores={"u1": {"slot_1": 0.9}},
        slot_representations={"slot_1": [0.1]},
        diagnostics={},
    )


def test_stage3_real_alignment_batch_requires_gold_alignment() -> None:
    batch = adapt_real_alignment_batch({"sample_id": "ra1", "gold_count": 2})
    result = compute_stage3_loss_for_batch(_outputs(), batch, {})

    assert result.diagnostics["missing_real_alignment_gold"] is True


def test_stage3_loss_supports_real_alignment_and_replay() -> None:
    real_batch = adapt_real_alignment_batch(
        {"sample_id": "ra2", "gold_count": 2, "gold_unit_to_intent": {"u1": "i1"}, "edit_units": [{"unit_id": "u1"}]}
    )
    replay_batch = adapt_strict_replay_batch(
        {"sample_id": "sr1", "gold_count": 1, "gold_unit_to_intent": {"u1": "i1"}, "edit_units": [{"unit_id": "u1"}]}
    )

    real_result = compute_stage3_loss_for_batch(_outputs(), real_batch, {})
    replay_result = compute_stage3_loss_for_batch(_outputs(), replay_batch, {})

    assert real_result.diagnostics["generation_loss_used"] is False
    assert real_result.diagnostics["stage3_core_calibration_loss_used"] is True
    assert real_result.loss_name == "stage3_core_calibration_only"
    assert float(real_result.loss) > 0.0
    assert replay_result.diagnostics["strict_replay_used"] is True


def test_stage3_plus_real_alignment_adds_assignment_drift_regularizer() -> None:
    batch = adapt_real_alignment_batch(
        {
            "sample_id": "ra3",
            "gold_count": 2,
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "edit_units": [{"unit_id": "u1"}, {"unit_id": "u2"}],
        }
    )
    batch.metadata["base_assignment_probs"] = torch.tensor([[[0.80, 0.20], [0.20, 0.80]]], dtype=torch.float32)
    outputs = TrainOutputs(
        count_logits=torch.tensor([[0.2, 0.8]], dtype=torch.float32),
        count_probs=torch.tensor([[0.3, 0.7]], dtype=torch.float32),
        pb_count_probs=torch.tensor([[0.25, 0.75]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.85, 0.15]], dtype=torch.float32),
        assignments={"u1": "slot_1", "u2": "slot_2"},
        assignment_scores={"u1": {"slot_1": 0.9}, "u2": {"slot_2": 0.9}},
        slot_representations={"slot_1": [0.1], "slot_2": [0.2]},
        diagnostics={},
        assignment_logits=torch.zeros(1, 2, 2),
        assignment_probs=torch.tensor([[[0.60, 0.40], [0.40, 0.60]]], dtype=torch.float32),
        unit_mask=torch.tensor([[True, True]]),
    )

    result = compute_stage3_loss_for_batch(outputs, batch, {"stage3_plus": {"enabled": True, "lambda_drift": 0.5}})

    assert result.diagnostics["assignment_drift_regularized"] is True
    assert result.diagnostics["stage3_plus_assignment_adapter"] is True
    assert result.components["loss_drift"].item() > 0.0
    assert result.components["lambda_drift"].item() == pytest.approx(0.5)


def test_stage3_plus_rejects_mismatched_base_assignment_snapshot() -> None:
    batch = adapt_real_alignment_batch(
        {
            "sample_id": "ra4",
            "gold_count": 1,
            "gold_unit_to_intent": {"u1": "i1"},
            "edit_units": [{"unit_id": "u1"}],
        }
    )
    batch.metadata["base_assignment_probs"] = torch.tensor([[0.9]], dtype=torch.float32)
    outputs = TrainOutputs(
        count_logits=torch.tensor([[0.9, 0.1]], dtype=torch.float32),
        count_probs=torch.tensor([[0.9, 0.1]], dtype=torch.float32),
        pb_count_probs=torch.tensor([[0.9, 0.1]], dtype=torch.float32),
        slot_exist_probs=torch.tensor([[0.9, 0.1]], dtype=torch.float32),
        assignments={"u1": "slot_1"},
        assignment_scores={"u1": {"slot_1": 0.9}},
        slot_representations={"slot_1": [0.1]},
        diagnostics={},
        assignment_logits=torch.zeros(1, 2, 1),
        assignment_probs=torch.tensor([[[0.9], [0.1]]], dtype=torch.float32),
        unit_mask=torch.tensor([[True]]),
    )

    with pytest.raises(ValueError, match="base_assignment_probs must match assignment_probs shape"):
        compute_stage3_loss_for_batch(outputs, batch, {"stage3_plus": {"enabled": True, "lambda_drift": 0.5}})
