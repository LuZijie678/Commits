from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.config_validation import validate_eval_spec
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.experiment.report_schema import build_experiment_report_schema
from code.mica.eval.attribution_metrics import (
    adjusted_rand_index,
    aggregate_attribution_metrics,
    bcubed_f1,
    build_primary_alignment_maps,
    count_metrics,
    hunk_micro_f1,
    normalized_mutual_info,
    pairwise_f1_from_assignments,
    unit_accuracy_hungarian,
)
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.paper_tables.metric_registry import validate_eval_metrics_against_paper_tables
from code.mica.reporting import build_alignment_main_table, write_markdown_report
from code.mica.schema_validation import validate_eval_prediction_contract


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alignment eval report runner.")
    parser.add_argument("--eval-spec", required=True)
    parser.add_argument("--rows-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_alignment_eval(
    *,
    eval_spec_path: str | Path,
    rows_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("Alignment eval runner requires explicit --dry-run.")
    spec = read_json(eval_spec_path)
    validation = validate_eval_spec(spec)
    if validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    rows = read_jsonl(rows_jsonl)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_alignment_eval",
        config_paths=[str(eval_spec_path)],
        asset_registry_path=None,
        seed=0,
        mode="dry_run",
        advisor_approval=False,
    )
    summaries = []
    predicted_aggregate_rows = []
    oracle_aggregate_rows = []
    input_validations = [validate_eval_prediction_contract(row) for row in rows]
    for row in rows:
        alignment_maps = build_primary_alignment_maps(row)
        gold = alignment_maps["gold_unit_to_intent"]
        pred = alignment_maps["pred_unit_to_slot"]
        oracle = alignment_maps["oracle_unit_to_slot"]
        gold_hunks = alignment_maps["gold_hunk_to_intent"]
        pred_hunks = alignment_maps["pred_hunk_to_slot"]
        oracle_hunks = alignment_maps["oracle_hunk_to_slot"]
        gold_labels = [gold[unit_id] for unit_id in sorted(set(gold) & set(pred))]
        pred_labels = [pred[unit_id] for unit_id in sorted(set(gold) & set(pred))]
        oracle_labels = [oracle[unit_id] for unit_id in sorted(set(gold) & set(oracle))]
        row_summary = {
            "sample_id": row.get("sample_id"),
            "alignment_mask_protocol": alignment_maps["alignment_mask_protocol"],
            "excluded_alignment_unit_ids": alignment_maps["excluded_alignment_unit_ids"],
            "excluded_alignment_unit_count": alignment_maps["excluded_alignment_unit_count"],
            "count_metrics": count_metrics([int(row.get("gold_count", 0) or 0)], [int(row.get("pred_count", 0) or 0)]),
            "predicted_k_metrics": {
                **pairwise_f1_from_assignments(gold, pred),
                **unit_accuracy_hungarian(gold, pred),
                **adjusted_rand_index(gold_labels, pred_labels),
                **normalized_mutual_info(gold_labels, pred_labels),
                **bcubed_f1(gold_labels, pred_labels),
                **hunk_micro_f1(gold_hunks, pred_hunks),
            },
        }
        if oracle:
            row_summary["oracle_k_metrics"] = {
                **pairwise_f1_from_assignments(gold, oracle),
                **unit_accuracy_hungarian(gold, oracle),
                **adjusted_rand_index(gold_labels, oracle_labels),
                **normalized_mutual_info(gold_labels, oracle_labels),
                **bcubed_f1(gold_labels, oracle_labels),
            }
            if oracle_hunks:
                row_summary["oracle_k_metrics"].update(hunk_micro_f1(gold_hunks, oracle_hunks))
        else:
            row_summary["oracle_k_metrics"] = {}
        summaries.append(row_summary)
        predicted_aggregate_rows.append(
            {
                "sample_id": row.get("sample_id"),
                "model_name": str(row.get("model_name", "fixture")),
                "alignment_mode": "predicted_k",
                "count_exact": row_summary["count_metrics"].get("count_accuracy", 0.0),
                "count_mae": row_summary["count_metrics"].get("count_mae", 0.0),
                "pairwise_f1": row_summary["predicted_k_metrics"].get("pairwise_f1", 0.0),
                "ari": row_summary["predicted_k_metrics"].get("ari", 0.0),
                "nmi": row_summary["predicted_k_metrics"].get("nmi", 0.0),
                "bcubed_f1": row_summary["predicted_k_metrics"].get("bcubed_f1", 0.0),
                "unit_accuracy": row_summary["predicted_k_metrics"].get("unit_accuracy", 0.0),
                "hunk_micro_f1": row_summary["predicted_k_metrics"].get("hunk_micro_f1", 0.0),
                "over_segmentation_rate": float(int(row.get("pred_count", 0) or 0) > int(row.get("gold_count", 0) or 0)),
                "under_segmentation_rate": float(int(row.get("pred_count", 0) or 0) < int(row.get("gold_count", 0) or 0)),
            }
        )
        if row_summary["oracle_k_metrics"]:
            oracle_aggregate_rows.append(
                {
                    "sample_id": row.get("sample_id"),
                    "model_name": str(row.get("model_name", "fixture")),
                    "alignment_mode": "oracle_k",
                    "count_exact": 1.0,
                    "count_mae": 0.0,
                    "pairwise_f1": row_summary["oracle_k_metrics"].get("pairwise_f1", 0.0),
                    "ari": row_summary["oracle_k_metrics"].get("ari", 0.0),
                    "nmi": row_summary["oracle_k_metrics"].get("nmi", 0.0),
                    "bcubed_f1": row_summary["oracle_k_metrics"].get("bcubed_f1", 0.0),
                    "unit_accuracy": row_summary["oracle_k_metrics"].get("unit_accuracy", 0.0),
                    "hunk_micro_f1": row_summary["oracle_k_metrics"].get("hunk_micro_f1", 0.0),
                    "over_segmentation_rate": 0.0,
                    "under_segmentation_rate": 0.0,
                }
            )
    aggregate_rows = predicted_aggregate_rows + oracle_aggregate_rows
    predicted_aggregate = aggregate_attribution_metrics(predicted_aggregate_rows)
    oracle_aggregate = aggregate_attribution_metrics(oracle_aggregate_rows)
    predicted_metric_means = _mean_alignment_metrics(predicted_aggregate_rows)
    summary = {
        "dry_run": True,
        "thresholds_applied_to_pass_fail": False,
        "experiment_manifest": experiment_manifest,
        "input_validations": input_validations,
        "rows": summaries,
        "aggregate": predicted_aggregate,
        "aggregates": {
            "predicted_k": predicted_aggregate,
            "oracle_k": oracle_aggregate,
        },
        "oracle_predicted_k_separately_reported": True,
        "main_table": build_alignment_main_table(aggregate_rows),
        "metric_registry_validation": validate_eval_metrics_against_paper_tables(
            predicted_metric_means,
            "alignment_main",
        ),
        "report_schema": build_experiment_report_schema(
            stage="eval_alignment",
            metrics=predicted_metric_means,
            provenance={
                "git": {
                    "dirty": bool(experiment_manifest.get("dirty")),
                    "git_commit": experiment_manifest.get("git_commit"),
                },
                "runner_manifest": experiment_manifest,
            },
        ),
        "report_markdown_written": True,
    }
    output_root = Path(output_root)
    write_json(output_root / "alignment_eval_summary.json", summary)
    write_markdown_report(
        output_root / "alignment_eval_summary.md",
        "Alignment Eval",
        {
            "PredictedK": summary["aggregates"]["predicted_k"],
            "OracleK": summary["aggregates"]["oracle_k"],
            "Config": {"dry_run": True, "thresholds_applied_to_pass_fail": False},
        },
    )
    return summary


def _mean_alignment_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    keys = (
        "count_exact",
        "count_mae",
        "pairwise_f1",
        "ari",
        "nmi",
        "bcubed_f1",
        "hunk_micro_f1",
        "over_segmentation_rate",
        "under_segmentation_rate",
    )
    return {
        key: (sum(float(row.get(key, 0.0)) for row in rows) / len(rows)) if rows else 0.0
        for key in keys
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_alignment_eval(
        eval_spec_path=args.eval_spec,
        rows_jsonl=args.rows_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
