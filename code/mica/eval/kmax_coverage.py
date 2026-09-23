from __future__ import annotations

from collections import defaultdict
import random
from typing import Any


COUNT_FIELDS = ("gold_count", "intent_count", "gold_k", "intent_k", "k")
SPLIT_ORDER = ("train", "dev", "test")
EXACT_COUNT_STATUS_VALUES = {"exact_gold", "manual_exact_gold", "verified_exact_gold"}


def build_kmax_coverage_report(
    rows: list[dict[str, Any]],
    *,
    kmax: int,
    tau: float | None = None,
    selected_kmax: int | None = None,
) -> dict[str, Any]:
    if kmax < 1:
        raise ValueError("kmax must be positive.")
    by_split: dict[str, list[int]] = defaultdict(list)
    eligible_rows_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_count_rows = 0
    synthetic_rows = 0
    excluded_rows_by_reason: dict[str, int] = defaultdict(int)
    for row in rows:
        if _is_synthetic(row):
            synthetic_rows += 1
        count = _extract_count(row)
        eligible, exclusion_reason = _is_kmax_freeze_eligible_row(row, count)
        if not eligible:
            missing_count_rows += 1
            excluded_rows_by_reason[exclusion_reason] += 1
            continue
        split = _normalize_split(row.get("split", "unspecified"))
        by_split[split].append(count)
        eligible_rows_by_split[split].append(dict(row, exact_k=count))

    split_reports = {split: _coverage_for_counts(counts, kmax=kmax) for split, counts in _ordered_splits(by_split)}
    train_dev_counts = [count for split in ("train", "dev") for count in by_split.get(split, [])]
    train_dev_rows = [row for split in ("train", "dev") for row in eligible_rows_by_split.get(split, [])]
    train_dev_report = _coverage_for_counts(train_dev_counts, kmax=kmax)
    stats_populated = bool(train_dev_counts)
    exact_multi_intent_train_dev_rows = sum(1 for count in train_dev_counts if count > 1)
    coverage_computed = bool(train_dev_counts) and exact_multi_intent_train_dev_rows > 0
    kmax_freeze_supported = False
    if tau is not None and coverage_computed and train_dev_report["coverage_at_kmax"] is not None:
        kmax_freeze_supported = bool(train_dev_report["coverage_at_kmax"] >= tau)
    selected_value = int(selected_kmax if selected_kmax is not None else kmax)
    if not stats_populated:
        status = "protocol_defined_but_stats_not_populated"
    elif exact_multi_intent_train_dev_rows == 0:
        status = "protocol_defined_but_real_multi_intent_counts_not_populated"
    else:
        status = "protocol_defined"
    max_observed_k = max(train_dev_counts, default=kmax)
    return {
        "status": status,
        "paper_readiness": (
            "ready_for_kmax_freeze_if_tau_satisfied"
            if coverage_computed and tau is None
            else (
                "ready_for_kmax_freeze_if_tau_satisfied"
                if kmax_freeze_supported
                else "not_final_paper_ready_until_exact_real_train_dev_multi_intent_coverage_stats_are_populated_and_frozen"
            )
        ),
        "kmax": int(kmax),
        "tau": tau,
        "selected_Kmax": {
            "value": selected_value,
            "status": "frozen_before_final_evaluation" if kmax_freeze_supported else "implementation_default_not_final_boundary",
        },
        "train_dev_selection_basis": {
            **train_dev_report,
            "selection_allowed": True,
            "final_test_used_for_selection": False,
            "exact_real_multi_intent_row_count": exact_multi_intent_train_dev_rows,
            "coverage_computed": coverage_computed,
            "tau_predeclared": tau is not None,
            "freeze_supported": kmax_freeze_supported,
        },
        "train_dev_count_distribution": _count_distribution(train_dev_counts, bucket_cap=max(kmax, 4)),
        "coverage_curve_train_dev": [
            {
                "candidate_kmax": candidate_k,
                **_coverage_for_counts(train_dev_counts, kmax=candidate_k),
            }
            for candidate_k in range(1, max(max_observed_k, kmax) + 1)
        ],
        "repository_level_distribution": _repository_level_distribution(train_dev_rows, bucket_cap=max(kmax, 4)),
        "repository_cluster_bootstrap_ci": _repository_cluster_bootstrap_ci(train_dev_rows, kmax=kmax),
        "train_dev_leakage_report": _train_dev_leakage_report(train_dev_rows),
        "attestations": {
            "train_dev_only_selection": True,
            "final_test_not_used": True,
            "synthetic_excluded_from_selection": True,
            "censored_counts_excluded_from_selection": True,
            "exact_real_only_selection": True,
        },
        "coverage_at_Kmax": split_reports,
        "missing_count_rows": missing_count_rows,
        "selection_basis_constraints": {
            "train_dev_only": True,
            "synthetic_allowed_for_selection": False,
            "censored_counts_allowed_for_selection": False,
            "exact_real_multi_intent_required": True,
        },
        "eligibility_summary": {
            "total_rows_received": len(rows),
            "eligible_exact_real_rows": sum(len(counts) for counts in by_split.values()),
            "eligible_train_dev_rows": len(train_dev_counts),
            "eligible_train_dev_multi_intent_rows": exact_multi_intent_train_dev_rows,
            "excluded_rows_by_reason": dict(sorted(excluded_rows_by_reason.items())),
        },
        "synthetic_distribution_usage": {
            "synthetic_rows": synthetic_rows,
            "reported_separately": True,
            "can_alone_justify_Kmax": False,
        },
        "overflow_policy": {
            "k_gt_Kmax_truncated": False,
            "k_gt_Kmax_evaluated_as": "overflow_or_out_of_scope",
            "overflow_rate_reported_on_every_split": True,
        },
        "forbidden": {
            "final_test_attribution_scores_for_kmax_selection": True,
            "message_utility_scores_for_kmax_selection": True,
            "synthetic_cardinality_distribution_alone": True,
        },
    }


def _coverage_for_counts(counts: list[int], *, kmax: int) -> dict[str, Any]:
    total = len(counts)
    covered = sum(1 for count in counts if count <= kmax)
    overflow = sum(1 for count in counts if count > kmax)
    return {
        "sample_count": total,
        "covered_count": covered,
        "overflow_count": overflow,
        "coverage_at_kmax": (covered / total) if total else None,
        "overflow_rate": (overflow / total) if total else None,
        "values_status": "values_populated" if total else "values_to_be_populated_by_metric_script",
    }


def _extract_count(row: dict[str, Any]) -> int | None:
    for field in COUNT_FIELDS:
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        return count if count >= 0 else None
    return None


def _normalize_split(value: Any) -> str:
    split = str(value or "unspecified").strip().lower().replace("-", "_")
    aliases = {
        "validation": "dev",
        "val": "dev",
        "development": "dev",
        "final_test": "test",
        "m_final_test": "test",
    }
    return aliases.get(split, split or "unspecified")


def _ordered_splits(by_split: dict[str, list[int]]) -> list[tuple[str, list[int]]]:
    ordered = [(split, by_split[split]) for split in SPLIT_ORDER if split in by_split]
    ordered.extend((split, by_split[split]) for split in sorted(by_split) if split not in SPLIT_ORDER)
    return ordered


def _is_synthetic(row: dict[str, Any]) -> bool:
    source = str(row.get("source_kind", row.get("dataset_kind", row.get("asset_kind", "")))).lower()
    construction = str(row.get("construction_type", "")).lower()
    return "synthetic" in source or "synthetic" in construction or bool(row.get("synthetic"))


def _is_kmax_freeze_eligible_row(row: dict[str, Any], count: int | None) -> tuple[bool, str]:
    if _is_synthetic(row):
        return False, "synthetic_excluded"
    label_type = str(row.get("cardinality_label_type") or "").strip().lower()
    if "censored" in label_type:
        return False, "censored_count_excluded"
    if count is None:
        return False, "missing_exact_count"
    if _is_exact_real_count_row(row):
        return True, "eligible_exact_real_count"
    return False, "non_exact_real_count_excluded"


def _is_exact_real_count_row(row: dict[str, Any]) -> bool:
    label_type = str(row.get("cardinality_label_type") or "").strip().lower()
    if label_type.startswith("exact_k") and label_type.endswith("_gold"):
        return True
    status = str(row.get("count_annotation_status") or "").strip().lower()
    return status in EXACT_COUNT_STATUS_VALUES


def _count_distribution(counts: list[int], *, bucket_cap: int) -> dict[str, int]:
    distribution = {f"k={value}": 0 for value in range(1, bucket_cap + 1)}
    distribution[f"k>{bucket_cap}"] = 0
    for count in counts:
        if count <= bucket_cap:
            distribution[f"k={count}"] += 1
        else:
            distribution[f"k>{bucket_cap}"] += 1
    return distribution


def _repository_level_distribution(rows: list[dict[str, Any]], *, bucket_cap: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        repo = str(row.get("repo") or row.get("repository") or "unknown")
        grouped[repo].append(int(row.get("exact_k") or 0))
    payload: list[dict[str, Any]] = []
    for repo in sorted(grouped):
        counts = grouped[repo]
        payload.append(
            {
                "repository": repo,
                "sample_count": len(counts),
                "mean_exact_k": (sum(counts) / len(counts)) if counts else None,
                "count_distribution": _count_distribution(counts, bucket_cap=bucket_cap),
            }
        )
    return payload


def _repository_cluster_bootstrap_ci(rows: list[dict[str, Any]], *, kmax: int, samples: int = 500) -> dict[str, Any]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        repo = str(row.get("repo") or row.get("repository") or "unknown")
        grouped[repo].append(int(row.get("exact_k") or 0))
    repos = sorted(grouped)
    if not repos:
        return {
            "cluster_unit": "repository",
            "bootstrap_samples": samples,
            "metric": "coverage_at_kmax",
            "mean": None,
            "lower": None,
            "upper": None,
            "eligible_repo_count": 0,
            "level": 0.95,
        }
    rng = random.Random(0)
    bootstrap_values: list[float] = []
    for _ in range(samples):
        sampled_counts: list[int] = []
        for _index in range(len(repos)):
            sampled_repo = repos[rng.randrange(len(repos))]
            sampled_counts.extend(grouped[sampled_repo])
        metric = _coverage_for_counts(sampled_counts, kmax=kmax)["coverage_at_kmax"]
        if metric is not None:
            bootstrap_values.append(float(metric))
    sorted_values = sorted(bootstrap_values)
    lower = _percentile(sorted_values, 0.025)
    upper = _percentile(sorted_values, 0.975)
    mean = (sum(sorted_values) / len(sorted_values)) if sorted_values else None
    return {
        "cluster_unit": "repository",
        "bootstrap_samples": samples,
        "metric": "coverage_at_kmax",
        "mean": mean,
        "lower": lower,
        "upper": upper,
        "eligible_repo_count": len(repos),
        "level": 0.95,
    }


def _train_dev_leakage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    train_groups = {
        str(row.get("leakage_group") or "")
        for row in rows
        if _normalize_split(row.get("split")) == "train" and str(row.get("leakage_group") or "")
    }
    dev_groups = {
        str(row.get("leakage_group") or "")
        for row in rows
        if _normalize_split(row.get("split")) == "dev" and str(row.get("leakage_group") or "")
    }
    overlap = sorted(train_groups & dev_groups)
    return {
        "train_group_count": len(train_groups),
        "dev_group_count": len(dev_groups),
        "overlap_count": len(overlap),
        "overlap_examples": overlap[:10],
        "leakage_clean": len(overlap) == 0,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    clamped = min(max(fraction, 0.0), 1.0)
    index = int(round((len(values) - 1) * clamped))
    return values[index]
