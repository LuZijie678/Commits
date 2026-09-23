from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from code.mica.adapters.stage1_prediction_adapter import normalize_stage1_prediction_row
from code.mica.eval.attribution_metrics import build_primary_alignment_maps, unit_accuracy_hungarian
from code.mica.io_utils import read_json, read_jsonl
from code.mica.runners.stage1_runtime import sha256_file
from code.mica.stages.stage1_official_validation import load_stage1_manifest_rows


METRIC_NAME = "unit_accuracy_gain_over_all_one"
METRIC_BOUND_NAME = "unit_accuracy_gain_over_all_one_min"
METRIC_DEFINITION_VERSION = "stage1-unit-accuracy-gain-over-all-one-v1"
SUPPLEMENT_SCHEMA_VERSION = "mica-stage1-unit-accuracy-supplement-v1"
STATUS_REVISION_SCHEMA_VERSION = "mica-stage1-official-result-status-revision-v1"
AUDIT_SCHEMA_VERSION = "mica-stage1-unit-accuracy-observability-audit-v1"
ALL_ONE_SLOT_ID = "__all_one__"
IMPLEMENTATION_PATH = (
    "code/mica/train/eval_stage1_sanity.py::evaluate_model -> "
    "code/mica/runners/run_stage1_official_validation.py::run_stage1_official_validation"
)
BASELINE_DEFINITION = (
    "Per eligible sample, assign every eligible foreground unit to a single synthetic "
    f"slot `{ALL_ONE_SLOT_ID}`; compute Hungarian unit accuracy; report the sample-mean "
    "MICA unit accuracy minus the sample-mean all-one baseline unit accuracy."
)
REQUIRED_INPUT_FIELDS = {
    "gold": ["sample_id", "gold_unit_to_intent"],
    "prediction": ["sample_id", "unit_to_slot"],
}


def compute_unit_accuracy_gain_from_frozen_rows(
    *,
    gold_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    prediction_index = {
        str(row.get("sample_id")): normalize_stage1_prediction_row(row)
        for row in prediction_rows
    }
    total_units = 0
    eligible_units = 0
    excluded_units = 0
    excluded_samples = 0
    exclusion_counts_by_reason: dict[str, int] = {}
    mica_accuracy_sum = 0.0
    baseline_accuracy_sum = 0.0
    per_sample: list[dict[str, Any]] = []

    for row in gold_rows:
        sample_id = str(row.get("sample_id") or "__missing_sample_id__")
        gold_unit_to_intent = row.get("gold_unit_to_intent")
        if not isinstance(gold_unit_to_intent, dict) or not gold_unit_to_intent:
            _bump(exclusion_counts_by_reason, "missing_gold_unit_to_intent")
            excluded_samples += 1
            continue
        total_units += len(gold_unit_to_intent)
        prediction = prediction_index.get(sample_id)
        if prediction is None:
            _bump(exclusion_counts_by_reason, "missing_prediction_row")
            excluded_samples += 1
            excluded_units += len(gold_unit_to_intent)
            continue
        unit_to_slot = prediction.get("unit_to_slot")
        if not isinstance(unit_to_slot, dict) or not unit_to_slot:
            _bump(exclusion_counts_by_reason, "missing_pred_unit_to_slot")
            excluded_samples += 1
            excluded_units += len(gold_unit_to_intent)
            continue

        combined = dict(row)
        combined["pred_unit_to_slot"] = unit_to_slot
        alignment_maps = build_primary_alignment_maps(combined)
        eligible_gold_map = dict(alignment_maps["gold_unit_to_intent"])
        eligible_pred_map = dict(alignment_maps["pred_unit_to_slot"])
        excluded_alignment_unit_count = int(alignment_maps.get("excluded_alignment_unit_count", 0) or 0)
        excluded_units += excluded_alignment_unit_count

        if not eligible_gold_map:
            _bump(exclusion_counts_by_reason, "no_eligible_gold_units_after_exclusion")
            excluded_samples += 1
            continue
        if not eligible_pred_map:
            _bump(exclusion_counts_by_reason, "prediction_missing_eligible_units")
            excluded_samples += 1
            excluded_units += len(eligible_gold_map)
            continue
        if set(eligible_pred_map) != set(eligible_gold_map):
            _bump(exclusion_counts_by_reason, "prediction_missing_eligible_units")
            excluded_samples += 1
            excluded_units += len(set(eligible_gold_map) - set(eligible_pred_map))
            continue

        eligible_units += len(eligible_gold_map)
        mica_unit_accuracy = float(unit_accuracy_hungarian(eligible_gold_map, eligible_pred_map)["unit_accuracy"])
        baseline_pred_map = {unit_id: ALL_ONE_SLOT_ID for unit_id in sorted(eligible_gold_map)}
        all_one_unit_accuracy = float(unit_accuracy_hungarian(eligible_gold_map, baseline_pred_map)["unit_accuracy"])
        mica_accuracy_sum += mica_unit_accuracy
        baseline_accuracy_sum += all_one_unit_accuracy
        per_sample.append(
            {
                "sample_id": sample_id,
                "eligible_unit_count": len(eligible_gold_map),
                "mica_unit_accuracy": mica_unit_accuracy,
                "all_one_unit_accuracy": all_one_unit_accuracy,
                "gain": mica_unit_accuracy - all_one_unit_accuracy,
                "gold_count": int(row.get("gold_count", 0) or 0),
            }
        )

    eligible_samples = len(per_sample)
    denominator = eligible_samples if eligible_samples > 0 else None
    observed_value = (
        float((mica_accuracy_sum / eligible_samples) - (baseline_accuracy_sum / eligible_samples))
        if eligible_samples > 0
        else None
    )
    return {
        "metric_name": METRIC_NAME,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "baseline_definition": BASELINE_DEFINITION,
        "per_sample": per_sample,
        "total_samples": len(gold_rows),
        "eligible_samples": eligible_samples,
        "excluded_samples": excluded_samples,
        "total_units": total_units,
        "eligible_units": eligible_units,
        "excluded_units": excluded_units,
        "exclusion_counts_by_reason": exclusion_counts_by_reason,
        "mica_unit_accuracy": (mica_accuracy_sum / eligible_samples) if eligible_samples > 0 else None,
        "all_one_baseline_accuracy": (baseline_accuracy_sum / eligible_samples) if eligible_samples > 0 else None,
        "numerator": {
            "mica_unit_accuracy_sum": mica_accuracy_sum if eligible_samples > 0 else None,
            "all_one_unit_accuracy_sum": baseline_accuracy_sum if eligible_samples > 0 else None,
            "gain_sum_difference": (mica_accuracy_sum - baseline_accuracy_sum) if eligible_samples > 0 else None,
        },
        "denominator": denominator,
        "observed_value": observed_value,
        "null_reason": None if observed_value is not None else _null_reason(exclusion_counts_by_reason, eligible_samples),
    }


def build_stage1_unit_accuracy_observability_audit(
    *,
    official_run_id: str,
    official_manifest_path: str | Path,
    predictions_path: str | Path,
    aggregate_metrics_path: str | Path,
    final_test_manifest_path: str | Path,
    threshold_spec_path: str | Path,
    official_result_path: str | Path,
    checkpoint_sha256: str,
) -> dict[str, Any]:
    official_manifest = read_json(official_manifest_path)
    aggregate_metrics = read_json(aggregate_metrics_path)
    threshold_spec = read_json(threshold_spec_path)
    official_result = read_json(official_result_path)
    gold_rows = load_stage1_manifest_rows(final_test_manifest_path)
    prediction_rows = read_jsonl(predictions_path)
    available_input_fields = {
        "gold_row_fields": sorted({key for row in gold_rows for key in row.keys()}),
        "prediction_row_fields": sorted({key for row in prediction_rows for key in row.keys()}),
        "gold_edit_unit_fields": sorted(
            {
                key
                for row in gold_rows
                for unit in row.get("edit_units", [])
                if isinstance(unit, dict)
                for key in unit.keys()
            }
        ),
        "prediction_unit_record_fields": sorted(
            {
                key
                for row in prediction_rows
                for unit in row.get("unit_records", row.get("edit_units", []))
                if isinstance(unit, dict)
                for key in unit.keys()
            }
        ),
    }
    missing_input_fields = _missing_required_fields(gold_rows=gold_rows, prediction_rows=prediction_rows)
    recomputed = compute_unit_accuracy_gain_from_frozen_rows(gold_rows=gold_rows, prediction_rows=prediction_rows)
    threshold_value = threshold_spec.get(METRIC_BOUND_NAME)
    threshold_bound_result = dict(aggregate_metrics.get("official_gate_results", {}).get(METRIC_NAME, {}))
    observed_in_aggregate = threshold_bound_result.get("observed")
    root_cause_class = _root_cause_class(
        observed_in_aggregate=observed_in_aggregate,
        recomputed_observed=recomputed["observed_value"],
        missing_input_fields=missing_input_fields,
        eligible_denominator=recomputed["denominator"],
    )
    null_reason = recomputed["null_reason"]
    if observed_in_aggregate is None and recomputed["observed_value"] is not None:
        null_reason = "aggregate_metric_missing_despite_complete_frozen_inputs"
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "official_run_id": official_run_id,
        "official_manifest_sha256": sha256_file(official_manifest_path),
        "predictions_sha256": sha256_file(predictions_path),
        "aggregate_metrics_sha256": sha256_file(aggregate_metrics_path),
        "final_test_manifest_sha256": sha256_file(final_test_manifest_path),
        "official_result_sha256": sha256_file(official_result_path),
        "checkpoint_sha256": checkpoint_sha256,
        "metric_name": METRIC_NAME,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "metric_implementation_path": IMPLEMENTATION_PATH,
        "baseline_definition": BASELINE_DEFINITION,
        "required_input_fields": deepcopy(REQUIRED_INPUT_FIELDS),
        "available_input_fields": available_input_fields,
        "missing_input_fields": missing_input_fields,
        "total_samples": recomputed["total_samples"],
        "eligible_samples": recomputed["eligible_samples"],
        "excluded_samples": recomputed["excluded_samples"],
        "total_units": recomputed["total_units"],
        "eligible_units": recomputed["eligible_units"],
        "excluded_units": recomputed["excluded_units"],
        "exclusion_counts_by_reason": recomputed["exclusion_counts_by_reason"],
        "numerator": recomputed["numerator"],
        "denominator": recomputed["denominator"],
        "observed_value": recomputed["observed_value"],
        "null_reason": null_reason,
        "root_cause_class": root_cause_class,
        "recomputation_allowed": bool(
            root_cause_class == "metric_computation_bug" and recomputed["observed_value"] is not None
        ),
        "protocol_amendment_required": bool(root_cause_class == "metric_definition_ambiguous"),
        "test_data_reexecution_required": False,
        "model_reexecution_required": False,
        "aggregate_metric_observed": observed_in_aggregate,
        "aggregate_metric_expected_bound": threshold_value,
        "frozen_definition_unique": True,
        "definition_notes": [
            "Threshold key was frozen before official evaluation.",
            "Historical Stage 1 code already computed the gain as unit_accuracy_hungarian - all_one_unit_accuracy.",
            "The frozen official final-test asset contains no uncertain/shared/mixed exclusions, so exclusion ambiguity does not affect the recovered value.",
        ],
        "source_artifact_hashes": {
            "official_manifest": sha256_file(official_manifest_path),
            "predictions": sha256_file(predictions_path),
            "aggregate_metrics": sha256_file(aggregate_metrics_path),
            "final_test_manifest": sha256_file(final_test_manifest_path),
            "threshold_spec": sha256_file(threshold_spec_path),
            "official_result": sha256_file(official_result_path),
        },
        "official_result_recorded_paper_ready": bool(official_result.get("paper_ready")),
        "official_manifest_recorded_paper_ready": bool(official_manifest.get("paper_ready")),
    }


def build_stage1_unit_accuracy_supplement(
    *,
    official_result: dict[str, Any],
    observability_audit: dict[str, Any],
    threshold_spec: dict[str, Any],
    computation_git_sha: str,
) -> dict[str, Any]:
    threshold = threshold_spec.get(METRIC_BOUND_NAME)
    observed_value = observability_audit.get("observed_value")
    passed = bool(observed_value is not None and threshold is not None and float(observed_value) >= float(threshold))
    return {
        "schema_version": SUPPLEMENT_SCHEMA_VERSION,
        "parent_official_run_id": official_result["run_id"],
        "supplement_version": "supplement_v1",
        "reason": "missing_metric_computation_completed_from_frozen_artifacts",
        "root_cause": observability_audit["root_cause_class"],
        "metric_name": METRIC_NAME,
        "formula_version": METRIC_DEFINITION_VERSION,
        "eligible_sample_count": observability_audit["eligible_samples"],
        "eligible_unit_count": observability_audit["eligible_units"],
        "excluded_sample_count": observability_audit["excluded_samples"],
        "excluded_unit_count": observability_audit["excluded_units"],
        "all_one_baseline_accuracy": observability_audit["numerator"]["all_one_unit_accuracy_sum"] / observability_audit["denominator"]
        if observability_audit.get("denominator")
        else None,
        "mica_unit_accuracy": observability_audit["numerator"]["mica_unit_accuracy_sum"] / observability_audit["denominator"]
        if observability_audit.get("denominator")
        else None,
        "absolute_gain": observed_value,
        "acceptance_threshold": float(threshold) if threshold is not None else None,
        "passed": passed,
        "source_artifact_hashes": deepcopy(observability_audit["source_artifact_hashes"]),
        "checkpoint_sha256": official_result["checkpoint_sha256"],
        "threshold_version": official_result["threshold_version"],
        "kmax_decision_version": official_result["kmax_decision_version"],
        "computation_git_sha": computation_git_sha,
        "no_model_change": True,
        "no_prediction_change": True,
        "no_test_driven_tuning": True,
        "status": "metric_recovered_from_frozen_artifacts" if passed else "metric_failed_threshold",
    }


def build_stage1_official_status_revision(
    *,
    official_result: dict[str, Any],
    supplement_record: dict[str, Any],
    supplement_record_path: str,
    computation_git_sha: str,
) -> dict[str, Any]:
    passed = bool(supplement_record.get("passed"))
    return {
        "schema_version": STATUS_REVISION_SCHEMA_VERSION,
        "parent_official_run_id": official_result["run_id"],
        "status_revision_version": "status_revision_v1",
        "official_validation_executed": True,
        "formal_ready": True,
        "paper_ready": passed,
        "paper_ready_revision_reason": "missing_metric_computation_completed" if passed else "missing_metric_computation_completed_but_threshold_failed",
        "supplemental_metric_record_path": supplement_record_path,
        "supplemental_metric_record_hash": sha256_file(supplement_record_path),
        "checkpoint_sha256": official_result["checkpoint_sha256"],
        "threshold_version": official_result["threshold_version"],
        "kmax_decision_version": official_result["kmax_decision_version"],
        "computation_git_sha": computation_git_sha,
        "status": "paper_ready" if passed else "not_paper_ready",
    }


def load_and_compute_stage1_unit_accuracy_supplement(
    *,
    official_result_path: str | Path,
    official_manifest_path: str | Path,
    predictions_path: str | Path,
    aggregate_metrics_path: str | Path,
    final_test_manifest_path: str | Path,
    threshold_spec_path: str | Path,
    checkpoint_sha256: str,
    computation_git_sha: str,
) -> dict[str, Any]:
    official_result = read_json(official_result_path)
    threshold_spec = read_json(threshold_spec_path)
    observability_audit = build_stage1_unit_accuracy_observability_audit(
        official_run_id=str(official_result["run_id"]),
        official_manifest_path=official_manifest_path,
        predictions_path=predictions_path,
        aggregate_metrics_path=aggregate_metrics_path,
        final_test_manifest_path=final_test_manifest_path,
        threshold_spec_path=threshold_spec_path,
        official_result_path=official_result_path,
        checkpoint_sha256=checkpoint_sha256,
    )
    supplement_record = build_stage1_unit_accuracy_supplement(
        official_result=official_result,
        observability_audit=observability_audit,
        threshold_spec=threshold_spec,
        computation_git_sha=computation_git_sha,
    )
    return {
        "official_result": official_result,
        "observability_audit": observability_audit,
        "supplement_record": supplement_record,
    }


def _missing_required_fields(
    *,
    gold_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    if not gold_rows:
        missing.append("gold.rows")
    if not prediction_rows:
        missing.append("prediction.rows")
    if any(not row.get("sample_id") for row in gold_rows):
        missing.append("gold.sample_id")
    if any(not isinstance(row.get("gold_unit_to_intent"), dict) or not row.get("gold_unit_to_intent") for row in gold_rows):
        missing.append("gold.gold_unit_to_intent")
    if any(not row.get("sample_id") for row in prediction_rows):
        missing.append("prediction.sample_id")
    if any(not isinstance(row.get("unit_to_slot"), dict) or not row.get("unit_to_slot") for row in prediction_rows):
        missing.append("prediction.unit_to_slot")
    return sorted(set(missing))


def _null_reason(exclusion_counts_by_reason: dict[str, int], eligible_samples: int) -> str:
    if eligible_samples == 0:
        if exclusion_counts_by_reason:
            primary_reason = sorted(exclusion_counts_by_reason.items(), key=lambda item: (-item[1], item[0]))[0][0]
            return f"no_eligible_samples:{primary_reason}"
        return "zero_eligible_denominator"
    return "unknown"


def _root_cause_class(
    *,
    observed_in_aggregate: Any,
    recomputed_observed: float | None,
    missing_input_fields: list[str],
    eligible_denominator: int | None,
) -> str:
    if observed_in_aggregate is not None:
        return "metric_already_observed"
    if missing_input_fields:
        return "metric_inputs_missing"
    if eligible_denominator in {None, 0}:
        return "zero_eligible_denominator"
    if recomputed_observed is not None:
        return "metric_computation_bug"
    return "other"


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = int(counter.get(key, 0)) + 1


__all__ = [
    "ALL_ONE_SLOT_ID",
    "AUDIT_SCHEMA_VERSION",
    "BASELINE_DEFINITION",
    "IMPLEMENTATION_PATH",
    "METRIC_BOUND_NAME",
    "METRIC_DEFINITION_VERSION",
    "METRIC_NAME",
    "STATUS_REVISION_SCHEMA_VERSION",
    "SUPPLEMENT_SCHEMA_VERSION",
    "build_stage1_official_status_revision",
    "build_stage1_unit_accuracy_observability_audit",
    "build_stage1_unit_accuracy_supplement",
    "compute_unit_accuracy_gain_from_frozen_rows",
    "load_and_compute_stage1_unit_accuracy_supplement",
]
