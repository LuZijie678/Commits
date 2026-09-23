from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.data.stage2_mixture import build_stage2_mixture_manifest
from code.mica.config_validation import validate_stage2_spec
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.losses.consistency_losses import high_confidence_consistency_loss
from code.mica.losses.stage2_losses import hard_b_loss, m_censored_loss, stage2_combined_loss, strict_replay_loss
from code.mica.reporting import build_stage2_calibration_report, build_stage2_tradeoff_report
from code.mica.run_manifest import assert_no_forbidden_training_flags, assert_stage2_not_training_without_approval, build_run_manifest
from code.mica.selective_risk import build_dev_selective_calibration_artifact
from code.mica.stages.stage2_real_calibration import (
    build_stage2_freeze_plan,
    build_stage2_lr_plan,
    build_stage2_training_plan,
    prepare_stage2_real_calibration,
    validate_stage2_training_plan,
)
from code.mica.training.batch_adapters import (
    adapt_hard_b_batch,
    adapt_m_weak_batch,
    adapt_real_alignment_batch,
    adapt_strict_replay_batch,
    validate_train_batch,
)
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.models.mica_model import MicaModel
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import build_checkpoint_payload, build_checkpoint_plan, load_checkpoint, save_checkpoint, validate_checkpoint_payload
from code.mica.training.loop_engine import run_train_epoch
from code.mica.training.train_loop import summarize_train_loop_capabilities


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 2 real-domain calibration runner.")
    parser.add_argument("--stage2-spec", required=True)
    parser.add_argument("--strict-replay-manifest", required=True)
    parser.add_argument("--hard-b-train", required=True)
    parser.add_argument("--hard-b-dev", required=True)
    parser.add_argument("--m-weak-train", required=True)
    parser.add_argument("--m-weak-dev", required=True)
    parser.add_argument("--m-align-calib")
    parser.add_argument("--m-final-test")
    parser.add_argument("--hard-b-test")
    parser.add_argument("--real-domain-split-test")
    parser.add_argument("--real-domain-selective-test")
    parser.add_argument("--asset-registry")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--implementation-check-only", action="store_true")
    parser.add_argument("--advisor-approved", action="store_true")
    return parser


def run_stage2_calibration(
    *,
    stage2_spec_path: str | Path,
    strict_replay_manifest: str | Path,
    hard_b_train_path: str | Path,
    hard_b_dev_path: str | Path,
    m_weak_train_path: str | Path,
    m_weak_dev_path: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    train: bool = False,
    implementation_check_only: bool = False,
    advisor_approved: bool = False,
    m_align_calib_path: str | Path | None = None,
    m_final_test_path: str | Path | None = None,
    hard_b_test_path: str | Path | None = None,
    real_domain_split_test_path: str | Path | None = None,
    real_domain_selective_test_path: str | Path | None = None,
    asset_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    if not dry_run and not train:
        raise ValueError("Stage 2 calibration runner requires explicit --dry-run or guarded --train.")

    spec = read_json(stage2_spec_path)
    spec_validation = validate_stage2_spec(spec)
    if spec_validation["errors"]:
        raise ValueError("; ".join(spec_validation["errors"]))
    if advisor_approved:
        spec = {**spec, "advisor_stage2_approved": True}
    assert_stage2_not_training_without_approval(spec, train)
    asset_registry = _build_stage2_runtime_asset_registry(
        explicit_registry_path=asset_registry_path,
        strict_replay_manifest=strict_replay_manifest,
        hard_b_train_path=hard_b_train_path,
        hard_b_dev_path=hard_b_dev_path,
        m_weak_train_path=m_weak_train_path,
        m_weak_dev_path=m_weak_dev_path,
        m_align_calib_path=m_align_calib_path,
        m_final_test_path=m_final_test_path,
        hard_b_test_path=hard_b_test_path,
        real_domain_split_test_path=real_domain_split_test_path,
        real_domain_selective_test_path=real_domain_selective_test_path,
    )
    asset_registry_validation = validate_asset_registry(asset_registry)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage2_calibration",
        config_paths=[str(stage2_spec_path)],
        asset_registry_path=str(asset_registry_path) if asset_registry_path is not None else None,
        seed=int(spec.get("seed", 0) or 0),
        mode="train" if train else "dry_run",
        advisor_approval=bool(spec.get("advisor_stage2_approved", False)),
    )

    source_manifests = {
        "strict_replay": _load_rows(strict_replay_manifest),
        "hard_b_train": _load_rows(hard_b_train_path),
        "hard_b_dev": _load_rows(hard_b_dev_path),
        "m_weak_train": _load_rows(m_weak_train_path),
        "m_weak_dev": _load_rows(m_weak_dev_path),
    }
    if m_align_calib_path is not None:
        source_manifests["m_align_calib"] = _load_rows(m_align_calib_path)
    if m_final_test_path is not None:
        source_manifests["m_final_test"] = _load_rows(m_final_test_path)
    if hard_b_test_path is not None:
        source_manifests["hard_b_test"] = _load_rows(hard_b_test_path)
    if real_domain_split_test_path is not None:
        source_manifests["real_domain_split_test"] = _load_rows(real_domain_split_test_path)
    if real_domain_selective_test_path is not None:
        source_manifests["real_domain_selective_test"] = _load_rows(real_domain_selective_test_path)

    stage_summary = prepare_stage2_real_calibration(spec, source_manifests)
    training_plan = build_stage2_training_plan(spec, stage_summary)
    training_plan_validation = validate_stage2_training_plan(training_plan)
    freeze_plan_first = build_stage2_freeze_plan(spec, phase="first_half")
    freeze_plan_second = build_stage2_freeze_plan(spec, phase="second_half")
    lr_plan = build_stage2_lr_plan(spec, base_lr=float(spec.get("base_lr", 1e-3)))
    output_root_path = Path(output_root)
    checkpoint_plan = build_checkpoint_plan(str(output_root_path / "checkpoints"), save_every_n_steps=None, keep_last_k=1)
    selective_calibration_artifact = _build_stage2_selective_calibration_artifact(spec, source_manifests)
    selective_dev_rows = _build_stage2_selective_dev_rows(source_manifests)
    selective_metrics_artifact = _build_stage2_selective_metrics_artifact(selective_dev_rows)
    adapter_availability = {
        "strict_replay": callable(adapt_strict_replay_batch),
        "hard_b": callable(adapt_hard_b_batch),
        "m_weak": callable(adapt_m_weak_batch),
        "m_align_calib": callable(adapt_real_alignment_batch),
    }
    implementation_capabilities = summarize_train_loop_capabilities(implementation_only=bool(implementation_check_only or train))
    if train:
        epoch = _run_guarded_stage2_training_check(spec, source_manifests, freeze_plan_first)
        checkpoint_payload = _save_stage2_checkpoint(
            output_root_path=output_root_path,
            spec=spec,
            asset_registry=asset_registry,
            epoch=epoch,
            freeze_plan=freeze_plan_first,
        )
        implementation_capabilities = {
            **implementation_capabilities,
            "trainer_backend_executed": True,
            "trainer_backend_type": "MicaModelBackendAdapter",
            "toy_backend_used": False,
        }
        return build_run_manifest(
            stage="stage2_real_domain_count_calibration",
            mode="implementation_check_only" if implementation_check_only else "train",
            output_root=None,
            flags={
                "training_enabled": True,
                "training_executed": True,
                "stage2_training_executed": True,
                "implementation_check_only": bool(implementation_check_only),
                "advisor_approved": bool(spec.get("advisor_stage2_approved", False)),
                "trainer_backend_executed": True,
                "trainer_backend_type": "MicaModelBackendAdapter",
                "toy_backend_used": False,
                "stage2_allowed": False,
                "m_final_test_used_for_training": False,
                "hard_b_test_used_for_training": False,
                "real_domain_split_test_used_for_training": False,
                "real_domain_selective_test_used_for_training": False,
                "checkpoint_written": True,
                "checkpoint_path": str(output_root_path / "checkpoints" / "stage2_epoch_1.ckpt.json"),
                "checkpoint_valid": validate_checkpoint_payload(checkpoint_payload)["valid"],
                "asset_registry_validation": asset_registry_validation,
                "asset_registry_snapshot": asset_registry,
                "selective_risk_threshold_status": selective_calibration_artifact["threshold"]["status"],
                "selective_risk_values_status": selective_calibration_artifact["values_status"],
                "epoch": {
                    "step_count": epoch.step_count,
                    "gradient_step_count": epoch.gradient_step_count,
                    "nan_step_count": epoch.nan_step_count,
                    "mean_loss": epoch.mean_loss,
                    "source_kind_counts": epoch.source_kind_counts,
                    "diagnostics": epoch.diagnostics,
                },
                "metadata": {
                    "spec_validation": spec_validation,
                    "training_plan_valid": training_plan_validation,
                    "freeze_plan_first_half": asdict(freeze_plan_first),
                    "freeze_plan_second_half": asdict(freeze_plan_second),
                    "lr_plan": asdict(lr_plan),
                    "checkpoint_plan": asdict(checkpoint_plan),
                    "selective_risk_calibration": selective_calibration_artifact,
                    "selective_risk_metrics": selective_metrics_artifact,
                    "adapter_availability": adapter_availability,
                    "implementation_capabilities": implementation_capabilities,
                    "experiment_manifest": experiment_manifest,
                },
            },
            inputs={
                "stage2_spec": stage2_spec_path,
                "strict_replay_manifest": strict_replay_manifest,
                "hard_b_train": hard_b_train_path,
                "hard_b_dev": hard_b_dev_path,
                "m_weak_train": m_weak_train_path,
                "m_weak_dev": m_weak_dev_path,
            },
        )

    loss_availability = {
        "hard_b_loss_available": callable(hard_b_loss),
        "m_censored_loss_available": callable(m_censored_loss),
        "strict_replay_loss_available": callable(strict_replay_loss),
        "combined_loss_available": callable(stage2_combined_loss),
        "consistency_loss_available": callable(high_confidence_consistency_loss),
        "consistency_default_enabled": bool(spec.get("consistency", {}).get("enabled", False)),
    }
    manifest = build_run_manifest(
        stage="stage2_real_domain_count_calibration",
        mode="dry_run" if dry_run else "train",
        output_root=str(output_root),
        flags={
            "dry_run": True,
            "stage2_training_executed": False,
            "training_entry_prepared": True,
            "advisor_approval_required": True,
            "m_final_test_used_for_training": False,
            "hard_b_test_used_for_training": False,
            "real_domain_split_test_used_for_training": False,
            "real_domain_selective_test_used_for_training": False,
            "thresholds_tuned": False,
            "selective_risk_threshold_status": selective_calibration_artifact["threshold"]["status"],
            "selective_risk_values_status": selective_calibration_artifact["values_status"],
            "asset_registry_validation": asset_registry_validation,
            "asset_registry_snapshot": asset_registry,
            "selective_risk_dev_row_count": len(selective_dev_rows),
            "advisor_stage2_approved": bool(spec.get("advisor_stage2_approved", False)),
            "loss_availability": loss_availability,
            "metadata": {
                "spec_validation": spec_validation,
                "training_plan_valid": training_plan_validation,
                "freeze_plan_first_half": asdict(freeze_plan_first),
                "freeze_plan_second_half": asdict(freeze_plan_second),
                "lr_plan": asdict(lr_plan),
                "checkpoint_plan": asdict(checkpoint_plan),
                "selective_risk_calibration": selective_calibration_artifact,
                "selective_risk_metrics": selective_metrics_artifact,
                "adapter_availability": adapter_availability,
                "implementation_capabilities": implementation_capabilities,
                "experiment_manifest": experiment_manifest,
            },
        },
        inputs={
            "stage2_spec": stage2_spec_path,
            "strict_replay_manifest": strict_replay_manifest,
            "hard_b_train": hard_b_train_path,
            "hard_b_dev": hard_b_dev_path,
            "m_weak_train": m_weak_train_path,
            "m_weak_dev": m_weak_dev_path,
        },
    )
    assert_no_forbidden_training_flags(manifest)
    stage2_tradeoff_report = build_stage2_tradeoff_report([_build_stage2_tradeoff_row(stage_summary)])
    stage2_calibration_report = build_stage2_calibration_report([_build_stage2_calibration_row(stage_summary)])
    write_json(output_root_path / "stage2_calibration_manifest.json", manifest)
    write_json(output_root_path / "stage2_runtime_asset_registry.json", asset_registry)
    write_json(output_root_path / "stage2_asset_registry_validation.json", asset_registry_validation)
    write_json(output_root_path / "stage2_mixture_summary.json", stage_summary)
    write_json(output_root_path / "stage2_selective_risk_dev_rows.json", {"rows": selective_dev_rows})
    write_json(output_root_path / "stage2_selective_risk_calibration_artifact.json", selective_calibration_artifact)
    write_json(output_root_path / "stage2_selective_risk_metrics_artifact.json", selective_metrics_artifact)
    write_json(output_root_path / "stage2_tradeoff_report.json", stage2_tradeoff_report)
    write_json(output_root_path / "stage2_calibration_report.json", stage2_calibration_report)
    return manifest


def _build_stage2_tradeoff_row(stage_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "values_to_be_populated_by_dev_calibration_script",
        "paper_readiness": "not_final_paper_ready_until_populated",
        "hard_b_fpr": None,
        "hard_b_top1_retained_foreground_mass": None,
        "hard_b_residual_foreground_mass": None,
        "hard_b_background_swallowing_rate": None,
        "m_recall": None,
        "strict_replay_forgetting": None,
        "active_slot_count_distribution": {},
        "source_dataset_roles": stage_summary.get("dataset_roles", {}),
        "note": "Dry-run materializes the report contract only; hard_b compactness values require backend dev outputs and no assignment compactness loss is added.",
    }


def _build_stage2_calibration_row(stage_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "values_to_be_populated_by_dev_calibration_script",
        "paper_readiness": "not_final_paper_ready_until_populated",
        "mean_abs_gap": None,
        "count_ece": None,
        "p_count_pb_gap": None,
        "active_slot_count_distribution": {},
        "source_dataset_roles": stage_summary.get("dataset_roles", {}),
        "final_test_tuning": "forbidden",
    }


def _build_stage2_selective_calibration_artifact(spec: dict[str, Any], source_manifests: dict[str, Any]) -> dict[str, Any]:
    selective_spec = dict(spec.get("selective_risk", {}))
    dev_rows = []
    for row in _rows_for_selective_calibration(source_manifests.get("hard_b_dev"), split="dev"):
        dev_rows.append(row)
    for row in _rows_for_selective_calibration(source_manifests.get("m_weak_dev"), split="dev"):
        dev_rows.append(row)
    return build_dev_selective_calibration_artifact(
        dev_rows,
        target_coverage=selective_spec.get("target_coverage"),
        target_risk=selective_spec.get("target_risk"),
    )


def _build_stage2_selective_dev_rows(source_manifests: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_rows_for_selective_calibration(source_manifests.get("hard_b_dev"), split="dev"))
    rows.extend(_rows_for_selective_calibration(source_manifests.get("m_weak_dev"), split="dev"))
    return rows


def _build_stage2_selective_metrics_artifact(dev_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored_rows = [row for row in dev_rows if row.get("risk_score") is not None]
    covered_rows = [row for row in scored_rows if "covered" in row or "abstained" in row]
    risks = [float(row["risk_score"]) for row in scored_rows]
    return {
        "artifact_type": "stage2_selective_risk_dev_metrics",
        "status": "populated_from_dev_only" if scored_rows else "values_to_be_populated_by_dev_calibration_script",
        "selection_split": "dev_only",
        "final_test_tuning": "forbidden",
        "dev_row_count": len(dev_rows),
        "dev_risk_score_count": len(scored_rows),
        "dev_release_decision_count": len(covered_rows),
        "mean_risk_score": (sum(risks) / len(risks)) if risks else None,
        "min_risk_score": min(risks) if risks else None,
        "max_risk_score": max(risks) if risks else None,
        "paper_readiness": "protocol_defined" if scored_rows else "not_final_paper_ready_until_dev_risk_rows_are_populated",
    }


def _rows_for_selective_calibration(payload: Any, *, split: str) -> list[dict[str, Any]]:
    rows = _rows_for_training(payload)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        copied.setdefault("split", split)
        normalized.append(copied)
    return normalized


def _build_stage2_runtime_asset_registry(
    *,
    explicit_registry_path: str | Path | None,
    strict_replay_manifest: str | Path,
    hard_b_train_path: str | Path,
    hard_b_dev_path: str | Path,
    m_weak_train_path: str | Path,
    m_weak_dev_path: str | Path,
    m_align_calib_path: str | Path | None,
    m_final_test_path: str | Path | None,
    hard_b_test_path: str | Path | None,
    real_domain_split_test_path: str | Path | None,
    real_domain_selective_test_path: str | Path | None,
) -> dict[str, Any]:
    if explicit_registry_path is not None:
        return load_asset_registry(str(explicit_registry_path))
    assets = {
        "strict_replay": _asset_entry(strict_replay_manifest, required_for=["stage2_train"], allowed_stages=["stage2_replay"], eval_only=False),
        "hard_b_train": _asset_entry(hard_b_train_path, required_for=["stage2_train"], allowed_stages=["stage2_train"], eval_only=False),
        "hard_b_dev": _asset_entry(hard_b_dev_path, required_for=["stage2_dev", "stage2_tuning"], allowed_stages=["stage2_dev"], eval_only=False),
        "m_weak_train": _asset_entry(m_weak_train_path, required_for=["stage2_train"], allowed_stages=["stage2_train"], eval_only=False),
        "m_weak_dev": _asset_entry(m_weak_dev_path, required_for=["stage2_dev", "stage2_tuning"], allowed_stages=["stage2_dev"], eval_only=False),
    }
    optional_paths = {
        "m_align_calib": (m_align_calib_path, False),
        "m_final_test": (m_final_test_path, True),
        "hard_b_test": (hard_b_test_path, True),
        "real_domain_split_test": (real_domain_split_test_path, True),
        "real_domain_selective_test": (real_domain_selective_test_path, True),
    }
    for name, (path, eval_only) in optional_paths.items():
        if path is not None:
            assets[name] = _asset_entry(path, required_for=[], allowed_stages=["final_eval"] if eval_only else ["stage2_calibration_optional"], eval_only=eval_only)
    return {"registry_status": "runtime_paths_from_stage2_runner_args", "assets": assets}


def _asset_entry(path: str | Path, *, required_for: list[str], allowed_stages: list[str], eval_only: bool) -> dict[str, Any]:
    return {
        "path": str(path),
        "required_for": list(required_for),
        "allowed_stages": list(allowed_stages),
        "forbidden_stages": ["stage2_train", "calibration", "tuning"] if eval_only else [],
        "eval_only": bool(eval_only),
        "forbidden_for_training": bool(eval_only),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage2_calibration(
        stage2_spec_path=args.stage2_spec,
        strict_replay_manifest=args.strict_replay_manifest,
        hard_b_train_path=args.hard_b_train,
        hard_b_dev_path=args.hard_b_dev,
        m_weak_train_path=args.m_weak_train,
        m_weak_dev_path=args.m_weak_dev,
        m_align_calib_path=args.m_align_calib,
        m_final_test_path=args.m_final_test,
        hard_b_test_path=args.hard_b_test,
        real_domain_split_test_path=args.real_domain_split_test,
        real_domain_selective_test_path=args.real_domain_selective_test,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        train=bool(args.train),
        implementation_check_only=bool(args.implementation_check_only),
        advisor_approved=bool(args.advisor_approved),
        asset_registry_path=args.asset_registry,
    )
    return 0


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if target.suffix.lower() == ".jsonl":
        return read_jsonl(target)
    payload = read_json(target)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and "rows" in payload:
        return [row for row in payload["rows"] if isinstance(row, dict)]
    return []


def _run_guarded_stage2_training_check(spec: dict[str, Any], source_manifests: dict[str, Any], freeze_plan) -> Any:
    batches = []
    for row in _rows_for_training(source_manifests.get("strict_replay")):
        batch = adapt_strict_replay_batch(row)
        _require_valid_train_batch(batch)
        batches.append(batch)
    for row in _rows_for_training(source_manifests.get("hard_b_train")):
        batch = adapt_hard_b_batch(row)
        _require_valid_train_batch(batch)
        batches.append(batch)
    for row in _rows_for_training(source_manifests.get("m_weak_train")):
        batch = adapt_m_weak_batch(row)
        _require_valid_train_batch(batch)
        batches.append(batch)
    if not batches:
        raise ValueError("Stage 2 guarded train requires at least one trainable non-final-test batch.")
    backend = _build_mica_backend(spec)
    backend.apply_freeze_plan(freeze_plan)
    optimizer = torch.optim.Adam(backend.trainable_parameters(), lr=float(spec.get("base_lr", 1e-3)))
    return run_train_epoch(
        backend,
        batches[: int(spec.get("implementation_check_max_batches", 8) or 8)],
        stage="stage2",
        spec=spec,
        optimizer=optimizer,
    )


def _save_stage2_checkpoint(
    *,
    output_root_path: Path,
    spec: dict[str, Any],
    asset_registry: dict[str, Any],
    epoch: Any,
    freeze_plan: Any,
) -> dict[str, Any]:
    checkpoint_path = output_root_path / "checkpoints" / "stage2_epoch_1.ckpt.json"
    payload = build_checkpoint_payload(
        stage="stage2",
        spec_snapshot=spec,
        asset_registry_snapshot=asset_registry,
        seed=int(spec.get("seed", 0) or 0),
        epoch=1,
        metrics={
            "mean_loss": epoch.mean_loss,
            "step_count": epoch.step_count,
            "gradient_step_count": epoch.gradient_step_count,
            "nan_step_count": epoch.nan_step_count,
            "source_kind_counts": epoch.source_kind_counts,
            "diagnostics": epoch.diagnostics,
        },
        trainable_components=list(freeze_plan.trainable_components),
        frozen_components=list(freeze_plan.frozen_components),
        forbidden_assets_not_used=["m_final_test", "hard_b_test", "real_domain_split_test", "real_domain_selective_test"],
        backend_state={
            "backend_type": "MicaModelBackendAdapter",
            "note": "JSON checkpoint stores protocol metadata and metrics; tensor weights require full model checkpoint implementation.",
        },
    )
    save_checkpoint(checkpoint_path, payload)
    loaded = load_checkpoint(checkpoint_path)
    validation = validate_checkpoint_payload(loaded)
    if not validation["valid"]:
        raise ValueError("Invalid Stage 2 checkpoint payload: " + ",".join(validation["errors"]))
    return loaded


def _build_mica_backend(spec: dict[str, Any]) -> MicaModelBackendAdapter:
    model = MicaModel(
        text_vector_dim=TEXT_VECTOR_DIM,
        dense_feature_dim=len(DENSE_FEATURE_NAMES),
        hidden_dim=int(spec.get("hidden_dim", 64) or 64),
        kmax=int(spec.get("kmax", 4) or 4),
        use_null_slot=True,
        use_pairwise_bias=True,
        assignment_temperature=float(spec.get("assignment_temperature", 0.7) or 0.7),
        count_pb_coupling_strength=0.0,
    )
    return MicaModelBackendAdapter(model)


def _rows_for_training(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        rows = []
    elif isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        rows = [row for row in payload["rows"] if isinstance(row, dict)]
    else:
        rows = []
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        copied = dict(row)
        copied.setdefault("sample_id", f"stage2_train_{index}")
        normalized.append(copied)
    return normalized


def _require_valid_train_batch(batch) -> None:
    validation = validate_train_batch(batch)
    diagnostics = list(validation.get("diagnostics", []))
    if not batch.edit_units:
        diagnostics.append("missing_edit_units")
    if diagnostics:
        sample_id = batch.sample_ids[0] if batch.sample_ids else "missing_sample_id"
        raise ValueError(
            f"Stage 2 guarded train requires protocol-valid non-placeholder batch for {sample_id}: "
            + ",".join(sorted(set(diagnostics)))
        )


if __name__ == "__main__":
    raise SystemExit(main())
