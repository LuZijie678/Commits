from __future__ import annotations

from pathlib import Path
from typing import Any

from code.mica.baselines.flat_classifier import fit_flat_classifier, run_flat_classifier_baseline
from code.mica.baselines.no_slot_decoder import run_no_slot_decoder_baseline
from code.mica.eval.attribution_metrics import (
    adjusted_rand_index,
    bcubed_f1,
    pairwise_f1_from_assignments,
    unit_accuracy_hungarian,
)
from code.mica.eval.baseline_metrics import (
    all_one_baseline,
    file_path_baseline,
    random_gold_k_baseline,
    size_heuristic_count_baseline,
)
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl


def load_manifest_rows(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
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
                if isinstance(item, dict):
                    copied = dict(item)
                    copied.setdefault("split", split)
                    rows.append(copied)
        return rows
    return []


def run_configured_baselines(rows: list[dict[str, Any]], baselines: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    baseline_context = _build_baseline_context(rows, baselines)
    for row in rows:
        for baseline_name in baselines:
            result = _dispatch_baseline(baseline_name, row, context=baseline_context.get(baseline_name))
            prediction_row = {"sample_id": row.get("sample_id"), "baseline": baseline_name, **result}
            predictions.append(prediction_row)
            if result.get("unit_to_slot"):
                gold_map = {
                    str(unit.get("unit_id")): str(unit.get("gold_intent_id"))
                    for unit in row.get("edit_units", [])
                    if unit.get("unit_id") is not None and unit.get("gold_intent_id") is not None
                }
                pred_map = {str(key): str(value) for key, value in result["unit_to_slot"].items()}
                if gold_map and pred_map:
                    gold_labels = [gold_map[unit_id] for unit_id in sorted(set(gold_map) & set(pred_map))]
                    pred_labels = [pred_map[unit_id] for unit_id in sorted(set(gold_map) & set(pred_map))]
                    metric_rows.append(
                        {
                            "sample_id": row.get("sample_id"),
                            "baseline": baseline_name,
                            "pairwise_f1": pairwise_f1_from_assignments(gold_map, pred_map)["pairwise_f1"],
                            "unit_accuracy": unit_accuracy_hungarian(gold_map, pred_map)["unit_accuracy"],
                            "ari": adjusted_rand_index(gold_labels, pred_labels)["ari"] if gold_labels else 0.0,
                            "bcubed_f1": bcubed_f1(gold_labels, pred_labels)["bcubed_f1"] if gold_labels else 0.0,
                        }
                    )
    summary = {
        "baseline_count": len(baselines),
        "prediction_row_count": len(predictions),
        "metric_row_count": len(metric_rows),
        "mean_pairwise_f1": _mean(metric_rows, "pairwise_f1"),
        "mean_unit_accuracy": _mean(metric_rows, "unit_accuracy"),
    }
    return predictions, summary


def write_baseline_outputs(
    *,
    output_root: str | Path,
    predictions: list[dict[str, Any]],
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_root_path = Path(output_root)
    write_jsonl(output_root_path / "stage1_baseline_predictions.jsonl", predictions)
    write_json(output_root_path / "stage1_baseline_summary.json", summary)
    write_json(output_root_path / "stage1_baselines_manifest.json", manifest)


def _dispatch_baseline(name: str, row: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    edit_units = list(row.get("edit_units", []))
    if name == "all_one":
        return all_one_baseline(edit_units)
    if name == "file_path":
        return file_path_baseline(edit_units)
    if name == "random_gold_k":
        return random_gold_k_baseline(edit_units, gold_k=int(row.get("gold_count", 1) or 1), seed=42)
    if name == "size_heuristic_count":
        return size_heuristic_count_baseline(edit_units)
    if name == "flat_classifier":
        fitted_model = (context or {}).get("model")
        return run_flat_classifier_baseline(row, model=fitted_model)
    if name == "no_slot_decoder":
        return run_no_slot_decoder_baseline(row, count_mode="gold_k" if row.get("gold_count") else "predicted_k")
    raise KeyError(f"Unsupported baseline: {name}")


def _build_baseline_context(rows: list[dict[str, Any]], baselines: list[str]) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    if "flat_classifier" in baselines:
        train_rows = [row for row in rows if str(row.get("split", "")).lower() == "train" and row.get("gold_count") is not None]
        if train_rows:
            context["flat_classifier"] = {"model": fit_flat_classifier(train_rows)}
    return context


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if key in row]
    return sum(values) / len(values) if values else 0.0
