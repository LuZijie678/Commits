from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any

from code.mica.eval.attribution_metrics import adjusted_rand_index, bcubed_f1, pairwise_f1_from_assignments
from code.mica.stage1_v2.family_split import canonicalize_candidate_row
from code.mica.stage1_v2.real_count import quadratic_weighted_kappa


REAL_ADJUDICATED_RECORD_SCHEMA_VERSION = "mica-stage1-v2-real-adjudicated-record-v1"
VALID_UNIT_LABELS = {"foreground", "background", "shared_support", "uncertain", "mixed"}
VALID_ANNOTATION_STATES = {
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
    # Legacy compatibility states retained for older fixtures.
    "double_annotated",
    "needs_adjudication",
}


def build_real_adjudicated_annotation_queue(
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
                "schema_version": REAL_ADJUDICATED_RECORD_SCHEMA_VERSION,
                "sample_id": str(row.get("sample_id") or f"real_adjudicated_candidate_{index:06d}"),
                "commit_id": str(row.get("commit_id") or row.get("sha") or row.get("sample_id") or ""),
                "repository": str(row.get("repo") or row.get("repository") or ""),
                "diff_reference": {
                    "repo": str(row.get("repo") or row.get("repository") or ""),
                    "sha": str(row.get("sha") or row.get("commit_id") or ""),
                    "source_asset": str(row.get("source_asset") or row.get("source_pool") or "unknown"),
                },
                "split_candidate": str(row.get("split_candidate") or row.get("split") or "pending"),
                "candidate_tags": list(row.get("candidate_tags") or []),
                "annotation_status": "pending",
                "blind_status": "hidden",
                "model_prediction_hidden": True,
                "commit_message_hidden": True,
                "split_hidden": True,
                "annotator_a_id": None,
                "annotator_b_id": None,
                "adjudicator_id": None,
                "annotation_a": None,
                "annotation_b": None,
                "agreement": None,
                "adjudicated_annotation": None,
                "adjudication_reason": None,
                "blind_review": None,
                "guideline_version": guideline_version,
                "annotation_version": annotation_version,
                "edit_units": list(row.get("edit_units") or []),
                "metadata": {
                    "language": row.get("language"),
                    "path_roles": row.get("path_roles"),
                    "file_count": row.get("file_count"),
                    "hunk_count": row.get("hunk_count"),
                    "changed_lines": row.get("changed_lines"),
                },
            }
        )
    return {
        "schema_version": REAL_ADJUDICATED_RECORD_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows": rows,
    }


def sample_real_adjudicated_candidates(
    candidates: list[dict[str, Any]],
    *,
    max_samples: int,
    max_per_repository: int,
    seed: int = 0,
) -> dict[str, Any]:
    ordered = sorted(
        [canonicalize_candidate_row(candidate) for candidate in candidates],
        key=lambda row: hashlib.sha1(f"{seed}:{row.get('sample_id')}".encode("utf-8")).hexdigest(),
    )
    selected: list[dict[str, Any]] = []
    repo_counts: Counter[str] = Counter()
    for row in ordered:
        repo = str(row.get("repo") or row.get("repository") or "unknown")
        if repo_counts[repo] >= max_per_repository:
            continue
        selected.append(row)
        repo_counts[repo] += 1
        if len(selected) >= max_samples:
            break
    return {
        "schema_version": "mica-stage1-v2-real-adjudicated-sampler-v1",
        "requested_sample_count": max_samples,
        "max_per_repository": max_per_repository,
        "selected_sample_count": len(selected),
        "repository_count": len(repo_counts),
        "rows": selected,
    }


def validate_real_adjudicated_record(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    required = (
        "schema_version",
        "sample_id",
        "commit_id",
        "repository",
        "diff_reference",
        "split_candidate",
        "annotation_status",
        "blind_status",
        "model_prediction_hidden",
        "commit_message_hidden",
        "split_hidden",
        "guideline_version",
        "annotation_version",
        "edit_units",
    )
    for field in required:
        if row.get(field) in (None, "", []):
            errors.append(f"missing_{field}")
    if str(row.get("schema_version") or "") != REAL_ADJUDICATED_RECORD_SCHEMA_VERSION:
        errors.append("invalid_schema_version")
    status = str(row.get("annotation_status") or "")
    if status not in VALID_ANNOTATION_STATES:
        errors.append("invalid_annotation_status")
    for field_name in ("annotation_a", "annotation_b", "adjudicated_annotation"):
        payload = row.get(field_name)
        if payload is not None:
            errors.extend(f"{field_name}:{item}" for item in _validate_single_annotation(payload))
    if status == "adjudicated":
        if row.get("annotation_a") is None or row.get("annotation_b") is None:
            errors.append("missing_double_annotation")
        if row.get("adjudicated_annotation") is None:
            errors.append("missing_adjudicated_annotation")
        if not row.get("adjudicator_id"):
            errors.append("missing_adjudicator_id")
    return {"valid": not errors, "errors": errors}


def summarize_real_adjudicated_readiness(
    rows: list[dict[str, Any]],
    *,
    agreement_thresholds: dict[str, float],
    target_distribution: dict[str, int],
    strata_targets: dict[str, int],
    repository_limits: dict[str, float],
) -> dict[str, Any]:
    validations = [validate_real_adjudicated_record(row) for row in rows]
    status_counts = Counter(str(row.get("annotation_status") or "missing") for row in rows)
    sample_rows = [row for row, validation in zip(rows, validations) if validation["valid"]]
    double_complete = sum(1 for row in sample_rows if row.get("annotation_a") and row.get("annotation_b"))
    adjudicated_complete = sum(1 for row in sample_rows if row.get("annotation_status") == "adjudicated")
    blind_review_complete = sum(1 for row in sample_rows if isinstance(row.get("blind_review"), dict) and row["blind_review"].get("completed"))
    agreement = summarize_real_adjudicated_agreement(sample_rows)
    strata = benchmark_strata_readiness(sample_rows, target_distribution=target_distribution, strata_targets=strata_targets, repository_limits=repository_limits)
    agreement_gates = {
        "exact_k_weighted_kappa": _gate(agreement.get("exact_k_weighted_kappa"), agreement_thresholds.get("exact_k_weighted_kappa_min")),
        "split_no_split_kappa": _gate(agreement.get("split_no_split_kappa"), agreement_thresholds.get("split_no_split_kappa_min")),
        "foreground_background_agreement": _gate(agreement.get("foreground_background_agreement"), agreement_thresholds.get("foreground_background_agreement_min")),
        "bcubed_agreement": _gate(agreement.get("mean_bcubed_f1"), agreement_thresholds.get("bcubed_agreement_min")),
        "pairwise_unit_agreement": _gate(agreement.get("mean_pairwise_f1"), agreement_thresholds.get("pairwise_unit_agreement_min")),
    }
    return {
        "schema_version": "mica-stage1-v2-real-adjudicated-readiness-v1",
        "row_count": len(rows),
        "valid_row_count": sum(1 for item in validations if item["valid"]),
        "invalid_row_count": sum(1 for item in validations if not item["valid"]),
        "status_counts": dict(sorted(status_counts.items())),
        "double_annotation_complete": double_complete == len(sample_rows) and len(sample_rows) > 0,
        "adjudication_complete": adjudicated_complete == len(sample_rows) and len(sample_rows) > 0,
        "blind_review_fraction": (blind_review_complete / len(sample_rows)) if sample_rows else 0.0,
        "agreement": agreement,
        "agreement_gates": agreement_gates,
        "benchmark_strata": strata,
        "formal_ready": (
            len(sample_rows) > 0
            and double_complete == len(sample_rows)
            and adjudicated_complete == len(sample_rows)
            and all(bool(item["passed"]) for item in agreement_gates.values())
            and bool(strata["formal_ready"])
        ),
    }


def summarize_real_adjudicated_agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in rows if row.get("annotation_a") and row.get("annotation_b")]
    if not comparable:
        return {
            "double_annotated_count": 0,
            "exact_k_agreement_rate": None,
            "exact_k_weighted_kappa": None,
            "split_no_split_kappa": None,
            "foreground_background_agreement": None,
            "mean_pairwise_f1": None,
            "mean_bcubed_f1": None,
            "mean_ari": None,
        }
    exact_a = [int(row["annotation_a"]["exact_k"]) for row in comparable]
    exact_b = [int(row["annotation_b"]["exact_k"]) for row in comparable]
    split_a = [1 if value > 1 else 0 for value in exact_a]
    split_b = [1 if value > 1 else 0 for value in exact_b]
    foreground_background_scores = []
    pairwise_scores = []
    bcubed_scores = []
    ari_scores = []
    for row in comparable:
        annotation_a = row["annotation_a"]
        annotation_b = row["annotation_b"]
        foreground_background_scores.append(_foreground_background_agreement(annotation_a, annotation_b))
        left_map = _foreground_unit_to_intent(annotation_a)
        right_map = _foreground_unit_to_intent(annotation_b)
        shared_units = sorted(set(left_map) & set(right_map))
        left_labels = [left_map[unit_id] for unit_id in shared_units]
        right_labels = [right_map[unit_id] for unit_id in shared_units]
        pairwise_scores.append(pairwise_f1_from_assignments(left_map, right_map)["pairwise_f1"])
        bcubed_scores.append(bcubed_f1(left_labels, right_labels)["bcubed_f1"] if left_labels else 0.0)
        ari_scores.append(adjusted_rand_index(left_labels, right_labels)["ari"] if left_labels else 0.0)
    return {
        "double_annotated_count": len(comparable),
        "exact_k_agreement_rate": sum(1 for left, right in zip(exact_a, exact_b) if left == right) / len(comparable),
        "exact_k_weighted_kappa": quadratic_weighted_kappa(exact_a, exact_b),
        "split_no_split_kappa": _binary_cohen_kappa(split_a, split_b),
        "foreground_background_agreement": sum(foreground_background_scores) / len(foreground_background_scores),
        "mean_pairwise_f1": sum(pairwise_scores) / len(pairwise_scores),
        "mean_bcubed_f1": sum(bcubed_scores) / len(bcubed_scores),
        "mean_ari": sum(ari_scores) / len(ari_scores),
    }


def benchmark_strata_readiness(
    rows: list[dict[str, Any]],
    *,
    target_distribution: dict[str, int],
    strata_targets: dict[str, int],
    repository_limits: dict[str, float],
) -> dict[str, Any]:
    adjudicated_rows = [row for row in rows if row.get("adjudicated_annotation")]
    exact_k_counts: Counter[int] = Counter()
    strata_counts: Counter[str] = Counter()
    repo_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    file_role_counts: Counter[str] = Counter()
    units_per_sample: list[int] = []
    hunks_per_sample: list[int] = []
    files_per_sample: list[int] = []
    for row in adjudicated_rows:
        adjudicated = row["adjudicated_annotation"]
        exact_k_counts[int(adjudicated["exact_k"])] += 1
        for tag in list(row.get("candidate_tags") or []):
            strata_counts[str(tag)] += 1
        repo_counts[str(row.get("repository") or "unknown")] += 1
        metadata = dict(row.get("metadata") or {})
        if metadata.get("language"):
            language_counts[str(metadata["language"])] += 1
        for role in _normalize_role_values(metadata.get("path_roles")):
            file_role_counts[role] += 1
        units_per_sample.append(len(list(row.get("edit_units") or [])))
        hunks_per_sample.append(int(metadata.get("hunk_count") or len(list(row.get("edit_units") or []))))
        files_per_sample.append(int(metadata.get("file_count") or len({str(unit.get("file_path") or "") for unit in row.get("edit_units", [])})))
    total = len(adjudicated_rows)
    top5_share = sum(count for _repo, count in repo_counts.most_common(5)) / total if total else 0.0
    max_repo_share = (max(repo_counts.values()) / total) if repo_counts and total else 0.0
    required_k = {
        1: target_distribution.get("k1_regular", 0) + target_distribution.get("k1_hard_single", 0),
        2: target_distribution.get("k2", 0),
        3: target_distribution.get("k3", 0),
        4: target_distribution.get("k4", 0),
    }
    k_gates = {f"k{value}": exact_k_counts.get(value, 0) >= int(required) for value, required in required_k.items()}
    strata_gates = {tag: strata_counts.get(tag, 0) >= int(target) for tag, target in strata_targets.items()}
    repository_gate = max_repo_share <= float(repository_limits.get("single_repository_max_fraction", 1.0))
    top5_gate = top5_share <= float(repository_limits.get("top5_repository_max_fraction", 1.0))
    return {
        "adjudicated_sample_count": total,
        "exact_k_counts": {str(key): int(value) for key, value in sorted(exact_k_counts.items())},
        "strata_counts": dict(sorted(strata_counts.items())),
        "repository_count": len(repo_counts),
        "max_repository_share": max_repo_share,
        "top5_repository_share": top5_share,
        "language_counts": dict(sorted(language_counts.items())),
        "file_role_counts": dict(sorted(file_role_counts.items())),
        "units_per_sample": _distribution_summary(units_per_sample),
        "hunks_per_sample": _distribution_summary(hunks_per_sample),
        "files_per_sample": _distribution_summary(files_per_sample),
        "k_gates": k_gates,
        "strata_gates": strata_gates,
        "repository_concentration_passed": repository_gate and top5_gate,
        "formal_ready": total > 0 and all(k_gates.values()) and all(strata_gates.values()) and repository_gate and top5_gate,
    }


def _validate_single_annotation(annotation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if annotation.get("exact_k") is None:
        errors.append("missing_exact_k")
    intents = list(annotation.get("intents") or [])
    unit_labels = dict(annotation.get("unit_labels") or {})
    if int(annotation.get("exact_k") or 0) != len(intents):
        errors.append("exact_k_intent_count_mismatch")
    seen_foreground_intent_ids = set()
    for unit_id, payload in unit_labels.items():
        label = str(dict(payload).get("label") or "")
        if label not in VALID_UNIT_LABELS:
            errors.append(f"invalid_unit_label:{unit_id}")
            continue
        if label == "foreground":
            intent_id = str(dict(payload).get("intent_id") or "")
            if not intent_id:
                errors.append(f"missing_foreground_intent_id:{unit_id}")
            else:
                seen_foreground_intent_ids.add(intent_id)
        elif dict(payload).get("intent_id"):
            errors.append(f"nonforeground_must_not_have_intent_id:{unit_id}")
    for intent in intents:
        if not str(dict(intent).get("action") or "").strip() or not str(dict(intent).get("object") or "").strip():
            errors.append("missing_action_or_object")
            break
    if len(seen_foreground_intent_ids) > len(intents):
        errors.append("foreground_intent_id_count_exceeds_intents")
    return errors


def _foreground_unit_to_intent(annotation: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for unit_id, payload in dict(annotation.get("unit_labels") or {}).items():
        info = dict(payload or {})
        if str(info.get("label") or "") == "foreground" and str(info.get("intent_id") or ""):
            mapping[str(unit_id)] = str(info["intent_id"])
    return mapping


def _foreground_background_agreement(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_labels = dict(left.get("unit_labels") or {})
    right_labels = dict(right.get("unit_labels") or {})
    unit_ids = sorted(set(left_labels) | set(right_labels))
    comparable = 0
    matched = 0
    for unit_id in unit_ids:
        left_value = _collapse_fg_bg_label(left_labels.get(unit_id))
        right_value = _collapse_fg_bg_label(right_labels.get(unit_id))
        if left_value is None or right_value is None:
            continue
        comparable += 1
        matched += int(left_value == right_value)
    return matched / comparable if comparable else 0.0


def _collapse_fg_bg_label(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    label = str(payload.get("label") or "")
    if label == "foreground":
        return "foreground"
    if label == "background":
        return "background"
    return None


def _binary_cohen_kappa(left: list[int], right: list[int]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    total = len(left)
    agree = sum(1 for a, b in zip(left, right) if a == b) / total
    left_pos = sum(left) / total
    right_pos = sum(right) / total
    expected = left_pos * right_pos + (1 - left_pos) * (1 - right_pos)
    if expected == 1.0:
        return 1.0
    return (agree - expected) / (1 - expected)


def _gate(value: float | None, threshold: float | None) -> dict[str, Any]:
    if value is None or threshold is None:
        return {"value": value, "threshold": threshold, "passed": False}
    return {"value": value, "threshold": threshold, "passed": float(value) >= float(threshold)}


def _normalize_role_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if value in (None, ""):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _distribution_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }
