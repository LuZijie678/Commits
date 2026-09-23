from __future__ import annotations

from collections import Counter
from math import comb, log
from itertools import combinations, permutations
from typing import Any


def pairwise_f1_from_assignments(gold_unit_to_intent: dict[str, str], pred_unit_to_slot: dict[str, str]) -> dict[str, Any]:
    unit_ids = sorted(set(gold_unit_to_intent) & set(pred_unit_to_slot))
    if len(unit_ids) < 2:
        return {
            "pairwise_f1": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "degraded": True,
            "diagnostics": ["insufficient_unit_pairs"],
        }

    tp = fp = fn = 0
    for left, right in combinations(unit_ids, 2):
        gold_same = gold_unit_to_intent[left] == gold_unit_to_intent[right]
        pred_same = pred_unit_to_slot[left] == pred_unit_to_slot[right]
        if pred_same and gold_same:
            tp += 1
        elif pred_same and not gold_same:
            fp += 1
        elif (not pred_same) and gold_same:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "pairwise_f1": f1,
        "precision": precision,
        "recall": recall,
        "degraded": False,
        "diagnostics": [],
    }


def build_primary_alignment_maps(row: dict[str, Any]) -> dict[str, Any]:
    """Build primary foreground-only alignment maps for real alignment metrics."""
    excluded = _excluded_alignment_units(row)
    gold = {
        str(unit_id): str(intent_id)
        for unit_id, intent_id in dict(row.get("gold_unit_to_intent", {})).items()
        if str(unit_id) not in excluded
    }
    pred = {
        str(unit_id): str(slot_id)
        for unit_id, slot_id in dict(row.get("pred_unit_to_slot", {})).items()
        if str(unit_id) in gold
    }
    oracle = {
        str(unit_id): str(slot_id)
        for unit_id, slot_id in dict(row.get("oracle_unit_to_slot", {})).items()
        if str(unit_id) in gold
    }
    gold_hunks = {
        str(hunk_id): str(intent_id)
        for hunk_id, intent_id in dict(row.get("gold_hunk_to_intent", {})).items()
        if str(hunk_id) not in excluded
    }
    pred_hunks = {
        str(hunk_id): str(slot_id)
        for hunk_id, slot_id in dict(row.get("pred_hunk_to_slot", {})).items()
        if str(hunk_id) in gold_hunks
    }
    oracle_hunks = {
        str(hunk_id): str(slot_id)
        for hunk_id, slot_id in dict(row.get("oracle_hunk_to_slot", {})).items()
        if str(hunk_id) in gold_hunks
    }
    return {
        "gold_unit_to_intent": gold,
        "pred_unit_to_slot": pred,
        "oracle_unit_to_slot": oracle,
        "gold_hunk_to_intent": gold_hunks,
        "pred_hunk_to_slot": pred_hunks,
        "oracle_hunk_to_slot": oracle_hunks,
        "excluded_alignment_unit_ids": sorted(excluded),
        "excluded_alignment_unit_count": len(excluded),
        "alignment_mask_protocol": "foreground_only_excludes_uncertain_shared_support_mixed",
    }


def unit_accuracy_hungarian(gold_unit_to_intent: dict[str, str], pred_unit_to_slot: dict[str, str]) -> dict[str, Any]:
    unit_ids = sorted(set(gold_unit_to_intent) & set(pred_unit_to_slot))
    if not unit_ids:
        return {"unit_accuracy": 0.0, "degraded": True, "diagnostics": ["empty_input"]}

    gold_labels = sorted(set(gold_unit_to_intent[unit] for unit in unit_ids))
    pred_labels = sorted(set(pred_unit_to_slot[unit] for unit in unit_ids))
    overlap: dict[tuple[str, str], int] = Counter(
        (pred_unit_to_slot[unit], gold_unit_to_intent[unit])
        for unit in unit_ids
    )

    diagnostics: list[str] = []
    if max(len(gold_labels), len(pred_labels)) <= 6:
        best = 0
        if len(pred_labels) <= len(gold_labels):
            for perm in permutations(gold_labels, len(pred_labels)):
                matched = sum(overlap.get((pred_label, gold_label), 0) for pred_label, gold_label in zip(pred_labels, perm))
                best = max(best, matched)
        else:
            for perm in permutations(pred_labels, len(gold_labels)):
                matched = sum(overlap.get((pred_label, gold_label), 0) for pred_label, gold_label in zip(perm, gold_labels))
                best = max(best, matched)
    else:
        diagnostics.append("greedy_matching_used")
        remaining_gold = set(gold_labels)
        best = 0
        for pred_label in pred_labels:
            best_gold = None
            best_overlap = -1
            for gold_label in remaining_gold:
                current = overlap.get((pred_label, gold_label), 0)
                if current > best_overlap:
                    best_overlap = current
                    best_gold = gold_label
            if best_gold is not None:
                remaining_gold.discard(best_gold)
                best += max(best_overlap, 0)

    return {
        "unit_accuracy": best / len(unit_ids),
        "degraded": False,
        "diagnostics": diagnostics,
    }


def count_metrics(gold_counts: list[int], pred_counts: list[int]) -> dict[str, Any]:
    if not gold_counts or not pred_counts:
        return {"count_accuracy": 0.0, "count_mae": 0.0, "degraded": True, "diagnostics": ["empty_input"]}
    pairs = list(zip(gold_counts, pred_counts))
    accuracy = sum(1 for gold, pred in pairs if gold == pred) / len(pairs)
    mae = sum(abs(gold - pred) for gold, pred in pairs) / len(pairs)
    return {"count_accuracy": accuracy, "count_mae": mae, "degraded": False, "diagnostics": []}


def slot_collapse_metrics(pred_unit_to_slot_rows: list[dict[str, Any]], *, collapse_ratio_threshold: float = 0.90) -> dict[str, Any]:
    collapse_count = 0
    evaluated = 0
    for row in pred_unit_to_slot_rows:
        predicted_count = int(row.get("predicted_count", 0) or 0)
        unit_to_slot = dict(row.get("unit_to_slot", {}))
        if predicted_count < 2 or not unit_to_slot:
            continue
        slot_sizes = Counter(unit_to_slot.values())
        if not slot_sizes:
            continue
        evaluated += 1
        if max(slot_sizes.values()) / len(unit_to_slot) >= collapse_ratio_threshold:
            collapse_count += 1
    rate = collapse_count / evaluated if evaluated else 0.0
    return {"slot_collapse_count": collapse_count, "slot_collapse_rate": rate, "evaluated_sample_count": evaluated}


def over_under_split_metrics(gold_counts: list[int], pred_counts: list[int]) -> dict[str, Any]:
    pairs = list(zip(gold_counts, pred_counts))
    gold_k1 = [pair for pair in pairs if pair[0] == 1]
    gold_k2 = [pair for pair in pairs if pair[0] == 2]
    over_split_rate = sum(1 for gold, pred in gold_k1 if pred > gold) / len(gold_k1) if gold_k1 else 0.0
    under_split_rate = sum(1 for gold, pred in gold_k2 if pred < gold) / len(gold_k2) if gold_k2 else 0.0
    return {
        "over_split_rate_on_k1": over_split_rate,
        "under_split_rate_on_k2": under_split_rate,
        "gold_k1_count": len(gold_k1),
        "gold_k2_count": len(gold_k2),
    }


def diagnostic_histogram(rows: list[dict[str, Any]]) -> dict[str, int]:
    histogram: Counter[str] = Counter()
    for row in rows:
        for diagnostic in row.get("diagnostics", []):
            code = diagnostic.get("code") if isinstance(diagnostic, dict) else str(diagnostic)
            histogram[str(code)] += 1
    return dict(histogram)


def adjusted_rand_index(gold_labels: list[str], pred_labels: list[str]) -> dict[str, Any]:
    if len(gold_labels) != len(pred_labels) or len(gold_labels) < 2:
        return {"ari": 0.0, "degraded": True, "diagnostics": ["insufficient_items"]}
    contingency = _contingency(gold_labels, pred_labels)
    sum_nij = sum(_comb2(count) for count in contingency.values())
    gold_counts = Counter(gold_labels)
    pred_counts = Counter(pred_labels)
    sum_ai = sum(_comb2(count) for count in gold_counts.values())
    sum_bj = sum(_comb2(count) for count in pred_counts.values())
    total_pairs = _comb2(len(gold_labels))
    if total_pairs == 0:
        return {"ari": 0.0, "degraded": True, "diagnostics": ["insufficient_items"]}
    expected = (sum_ai * sum_bj) / total_pairs if total_pairs else 0.0
    max_index = 0.5 * (sum_ai + sum_bj)
    denominator = max_index - expected
    if denominator == 0:
        return {"ari": 1.0 if gold_labels == pred_labels else 0.0, "degraded": False, "diagnostics": []}
    return {"ari": (sum_nij - expected) / denominator, "degraded": False, "diagnostics": []}


def normalized_mutual_info(gold_labels: list[str], pred_labels: list[str]) -> dict[str, Any]:
    if len(gold_labels) != len(pred_labels) or not gold_labels:
        return {"nmi": 0.0, "degraded": True, "diagnostics": ["empty_input"]}
    total = len(gold_labels)
    contingency = _contingency(gold_labels, pred_labels)
    gold_counts = Counter(gold_labels)
    pred_counts = Counter(pred_labels)
    mutual_info = 0.0
    for (gold_label, pred_label), count in contingency.items():
        if count == 0:
            continue
        mutual_info += (count / total) * log((count * total) / (gold_counts[gold_label] * pred_counts[pred_label]), 2)
    h_gold = _entropy(gold_counts, total)
    h_pred = _entropy(pred_counts, total)
    denominator = (h_gold + h_pred) / 2.0
    if denominator == 0:
        return {"nmi": 1.0 if gold_labels == pred_labels else 0.0, "degraded": False, "diagnostics": []}
    return {"nmi": mutual_info / denominator, "degraded": False, "diagnostics": []}


def bcubed_f1(gold_labels: list[str], pred_labels: list[str]) -> dict[str, Any]:
    if len(gold_labels) != len(pred_labels) or not gold_labels:
        return {"bcubed_f1": 0.0, "precision": 0.0, "recall": 0.0, "degraded": True, "diagnostics": ["empty_input"]}
    precisions: list[float] = []
    recalls: list[float] = []
    for index, (gold_label, pred_label) in enumerate(zip(gold_labels, pred_labels)):
        same_pred = {pos for pos, label in enumerate(pred_labels) if label == pred_label}
        same_gold = {pos for pos, label in enumerate(gold_labels) if label == gold_label}
        overlap = len(same_pred & same_gold)
        precisions.append(overlap / len(same_pred))
        recalls.append(overlap / len(same_gold))
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"bcubed_f1": f1, "precision": precision, "recall": recall, "degraded": False, "diagnostics": []}


def hunk_micro_f1(gold_hunk_to_intent: dict[str, str], pred_hunk_to_slot: dict[str, str]) -> dict[str, Any]:
    result = unit_accuracy_hungarian(gold_hunk_to_intent, pred_hunk_to_slot)
    if result.get("degraded"):
        return {"hunk_micro_f1": 0.0, "degraded": True, "diagnostics": result.get("diagnostics", [])}
    score = float(result["unit_accuracy"])
    return {"hunk_micro_f1": score, "precision": score, "recall": score, "degraded": False, "diagnostics": result.get("diagnostics", [])}


def aggregate_attribution_metrics(sample_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("pairwise_f1", "ari", "nmi", "bcubed_f1", "unit_accuracy", "hunk_micro_f1")
    payload: dict[str, Any] = {
        "sample_count": len(sample_metrics),
        "diagnostic_histogram": diagnostic_histogram(sample_metrics),
    }
    for key in keys:
        values = [float(row[key]) for row in sample_metrics if key in row]
        payload[f"mean_{key}"] = (sum(values) / len(values)) if values else 0.0
        payload[f"{key}_count"] = len(values)
    return payload


def _excluded_alignment_units(row: dict[str, Any]) -> set[str]:
    excluded = {str(item) for item in row.get("uncertain_units", [])}
    excluded.update(str(item) for item in row.get("shared_support_units", []))
    excluded.update(str(item) for item in row.get("mixed_units", []))
    return excluded


def _comb2(value: int) -> int:
    return comb(value, 2) if value >= 2 else 0


def _contingency(gold_labels: list[str], pred_labels: list[str]) -> Counter[tuple[str, str]]:
    return Counter(zip(gold_labels, pred_labels))


def _entropy(counts: Counter[str], total: int) -> float:
    entropy = 0.0
    for count in counts.values():
        probability = count / total
        if probability > 0:
            entropy -= probability * log(probability, 2)
    return entropy
