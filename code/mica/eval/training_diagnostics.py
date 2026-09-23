from __future__ import annotations

from collections import Counter
from typing import Any

import math


def slot_collapse_rate(rows: list[dict[str, Any]], threshold: float = 0.75) -> dict[str, Any]:
    flagged = 0
    eligible = 0
    for row in rows:
        predicted_count = int(row.get("predicted_count", 1) or 1)
        assignments = dict(row.get("unit_to_slot", {}))
        if predicted_count < 2 or not assignments:
            continue
        eligible += 1
        counts = Counter(assignments.values())
        dominant = max(counts.values()) / sum(counts.values())
        if dominant >= threshold:
            flagged += 1
    return {"slot_collapse_rate": (flagged / eligible) if eligible else 0.0, "eligible_rows": eligible}


def active_slot_count_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distribution = Counter()
    for row in rows:
        assignments = dict(row.get("unit_to_slot", {}))
        active = len({slot_id for slot_id in assignments.values() if slot_id != "slot_null"})
        distribution[str(active)] += 1
    return {"active_slot_count_distribution": dict(distribution)}


def assignment_entropy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    entropies: list[float] = []
    for row in rows:
        for slot_scores in dict(row.get("assignment_scores", {})).values():
            probs = [max(float(value), 1e-6) for value in dict(slot_scores).values()]
            total = sum(probs)
            if total <= 0.0:
                continue
            normalized = [value / total for value in probs]
            entropies.append(-sum(value * math.log(value) for value in normalized))
    return {"mean_assignment_entropy": (sum(entropies) / len(entropies)) if entropies else 0.0}


def p_count_pb_calibration_gap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps: list[float] = []
    for row in rows:
        count_probs = [float(item) for item in row.get("count_probs", [])]
        pb_probs = [float(item) for item in row.get("pb_count_probs", [])]
        if not count_probs or not pb_probs:
            continue
        width = min(len(count_probs), len(pb_probs))
        gaps.append(sum(abs(count_probs[index] - pb_probs[index]) for index in range(width)) / width)
    return {"mean_abs_gap": (sum(gaps) / len(gaps)) if gaps else 0.0}


def oracle_k_predicted_k_gap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [
        abs(int(row.get("predicted_count", 0) or 0) - int(row.get("oracle_k", row.get("gold_count", 0)) or 0))
        for row in rows
        if row.get("predicted_count") is not None and (row.get("oracle_k") is not None or row.get("gold_count") is not None)
    ]
    return {"mean_abs_gap": (sum(gaps) / len(gaps)) if gaps else 0.0}


def strict_replay_forgetting(rows: list[dict[str, Any]]) -> dict[str, Any]:
    forgetting = []
    for row in rows:
        before = row.get("stage1_replay_metric")
        after = row.get("current_replay_metric")
        if before is None or after is None:
            continue
        forgetting.append(max(float(before) - float(after), 0.0))
    return {"mean_forgetting": (sum(forgetting) / len(forgetting)) if forgetting else 0.0}


def grad_conflict_placeholder_or_optional(rows: list[dict[str, Any]]) -> dict[str, Any]:
    conflicts = [row.get("grad_conflict") for row in rows if row.get("grad_conflict") is not None]
    if not conflicts:
        return {
            "available": False,
            "status": "unavailable",
            "missing_reason": "missing_grad_conflict",
            "required_fields": ["grad_conflict"],
            "sample_count": 0,
        }
    return {
        "available": True,
        "status": "available",
        "mean_grad_conflict": sum(float(item) for item in conflicts) / len(conflicts),
        "required_fields": ["grad_conflict"],
        "sample_count": len(conflicts),
    }
