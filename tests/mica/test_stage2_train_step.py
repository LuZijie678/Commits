from __future__ import annotations

import pytest
import torch

from code.mica.stages.stage2_real_calibration import combine_stage2_epoch_results, compute_stage2_loss_for_batch
from code.mica.training.batch_adapters import adapt_hard_b_batch, adapt_m_weak_batch, adapt_strict_replay_batch
from code.mica.training.trainer_types import TrainOutputs, TrainStepResult


def _outputs() -> TrainOutputs:
    return TrainOutputs(
        count_logits=[0.1, 0.9],
        count_probs=[0.2, 0.8],
        pb_count_probs=[0.25, 0.75],
        slot_exist_probs=[0.9, 0.1],
        assignments={"u1": "slot_1"},
        assignment_scores={"u1": {"slot_1": 0.9}},
        slot_representations={"slot_1": [0.1, 0.2]},
        diagnostics={},
    )


def _outputs_with_assignments() -> TrainOutputs:
    return TrainOutputs(
        count_logits=torch.tensor([[2.0, 0.1]]),
        count_probs=torch.tensor([[0.9, 0.1]]),
        pb_count_probs=torch.tensor([[0.85, 0.15]]),
        slot_exist_probs=torch.tensor([[0.95, 0.05]]),
        assignments={"u1": "slot_1", "u2": "slot_null", "u3": "slot_1"},
        assignment_scores={"u1": {"slot_1": 0.8}, "u2": {"slot_null": 0.7}, "u3": {"slot_1": 0.4}},
        slot_representations={"slot_1": [0.1, 0.2]},
        diagnostics={},
        assignment_probs=torch.tensor([[[0.8, 0.2, 0.4], [0.1, 0.1, 0.3]]]),
        null_assignment_probs=torch.tensor([[0.1, 0.7, 0.3]]),
    )


def test_stage2_loss_routing_uses_replay_main_for_strict_replay() -> None:
    batch = adapt_strict_replay_batch(
        {"sample_id": "s1", "gold_count": 1, "gold_unit_to_intent": {"u1": "i1"}, "edit_units": [{"unit_id": "u1"}]}
    )
    result = compute_stage2_loss_for_batch(_outputs(), batch, {"loss_weights": {"lambda_cons": 0.0}})

    assert result.source_kind == "strict_replay"
    assert result.diagnostics["alignment_loss_used"] is True
    assert result.diagnostics["generation_loss_used"] is False


def test_stage2_loss_routing_for_hard_b_does_not_require_alignment() -> None:
    batch = adapt_hard_b_batch({"sample_id": "hb1", "edit_units": [{"unit_id": "u1"}]})
    result = compute_stage2_loss_for_batch(_outputs(), batch, {"hard_b_loss": {"rho": 0.1, "margin": 0.2, "eta": 0.05}})

    assert result.source_kind == "hard_b"
    assert result.diagnostics["alignment_loss_used"] is False
    assert result.diagnostics["count_loss_used"] is True
    assert result.diagnostics["hard_b_compactness_loss_used"] is False


def test_stage2_hard_b_reports_compactness_without_training_assignment_loss() -> None:
    batch = adapt_hard_b_batch(
        {
            "sample_id": "hb1",
            "edit_units": [
                {"unit_id": "u1", "file_role": "source"},
                {"unit_id": "u2", "file_role": "lockfile"},
                {"unit_id": "u3", "file_role": "test"},
            ],
        }
    )
    result = compute_stage2_loss_for_batch(_outputs_with_assignments(), batch, {"hard_b_loss": {"eta": 0.0}})

    assert result.diagnostics["hard_b_compactness_protocol"] == "report_only_no_assignment_loss"
    assert result.diagnostics["hard_b_compactness_loss_used"] is False
    assert result.diagnostics["hard_b_semantic_unit_count"] == 2
    assert result.diagnostics["hard_b_top1_retained_foreground_mass"] == pytest.approx(0.6)
    assert result.diagnostics["hard_b_residual_foreground_mass"] == pytest.approx(0.05)
    assert result.diagnostics["hard_b_background_swallowing_rate"] == pytest.approx(0.2)


def test_stage2_loss_routing_for_m_weak_uses_censored_supervision() -> None:
    batch = adapt_m_weak_batch({"sample_id": "mw1", "edit_units": [{"unit_id": "u1"}]})
    result = compute_stage2_loss_for_batch(_outputs(), batch, {"m_censored_loss": {"gamma_pb": 0.3}, "consistency": {"enabled": False}})

    assert result.source_kind == "m_weak"
    assert result.diagnostics["censored_supervision_used"] is True
    assert result.diagnostics["exact_k_supervision_used"] is False
    assert result.diagnostics["generation_loss_used"] is False


def test_stage2_epoch_summary_aggregates_step_results() -> None:
    steps = [
        TrainStepResult(sample_ids=["s1"], source_kind="strict_replay", loss_total=1.0, diagnostics={"source_kind": "strict_replay"}),
        TrainStepResult(
            sample_ids=["s2"],
            source_kind="hard_b",
            loss_total=2.0,
            diagnostics={"source_kind": "hard_b", "hard_b_top1_retained_foreground_mass": 0.6},
        ),
    ]
    epoch = combine_stage2_epoch_results(steps)

    assert epoch.step_count == 2
    assert epoch.mean_loss == 1.5
    assert epoch.source_kind_counts["strict_replay"] == 1
    assert epoch.diagnostics["mean_hard_b_top1_retained_foreground_mass"] == 0.6
