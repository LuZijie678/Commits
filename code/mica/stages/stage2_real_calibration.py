from __future__ import annotations

from collections import Counter
from typing import Any

import torch

from code.mica.data.stage2_mixture import build_stage2_mixture_manifest
from code.mica.losses.stage2_losses import hard_b_loss, m_censored_loss, strict_replay_loss
from code.mica.training.optimizer_plan import build_component_lr_groups
from code.mica.training.trainer_types import (
    ComponentFreezePlan,
    EpochResult,
    LossResult,
    TrainBatch,
    TrainingPlan,
    TrainOutputs,
    TrainStepResult,
)


def prepare_stage2_real_calibration(spec: dict[str, Any], source_manifests: dict[str, Any]) -> dict[str, Any]:
    return build_stage2_mixture_manifest(spec, source_manifests)


def build_stage2_training_plan(spec: dict[str, Any], mixture_summary: dict[str, Any]) -> TrainingPlan:
    freeze_first = build_stage2_freeze_plan(spec, phase="first_half")
    return TrainingPlan(
        stage=str(spec.get("stage", "stage2_real_domain_count_calibration")),
        mode=str(spec.get("default_mode", "dry_run")),
        approved=bool(spec.get("advisor_stage2_approved", False)),
        dry_run=str(spec.get("default_mode", "dry_run")) == "dry_run",
        trainable_components=list(freeze_first.trainable_components),
        frozen_components=list(freeze_first.frozen_components),
        loss_weights={key: float(value) for key, value in dict(spec.get("loss_weights", {})).items()},
        data_mixture=mixture_summary.get("dataset_roles", {}),
            forbidden_assets=["m_final_test", "hard_b_test", "real_domain_split_test", "real_domain_selective_test"],
        metadata={
            "renderer_disabled": True,
            "generation_loss_disabled": True,
            "core_assignment_frozen": True,
            "real_alignment_excluded": True,
            "consistency_default_enabled": bool(spec.get("consistency", {}).get("enabled", False)),
            "core_method_config": {
                "null_slot": dict(spec.get("null_slot", {})),
                "dual_cardinality": dict(spec.get("dual_cardinality", spec.get("cardinality_schedule", {}))),
                "assignment_schedule": dict(spec.get("assignment_schedule", {})),
                "evidence_graph": dict(spec.get("evidence_graph", {})),
                "consistency_enabled": bool(spec.get("consistency", {}).get("enabled", False)),
            },
        },
    )


def build_stage2_freeze_plan(spec: dict[str, Any], phase: str) -> ComponentFreezePlan:
    if phase == "first_half":
        return ComponentFreezePlan(
            phase=phase,
            frozen_components=["encoder.lower", "relation_encoder", "slot_queries", "assignment_decoder", "background_routing_head", "renderer"],
            trainable_components=["count_head", "existence_head", "count_temperature", "existence_temperature", "selective_risk_calibration"],
            metadata={"renderer_lr": float(spec.get("freeze_strategy", {}).get("first_half", {}).get("renderer_lr", 0.0))},
        )
    return ComponentFreezePlan(
        phase=phase,
        frozen_components=["encoder.lower", "relation_encoder", "slot_queries", "assignment_decoder", "background_routing_head", "renderer"],
        trainable_components=["count_head", "existence_head", "count_temperature", "existence_temperature", "selective_risk_calibration"],
        metadata={"renderer_lr": float(spec.get("freeze_strategy", {}).get("second_half", {}).get("renderer_lr", 0.0))},
    )


def build_stage2_lr_plan(spec: dict[str, Any], base_lr: float) -> Any:
    multiplier = float(spec.get("freeze_strategy", {}).get("second_half", {}).get("encoder_lr_multiplier", 0.1))
    renderer_lr = float(spec.get("freeze_strategy", {}).get("first_half", {}).get("renderer_lr", 0.0))
    return build_component_lr_groups(base_lr, encoder_lr_multiplier=multiplier, renderer_lr=renderer_lr)


def validate_stage2_training_plan(plan: TrainingPlan) -> dict[str, Any]:
    errors: list[str] = []
    if "m_final_test" not in plan.forbidden_assets:
        errors.append("m_final_test_not_forbidden")
    if plan.metadata.get("renderer_disabled") is not True:
        errors.append("renderer_must_be_disabled")
    return {"valid": not errors, "errors": errors, "approved": plan.approved}


def compute_stage2_loss_for_batch(outputs: TrainOutputs, batch: TrainBatch, spec: dict[str, Any]) -> LossResult:
    diagnostics = {
        "source_kind": batch.source_kind,
        "count_loss_used": False,
        "pb_loss_used": False,
        "alignment_loss_used": False,
        "censored_supervision_used": False,
        "exact_k_supervision_used": False,
        "generation_loss_used": False,
        "role_loss_used": False,
        "cohesion_loss_used": False,
    }
    output_dict = _outputs_to_loss_dict(outputs)
    if batch.source_kind == "strict_replay":
        if getattr(outputs, "assignment_probs", None) is not None and hasattr(getattr(outputs, "count_logits"), "size"):
            replay = strict_replay_loss(
                outputs,
                gold=_build_stage1_targets(batch, outputs),
                weights={
                    "lambda_align": float(spec.get("loss_weights", {}).get("lambda_align", 1.0)),
                    "lambda_count": float(spec.get("loss_weights", {}).get("lambda_count", 0.5)),
                    "lambda_exist": float(spec.get("loss_weights", {}).get("lambda_exist", 0.5)),
                },
            )
        else:
            replay = strict_replay_loss({"loss_main": _proxy_replay_loss(outputs, batch)}, gold=None, weights=None)
        diagnostics["count_loss_used"] = True
        diagnostics["pb_loss_used"] = True
        diagnostics["alignment_loss_used"] = True
        diagnostics["strict_replay_used"] = True
        return LossResult(
            loss=replay["loss_total"],
            loss_name="strict_replay",
            components={key: value for key, value in replay.items() if key.startswith("loss_")},
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    if batch.source_kind == "hard_b":
        hard = hard_b_loss(output_dict, **dict(spec.get("hard_b_loss", {})))
        diagnostics["count_loss_used"] = True
        diagnostics["pb_loss_used"] = True
        diagnostics.update(compute_hard_b_compactness_diagnostics(outputs, batch))
        return LossResult(
            loss=hard["loss_total"],
            loss_name="hard_b",
            components={"hard_b_count_loss": hard["hard_b_count_loss"], "hard_b_pb_loss": hard["hard_b_pb_loss"]},
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    if batch.source_kind == "m_weak":
        weak = m_censored_loss(output_dict, **dict(spec.get("m_censored_loss", {})))
        diagnostics["count_loss_used"] = True
        diagnostics["pb_loss_used"] = True
        diagnostics["censored_supervision_used"] = True
        diagnostics["exact_k_supervision_used"] = False
        diagnostics["consistency_used"] = bool(spec.get("consistency", {}).get("enabled", False))
        return LossResult(
            loss=weak["loss_total"],
            loss_name="m_censored",
            components={"p_multi_count": weak["p_multi_count"], "p_multi_pb": weak["p_multi_pb"]},
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    if batch.source_kind in {"real_alignment", "m_align_calib"}:
        return LossResult(
            loss=_zero_loss(outputs),
            loss_name="real_alignment_excluded_from_stage2",
            components={},
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    return LossResult(loss=_zero_loss(outputs), loss_name="unsupported", components={}, diagnostics=diagnostics, source_kind=batch.source_kind)


def combine_stage2_epoch_results(step_results: list[TrainStepResult]) -> EpochResult:
    source_counts = Counter(step.source_kind for step in step_results)
    mean_loss = (sum(step.loss_total for step in step_results) / len(step_results)) if step_results else 0.0
    return EpochResult(
        step_count=len(step_results),
        mean_loss=mean_loss,
        source_kind_counts=dict(source_counts),
        diagnostics=summarize_stage2_diagnostics(step_results),
    )


def summarize_stage2_diagnostics(step_results: list[TrainStepResult]) -> dict[str, Any]:
    histogram = Counter()
    numeric_values: dict[str, list[float]] = {}
    for step in step_results:
        for key, value in step.diagnostics.items():
            if value is True:
                histogram[key] += 1
            elif key.startswith("hard_b_") and isinstance(value, int | float):
                numeric_values.setdefault(key, []).append(float(value))
    summary: dict[str, Any] = dict(histogram)
    for key, values in numeric_values.items():
        if values:
            summary[f"mean_{key}"] = sum(values) / len(values)
    return summary


def compute_hard_b_compactness_diagnostics(outputs: TrainOutputs, batch: TrainBatch, *, tau_fg: float = 0.5) -> dict[str, Any]:
    """Report hard_b evidence retention without adding weak assignment supervision."""
    assignment_probs = getattr(outputs, "assignment_probs", None)
    null_assignment_probs = getattr(outputs, "null_assignment_probs", None)
    if assignment_probs is None or null_assignment_probs is None:
        return {
            "hard_b_compactness_protocol": "report_only_no_assignment_loss",
            "hard_b_compactness_status": "values_to_be_populated_by_backend_outputs",
            "hard_b_compactness_loss_used": False,
        }

    assignment = _first_sample_tensor(assignment_probs)
    null_probs = _first_sample_tensor(null_assignment_probs).reshape(-1)
    if assignment.ndim != 2:
        raise ValueError("hard_b compactness diagnostics require assignment_probs with shape (Kmax, units).")
    if null_probs.numel() != assignment.size(1):
        raise ValueError("hard_b compactness diagnostics require null_assignment_probs to match unit count.")

    semantic_mask = _semantic_unit_mask(batch, assignment.size(1), device=assignment.device, dtype=assignment.dtype)
    semantic_denominator = semantic_mask.sum().clamp_min(1.0)
    top1_mass = assignment.max(dim=0).values
    top1_retained = (top1_mass * semantic_mask).sum() / semantic_denominator
    residual = (torch.tensor(float(tau_fg), device=assignment.device, dtype=assignment.dtype) - top1_mass).clamp_min(0.0)
    residual_foreground_mass = (residual * semantic_mask).sum() / semantic_denominator
    background_swallowing = (null_probs.to(device=assignment.device, dtype=assignment.dtype) * semantic_mask).sum() / semantic_denominator

    return {
        "hard_b_compactness_protocol": "report_only_no_assignment_loss",
        "hard_b_compactness_loss_used": False,
        "hard_b_top1_retained_foreground_mass": float(top1_retained.detach().cpu().item()),
        "hard_b_residual_foreground_mass": float(residual_foreground_mass.detach().cpu().item()),
        "hard_b_background_swallowing_rate": float(background_swallowing.detach().cpu().item()),
        "hard_b_semantic_unit_count": int(semantic_mask.sum().detach().cpu().item()),
    }


def _first_sample_tensor(value: Any) -> torch.Tensor:
    tensor = _to_tensor(value)
    if tensor.ndim >= 3 and tensor.size(0) == 1:
        return tensor[0]
    if tensor.ndim == 2 and tensor.size(0) == 1:
        return tensor[0]
    return tensor


def _semantic_unit_mask(batch: TrainBatch, unit_count: int, *, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    values: list[float] = []
    for unit in batch.edit_units[:unit_count]:
        role = str(unit.get("file_role", "source") or "source").lower()
        values.append(0.0 if role in {"generated", "lockfile", "vendor", "minified", "unknown_auxiliary"} else 1.0)
    while len(values) < unit_count:
        values.append(1.0)
    if not values:
        values = [1.0]
    return torch.tensor(values, device=device, dtype=dtype)

def _outputs_to_loss_dict(outputs: TrainOutputs) -> dict[str, Any]:
    return {
        "count_probs": outputs.count_probs,
        "pb_count_probs": outputs.pb_count_probs,
        "slot_exist_probs": outputs.slot_exist_probs,
    }


def _build_stage1_targets(batch: TrainBatch, outputs: TrainOutputs) -> dict[str, Any]:
    gold_count = max(int(batch.gold_count or 1), 1)
    unit_ids = [str(unit.get("unit_id", f"unit_{index}")) for index, unit in enumerate(batch.edit_units)]
    gold_assignment_masks = torch.zeros(gold_count, max(len(unit_ids), 1), dtype=torch.float32)
    unit_mask = outputs.unit_mask if outputs.unit_mask is not None else torch.ones(1, max(len(unit_ids), 1), dtype=torch.bool)
    gold_unit_to_intent = batch.gold_unit_to_intent or {}
    if gold_unit_to_intent:
        label_to_index = {label: index for index, label in enumerate(sorted(set(gold_unit_to_intent.values())))}
        for unit_index, unit_id in enumerate(unit_ids):
            label = gold_unit_to_intent.get(unit_id)
            if label is not None and label in label_to_index:
                gold_assignment_masks[label_to_index[label], unit_index] = 1.0
    elif batch.gold_hunk_to_intent:
        hunk_to_index = {label: index for index, label in enumerate(sorted(set(batch.gold_hunk_to_intent.values())))}
        for unit_index, unit in enumerate(batch.edit_units):
            hunk_id = str(unit.get("hunk_id", unit_ids[unit_index]))
            label = batch.gold_hunk_to_intent.get(hunk_id)
            if label is not None and label in hunk_to_index:
                gold_assignment_masks[hunk_to_index[label], unit_index] = 1.0
    return {
        "gold_counts": torch.tensor([gold_count], dtype=torch.long),
        "gold_assignment_masks": [gold_assignment_masks],
        "unit_mask": unit_mask,
    }


def _zero_loss(outputs: TrainOutputs) -> torch.Tensor:
    return _to_tensor(outputs.count_logits).sum() * 0.0


def _to_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)


def _proxy_replay_loss(outputs: TrainOutputs, batch: TrainBatch) -> torch.Tensor:
    if batch.gold_count is None:
        return _zero_loss(outputs)
    count_probs = _to_tensor(outputs.count_probs).reshape(-1)
    pb_probs = _to_tensor(outputs.pb_count_probs).reshape(-1)
    slot_exist = _to_tensor(outputs.slot_exist_probs).reshape(-1)
    gold_index = max(min(batch.gold_count - 1, count_probs.numel() - 1), 0)
    count_term = -count_probs[gold_index].clamp_min(1e-6).log()
    pb_term = -pb_probs[gold_index].clamp_min(1e-6).log() if gold_index < pb_probs.numel() else count_term * 0.0
    active_slots = max(int(batch.gold_count or 1), 1)
    exist_target = torch.zeros_like(slot_exist)
    exist_target[: min(active_slots, slot_exist.numel())] = 1.0
    exist_term = torch.nn.functional.binary_cross_entropy(slot_exist.clamp(1e-6, 1 - 1e-6), exist_target, reduction="mean")
    align_bonus = torch.tensor(0.25 if batch.gold_unit_to_intent or batch.gold_hunk_to_intent else 0.0, dtype=torch.float32)
    return count_term + 0.5 * pb_term + 0.5 * exist_term + align_bonus
