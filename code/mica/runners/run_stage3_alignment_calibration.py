from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

from code.mica.config_validation import validate_stage3_spec
from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.data.real_alignment import check_double_annotation_coverage, summarize_real_alignment, validate_real_alignment_rows
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.models.mica_model import MicaModel
from code.mica.reporting import build_stage3_alignment_calibration_report
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest
from code.mica.stages.stage3_real_alignment_calibration import (
    build_stage3_calibration_plan,
    build_stage3_freeze_plan,
    prepare_stage3_real_alignment_calibration,
)
from code.mica.training.batch_adapters import adapt_real_alignment_batch, adapt_strict_replay_batch, validate_train_batch
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import (
    build_checkpoint_payload,
    build_checkpoint_plan,
    load_checkpoint,
    save_checkpoint,
    validate_checkpoint_payload,
)
from code.mica.training.loop_engine import run_train_epoch
from code.mica.training.train_loop import summarize_train_loop_capabilities


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 3 real alignment calibration runner.")
    parser.add_argument("--stage3-spec", required=True)
    parser.add_argument("--alignment-jsonl", required=True)
    parser.add_argument("--strict-replay-manifest", required=True)
    parser.add_argument("--m-final-test")
    parser.add_argument("--asset-registry")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--implementation-check-only", action="store_true")
    parser.add_argument("--advisor-approved", action="store_true")
    return parser


def run_stage3_alignment_calibration(
    *,
    stage3_spec_path: str | Path,
    alignment_jsonl: str | Path,
    strict_replay_manifest: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    train: bool = False,
    implementation_check_only: bool = False,
    advisor_approved: bool = False,
    m_final_test_path: str | Path | None = None,
    asset_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    if not dry_run and not train:
        raise ValueError("Stage 3 calibration runner requires explicit --dry-run or guarded --train.")

    spec = read_json(stage3_spec_path)
    spec_validation = validate_stage3_spec(spec)
    if spec_validation["errors"]:
        raise ValueError("; ".join(spec_validation["errors"]))
    if advisor_approved:
        spec = {**spec, "advisor_stage3_approved": True}
    if train and not bool(spec.get("advisor_stage3_approved", False)):
        raise ValueError("Stage 3 training requires advisor_stage3_approved=true in the stage3 spec.")
    if m_final_test_path is not None:
        raise ValueError("M-final-test is forbidden for Stage 3 calibration.")
    asset_registry = _build_stage3_runtime_asset_registry(
        explicit_registry_path=asset_registry_path,
        alignment_jsonl=alignment_jsonl,
        strict_replay_manifest=strict_replay_manifest,
        m_final_test_path=m_final_test_path,
    )
    asset_registry_validation = validate_asset_registry(asset_registry)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage3_alignment_calibration",
        config_paths=[str(stage3_spec_path)],
        asset_registry_path=str(asset_registry_path) if asset_registry_path is not None else None,
        seed=int(spec.get("seed", 0) or 0),
        mode="train" if train else "dry_run",
        advisor_approval=bool(spec.get("advisor_stage3_approved", False)),
    )

    strict_replay_rows = _load_rows(strict_replay_manifest)
    rows = read_jsonl(alignment_jsonl)
    stage_summary = prepare_stage3_real_alignment_calibration(spec, rows)
    training_plan = build_stage3_calibration_plan(spec, stage_summary["summary"])
    freeze_plan = build_stage3_freeze_plan(spec)
    output_root_path = Path(output_root)
    checkpoint_plan = build_checkpoint_plan(str(output_root_path / "checkpoints"), save_every_n_steps=None, keep_last_k=1)
    metric_artifact = _build_stage3_metric_artifact(stage_summary)
    adapter_availability = {
        "strict_replay": callable(adapt_strict_replay_batch),
        "real_alignment": callable(adapt_real_alignment_batch),
    }
    implementation_capabilities = summarize_train_loop_capabilities(implementation_only=bool(implementation_check_only or train))
    if train:
        epoch = _run_guarded_stage3_training_check(spec, rows, strict_replay_rows, freeze_plan)
        checkpoint_payload = _save_stage3_checkpoint(
            output_root_path=output_root_path,
            spec=spec,
            asset_registry=asset_registry,
            epoch=epoch,
            freeze_plan=freeze_plan,
        )
        implementation_capabilities = {
            **implementation_capabilities,
            "trainer_backend_executed": True,
            "trainer_backend_type": "MicaModelBackendAdapter",
            "toy_backend_used": False,
        }
        return build_run_manifest(
            stage="stage3_real_alignment_calibration",
            mode="implementation_check_only" if implementation_check_only else "train",
            output_root=None,
            flags={
                "training_enabled": True,
                "training_executed": True,
                "stage3_training_executed": True,
                "implementation_check_only": bool(implementation_check_only),
                "advisor_approved": bool(spec.get("advisor_stage3_approved", False)),
                "trainer_backend_executed": True,
                "trainer_backend_type": "MicaModelBackendAdapter",
                "toy_backend_used": False,
                "stage2_allowed": False,
                "m_final_test_used_for_calibration": False,
                "checkpoint_written": True,
                "checkpoint_path": str(output_root_path / "checkpoints" / "stage3_epoch_1.ckpt.json"),
                "checkpoint_valid": validate_checkpoint_payload(checkpoint_payload)["valid"],
                "asset_registry_validation": asset_registry_validation,
                "asset_registry_snapshot": asset_registry,
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
                    "training_plan": asdict(training_plan),
                    "freeze_plan": asdict(freeze_plan),
                    "checkpoint_plan": asdict(checkpoint_plan),
                    "real_alignment_metric_artifact": metric_artifact,
                    "adapter_availability": adapter_availability,
                    "implementation_capabilities": implementation_capabilities,
                    "experiment_manifest": experiment_manifest,
                },
            },
            inputs={
                "stage3_spec": stage3_spec_path,
                "alignment_jsonl": alignment_jsonl,
                "strict_replay_manifest": strict_replay_manifest,
            },
        )

    manifest = build_run_manifest(
        stage="stage3_real_alignment_calibration",
        mode="dry_run" if dry_run else "train",
        output_root=str(output_root),
        flags={
            "dry_run": True,
            "stage3_training_executed": False,
            "advisor_approval_required": True,
            "m_final_test_used_for_calibration": False,
            "freeze_base_encoder": bool(spec.get("freeze_base_encoder", True)),
            "trainable_components": list(spec.get("trainable_components", [])),
            "asset_registry_validation": asset_registry_validation,
            "asset_registry_snapshot": asset_registry,
            "real_alignment_metrics_status": metric_artifact["status"],
            "real_alignment_metrics_values_status": metric_artifact["values_status"],
            "metadata": {
                "spec_validation": spec_validation,
                "training_plan": asdict(training_plan),
                "freeze_plan": asdict(freeze_plan),
                "checkpoint_plan": asdict(checkpoint_plan),
                "real_alignment_metric_artifact": metric_artifact,
                "adapter_availability": adapter_availability,
                "implementation_capabilities": implementation_capabilities,
                "experiment_manifest": experiment_manifest,
            },
        },
        inputs={
            "stage3_spec": stage3_spec_path,
            "alignment_jsonl": alignment_jsonl,
            "strict_replay_manifest": strict_replay_manifest,
        },
    )
    assert_no_forbidden_training_flags(manifest)
    alignment_report = build_stage3_alignment_calibration_report([_build_stage3_alignment_report_row(stage_summary)])
    write_json(output_root_path / "stage3_alignment_calibration_manifest.json", manifest)
    write_json(output_root_path / "stage3_runtime_asset_registry.json", asset_registry)
    write_json(output_root_path / "stage3_asset_registry_validation.json", asset_registry_validation)
    write_json(output_root_path / "stage3_real_alignment_validation.json", validate_real_alignment_rows(rows))
    write_json(output_root_path / "stage3_real_alignment_summary.json", summarize_real_alignment(rows))
    write_json(output_root_path / "stage3_real_alignment_double_annotation.json", check_double_annotation_coverage(rows))
    write_json(output_root_path / "stage3_alignment_stage_summary.json", stage_summary)
    write_json(output_root_path / "stage3_alignment_calibration_report.json", alignment_report)
    write_json(output_root_path / "stage3_real_alignment_metrics_artifact.json", metric_artifact)
    return manifest


def _build_stage3_alignment_report_row(stage_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(stage_summary.get("summary", {}))
    validation = dict(stage_summary.get("validation", {}))
    return {
        "status": "values_to_be_populated_by_real_alignment_eval",
        "paper_readiness": "not_final_paper_ready_until_populated",
        "pairwise_f1": None,
        "ari": None,
        "nmi": None,
        "bcubed_f1": None,
        "hunk_micro_f1": None,
        "hard_b_fpr_rebound": None,
        "m_recall_drop": None,
        "real_alignment_sample_count": summary.get("row_count", validation.get("row_count", 0)),
        "final_test_tuning": "forbidden",
        "note": "Dry-run validates real-alignment assets and report schema; metric values require the alignment eval runner.",
    }


def _build_stage3_metric_artifact(stage_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(stage_summary.get("summary", {}))
    validation = dict(stage_summary.get("validation", {}))
    double_annotation = dict(stage_summary.get("double_annotation", {}))
    values_ready = False
    return {
        "artifact_type": "stage3_real_alignment_metrics",
        "status": "protocol_defined",
        "values_status": "values_to_be_populated_by_real_alignment_eval",
        "paper_readiness": "not_final_paper_ready_until_populated",
        "selection_split": "real_alignment_calibration_only",
        "final_test_tuning": "forbidden",
        "real_alignment_row_count": summary.get("row_count", validation.get("row_count", 0)),
        "validation": validation,
        "double_annotation": double_annotation,
        "metrics": {
            "pairwise_f1": None,
            "ari": None,
            "nmi": None,
            "bcubed_f1": None,
            "hunk_micro_f1": None,
            "hard_b_fpr_rebound": None,
            "m_recall_drop": None,
        },
        "metric_values_populated": values_ready,
        "note": "Runner materializes the metric artifact contract; values require predicted alignment outputs from the alignment eval runner.",
    }


def _build_stage3_runtime_asset_registry(
    *,
    explicit_registry_path: str | Path | None,
    alignment_jsonl: str | Path,
    strict_replay_manifest: str | Path,
    m_final_test_path: str | Path | None,
) -> dict[str, Any]:
    if explicit_registry_path is not None:
        return load_asset_registry(str(explicit_registry_path))
    assets = {
        "m_align_calib": _asset_entry(
            alignment_jsonl,
            required_for=["stage3_calibration"],
            allowed_stages=["stage3_calibration"],
            eval_only=False,
        ),
        "strict_replay": _asset_entry(
            strict_replay_manifest,
            required_for=["stage3_replay"],
            allowed_stages=["stage3_replay"],
            eval_only=False,
        ),
    }
    if m_final_test_path is not None:
        assets["m_final_test"] = _asset_entry(
            m_final_test_path,
            required_for=[],
            allowed_stages=["final_eval"],
            eval_only=True,
        )
    return {"registry_status": "runtime_paths_from_stage3_runner_args", "assets": assets}


def _asset_entry(path: str | Path, *, required_for: list[str], allowed_stages: list[str], eval_only: bool) -> dict[str, Any]:
    return {
        "path": str(path),
        "required_for": list(required_for),
        "allowed_stages": list(allowed_stages),
        "forbidden_stages": ["stage3_calibration", "training", "tuning"] if eval_only else [],
        "eval_only": bool(eval_only),
        "forbidden_for_training": bool(eval_only),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage3_alignment_calibration(
        stage3_spec_path=args.stage3_spec,
        alignment_jsonl=args.alignment_jsonl,
        strict_replay_manifest=args.strict_replay_manifest,
        m_final_test_path=args.m_final_test,
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


def _run_guarded_stage3_training_check(spec: dict[str, Any], alignment_rows: list[dict[str, Any]], strict_replay_rows: list[dict[str, Any]], freeze_plan) -> Any:
    batches = []
    for row in _normalized_stage3_rows(alignment_rows, prefix="real_alignment"):
        batch = adapt_real_alignment_batch(row)
        _require_valid_stage3_batch(batch)
        batches.append(batch)
    for row in _normalized_stage3_rows(strict_replay_rows, prefix="strict_replay"):
        batch = adapt_strict_replay_batch(row)
        _require_valid_stage3_batch(batch)
        batches.append(batch)
    if not batches:
        raise ValueError("Stage 3 guarded train requires real alignment or strict replay batches.")
    backend = _build_mica_backend(spec)
    backend.apply_freeze_plan(freeze_plan)
    optimizer = torch.optim.Adam(backend.trainable_parameters(), lr=float(spec.get("base_lr", 1e-3)))
    return run_train_epoch(
        backend,
        batches[: int(spec.get("implementation_check_max_batches", 8) or 8)],
        stage="stage3",
        spec=spec,
        optimizer=optimizer,
    )


def _save_stage3_checkpoint(
    *,
    output_root_path: Path,
    spec: dict[str, Any],
    asset_registry: dict[str, Any],
    epoch: Any,
    freeze_plan: Any,
) -> dict[str, Any]:
    checkpoint_path = output_root_path / "checkpoints" / "stage3_epoch_1.ckpt.json"
    payload = build_checkpoint_payload(
        stage="stage3",
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
        forbidden_assets_not_used=["m_final_test"],
        backend_state={
            "backend_type": "MicaModelBackendAdapter",
            "note": "JSON checkpoint stores protocol metadata and metrics; tensor weights require full model checkpoint implementation.",
        },
    )
    save_checkpoint(checkpoint_path, payload)
    loaded = load_checkpoint(checkpoint_path)
    validation = validate_checkpoint_payload(loaded)
    if not validation["valid"]:
        raise ValueError("Invalid Stage 3 checkpoint payload: " + ",".join(validation["errors"]))
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


def _normalized_stage3_rows(rows: list[dict[str, Any]], *, prefix: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        copied = dict(row)
        copied.setdefault("sample_id", f"{prefix}_{index}")
        normalized.append(copied)
    return normalized


def _require_valid_stage3_batch(batch) -> None:
    validation = validate_train_batch(batch)
    diagnostics = list(validation.get("diagnostics", []))
    if not batch.edit_units:
        diagnostics.append("missing_edit_units")
    if diagnostics:
        sample_id = batch.sample_ids[0] if batch.sample_ids else "missing_sample_id"
        raise ValueError(
            f"Stage 3 guarded train requires protocol-valid real edit-unit alignment for {sample_id}: "
            + ",".join(sorted(set(diagnostics)))
        )


if __name__ == "__main__":
    raise SystemExit(main())
