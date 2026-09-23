from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from code.mica.eval.kmax_coverage import build_kmax_coverage_report
from code.mica.stage1_v2.family_split import canonicalize_candidate_row


REAL_COUNT_QUEUE_SCHEMA_VERSION = "mica-stage1-v2-real-count-queue-v1"
ELIGIBLE_REAL_COUNT_SOURCE_TYPES = {"hard_b", "m_weak", "real_candidate", "real_count_candidate"}
EXCLUDED_REAL_COUNT_SOURCE_TYPES = {"strict_synthetic", "strict_replay", "pseudo_exact_count"}
VALID_REAL_COUNT_ANNOTATION_STATES = {
    "pending",
    "annotated_a",
    "annotated_b",
    "independently_double_annotated",
    "agreement",
    "conflict",
    "adjudication_pending",
    "adjudicated",
    "quality_reviewed",
    "eligible_for_asset",
    # Legacy compatibility states retained for earlier fixtures.
    "double_annotated",
    "conflict_pending_adjudication",
}


def build_real_count_annotation_queue(
    candidates: list[dict[str, Any]],
    *,
    guideline_version: str,
    annotation_version: str,
) -> dict[str, Any]:
    rows = []
    for index, candidate in enumerate(candidates):
        row = canonicalize_candidate_row(candidate)
        rows.append(
            {
                "schema_version": REAL_COUNT_QUEUE_SCHEMA_VERSION,
                "sample_id": str(row.get("sample_id") or f"real_count_candidate_{index:06d}"),
                "commit_id": str(row.get("commit_id") or row.get("sha") or row.get("sample_id") or ""),
                "repository": str(row.get("repo") or row.get("repository") or ""),
                "diff_reference": {
                    "repo": str(row.get("repo") or row.get("repository") or ""),
                    "sha": str(row.get("sha") or row.get("commit_id") or ""),
                    "source_asset": str(row.get("source_asset") or row.get("source_pool") or "unknown"),
                },
                "split_candidate": str(row.get("split_candidate") or row.get("split") or "pending"),
                "current_weak_label": str(row.get("current_weak_label") or row.get("weak_label") or row.get("cardinality_label_type") or ""),
                "source_type": str(row.get("source_type") or row.get("source_kind") or "real_candidate"),
                "annotation_status": "pending",
                "annotator_a_count": None,
                "annotator_b_count": None,
                "adjudicated_exact_k": None,
                "annotator_a_id": None,
                "annotator_b_id": None,
                "adjudicator_id": None,
                "guideline_version": guideline_version,
                "annotation_version": annotation_version,
                "leakage_group": str(row.get("leakage_group") or f"{row.get('repo')}::{row.get('sha')}"),
                "normalized_diff_hash": str(row.get("normalized_diff_hash") or ""),
                "count_annotation_status": "pending",
            }
        )
    return {
        "schema_version": REAL_COUNT_QUEUE_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows": rows,
    }


def validate_real_count_row(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    required = (
        "schema_version",
        "sample_id",
        "commit_id",
        "repository",
        "diff_reference",
        "split_candidate",
        "current_weak_label",
        "source_type",
        "annotation_status",
        "guideline_version",
        "annotation_version",
        "leakage_group",
        "normalized_diff_hash",
    )
    for field in required:
        if row.get(field) in (None, "", []):
            errors.append(f"missing_{field}")
    if str(row.get("schema_version") or "") != REAL_COUNT_QUEUE_SCHEMA_VERSION:
        errors.append("invalid_schema_version")
    source_type = str(row.get("source_type") or "")
    if source_type in EXCLUDED_REAL_COUNT_SOURCE_TYPES:
        errors.append("forbidden_source_type")
    weak_label = str(row.get("current_weak_label") or "").lower()
    if "commit_message" in weak_label:
        errors.append("commit_message_derived_count_forbidden")
    status = str(row.get("annotation_status") or "")
    if status == "adjudicated":
        if row.get("adjudicated_exact_k") is None:
            errors.append("missing_adjudicated_exact_k")
        if not row.get("annotator_a_id") or not row.get("annotator_b_id") or not row.get("adjudicator_id"):
            errors.append("missing_annotation_actor")
    if status not in VALID_REAL_COUNT_ANNOTATION_STATES:
        errors.append("invalid_annotation_status")
    return {"valid": not errors, "errors": errors}


def summarize_real_count_queue(rows: list[dict[str, Any]]) -> dict[str, Any]:
    validations = [validate_real_count_row(row) for row in rows]
    status_counts = Counter(str(row.get("annotation_status") or "missing") for row in rows)
    source_counts = Counter(str(row.get("source_type") or "missing") for row in rows)
    agreement = summarize_real_count_agreement(rows)
    return {
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "source_type_counts": dict(sorted(source_counts.items())),
        "valid_row_count": sum(1 for item in validations if item["valid"]),
        "invalid_row_count": sum(1 for item in validations if not item["valid"]),
        "agreement": agreement,
    }


def summarize_real_count_agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [
        row
        for row in rows
        if _get_count_value(row, "a") is not None and _get_count_value(row, "b") is not None
    ]
    if not comparable:
        return {
            "double_annotated_count": 0,
            "count_agreement_rate": None,
            "weighted_kappa": None,
            "adjudication_rate": None,
        }
    a_counts = [int(_get_count_value(row, "a") or 0) for row in comparable]
    b_counts = [int(_get_count_value(row, "b") or 0) for row in comparable]
    agreement_rate = sum(1 for left, right in zip(a_counts, b_counts) if left == right) / len(comparable)
    needs_adjudication = sum(1 for left, right in zip(a_counts, b_counts) if left != right)
    adjudicated = sum(1 for row in comparable if row.get("annotation_status") == "adjudicated")
    return {
        "double_annotated_count": len(comparable),
        "count_agreement_rate": agreement_rate,
        "weighted_kappa": quadratic_weighted_kappa(a_counts, b_counts),
        "adjudication_rate": adjudicated / needs_adjudication if needs_adjudication else 0.0,
    }


def build_real_count_kmax_asset(
    rows: list[dict[str, Any]],
    *,
    tau: float,
) -> dict[str, Any]:
    eligible_rows: list[dict[str, Any]] = []
    excluded_rows_by_reason: dict[str, int] = defaultdict(int)
    for row in rows:
        eligible, reason = _is_real_count_kmax_eligible(row)
        if not eligible:
            excluded_rows_by_reason[reason] += 1
            continue
        eligible_rows.append(
            {
                "sample_id": row["sample_id"],
                "repo": row["repository"],
                "split": row["split_candidate"],
                "gold_count": int(row["adjudicated_exact_k"]),
                "cardinality_label_type": f"exact_k{int(row['adjudicated_exact_k'])}_gold",
                "count_annotation_status": "manual_exact_gold",
                "source_type": row["source_type"],
                "leakage_group": row["leakage_group"],
                "normalized_diff_hash": row["normalized_diff_hash"],
            }
        )
    max_candidate_k = max([int(row["gold_count"]) for row in eligible_rows], default=4)
    coverage_curve = []
    selected_k = None
    for candidate_k in range(1, max_candidate_k + 1):
        report = build_kmax_coverage_report(eligible_rows, kmax=candidate_k, tau=tau, selected_kmax=candidate_k)
        lcb = report["repository_cluster_bootstrap_ci"]["lower"]
        coverage_curve.append(
            {
                "candidate_kmax": candidate_k,
                "coverage_at_kmax": report["train_dev_selection_basis"]["coverage_at_kmax"],
                "lcb_95": lcb,
            }
        )
        if selected_k is None and lcb is not None and float(lcb) >= float(tau):
            selected_k = candidate_k
    return {
        "schema_version": "mica-stage1-v2-real-count-kmax-asset-v1",
        "tau": float(tau),
        "eligible_row_count": len(eligible_rows),
        "excluded_rows_by_reason": dict(sorted(excluded_rows_by_reason.items())),
        "selected_kmax": selected_k,
        "coverage_curve": coverage_curve,
        "rows": eligible_rows,
        "status": "candidate_ready_for_freeze" if selected_k is not None else "annotation_pending",
    }


def quadratic_weighted_kappa(left: list[int], right: list[int]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    min_rating = min(min(left), min(right))
    max_rating = max(max(left), max(right))
    categories = list(range(min_rating, max_rating + 1))
    if len(categories) == 1:
        return 1.0
    index = {value: position for position, value in enumerate(categories)}
    observed = [[0.0 for _ in categories] for _ in categories]
    for l_value, r_value in zip(left, right):
        observed[index[l_value]][index[r_value]] += 1.0
    total = float(len(left))
    observed = [[value / total for value in row] for row in observed]
    left_hist = Counter(left)
    right_hist = Counter(right)
    expected = [
        [
            (left_hist[categories[i]] / total) * (right_hist[categories[j]] / total)
            for j in range(len(categories))
        ]
        for i in range(len(categories))
    ]
    weight = [
        [
            ((i - j) ** 2) / ((len(categories) - 1) ** 2)
            for j in range(len(categories))
        ]
        for i in range(len(categories))
    ]
    observed_score = sum(weight[i][j] * observed[i][j] for i in range(len(categories)) for j in range(len(categories)))
    expected_score = sum(weight[i][j] * expected[i][j] for i in range(len(categories)) for j in range(len(categories)))
    if expected_score == 0.0:
        return 1.0
    return 1.0 - (observed_score / expected_score)


def _is_real_count_kmax_eligible(row: dict[str, Any]) -> tuple[bool, str]:
    if str(row.get("source_type") or "") in EXCLUDED_REAL_COUNT_SOURCE_TYPES:
        return False, "excluded_source_type"
    if "censored" in str(row.get("current_weak_label") or "").lower():
        return False, "censored_label"
    if str(row.get("annotation_status") or "") != "adjudicated":
        return False, "annotation_not_adjudicated"
    if row.get("adjudicated_exact_k") is None:
        return False, "missing_exact_k"
    if not row.get("annotator_a_id") or not row.get("annotator_b_id") or not row.get("adjudicator_id"):
        return False, "missing_annotation_provenance"
    if str(row.get("source_type") or "") not in ELIGIBLE_REAL_COUNT_SOURCE_TYPES:
        return False, "non_real_source_type"
    return True, "eligible"


def _get_count_value(row: dict[str, Any], slot: str) -> int | None:
    exact_key = f"annotator_{slot}_exact_k"
    legacy_key = f"annotator_{slot}_count"
    value = row.get(exact_key)
    if value is None:
        value = row.get(legacy_key)
    return int(value) if value is not None else None
