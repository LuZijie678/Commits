from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.config_validation import validate_eval_spec
from code.mica.eval.ood_stress import aggregate_slice_metrics, build_ood_stress_report
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.reporting import write_markdown_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OOD stress eval dry-run runner.")
    parser.add_argument("--eval-spec", required=True)
    parser.add_argument("--rows-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_ood_stress_eval(
    *,
    eval_spec_path: str | Path,
    rows_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("OOD stress eval runner requires explicit --dry-run.")
    spec = {
        "final_test_eval_only": True,
        "no_threshold_tuning_on_final_test": True,
        **read_json(eval_spec_path),
    }
    validation = validate_eval_spec(spec)
    if validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    rows = read_jsonl(rows_jsonl)
    metric_keys = [str(item) for item in spec.get("metric_keys", ["pairwise_f1"])]
    slice_metrics = aggregate_slice_metrics(rows, metric_keys)
    report = build_ood_stress_report(slice_metrics)
    summary = {
        "dry_run": True,
        "thresholds_applied_to_pass_fail": False,
        "slice_report": report,
    }
    output_root_path = Path(output_root)
    write_json(output_root_path / "ood_stress_eval_summary.json", summary)
    write_markdown_report(
        output_root_path / "ood_stress_eval_summary.md",
        "OOD Stress Eval",
        {
            "Config": {"dry_run": True, "metric_keys": metric_keys},
            "Slices": report["slice_metrics"],
        },
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_ood_stress_eval(
        eval_spec_path=args.eval_spec,
        rows_jsonl=args.rows_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
