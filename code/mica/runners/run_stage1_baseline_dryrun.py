from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.eval.attribution_metrics import pairwise_f1_from_assignments, unit_accuracy_hungarian
from code.mica.eval.baseline_metrics import (
    all_one_baseline,
    file_path_baseline,
    random_gold_k_baseline,
    size_heuristic_count_baseline,
)
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl


BASELINE_FUNCTIONS = {
    "all_one": all_one_baseline,
    "file_path": file_path_baseline,
    "random_gold_k": random_gold_k_baseline,
    "size_heuristic_count": size_heuristic_count_baseline,
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 deterministic baseline dry-run runner.")
    parser.add_argument("--baseline-spec", required=True)
    parser.add_argument("--edit-units-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_stage1_baseline_dryrun(
    *,
    baseline_spec_path: str | Path,
    edit_units_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("Stage 1 baseline dry-run requires explicit --dry-run.")

    baseline_spec = read_json(baseline_spec_path)
    rows = read_jsonl(edit_units_jsonl)
    predictions: list[dict[str, Any]] = []
    diagnostic_scores: list[dict[str, Any]] = []
    baselines = list(baseline_spec.get("baselines", []))

    for row in rows:
        sample_id = str(row["sample_id"])
        edit_units = list(row.get("edit_units", []))
        for baseline_name in baselines:
            baseline = _run_baseline(baseline_name, edit_units, row)
            predictions.append({"sample_id": sample_id, "baseline": baseline_name, **baseline})
            gold_map = {
                str(unit["unit_id"]): str(unit["gold_intent_id"])
                for unit in edit_units
                if unit.get("unit_id") is not None and unit.get("gold_intent_id") is not None
            }
            if gold_map:
                diagnostic_scores.append(
                    {
                        "sample_id": sample_id,
                        "baseline": baseline_name,
                        "pairwise_f1": pairwise_f1_from_assignments(gold_map, baseline["unit_to_slot"])["pairwise_f1"],
                        "unit_accuracy_hungarian": unit_accuracy_hungarian(gold_map, baseline["unit_to_slot"])["unit_accuracy"],
                    }
                )

    output_root_path = Path(output_root)
    write_jsonl(output_root_path / "baseline_predictions.jsonl", predictions)
    summary = {
        "baseline_count": len(baselines),
        "prediction_row_count": len(predictions),
        "metric_dryrun_executed": bool(diagnostic_scores),
        "pairwise_f1_mean": (
            sum(item["pairwise_f1"] for item in diagnostic_scores) / len(diagnostic_scores)
            if diagnostic_scores
            else 0.0
        ),
    }
    write_json(output_root_path / "stage1_baseline_dryrun_summary.json", summary)
    manifest = {
        "run_id": f"stage1_baseline_dryrun_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "stage": "stage1_baseline_dryrun",
        "dry_run": True,
        "training_enabled": False,
        "flat_classifier_trained": False,
        "no_slot_decoder_trained": False,
        "thresholds_applied_to_pass_fail": False,
    }
    write_json(output_root_path / "stage1_baseline_dryrun_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_baseline_dryrun(
        baseline_spec_path=args.baseline_spec,
        edit_units_jsonl=args.edit_units_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
    )
    return 0


def _run_baseline(baseline_name: str, edit_units: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    if baseline_name == "random_gold_k":
        return random_gold_k_baseline(edit_units, gold_k=int(row.get("gold_count", 1) or 1), seed=42)
    if baseline_name == "size_heuristic_count":
        return size_heuristic_count_baseline(edit_units, thresholds=None)
    return BASELINE_FUNCTIONS[baseline_name](edit_units)


if __name__ == "__main__":
    raise SystemExit(main())
