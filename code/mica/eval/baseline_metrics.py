from __future__ import annotations

import random
from pathlib import Path
from typing import Any


def all_one_baseline(edit_units: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "predicted_count": 1,
        "unit_to_slot": {str(unit["unit_id"]): "slot_1" for unit in edit_units},
        "metadata": {"baseline": "all_one"},
    }


def file_path_baseline(edit_units: list[dict[str, Any]]) -> dict[str, Any]:
    unit_to_slot: dict[str, str] = {}
    slot_by_group: dict[str, str] = {}
    for unit in edit_units:
        group = _path_group(str(unit.get("file_path", "")))
        slot_by_group.setdefault(group, f"slot_{len(slot_by_group) + 1}")
        unit_to_slot[str(unit["unit_id"])] = slot_by_group[group]
    return {
        "predicted_count": len(set(unit_to_slot.values())),
        "unit_to_slot": unit_to_slot,
        "metadata": {"baseline": "file_path"},
    }


def random_gold_k_baseline(edit_units: list[dict[str, Any]], gold_k: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    unit_ids = [str(unit["unit_id"]) for unit in edit_units]
    shuffled = list(unit_ids)
    rng.shuffle(shuffled)
    unit_to_slot: dict[str, str] = {}
    for index, unit_id in enumerate(shuffled):
        slot_index = (index % max(gold_k, 1)) + 1
        unit_to_slot[unit_id] = f"slot_{slot_index}"
    return {
        "predicted_count": max(gold_k, 1),
        "unit_to_slot": unit_to_slot,
        "metadata": {"baseline": "random_gold_k", "seed": seed},
    }


def size_heuristic_count_baseline(edit_units: list[dict[str, Any]], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_thresholds = dict(thresholds or {"unit_count_multi_threshold": 6})
    threshold = int(runtime_thresholds.get("unit_count_multi_threshold", 6))
    predicted_count = 2 if len(edit_units) >= threshold else 1
    return {
        "predicted_count": predicted_count,
        "unit_to_slot": {str(unit["unit_id"]): "slot_1" for unit in edit_units},
        "metadata": {
            "baseline": "size_heuristic_count",
            "thresholds": runtime_thresholds,
            "thresholds_are_not_final": True,
        },
    }


def build_baseline_run_status(
    *,
    baseline_name: str,
    benchmark_domain: str,
    requires_training_or_api: bool,
) -> dict[str, Any]:
    return {
        "implemented": True,
        "executed": False,
        "status": "not_run_in_this_stage",
        "benchmark_domain": benchmark_domain,
        "requires_training_or_api": requires_training_or_api,
    }


def flat_classifier_baseline_placeholder() -> dict[str, Any]:
    return build_baseline_run_status(
        baseline_name="flat_classifier",
        benchmark_domain="attribution",
        requires_training_or_api=True,
    )


def no_slot_decoder_baseline_placeholder() -> dict[str, Any]:
    return build_baseline_run_status(
        baseline_name="no_slot_decoder",
        benchmark_domain="attribution",
        requires_training_or_api=True,
    )


def direct_generation_baseline_placeholder() -> dict[str, Any]:
    return build_baseline_run_status(
        baseline_name="direct_generation",
        benchmark_domain="message_utility",
        requires_training_or_api=True,
    )


def llm_prompting_baseline_placeholder() -> dict[str, Any]:
    return build_baseline_run_status(
        baseline_name="llm_prompting",
        benchmark_domain="message_utility",
        requires_training_or_api=True,
    )


def _path_group(file_path: str) -> str:
    path = Path(file_path)
    parent = path.parent.as_posix()
    return parent if parent not in {"", "."} else path.as_posix()
