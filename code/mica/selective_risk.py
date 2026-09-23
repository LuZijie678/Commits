from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch


@dataclass(slots=True)
class SelectiveRiskResult:
    risk_score: torch.Tensor
    components: dict[str, torch.Tensor]
    diagnostics: dict[str, Any]


RISK_COMPONENT_NAMES = (
    "capacity_saturation",
    "count_pb_js",
    "assignment_entropy",
    "residual_foreground_mass",
    "low_slot_margin",
)


def build_dev_selective_calibration_artifact(
    rows: list[dict[str, Any]],
    *,
    target_coverage: float | None = None,
    target_risk: float | None = None,
) -> dict[str, Any]:
    """Freeze dev-only selective-risk normalization and threshold metadata.

    The artifact intentionally stores protocol state and dev-derived values only.
    It never infers values from final-test rows and never fabricates overflow gold.
    """
    if target_coverage is not None and target_risk is not None:
        raise ValueError("selective calibration accepts either target_coverage or target_risk, not both.")
    final_test_rows = [row for row in rows if _is_final_test_split(row.get("split"))]
    if final_test_rows:
        raise ValueError("final-test rows are forbidden for selective-risk calibration.")
    dev_rows = [row for row in rows if str(row.get("split", "dev")).lower() in {"dev", "calib", "calibration"}]
    component_values: dict[str, list[float]] = {name: [] for name in RISK_COMPONENT_NAMES}
    risk_scores: list[float] = []
    for row in dev_rows:
        components = dict(row.get("risk_components", {}))
        for name in RISK_COMPONENT_NAMES:
            if name in components:
                component_values[name].append(float(components[name]))
        if row.get("risk_score") is not None:
            risk_scores.append(float(row["risk_score"]))
    normalization = {
        name: _normalization_stats(values)
        for name, values in component_values.items()
    }
    populated_component_count = sum(1 for values in component_values.values() if values)
    values_populated = bool(risk_scores) and populated_component_count == len(RISK_COMPONENT_NAMES)
    threshold = _select_threshold(risk_scores, target_coverage=target_coverage, target_risk=target_risk)
    return {
        "artifact_type": "selective_risk_dev_calibration",
        "status": "protocol_defined" if dev_rows else "protocol_defined_but_values_not_populated",
        "values_status": "populated_from_dev_only" if values_populated else "values_to_be_populated_by_dev_calibration_script",
        "selection_split": "dev_only",
        "final_test_tuning": "forbidden",
        "weights": {name: 1.0 for name in RISK_COMPONENT_NAMES},
        "normalization": normalization,
        "threshold": threshold,
        "threshold_selection_rule": _threshold_rule(target_coverage=target_coverage, target_risk=target_risk),
        "dev_row_count": len(dev_rows),
        "dev_risk_score_count": len(risk_scores),
        "dev_component_value_counts": {name: len(values) for name, values in component_values.items()},
        "paper_readiness": "protocol_defined" if values_populated else "not_final_paper_ready_until_dev_calibration_artifact_is_frozen",
    }


def compute_selective_risk(
    *,
    count_probs: torch.Tensor,
    pb_count_probs: torch.Tensor,
    assignment_probs: torch.Tensor,
    null_assignment_probs: torch.Tensor | None = None,
    semantic_unit_mask: torch.Tensor | None = None,
    weights: dict[str, float] | None = None,
    tau_fg: float = 0.5,
    margin_delta: float = 0.2,
) -> SelectiveRiskResult:
    if count_probs.ndim != 1 or pb_count_probs.ndim != 1:
        raise ValueError("count_probs and pb_count_probs must be 1D tensors.")
    if assignment_probs.ndim != 2:
        raise ValueError("assignment_probs must have shape (Kmax, units).")
    if count_probs.numel() != pb_count_probs.numel():
        raise ValueError("count_probs and pb_count_probs must have the same count support.")

    device = assignment_probs.device
    dtype = assignment_probs.dtype
    unit_count = assignment_probs.size(1)
    semantic_mask = _semantic_mask(semantic_unit_mask, unit_count, device=device, dtype=dtype)
    count_distribution = count_probs.to(device=device, dtype=dtype).clamp_min(1e-6)
    pb_distribution = pb_count_probs.to(device=device, dtype=dtype).clamp_min(1e-6)
    count_distribution = count_distribution / count_distribution.sum().clamp_min(1e-6)
    pb_distribution = pb_distribution / pb_distribution.sum().clamp_min(1e-6)

    capacity_saturation = count_distribution[-1]
    js_divergence = _js_divergence(count_distribution, pb_distribution)
    fg_entropy = _masked_mean(_entropy(assignment_probs.clamp_min(1e-6), dim=0), semantic_mask)
    residual_foreground_mass = _residual_foreground_mass(assignment_probs, semantic_mask, tau_fg=tau_fg)
    low_slot_margin = _low_slot_margin(assignment_probs, semantic_mask, margin_delta=margin_delta)
    components = {
        "capacity_saturation": capacity_saturation,
        "count_pb_js": js_divergence,
        "assignment_entropy": fg_entropy,
        "residual_foreground_mass": residual_foreground_mass,
        "low_slot_margin": low_slot_margin,
    }
    if null_assignment_probs is not None:
        joint = torch.cat([assignment_probs, null_assignment_probs.to(device=device, dtype=dtype).unsqueeze(0)], dim=0)
        components["foreground_plus_null_entropy"] = _masked_mean(_entropy(joint.clamp_min(1e-6), dim=0), semantic_mask)

    default_weights = {name: 1.0 for name in RISK_COMPONENT_NAMES}
    merged_weights = {**default_weights, **dict(weights or {})}
    risk_score = sum(components[name] * float(merged_weights.get(name, 0.0)) for name in default_weights)
    return SelectiveRiskResult(
        risk_score=risk_score,
        components=components,
        diagnostics={
            "risk_protocol": "fixed_non_learned_weighted_components",
            "normalization_split": "dev_only_required_for_calibrated_use",
            "final_test_tuning": "forbidden",
            "weights_source": "fixed_equal_weights_unless_dev_calibration_artifact_supplied",
            "semantic_unit_count": int(semantic_mask.sum().item()),
            "null_entropy_reported": null_assignment_probs is not None,
        },
    )


def _entropy(probs: torch.Tensor, *, dim: int) -> torch.Tensor:
    normalized = probs / probs.sum(dim=dim, keepdim=True).clamp_min(1e-6)
    return -(normalized * normalized.clamp_min(1e-6).log()).sum(dim=dim)


def _js_divergence(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    midpoint = 0.5 * (left + right)
    return 0.5 * _kl(left, midpoint) + 0.5 * _kl(right, midpoint)


def _kl(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    return (left * (left.clamp_min(1e-6).log() - right.clamp_min(1e-6).log())).sum()


def _residual_foreground_mass(assignment_probs: torch.Tensor, semantic_mask: torch.Tensor, *, tau_fg: float) -> torch.Tensor:
    max_fg = assignment_probs.max(dim=0).values
    residual = torch.relu(torch.tensor(tau_fg, device=assignment_probs.device, dtype=assignment_probs.dtype) - max_fg)
    return _masked_mean(residual, semantic_mask)


def _low_slot_margin(assignment_probs: torch.Tensor, semantic_mask: torch.Tensor, *, margin_delta: float) -> torch.Tensor:
    if assignment_probs.size(0) < 2:
        return torch.zeros((), device=assignment_probs.device, dtype=assignment_probs.dtype)
    top2 = torch.topk(assignment_probs, k=2, dim=0).values
    margin = top2[0] - top2[1]
    penalty = torch.relu(torch.tensor(margin_delta, device=assignment_probs.device, dtype=assignment_probs.dtype) - margin)
    return _masked_mean(penalty, semantic_mask)


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (values * mask).sum() / mask.sum().clamp_min(1.0)


def _semantic_mask(mask: torch.Tensor | None, unit_count: int, *, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    if mask is None:
        return torch.ones(unit_count, device=device, dtype=dtype)
    if mask.ndim != 1 or mask.numel() != unit_count:
        raise ValueError("semantic_unit_mask must be 1D and match assignment unit dimension.")
    return mask.to(device=device, dtype=dtype)


def _normalization_stats(values: list[float]) -> dict[str, float | str]:
    if not values:
        return {"status": "values_to_be_populated", "mean": 0.0, "std": 1.0}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {"status": "populated_from_dev_only", "mean": mean, "std": max(variance ** 0.5, 1e-6)}


def _select_threshold(
    risk_scores: list[float],
    *,
    target_coverage: float | None,
    target_risk: float | None,
) -> dict[str, float | str | None]:
    if not risk_scores:
        return {"status": "values_to_be_populated", "value": None}
    ordered = sorted(risk_scores)
    if target_risk is not None:
        return {"status": "populated_from_dev_only", "value": float(target_risk)}
    if target_coverage is not None:
        clipped = min(max(float(target_coverage), 0.0), 1.0)
        index = min(max(int(round(clipped * len(ordered))) - 1, 0), len(ordered) - 1)
        return {"status": "populated_from_dev_only", "value": ordered[index]}
    return {"status": "coverage_risk_curve_only", "value": None}


def _threshold_rule(*, target_coverage: float | None, target_risk: float | None) -> str:
    if target_coverage is not None:
        return "predeclared_target_coverage_on_dev"
    if target_risk is not None:
        return "predeclared_target_risk_on_dev"
    return "full_coverage_risk_curve"


def _is_final_test_split(value: Any) -> bool:
    return str(value or "").lower() in {"test", "final_test", "m-final-test", "m_final_test"}
