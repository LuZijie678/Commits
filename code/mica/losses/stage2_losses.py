from __future__ import annotations

from typing import Any

import torch


def hard_b_loss(outputs: Any, eta_pb: float = 0.05, **_: Any) -> dict[str, Any]:
    count_probs = _field(outputs, "count_probs")
    pb_count_probs = _field(outputs, "pb_count_probs")
    slot_exist_probs = _field(outputs, "slot_exist_probs")

    hard_b_count_term = (-count_probs[..., 0].clamp_min(1e-6).log()).mean()
    hard_b_pb_term = (-pb_count_probs[..., 0].clamp_min(1e-6).log()).mean()
    sum_slot_existence = slot_exist_probs.sum(dim=-1)
    top_slot_prob = slot_exist_probs.max(dim=-1).values
    extra_slot_mass = (sum_slot_existence - top_slot_prob).mean()
    loss_total = hard_b_count_term + eta_pb * hard_b_pb_term
    return {
        "loss_total": loss_total,
        "hard_b_count_loss": hard_b_count_term,
        "hard_b_pb_loss": eta_pb * hard_b_pb_term,
        "extra_slot_penalty": hard_b_count_term * 0.0,
        "sum_slot_existence": sum_slot_existence.mean(),
        "top_slot_prob": top_slot_prob.mean(),
        "extra_slot_mass_diagnostic": extra_slot_mass,
        "stage2_training_signal": "hard_b_anti_over_split",
        "assignment_updated": False,
        "compactness_loss_used": False,
    }


def m_censored_loss(outputs: Any, gamma_pb: float = 0.0) -> dict[str, Any]:
    count_probs = _field(outputs, "count_probs")
    pb_count_probs = _field(outputs, "pb_count_probs")
    p_multi_count = count_probs[..., 1:].sum(dim=-1).clamp_min(1e-6)
    p_multi_pb = pb_count_probs[..., 1:].sum(dim=-1).clamp_min(1e-6)
    loss_total = (-p_multi_count.log()).mean()
    if gamma_pb:
        loss_total = loss_total - gamma_pb * p_multi_pb.log().mean()
    return {
        "loss_total": loss_total,
        "p_multi_count": p_multi_count.mean(),
        "p_multi_pb": p_multi_pb.mean(),
        "gamma_pb": gamma_pb,
        "m_weak_supervision": "censored_k_at_least_2",
        "exact_k_supervision_used": False,
        "assignment_updated": False,
    }


def strict_replay_loss(outputs: Any, gold: dict[str, Any] | None, weights: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(outputs, dict) and "loss_main" in outputs:
        replay_main = _to_tensor(outputs["loss_main"])
        result = {
            "loss_total": replay_main,
            "loss_main": replay_main,
        }
    elif _looks_like_mica_output(outputs) and isinstance(gold, dict):
        from code.mica.losses.mica_losses import compute_stage1_losses

        adapted_weights = dict(weights or {})
        result = compute_stage1_losses(
            outputs,
            gold,
            lambda_align=float(adapted_weights.get("lambda_align", 1.0)),
            lambda_count=float(adapted_weights.get("lambda_count", 0.5)),
            lambda_exist=float(adapted_weights.get("lambda_exist", 0.5)),
        )
    else:
        adapter = (weights or {}).get("stage1_loss_adapter")
        if adapter is None:
            raise ValueError("strict_replay_loss needs loss_main, a stage1 adapter, or a MicaOutput + gold targets.")
        result = adapter(outputs, gold, weights or {})
    replay_main = _to_tensor(result["loss_main"])
    replay_result = {
        "loss_total": replay_main,
        "loss_main": replay_main,
        "stage1_replay_used": True,
        "generation_loss_included": False,
        "role_loss_included": False,
        "cohesion_loss_included": False,
    }
    for key, value in result.items():
        if key not in replay_result:
            replay_result[key] = value
    return replay_result


def stage2_combined_loss(loss_parts: dict[str, dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    combined = torch.tensor(0.0)
    mapping = {
        "replay": float(weights.get("lambda_replay", 0.0)),
        "hard_b": float(weights.get("lambda_hard", 0.0)),
        "m_censored": float(weights.get("lambda_M", 0.0)),
        "consistency": float(weights.get("lambda_cons", 0.0)),
        "real_alignment": 0.0,
    }
    for part_name, weight in mapping.items():
        if part_name in loss_parts:
            combined = combined + weight * _to_tensor(loss_parts[part_name]["loss_total"])
    return {
        "loss_total": combined,
        "weights": mapping,
        "consistency_enabled": bool(mapping["consistency"] > 0.0 and "consistency" in loss_parts),
    }


def _field(outputs: Any, name: str) -> torch.Tensor:
    if isinstance(outputs, dict):
        value = outputs[name]
    else:
        value = getattr(outputs, name)
    return _to_tensor(value)


def _to_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)


def _looks_like_mica_output(outputs: Any) -> bool:
    required = ("assignment_probs", "slot_exist_probs", "count_logits", "pb_count_probs")
    if not all(hasattr(outputs, field) for field in required):
        return False
    return getattr(outputs, "assignment_probs", None) is not None and hasattr(getattr(outputs, "count_logits"), "size")
