from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.config_validation import validate_eval_spec
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.experiment.report_schema import build_experiment_report_schema
from code.mica.eval.real_domain_detection import (
    auprc,
    auroc,
    balanced_accuracy,
    binary_classification_metrics,
    expected_calibration_error,
    hard_b_fpr,
    m_recall,
    selective_metrics,
)
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.paper_tables.metric_registry import validate_eval_metrics_against_paper_tables
from code.mica.reporting import (
    build_real_domain_main_table,
    build_real_domain_selective_table,
    build_real_domain_split_table,
    write_markdown_report,
)
from code.mica.schema_validation import validate_eval_prediction_contract


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real-domain Split/Selective eval dry-run.")
    parser.add_argument("--eval-spec", required=True)
    parser.add_argument("--rows-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_real_domain_detection_eval(
    *,
    eval_spec_path: str | Path,
    rows_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("Real-domain detection eval runner requires explicit --dry-run.")
    spec = read_json(eval_spec_path)
    validation = validate_eval_spec(spec)
    if validation["errors"]:
        raise ValueError("; ".join(validation["errors"]))
    rows = read_jsonl(rows_jsonl)
    split_rows = [row for row in rows if _row_task(row) == "RealDomainSplit"]
    selective_rows = [row for row in rows if _row_task(row) == "RealDomainSelective"]
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_real_domain_detection_eval",
        config_paths=[str(eval_spec_path)],
        asset_registry_path=None,
        seed=0,
        mode="dry_run",
        advisor_approval=False,
    )
    input_validations = [_validate_row(row, index) for index, row in enumerate(rows)]
    split_metrics_row = _build_split_metrics_row(split_rows)
    split_table_row = _build_split_table_row(split_metrics_row)
    selective_table_row = _build_selective_table_row(selective_rows)
    split_metrics = {
        **binary_classification_metrics(
            [int(row.get("label", 0)) for row in split_rows],
            [float(row.get("score", 0.0)) for row in split_rows],
        ),
        **{key: split_metrics_row[key] for key in ("balanced_accuracy", "auroc", "auprc") if key in split_metrics_row},
    }
    split_table = build_real_domain_split_table([split_table_row])
    selective_table = build_real_domain_selective_table([selective_table_row])
    summary = {
        "dry_run": True,
        "experiment_manifest": experiment_manifest,
        "input_validations": input_validations,
        "metrics": split_metrics,
        "real_domain_split": {
            "row_count": len(split_rows),
            "metrics": split_table_row,
            "table": split_table,
            "metric_registry_validation": validate_eval_metrics_against_paper_tables(split_table_row, "real_domain_split"),
        },
        "real_domain_selective": {
            "row_count": len(selective_rows),
            "metrics": selective_table_row,
            "table": selective_table,
            "metric_registry_validation": validate_eval_metrics_against_paper_tables(selective_table_row, "real_domain_selective"),
            "thresholds_selected_on_final_test": False,
        },
        "ece": {key: split_metrics_row[key] for key in ("ece",) if key in split_metrics_row},
        "hard_b_fpr": {key: split_metrics_row[key] for key in ("hard_b_fpr",) if key in split_metrics_row},
        "m_recall": {key: split_metrics_row[key] for key in ("m_recall",) if key in split_metrics_row},
        "thresholds_applied_to_pass_fail": False,
        "main_table": build_real_domain_main_table([split_metrics_row]),
        "split_table": split_table,
        "selective_table": selective_table,
        "metric_registry_validation": {
            "real_domain_main": validate_eval_metrics_against_paper_tables(split_metrics_row, "real_domain_main"),
            "real_domain_split": validate_eval_metrics_against_paper_tables(split_table_row, "real_domain_split"),
            "real_domain_selective": validate_eval_metrics_against_paper_tables(selective_table_row, "real_domain_selective"),
        },
        "report_schema": build_experiment_report_schema(
            stage="eval_real_domain",
            metrics={
                "split_auroc": split_table_row.get("auroc", 0.0),
                "split_auprc": split_table_row.get("auprc", 0.0),
                "split_balanced_accuracy": split_table_row.get("balanced_accuracy", 0.0),
                "split_hard_b_fpr": split_table_row.get("hard_b_fpr", 0.0),
                "split_m_recall": split_metrics_row.get("m_recall", 0.0),
                "split_ece": split_table_row.get("ece", 0.0),
                "selective_coverage": selective_table_row.get("coverage", 0.0),
                "selective_risk_at_coverage": selective_table_row.get("risk_at_coverage", 0.0),
                "selective_aurc": selective_table_row.get("aurc", 0.0),
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
    write_json(output_root / "real_domain_detection_eval_summary.json", summary)
    write_markdown_report(
        output_root / "real_domain_detection_eval_summary.md",
        "Real Domain Detection Eval",
        {
            "Config": {"dry_run": True, "thresholds_applied_to_pass_fail": False},
            "RealDomainSplit": split_table_row,
            "RealDomainSelective": selective_table_row,
        },
    )
    return summary


def _row_task(row: dict[str, Any]) -> str:
    task = str(row.get("task") or row.get("eval_task") or "")
    if task in {"RealDomainSelective", "real_domain_selective"}:
        return "RealDomainSelective"
    if task in {"RealDomainSplit", "real_domain_split"}:
        return "RealDomainSplit"
    if any(key in row for key in ("in_scope_label", "risk_score", "abstained", "covered")):
        return "RealDomainSelective"
    return "RealDomainSplit"


def _validate_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    task = _row_task(row)
    sample_id = row.get("sample_id", f"row_{index}")
    if task == "RealDomainSelective":
        payload = {"sample_id": sample_id, "label": row.get("in_scope_label"), "score": row.get("risk_score")}
    else:
        payload = {"sample_id": sample_id, "label": row.get("label"), "score": row.get("score")}
    validation = validate_eval_prediction_contract(payload)
    validation["task"] = task
    return validation


def _build_split_metrics_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    y_true = [int(row.get("label", 0)) for row in rows]
    y_prob = [float(row.get("score", 0.0)) for row in rows]
    return {
        "model_name": "fixture",
        "split": "fixture",
        **balanced_accuracy(y_true, y_prob),
        **auroc(y_true, y_prob),
        **auprc(y_true, y_prob),
        **hard_b_fpr(y_true, y_prob),
        **m_recall(y_true, y_prob),
        **expected_calibration_error(y_true, y_prob),
    }


def _build_split_table_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_name": row["model_name"],
        "split": row["split"],
        "balanced_accuracy": row["balanced_accuracy"],
        "auroc": row["auroc"],
        "auprc": row["auprc"],
        "hard_b_fpr": row["hard_b_fpr"],
        "ece": row["ece"],
    }


def _build_selective_table_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    in_scope = [int(row.get("in_scope_label", row.get("label", 1))) for row in rows]
    risks = [float(row.get("risk_score", row.get("score", 0.0))) for row in rows]
    abstained = [
        _selective_reject_flag(row)
        for row in rows
    ]
    covered = [bool(row.get("covered", not rejected)) for row, rejected in zip(rows, abstained)]
    return {
        "model_name": "fixture",
        "split": "fixture",
        **selective_metrics(in_scope=in_scope, risk_scores=risks, covered=covered, abstained=abstained),
        "threshold_protocol": "use_explicit_dev_frozen_abstained_or_covered_flags",
        "implicit_risk_threshold_used": False,
    }


def _selective_reject_flag(row: dict[str, Any]) -> bool:
    if "abstained" in row:
        return bool(row["abstained"])
    if "covered" in row:
        return not bool(row["covered"])
    raise ValueError("RealDomainSelective rows require explicit dev-frozen `abstained` or `covered` flags.")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_real_domain_detection_eval(
        eval_spec_path=args.eval_spec,
        rows_jsonl=args.rows_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
