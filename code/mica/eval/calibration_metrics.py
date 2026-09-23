from __future__ import annotations

from collections import Counter
from typing import Any


def p_count_pb_gap(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"mean_abs_gap": 0.0}
    gaps = [abs(float(row.get("p_count_multi", 0.0)) - float(row.get("p_pb_multi", 0.0))) for row in rows]
    return {"mean_abs_gap": sum(gaps) / len(gaps)}


def count_ece(rows: list[dict[str, Any]], n_bins: int = 10) -> dict[str, float]:
    if not rows:
        return {"count_ece": 0.0, "n_bins": float(n_bins)}
    probs = [float(row.get("p_true_count", 0.0)) for row in rows]
    hits = [1 if row.get("gold_count") == row.get("pred_count") else 0 for row in rows]
    contributions = []
    for bin_index in range(max(n_bins, 1)):
        lower = bin_index / n_bins
        upper = (bin_index + 1) / n_bins
        indices = [i for i, prob in enumerate(probs) if lower <= prob <= upper or (bin_index == n_bins - 1 and prob == 1.0)]
        if not indices:
            continue
        avg_prob = sum(probs[i] for i in indices) / len(indices)
        avg_acc = sum(hits[i] for i in indices) / len(indices)
        contributions.append((len(indices) / len(rows)) * abs(avg_prob - avg_acc))
    return {"count_ece": sum(contributions), "n_bins": float(n_bins)}


def active_slot_count_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(int(row.get("active_slot_count", 0) or 0) for row in rows)
    return {"active_slot_count_distribution": dict(counts)}
