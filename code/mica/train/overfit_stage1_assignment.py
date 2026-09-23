from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.train.train_stage1_sanity import (
    DEFAULT_CONFIG,
    _write_json,
    fit_stage1_sanity_model,
    prepare_stage1_sanity_run,
)
from code.mica.train.eval_stage1_sanity import evaluate_model


def _default_settings() -> list[dict[str, Any]]:
    return [
        {
            "setting_name": "A_20_k2_only",
            "k2_count": 20,
            "k1_count": 0,
            "epochs": 30,
            "batch_size": 4,
            "learning_rate": 1e-3,
            "device": "cpu",
            "seed": 42,
            "align_only": False,
        },
        {
            "setting_name": "B_50_k2_only",
            "k2_count": 50,
            "k1_count": 0,
            "epochs": 30,
            "batch_size": 4,
            "learning_rate": 1e-3,
            "device": "cpu",
            "seed": 42,
            "align_only": False,
        },
        {
            "setting_name": "C_50_k2_plus_50_k1",
            "k2_count": 50,
            "k1_count": 50,
            "epochs": 30,
            "batch_size": 4,
            "learning_rate": 1e-3,
            "device": "cpu",
            "seed": 42,
            "align_only": False,
        },
        {
            "setting_name": "D_20_k2_align_only",
            "k2_count": 20,
            "k1_count": 0,
            "epochs": 30,
            "batch_size": 4,
            "learning_rate": 1e-3,
            "device": "cpu",
            "seed": 42,
            "align_only": True,
        },
    ]


def _select_overfit_train_samples(train_samples: list[Any], *, k1_count: int, k2_count: int) -> list[Any]:
    k1_samples = [sample for sample in train_samples if sample.source_kind == "atomic_k1"][:k1_count]
    k2_samples = [sample for sample in train_samples if sample.source_kind == "synthetic_k2"][:k2_count]
    selected = k2_samples + k1_samples
    if len(k1_samples) < k1_count or len(k2_samples) < k2_count:
        raise ValueError(
            f"insufficient manifest train samples for overfit selection: requested k1={k1_count}, k2={k2_count}, got k1={len(k1_samples)}, k2={len(k2_samples)}"
        )
    return selected


def _judge_overfit(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if float(metrics["unit_accuracy_hungarian_train"]) < 0.85:
        reasons.append("unit_accuracy_below_threshold")
    if float(metrics["macro_intent_f1_hungarian_train"]) < 0.80:
        reasons.append("macro_intent_f1_below_threshold")
    if float(metrics["k2_split_recall_train"]) < 0.80:
        reasons.append("k2_split_recall_below_threshold")
    if float(metrics["second_slot_gold_recall_train"]) < 0.70:
        reasons.append("second_slot_gold_recall_below_threshold")
    if float(metrics["slot_collapse_rate_train"]) > 0.30:
        reasons.append("slot_collapse_rate_above_threshold")
    return len(reasons) == 0, reasons


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Assignment Overfit Result",
        "",
        f"- training_run: {str(payload['training_run']).lower()}",
        f"- uses_only_stage1_sources: {str(payload['uses_only_stage1_sources']).lower()}",
        f"- uses_hard_b_or_m: {str(payload['uses_hard_b_or_m']).lower()}",
        "",
    ]
    for item in payload["settings"]:
        lines.extend(
            [
                f"## {item['setting_name']}",
                "",
                f"- overfit_passed: {str(item['overfit_passed']).lower()}",
                f"- align_only: {str(item['align_only']).lower()}",
                f"- train_sample_count: {item['train_sample_count']}",
                f"- k1_count: {item['k1_count']}",
                f"- k2_count: {item['k2_count']}",
                f"- train_loss_first_epoch: {item['train_loss_first_epoch']:.6f}",
                f"- train_loss_last_epoch: {item['train_loss_last_epoch']:.6f}",
                f"- count_accuracy_train: {item['count_accuracy_train']:.6f}",
                f"- unit_accuracy_hungarian_train: {item['unit_accuracy_hungarian_train']:.6f}",
                f"- macro_intent_f1_hungarian_train: {item['macro_intent_f1_hungarian_train']:.6f}",
                f"- k2_split_recall_train: {item['k2_split_recall_train']:.6f}",
                f"- second_slot_gold_recall_train: {item['second_slot_gold_recall_train']:.6f}",
                f"- second_slot_assignment_mass_train: {item['second_slot_assignment_mass_train']:.6f}",
                f"- effective_slot_count_mean_train: {item['effective_slot_count_mean_train']:.6f}",
                f"- slot_collapse_rate_train: {item['slot_collapse_rate_train']:.6f}",
                f"- assignment_entropy_train: {item['assignment_entropy_train']:.6f}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage1_assignment_overfit(
    *,
    manifest_json: str,
    atomic_csv: str,
    synthetic_jsonl: str,
    output_root: str,
    reports_root: str,
    settings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prepared = prepare_stage1_sanity_run(
        dict(DEFAULT_CONFIG),
        cli_manifest_json=manifest_json,
        cli_curriculum_level="medium",
        cli_atomic_csv=atomic_csv,
        cli_synthetic_jsonl=synthetic_jsonl,
        cli_output_root=output_root,
    )
    manifest_train_samples = prepared["train_samples"]
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for setting in (settings or _default_settings()):
        selected_train = _select_overfit_train_samples(
            manifest_train_samples,
            k1_count=int(setting["k1_count"]),
            k2_count=int(setting["k2_count"]),
        )
        config = dict(DEFAULT_CONFIG)
        config.update(
            {
                "epochs": int(setting["epochs"]),
                "batch_size": int(setting["batch_size"]),
                "learning_rate": float(setting["learning_rate"]),
                "device": str(setting["device"]),
                "seed": int(setting["seed"]),
                "lambda_count": 0.0 if bool(setting.get("align_only")) else DEFAULT_CONFIG["lambda_count"],
                "lambda_exist": 0.0 if bool(setting.get("align_only")) else DEFAULT_CONFIG["lambda_exist"],
            }
        )
        model, epoch_train_losses, training_log_rows = fit_stage1_sanity_model(config, selected_train)
        metrics = evaluate_model(model, selected_train, batch_size=int(setting["batch_size"]), device=str(setting["device"]))
        overfit_passed, fail_reasons = _judge_overfit(
            {
                "unit_accuracy_hungarian_train": metrics["unit_accuracy_hungarian"],
                "macro_intent_f1_hungarian_train": metrics["macro_intent_f1_hungarian"],
                "k2_split_recall_train": metrics["k2_split_recall"],
                "second_slot_gold_recall_train": metrics["second_slot_gold_recall"],
                "slot_collapse_rate_train": metrics["slot_collapse_rate"],
            }
        )
        result_row = {
            "setting_name": str(setting["setting_name"]),
            "train_sample_count": len(selected_train),
            "k1_count": sum(1 for sample in selected_train if sample.source_kind == "atomic_k1"),
            "k2_count": sum(1 for sample in selected_train if sample.source_kind == "synthetic_k2"),
            "align_only": bool(setting.get("align_only", False)),
            "train_loss_first_epoch": float(epoch_train_losses[0]),
            "train_loss_last_epoch": float(epoch_train_losses[-1]),
            "count_accuracy_train": float(metrics["count_accuracy"]),
            "unit_accuracy_hungarian_train": float(metrics["unit_accuracy_hungarian"]),
            "macro_intent_f1_hungarian_train": float(metrics["macro_intent_f1_hungarian"]),
            "k2_split_recall_train": float(metrics["k2_split_recall"]),
            "second_slot_gold_recall_train": float(metrics["second_slot_gold_recall"]),
            "second_slot_assignment_mass_train": float(metrics["second_slot_assignment_mass"]),
            "effective_slot_count_mean_train": float(metrics["effective_slot_count_mean"]),
            "slot_collapse_rate_train": float(metrics["slot_collapse_rate"]),
            "assignment_entropy_train": float(metrics["assignment_entropy"]),
            "assignment_head_grad_norm_last_epoch": float(training_log_rows[-1]["assignment_head_grad_norm"]) if training_log_rows else 0.0,
            "slot_query_grad_norm_last_epoch": float(training_log_rows[-1]["slot_query_grad_norm"]) if training_log_rows else 0.0,
            "encoder_grad_norm_last_epoch": float(training_log_rows[-1]["encoder_grad_norm"]) if training_log_rows else 0.0,
            "overfit_passed": bool(overfit_passed),
            "fail_reasons": fail_reasons,
        }
        results.append(result_row)
        _write_json(output_root_path / f"{setting['setting_name']}_metrics.json", result_row)

    payload = {
        "training_run": True,
        "sanity_only": True,
        "uses_only_stage1_sources": True,
        "uses_hard_b_or_m": False,
        "settings": results,
        "any_overfit_passed": any(item["overfit_passed"] for item in results),
    }
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_assignment_overfit_result.json", payload)
    _write_markdown(reports_root_path / "mica_stage1_assignment_overfit_result.md", payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MICA Stage 1 assignment overfit diagnostics.")
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = run_stage1_assignment_overfit(
        manifest_json=args.manifest_json,
        atomic_csv=args.atomic_csv,
        synthetic_jsonl=args.synthetic_jsonl,
        output_root=args.output_root,
        reports_root=args.reports_root,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
