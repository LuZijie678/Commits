from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import torch


@dataclass(slots=True)
class MatchingResult:
    matched_pairs: list[tuple[int, int]]
    unmatched_predicted: list[int]
    unmatched_gold: list[int]
    total_cost: float


def solve_slot_matching(cost_matrix: torch.Tensor) -> MatchingResult:
    if cost_matrix.dim() != 2:
        raise ValueError("solve_slot_matching expects a 2D cost matrix")
    gold_count, predicted_count = cost_matrix.shape
    if gold_count == 0:
        return MatchingResult([], list(range(predicted_count)), [], 0.0)
    if predicted_count < gold_count:
        raise ValueError("predicted slots must be >= gold slots for matching")

    predicted_indices = list(range(predicted_count))
    best_pairs: list[tuple[int, int]] | None = None
    best_cost = float("inf")
    for candidate in permutations(predicted_indices, gold_count):
        total_cost = 0.0
        pairs = []
        for gold_index, predicted_index in enumerate(candidate):
            total_cost += float(cost_matrix[gold_index, predicted_index].item())
            pairs.append((gold_index, predicted_index))
        if total_cost < best_cost:
            best_cost = total_cost
            best_pairs = pairs

    assert best_pairs is not None
    used_predicted = {predicted_index for _, predicted_index in best_pairs}
    return MatchingResult(
        matched_pairs=best_pairs,
        unmatched_predicted=[index for index in predicted_indices if index not in used_predicted],
        unmatched_gold=[],
        total_cost=best_cost,
    )
