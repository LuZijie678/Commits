from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.build_stage1_sanity_manifest import build_stage1_sanity_manifest
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM, collate_mica_samples
from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.losses.mica_losses import compute_stage1_losses
from code.mica.models.mica_model import MicaModel, MicaOutput
from code.mica.train.eval_stage1_sanity import decide_sanity_status, evaluate_model


DEFAULT_CONFIG: dict[str, Any] = {
    "atomic_csv": "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
    "synthetic_jsonl": None,
    "max_train_samples": 200,
    "max_dev_samples": 50,
    "batch_size": 8,
    "epochs": 3,
    "Kmax": 4,
    "learning_rate": 1e-3,
    "seed": 42,
    "device": "cpu",
    "output_root": None,
    "sanity_only": True,
    "assignment_temperature": 0.7,
    "assignment_tau_start": 1.5,
    "assignment_tau_end": 0.7,
    "existence_mass_coupling_strength": 1.5,
    "count_pb_coupling_strength": 0.0,
    "lambda_align": 1.0,
    "lambda_count": 0.5,
    "lambda_exist": 0.5,
    "alpha_pb": 0.5,
    "lambda_stab": 0.03,
    "lambda_bg": 0.2,
    "k2_min_second_slot_mass_ratio": 0.20,
}

CONFIG_ALIASES = {
    "atomic_csv_path": "atomic_csv",
    "synthetic_jsonl_path": "synthetic_jsonl",
    "kmax": "Kmax",
    "output_dir": "output_root",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw in {"null", "None", ""}:
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw.strip("'\"")


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    for key, value in config.items():
        canonical_key = CONFIG_ALIASES.get(key, key)
        normalized[canonical_key] = value
    return normalized


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload: dict[str, Any] = {}
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition(":")
        payload[key.strip()] = _parse_scalar(value)
    return _normalize_config(payload)


def _resolve_path(value: str | Path | None) -> str:
    if value is None or value == "":
        return ""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((_repo_root() / path).resolve())


def resolve_stage1_sanity_paths(
    config: dict[str, Any],
    *,
    cli_synthetic_jsonl: str | None = None,
    cli_atomic_csv: str | None = None,
    cli_output_root: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    effective_env = env if env is not None else os.environ
    merged = _normalize_config(config)

    atomic_csv = cli_atomic_csv or merged.get("atomic_csv")
    if not atomic_csv:
        raise FileNotFoundError("atomic csv path is required for Stage 1 sanity")
    atomic_path = Path(_resolve_path(atomic_csv))
    if not atomic_path.exists():
        raise FileNotFoundError(f"atomic csv not found: {atomic_path}")

    synthetic_jsonl = cli_synthetic_jsonl or effective_env.get("MICA_STAGE1_SYNTHETIC_JSONL") or merged.get("synthetic_jsonl")
    if not synthetic_jsonl:
        raise ValueError(
            "synthetic jsonl is required; pass --synthetic-jsonl or set MICA_STAGE1_SYNTHETIC_JSONL"
        )
    synthetic_path = Path(_resolve_path(synthetic_jsonl))
    if not synthetic_path.exists():
        raise FileNotFoundError(f"synthetic jsonl not found: {synthetic_path}")

    output_root = cli_output_root or merged.get("output_root")
    output_root_value = output_root or str(_repo_root() / "outputs" / f"mica_stage1_sanity_{_timestamp()}")
    output_root_path = Path(output_root_value)
    if not output_root_path.is_absolute():
        output_root_path = (_repo_root() / output_root_path).resolve()

    return {
        "atomic_csv": str(atomic_path),
        "synthetic_jsonl": str(synthetic_path),
        "output_root": str(output_root_path),
    }


def _batched(samples: list[Any], batch_size: int, *, seed: int, shuffle: bool) -> list[list[Any]]:
    indices = list(range(len(samples)))
    if shuffle:
        random.Random(seed).shuffle(indices)
    return [[samples[index] for index in indices[offset : offset + batch_size]] for offset in range(0, len(indices), batch_size)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _parameter_grad_norm(parameters: list[torch.nn.Parameter]) -> float:
    grad_squares = 0.0
    has_grad = False
    for parameter in parameters:
        if parameter.grad is None:
            continue
        grad = parameter.grad.detach()
        grad_squares += float((grad * grad).sum().item())
        has_grad = True
    if not has_grad:
        return 0.0
    return float(grad_squares ** 0.5)


def _load_manifest_payload(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _select_manifest_samples(
    *,
    atomic_csv: str,
    synthetic_jsonl: str,
    split_seed: int,
    manifest_payload: dict[str, Any],
) -> tuple[list[Any], list[Any], list[dict[str, Any]]]:
    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=atomic_csv,
        synthetic_jsonl_path=synthetic_jsonl,
        split_seed=split_seed,
    )
    all_samples = bundle.train + bundle.dev + bundle.test
    by_sample_id = {sample.sample_id: sample for sample in all_samples}

    def _materialize(entries: list[dict[str, Any]], section: str) -> list[Any]:
        samples: list[Any] = []
        for entry in entries:
            sample_id = str(entry["sample_id"])
            if sample_id not in by_sample_id:
                raise KeyError(f"manifest sample_id not found in Stage 1 bootstrap: {section}:{sample_id}")
            samples.append(by_sample_id[sample_id])
        return samples

    train_samples = _materialize(list(manifest_payload.get("train_samples", [])), "train_samples")
    dev_samples = _materialize(list(manifest_payload.get("dev_samples", [])), "dev_samples")
    return train_samples, dev_samples, bundle.skipped


def _manifest_audit(train_samples: list[Any], dev_samples: list[Any]) -> dict[str, Any]:
    selected_samples = train_samples + dev_samples
    return {
        "train_count": len(train_samples),
        "dev_count": len(dev_samples),
        "k1_train": sum(1 for sample in train_samples if sample.gold_count == 1),
        "k2_train": sum(1 for sample in train_samples if sample.gold_count == 2),
        "k1_dev": sum(1 for sample in dev_samples if sample.gold_count == 1),
        "k2_dev": sum(1 for sample in dev_samples if sample.gold_count == 2),
        "source_kind_distribution": {
            "atomic_k1": sum(1 for sample in selected_samples if sample.source_kind == "atomic_k1"),
            "synthetic_k2": sum(1 for sample in selected_samples if sample.source_kind == "synthetic_k2"),
        },
    }


def assignment_temperature_for_epoch(*, epoch_index: int, total_epochs: int, tau_start: float, tau_end: float) -> float:
    if total_epochs <= 1:
        return tau_end
    position = epoch_index / max(total_epochs - 1, 1)
    return tau_start + (tau_end - tau_start) * position


def prepare_stage1_sanity_run(
    config: dict[str, Any],
    *,
    cli_synthetic_jsonl: str | None = None,
    cli_atomic_csv: str | None = None,
    cli_output_root: str | None = None,
    cli_manifest_json: str | None = None,
    cli_curriculum_level: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged = _normalize_config(config)
    random.seed(int(merged["seed"]))
    torch.manual_seed(int(merged["seed"]))

    resolved_paths = resolve_stage1_sanity_paths(
        merged,
        cli_synthetic_jsonl=cli_synthetic_jsonl,
        cli_atomic_csv=cli_atomic_csv,
        cli_output_root=cli_output_root,
        env=env,
    )
    output_root = Path(resolved_paths["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_result: dict[str, Any]
    if cli_manifest_json:
        manifest_path = Path(cli_manifest_json)
        manifest_payload = _load_manifest_payload(manifest_path)
        train_samples, dev_samples, skipped_samples = _select_manifest_samples(
            atomic_csv=resolved_paths["atomic_csv"],
            synthetic_jsonl=resolved_paths["synthetic_jsonl"],
            split_seed=int(merged["seed"]),
            manifest_payload=manifest_payload,
        )
        manifest_summary = dict(manifest_payload.get("summary", {}))
        manifest_result = {
            "manifest_path": str(manifest_path),
            "manifest_payload": manifest_payload,
            "manifest_summary": manifest_summary,
            "curriculum_level": cli_curriculum_level or manifest_payload.get("curriculum_level"),
            "audit": _manifest_audit(train_samples, dev_samples),
            "train_samples": train_samples,
            "dev_samples": dev_samples,
            "skipped_samples": skipped_samples,
        }
    else:
        manifest_result = build_stage1_sanity_manifest(
            atomic_csv=resolved_paths["atomic_csv"],
            synthetic_jsonl=resolved_paths["synthetic_jsonl"],
            output_root=output_root,
            reports_root=_repo_root() / "reports",
            max_train_samples=int(merged["max_train_samples"]),
            max_dev_samples=int(merged["max_dev_samples"]),
            split_seed=int(merged["seed"]),
        )
        manifest_result["manifest_summary"] = manifest_result["audit"]
        manifest_result["curriculum_level"] = cli_curriculum_level
        train_samples = manifest_result["train_samples"]
        dev_samples = manifest_result["dev_samples"]
    if not train_samples or not dev_samples:
        raise ValueError("insufficient Stage 1 sanity samples after manifest selection")
    return {
        "config": merged,
        "resolved_paths": resolved_paths,
        "output_root": output_root,
        "manifest_result": manifest_result,
        "train_samples": train_samples,
        "dev_samples": dev_samples,
    }


def build_stage1_model_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "text_vector_dim": TEXT_VECTOR_DIM,
        "dense_feature_dim": len(DENSE_FEATURE_NAMES),
        "hidden_dim": int(config.get("hidden_dim", 64) or 64),
        "kmax": int(config["Kmax"]),
        "use_null_slot": bool(config.get("use_null_slot", False)),
        "use_pairwise_bias": bool(config.get("use_pairwise_bias", True)),
        "assignment_temperature": float(config["assignment_temperature"]),
        "count_pb_coupling_strength": float(config["count_pb_coupling_strength"]),
    }


def fit_stage1_model_with_artifacts(config: dict[str, Any], train_samples: list[Any]) -> dict[str, Any]:
    device = str(config["device"])
    model_config = build_stage1_model_config(config)
    model = MicaModel(**model_config).to(device)
    model.slot_decoder.existence_mass_coupling_strength = float(config["existence_mass_coupling_strength"])
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    scheduler = None

    batch_size = int(config["batch_size"])
    epoch_train_losses: list[float] = []
    training_log_rows: list[dict[str, Any]] = []
    total_epochs = int(config["epochs"])
    global_step = 0
    tau_first = assignment_temperature_for_epoch(
        epoch_index=0,
        total_epochs=total_epochs,
        tau_start=float(config["assignment_tau_start"]),
        tau_end=float(config["assignment_tau_end"]),
    )
    tau_last = assignment_temperature_for_epoch(
        epoch_index=max(total_epochs - 1, 0),
        total_epochs=total_epochs,
        tau_start=float(config["assignment_tau_start"]),
        tau_end=float(config["assignment_tau_end"]),
    )
    for epoch_index in range(total_epochs):
        epoch_tau = assignment_temperature_for_epoch(
            epoch_index=epoch_index,
            total_epochs=total_epochs,
            tau_start=float(config["assignment_tau_start"]),
            tau_end=float(config["assignment_tau_end"]),
        )
        model.slot_decoder.assignment_temperature = epoch_tau
        model.train()
        batch_losses: list[float] = []
        assignment_head_grad_norms: list[float] = []
        slot_decoder_grad_norms: list[float] = []
        slot_query_grad_norms: list[float] = []
        encoder_grad_norms: list[float] = []
        for batch_samples in _batched(train_samples, batch_size, seed=int(config["seed"]) + epoch_index, shuffle=True):
            batch = collate_mica_samples(batch_samples)
            tensor_batch = {
                key: value.to(device) if isinstance(value, torch.Tensor) else value
                for key, value in batch.items()
            }
            output: MicaOutput = model(tensor_batch)
            losses = compute_stage1_losses(
                output,
                tensor_batch,
                lambda_align=float(config["lambda_align"]),
                lambda_count=float(config["lambda_count"]),
                lambda_exist=float(config["lambda_exist"]),
                alpha_pb=float(config["alpha_pb"]),
                lambda_stab=float(config["lambda_stab"]),
                k2_min_second_slot_mass_ratio=float(config["k2_min_second_slot_mass_ratio"]),
                lambda_bg=float(config.get("lambda_bg", 0.0)),
            )
            loss_value = float(losses["loss_total"].item())
            if not torch.isfinite(losses["loss_total"]):
                raise ValueError("Stage 1 sanity loss became non-finite")
            optimizer.zero_grad()
            losses["loss_total"].backward()
            assignment_head_grad_norms.append(_parameter_grad_norm(list(model.slot_decoder.parameters())))
            slot_decoder_grad_norms.append(_parameter_grad_norm(list(model.slot_decoder.parameters())))
            slot_query_grad_norms.append(_parameter_grad_norm([model.slot_decoder.slot_queries]))
            encoder_grad_norms.append(_parameter_grad_norm(list(model.encoder.parameters())))
            optimizer.step()
            global_step += 1
            batch_losses.append(loss_value)
        epoch_loss = sum(batch_losses) / max(len(batch_losses), 1)
        epoch_train_losses.append(epoch_loss)
        training_log_rows.append(
            {
                "epoch": epoch_index + 1,
                "train_loss": epoch_loss,
                "assignment_tau": epoch_tau,
                "assignment_head_grad_norm": float(sum(assignment_head_grad_norms) / max(len(assignment_head_grad_norms), 1)),
                "slot_decoder_grad_norm": float(sum(slot_decoder_grad_norms) / max(len(slot_decoder_grad_norms), 1)),
                "slot_query_grad_norm": float(sum(slot_query_grad_norms) / max(len(slot_query_grad_norms), 1)),
                "encoder_grad_norm": float(sum(encoder_grad_norms) / max(len(encoder_grad_norms), 1)),
                "global_step": global_step,
            }
        )
        if scheduler is not None:
            scheduler.step()
    model.slot_decoder.assignment_temperature = tau_last
    return {
        "model": model,
        "model_config": model_config,
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict() if scheduler is not None else {},
        "scheduler_enabled": scheduler is not None,
        "epoch_train_losses": epoch_train_losses,
        "training_log_rows": training_log_rows,
        "global_step": global_step,
        "epochs_completed": total_epochs,
    }


def fit_stage1_sanity_model(config: dict[str, Any], train_samples: list[Any]) -> tuple[MicaModel, list[float], list[dict[str, Any]]]:
    result = fit_stage1_model_with_artifacts(config, train_samples)
    return result["model"], result["epoch_train_losses"], result["training_log_rows"]


def _write_sanity_summary_reports(result: dict[str, Any], reports_root: Path) -> None:
    reports_root.mkdir(parents=True, exist_ok=True)
    summary = {
        "training_run": bool(result["training_run"]),
        "sanity_only": True,
        "synthetic_source": "local_runtime_only",
        "synthetic_source_committed": False,
        "local_runtime_only_path_available": True,
        "max_train_samples": int(result["config"]["max_train_samples"]),
        "max_dev_samples": int(result["config"]["max_dev_samples"]),
        "epochs": int(result["config"]["epochs"]),
        "batch_size": int(result["config"]["batch_size"]),
        "device": str(result["config"]["device"]),
        "curriculum_level": result.get("curriculum_level"),
        "manifest_path_runtime_only": result.get("manifest_path_runtime_only"),
        "manifest_summary": result.get("manifest_summary"),
        "assignment_temperature": float(result["config"]["assignment_temperature"]),
        "assignment_tau_first_epoch": float(result["config"]["assignment_tau_first_epoch"]),
        "assignment_tau_last_epoch": float(result["config"]["assignment_tau_last_epoch"]),
        "existence_mass_coupling_strength": float(result["config"]["existence_mass_coupling_strength"]),
        "count_pb_coupling_strength": float(result["config"]["count_pb_coupling_strength"]),
        "with_stabilizer": bool(result["config"]["with_stabilizer"]),
        "lambda_stab": float(result["config"]["lambda_stab"]),
        "train_loss_first_epoch": float(result["train_loss_first_epoch"]),
        "train_loss_last_epoch": float(result["train_loss_last_epoch"]),
        "dev_loss": float(result["dev_loss"]),
        "count_accuracy": float(result["count_accuracy"]),
        "binary_multi_accuracy": float(result["binary_multi_accuracy"]),
        "over_split_rate_on_k1": float(result["over_split_rate_on_k1"]),
        "under_split_rate_on_k2": float(result["under_split_rate_on_k2"]),
        "slot_collapse_rate": float(result["slot_collapse_rate"]),
        "assignment_entropy": float(result["assignment_entropy"]),
        "oracle_k_alignment_pairwise_f1": float(result["oracle_k_alignment_pairwise_f1"]),
        "predicted_k_alignment_pairwise_f1": float(result["predicted_k_alignment_pairwise_f1"]),
        "unit_accuracy_hungarian": float(result["unit_accuracy_hungarian"]),
        "hunk_accuracy_hungarian": float(result["hunk_accuracy_hungarian"]),
        "macro_intent_f1_hungarian": float(result["macro_intent_f1_hungarian"]),
        "micro_intent_f1_hungarian": float(result["micro_intent_f1_hungarian"]),
        "per_intent_recall_mean": float(result["per_intent_recall_mean"]),
        "per_intent_precision_mean": float(result["per_intent_precision_mean"]),
        "k2_split_recall": float(result["k2_split_recall"]),
        "second_slot_gold_recall": float(result["second_slot_gold_recall"]),
        "second_slot_assignment_mass": float(result["second_slot_assignment_mass"]),
        "foreground_slot_usage_count": float(result["foreground_slot_usage_count"]),
        "effective_slot_count_mean": float(result["effective_slot_count_mean"]),
        "assignment_top1_nonprimary_fraction": float(result["assignment_top1_nonprimary_fraction"]),
        "all_one_unit_accuracy": float(result["all_one_unit_accuracy"]),
        "file_path_unit_accuracy": float(result["file_path_unit_accuracy"]),
        "random_gold_k_unit_accuracy_mean": float(result["random_gold_k_unit_accuracy_mean"]),
        "all_one_macro_intent_f1": float(result["all_one_macro_intent_f1"]),
        "file_path_macro_intent_f1": float(result["file_path_macro_intent_f1"]),
        "random_gold_k_macro_intent_f1_mean": float(result["random_gold_k_macro_intent_f1_mean"]),
        "alignment_pairwise_f1_all_one_cluster": float(result["alignment_pairwise_f1_all_one_cluster"]),
        "alignment_pairwise_f1_file_path_baseline": float(result["alignment_pairwise_f1_file_path_baseline"]),
        "alignment_pairwise_f1_random_gold_k_mean": float(result["alignment_pairwise_f1_random_gold_k_mean"]),
        "alignment_gain_over_all_one": float(result["alignment_gain_over_all_one"]),
        "alignment_gain_over_file_path": float(result["alignment_gain_over_file_path"]),
        "alignment_gain_over_random_gold_k": float(result["alignment_gain_over_random_gold_k"]),
        "attribution_gain": bool(result["attribution_gain"]),
        "sanity_status": str(result["sanity_status"]),
        "failure_or_warning_notes": list(result["failure_or_warning_notes"]),
        "next_recommended_action": str(result["next_recommended_action"]),
    }
    comparison_metrics = [
        "count_accuracy",
        "binary_multi_accuracy",
        "over_split_rate_on_k1",
        "under_split_rate_on_k2",
        "slot_collapse_rate",
        "assignment_entropy",
        "oracle_k_alignment_pairwise_f1",
        "predicted_k_alignment_pairwise_f1",
        "alignment_gain_over_all_one",
        "alignment_gain_over_file_path",
        "alignment_gain_over_random_gold_k",
    ]
    previous_summary: dict[str, Any] | None = None
    try:
        previous_raw = subprocess.run(
            ["git", "show", "a294243:reports/mica_stage1_sanity_result.json"],
            cwd=_repo_root(),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        previous_summary = json.loads(previous_raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        previous_summary = None
    if previous_summary is not None:
        summary["comparison_to_previous_a294243"] = {
            metric: {
                "previous": float(previous_summary[metric]),
                "current": float(summary[metric]),
                "delta": float(summary[metric]) - float(previous_summary[metric]),
            }
            for metric in comparison_metrics
            if metric in previous_summary and metric in summary
        }
    json_path = reports_root / "mica_stage1_sanity_result.json"
    md_path = reports_root / "mica_stage1_sanity_result.md"
    _write_json(json_path, summary)
    lines = [
        "# MICA Stage 1 Sanity Result",
        "",
        f"- training_run: {str(summary['training_run']).lower()}",
        f"- sanity_only: true",
        f"- synthetic_source: {summary['synthetic_source']}",
        f"- synthetic_source_committed: false",
        f"- local_runtime_only_path_available: {str(summary['local_runtime_only_path_available']).lower()}",
        f"- max_train_samples: {summary['max_train_samples']}",
        f"- max_dev_samples: {summary['max_dev_samples']}",
        f"- epochs: {summary['epochs']}",
        f"- batch_size: {summary['batch_size']}",
        f"- device: {summary['device']}",
        f"- curriculum_level: {summary['curriculum_level']}",
        f"- assignment_temperature: {summary['assignment_temperature']:.3f}",
        f"- assignment_tau_first_epoch: {summary['assignment_tau_first_epoch']:.3f}",
        f"- assignment_tau_last_epoch: {summary['assignment_tau_last_epoch']:.3f}",
        f"- existence_mass_coupling_strength: {summary['existence_mass_coupling_strength']:.3f}",
        f"- count_pb_coupling_strength: {summary['count_pb_coupling_strength']:.3f}",
        f"- with_stabilizer: {str(summary['with_stabilizer']).lower()}",
        f"- lambda_stab: {summary['lambda_stab']:.3f}",
        f"- train_loss_first_epoch: {summary['train_loss_first_epoch']:.6f}",
        f"- train_loss_last_epoch: {summary['train_loss_last_epoch']:.6f}",
        f"- dev_loss: {summary['dev_loss']:.6f}",
        f"- count_accuracy: {summary['count_accuracy']:.6f}",
        f"- binary_multi_accuracy: {summary['binary_multi_accuracy']:.6f}",
        f"- over_split_rate_on_k1: {summary['over_split_rate_on_k1']:.6f}",
        f"- under_split_rate_on_k2: {summary['under_split_rate_on_k2']:.6f}",
        f"- slot_collapse_rate: {summary['slot_collapse_rate']:.6f}",
        f"- assignment_entropy: {summary['assignment_entropy']:.6f}",
        f"- oracle_k_alignment_pairwise_f1: {summary['oracle_k_alignment_pairwise_f1']:.6f}",
        f"- predicted_k_alignment_pairwise_f1: {summary['predicted_k_alignment_pairwise_f1']:.6f}",
        f"- unit_accuracy_hungarian: {summary['unit_accuracy_hungarian']:.6f}",
        f"- hunk_accuracy_hungarian: {summary['hunk_accuracy_hungarian']:.6f}",
        f"- macro_intent_f1_hungarian: {summary['macro_intent_f1_hungarian']:.6f}",
        f"- micro_intent_f1_hungarian: {summary['micro_intent_f1_hungarian']:.6f}",
        f"- per_intent_recall_mean: {summary['per_intent_recall_mean']:.6f}",
        f"- per_intent_precision_mean: {summary['per_intent_precision_mean']:.6f}",
        f"- k2_split_recall: {summary['k2_split_recall']:.6f}",
        f"- second_slot_gold_recall: {summary['second_slot_gold_recall']:.6f}",
        f"- second_slot_assignment_mass: {summary['second_slot_assignment_mass']:.6f}",
        f"- foreground_slot_usage_count: {summary['foreground_slot_usage_count']:.6f}",
        f"- effective_slot_count_mean: {summary['effective_slot_count_mean']:.6f}",
        f"- assignment_top1_nonprimary_fraction: {summary['assignment_top1_nonprimary_fraction']:.6f}",
        f"- all_one_unit_accuracy: {summary['all_one_unit_accuracy']:.6f}",
        f"- file_path_unit_accuracy: {summary['file_path_unit_accuracy']:.6f}",
        f"- random_gold_k_unit_accuracy_mean: {summary['random_gold_k_unit_accuracy_mean']:.6f}",
        f"- all_one_macro_intent_f1: {summary['all_one_macro_intent_f1']:.6f}",
        f"- file_path_macro_intent_f1: {summary['file_path_macro_intent_f1']:.6f}",
        f"- random_gold_k_macro_intent_f1_mean: {summary['random_gold_k_macro_intent_f1_mean']:.6f}",
        f"- alignment_pairwise_f1_all_one_cluster: {summary['alignment_pairwise_f1_all_one_cluster']:.6f}",
        f"- alignment_pairwise_f1_file_path_baseline: {summary['alignment_pairwise_f1_file_path_baseline']:.6f}",
        f"- alignment_pairwise_f1_random_gold_k_mean: {summary['alignment_pairwise_f1_random_gold_k_mean']:.6f}",
        f"- alignment_gain_over_all_one: {summary['alignment_gain_over_all_one']:.6f}",
        f"- alignment_gain_over_file_path: {summary['alignment_gain_over_file_path']:.6f}",
        f"- alignment_gain_over_random_gold_k: {summary['alignment_gain_over_random_gold_k']:.6f}",
        f"- attribution_gain: {str(summary['attribution_gain']).lower()}",
        f"- sanity_status: {summary['sanity_status']}",
        "",
        "## Notes",
        "",
    ]
    for note in summary["failure_or_warning_notes"]:
        lines.append(f"- {note}")
    if "comparison_to_previous_a294243" in summary:
        lines.extend(
            [
                "",
                "## Comparison to a294243",
                "",
            ]
        )
        for metric, payload in summary["comparison_to_previous_a294243"].items():
            lines.append(
                f"- {metric}: previous={payload['previous']:.6f}, current={payload['current']:.6f}, delta={payload['delta']:.6f}"
            )
    lines.extend(
        [
            "",
            "## Next Recommended Action",
            "",
            f"- {summary['next_recommended_action']}",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage1_sanity(
    config: dict[str, Any],
    *,
    cli_synthetic_jsonl: str | None = None,
    cli_atomic_csv: str | None = None,
    cli_output_root: str | None = None,
    cli_manifest_json: str | None = None,
    cli_curriculum_level: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    prepared = prepare_stage1_sanity_run(
        config,
        cli_synthetic_jsonl=cli_synthetic_jsonl,
        cli_atomic_csv=cli_atomic_csv,
        cli_output_root=cli_output_root,
        cli_manifest_json=cli_manifest_json,
        cli_curriculum_level=cli_curriculum_level,
        env=env,
    )
    merged = prepared["config"]
    output_root: Path = prepared["output_root"]
    manifest_result = prepared["manifest_result"]
    train_samples = prepared["train_samples"]
    dev_samples = prepared["dev_samples"]
    batch_size = int(merged["batch_size"])
    model, epoch_train_losses, training_log_rows = fit_stage1_sanity_model(merged, train_samples)

    metrics = evaluate_model(model, dev_samples, batch_size=batch_size, device=str(merged["device"]))
    _write_jsonl(output_root / "training_log.jsonl", training_log_rows)
    _write_jsonl(output_root / "dev_predictions_sample.jsonl", metrics["dev_predictions"])

    selected_samples = train_samples + dev_samples
    source_kind_distribution: dict[str, int] = {}
    for sample in selected_samples:
        source_kind_distribution[sample.source_kind] = source_kind_distribution.get(sample.source_kind, 0) + 1

    result: dict[str, Any] = {
        "training_run": True,
        "training_not_run": False,
        "sanity_only": bool(merged["sanity_only"]),
        "synthetic_source": "local_runtime_only",
        "synthetic_source_committed": False,
        "local_runtime_only_path_available": True,
        "config": {
            "max_train_samples": int(merged["max_train_samples"]),
            "max_dev_samples": int(merged["max_dev_samples"]),
            "batch_size": int(merged["batch_size"]),
            "epochs": int(merged["epochs"]),
            "Kmax": int(merged["Kmax"]),
            "learning_rate": float(merged["learning_rate"]),
            "device": str(merged["device"]),
            "assignment_temperature": float(merged["assignment_temperature"]),
            "assignment_tau_first_epoch": assignment_temperature_for_epoch(
                epoch_index=0,
                total_epochs=int(merged["epochs"]),
                tau_start=float(merged["assignment_tau_start"]),
                tau_end=float(merged["assignment_tau_end"]),
            ),
            "assignment_tau_last_epoch": assignment_temperature_for_epoch(
                epoch_index=max(int(merged["epochs"]) - 1, 0),
                total_epochs=int(merged["epochs"]),
                tau_start=float(merged["assignment_tau_start"]),
                tau_end=float(merged["assignment_tau_end"]),
            ),
            "existence_mass_coupling_strength": float(merged["existence_mass_coupling_strength"]),
            "count_pb_coupling_strength": float(merged["count_pb_coupling_strength"]),
            "with_stabilizer": float(merged["lambda_stab"]) > 0.0,
            "lambda_stab": float(merged["lambda_stab"]),
        },
        "train_loss_first_epoch": epoch_train_losses[0],
        "train_loss_last_epoch": epoch_train_losses[-1],
        "train_loss": epoch_train_losses[-1],
        "dev_loss": metrics["dev_loss"],
        "count_accuracy": metrics["count_accuracy"],
        "binary_multi_accuracy": metrics["binary_multi_accuracy"],
        "over_split_rate_on_k1": metrics["over_split_rate_on_k1"],
        "under_split_rate_on_k2": metrics["under_split_rate_on_k2"],
        "slot_collapse_rate": metrics["slot_collapse_rate"],
        "assignment_entropy": metrics["assignment_entropy"],
        "oracle_k_alignment_pairwise_f1": metrics["oracle_k_alignment_pairwise_f1"],
        "predicted_k_alignment_pairwise_f1": metrics["predicted_k_alignment_pairwise_f1"],
        "unit_accuracy_hungarian": metrics["unit_accuracy_hungarian"],
        "hunk_accuracy_hungarian": metrics["hunk_accuracy_hungarian"],
        "macro_intent_f1_hungarian": metrics["macro_intent_f1_hungarian"],
        "micro_intent_f1_hungarian": metrics["micro_intent_f1_hungarian"],
        "per_intent_recall_mean": metrics["per_intent_recall_mean"],
        "per_intent_precision_mean": metrics["per_intent_precision_mean"],
        "k2_split_recall": metrics["k2_split_recall"],
        "second_slot_gold_recall": metrics["second_slot_gold_recall"],
        "second_slot_assignment_mass": metrics["second_slot_assignment_mass"],
        "foreground_slot_usage_count": metrics["foreground_slot_usage_count"],
        "effective_slot_count_mean": metrics["effective_slot_count_mean"],
        "assignment_top1_nonprimary_fraction": metrics["assignment_top1_nonprimary_fraction"],
        "all_one_unit_accuracy": metrics["all_one_unit_accuracy"],
        "file_path_unit_accuracy": metrics["file_path_unit_accuracy"],
        "random_gold_k_unit_accuracy_mean": metrics["random_gold_k_unit_accuracy_mean"],
        "all_one_macro_intent_f1": metrics["all_one_macro_intent_f1"],
        "file_path_macro_intent_f1": metrics["file_path_macro_intent_f1"],
        "random_gold_k_macro_intent_f1_mean": metrics["random_gold_k_macro_intent_f1_mean"],
        "alignment_pairwise_f1_all_one_cluster": metrics["alignment_pairwise_f1_all_one_cluster"],
        "alignment_pairwise_f1_file_path_baseline": metrics["alignment_pairwise_f1_file_path_baseline"],
        "alignment_pairwise_f1_random_gold_k_mean": metrics["alignment_pairwise_f1_random_gold_k_mean"],
        "alignment_gain_over_all_one": metrics["alignment_gain_over_all_one"],
        "alignment_gain_over_file_path": metrics["alignment_gain_over_file_path"],
        "alignment_gain_over_random_gold_k": metrics["alignment_gain_over_random_gold_k"],
        "attribution_gain": metrics["attribution_gain"],
        "count_majority_baseline": metrics["count_majority_baseline"],
        "trivial_pairwise_f1_baseline": metrics["trivial_pairwise_f1_baseline"],
        "all_same_count_prediction": metrics["all_same_count_prediction"],
        "predicted_count_distribution": metrics["predicted_count_distribution"],
        "train_sample_count": len(train_samples),
        "dev_sample_count": len(dev_samples),
        "k1_train": manifest_result["audit"]["k1_train"],
        "k2_train": manifest_result["audit"]["k2_train"],
        "k1_dev": manifest_result["audit"]["k1_dev"],
        "k2_dev": manifest_result["audit"]["k2_dev"],
        "source_kind_distribution": source_kind_distribution,
        "source_stats": manifest_result["audit"],
        "curriculum_level": manifest_result.get("curriculum_level"),
        "manifest_path_runtime_only": manifest_result.get("manifest_path"),
        "manifest_summary": manifest_result.get("manifest_summary", manifest_result["audit"]),
        "skipped_samples_preview": manifest_result["skipped_samples"][:20],
    }
    sanity_status, notes = decide_sanity_status(result)
    result["sanity_status"] = sanity_status
    result["failure_or_warning_notes"] = notes
    result["next_recommended_action"] = {
        "passed": "freeze formal Stage 1 protocol and prepare a non-local split before any Stage 2 work",
        "failed": "debug training collapse or data issues before attempting any Stage 2 calibration",
        "inconclusive": "inspect metrics and sample mix, then tighten Stage 1 data or model before Stage 2",
    }[sanity_status]
    _write_json(output_root / "metrics.json", result)
    _write_sanity_summary_reports(result, output_root / "reports")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MICA-v3 Stage 1 sanity training loop.")
    parser.add_argument("--config", default="code/mica/configs/mica_stage1_sanity.yaml")
    parser.add_argument("--synthetic-jsonl")
    parser.add_argument("--atomic-csv")
    parser.add_argument("--output-root")
    parser.add_argument("--manifest-json")
    parser.add_argument("--curriculum-level", choices=["easy", "medium", "hard"])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        result = run_stage1_sanity(
            config,
            cli_synthetic_jsonl=args.synthetic_jsonl,
            cli_atomic_csv=args.atomic_csv,
            cli_output_root=args.output_root,
            cli_manifest_json=args.manifest_json,
            cli_curriculum_level=args.curriculum_level,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
