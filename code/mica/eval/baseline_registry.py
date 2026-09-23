from __future__ import annotations

from typing import Any


_BASELINE_REGISTRY: dict[str, dict[str, Any]] = {
    "all_one": {
        "implemented": True,
        "status": "diagnostic",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "file_path": {
        "implemented": True,
        "status": "diagnostic",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "random_gold_k": {
        "implemented": True,
        "status": "diagnostic",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "size_heuristic_count": {
        "implemented": True,
        "status": "diagnostic",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "flat_classifier": {
        "implemented": True,
        "status": "trainable_lightweight",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "no_slot_decoder": {
        "implemented": True,
        "status": "graph_clustering",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "metadata_tfidf_classifier": {
        "implemented": True,
        "status": "lightweight_text_metadata_classifier",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "graph_clustering": {
        "implemented": True,
        "status": "evidence_graph_clustering",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "oracle_k_clustering": {
        "implemented": True,
        "status": "oracle_k_diagnostic",
        "requires_training_or_api": False,
        "benchmark_domain": "attribution",
        "output_kind": "attribution_prediction",
        "execution_mode": "local",
    },
    "direct_generation": {
        "implemented": True,
        "status": "weak_deterministic",
        "requires_training_or_api": False,
        "benchmark_domain": "message_utility",
        "output_kind": "commit_message",
        "execution_mode": "local",
    },
    "llm_prompting": {
        "implemented": True,
        "status": "external_reference",
        "requires_training_or_api": True,
        "benchmark_domain": "message_utility",
        "output_kind": "commit_message",
        "execution_mode": "external_api",
    },
    "pretrained_generation": {
        "implemented": True,
        "status": "external_reference",
        "requires_training_or_api": True,
        "benchmark_domain": "message_utility",
        "output_kind": "commit_message",
        "execution_mode": "external_api",
    },
    "pretrained_classifier": {
        "implemented": True,
        "status": "deprecated_alias_for_pretrained_generation",
        "requires_training_or_api": True,
        "benchmark_domain": "message_utility",
        "output_kind": "commit_message",
        "execution_mode": "external_api",
        "alias_for": "pretrained_generation",
    },
}


def list_baselines() -> list[dict[str, Any]]:
    return [{"name": name, **payload} for name, payload in _BASELINE_REGISTRY.items()]


def get_baseline_status(name: str) -> dict[str, Any]:
    if name not in _BASELINE_REGISTRY:
        raise KeyError(f"Unknown baseline: {name}")
    return {"name": name, **_BASELINE_REGISTRY[name]}


def assert_baseline_implemented_before_run(name: str) -> None:
    baseline = get_baseline_status(name)
    if not baseline["implemented"]:
        raise ValueError(f"Baseline `{name}` is not implemented and cannot be run in this stage.")
