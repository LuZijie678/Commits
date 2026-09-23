from __future__ import annotations

import torch

from code.mica.losses.hungarian_matching import solve_slot_matching


def test_hungarian_matching_prefers_low_cost_predicted_slots() -> None:
    cost_matrix = torch.tensor(
        [
            [0.2, 0.9, 0.3, 0.8],
            [0.7, 0.1, 0.6, 0.4],
        ],
        dtype=torch.float32,
    )

    result = solve_slot_matching(cost_matrix)

    assert result.matched_pairs == [(0, 0), (1, 1)]
    assert result.unmatched_predicted == [2, 3]
    assert result.unmatched_gold == []
    assert abs(result.total_cost - 0.3) < 1e-6
