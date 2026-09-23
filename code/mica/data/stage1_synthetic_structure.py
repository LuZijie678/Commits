from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from code.mica.data.schema import MicaSample


def pairwise_f1(pred_labels: list[int], gold_labels: list[int]) -> float:
    pair_count = 0
    tp = 0
    fp = 0
    fn = 0
    for left_index in range(len(gold_labels)):
        for right_index in range(left_index + 1, len(gold_labels)):
            pair_count += 1
            pred_same = pred_labels[left_index] == pred_labels[right_index]
            gold_same = gold_labels[left_index] == gold_labels[right_index]
            if pred_same and gold_same:
                tp += 1
            elif pred_same and not gold_same:
                fp += 1
            elif not pred_same and gold_same:
                fn += 1
    if pair_count == 0:
        return 1.0
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    denom = 2 * tp + fp + fn
    return 0.0 if denom == 0 else float((2 * tp) / denom)


def all_one_cluster_labels(active_unit_count: int) -> list[int]:
    return [0 for _ in range(active_unit_count)]


def file_path_cluster_labels(sample: MicaSample) -> list[int]:
    label_by_path: dict[str, int] = {}
    labels: list[int] = []
    for unit in sample.edit_units:
        if unit.file_path not in label_by_path:
            label_by_path[unit.file_path] = len(label_by_path)
        labels.append(label_by_path[unit.file_path])
    return labels


def random_gold_k_labels(*, active_unit_count: int, gold_count: int, seed: int) -> list[int]:
    if active_unit_count <= 0:
        return []
    requested_k = max(1, min(gold_count, active_unit_count))
    labels = [index % requested_k for index in range(active_unit_count)]
    state = seed & 0xFFFFFFFF
    order = list(range(active_unit_count))
    for index in range(active_unit_count - 1, 0, -1):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        swap_index = state % (index + 1)
        order[index], order[swap_index] = order[swap_index], order[index]
    shuffled = [0 for _ in range(active_unit_count)]
    for source_index, target_index in enumerate(order):
        shuffled[target_index] = labels[source_index]
    return shuffled


def gold_labels_from_sample(sample: MicaSample) -> list[int]:
    return [int(unit.gold_intent_id or 0) for unit in sample.edit_units]


def stable_sample_seed(sample_id: str, *, offset: int = 0) -> int:
    digest = hashlib.sha1(f"{sample_id}:{offset}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def synthetic_k2_structure_features(
    sample: MicaSample,
    *,
    random_trials: int = 16,
    path_dominated_threshold: float = 0.90,
    nondegenerate_file_path_ceiling: float = 0.85,
    nondegenerate_random_ceiling: float = 0.75,
) -> dict[str, Any]:
    if sample.gold_count != 2:
        raise ValueError(f"synthetic_k2_structure_features expects gold_count=2, got {sample.gold_count}")

    gold_labels = gold_labels_from_sample(sample)
    intent_counts = Counter(gold_labels)
    count_0 = int(intent_counts.get(0, 0))
    count_1 = int(intent_counts.get(1, 0))
    total_units = len(sample.edit_units)
    file_paths = [unit.file_path for unit in sample.edit_units]
    directories = {str(PurePosixPath(path).parent) for path in file_paths}
    file_roles = {unit.file_role for unit in sample.edit_units}
    file_path_labels = file_path_cluster_labels(sample)
    all_one_f1 = pairwise_f1(all_one_cluster_labels(total_units), gold_labels)
    file_path_f1 = pairwise_f1(file_path_labels, gold_labels)
    random_scores = [
        pairwise_f1(
            random_gold_k_labels(
                active_unit_count=total_units,
                gold_count=sample.gold_count,
                seed=stable_sample_seed(sample.sample_id, offset=trial),
            ),
            gold_labels,
        )
        for trial in range(random_trials)
    ]
    random_mean = float(sum(random_scores) / max(len(random_scores), 1))
    min_intent_units = min(count_0, count_1)
    max_intent_units = max(count_0, count_1)
    gold_intents_nonempty = count_0 > 0 and count_1 > 0
    singleton_dominated = min_intent_units <= 1
    return {
        "sample_id": sample.sample_id,
        "repo": sample.repo,
        "gold_count": sample.gold_count,
        "edit_unit_count": total_units,
        "hunk_count": total_units,
        "file_count": len(set(file_paths)),
        "directory_count": len(directories),
        "intent_unit_counts": [count_0, count_1],
        "min_intent_units": min_intent_units,
        "max_intent_units": max_intent_units,
        "same_file": len(set(file_paths)) == 1,
        "cross_file": len(set(file_paths)) >= 2,
        "same_directory": len(directories) == 1,
        "different_file_role": len(file_roles) >= 2,
        "all_one_baseline_pairwise_f1": all_one_f1,
        "file_path_baseline_pairwise_f1": file_path_f1,
        "random_gold_k_pairwise_f1": random_mean,
        "random_gold_k_trials": random_scores,
        "singleton_dominated": singleton_dominated,
        "both_intents_singleton": count_0 == 1 and count_1 == 1,
        "path_dominated": file_path_f1 >= path_dominated_threshold and not singleton_dominated,
        "gold_intents_nonempty": gold_intents_nonempty,
        "nondegenerate_candidate": (
            gold_intents_nonempty
            and total_units >= 4
            and min_intent_units >= 2
            and file_path_f1 <= nondegenerate_file_path_ceiling
            and random_mean <= nondegenerate_random_ceiling
        ),
    }


def counter_to_sorted_dict(counter: Counter[Any]) -> dict[str, int]:
    def _sort_key(item: Any) -> tuple[int, Any]:
        if isinstance(item, str):
            try:
                return (0, float(item))
            except ValueError:
                return (1, item)
        return (0, item)

    return {str(key): int(counter[key]) for key in sorted(counter.keys(), key=_sort_key)}


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def round_distribution(values: list[float], *, digits: int = 4) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in values:
        counter[f"{value:.{digits}f}"] += 1
    return counter_to_sorted_dict(counter)


def sample_summary_row(sample: MicaSample, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "sample_id": sample.sample_id,
        "split": sample.split,
        "k": sample.gold_count,
        "source_kind": sample.source_kind,
        "repo": sample.repo,
        "edit_unit_count": len(sample.edit_units),
    }
    if extra:
        payload.update(extra)
    return payload


def jsonl_dump(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
