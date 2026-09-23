from __future__ import annotations

from typing import Any


_METRIC_REGISTRY: dict[str, dict[str, Any]] = {
    "real_domain_main": {
        "metrics": {
            "auroc": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "auprc": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "balanced_accuracy": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "hard_b_fpr": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "m_recall": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "ece": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
        },
        "aliases": {},
    },
    "real_domain_split": {
        "metrics": {
            "auroc": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "auprc": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "balanced_accuracy": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "ece": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "hard_b_fpr": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
        },
        "aliases": {},
    },
    "real_domain_selective": {
        "metrics": {
            "coverage": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "risk_at_coverage": {"higher_is_better": False, "is_primary_metric": True, "is_proxy_metric": False},
            "aurc": {"higher_is_better": False, "is_primary_metric": True, "is_proxy_metric": False},
            "abstention_precision": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "false_abstention_on_in_scope": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "missed_overflow_rate": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "forced_decomposition_error": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "implicit_risk_threshold_used": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
        },
        "aliases": {
            "AURC": "aurc",
            "false_abstention": "false_abstention_on_in_scope",
        },
    },
    "alignment_main": {
        "metrics": {
            "count_exact": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "count_mae": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "pairwise_f1": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "ari": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "nmi": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "bcubed_f1": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "hunk_micro_f1": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False},
            "over_segmentation_rate": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "under_segmentation_rate": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
        },
        "aliases": {},
    },
    "message_utility_main": {
        "metrics": {
            "intent_coverage": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": True},
            "missing_intent_rate": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": True},
            "extra_intent_rate": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": True},
            "hallucination_proxy": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": True},
            "faithfulness_proxy": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": True},
            "specificity_proxy": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": True},
            "human_usefulness": {"higher_is_better": True, "is_primary_metric": False, "is_proxy_metric": False, "requires_human_eval": True},
        },
        "aliases": {
            "covered_intent_fraction": "intent_coverage",
            "specificity": "specificity_proxy",
            "specificity_proxy_mean": "specificity_proxy",
        },
    },
    "shortcut_ood_main": {
        "metrics": {
            "original_metric": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "masked_metric": {"higher_is_better": True, "is_primary_metric": True, "is_proxy_metric": False},
            "delta": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
            "sensitivity": {"higher_is_better": False, "is_primary_metric": False, "is_proxy_metric": False},
        },
        "aliases": {},
    },
}


def list_metric_definitions() -> dict[str, dict[str, Any]]:
    return _METRIC_REGISTRY


def normalize_metric_key(key: str) -> str:
    normalized = str(key)
    for payload in _METRIC_REGISTRY.values():
        aliases = payload.get("aliases", {})
        if normalized in aliases:
            return str(aliases[normalized])
    return normalized


def validate_eval_metrics_against_paper_tables(eval_payload: dict[str, Any], table_name: str) -> dict[str, Any]:
    if table_name not in _METRIC_REGISTRY:
        return {"valid": False, "errors": [f"unknown_table_{table_name}"], "normalized_metrics": {}}
    definition = _METRIC_REGISTRY[table_name]
    allowed = definition["metrics"]
    normalized_metrics: dict[str, Any] = {}
    errors: list[str] = []
    for key, value in eval_payload.items():
        if key == "proxy_not_human_eval":
            continue
        normalized_key = normalize_metric_key(key)
        if normalized_key in allowed:
            normalized_metrics[normalized_key] = value
        elif isinstance(value, (int, float)):
            errors.append(f"unknown_metric_{key}")
    if any(spec.get("is_proxy_metric", False) for spec in allowed.values()) and eval_payload.get("proxy_not_human_eval") is not True:
        errors.append("missing_proxy_not_human_eval")
    return {"valid": len(errors) == 0, "errors": errors, "normalized_metrics": normalized_metrics}
