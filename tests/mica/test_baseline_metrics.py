from __future__ import annotations

from code.mica.eval.baseline_metrics import (
    all_one_baseline,
    file_path_baseline,
    random_gold_k_baseline,
    size_heuristic_count_baseline,
)


def _edit_units() -> list[dict]:
    return [
        {"unit_id": "u1", "file_path": "src/auth/a.py"},
        {"unit_id": "u2", "file_path": "src/auth/b.py"},
        {"unit_id": "u3", "file_path": "docs/api.md"},
    ]


def test_all_one_baseline_outputs_single_slot() -> None:
    result = all_one_baseline(_edit_units())
    assert result["predicted_count"] == 1
    assert set(result["unit_to_slot"].values()) == {"slot_1"}
    assert result["metadata"]["baseline"] == "all_one"


def test_file_path_baseline_groups_by_path_family() -> None:
    result = file_path_baseline(_edit_units())
    assert result["predicted_count"] >= 2
    assert result["unit_to_slot"]["u1"] == result["unit_to_slot"]["u2"]
    assert result["unit_to_slot"]["u3"] != result["unit_to_slot"]["u1"]


def test_random_gold_k_baseline_is_deterministic_with_seed() -> None:
    first = random_gold_k_baseline(_edit_units(), gold_k=2, seed=42)
    second = random_gold_k_baseline(_edit_units(), gold_k=2, seed=42)
    assert first["unit_to_slot"] == second["unit_to_slot"]
    assert first["predicted_count"] == 2


def test_size_heuristic_baseline_is_diagnostic_only() -> None:
    result = size_heuristic_count_baseline(_edit_units(), thresholds=None)
    assert result["metadata"]["baseline"] == "size_heuristic_count"
    assert result["metadata"]["thresholds_are_not_final"] is True
