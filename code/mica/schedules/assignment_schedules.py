from __future__ import annotations

from typing import Any


def compute_assignment_temperature(step: int, total_steps: int, spec: dict[str, Any]) -> float:
    cfg = dict(spec.get("assignment_schedule", spec))
    start = float(cfg.get("tau_start", 2.0))
    end = float(cfg.get("tau_end", 1.0))
    progress = _progress(step, total_steps)
    return round(start + (end - start) * progress, 10)


def compute_assignment_entropy_coeff(step: int, total_steps: int, spec: dict[str, Any]) -> float:
    cfg = dict(spec.get("assignment_schedule", spec))
    start = float(cfg.get("entropy_coeff_start", 0.02))
    end = float(cfg.get("entropy_coeff_end", 0.0))
    progress = _progress(step, total_steps)
    return round(start + (end - start) * progress, 10)


def _progress(step: int, total_steps: int) -> float:
    if total_steps <= 0:
        return 0.0
    return min(max(float(step) / float(total_steps), 0.0), 1.0)

