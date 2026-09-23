from __future__ import annotations

from code.mica.eval.training_diagnostics import (
    active_slot_count_distribution,
    assignment_entropy_summary,
    grad_conflict_placeholder_or_optional,
    oracle_k_predicted_k_gap,
    p_count_pb_calibration_gap,
    slot_collapse_rate,
    strict_replay_forgetting,
)


def test_training_diagnostics_summarize_core_failure_modes() -> None:
    rows = [
        {
            "predicted_count": 2,
            "oracle_k": 2,
            "unit_to_slot": {"u1": "slot_1", "u2": "slot_1", "u3": "slot_1", "u4": "slot_2"},
            "assignment_scores": {
                "u1": {"slot_1": 0.9, "slot_2": 0.1},
                "u2": {"slot_1": 0.8, "slot_2": 0.2},
            },
            "count_probs": [0.1, 0.8, 0.1],
            "pb_count_probs": [0.2, 0.7, 0.1],
            "stage1_replay_metric": 0.9,
            "current_replay_metric": 0.7,
        },
        {
            "predicted_count": 1,
            "oracle_k": 2,
            "unit_to_slot": {"u5": "slot_1"},
            "assignment_scores": {"u5": {"slot_1": 1.0}},
            "count_probs": [0.8, 0.2],
            "pb_count_probs": [0.7, 0.3],
            "stage1_replay_metric": 0.8,
            "current_replay_metric": 0.75,
        },
    ]

    assert slot_collapse_rate(rows)["slot_collapse_rate"] > 0.0
    assert active_slot_count_distribution(rows)["active_slot_count_distribution"]["1"] >= 1
    assert assignment_entropy_summary(rows)["mean_assignment_entropy"] >= 0.0
    assert p_count_pb_calibration_gap(rows)["mean_abs_gap"] >= 0.0
    assert oracle_k_predicted_k_gap(rows)["mean_abs_gap"] > 0.0
    assert strict_replay_forgetting(rows)["mean_forgetting"] > 0.0


def test_grad_conflict_optional_diagnostic_reports_machine_readable_unavailable_state() -> None:
    unavailable = grad_conflict_placeholder_or_optional([])
    available = grad_conflict_placeholder_or_optional(
        [
            {"grad_conflict": 0.2},
            {"grad_conflict": 0.4},
        ]
    )

    assert unavailable == {
        "available": False,
        "status": "unavailable",
        "missing_reason": "missing_grad_conflict",
        "required_fields": ["grad_conflict"],
        "sample_count": 0,
    }
    assert available["available"] is True
    assert available["status"] == "available"
    assert available["sample_count"] == 2
    assert available["mean_grad_conflict"] == 0.30000000000000004
