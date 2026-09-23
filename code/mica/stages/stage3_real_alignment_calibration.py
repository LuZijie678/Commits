from __future__ import annotations

from collections import Counter
from typing import Any

import torch
import torch.nn.functional as F

from code.mica.data.real_alignment import check_double_annotation_coverage, summarize_real_alignment, validate_real_alignment_rows
from code.mica.losses.stage2_losses import strict_replay_loss
from code.mica.training.trainer_types import ComponentFreezePlan, LossResult, TrainBatch, TrainOutputs, TrainingPlan, TrainStepResult


def prepare_stage3_real_alignment_calibration(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage": spec.get("stage", "stage3_real_alignment_calibration"),
        "validation": validate_real_alignment_rows(rows),
        "summary": summarize_real_alignment(rows),
        "double_annotation": check_double_annotation_coverage(rows),
        "training_executed": False,
    }


def build_stage3_calibration_plan(spec: dict[str, Any], alignment_summary: dict[str, Any]) -> TrainingPlan:
    freeze = build_stage3_freeze_plan(spec)
    stage3_plus_enabled = bool(spec.get("stage3_plus", {}).get("enabled", False))
    return TrainingPlan(
        stage=str(spec.get("stage", "stage3_real_alignment_calibration")),
        mode=str(spec.get("default_mode", "dry_run")),
        approved=bool(spec.get("advisor_stage3_approved", False)),
        dry_run=str(spec.get("default_mode", "dry_run")) == "dry_run",
        trainable_components=list(freeze.trainable_components),
        frozen_components=list(freeze.frozen_components),
        loss_weights={
            "lambda_align_real": 1.0 if stage3_plus_enabled else 0.0,
            "lambda_count_real": 0.5,
            "lambda_exist": 0.3,
            "lambda_replay": 0.3,
            "lambda_drift": float(spec.get("stage3_plus", {}).get("lambda_drift", 0.0)),
        },
        data_mixture={"real_alignment": alignment_summary, "strict_replay_required": bool(spec.get("strict_replay_required", True))},
        forbidden_assets=["m_final_test"],
        metadata={
            "strict_replay_required": bool(spec.get("strict_replay_required", True)),
            "generation_loss_disabled": True,
            "stage3_core_default": not stage3_plus_enabled,
            "stage3_plus_enabled": stage3_plus_enabled,
            "core_method_config": {
                "null_slot": dict(spec.get("null_slot", {})),
                "dual_cardinality": dict(spec.get("dual_cardinality", spec.get("cardinality_schedule", {}))),
                "assignment_schedule": dict(spec.get("assignment_schedule", {})),
                "evidence_graph": dict(spec.get("evidence_graph", {})),
                "consistency_enabled": bool(spec.get("consistency", {}).get("enabled", False)),
            },
        },
    )


def build_stage3_freeze_plan(spec: dict[str, Any]) -> ComponentFreezePlan:
    stage3_plus_enabled = bool(spec.get("stage3_plus", {}).get("enabled", False))
    trainable = ["count_temperature", "existence_temperature"]
    if stage3_plus_enabled:
        trainable.extend(["low_rank_assignment_adapter", "slot_existence_temperature"])
    return ComponentFreezePlan(
        phase="stage3",
        frozen_components=[
            "base_encoder",
            "base_slot_decoder",
            "base_slot_queries",
            "base_assignment_scorer",
            "renderer",
        ],
        trainable_components=trainable,
        metadata={
            "stage3_core_default": not stage3_plus_enabled,
            "stage3_plus_enabled": stage3_plus_enabled,
            "full_encoder_decoder_finetuning_allowed": False,
        },
    )


def compute_stage3_loss_for_batch(outputs: TrainOutputs, batch: TrainBatch, spec: dict[str, Any]) -> LossResult:
    diagnostics = {
        "source_kind": batch.source_kind,
        "strict_replay_used": False,
        "generation_loss_used": False,
        "renderer_loss_used": False,
        "missing_real_alignment_gold": False,
    }
    stage3_plus_enabled = bool(spec.get("stage3_plus", {}).get("enabled", False))
    if batch.source_kind == "real_alignment":
        if not batch.gold_unit_to_intent and not batch.gold_hunk_to_intent:
            diagnostics["missing_real_alignment_gold"] = True
            return LossResult(loss=_zero_loss(outputs), loss_name="missing_real_alignment_gold", components={}, diagnostics=diagnostics, source_kind=batch.source_kind)
        if not stage3_plus_enabled:
            diagnostics["stage3_core_no_assignment_training"] = True
            core_loss = _stage3_core_calibration_loss(outputs, batch, spec)
            diagnostics["stage3_core_calibration_loss_used"] = True
            return LossResult(
                loss=core_loss,
                loss_name="stage3_core_calibration_only",
                components={"loss_stage3_core_calibration": core_loss},
                diagnostics=diagnostics,
                source_kind=batch.source_kind,
            )
        if getattr(outputs, "assignment_probs", None) is not None and hasattr(getattr(outputs, "count_logits"), "size"):
            real_loss = strict_replay_loss(
                outputs,
                gold=_build_stage1_targets(batch, outputs),
                weights={
                    "lambda_align": float(spec.get("loss_weights", {}).get("lambda_align_real", 1.0)),
                    "lambda_count": float(spec.get("loss_weights", {}).get("lambda_count_real", 0.5)),
                    "lambda_exist": float(spec.get("loss_weights", {}).get("lambda_exist", 0.3)),
                },
            )
        else:
            real_loss = strict_replay_loss({"loss_main": _proxy_real_alignment_loss(outputs, batch)}, gold=None, weights=None)
        drift = _assignment_drift_loss(outputs, batch)
        lambda_drift = float(spec.get("stage3_plus", {}).get("lambda_drift", spec.get("loss_weights", {}).get("lambda_drift", 0.0)))
        loss_total = real_loss["loss_total"] + lambda_drift * drift
        diagnostics["assignment_drift_regularized"] = lambda_drift > 0.0
        diagnostics["stage3_plus_assignment_adapter"] = True
        return LossResult(
            loss=loss_total,
            loss_name="real_alignment",
            components={
                **{key: value for key, value in real_loss.items() if key.startswith("loss_")},
                "loss_drift": drift,
                "lambda_drift": torch.tensor(lambda_drift, dtype=drift.dtype, device=drift.device),
            },
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    if batch.source_kind == "strict_replay":
        diagnostics["strict_replay_used"] = True
        if getattr(outputs, "assignment_probs", None) is not None and hasattr(getattr(outputs, "count_logits"), "size"):
            replay = strict_replay_loss(
                outputs,
                gold=_build_stage1_targets(batch, outputs),
                weights={"lambda_align": 1.0, "lambda_count": 0.5, "lambda_exist": 0.5},
            )
        else:
            replay = strict_replay_loss({"loss_main": _proxy_real_alignment_loss(outputs, batch)}, gold=None, weights=None)
        replay_weight = float(spec.get("loss_weights", {}).get("lambda_replay", 0.3))
        return LossResult(
            loss=replay_weight * replay["loss_total"],
            loss_name="strict_replay",
            components={"loss_replay": replay_weight * replay["loss_total"]},
            diagnostics=diagnostics,
            source_kind=batch.source_kind,
        )
    return LossResult(loss=_zero_loss(outputs), loss_name="unsupported", components={}, diagnostics=diagnostics, source_kind=batch.source_kind)


def summarize_stage3_diagnostics(step_results: list[TrainStepResult]) -> dict[str, Any]:
    histogram = Counter()
    for step in step_results:
        for key, value in step.diagnostics.items():
            if value is True:
                histogram[key] += 1
    return dict(histogram)

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
    if isinstance(outputs.count_logits, torch.Tensor):
        return outputs.count_logits.sum() * 0.0
    return torch.tensor(0.0)


def _proxy_real_alignment_loss(outputs: TrainOutputs, batch: TrainBatch) -> torch.Tensor:
    if batch.gold_count is None:
        return _zero_loss(outputs)
    count_probs = torch.tensor(outputs.count_probs, dtype=torch.float32).reshape(-1)
    slot_exist_probs = torch.tensor(outputs.slot_exist_probs, dtype=torch.float32).reshape(-1)
    gold_index = max(min(batch.gold_count - 1, count_probs.numel() - 1), 0)
    count_term = -count_probs[gold_index].clamp_min(1e-6).log()
    exist_target = torch.zeros_like(slot_exist_probs)
    exist_target[: min(batch.gold_count, slot_exist_probs.numel())] = 1.0
    exist_term = torch.nn.functional.binary_cross_entropy(slot_exist_probs.clamp(1e-6, 1 - 1e-6), exist_target, reduction="mean")
    align_term = torch.tensor(1.0 if batch.gold_unit_to_intent or batch.gold_hunk_to_intent else 0.0, dtype=torch.float32)
    return align_term + 0.5 * count_term + 0.3 * exist_term


def _stage3_core_calibration_loss(outputs: TrainOutputs, batch: TrainBatch, spec: dict[str, Any]) -> torch.Tensor:
    if batch.gold_count is None:
        return _zero_loss(outputs)
    count_probs = torch.as_tensor(outputs.count_probs, dtype=torch.float32).reshape(-1)
    slot_exist_probs = torch.as_tensor(outputs.slot_exist_probs, dtype=torch.float32).reshape(-1)
    gold_index = max(min(int(batch.gold_count) - 1, count_probs.numel() - 1), 0)
    count_term = -count_probs[gold_index].clamp_min(1e-6).log()
    active_slots = max(min(int(batch.gold_count), slot_exist_probs.numel()), 1)
    exist_target = torch.zeros_like(slot_exist_probs)
    exist_target[:active_slots] = 1.0
    exist_term = torch.nn.functional.binary_cross_entropy(slot_exist_probs.clamp(1e-6, 1 - 1e-6), exist_target, reduction="mean")
    weights = dict(spec.get("loss_weights", {}))
    lambda_count = float(weights.get("lambda_count_real", 0.5))
    lambda_exist = float(weights.get("lambda_exist", 0.3))
    return lambda_count * count_term + lambda_exist * exist_term


def _assignment_drift_loss(outputs: TrainOutputs, batch: TrainBatch) -> torch.Tensor:
    assignment_probs = getattr(outputs, "assignment_probs", None)
    if not isinstance(assignment_probs, torch.Tensor):
        return _zero_loss(outputs)
    base_assignment_probs = batch.metadata.get("base_assignment_probs")
    if base_assignment_probs is None:
        base_assignment_probs = outputs.diagnostics.get("base_assignment_probs")
    if base_assignment_probs is None:
        return assignment_probs.sum() * 0.0
    base = torch.as_tensor(base_assignment_probs, dtype=assignment_probs.dtype, device=assignment_probs.device)
    if base.shape != assignment_probs.shape:
        raise ValueError("base_assignment_probs must match assignment_probs shape for Stage 3-Plus drift regularization.")
    adapted = assignment_probs.clamp_min(1e-6)
    reference = base.clamp_min(1e-6)
    unit_mask = getattr(outputs, "unit_mask", None)
    if isinstance(unit_mask, torch.Tensor):
        mask = unit_mask.to(device=assignment_probs.device, dtype=assignment_probs.dtype).unsqueeze(1)
    else:
        mask = torch.ones_like(assignment_probs)
    per_unit_kl = F.kl_div(adapted.log(), reference, reduction="none").sum(dim=1)
    unit_denominator = mask.squeeze(1).sum().clamp_min(1.0)
    return (per_unit_kl * mask.squeeze(1)).sum() / unit_denominator
