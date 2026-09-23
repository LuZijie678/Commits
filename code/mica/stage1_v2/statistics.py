from __future__ import annotations

import random
from typing import Any


def build_seed_matrix(protocol_spec: dict[str, Any]) -> dict[str, Any]:
    model_requirements = dict(protocol_spec.get("model_requirements") or {})
    baseline_matrix = dict(protocol_spec.get("baseline_matrix") or {})
    return {
        "mica_seeds": list(model_requirements.get("seeds") or []),
        "learned_baseline_seeds": list(baseline_matrix.get("learned_baseline_seeds") or []),
        "deterministic_baseline_repeats": int(baseline_matrix.get("deterministic_baseline_repeats") or 0),
        "seed_matrix_frozen": True,
    }


def summarize_per_seed_metric(rows: list[dict[str, Any]], metric_key: str) -> dict[str, Any]:
    values = [float(row[metric_key]) for row in rows if row.get(metric_key) is not None]
    if not values:
        return {"count": 0, "mean": None, "std": None, "worst": None}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "count": len(values),
        "mean": mean,
        "std": variance ** 0.5,
        "worst": min(values),
    }


def sample_bootstrap_ci(values: list[float], *, confidence_level: float = 0.95, samples: int = 1000, seed: int = 0) -> dict[str, Any]:
    if not values:
        return {"mean": None, "lower": None, "upper": None, "bootstrap_samples": samples, "confidence_level": confidence_level}
    rng = random.Random(seed)
    bootstrap_values: list[float] = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in range(len(values))]
        bootstrap_values.append(sum(draw) / len(draw))
    ordered = sorted(bootstrap_values)
    lower_index = max(int(((1.0 - confidence_level) / 2.0) * len(ordered)), 0)
    upper_index = min(int((1.0 - (1.0 - confidence_level) / 2.0) * len(ordered)) - 1, len(ordered) - 1)
    return {
        "mean": sum(values) / len(values),
        "lower": ordered[lower_index],
        "upper": ordered[upper_index],
        "bootstrap_samples": samples,
        "confidence_level": confidence_level,
    }


def repository_cluster_bootstrap_ci(
    rows: list[dict[str, Any]],
    *,
    metric_key: str,
    repo_key: str = "repository",
    confidence_level: float = 0.95,
    samples: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get(metric_key) is None:
            continue
        repo = str(row.get(repo_key) or "unknown")
        grouped.setdefault(repo, []).append(float(row[metric_key]))
    repos = sorted(grouped)
    if not repos:
        return {"mean": None, "lower": None, "upper": None, "bootstrap_samples": samples, "confidence_level": confidence_level}
    rng = random.Random(seed)
    bootstrap_values: list[float] = []
    for _ in range(samples):
        values: list[float] = []
        for _index in range(len(repos)):
            repo = repos[rng.randrange(len(repos))]
            values.extend(grouped[repo])
        bootstrap_values.append(sum(values) / len(values))
    ordered = sorted(bootstrap_values)
    lower_index = max(int(((1.0 - confidence_level) / 2.0) * len(ordered)), 0)
    upper_index = min(int((1.0 - (1.0 - confidence_level) / 2.0) * len(ordered)) - 1, len(ordered) - 1)
    raw_values = [float(row[metric_key]) for row in rows if row.get(metric_key) is not None]
    return {
        "mean": (sum(raw_values) / len(raw_values)) if raw_values else None,
        "lower": ordered[lower_index],
        "upper": ordered[upper_index],
        "bootstrap_samples": samples,
        "confidence_level": confidence_level,
    }


def paired_bootstrap_delta(
    left_values: list[float],
    right_values: list[float],
    *,
    confidence_level: float = 0.95,
    samples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    if len(left_values) != len(right_values) or not left_values:
        return {"mean_delta": None, "lower": None, "upper": None, "bootstrap_samples": samples}
    deltas = [left - right for left, right in zip(left_values, right_values)]
    return sample_bootstrap_ci(deltas, confidence_level=confidence_level, samples=samples, seed=seed) | {
        "mean_delta": sum(deltas) / len(deltas)
    }


def paired_permutation_test(left_values: list[float], right_values: list[float], *, permutations: int = 2000, seed: int = 0) -> dict[str, Any]:
    if len(left_values) != len(right_values) or not left_values:
        return {"p_value": None, "permutations": permutations}
    observed = abs(sum(left - right for left, right in zip(left_values, right_values)) / len(left_values))
    rng = random.Random(seed)
    exceed = 0
    for _ in range(permutations):
        permuted = []
        for left, right in zip(left_values, right_values):
            if rng.random() < 0.5:
                permuted.append(left - right)
            else:
                permuted.append(right - left)
        statistic = abs(sum(permuted) / len(permuted))
        exceed += int(statistic >= observed)
    return {"p_value": (exceed + 1) / (permutations + 1), "permutations": permutations}


def holm_bonferroni(p_values: dict[str, float | None]) -> dict[str, Any]:
    defined = [(name, float(value)) for name, value in p_values.items() if value is not None]
    ordered = sorted(defined, key=lambda item: item[1])
    adjusted: dict[str, float | None] = {name: None for name in p_values}
    total = len(ordered)
    for index, (name, value) in enumerate(ordered):
        adjusted[name] = min((total - index) * value, 1.0)
    return {"method": "holm_bonferroni", "adjusted_p_values": adjusted}
