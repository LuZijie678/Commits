from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

import torch

from code.mica.stages.stage2_real_calibration import combine_stage2_epoch_results, compute_stage2_loss_for_batch
from code.mica.stages.stage3_real_alignment_calibration import compute_stage3_loss_for_batch, summarize_stage3_diagnostics
from code.mica.training.trainer_types import ComponentFreezePlan, EpochResult, TrainBatch, TrainStepResult


def run_train_epoch(
    backend,
    batches: list[TrainBatch] | Iterable[TrainBatch],
    stage: str,
    spec: dict[str, Any],
    optimizer,
    freeze_plan: ComponentFreezePlan | None = None,
) -> EpochResult:
    if freeze_plan is not None:
        backend.apply_freeze_plan(freeze_plan)
    backend.set_train_mode()
    step_results: list[TrainStepResult] = []
    loss_name_histogram: Counter[str] = Counter()
    gradient_step_count = 0
    nan_step_count = 0
    losses: list[float] = []
    for batch in list(batches):
        optimizer.zero_grad()
        outputs = backend.forward(batch)
        loss_result = _compute_loss(stage=stage, outputs=outputs, batch=batch, spec=spec)
        loss_name_histogram[loss_result.loss_name] += 1
        weighted_loss = _to_tensor(loss_result.loss) * float(batch.sample_weight)
        if not torch.isfinite(weighted_loss):
            nan_step_count += 1
            step_results.append(
                TrainStepResult(
                    sample_ids=list(batch.sample_ids),
                    source_kind=batch.source_kind,
                    loss_total=float("nan"),
                    diagnostics={**loss_result.diagnostics, "non_finite_loss": True},
                )
            )
            continue
        weighted_loss.backward()
        clip_norm = spec.get("gradient_clip_norm")
        if clip_norm:
            torch.nn.utils.clip_grad_norm_(backend.trainable_parameters(), float(clip_norm))
        optimizer.step()
        gradient_step_count += 1
        scalar_loss = float(weighted_loss.detach().item())
        losses.append(scalar_loss)
        step_results.append(
            TrainStepResult(
                sample_ids=list(batch.sample_ids),
                source_kind=batch.source_kind,
                loss_total=scalar_loss,
                diagnostics={**loss_result.diagnostics, "loss_name": loss_result.loss_name},
            )
        )
    return _finalize_epoch(stage, step_results, gradient_step_count=gradient_step_count, nan_step_count=nan_step_count, loss_name_histogram=loss_name_histogram, losses=losses)


def run_eval_epoch(
    backend,
    batches: list[TrainBatch] | Iterable[TrainBatch],
    stage: str,
    spec: dict[str, Any],
) -> EpochResult:
    backend.set_eval_mode()
    step_results: list[TrainStepResult] = []
    loss_name_histogram: Counter[str] = Counter()
    losses: list[float] = []
    with torch.no_grad():
        for batch in list(batches):
            outputs = backend.forward(batch)
            loss_result = _compute_loss(stage=stage, outputs=outputs, batch=batch, spec=spec)
            loss_name_histogram[loss_result.loss_name] += 1
            scalar_loss = float(_to_tensor(loss_result.loss).detach().item())
            losses.append(scalar_loss)
            step_results.append(
                TrainStepResult(
                    sample_ids=list(batch.sample_ids),
                    source_kind=batch.source_kind,
                    loss_total=scalar_loss,
                    diagnostics={**loss_result.diagnostics, "loss_name": loss_result.loss_name},
                )
            )
    return _finalize_epoch(stage, step_results, gradient_step_count=0, nan_step_count=0, loss_name_histogram=loss_name_histogram, losses=losses)


def _compute_loss(*, stage: str, outputs, batch: TrainBatch, spec: dict[str, Any]):
    if stage == "stage2":
        return compute_stage2_loss_for_batch(outputs, batch, spec)
    if stage == "stage3":
        return compute_stage3_loss_for_batch(outputs, batch, spec)
    raise KeyError(f"Unsupported stage: {stage}")


def _finalize_epoch(
    stage: str,
    step_results: list[TrainStepResult],
    *,
    gradient_step_count: int,
    nan_step_count: int,
    loss_name_histogram: Counter[str],
    losses: list[float],
) -> EpochResult:
    if stage == "stage2":
        epoch = combine_stage2_epoch_results(step_results)
    elif stage == "stage3":
        source_counts = Counter(step.source_kind for step in step_results)
        epoch = EpochResult(
            step_count=len(step_results),
            mean_loss=(sum(losses) / len(losses)) if losses else 0.0,
            source_kind_counts=dict(source_counts),
            diagnostics=summarize_stage3_diagnostics(step_results),
        )
    else:
        raise KeyError(f"Unsupported stage: {stage}")
    epoch.gradient_step_count = gradient_step_count
    epoch.nan_step_count = nan_step_count
    epoch.metrics = {"loss_name_histogram": dict(loss_name_histogram)}
    epoch.diagnostics = {**epoch.diagnostics, "loss_name_histogram": dict(loss_name_histogram)}
    return epoch


def _to_tensor(value: Any) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    return torch.tensor(value, dtype=torch.float32)
