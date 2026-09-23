from __future__ import annotations

import pytest
import torch

from code.mica.losses.stage2_losses import hard_b_loss, m_censored_loss, stage2_combined_loss, strict_replay_loss


def test_hard_b_loss_does_not_require_alignment_gold() -> None:
    outputs = {
        "count_probs": torch.tensor([[0.70, 0.20, 0.10]], dtype=torch.float32),
        "pb_count_probs": torch.tensor([[0.60, 0.30, 0.10]], dtype=torch.float32),
        "slot_exist_probs": torch.tensor([[0.85, 0.18, 0.07]], dtype=torch.float32),
    }

    result = hard_b_loss(outputs, margin=0.2, rho=0.1, eta=0.05)

    assert float(result["loss_total"]) > 0.0
    assert "hard_b_count_loss" in result
    assert "hard_b_pb_loss" in result
    assert "extra_slot_penalty" in result
    assert result["stage2_training_signal"] == "hard_b_anti_over_split"


def test_m_censored_loss_treats_m_weak_as_k_ge_2_not_exact_k2() -> None:
    outputs = {
        "count_probs": torch.tensor([[0.10, 0.60, 0.30]], dtype=torch.float32),
        "pb_count_probs": torch.tensor([[0.15, 0.55, 0.30]], dtype=torch.float32),
    }

    result = m_censored_loss(outputs, gamma_pb=0.3)

    assert result["m_weak_supervision"] == "censored_k_at_least_2"
    assert result["exact_k_supervision_used"] is False
    assert float(result["p_multi_count"]) == pytest.approx(0.9)
    assert float(result["p_multi_pb"]) == pytest.approx(0.85)


def test_strict_replay_loss_can_reuse_existing_stage1_loss_stub() -> None:
    result = strict_replay_loss({"loss_main": torch.tensor(1.25)}, gold=None, weights=None)

    assert float(result["loss_total"]) == 1.25
    assert result["stage1_replay_used"] is True
    assert result["generation_loss_included"] is False
    assert result["role_loss_included"] is False
    assert result["cohesion_loss_included"] is False


def test_stage2_combined_loss_merges_named_parts_with_weights() -> None:
    parts = {
        "replay": {"loss_total": torch.tensor(1.0)},
        "hard_b": {"loss_total": torch.tensor(2.0)},
        "m_censored": {"loss_total": torch.tensor(3.0)},
    }
    result = stage2_combined_loss(parts, {"lambda_replay": 0.5, "lambda_hard": 0.25, "lambda_M": 0.25})

    assert float(result["loss_total"]) == pytest.approx(1.75)
    assert result["consistency_enabled"] is False
