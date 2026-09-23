from __future__ import annotations

from typing import Any


def compute_lambda_cal_schedule(step: int, total_steps: int, spec: dict[str, Any]) -> float:
    cfg = dict(spec.get("cardinality_schedule", spec))
    max_value = float(cfg.get("lambda_cal_max", 0.05))
    warmup_fraction = float(cfg.get("kl_warmup_fraction", cfg.get("warmup_fraction", 0.2)))
    progress = _progress(step, total_steps)
    if progress < warmup_fraction:
        return 0.0
    if warmup_fraction >= 1.0:
        return max_value
    scaled = (progress - warmup_fraction) / max(1e-6, 1.0 - warmup_fraction)
    return round(max_value * min(max(scaled, 0.0), 1.0), 10)


def compute_alpha_pb_schedule(step: int, total_steps: int, spec: dict[str, Any]) -> float:
    cfg = dict(spec.get("cardinality_schedule", spec))
    start = float(cfg.get("alpha_pb_start", cfg.get("alpha_pb", 0.5)))
    end = float(cfg.get("alpha_pb_end", start))
    progress = _progress(step, total_steps)
    return round(start + (end - start) * progress, 10)


def _progress(step: int, total_steps: int) -> float:
    if total_steps <= 0:
        return 0.0
    return min(max(float(step) / float(total_steps), 0.0), 1.0)

