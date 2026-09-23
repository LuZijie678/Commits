from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.data.schema import MicaSample
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM, collate_mica_samples
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


def build_stage1_slot_competition_settings() -> list[dict[str, Any]]:
    return [
        {
            "setting_name": "S0_current_normal_medium",
            "epochs": 3,
            "schedule_description": "Current normal medium baseline with mixed k1/k2 training and current coupling.",
            "phases": [
                {
                    "epoch_count": 3,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S1_longer_training",
            "epochs": 10,
            "schedule_description": "Longer mixed training to test whether 3 epochs are insufficient.",
            "phases": [
                {
                    "epoch_count": 10,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S2_align_dominant",
            "epochs": 10,
            "schedule_description": "Reduce count/existence pressure while keeping mixed training and current coupling.",
            "phases": [
                {
                    "epoch_count": 10,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.1,
                    "lambda_exist": 0.1,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S3_align_only_warmup_then_full",
            "epochs": 10,
            "schedule_description": "Warm up assignment with align-only epochs, then enable count/existence calibration.",
            "phases": [
                {
                    "epoch_count": 5,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.0,
                    "lambda_exist": 0.0,
                    "enable_existence_mass_coupling": False,
                    "enable_count_pb_coupling": False,
                },
                {
                    "epoch_count": 5,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S4_k2_focused_warmup_then_mixed",
            "epochs": 10,
            "schedule_description": "Warm up on medium k2 only, then switch to mixed k1/k2 training.",
            "phases": [
                {
                    "epoch_count": 5,
                    "train_scope": "k2_only",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.2,
                    "lambda_exist": 0.2,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                },
                {
                    "epoch_count": 5,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                },
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S5_disable_deterministic_coupling",
            "epochs": 10,
            "schedule_description": "Keep mixed training but disable deterministic assignment-mass and pb-prior coupling.",
            "phases": [
                {
                    "epoch_count": 10,
                    "train_scope": "mixed",
                    "dev_scope": "mixed",
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "enable_existence_mass_coupling": False,
                    "enable_count_pb_coupling": False,
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
        {
            "setting_name": "S6_k2_only_generalization",
            "epochs": 10,
            "schedule_description": "Train and evaluate on medium k2 only to isolate k1 mixing pressure.",
            "phases": [
                {
                    "epoch_count": 10,
                    "train_scope": "k2_only",
                    "dev_scope": "k2_only",
                    "lambda_align": 1.0,
                    "lambda_count": 0.2,
                    "lambda_exist": 0.2,
                    "enable_existence_mass_coupling": True,
                    "enable_count_pb_coupling": True,
                }
            ],
            "uses_only_stage1_sources": True,
            "uses_hard_b_or_m": False,
        },
    ]


def epoch_phase_for_setting(setting: dict[str, Any], epoch_index: int) -> dict[str, Any]:
    remaining = int(epoch_index)
    for phase in setting["phases"]:
        phase_epochs = int(phase["epoch_count"])
        if remaining < phase_epochs:
            return dict(phase)
        remaining -= phase_epochs
    return dict(setting["phases"][-1])


def select_train_samples_for_phase(train_samples: list[MicaSample], phase: dict[str, Any]) -> list[MicaSample]:
    train_scope = str(phase["train_scope"])
    if train_scope == "mixed":
        return list(train_samples)
    if train_scope == "k2_only":
        return [sample for sample in train_samples if sample.source_kind == "synthetic_k2"]
    raise ValueError(f"unsupported train scope: {train_scope}")


def _select_dev_samples_for_setting(dev_samples: list[MicaSample], setting: dict[str, Any]) -> list[MicaSample]:
    final_phase = epoch_phase_for_setting(setting, int(setting["epochs"]) - 1)
    dev_scope = str(final_phase["dev_scope"])
    if dev_scope == "mixed":
        return list(dev_samples)
    if dev_scope == "k2_only":
        return [sample for sample in dev_samples if sample.source_kind == "synthetic_k2"]
    raise ValueError(f"unsupported dev scope: {dev_scope}")


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
    return float(sum(values) / max(len(values), 1))


def _setting_passes_fix(result: dict[str, Any]) -> bool:
    return (
        float(result["k2_split_recall"]) >= 0.50
        and float(result["second_slot_gold_recall"]) >= 0.40
        and float(result["unit_accuracy_gain_over_all_one"]) > 0.03
        and float(result["slot_collapse_rate"]) <= 0.45
        and float(result["count_accuracy"]) >= 0.55
    )


def rank_ablation_results(results: list[dict[str, Any]]) -> dict[str, str | None]:
    if not results:
        return {
            "best_by_k2_split_recall": None,
            "best_by_second_slot_gold_recall": None,
            "best_by_unit_accuracy_gain": None,
            "best_by_lowest_slot_collapse": None,
            "best_balanced_setting": None,
        }

    def _max_key(metric: str) -> str:
        return max(results, key=lambda item: (float(item[metric]), float(item["count_accuracy"]), -float(item["slot_collapse_rate"])))["setting_name"]

    def _min_key(metric: str) -> str:
        return min(results, key=lambda item: (float(item[metric]), -float(item["k2_split_recall"]), -float(item["count_accuracy"])))["setting_name"]

    def _balanced_score(item: dict[str, Any]) -> tuple[float, float, float, float, float]:
        return (
            1.0 if _setting_passes_fix(item) else 0.0,
            float(item["k2_split_recall"]),
            float(item["second_slot_gold_recall"]),
            float(item["unit_accuracy_gain_over_all_one"]),
            float(item["count_accuracy"]) - float(item["slot_collapse_rate"]),
        )

    return {
        "best_by_k2_split_recall": _max_key("k2_split_recall"),
        "best_by_second_slot_gold_recall": _max_key("second_slot_gold_recall"),
        "best_by_unit_accuracy_gain": _max_key("unit_accuracy_gain_over_all_one"),
        "best_by_lowest_slot_collapse": _min_key("slot_collapse_rate"),
        "best_balanced_setting": max(results, key=_balanced_score)["setting_name"],
    }


def _resolve_or_rebuild_medium_manifest(
    *,
    curriculum_manifest: str,
    atomic_csv: str,
    synthetic_jsonl: str,
    output_root: Path,
) -> dict[str, Any]:
    manifest_path = Path(curriculum_manifest)
    if manifest_path.is_absolute():
        resolved_manifest_path = manifest_path
    else:
        resolved_manifest_path = (ROOT / manifest_path).resolve()
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


def _mean(values: list[float]) -> float:
    return float(sum(values) / max(len(values), 1))


def _fit_setting(
    *,
    config: dict[str, Any],
    setting: dict[str, Any],
    train_samples: list[MicaSample],
) -> tuple[MicaModel, list[float], list[dict[str, Any]]]:
    device = str(config["device"])
    model = MicaModel(
        text_vector_dim=TEXT_VECTOR_DIM,
        dense_feature_dim=len(DENSE_FEATURE_NAMES),
        hidden_dim=64,
        kmax=int(config["Kmax"]),
        assignment_temperature=float(config["assignment_temperature"]),
        count_pb_coupling_strength=float(config["count_pb_coupling_strength"]),
    ).to(device)
    model.slot_decoder.existence_mass_coupling_strength = float(config["existence_mass_coupling_strength"])
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))

    batch_size = int(config["batch_size"])
    epoch_train_losses: list[float] = []
    training_log_rows: list[dict[str, Any]] = []
    total_epochs = int(setting["epochs"])
    for epoch_index in range(total_epochs):
        phase = epoch_phase_for_setting(setting, epoch_index)
        epoch_tau = assignment_temperature_for_epoch(
            epoch_index=epoch_index,
            total_epochs=total_epochs,
            tau_start=float(config["assignment_tau_start"]),
            tau_end=float(config["assignment_tau_end"]),
        )
        model.slot_decoder.assignment_temperature = epoch_tau
        model.slot_decoder.existence_mass_coupling_strength = (
            float(config["existence_mass_coupling_strength"]) if bool(phase["enable_existence_mass_coupling"]) else 0.0
        )
        model.count_pb_coupling_strength = (
            float(config["count_pb_coupling_strength"]) if bool(phase["enable_count_pb_coupling"]) else 0.0
        )
        epoch_train_samples = select_train_samples_for_phase(train_samples, phase)

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
                lambda_align=float(phase["lambda_align"]),
                lambda_count=float(phase["lambda_count"]),
                lambda_exist=float(phase["lambda_exist"]),
                alpha_pb=float(config["alpha_pb"]),
                lambda_stab=float(config["lambda_stab"]),
                k2_min_second_slot_mass_ratio=float(config["k2_min_second_slot_mass_ratio"]),
            )
            if not torch.isfinite(losses["loss_total"]):
                raise ValueError(f"non-finite Stage 1 loss for {setting['setting_name']} epoch {epoch_index + 1}")
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
                "train_loss": epoch_train_losses[-1],
                "assignment_tau": epoch_tau,
                "train_scope": phase["train_scope"],
                "lambda_align": float(phase["lambda_align"]),
                "lambda_count": float(phase["lambda_count"]),
                "lambda_exist": float(phase["lambda_exist"]),
                "enable_existence_mass_coupling": bool(phase["enable_existence_mass_coupling"]),
                "enable_count_pb_coupling": bool(phase["enable_count_pb_coupling"]),
                "assignment_head_grad_norm": _mean(assignment_head_grad_norms),
                "slot_query_grad_norm": _mean(slot_query_grad_norms),
                "encoder_grad_norm": _mean(encoder_grad_norms),
            }
        )

    return model, epoch_train_losses, training_log_rows


def _setting_result(
    *,
    setting: dict[str, Any],
    config: dict[str, Any],
    model: MicaModel,
    epoch_train_losses: list[float],
    training_log_rows: list[dict[str, Any]],
    eval_metrics: dict[str, Any],
) -> dict[str, Any]:
    unit_accuracy_gain = float(eval_metrics["unit_accuracy_hungarian"]) - float(eval_metrics["all_one_unit_accuracy"])
    macro_f1_gain = float(eval_metrics["macro_intent_f1_hungarian"]) - float(eval_metrics["all_one_macro_intent_f1"])
    result = {
        "setting_name": str(setting["setting_name"]),
        "epochs": int(setting["epochs"]),
        "schedule_description": str(setting["schedule_description"]),
        "train_loss_first_epoch": float(epoch_train_losses[0]),
        "train_loss_last_epoch": float(epoch_train_losses[-1]),
        "dev_loss": float(eval_metrics["dev_loss"]),
        "count_accuracy": float(eval_metrics["count_accuracy"]),
        "binary_multi_accuracy": float(eval_metrics["binary_multi_accuracy"]),
        "over_split_rate_on_k1": float(eval_metrics["over_split_rate_on_k1"]),
        "under_split_rate_on_k2": float(eval_metrics["under_split_rate_on_k2"]),
        "unit_accuracy_hungarian": float(eval_metrics["unit_accuracy_hungarian"]),
        "macro_intent_f1_hungarian": float(eval_metrics["macro_intent_f1_hungarian"]),
        "micro_intent_f1_hungarian": float(eval_metrics["micro_intent_f1_hungarian"]),
        "k2_split_recall": float(eval_metrics["k2_split_recall"]),
        "second_slot_gold_recall": float(eval_metrics["second_slot_gold_recall"]),
        "second_slot_assignment_mass": float(eval_metrics["second_slot_assignment_mass"]),
        "effective_slot_count_mean": float(eval_metrics["effective_slot_count_mean"]),
        "foreground_slot_usage_count": float(eval_metrics["foreground_slot_usage_count"]),
        "slot_collapse_rate": float(eval_metrics["slot_collapse_rate"]),
        "assignment_entropy": float(eval_metrics["assignment_entropy"]),
        "alignment_pairwise_f1_all_one_cluster": float(eval_metrics["alignment_pairwise_f1_all_one_cluster"]),
        "alignment_pairwise_f1_file_path_baseline": float(eval_metrics["alignment_pairwise_f1_file_path_baseline"]),
        "alignment_pairwise_f1_random_gold_k_mean": float(eval_metrics["alignment_pairwise_f1_random_gold_k_mean"]),
        "alignment_pairwise_f1_model_oracle_k": float(eval_metrics["alignment_pairwise_f1_model_oracle_k"]),
        "alignment_pairwise_f1_model_predicted_k": float(eval_metrics["alignment_pairwise_f1_model_predicted_k"]),
        "alignment_gain_over_all_one": float(eval_metrics["alignment_gain_over_all_one"]),
        "unit_accuracy_gain_over_all_one": unit_accuracy_gain,
        "macro_f1_gain_over_all_one": macro_f1_gain,
        "assignment_top1_slot_distribution": dict(eval_metrics["assignment_top1_slot_distribution"]),
        "slot_query_pairwise_cosine_mean": _slot_query_pairwise_cosine_mean(model),
        "gradient_norm_assignment_head_mean": _mean([float(row["assignment_head_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_slot_queries_mean": _mean([float(row["slot_query_grad_norm"]) for row in training_log_rows]),
        "gradient_norm_encoder_mean": _mean([float(row["encoder_grad_norm"]) for row in training_log_rows]),
        "train_scope_sequence": [str(row["train_scope"]) for row in training_log_rows],
        "uses_only_stage1_sources": bool(setting["uses_only_stage1_sources"]),
        "uses_hard_b_or_m": bool(setting["uses_hard_b_or_m"]),
        "slot_competition_fix": False,
    }
    result["slot_competition_fix"] = _setting_passes_fix(result)
    return result


def _answers_by_setting_name(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["setting_name"]: item for item in results}


def _cause_analysis(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = _answers_by_setting_name(results)
    s0 = by_name.get("S0_current_normal_medium")
    s1 = by_name.get("S1_longer_training")
    s2 = by_name.get("S2_align_dominant")
    s3 = by_name.get("S3_align_only_warmup_then_full")
    s4 = by_name.get("S4_k2_focused_warmup_then_mixed")
    s5 = by_name.get("S5_disable_deterministic_coupling")
    s6 = by_name.get("S6_k2_only_generalization")

    def _passed(item: dict[str, Any] | None) -> bool:
        return bool(item and item["slot_competition_fix"])

    epochs_too_few = bool(s0 and s1 and _passed(s1) and not _passed(s0))
    count_exist_suppresses = bool(s0 and ((_passed(s2) if s2 else False) or (_passed(s3) if s3 else False)) and not _passed(s0))
    mixing_suppresses = bool(s6 and _passed(s6) and not any(_passed(item) for name, item in by_name.items() if name != "S6_k2_only_generalization"))
    coupling_contributed = bool(s0 and s5 and _passed(s5) and not _passed(s0))

    minimal_schedule = None
    for candidate_name in (
        "S3_align_only_warmup_then_full",
        "S4_k2_focused_warmup_then_mixed",
        "S2_align_dominant",
        "S5_disable_deterministic_coupling",
        "S1_longer_training",
        "S6_k2_only_generalization",
    ):
        if candidate_name in by_name and _passed(by_name[candidate_name]):
            minimal_schedule = candidate_name
            break

    if mixing_suppresses:
        conclusion = "k1/k2 mixing suppresses early slot specialization; need k2-focused or align-only warmup before mixed training."
    elif _passed(s3):
        conclusion = "align-only warmup is required before count/existence calibration."
    elif _passed(s5):
        conclusion = "deterministic count/existence coupling contributed to collapse and should be disabled or delayed."
    elif not any(item["slot_competition_fix"] for item in results) and s6 is not None and not _passed(s6):
        conclusion = "medium generalization fails even without k1 pressure; current evidence features or assignment architecture are insufficient."
    elif not any(item["slot_competition_fix"] for item in results):
        conclusion = "model can memorize assignment but does not generalize under current features; next step should improve evidence representation, not Stage 2."
    else:
        conclusion = f"best current Stage 1 schedule is {minimal_schedule}."

    return {
        "q1_k1_k2_mixed_training_causes_collapse": mixing_suppresses,
        "q2_count_existence_loss_suppresses_alignment": count_exist_suppresses,
        "q3_deterministic_coupling_contributed_to_collapse": coupling_contributed,
        "q4_epochs_too_few": epochs_too_few,
        "q5_k2_split_signal_too_weak": False if s6 is None else (not _passed(s6)),
        "q6_minimal_viable_stage1_schedule": minimal_schedule,
        "conclusion": conclusion,
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Slot Competition Ablation Result",
        "",
        f"- training_run: {str(payload['training_run']).lower()}",
        f"- sanity_only: true",
        f"- manifest_rebuilt: {str(payload['manifest_rebuilt']).lower()}",
        f"- manifest_runtime_only: {str(payload['manifest_runtime_only']).lower()}",
        f"- slot_competition_fix_found: {str(payload['slot_competition_fix_found']).lower()}",
        "",
        "## Problem Statement",
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
                f"- dev_loss: {setting['dev_loss']:.6f}",
                f"- count_accuracy: {setting['count_accuracy']:.6f}",
                f"- over_split_rate_on_k1: {setting['over_split_rate_on_k1']:.6f}",
                f"- under_split_rate_on_k2: {setting['under_split_rate_on_k2']:.6f}",
                f"- unit_accuracy_hungarian: {setting['unit_accuracy_hungarian']:.6f}",
                f"- macro_intent_f1_hungarian: {setting['macro_intent_f1_hungarian']:.6f}",
                f"- k2_split_recall: {setting['k2_split_recall']:.6f}",
                f"- second_slot_gold_recall: {setting['second_slot_gold_recall']:.6f}",
                f"- second_slot_assignment_mass: {setting['second_slot_assignment_mass']:.6f}",
                f"- slot_collapse_rate: {setting['slot_collapse_rate']:.6f}",
                f"- alignment_gain_over_all_one: {setting['alignment_gain_over_all_one']:.6f}",
                f"- unit_accuracy_gain_over_all_one: {setting['unit_accuracy_gain_over_all_one']:.6f}",
                f"- macro_f1_gain_over_all_one: {setting['macro_f1_gain_over_all_one']:.6f}",
                f"- slot_competition_fix: {str(setting['slot_competition_fix']).lower()}",
                "",
            ]
        )
    lines.extend(
        [
            "## Ranking",
            "",
            f"- best_by_k2_split_recall: {payload['ranking']['best_by_k2_split_recall']}",
            f"- best_by_second_slot_gold_recall: {payload['ranking']['best_by_second_slot_gold_recall']}",
            f"- best_by_unit_accuracy_gain: {payload['ranking']['best_by_unit_accuracy_gain']}",
            f"- best_by_lowest_slot_collapse: {payload['ranking']['best_by_lowest_slot_collapse']}",
            f"- best_balanced_setting: {payload['ranking']['best_balanced_setting']}",
            "",
            "## Cause Analysis",
            "",
            f"- q1_k1_k2_mixed_training_causes_collapse: {str(payload['cause_analysis']['q1_k1_k2_mixed_training_causes_collapse']).lower()}",
            f"- q2_count_existence_loss_suppresses_alignment: {str(payload['cause_analysis']['q2_count_existence_loss_suppresses_alignment']).lower()}",
            f"- q3_deterministic_coupling_contributed_to_collapse: {str(payload['cause_analysis']['q3_deterministic_coupling_contributed_to_collapse']).lower()}",
            f"- q4_epochs_too_few: {str(payload['cause_analysis']['q4_epochs_too_few']).lower()}",
            f"- q5_k2_split_signal_too_weak: {str(payload['cause_analysis']['q5_k2_split_signal_too_weak']).lower()}",
            f"- q6_minimal_viable_stage1_schedule: {payload['cause_analysis']['q6_minimal_viable_stage1_schedule']}",
            "",
            payload["cause_analysis"]["conclusion"],
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage1_slot_competition_ablation(
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
    config = dict(prepared["config"])
    setting_results: list[dict[str, Any]] = []

    for setting in (settings or build_stage1_slot_competition_settings()):
        model, epoch_train_losses, training_log_rows = _fit_setting(
            config=config,
            setting=setting,
            train_samples=medium_train,
        )
        eval_samples = _select_dev_samples_for_setting(medium_dev, setting)
        eval_metrics = evaluate_model(model, eval_samples, batch_size=int(config["batch_size"]), device=str(config["device"]))
        result_row = _setting_result(
            setting=setting,
            config=config,
            model=model,
            epoch_train_losses=epoch_train_losses,
            training_log_rows=training_log_rows,
            eval_metrics=eval_metrics,
        )
        setting_results.append(result_row)
        _write_json(output_root_path / f"{setting['setting_name']}_metrics.json", result_row)
        _write_jsonl(output_root_path / f"{setting['setting_name']}_training_log.jsonl", training_log_rows)

    ranking = rank_ablation_results(setting_results)
    slot_competition_fix_found = any(item["slot_competition_fix"] for item in setting_results)
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
        "slot_competition_fix_found": slot_competition_fix_found,
        "cause_analysis": cause_analysis,
    }
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_slot_competition_ablation_result.json", payload)
    _write_markdown(reports_root_path / "mica_stage1_slot_competition_ablation_result.md", payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage 1 slot competition ablations for MICA-v3.")
    parser.add_argument("--curriculum-manifest", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = run_stage1_slot_competition_ablation(
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
