from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.train.run_stage1_staged_curriculum import _fit_setting
from code.mica.train.train_stage1_sanity import _write_json, _write_jsonl
from code.mica.train.validate_stage1_t2_scaleup import (
    _prepare_scale,
    _setting_result,
    build_stage1_t2_scaleup_settings,
    scaleup_passes_thresholds,
)


CORE_SUMMARY_METRICS = [
    "k2_split_recall_mixed",
    "second_slot_gold_recall_mixed",
    "unit_accuracy_gain_over_all_one_mixed",
    "slot_collapse_rate_mixed",
    "count_accuracy_mixed",
    "over_split_rate_on_k1_mixed",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_comparison_scales(*, include_scale_b: bool = False) -> list[dict[str, Any]]:
    scales: list[dict[str, Any]] = []
    if include_scale_b:
        scales.append(
            {
                "scale_name": "scale_b_medium",
                "k1_train": 300,
                "k2_train": 300,
                "k1_dev": 75,
                "k2_dev": 75,
                "scale_c_downgraded": False,
                "downgrade_reason": None,
                "primary_judgment_scale": False,
            }
        )
    scales.append(
        {
            "scale_name": "scale_c_larger",
            "k1_train": 500,
            "k2_train": 500,
            "k1_dev": 125,
            "k2_dev": 125,
            "scale_c_downgraded": True,
            "downgrade_reason": "cpu validation cost; using accepted 500/500/125/125 Scale C setting",
            "primary_judgment_scale": True,
        }
    )
    return scales


def build_candidate_schedule_settings() -> list[dict[str, Any]]:
    return build_stage1_t2_scaleup_settings()


def candidate_passes_thresholds(row: dict[str, Any]) -> bool:
    return scaleup_passes_thresholds(row)


def _mean(values: list[float]) -> float:
    return float(sum(values) / max(len(values), 1))


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return float(math.sqrt(variance))


def _metric_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": _mean(values),
        "std": _std(values),
        "min": float(min(values)),
        "max": float(max(values)),
    }


def summarize_schedule_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    schedule_names = sorted({str(row["schedule_name"]) for row in runs})
    for schedule_name in schedule_names:
        schedule_rows = [row for row in runs if row["schedule_name"] == schedule_name]
        pass_count = sum(1 for row in schedule_rows if candidate_passes_thresholds(row))
        summary[schedule_name] = {
            "run_count": len(schedule_rows),
            "pass_count": pass_count,
            "pass_rate": float(pass_count / max(len(schedule_rows), 1)),
            "metrics": {
                metric: _metric_summary([float(row[metric]) for row in schedule_rows])
                for metric in CORE_SUMMARY_METRICS
            },
        }
    return summary


def _metric_mean(summary: dict[str, Any], schedule_name: str, metric: str) -> float:
    return float(summary.get(schedule_name, {}).get("metrics", {}).get(metric, {}).get("mean", 0.0))


def _metric_std(summary: dict[str, Any], schedule_name: str, metric: str) -> float:
    return float(summary.get(schedule_name, {}).get("metrics", {}).get(metric, {}).get("std", 0.0))


def choose_candidate_schedule(summary: dict[str, Any]) -> dict[str, Any]:
    naive = "naive_balanced_mixed"
    t2 = "T2_replay_protected_mixed"
    naive_pass_rate = float(summary.get(naive, {}).get("pass_rate", 0.0))
    t2_pass_rate = float(summary.get(t2, {}).get("pass_rate", 0.0))
    pass_threshold = 2.0 / 3.0

    naive_second = _metric_mean(summary, naive, "second_slot_gold_recall_mixed")
    t2_second = _metric_mean(summary, t2, "second_slot_gold_recall_mixed")
    naive_unit = _metric_mean(summary, naive, "unit_accuracy_gain_over_all_one_mixed")
    t2_unit = _metric_mean(summary, t2, "unit_accuracy_gain_over_all_one_mixed")
    naive_collapse = _metric_mean(summary, naive, "slot_collapse_rate_mixed")
    t2_collapse = _metric_mean(summary, t2, "slot_collapse_rate_mixed")

    naive_dominates = (
        naive_pass_rate >= pass_threshold
        and naive_second >= t2_second
        and naive_unit >= t2_unit
        and naive_collapse <= t2_collapse
    )
    t2_dominates = (
        t2_pass_rate >= pass_threshold
        and t2_second > naive_second
        and t2_unit > naive_unit
        and t2_collapse < naive_collapse
    )
    variance_high = any(
        _metric_std(summary, schedule_name, "second_slot_gold_recall_mixed") >= 0.15
        or _metric_std(summary, schedule_name, "slot_collapse_rate_mixed") >= 0.10
        for schedule_name in (naive, t2)
    )

    if naive_dominates and not variance_high:
        validated = "naive"
        next_step = "freeze naive larger-scale Stage 1 candidate protocol"
        reason = "naive pass rate and mean direct attribution metrics dominate T2"
    elif t2_dominates and not variance_high:
        validated = "T2"
        next_step = "freeze T2 candidate protocol"
        reason = "T2 pass rate and mean direct attribution metrics dominate naive"
    elif naive_pass_rate >= (1.0 / 3.0) or t2_pass_rate >= (1.0 / 3.0):
        validated = "unstable"
        next_step = "representation/assignment architecture revision, not later-stage escalation"
        reason = "both schedules show nonzero wins or high variance without clear dominance"
    else:
        validated = "none"
        next_step = "representation/assignment architecture revision, not later-stage escalation"
        reason = "both candidate schedules have low pass rate"

    return {
        "candidate_schedule_validated": validated,
        "next_step": next_step,
        "reason": reason,
        "naive_pass_rate": naive_pass_rate,
        "t2_pass_rate": t2_pass_rate,
        "naive_mean_second_slot_gold_recall": naive_second,
        "t2_mean_second_slot_gold_recall": t2_second,
        "naive_mean_unit_accuracy_gain": naive_unit,
        "t2_mean_unit_accuracy_gain": t2_unit,
        "naive_mean_slot_collapse_rate": naive_collapse,
        "t2_mean_slot_collapse_rate": t2_collapse,
        "seed_variance_high_enough_to_change_conclusion": variance_high,
        "freeze_candidate_formal_stage1_schedule": validated in {"naive", "T2"},
    }


def build_candidate_comparison_report(
    *,
    runs: list[dict[str, Any]],
    scale_audits: list[dict[str, Any]],
    seeds: list[int],
    seed_count_downgraded: bool,
    downgrade_reason: str | None,
    output_root: Path,
) -> dict[str, Any]:
    summary = summarize_schedule_runs(runs)
    judgment = choose_candidate_schedule(summary)
    return {
        "training_run": True,
        "sanity_only": True,
        "created_at_utc": _timestamp(),
        "core_question": "At larger Stage 1 medium scale, is naive balanced mixed training consistently better than T2 replay-protected mixed training, or was the Scale C result a seed/sample artifact?",
        "output_root_runtime_only": str(output_root),
        "seeds": list(seeds),
        "seed_count": len(seeds),
        "seed_count_downgraded": bool(seed_count_downgraded),
        "downgrade_reason": downgrade_reason,
        "uses_only_stage1_sources": True,
        "uses_forbidden_stage2_sources": False,
        "model_structure_changed": False,
        "main_objective": {
            "lambda_align": 1.0,
            "lambda_count": 0.5,
            "lambda_exist": 0.5,
            "note": "Only schedule and exposure differ between candidates.",
        },
        "scale_audits": scale_audits,
        "runs": runs,
        "schedule_summary": summary,
        "candidate_judgment": judgment,
    }


def _run_one_schedule(
    *,
    seed: int,
    scale: dict[str, Any],
    setting: dict[str, Any],
    train_samples: list[Any],
    dev_samples: list[Any],
    config: dict[str, Any],
    medium_candidate_count_available: int,
    output_root: Path,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    model, epoch_train_losses, training_log_rows, seen_counts = _fit_setting(
        config=config,
        setting=setting,
        train_samples=train_samples,
    )
    mixed_metrics = evaluate_model(
        model,
        dev_samples,
        batch_size=int(config["batch_size"]),
        device=str(config["device"]),
    )
    k2_only_dev = [sample for sample in dev_samples if sample.source_kind == "synthetic_k2"]
    k2_only_metrics = evaluate_model(
        model,
        k2_only_dev,
        batch_size=int(config["batch_size"]),
        device=str(config["device"]),
    )
    row = _setting_result(
        scale=scale,
        setting=setting,
        model=model,
        epoch_train_losses=epoch_train_losses,
        training_log_rows=training_log_rows,
        seen_counts=seen_counts,
        mixed_metrics=mixed_metrics,
        k2_only_metrics=k2_only_metrics,
        train_samples=train_samples,
        dev_samples=dev_samples,
        seed=seed,
    )
    row["schedule_name"] = str(setting["setting_name"])
    row["medium_candidate_count_available"] = int(medium_candidate_count_available)
    row["candidate_threshold_pass"] = candidate_passes_thresholds(row)
    row_prefix = f"{scale['scale_name']}_seed_{seed}_{setting['setting_name']}"
    _write_json(output_root / f"{row_prefix}_metrics.json", row)
    _write_jsonl(output_root / f"{row_prefix}_training_log.jsonl", training_log_rows)
    return row


def run_stage1_candidate_schedule_comparison(
    *,
    synthetic_jsonl: str,
    atomic_csv: str,
    output_root: str,
    reports_root: str = "reports",
    seeds: list[int] | None = None,
    include_scale_b: bool = False,
) -> dict[str, Any]:
    effective_seeds = list(seeds or [13, 42, 2026])
    seed_count_downgraded = len(effective_seeds) < 3
    downgrade_reason = "runtime-limited explicit seed list" if seed_count_downgraded else None
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    scale_audits: list[dict[str, Any]] = []

    for seed in effective_seeds:
        for scale in build_comparison_scales(include_scale_b=include_scale_b):
            train_samples, dev_samples, config, data_audit = _prepare_scale(
                scale=scale,
                atomic_csv=atomic_csv,
                synthetic_jsonl=synthetic_jsonl,
                output_root=output_root_path / f"seed_{seed}",
                seed=seed,
            )
            data_audit = dict(data_audit)
            data_audit["seed"] = int(seed)
            scale_audits.append(data_audit)
            for setting in build_candidate_schedule_settings():
                runs.append(
                    _run_one_schedule(
                        seed=seed,
                        scale=scale,
                        setting=setting,
                        train_samples=train_samples,
                        dev_samples=dev_samples,
                        config=config,
                        medium_candidate_count_available=int(data_audit["k2_candidate_count_available"]),
                        output_root=output_root_path,
                    )
                )

    payload = build_candidate_comparison_report(
        runs=runs,
        scale_audits=scale_audits,
        seeds=effective_seeds,
        seed_count_downgraded=seed_count_downgraded,
        downgrade_reason=downgrade_reason,
        output_root=output_root_path,
    )
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_candidate_schedule_comparison_result.json", payload)
    _write_markdown(reports_root_path / "mica_stage1_candidate_schedule_comparison_result.md", payload)
    return payload


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Candidate Schedule Comparison Result",
        "",
        f"- training_run: {str(payload['training_run']).lower()}",
        f"- sanity_only: {str(payload['sanity_only']).lower()}",
        f"- seeds: {payload['seeds']}",
        f"- seed_count_downgraded: {str(payload['seed_count_downgraded']).lower()}",
        f"- candidate_schedule_validated: {payload['candidate_judgment']['candidate_schedule_validated']}",
        f"- uses_only_stage1_sources: {str(payload['uses_only_stage1_sources']).lower()}",
        f"- uses_forbidden_stage2_sources: {str(payload['uses_forbidden_stage2_sources']).lower()}",
        f"- model_structure_changed: {str(payload['model_structure_changed']).lower()}",
        "",
        "## Results by Seed",
        "",
    ]
    for row in payload["runs"]:
        lines.extend(
            [
                f"### seed {row['seed']} / {row['scale_name']} / {row['schedule_name']}",
                "",
                f"- train_sample_count: {row['train_sample_count']}",
                f"- dev_sample_count: {row['dev_sample_count']}",
                f"- medium_candidate_count_available: {row['medium_candidate_count_available']}",
                f"- train_loss_first_epoch: {row['train_loss_first_epoch']:.6f}",
                f"- train_loss_last_epoch: {row['train_loss_last_epoch']:.6f}",
                f"- dev_loss_mixed: {row['dev_loss_mixed']:.6f}",
                f"- count_accuracy_mixed: {row['count_accuracy_mixed']:.6f}",
                f"- over_split_rate_on_k1_mixed: {row['over_split_rate_on_k1_mixed']:.6f}",
                f"- k2_split_recall_mixed: {row['k2_split_recall_mixed']:.6f}",
                f"- second_slot_gold_recall_mixed: {row['second_slot_gold_recall_mixed']:.6f}",
                f"- unit_accuracy_gain_over_all_one_mixed: {row['unit_accuracy_gain_over_all_one_mixed']:.6f}",
                f"- slot_collapse_rate_mixed: {row['slot_collapse_rate_mixed']:.6f}",
                f"- candidate_threshold_pass: {str(row['candidate_threshold_pass']).lower()}",
                "",
            ]
        )
    lines.extend(["## Multi-seed Summary", ""])
    for schedule_name, summary in payload["schedule_summary"].items():
        lines.extend(
            [
                f"### {schedule_name}",
                "",
                f"- run_count: {summary['run_count']}",
                f"- pass_count: {summary['pass_count']}",
                f"- pass_rate: {summary['pass_rate']:.6f}",
            ]
        )
        for metric, metric_summary in summary["metrics"].items():
            lines.append(
                f"- {metric}: mean={metric_summary['mean']:.6f}, std={metric_summary['std']:.6f}, min={metric_summary['min']:.6f}, max={metric_summary['max']:.6f}"
            )
        lines.append("")
    judgment = payload["candidate_judgment"]
    lines.extend(
        [
            "## Judgment",
            "",
            f"- candidate_schedule_validated: {judgment['candidate_schedule_validated']}",
            f"- reason: {judgment['reason']}",
            f"- naive_pass_rate: {judgment['naive_pass_rate']:.6f}",
            f"- t2_pass_rate: {judgment['t2_pass_rate']:.6f}",
            f"- naive_mean_second_slot_gold_recall: {judgment['naive_mean_second_slot_gold_recall']:.6f}",
            f"- t2_mean_second_slot_gold_recall: {judgment['t2_mean_second_slot_gold_recall']:.6f}",
            f"- naive_mean_unit_accuracy_gain: {judgment['naive_mean_unit_accuracy_gain']:.6f}",
            f"- t2_mean_unit_accuracy_gain: {judgment['t2_mean_unit_accuracy_gain']:.6f}",
            f"- naive_mean_slot_collapse_rate: {judgment['naive_mean_slot_collapse_rate']:.6f}",
            f"- t2_mean_slot_collapse_rate: {judgment['t2_mean_slot_collapse_rate']:.6f}",
            f"- seed_variance_high_enough_to_change_conclusion: {str(judgment['seed_variance_high_enough_to_change_conclusion']).lower()}",
            f"- freeze_candidate_formal_stage1_schedule: {str(judgment['freeze_candidate_formal_stage1_schedule']).lower()}",
            f"- next_step: {judgment['next_step']}",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare MICA Stage 1 candidate schedules across seeds.")
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", default="datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv")
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "outputs" / f"mica_stage1_candidate_schedule_comparison_{_timestamp()}"),
    )
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--seeds", nargs="+", type=int, default=[13, 42, 2026])
    parser.add_argument("--include-scale-b", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = run_stage1_candidate_schedule_comparison(
        synthetic_jsonl=args.synthetic_jsonl,
        atomic_csv=args.atomic_csv,
        output_root=args.output_root,
        reports_root=args.reports_root,
        seeds=args.seeds,
        include_scale_b=bool(args.include_scale_b),
    )
    print(
        json.dumps(
            {
                "report_json": str(Path(args.reports_root) / "mica_stage1_candidate_schedule_comparison_result.json"),
                "report_md": str(Path(args.reports_root) / "mica_stage1_candidate_schedule_comparison_result.md"),
                "candidate_schedule_validated": payload["candidate_judgment"]["candidate_schedule_validated"],
                "reason": payload["candidate_judgment"]["reason"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
