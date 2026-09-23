from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM, collate_mica_samples
from code.mica.data.schema import MicaSample
from code.mica.losses.mica_losses import compute_stage1_losses
from code.mica.models.mica_model import MicaModel, MicaOutput
from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.train.train_stage1_sanity import (
    DEFAULT_CONFIG,
    _batched,
    _parameter_grad_norm,
    _write_json,
    _write_jsonl,
    assignment_temperature_for_epoch,
    prepare_stage1_sanity_run,
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_stage1_staged_curriculum_settings() -> list[dict[str, Any]]:
    return [
        {
            "setting_name": "T0_k2_only_reference",
            "epochs": 10,
            "schedule_description": "K2-only attribution upper reference; not a final mixed Stage 1 protocol.",
            "phases": [
                {
                    "epoch_count": 10,
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
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "T1_long_k2_specialization_then_gentle_k1_reintroduction",
            "epochs": 15,
            "schedule_description": "Long k2-only specialization, then 3:1 and 1:1 reintroduction with gentle coupling.",
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
                    "enable_existence_mass_coupling": False,
                    "enable_count_pb_coupling": False,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
                {
                    "epoch_count": 4,
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.3,
                    "lambda_count_end": 0.3,
                    "lambda_exist_start": 0.3,
                    "lambda_exist_end": 0.3,
                    "k2_to_k1_ratio": [3, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "coupling_scale": 0.5,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
                {
                    "epoch_count": 3,
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.5,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.5,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "coupling_scale": 0.5,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "T2_k2_specialization_with_replay_protected_mixed_training",
            "epochs": 15,
            "schedule_description": "K2-only specialization followed by mixed training with fixed k2 replay batches.",
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
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "T3_align_preserving_mixed_training",
            "epochs": 15,
            "schedule_description": "Align-only k2 warmup, then mixed training with gradual count/exist warmup.",
            "phases": [
                {
                    "epoch_count": 6,
                    "train_scope": "k2_only",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.0,
                    "lambda_count_end": 0.0,
                    "lambda_exist_start": 0.0,
                    "lambda_exist_end": 0.0,
                    "k2_to_k1_ratio": None,
                    "enable_existence_mass_coupling": False,
                    "enable_count_pb_coupling": False,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
                {
                    "epoch_count": 9,
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.2,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.2,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "coupling_scale": 0.5,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "T4_freeze_slot_queries_after_k2_specialization",
            "epochs": 15,
            "schedule_description": "Freeze slot queries during mixed reintroduction to protect specialized foreground slots.",
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
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.5,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.5,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                    "freeze_slot_queries": True,
                    "k2_replay_ratio": 0.0,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "T5_disable_deterministic_coupling_during_reintroduction",
            "epochs": 15,
            "schedule_description": "Disable deterministic coupling during mixed k1 reintroduction.",
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
                    "train_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count_start": 0.5,
                    "lambda_count_end": 0.5,
                    "lambda_exist_start": 0.5,
                    "lambda_exist_end": 0.5,
                    "k2_to_k1_ratio": [1, 1],
                    "enable_existence_mass_coupling": False,
                    "enable_count_pb_coupling": False,
                    "freeze_slot_queries": False,
                    "k2_replay_ratio": 0.0,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
    ]


def _resolve_or_rebuild_medium_manifest(
    *,
    curriculum_manifest: str,
    atomic_csv: str,
    synthetic_jsonl: str,
    output_root: Path,
) -> dict[str, Any]:
    manifest_path = Path(curriculum_manifest)
    resolved_manifest_path = manifest_path if manifest_path.is_absolute() else (ROOT / manifest_path).resolve()
    if resolved_manifest_path.exists():
        payload = json.loads(resolved_manifest_path.read_text(encoding="utf-8"))
        return {
            "manifest_path": str(resolved_manifest_path),
            "manifest_summary": dict(payload.get("summary", {})),
            "manifest_rebuilt": False,
            "manifest_runtime_only": True,
        }

    rebuilt_root = output_root / "rebuilt_curriculum"
    rebuilt_reports = output_root / "rebuilt_curriculum_reports"
    payload = build_stage1_curriculum_manifests(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=rebuilt_root,
        reports_root=rebuilt_reports,
        split_seed=int(DEFAULT_CONFIG["seed"]),
        k1_train_count=100,
        k2_train_count=100,
        k1_dev_count=25,
        k2_dev_count=25,
    )
    medium = payload["medium"]
    return {
        "manifest_path": str(Path(medium["manifest_path"]).resolve()),
        "manifest_summary": dict(medium["summary"]),
        "manifest_rebuilt": True,
        "manifest_runtime_only": True,
    }


def _phase_progress(local_epoch_index: int, epoch_count: int) -> float:
    if epoch_count <= 1:
        return 1.0
    return float(local_epoch_index / max(epoch_count - 1, 1))


def _interpolate(start: float, end: float, progress: float) -> float:
    return float(start + (end - start) * progress)


def epoch_phase_for_setting(setting: dict[str, Any], epoch_index: int) -> dict[str, Any]:
    remaining = int(epoch_index)
    phase_start = 0
    for phase in setting["phases"]:
        phase_epochs = int(phase["epoch_count"])
        if remaining < phase_epochs:
            progress = _phase_progress(remaining, phase_epochs)
            return {
                **phase,
                "phase_start_epoch": phase_start,
                "phase_epoch_index": remaining,
                "resolved_lambda_count": _interpolate(
                    float(phase["lambda_count_start"]),
                    float(phase["lambda_count_end"]),
                    progress,
                ),
                "resolved_lambda_exist": _interpolate(
                    float(phase["lambda_exist_start"]),
                    float(phase["lambda_exist_end"]),
                    progress,
                ),
                "resolved_lambda_align": float(phase["lambda_align"]),
                "resolved_coupling_scale": float(phase.get("coupling_scale", 1.0)),
            }
        remaining -= phase_epochs
        phase_start += phase_epochs
    return epoch_phase_for_setting(setting, int(setting["epochs"]) - 1)


def _sample_with_ratio(
    source: list[MicaSample],
    *,
    requested_count: int,
    rng: random.Random,
) -> list[MicaSample]:
    if requested_count <= 0 or not source:
        return []
    if requested_count <= len(source):
        return rng.sample(source, requested_count)
    result = list(source)
    remaining = requested_count - len(result)
    result.extend(rng.choice(source) for _ in range(remaining))
    return result


def build_epoch_train_samples(
    train_samples: list[MicaSample],
    phase: dict[str, Any],
    *,
    seed: int,
    epoch_index: int,
    k2_replay_pool: list[MicaSample] | None = None,
) -> tuple[list[MicaSample], dict[str, Any]]:
    k1_samples = [sample for sample in train_samples if sample.source_kind == "atomic_k1"]
    k2_samples = [sample for sample in train_samples if sample.source_kind == "synthetic_k2"]
    rng = random.Random(seed + epoch_index * 1009)
    train_scope = str(phase["train_scope"])

    if train_scope == "k2_only":
        selected = _sample_with_ratio(k2_samples, requested_count=len(k2_samples), rng=rng)
        return selected, {
            "k1_seen_count": 0,
            "k2_seen_count": len(selected),
            "k2_replay_sample_count": 0,
        }

    total_target = len(k1_samples) + len(k2_samples)
    ratio = phase.get("k2_to_k1_ratio") or [1, 1]
    k2_ratio = int(ratio[0])
    k1_ratio = int(ratio[1])

    replay_samples: list[MicaSample] = []
    replay_ratio = float(phase.get("k2_replay_ratio", 0.0))
    replay_count = 0
    if train_scope == "mixed_with_replay":
        replay_count = int(round(total_target * replay_ratio))
        replay_source = list(k2_replay_pool or k2_samples)
        replay_samples = _sample_with_ratio(replay_source, requested_count=replay_count, rng=rng)

    remaining_total = max(total_target - replay_count, 0)
    total_ratio = max(k2_ratio + k1_ratio, 1)
    k2_count = int(round(remaining_total * k2_ratio / total_ratio))
    k1_count = remaining_total - k2_count
    sampled_k2 = _sample_with_ratio(k2_samples, requested_count=k2_count, rng=rng)
    sampled_k1 = _sample_with_ratio(k1_samples, requested_count=k1_count, rng=rng)
    selected = replay_samples + sampled_k2 + sampled_k1
    rng.shuffle(selected)
    return selected, {
        "k1_seen_count": len(sampled_k1),
        "k2_seen_count": len(replay_samples) + len(sampled_k2),
        "k2_replay_sample_count": len(replay_samples),
    }


def select_train_samples_for_phase(
    train_samples: list[MicaSample],
    phase: dict[str, Any],
    *,
    seed: int = 42,
    epoch_index: int = 0,
    k2_replay_pool: list[MicaSample] | None = None,
) -> list[MicaSample]:
    selected, _ = build_epoch_train_samples(
        train_samples,
        phase,
        seed=seed,
        epoch_index=epoch_index,
        k2_replay_pool=k2_replay_pool,
    )
    return selected


def _mean(values: list[float]) -> float:
    return float(sum(values) / max(len(values), 1))


def _slot_query_pairwise_cosine_mean(model: MicaModel) -> float:
    queries = model.slot_decoder.slot_queries.detach().cpu()
    if queries.size(0) <= 1:
        return 0.0
    values: list[float] = []
    for left_index in range(queries.size(0)):
        for right_index in range(left_index + 1, queries.size(0)):
            left = queries[left_index]
            right = queries[right_index]
            denom = left.norm().item() * right.norm().item()
            cosine = 0.0 if denom == 0 else float(torch.dot(left, right).item() / denom)
            values.append(cosine)
    return _mean(values)


def _setting_passes_fix(result: dict[str, Any]) -> bool:
    return (
        float(result["k2_split_recall_mixed"]) >= 0.50
        and float(result["second_slot_gold_recall_mixed"]) >= 0.40
        and float(result["unit_accuracy_gain_over_all_one_mixed"]) > 0.03
        and float(result["slot_collapse_rate_mixed"]) <= 0.45
        and float(result["count_accuracy_mixed"]) >= 0.55
        and float(result["over_split_rate_on_k1_mixed"]) <= 0.45
    )


def rank_staged_curriculum_results(results: list[dict[str, Any]]) -> dict[str, str | None]:
    if not results:
        return {
            "best_by_mixed_second_slot_gold_recall": None,
            "best_by_mixed_k2_split_recall": None,
            "best_by_mixed_unit_accuracy_gain": None,
            "best_by_lowest_mixed_slot_collapse": None,
            "best_balanced_stage1_schedule": None,
        }

    def _max_key(metric: str) -> str:
        return max(
            results,
            key=lambda item: (
                float(item[metric]),
                float(item["unit_accuracy_gain_over_all_one_mixed"]),
                -float(item["slot_collapse_rate_mixed"]),
            ),
        )["setting_name"]

    def _min_key(metric: str) -> str:
        return min(
            results,
            key=lambda item: (
                float(item[metric]),
                -float(item["k2_split_recall_mixed"]),
                -float(item["second_slot_gold_recall_mixed"]),
            ),
        )["setting_name"]

    def _balanced_score(item: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        return (
            1.0 if _setting_passes_fix(item) else 0.0,
            float(item["second_slot_gold_recall_mixed"]),
            float(item["k2_split_recall_mixed"]),
            float(item["unit_accuracy_gain_over_all_one_mixed"]),
            float(item["count_accuracy_mixed"]),
            -float(item["slot_collapse_rate_mixed"]),
        )

    return {
        "best_by_mixed_second_slot_gold_recall": _max_key("second_slot_gold_recall_mixed"),
        "best_by_mixed_k2_split_recall": _max_key("k2_split_recall_mixed"),
        "best_by_mixed_unit_accuracy_gain": _max_key("unit_accuracy_gain_over_all_one_mixed"),
        "best_by_lowest_mixed_slot_collapse": _min_key("slot_collapse_rate_mixed"),
        "best_balanced_stage1_schedule": max(results, key=_balanced_score)["setting_name"],
    }


def _copy_eval_metrics_with_suffix(metrics: dict[str, Any], suffix: str) -> dict[str, Any]:
    fields = {
        f"dev_loss_{suffix}": "dev_loss",
        f"count_accuracy_{suffix}": "count_accuracy",
        f"binary_multi_accuracy_{suffix}": "binary_multi_accuracy",
        f"over_split_rate_on_k1_{suffix}": "over_split_rate_on_k1",
        f"under_split_rate_on_k2_{suffix}": "under_split_rate_on_k2",
        f"unit_accuracy_hungarian_{suffix}": "unit_accuracy_hungarian",
        f"macro_intent_f1_hungarian_{suffix}": "macro_intent_f1_hungarian",
        f"micro_intent_f1_hungarian_{suffix}": "micro_intent_f1_hungarian",
        f"k2_split_recall_{suffix}": "k2_split_recall",
        f"second_slot_gold_recall_{suffix}": "second_slot_gold_recall",
        f"second_slot_assignment_mass_{suffix}": "second_slot_assignment_mass",
        f"effective_slot_count_mean_{suffix}": "effective_slot_count_mean",
        f"slot_collapse_rate_{suffix}": "slot_collapse_rate",
        f"assignment_entropy_{suffix}": "assignment_entropy",
        f"alignment_pairwise_f1_all_one_cluster_{suffix}": "alignment_pairwise_f1_all_one_cluster",
        f"alignment_pairwise_f1_file_path_baseline_{suffix}": "alignment_pairwise_f1_file_path_baseline",
        f"alignment_pairwise_f1_random_gold_k_mean_{suffix}": "alignment_pairwise_f1_random_gold_k_mean",
        f"alignment_pairwise_f1_model_oracle_k_{suffix}": "alignment_pairwise_f1_model_oracle_k",
        f"alignment_pairwise_f1_model_predicted_k_{suffix}": "alignment_pairwise_f1_model_predicted_k",
        f"alignment_gain_over_all_one_{suffix}": "alignment_gain_over_all_one",
        f"foreground_slot_usage_count_{suffix}": "foreground_slot_usage_count",
        f"assignment_top1_slot_distribution_{suffix}": "assignment_top1_slot_distribution",
    }
    payload = {target_key: metrics[source_key] for target_key, source_key in fields.items()}
    payload[f"unit_accuracy_gain_over_all_one_{suffix}"] = float(metrics["unit_accuracy_hungarian"]) - float(
        metrics["all_one_unit_accuracy"]
    )
    payload[f"macro_f1_gain_over_all_one_{suffix}"] = float(metrics["macro_intent_f1_hungarian"]) - float(
        metrics["all_one_macro_intent_f1"]
    )
    return payload


def _fit_setting(
    *,
    config: dict[str, Any],
    setting: dict[str, Any],
    train_samples: list[MicaSample],
) -> tuple[MicaModel, list[float], list[dict[str, Any]], dict[str, int]]:
    device = str(config["device"])
    model = MicaModel(
        text_vector_dim=TEXT_VECTOR_DIM,
        dense_feature_dim=len(DENSE_FEATURE_NAMES),
        hidden_dim=64,
        kmax=int(config["Kmax"]),
        assignment_temperature=float(config["assignment_temperature"]),
        count_pb_coupling_strength=float(config["count_pb_coupling_strength"]),
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    batch_size = int(config["batch_size"])
    total_epochs = int(setting["epochs"])
    k2_replay_pool = [sample for sample in train_samples if sample.source_kind == "synthetic_k2"]

    epoch_train_losses: list[float] = []
    training_log_rows: list[dict[str, Any]] = []
    seen_counts = {"k1_seen_count": 0, "k2_seen_count": 0, "k2_replay_sample_count": 0}

    for epoch_index in range(total_epochs):
        phase = epoch_phase_for_setting(setting, epoch_index)
        epoch_tau = assignment_temperature_for_epoch(
            epoch_index=epoch_index,
            total_epochs=total_epochs,
            tau_start=float(config["assignment_tau_start"]),
            tau_end=float(config["assignment_tau_end"]),
        )
        model.slot_decoder.assignment_temperature = epoch_tau
        coupling_scale = float(phase["resolved_coupling_scale"])
        model.slot_decoder.existence_mass_coupling_strength = (
            float(config["existence_mass_coupling_strength"]) * coupling_scale
            if bool(phase["enable_existence_mass_coupling"])
            else 0.0
        )
        model.count_pb_coupling_strength = (
            float(config["count_pb_coupling_strength"]) * coupling_scale
            if bool(phase["enable_count_pb_coupling"])
            else 0.0
        )
        model.slot_decoder.slot_queries.requires_grad_(not bool(phase.get("freeze_slot_queries", False)))

        epoch_train_samples, epoch_counts = build_epoch_train_samples(
            train_samples,
            phase,
            seed=int(config["seed"]),
            epoch_index=epoch_index,
            k2_replay_pool=k2_replay_pool,
        )
        for key, value in epoch_counts.items():
            seen_counts[key] += int(value)

        model.train()
        batch_losses: list[float] = []
        assignment_head_grad_norms: list[float] = []
        slot_query_grad_norms: list[float] = []
        encoder_grad_norms: list[float] = []
        for batch_samples in _batched(epoch_train_samples, batch_size, seed=int(config["seed"]) + epoch_index, shuffle=True):
            batch = collate_mica_samples(batch_samples)
            tensor_batch = {
                key: value.to(device) if isinstance(value, torch.Tensor) else value
                for key, value in batch.items()
            }
            output: MicaOutput = model(tensor_batch)
            losses = compute_stage1_losses(
                output,
                tensor_batch,
                lambda_align=float(phase["resolved_lambda_align"]),
                lambda_count=float(phase["resolved_lambda_count"]),
                lambda_exist=float(phase["resolved_lambda_exist"]),
                alpha_pb=float(config["alpha_pb"]),
                lambda_stab=float(config["lambda_stab"]),
                k2_min_second_slot_mass_ratio=float(config["k2_min_second_slot_mass_ratio"]),
            )
            if not torch.isfinite(losses["loss_total"]):
                raise ValueError(f"non-finite loss for {setting['setting_name']} epoch {epoch_index + 1}")
            optimizer.zero_grad()
            losses["loss_total"].backward()
            assignment_head_grad_norms.append(_parameter_grad_norm(list(model.slot_decoder.parameters())))
            slot_query_grad_norms.append(_parameter_grad_norm([model.slot_decoder.slot_queries]))
            encoder_grad_norms.append(_parameter_grad_norm(list(model.encoder.parameters())))
            optimizer.step()
            batch_losses.append(float(losses["loss_total"].item()))

        epoch_train_losses.append(_mean(batch_losses))
        training_log_rows.append(
            {
                "epoch": epoch_index + 1,
                "phase_epoch_index": int(phase["phase_epoch_index"]),
                "train_scope": str(phase["train_scope"]),
                "train_loss": epoch_train_losses[-1],
                "assignment_tau": epoch_tau,
                "lambda_align": float(phase["resolved_lambda_align"]),
                "lambda_count": float(phase["resolved_lambda_count"]),
                "lambda_exist": float(phase["resolved_lambda_exist"]),
                "enable_existence_mass_coupling": bool(phase["enable_existence_mass_coupling"]),
                "enable_count_pb_coupling": bool(phase["enable_count_pb_coupling"]),
                "coupling_scale": float(coupling_scale),
                "freeze_slot_queries": bool(phase.get("freeze_slot_queries", False)),
                "k1_seen_count": int(epoch_counts["k1_seen_count"]),
                "k2_seen_count": int(epoch_counts["k2_seen_count"]),
                "k2_replay_sample_count": int(epoch_counts["k2_replay_sample_count"]),
                "assignment_head_grad_norm": _mean(assignment_head_grad_norms),
                "slot_query_grad_norm": _mean(slot_query_grad_norms),
                "encoder_grad_norm": _mean(encoder_grad_norms),
            }
        )

    model.slot_decoder.slot_queries.requires_grad_(True)
    return model, epoch_train_losses, training_log_rows, seen_counts


def _setting_result(
    *,
    setting: dict[str, Any],
    model: MicaModel,
    epoch_train_losses: list[float],
    training_log_rows: list[dict[str, Any]],
    seen_counts: dict[str, int],
    mixed_metrics: dict[str, Any],
    k2_only_metrics: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "setting_name": str(setting["setting_name"]),
        "schedule_description": str(setting["schedule_description"]),
        "epochs": int(setting["epochs"]),
        "phase_definitions": [
            {
                "epoch_count": int(phase["epoch_count"]),
                "train_scope": str(phase["train_scope"]),
                "lambda_align": float(phase["lambda_align"]),
                "lambda_count_start": float(phase["lambda_count_start"]),
                "lambda_count_end": float(phase["lambda_count_end"]),
                "lambda_exist_start": float(phase["lambda_exist_start"]),
                "lambda_exist_end": float(phase["lambda_exist_end"]),
                "k2_to_k1_ratio": phase.get("k2_to_k1_ratio"),
                "enable_existence_mass_coupling": bool(phase["enable_existence_mass_coupling"]),
                "enable_count_pb_coupling": bool(phase["enable_count_pb_coupling"]),
                "coupling_scale": float(phase.get("coupling_scale", 1.0)),
                "freeze_slot_queries": bool(phase.get("freeze_slot_queries", False)),
                "k2_replay_ratio": float(phase.get("k2_replay_ratio", 0.0)),
            }
            for phase in setting["phases"]
        ],
        "k1_seen_count": int(seen_counts["k1_seen_count"]),
        "k2_seen_count": int(seen_counts["k2_seen_count"]),
        "k2_replay_ratio": max(
            [
                float(row["k2_replay_sample_count"])
                / max(float(row["k1_seen_count"] + row["k2_seen_count"]), 1.0)
                for row in training_log_rows
            ]
            or [0.0]
        ),
        "k2_replay_sample_count": int(seen_counts["k2_replay_sample_count"]),
        "coupling_schedule": [
            {
                "epoch": int(row["epoch"]),
                "enable_existence_mass_coupling": bool(row["enable_existence_mass_coupling"]),
                "enable_count_pb_coupling": bool(row["enable_count_pb_coupling"]),
                "coupling_scale": float(row["coupling_scale"]),
            }
            for row in training_log_rows
        ],
        "loss_weight_schedule": [
            {
                "epoch": int(row["epoch"]),
                "lambda_align": float(row["lambda_align"]),
                "lambda_count": float(row["lambda_count"]),
                "lambda_exist": float(row["lambda_exist"]),
            }
            for row in training_log_rows
        ],
        "train_loss_first_epoch": float(epoch_train_losses[0]),
        "train_loss_last_epoch": float(epoch_train_losses[-1]),
        "assignment_tau_first_epoch": float(training_log_rows[0]["assignment_tau"]),
        "assignment_tau_last_epoch": float(training_log_rows[-1]["assignment_tau"]),
        "slot_query_pairwise_cosine_mean": _slot_query_pairwise_cosine_mean(model),
        "gradient_norm_assignment_head_mean": _mean([float(row["assignment_head_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_slot_queries_mean": _mean([float(row["slot_query_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_encoder_mean": _mean([float(row["encoder_grad_norm"]) for row in training_log_rows]),
        "uses_only_stage1_sources": bool(setting["uses_only_stage1_sources"]),
        "uses_hard_b_or_m": bool(setting["uses_hard_b_or_m"]),
    }
    result.update(_copy_eval_metrics_with_suffix(mixed_metrics, "mixed"))
    result.update(_copy_eval_metrics_with_suffix(k2_only_metrics, "k2_only"))
    result["staged_schedule_fix"] = _setting_passes_fix(result)
    return result


def _answers_by_setting_name(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["setting_name"]: item for item in results}


def _cause_analysis(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = _answers_by_setting_name(results)
    t0 = by_name.get("T0_k2_only_reference")
    mixed_settings = [item for name, item in by_name.items() if name != "T0_k2_only_reference"]
    t1 = by_name.get("T1_long_k2_specialization_then_gentle_k1_reintroduction")
    t2 = by_name.get("T2_k2_specialization_with_replay_protected_mixed_training")
    t3 = by_name.get("T3_align_preserving_mixed_training")
    t4 = by_name.get("T4_freeze_slot_queries_after_k2_specialization")
    t5 = by_name.get("T5_disable_deterministic_coupling_during_reintroduction")

    def _passed(item: dict[str, Any] | None) -> bool:
        return bool(item and item["staged_schedule_fix"])

    t0_k2_upper_reference = bool(
        t0
        and float(t0["k2_split_recall_k2_only"]) >= 0.80
        and float(t0["second_slot_gold_recall_k2_only"]) >= 0.40
        and float(t0["slot_collapse_rate_k2_only"]) <= 0.20
    )
    mixing_suppresses = bool(
        t0_k2_upper_reference
        and any(
            float(item["second_slot_gold_recall_mixed"]) + 0.05 < float(t0["second_slot_gold_recall_k2_only"])
            for item in mixed_settings
        )
    )
    count_exist_suppresses = bool(t3 and _passed(t3))
    coupling_contributed = bool(t5 and _passed(t5))
    minimal_schedule = None
    for candidate_name in (
        "T1_long_k2_specialization_then_gentle_k1_reintroduction",
        "T2_k2_specialization_with_replay_protected_mixed_training",
        "T3_align_preserving_mixed_training",
        "T4_freeze_slot_queries_after_k2_specialization",
        "T5_disable_deterministic_coupling_during_reintroduction",
    ):
        if candidate_name in by_name and _passed(by_name[candidate_name]):
            minimal_schedule = candidate_name
            break

    if t0 and _passed(t0) and not any(_passed(item) for item in mixed_settings):
        conclusion = "k2 specialization works but cannot survive k1 reintroduction; next step should change representation or architecture."
    elif t3 and _passed(t3):
        conclusion = "align-only warmup is required before count/existence calibration."
    elif t5 and _passed(t5):
        conclusion = "deterministic coupling should be disabled or delayed in formal Stage 1."
    elif t4 and _passed(t4):
        conclusion = "mixed stage disrupts slot queries; freezing or lower LR for slot queries should be considered."
    elif t1 and _passed(t1) or t2 and _passed(t2):
        conclusion = "staged Stage 1 protocol is viable; next step should freeze formal Stage 1 schedule and rerun with larger sample."
    else:
        conclusion = "staged schedules improved diagnostics, but mixed training still fails; next step should change representation or architecture inside Stage 1."

    return {
        "q1_k1_k2_mixing_suppresses_early_slot_specialization": mixing_suppresses,
        "q2_count_existence_losses_suppress_alignment": count_exist_suppresses,
        "q3_deterministic_coupling_aggravates_collapse": coupling_contributed,
        "q4_epochs_too_few": False,
        "q5_k2_split_signal_too_weak": not t0_k2_upper_reference,
        "q6_minimal_viable_stage1_schedule": minimal_schedule,
        "conclusion": conclusion,
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Staged Curriculum Result",
        "",
        f"- training_run: {str(payload['training_run']).lower()}",
        f"- sanity_only: true",
        f"- manifest_rebuilt: {str(payload['manifest_rebuilt']).lower()}",
        f"- manifest_runtime_only: {str(payload['manifest_runtime_only']).lower()}",
        f"- staged_schedule_fix_found: {str(payload['staged_schedule_fix_found']).lower()}",
        "",
        "## Motivation",
        "",
        payload["problem_statement"],
        "",
    ]
    for setting in payload["settings"]:
        lines.extend(
            [
                f"## {setting['setting_name']}",
                "",
                f"- schedule_description: {setting['schedule_description']}",
                f"- epochs: {setting['epochs']}",
                f"- train_loss_first_epoch: {setting['train_loss_first_epoch']:.6f}",
                f"- train_loss_last_epoch: {setting['train_loss_last_epoch']:.6f}",
                f"- count_accuracy_mixed: {setting['count_accuracy_mixed']:.6f}",
                f"- count_accuracy_k2_only: {setting['count_accuracy_k2_only']:.6f}",
                f"- unit_accuracy_hungarian_mixed: {setting['unit_accuracy_hungarian_mixed']:.6f}",
                f"- unit_accuracy_hungarian_k2_only: {setting['unit_accuracy_hungarian_k2_only']:.6f}",
                f"- k2_split_recall_mixed: {setting['k2_split_recall_mixed']:.6f}",
                f"- k2_split_recall_k2_only: {setting['k2_split_recall_k2_only']:.6f}",
                f"- second_slot_gold_recall_mixed: {setting['second_slot_gold_recall_mixed']:.6f}",
                f"- second_slot_gold_recall_k2_only: {setting['second_slot_gold_recall_k2_only']:.6f}",
                f"- slot_collapse_rate_mixed: {setting['slot_collapse_rate_mixed']:.6f}",
                f"- slot_collapse_rate_k2_only: {setting['slot_collapse_rate_k2_only']:.6f}",
                f"- unit_accuracy_gain_over_all_one_mixed: {setting['unit_accuracy_gain_over_all_one_mixed']:.6f}",
                f"- macro_f1_gain_over_all_one_mixed: {setting['macro_f1_gain_over_all_one_mixed']:.6f}",
                f"- staged_schedule_fix: {str(setting['staged_schedule_fix']).lower()}",
                "",
            ]
        )
    lines.extend(
        [
            "## Ranking",
            "",
            f"- best_by_mixed_second_slot_gold_recall: {payload['ranking']['best_by_mixed_second_slot_gold_recall']}",
            f"- best_by_mixed_k2_split_recall: {payload['ranking']['best_by_mixed_k2_split_recall']}",
            f"- best_by_mixed_unit_accuracy_gain: {payload['ranking']['best_by_mixed_unit_accuracy_gain']}",
            f"- best_by_lowest_mixed_slot_collapse: {payload['ranking']['best_by_lowest_mixed_slot_collapse']}",
            f"- best_balanced_stage1_schedule: {payload['ranking']['best_balanced_stage1_schedule']}",
            "",
            "## Cause Analysis",
            "",
            f"- q1_k1_k2_mixing_suppresses_early_slot_specialization: {str(payload['cause_analysis']['q1_k1_k2_mixing_suppresses_early_slot_specialization']).lower()}",
            f"- q2_count_existence_losses_suppress_alignment: {str(payload['cause_analysis']['q2_count_existence_losses_suppress_alignment']).lower()}",
            f"- q3_deterministic_coupling_aggravates_collapse: {str(payload['cause_analysis']['q3_deterministic_coupling_aggravates_collapse']).lower()}",
            f"- q4_epochs_too_few: {str(payload['cause_analysis']['q4_epochs_too_few']).lower()}",
            f"- q5_k2_split_signal_too_weak: {str(payload['cause_analysis']['q5_k2_split_signal_too_weak']).lower()}",
            f"- q6_minimal_viable_stage1_schedule: {payload['cause_analysis']['q6_minimal_viable_stage1_schedule']}",
            "",
            payload["cause_analysis"]["conclusion"],
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage1_staged_curriculum(
    *,
    curriculum_manifest: str,
    synthetic_jsonl: str,
    atomic_csv: str,
    output_root: str,
    reports_root: str = "reports",
    settings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    manifest_info = _resolve_or_rebuild_medium_manifest(
        curriculum_manifest=curriculum_manifest,
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=output_root_path,
    )
    prepared = prepare_stage1_sanity_run(
        dict(DEFAULT_CONFIG),
        cli_manifest_json=manifest_info["manifest_path"],
        cli_curriculum_level="medium",
        cli_atomic_csv=atomic_csv,
        cli_synthetic_jsonl=synthetic_jsonl,
        cli_output_root=str(output_root_path),
    )
    manifest_result = prepared["manifest_result"]
    medium_train = list(prepared["train_samples"])
    medium_dev = list(prepared["dev_samples"])
    k2_only_dev = [sample for sample in medium_dev if sample.source_kind == "synthetic_k2"]
    config = dict(prepared["config"])
    setting_results: list[dict[str, Any]] = []

    for setting in (settings or build_stage1_staged_curriculum_settings()):
        model, epoch_train_losses, training_log_rows, seen_counts = _fit_setting(
            config=config,
            setting=setting,
            train_samples=medium_train,
        )
        mixed_metrics = evaluate_model(model, medium_dev, batch_size=int(config["batch_size"]), device=str(config["device"]))
        k2_only_metrics = evaluate_model(
            model,
            k2_only_dev,
            batch_size=int(config["batch_size"]),
            device=str(config["device"]),
        )
        result_row = _setting_result(
            setting=setting,
            model=model,
            epoch_train_losses=epoch_train_losses,
            training_log_rows=training_log_rows,
            seen_counts=seen_counts,
            mixed_metrics=mixed_metrics,
            k2_only_metrics=k2_only_metrics,
        )
        setting_results.append(result_row)
        _write_json(output_root_path / f"{setting['setting_name']}_metrics.json", result_row)
        _write_jsonl(output_root_path / f"{setting['setting_name']}_training_log.jsonl", training_log_rows)

    ranking = rank_staged_curriculum_results(setting_results)
    staged_schedule_fix_found = any(item["staged_schedule_fix"] for item in setting_results)
    cause_analysis = _cause_analysis(setting_results)
    payload = {
        "training_run": True,
        "sanity_only": True,
        "problem_statement": "The model can overfit assignment, but normal medium Stage 1 training collapses to one foreground slot. This suggests a slot-competition/training-schedule failure rather than an unlearnable assignment head.",
        "manifest_path_runtime_only": manifest_info["manifest_path"],
        "manifest_summary": manifest_info["manifest_summary"],
        "manifest_rebuilt": bool(manifest_info["manifest_rebuilt"]),
        "manifest_runtime_only": bool(manifest_info["manifest_runtime_only"]),
        "uses_only_stage1_sources": True,
        "uses_hard_b_or_m": False,
        "curriculum_level": manifest_result.get("curriculum_level"),
        "settings": setting_results,
        "ranking": ranking,
        "staged_schedule_fix_found": staged_schedule_fix_found,
        "cause_analysis": cause_analysis,
    }
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_staged_curriculum_result.json", payload)
    _write_markdown(reports_root_path / "mica_stage1_staged_curriculum_result.md", payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage 1 staged curriculum schedules for MICA-v3.")
    parser.add_argument("--curriculum-manifest", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = run_stage1_staged_curriculum(
        curriculum_manifest=args.curriculum_manifest,
        synthetic_jsonl=args.synthetic_jsonl,
        atomic_csv=args.atomic_csv,
        output_root=args.output_root,
        reports_root=args.reports_root,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
