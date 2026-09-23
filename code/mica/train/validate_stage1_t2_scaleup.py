from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.data.schema import MicaSample
from code.mica.data.stage1_synthetic_structure import quantile, synthetic_k2_structure_features
from code.mica.models.mica_model import MicaModel
from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.train.run_stage1_staged_curriculum import (
    _copy_eval_metrics_with_suffix,
    _fit_setting,
    _mean,
    _slot_query_pairwise_cosine_mean,
    epoch_phase_for_setting,
)
from code.mica.train.train_stage1_sanity import (
    DEFAULT_CONFIG,
    _write_json,
    _write_jsonl,
    prepare_stage1_sanity_run,
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def build_stage1_t2_scaleup_scales(*, scale_c: str = "downgraded") -> list[dict[str, Any]]:
    scale_c_downgraded = scale_c != "preferred"
    scale_c_counts = (
        {"k1_train": 800, "k2_train": 800, "k1_dev": 200, "k2_dev": 200}
        if not scale_c_downgraded
        else {"k1_train": 500, "k2_train": 500, "k1_dev": 125, "k2_dev": 125}
    )
    return [
        {
            "scale_name": "scale_a_sanity_reference",
            "k1_train": 100,
            "k2_train": 100,
            "k1_dev": 25,
            "k2_dev": 25,
            "scale_c_downgraded": False,
            "downgrade_reason": None,
        },
        {
            "scale_name": "scale_b_medium",
            "k1_train": 300,
            "k2_train": 300,
            "k1_dev": 75,
            "k2_dev": 75,
            "scale_c_downgraded": False,
            "downgrade_reason": None,
        },
        {
            "scale_name": "scale_c_larger",
            **scale_c_counts,
            "scale_c_downgraded": scale_c_downgraded,
            "downgrade_reason": (
                "cpu validation cost; retained allowed 500/500/125/125 Scale C fallback"
                if scale_c_downgraded
                else None
            ),
        },
    ]


def build_stage1_t2_scaleup_settings() -> list[dict[str, Any]]:
    return [
        {
            "setting_name": "naive_balanced_mixed",
            "epochs": 15,
            "schedule_description": "Naive balanced k1/k2 mixed training from epoch 1; no replay.",
            "uses_replay": False,
            "uses_only_stage1_sources": True,
            "phases": [
                {
                    "epoch_count": 15,
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.5,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.5,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                }
            ],
        },
        {
            "setting_name": "T2_replay_protected_mixed",
            "epochs": 15,
            "schedule_description": "K2-only specialization for epochs 1-8, then mixed training with k2 replay protection.",
            "uses_replay": True,
            "uses_only_stage1_sources": True,
            "phases": [
                {
                    "epoch_count": 8,
                    "train_scope": "k2_only",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.2,
                    "lambda_count_end": 0.2,
                    "lambda_exist_start": 0.2,
                    "lambda_exist_end": 0.2,
                    "k2_to_k1_ratio": None,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
                {
                    "epoch_count": 7,
                    "train_scope": "mixed_with_replay",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.5,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.5,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.5,
                },
            ],
        },
    ]


def epoch_phase_for_scaleup_setting(setting: dict[str, Any], epoch_index: int) -> dict[str, Any]:
    return epoch_phase_for_setting(setting, epoch_index)


def scaleup_passes_thresholds(row: dict[str, Any]) -> bool:
    return (
        float(row["k2_split_recall_mixed"]) >= 0.50
        and float(row["second_slot_gold_recall_mixed"]) >= 0.40
        and float(row["unit_accuracy_gain_over_all_one_mixed"]) > 0.03
        and float(row["slot_collapse_rate_mixed"]) <= 0.45
        and float(row["count_accuracy_mixed"]) >= 0.55
        and float(row["over_split_rate_on_k1_mixed"]) <= 0.45
    )


def _medium_primary(features: dict[str, Any]) -> bool:
    return (
        bool(features["gold_intents_nonempty"])
        and int(features["edit_unit_count"]) >= 4
        and int(features["min_intent_units"]) >= 2
        and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
        and float(features["random_gold_k_pairwise_f1"]) <= 0.80
    )


def _selected_k2_features(samples: list[MicaSample]) -> list[dict[str, Any]]:
    return [synthetic_k2_structure_features(sample) for sample in samples if sample.source_kind == "synthetic_k2"]


def _data_audit_for_scale(
    *,
    scale: dict[str, Any],
    manifest_summary: dict[str, Any],
    train_samples: list[MicaSample],
    dev_samples: list[MicaSample],
    atomic_csv: str,
    synthetic_jsonl: str,
    seed: int,
) -> dict[str, Any]:
    selected_features = _selected_k2_features(train_samples + dev_samples)
    selected_unit_counts = [float(features["edit_unit_count"]) for features in selected_features]
    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=_resolve_path(atomic_csv),
        synthetic_jsonl_path=_resolve_path(synthetic_jsonl),
        split_seed=seed,
    )
    candidate_count = 0
    for sample in bundle.train + bundle.dev + bundle.test:
        if sample.source_kind != "synthetic_k2":
            continue
        if _medium_primary(synthetic_k2_structure_features(sample)):
            candidate_count += 1
    return {
        "scale_name": scale["scale_name"],
        "k1_train": int(scale["k1_train"]),
        "k2_train": int(scale["k2_train"]),
        "k1_dev": int(scale["k1_dev"]),
        "k2_dev": int(scale["k2_dev"]),
        "k2_candidate_count_available": int(candidate_count),
        "fallback_applied": bool(manifest_summary.get("fallback_applied", False)),
        "fallback_reason": list(manifest_summary.get("fallback_reason", [])),
        "singleton_intent_fraction": float(manifest_summary.get("singleton_intent_fraction", 0.0)),
        "file_path_baseline_mean": float(manifest_summary.get("file_path_baseline_mean", 0.0)),
        "random_gold_k_baseline_mean": float(manifest_summary.get("random_gold_k_baseline_mean", 0.0)),
        "avg_edit_units": float(manifest_summary.get("avg_edit_units", 0.0)),
        "p50_edit_units": float(quantile(selected_unit_counts, 0.50)),
        "p90_edit_units": float(quantile(selected_unit_counts, 0.90)),
        "scale_c_downgraded": bool(scale.get("scale_c_downgraded", False)),
        "downgrade_reason": scale.get("downgrade_reason"),
    }


def _phase_epoch_ranges(setting: dict[str, Any]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    start = 1
    for phase in setting["phases"]:
        end = start + int(phase["epoch_count"]) - 1
        ranges.append(
            {
                "start_epoch": start,
                "end_epoch": end,
                "train_scope": str(phase["train_scope"]),
                "lambda_align": float(phase["lambda_align"]),
                "lambda_count_start": float(phase["lambda_count_start"]),
                "lambda_count_end": float(phase["lambda_count_end"]),
                "lambda_exist_start": float(phase["lambda_exist_start"]),
                "lambda_exist_end": float(phase["lambda_exist_end"]),
                "k2_replay_ratio": float(phase.get("k2_replay_ratio", 0.0)),
            }
        )
        start = end + 1
    return ranges


def _setting_result(
    *,
    scale: dict[str, Any],
    setting: dict[str, Any],
    model: MicaModel,
    epoch_train_losses: list[float],
    training_log_rows: list[dict[str, Any]],
    seen_counts: dict[str, int],
    mixed_metrics: dict[str, Any],
    k2_only_metrics: dict[str, Any],
    train_samples: list[MicaSample],
    dev_samples: list[MicaSample],
    seed: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scale_name": str(scale["scale_name"]),
        "setting_name": str(setting["setting_name"]),
        "train_sample_count": len(train_samples),
        "dev_sample_count": len(dev_samples),
        "epochs": int(setting["epochs"]),
        "seed": int(seed),
        "schedule_description": str(setting["schedule_description"]),
        "phase_epoch_ranges": _phase_epoch_ranges(setting),
        "loss_weight_schedule": [
            {
                "epoch": int(row["epoch"]),
                "lambda_align": float(row["lambda_align"]),
                "lambda_count": float(row["lambda_count"]),
                "lambda_exist": float(row["lambda_exist"]),
            }
            for row in training_log_rows
        ],
        "coupling_schedule": [
            {
                "epoch": int(row["epoch"]),
                "enable_existence_mass_coupling": bool(row["enable_existence_mass_coupling"]),
                "enable_count_pb_coupling": bool(row["enable_count_pb_coupling"]),
                "coupling_scale": float(row["coupling_scale"]),
            }
            for row in training_log_rows
        ],
        "k2_replay_ratio": max(
            [
                float(row["k2_replay_sample_count"])
                / max(float(row["k1_seen_count"] + row["k2_seen_count"]), 1.0)
                for row in training_log_rows
            ]
            or [0.0]
        ),
        "k2_replay_sample_count": int(seen_counts["k2_replay_sample_count"]),
        "actual_k1_seen_count": int(seen_counts["k1_seen_count"]),
        "actual_k2_seen_count": int(seen_counts["k2_seen_count"]),
        "train_loss_first_epoch": float(epoch_train_losses[0]),
        "train_loss_last_epoch": float(epoch_train_losses[-1]),
        "slot_query_pairwise_cosine_mean": _slot_query_pairwise_cosine_mean(model),
        "gradient_norm_assignment_head_mean": _mean([float(row["assignment_head_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_slot_queries_mean": _mean([float(row["slot_query_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_encoder_mean": _mean([float(row["encoder_grad_norm"]) for row in training_log_rows]),
        "uses_only_stage1_sources": bool(setting["uses_only_stage1_sources"]),
        "uses_forbidden_stage2_sources": False,
    }
    result.update(_copy_eval_metrics_with_suffix(mixed_metrics, "mixed"))
    result.update(_copy_eval_metrics_with_suffix(k2_only_metrics, "k2_only"))
    result["scaleup_threshold_pass"] = scaleup_passes_thresholds(result)
    return result


def _comparison_by_scale(settings: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_scale: dict[str, dict[str, dict[str, Any]]] = {}
    for row in settings:
        by_scale.setdefault(str(row["scale_name"]), {})[str(row["setting_name"])] = row

    comparisons: dict[str, dict[str, float]] = {}
    for scale_name, rows in by_scale.items():
        naive = rows.get("naive_balanced_mixed")
        t2 = rows.get("T2_replay_protected_mixed")
        if not naive or not t2:
            continue
        comparisons[scale_name] = {
            "delta_k2_split_recall": float(t2["k2_split_recall_mixed"]) - float(naive["k2_split_recall_mixed"]),
            "delta_second_slot_gold_recall": float(t2["second_slot_gold_recall_mixed"])
            - float(naive["second_slot_gold_recall_mixed"]),
            "delta_unit_accuracy_gain_over_all_one": float(t2["unit_accuracy_gain_over_all_one_mixed"])
            - float(naive["unit_accuracy_gain_over_all_one_mixed"]),
            "delta_slot_collapse_rate": float(t2["slot_collapse_rate_mixed"]) - float(naive["slot_collapse_rate_mixed"]),
            "delta_count_accuracy": float(t2["count_accuracy_mixed"]) - float(naive["count_accuracy_mixed"]),
            "delta_over_split_rate_on_k1": float(t2["over_split_rate_on_k1_mixed"])
            - float(naive["over_split_rate_on_k1_mixed"]),
        }
    return comparisons


def _judgment(settings: list[dict[str, Any]], comparisons: dict[str, dict[str, float]]) -> dict[str, Any]:
    by_scale = {
        str(row["scale_name"]): row
        for row in settings
        if row["setting_name"] == "T2_replay_protected_mixed"
    }

    def _valid(scale_name: str) -> bool:
        row = by_scale.get(scale_name)
        comparison = comparisons.get(scale_name, {})
        return bool(
            row
            and scaleup_passes_thresholds(row)
            and float(comparison.get("delta_second_slot_gold_recall", 0.0)) > 0
            and float(comparison.get("delta_slot_collapse_rate", 0.0)) < 0
        )

    scale_b_valid = _valid("scale_b_medium")
    scale_c_valid = _valid("scale_c_larger")
    if scale_b_valid and scale_c_valid:
        status = "true"
        reason = "T2 passed Scale B and Scale C thresholds and improved over naive mixed."
        next_step = "freeze candidate formal Stage 1 schedule and run official Stage 1 protocol"
    elif scale_b_valid and not scale_c_valid:
        status = "partial"
        reason = "scale sensitivity"
        next_step = "tune representation or training capacity before formal freeze"
    else:
        status = "false"
        reason = "T2 did not pass required Scale B/C validation."
        next_step = "representation/architecture revision inside Stage 1, not later-stage data"
    return {
        "t2_scaleup_validated": status,
        "scale_b_valid": scale_b_valid,
        "scale_c_valid": scale_c_valid,
        "reason": reason,
        "next_step": next_step,
        "freeze_candidate_formal_stage1_schedule": status == "true",
    }


def build_scaleup_report(
    *,
    settings: list[dict[str, Any]],
    data_audits: list[dict[str, Any]],
    output_root: Path,
    seed: int,
) -> dict[str, Any]:
    comparisons = _comparison_by_scale(settings)
    judgment = _judgment(settings, comparisons)
    return {
        "training_run": True,
        "sanity_only": True,
        "created_at_utc": _timestamp(),
        "core_question": "Does T2 replay-protected mixed training remain effective when Stage 1 medium curriculum is scaled beyond the tiny 100/100 sanity setting?",
        "output_root_runtime_only": str(output_root),
        "seed": int(seed),
        "uses_only_stage1_sources": True,
        "uses_forbidden_stage2_sources": False,
        "main_objective": {
            "lambda_align": 1.0,
            "lambda_count": 0.5,
            "lambda_exist": 0.5,
            "note": "T2 warmup uses lower count/exist weights but does not add a new main loss.",
        },
        "data_audits": data_audits,
        "settings": settings,
        "t2_vs_naive_comparison": comparisons,
        "scaleup_judgment": judgment,
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 T2 Scale-up Result",
        "",
        f"- training_run: {str(payload['training_run']).lower()}",
        f"- sanity_only: {str(payload['sanity_only']).lower()}",
        f"- t2_scaleup_validated: {payload['scaleup_judgment']['t2_scaleup_validated']}",
        f"- uses_only_stage1_sources: {str(payload['uses_only_stage1_sources']).lower()}",
        f"- uses_forbidden_stage2_sources: {str(payload['uses_forbidden_stage2_sources']).lower()}",
        "",
        "## Data Audits",
        "",
    ]
    for audit in payload["data_audits"]:
        lines.extend(
            [
                f"### {audit['scale_name']}",
                "",
                f"- k1_train: {audit['k1_train']}",
                f"- k2_train: {audit['k2_train']}",
                f"- k1_dev: {audit['k1_dev']}",
                f"- k2_dev: {audit['k2_dev']}",
                f"- k2_candidate_count_available: {audit['k2_candidate_count_available']}",
                f"- fallback_applied: {str(audit['fallback_applied']).lower()}",
                f"- fallback_reason: {audit['fallback_reason']}",
                f"- singleton_intent_fraction: {audit['singleton_intent_fraction']:.6f}",
                f"- file_path_baseline_mean: {audit['file_path_baseline_mean']:.6f}",
                f"- random_gold_k_baseline_mean: {audit['random_gold_k_baseline_mean']:.6f}",
                f"- avg_edit_units: {audit['avg_edit_units']:.6f}",
                f"- p50_edit_units: {audit['p50_edit_units']:.6f}",
                f"- p90_edit_units: {audit['p90_edit_units']:.6f}",
                f"- scale_c_downgraded: {str(audit['scale_c_downgraded']).lower()}",
                f"- downgrade_reason: {audit['downgrade_reason']}",
                "",
            ]
        )
    lines.extend(["## Results", ""])
    for row in payload["settings"]:
        lines.extend(
            [
                f"### {row['scale_name']} / {row['setting_name']}",
                "",
                f"- epochs: {row['epochs']}",
                f"- train_sample_count: {row['train_sample_count']}",
                f"- dev_sample_count: {row['dev_sample_count']}",
                f"- train_loss_first_epoch: {row['train_loss_first_epoch']:.6f}",
                f"- train_loss_last_epoch: {row['train_loss_last_epoch']:.6f}",
                f"- dev_loss_mixed: {row['dev_loss_mixed']:.6f}",
                f"- dev_loss_k2_only: {row['dev_loss_k2_only']:.6f}",
                f"- count_accuracy_mixed: {row['count_accuracy_mixed']:.6f}",
                f"- over_split_rate_on_k1_mixed: {row['over_split_rate_on_k1_mixed']:.6f}",
                f"- k2_split_recall_mixed: {row['k2_split_recall_mixed']:.6f}",
                f"- second_slot_gold_recall_mixed: {row['second_slot_gold_recall_mixed']:.6f}",
                f"- unit_accuracy_gain_over_all_one_mixed: {row['unit_accuracy_gain_over_all_one_mixed']:.6f}",
                f"- slot_collapse_rate_mixed: {row['slot_collapse_rate_mixed']:.6f}",
                f"- scaleup_threshold_pass: {str(row['scaleup_threshold_pass']).lower()}",
                "",
            ]
        )
    lines.extend(["## T2 vs Naive", ""])
    for scale_name, comparison in payload["t2_vs_naive_comparison"].items():
        lines.extend(
            [
                f"### {scale_name}",
                "",
                f"- delta_k2_split_recall: {comparison['delta_k2_split_recall']:.6f}",
                f"- delta_second_slot_gold_recall: {comparison['delta_second_slot_gold_recall']:.6f}",
                f"- delta_unit_accuracy_gain_over_all_one: {comparison['delta_unit_accuracy_gain_over_all_one']:.6f}",
                f"- delta_slot_collapse_rate: {comparison['delta_slot_collapse_rate']:.6f}",
                f"- delta_count_accuracy: {comparison['delta_count_accuracy']:.6f}",
                f"- delta_over_split_rate_on_k1: {comparison['delta_over_split_rate_on_k1']:.6f}",
                "",
            ]
        )
    lines.extend(
        [
            "## Judgment",
            "",
            f"- t2_scaleup_validated: {payload['scaleup_judgment']['t2_scaleup_validated']}",
            f"- scale_b_valid: {str(payload['scaleup_judgment']['scale_b_valid']).lower()}",
            f"- scale_c_valid: {str(payload['scaleup_judgment']['scale_c_valid']).lower()}",
            f"- reason: {payload['scaleup_judgment']['reason']}",
            f"- next_step: {payload['scaleup_judgment']['next_step']}",
            f"- freeze_candidate_formal_stage1_schedule: {str(payload['scaleup_judgment']['freeze_candidate_formal_stage1_schedule']).lower()}",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_scale(
    *,
    scale: dict[str, Any],
    atomic_csv: str,
    synthetic_jsonl: str,
    output_root: Path,
    seed: int,
) -> tuple[list[MicaSample], list[MicaSample], dict[str, Any], dict[str, Any]]:
    manifest_root = output_root / "manifests" / str(scale["scale_name"])
    manifest_reports = output_root / "manifest_reports" / str(scale["scale_name"])
    manifests = build_stage1_curriculum_manifests(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=manifest_root,
        reports_root=manifest_reports,
        split_seed=seed,
        k1_train_count=int(scale["k1_train"]),
        k2_train_count=int(scale["k2_train"]),
        k1_dev_count=int(scale["k1_dev"]),
        k2_dev_count=int(scale["k2_dev"]),
    )
    medium_manifest = manifests["medium"]
    config = dict(DEFAULT_CONFIG, seed=seed, epochs=15, batch_size=8, device="cpu", Kmax=4)
    prepared = prepare_stage1_sanity_run(
        config,
        cli_manifest_json=medium_manifest["manifest_path"],
        cli_curriculum_level="medium",
        cli_atomic_csv=atomic_csv,
        cli_synthetic_jsonl=synthetic_jsonl,
        cli_output_root=str(output_root / "prepared" / str(scale["scale_name"])),
    )
    train_samples = list(prepared["train_samples"])
    dev_samples = list(prepared["dev_samples"])
    data_audit = _data_audit_for_scale(
        scale=scale,
        manifest_summary=dict(medium_manifest["summary"]),
        train_samples=train_samples,
        dev_samples=dev_samples,
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        seed=seed,
    )
    return train_samples, dev_samples, prepared["config"], data_audit


def run_stage1_t2_scaleup(
    *,
    synthetic_jsonl: str,
    atomic_csv: str,
    output_root: str,
    reports_root: str = "reports",
    seed: int = 42,
    scale_c: str = "downgraded",
) -> dict[str, Any]:
    torch.manual_seed(seed)
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    settings_payload: list[dict[str, Any]] = []
    data_audits: list[dict[str, Any]] = []

    for scale in build_stage1_t2_scaleup_scales(scale_c=scale_c):
        train_samples, dev_samples, config, data_audit = _prepare_scale(
            scale=scale,
            atomic_csv=atomic_csv,
            synthetic_jsonl=synthetic_jsonl,
            output_root=output_root_path,
            seed=seed,
        )
        data_audits.append(data_audit)
        k2_only_dev = [sample for sample in dev_samples if sample.source_kind == "synthetic_k2"]

        for setting in build_stage1_t2_scaleup_settings():
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
            settings_payload.append(row)
            row_prefix = f"{scale['scale_name']}_{setting['setting_name']}"
            _write_json(output_root_path / f"{row_prefix}_metrics.json", row)
            _write_jsonl(output_root_path / f"{row_prefix}_training_log.jsonl", training_log_rows)

    payload = build_scaleup_report(
        settings=settings_payload,
        data_audits=data_audits,
        output_root=output_root_path,
        seed=seed,
    )
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_t2_scaleup_result.json", payload)
    _write_markdown(reports_root_path / "mica_stage1_t2_scaleup_result.md", payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate MICA Stage 1 T2 replay-protected schedule at larger scales.")
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", default="datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv")
    parser.add_argument("--output-root", default=str(ROOT / "outputs" / f"mica_stage1_t2_scaleup_{_timestamp()}"))
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scale-c", choices=["preferred", "downgraded"], default="downgraded")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = run_stage1_t2_scaleup(
        synthetic_jsonl=args.synthetic_jsonl,
        atomic_csv=args.atomic_csv,
        output_root=args.output_root,
        reports_root=args.reports_root,
        seed=args.seed,
        scale_c=args.scale_c,
    )
    print(
        json.dumps(
            {
                "report_json": str(Path(args.reports_root) / "mica_stage1_t2_scaleup_result.json"),
                "report_md": str(Path(args.reports_root) / "mica_stage1_t2_scaleup_result.md"),
                "t2_scaleup_validated": payload["scaleup_judgment"]["t2_scaleup_validated"],
                "reason": payload["scaleup_judgment"]["reason"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
