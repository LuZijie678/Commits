from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.eval.attribution_metrics import count_metrics, pairwise_f1_from_assignments, unit_accuracy_hungarian
from code.mica.eval.manifest_checks import (
    check_edit_units_compatibility,
    check_prediction_compatibility,
    check_stage1_manifest_compatibility,
)
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.runners.export_consumer_plans import export_consumer_plans
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 official validation dry-run report runner.")
    parser.add_argument("--protocol-spec", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--prediction-jsonl")
    parser.add_argument("--edit-units-jsonl")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export-consumer-plans", action="store_true")
    parser.add_argument("--consumer-plan-review-ready", action="store_true")
    return parser


def run_stage1_official_validation_dryrun(
    *,
    protocol_spec_path: str | Path,
    metric_thresholds_path: str | Path,
    manifest_path: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    prediction_jsonl: str | Path | None = None,
    edit_units_jsonl: str | Path | None = None,
    export_consumer_plans_artifact: bool = False,
    consumer_plan_review_ready: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("Stage 1 official validation dry-run requires explicit --dry-run.")
    if consumer_plan_review_ready:
        export_consumer_plans_artifact = True
    if export_consumer_plans_artifact and prediction_jsonl is None:
        raise ValueError("Stage 1 consumer plan export requires prediction_jsonl.")

    protocol_spec = read_json(protocol_spec_path)
    _ = read_json(metric_thresholds_path)
    manifest_rows = _load_manifest_rows(manifest_path)
    manifest_summary = check_stage1_manifest_compatibility(manifest_rows, protocol_spec)

    output_root_path = Path(output_root)
    consumer_plan_output_jsonl = output_root_path / "stage1_official_validation_dryrun_consumer_plans.jsonl"
    consumer_plan_error_jsonl = output_root_path / "stage1_official_validation_dryrun_consumer_plan_export_errors.jsonl"
    consumer_plan_summary_json = output_root_path / "stage1_official_validation_dryrun_consumer_plan_export_summary.json"
    prediction_summary = None
    edit_units_summary = None
    metric_summary = None
    consumer_plan_export_summary = None

    if prediction_jsonl is not None:
        prediction_rows = read_jsonl(prediction_jsonl)
        prediction_summary = check_prediction_compatibility(prediction_rows)
    else:
        prediction_rows = []
    if edit_units_jsonl is not None:
        edit_unit_rows = read_jsonl(edit_units_jsonl)
        edit_units_summary = check_edit_units_compatibility(edit_unit_rows)
    else:
        edit_unit_rows = []

    if prediction_rows:
        metric_summary = _metric_dryrun_summary(manifest_rows, prediction_rows, edit_unit_rows)
    if export_consumer_plans_artifact and prediction_jsonl is not None:
        consumer_plan_export_summary = export_consumer_plans(
            prediction_jsonl=prediction_jsonl,
            output_jsonl=consumer_plan_output_jsonl,
            error_jsonl=consumer_plan_error_jsonl,
            edit_units_jsonl_or_manifest=edit_units_jsonl,
            overwrite=True,
            strict=False,
            review_ready=consumer_plan_review_ready,
        )

    manifest = build_run_manifest(
        stage="stage1_official_validation_dryrun",
        mode="dry_run",
        output_root=str(output_root),
        flags={
            "dry_run": True,
            "official_validation_executed": False,
            "training_executed": False,
            "thresholds_applied_to_pass_fail": False,
            "stage2_allowed": False,
            "hard_b_loaded": False,
            "m_weak_loaded": False,
            "real_domain_split_loaded": False,
            "real_domain_selective_loaded": False,
        },
        inputs={
            "protocol_spec": protocol_spec_path,
            "metric_thresholds": metric_thresholds_path,
            "manifest": manifest_path,
            "prediction_jsonl": prediction_jsonl,
            "edit_units_jsonl": edit_units_jsonl,
            "export_consumer_plans": export_consumer_plans_artifact,
            "consumer_plan_review_ready": consumer_plan_review_ready,
        },
        metadata={
            "consumer_plan_export": {
                "requested": export_consumer_plans_artifact,
                "review_ready": consumer_plan_review_ready,
                "output_jsonl": consumer_plan_output_jsonl.name if export_consumer_plans_artifact else None,
                "error_jsonl": consumer_plan_error_jsonl.name if export_consumer_plans_artifact else None,
                "summary_json": consumer_plan_summary_json.name if export_consumer_plans_artifact else None,
                "summary": consumer_plan_export_summary,
            }
        },
    )
    assert_no_forbidden_training_flags(manifest)

    write_json(output_root_path / "stage1_validation_dryrun_manifest.json", manifest)
    write_json(output_root_path / "stage1_manifest_compatibility.json", manifest_summary)
    _write_markdown(output_root_path / "stage1_manifest_compatibility.md", manifest_summary)
    if prediction_summary is not None:
        write_json(output_root_path / "stage1_prediction_compatibility.json", prediction_summary)
    if edit_units_summary is not None:
        write_json(output_root_path / "stage1_edit_units_compatibility.json", edit_units_summary)
    if metric_summary is not None:
        write_json(output_root_path / "stage1_metric_dryrun_summary.json", metric_summary)
        _write_markdown(output_root_path / "stage1_metric_dryrun_summary.md", metric_summary)
    if consumer_plan_export_summary is not None:
        write_json(consumer_plan_summary_json, consumer_plan_export_summary)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_official_validation_dryrun(
        protocol_spec_path=args.protocol_spec,
        metric_thresholds_path=args.metric_thresholds,
        manifest_path=args.manifest,
        prediction_jsonl=args.prediction_jsonl,
        edit_units_jsonl=args.edit_units_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        export_consumer_plans_artifact=bool(args.export_consumer_plans),
        consumer_plan_review_ready=bool(args.consumer_plan_review_ready),
    )
    return 0


def _load_manifest_rows(path: str | Path) -> list[dict[str, Any]]:
    manifest_path = Path(path)
    if manifest_path.suffix.lower() == ".jsonl":
        return read_jsonl(manifest_path)
    payload = read_json(manifest_path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "splits" in payload:
        rows: list[dict[str, Any]] = []
        for split, items in payload["splits"].items():
            for item in items:
                copied = dict(item)
                copied.setdefault("split", split)
                rows.append(copied)
        return rows
    if isinstance(payload, dict) and "rows" in payload:
        return list(payload["rows"])
    return []


def _metric_dryrun_summary(
    manifest_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    edit_unit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest_by_sample = {str(row["sample_id"]): row for row in manifest_rows if row.get("sample_id") is not None}
    edit_units_by_sample = {str(row["sample_id"]): row for row in edit_unit_rows if row.get("sample_id") is not None}
    gold_counts: list[int] = []
    pred_counts: list[int] = []
    pairwise_scores: list[float] = []
    unit_accuracy_scores: list[float] = []

    for prediction in prediction_rows:
        sample_id = str(prediction.get("sample_id", ""))
        if sample_id in manifest_by_sample and prediction.get("predicted_count") is not None:
            gold_counts.append(int(manifest_by_sample[sample_id]["gold_count"]))
            pred_counts.append(int(prediction["predicted_count"]))
        if sample_id not in edit_units_by_sample:
            continue
        gold_map = {
            str(unit["unit_id"]): str(unit["gold_intent_id"])
            for unit in edit_units_by_sample[sample_id].get("edit_units", [])
            if unit.get("unit_id") is not None and unit.get("gold_intent_id") is not None
        }
        pred_map = {str(key): str(value) for key, value in dict(prediction.get("unit_to_slot", {})).items()}
        if gold_map and pred_map:
            pairwise_scores.append(pairwise_f1_from_assignments(gold_map, pred_map)["pairwise_f1"])
            unit_accuracy_scores.append(unit_accuracy_hungarian(gold_map, pred_map)["unit_accuracy"])

    summary = {
        "metric_dryrun_executed": True,
        "official_validation_executed": False,
        "training_executed": False,
        "thresholds_applied_to_pass_fail": False,
        "count_metrics": count_metrics(gold_counts, pred_counts),
        "mean_pairwise_f1": (sum(pairwise_scores) / len(pairwise_scores)) if pairwise_scores else 0.0,
        "mean_unit_accuracy_hungarian": (sum(unit_accuracy_scores) / len(unit_accuracy_scores)) if unit_accuracy_scores else 0.0,
    }
    return summary


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [f"# {path.stem}", ""]
    for key, value in payload.items():
        lines.append(f"- `{key}`: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
