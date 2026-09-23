from __future__ import annotations

from pathlib import Path
from typing import Any

from code.mica.adapters.stage1_prediction_adapter import normalize_stage1_prediction_row
from code.mica.baselines.baseline_runner import run_configured_baselines
from code.mica.eval.attribution_metrics import (
    adjusted_rand_index,
    aggregate_attribution_metrics,
    bcubed_f1,
    count_metrics,
    hunk_micro_f1,
    normalized_mutual_info,
    pairwise_f1_from_assignments,
    unit_accuracy_hungarian,
)
from code.mica.io_utils import read_json, read_jsonl


def load_stage1_manifest_rows(manifest_path: str | Path) -> list[dict[str, Any]]:
    target = Path(manifest_path)
    if target.suffix.lower() == ".jsonl":
        return read_jsonl(target)
    payload = read_json(target)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and "rows" in payload:
        return [row for row in payload["rows"] if isinstance(row, dict)]
    if isinstance(payload, dict) and "splits" in payload:
        rows: list[dict[str, Any]] = []
        for split, items in payload["splits"].items():
            for item in items:
                if not isinstance(item, dict):
                    continue
                copied = dict(item)
                copied.setdefault("split", split)
                rows.append(copied)
        return rows
    return []


def build_stage1_validation_dataset(
    manifest_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gold_rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        gold_unit_to_intent = dict(row.get("gold_unit_to_intent", {}))
        if not gold_unit_to_intent:
            gold_unit_to_intent = {
                str(unit.get("unit_id")): str(unit.get("gold_intent_id"))
                for unit in row.get("edit_units", [])
                if unit.get("unit_id") is not None and unit.get("gold_intent_id") is not None
            }
        gold_rows.append(
            {
                "sample_id": row.get("sample_id"),
                "split": row.get("split"),
                "gold_count": int(row.get("gold_count", 0) or 0),
                "gold_unit_to_intent": gold_unit_to_intent,
                "gold_hunk_to_intent": dict(row.get("gold_hunk_to_intent", {})),
                "edit_units": list(row.get("edit_units", [])),
            }
        )
    normalized_predictions = [normalize_stage1_prediction_row(row) for row in (prediction_rows or [])]
    return {
        "row_count": len(gold_rows),
        "gold_rows": gold_rows,
        "prediction_rows": normalized_predictions,
        "prediction_count": len(normalized_predictions),
    }


def build_stage1_official_validation_plan(
    protocol_spec: dict[str, Any],
    metric_thresholds: dict[str, Any],
    manifest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "candidate_schedule": protocol_spec.get("candidate_schedule"),
        "threshold_status": metric_thresholds.get("threshold_status"),
        "sample_count": len(manifest_rows),
        "components": [
            "frozen_manifest_loader",
            "stage1_model_loader",
            "formal_asset_registry_gate",
            "stage1_eval_components",
            "attribution_metrics",
            "baseline_evaluator",
            "summary_writer",
        ],
        "official_validation_executed": False,
    }


def evaluate_stage1_predictions(
    gold_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    metric_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metric_spec = metric_spec or {}
    prediction_index = {str(row.get("sample_id")): row for row in prediction_rows}
    predicted_metrics: list[dict[str, Any]] = []
    oracle_metrics: list[dict[str, Any]] = []
    count_gold: list[int] = []
    count_pred: list[int] = []
    per_sample: list[dict[str, Any]] = []

    for row in gold_rows:
        sample_id = str(row.get("sample_id"))
        prediction = prediction_index.get(sample_id)
        if prediction is None:
            continue
        gold_map = dict(row.get("gold_unit_to_intent", {}))
        pred_map = dict(prediction.get("unit_to_slot", {}))
        gold_hunks = dict(row.get("gold_hunk_to_intent", {}))
        pred_hunks = _prediction_hunk_map(prediction, row)
        gold_labels, pred_labels = _label_lists(gold_map, pred_map)
        predicted = {
            "sample_id": sample_id,
            **pairwise_f1_from_assignments(gold_map, pred_map),
            **unit_accuracy_hungarian(gold_map, pred_map),
            **adjusted_rand_index(gold_labels, pred_labels),
            **normalized_mutual_info(gold_labels, pred_labels),
            **bcubed_f1(gold_labels, pred_labels),
            **hunk_micro_f1(gold_hunks, pred_hunks),
        }
        predicted_metrics.append(
            {
                "sample_id": sample_id,
                "pairwise_f1": predicted.get("pairwise_f1", 0.0),
                "ari": predicted.get("ari", 0.0),
                "nmi": predicted.get("nmi", 0.0),
                "bcubed_f1": predicted.get("bcubed_f1", 0.0),
                "unit_accuracy": predicted.get("unit_accuracy", 0.0),
                "hunk_micro_f1": predicted.get("hunk_micro_f1", 0.0),
            }
        )
        count_gold.append(int(row.get("gold_count", 0) or 0))
        count_pred.append(int(prediction.get("predicted_count", 0) or 0))
        sample_payload = {"sample_id": sample_id, "predicted_k_metrics": predicted}
        oracle_map = dict(prediction.get("oracle_unit_to_slot", {}))
        if metric_spec.get("report_oracle_k") and oracle_map:
            oracle_labels = _label_lists(gold_map, oracle_map)[1]
            oracle = {
                **pairwise_f1_from_assignments(gold_map, oracle_map),
                **unit_accuracy_hungarian(gold_map, oracle_map),
                **adjusted_rand_index(gold_labels, oracle_labels),
                **normalized_mutual_info(gold_labels, oracle_labels),
                **bcubed_f1(gold_labels, oracle_labels),
            }
            oracle_metrics.append(
                {
                    "sample_id": sample_id,
                    "pairwise_f1": oracle.get("pairwise_f1", 0.0),
                    "ari": oracle.get("ari", 0.0),
                    "nmi": oracle.get("nmi", 0.0),
                    "bcubed_f1": oracle.get("bcubed_f1", 0.0),
                    "unit_accuracy": oracle.get("unit_accuracy", 0.0),
                }
            )
            sample_payload["oracle_k_metrics"] = oracle
        else:
            sample_payload["oracle_k_metrics"] = {}
        per_sample.append(sample_payload)

    return {
        "sample_count": len(per_sample),
        "count_metrics": count_metrics(count_gold, count_pred),
        "predicted_k": aggregate_attribution_metrics(predicted_metrics),
        "oracle_k": aggregate_attribution_metrics(oracle_metrics),
        "rows": per_sample,
    }


def evaluate_stage1_with_baselines(
    gold_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    baseline_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del prediction_rows
    baseline_spec = baseline_spec or {}
    baselines = list(baseline_spec.get("baselines", []))
    if not baselines:
        return {"baselines": {}, "baseline_count": 0}
    predictions, summary = run_configured_baselines(gold_rows, baselines)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for prediction in predictions:
        grouped.setdefault(str(prediction["baseline"]), []).append(prediction)
    return {
        "baseline_count": len(grouped),
        "summary": summary,
        "baselines": grouped,
    }


def build_stage1_official_summary(
    *,
    dataset: dict[str, Any],
    prediction_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    official_validation_executed: bool = False,
    thresholds_applied_to_pass_fail: bool = False,
    completion_status: str = "not_executed",
    final_paper_ready: bool = False,
) -> dict[str, Any]:
    return {
        "official_validation_executed": bool(official_validation_executed),
        "thresholds_applied_to_pass_fail": bool(thresholds_applied_to_pass_fail),
        "completion_status": completion_status,
        "final_paper_ready": bool(final_paper_ready),
        "dataset_row_count": dataset.get("row_count", 0),
        "prediction_row_count": dataset.get("prediction_count", 0),
        "prediction_metrics": prediction_metrics,
        "baseline_metrics": baseline_metrics,
    }


def _label_lists(gold_map: dict[str, str], pred_map: dict[str, str]) -> tuple[list[str], list[str]]:
    unit_ids = sorted(set(gold_map) & set(pred_map))
    return [gold_map[unit_id] for unit_id in unit_ids], [pred_map[unit_id] for unit_id in unit_ids]


def _prediction_hunk_map(prediction: dict[str, Any], gold_row: dict[str, Any]) -> dict[str, str]:
    unit_to_slot = dict(prediction.get("unit_to_slot", {}))
    hunk_map: dict[str, str] = {}
    for unit in gold_row.get("edit_units", []):
        unit_id = str(unit.get("unit_id", ""))
        hunk_id = unit.get("hunk_id")
        if hunk_id is not None and unit_id in unit_to_slot:
            hunk_map[str(hunk_id)] = unit_to_slot[unit_id]
    return hunk_map
