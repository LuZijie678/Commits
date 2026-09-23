from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.config_validation import validate_eval_spec
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.experiment.report_schema import build_experiment_report_schema
from code.mica.eval.message_utility import (
    build_renderer_ablation_summary,
    compare_oracle_vs_predicted_rendering,
    extra_intent_rate,
    hallucination_proxy,
    intent_coverage,
    missing_intent_rate,
    specificity_proxy,
)
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.paper_tables.metric_registry import validate_eval_metrics_against_paper_tables
from code.mica.reporting import build_message_utility_table, write_markdown_report
from code.mica.schema_validation import validate_renderer_input_contract


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Message utility eval for oracle, predicted, and direct-diff renderers.")
    parser.add_argument("--eval-spec", required=True)
    parser.add_argument("--rows-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_message_utility_eval(
    *,
    eval_spec_path: str | Path,
    rows_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("Message utility eval runner requires explicit --dry-run.")
    spec = read_json(eval_spec_path)
    validation = validate_eval_spec(spec)
    if validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    rows = read_jsonl(rows_jsonl)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_message_utility_eval",
        config_paths=[str(eval_spec_path)],
        asset_registry_path=None,
        seed=0,
        mode="dry_run",
        advisor_approval=False,
    )
    coverage_rows = []
    input_validations = [validate_renderer_input_contract(row) for row in rows]
    for row in rows:
        coverage = intent_coverage(dict(row.get("structured_intent_plan", {})), str(row.get("message", "")))
        hallucination = hallucination_proxy(str(row.get("message", "")), list(row.get("evidence_terms", [])))
        specificity = specificity_proxy(str(row.get("message", "")), list(row.get("evidence_terms", [])))
        coverage_rows.append(
            {
                "model_name": str(row.get("model_name", "fixture")),
                "rendering_mode": _rendering_mode(row),
                "sample_id": str(row.get("sample_id", "")),
                "intent_coverage": float(coverage.get("covered_intent_fraction", 0.0)),
                "missing_intent_rate": 1.0 - float(coverage.get("covered_intent_fraction", 0.0)),
                "extra_intent_rate": float(row.get("extra_intent_fraction", 0.0)),
                "hallucination_proxy": float(hallucination.get("unsupported_term_fraction", 0.0)),
                "faithfulness_proxy": 1.0 - float(hallucination.get("unsupported_term_fraction", 0.0)),
                "specificity_proxy": float(specificity.get("specificity_proxy", 0.0)),
                "proxy_not_human_eval": True,
                **coverage,
                **hallucination,
                **specificity,
            }
        )
    grouped_rows = _group_rows_by_mode(coverage_rows)
    mode_summaries = {mode: _message_utility_summary(mode_rows) for mode, mode_rows in grouped_rows.items()}
    oracle_vs_predicted = compare_oracle_vs_predicted_rendering(
        grouped_rows.get("oracle_slots", []),
        grouped_rows.get("predicted_slots", []),
    )
    summary = {
        "dry_run": True,
        "proxy_not_human_eval": True,
        "experiment_manifest": experiment_manifest,
        "input_validations": input_validations,
        "coverage_rows": coverage_rows,
        "mode_summaries": mode_summaries,
        "oracle_vs_predicted_rendering": oracle_vs_predicted,
        "message_utility_modes_separately_reported": True,
        "missing_intent_rate": missing_intent_rate(coverage_rows),
        "extra_intent_rate": extra_intent_rate(coverage_rows),
        "specificity_proxy_mean": (sum(float(row.get("specificity_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
        "main_table": build_message_utility_table(coverage_rows),
        "metric_registry_validation": validate_eval_metrics_against_paper_tables(
            {
                "intent_coverage": (sum(float(row.get("intent_coverage", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "missing_intent_rate": missing_intent_rate(coverage_rows)["missing_intent_rate"],
                "extra_intent_rate": extra_intent_rate(coverage_rows)["extra_intent_rate"],
                "hallucination_proxy": (sum(float(row.get("hallucination_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "faithfulness_proxy": (sum(float(row.get("faithfulness_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "specificity_proxy": (sum(float(row.get("specificity_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "proxy_not_human_eval": True,
            },
            "message_utility_main",
        ),
        "report_schema": build_experiment_report_schema(
            stage="eval_message_utility",
            metrics={
                "intent_coverage": (sum(float(row.get("intent_coverage", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "missing_intent_rate": missing_intent_rate(coverage_rows)["missing_intent_rate"],
                "extra_intent_rate": extra_intent_rate(coverage_rows)["extra_intent_rate"],
                "hallucination_proxy": (sum(float(row.get("hallucination_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "faithfulness_proxy": (sum(float(row.get("faithfulness_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "specificity_proxy": (sum(float(row.get("specificity_proxy", 0.0)) for row in coverage_rows) / len(coverage_rows)) if coverage_rows else 0.0,
                "proxy_not_human_eval": True,
            },
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
    write_json(output_root / "message_utility_eval_summary.json", summary)
    write_markdown_report(
        output_root / "message_utility_eval_summary.md",
        "Message Utility Eval",
        {
            "Modes": summary["mode_summaries"],
            "OracleVsPredicted": summary["oracle_vs_predicted_rendering"],
        },
    )
    return summary


def _rendering_mode(row: dict[str, Any]) -> str:
    raw = str(row.get("rendering_mode") or row.get("renderer_mode") or row.get("mode") or "").strip()
    aliases = {
        "oracle": "oracle_slots",
        "oracle_slot": "oracle_slots",
        "oracle_slots": "oracle_slots",
        "oracle_plan": "oracle_slots",
        "predicted": "predicted_slots",
        "predicted_slot": "predicted_slots",
        "predicted_slots": "predicted_slots",
        "predicted_plan": "predicted_slots",
        "direct": "direct_diff",
        "direct_diff": "direct_diff",
        "direct_diff_message": "direct_diff",
    }
    if raw in aliases:
        return aliases[raw]
    plan_source = str(row.get("structured_intent_plan", {}).get("source", ""))
    if plan_source in aliases:
        return aliases[plan_source]
    return "predicted_slots"


def _group_rows_by_mode(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("rendering_mode", "predicted_slots")), []).append(row)
    return grouped


def _message_utility_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return build_renderer_ablation_summary(rows)
    return {
        **build_renderer_ablation_summary(rows),
        **missing_intent_rate(rows),
        **extra_intent_rate(rows),
        "specificity_proxy_mean": sum(float(row.get("specificity_proxy", 0.0)) for row in rows) / len(rows),
        "faithfulness_proxy_mean": sum(float(row.get("faithfulness_proxy", 0.0)) for row in rows) / len(rows),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_message_utility_eval(
        eval_spec_path=args.eval_spec,
        rows_jsonl=args.rows_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
