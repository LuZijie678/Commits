from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.io_utils import read_json, write_json, write_jsonl
from code.mica.run_manifest import build_run_manifest
from code.mica.runners.stage1_runtime import (
    STAGE1_DEV_ASSET_NAMES,
    STAGE1_TRAIN_ASSET_NAMES,
    build_stage1_checkpoint_artifact_id,
    build_required_asset_status,
    input_asset_hashes,
    load_formal_asset_rows,
    load_stage1_samples_from_rows,
    manifest_row_to_train_batch,
    required_assets_ready,
    resolve_formal_asset_entry,
    sha256_file,
    update_stage1_checkpoint_registry,
)
from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.train.train_stage1_sanity import fit_stage1_model_with_artifacts, load_config
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import (
    build_model_checkpoint_payload,
    instantiate_backend_from_checkpoint,
    load_checkpoint,
    save_checkpoint,
    validate_checkpoint_payload,
)


DEFAULT_BASE_CONFIG = "code/mica/configs/mica_stage1_sanity.yaml"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonical Stage 1 formal training runner.")
    parser.add_argument("--protocol-spec", required=True)
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--base-config", default=DEFAULT_BASE_CONFIG)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--register-checkpoint", action="store_true")
    return parser


def run_stage1_formal_training(
    *,
    protocol_spec_path: str | Path,
    asset_registry_path: str | Path,
    output_root: str | Path,
    base_config_path: str | Path = DEFAULT_BASE_CONFIG,
    overwrite: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    execute: bool = False,
    register_checkpoint: bool = False,
) -> dict[str, Any]:
    mode_count = sum(bool(flag) for flag in (dry_run, validate_only, execute))
    if mode_count != 1:
        raise ValueError("Stage 1 formal training requires exactly one of --dry-run, --validate-only, or --execute.")

    protocol_spec = read_json(protocol_spec_path)
    asset_registry = load_asset_registry(str(asset_registry_path))
    asset_registry_validation = validate_asset_registry(asset_registry)
    base_config = load_config(base_config_path)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage1_formal_training",
        config_paths=[str(protocol_spec_path)],
        asset_registry_path=str(asset_registry_path),
        seed=int(base_config.get("seed", 42) or 42),
        mode="execute" if execute else ("validate_only" if validate_only else "dry_run"),
        advisor_approval=False,
    )

    output_root_path = Path(output_root)
    _ensure_output_root(output_root_path, overwrite=overwrite)
    manifest_json = output_root_path / "stage1_formal_training_manifest.json"
    readiness_json = output_root_path / "stage1_formal_training_readiness.json"
    training_metrics_json = output_root_path / "stage1_formal_training_dev_metrics.json"
    training_log_jsonl = output_root_path / "stage1_formal_training_log.jsonl"
    checkpoint_metadata_json = output_root_path / "stage1_formal_training_checkpoint_metadata.json"
    roundtrip_json = output_root_path / "stage1_formal_training_checkpoint_roundtrip.json"
    checkpoint_path = output_root_path / "stage1_full_model_checkpoint.pt"

    required_assets_status = build_required_asset_status(
        asset_registry_validation,
        (*STAGE1_TRAIN_ASSET_NAMES, *STAGE1_DEV_ASSET_NAMES),
    )
    assets_ready = required_assets_ready(required_assets_status)
    plan_payload = _build_training_plan(protocol_spec=protocol_spec, base_config=base_config)
    readiness_payload = {
        "protocol_spec_path": str(protocol_spec_path),
        "asset_registry_path": str(asset_registry_path),
        "required_assets_status": required_assets_status,
        "assets_ready": assets_ready,
        "register_checkpoint_requested": bool(register_checkpoint),
        "mode": "execute" if execute else ("validate_only" if validate_only else "dry_run"),
        "training_plan": plan_payload,
        "experiment_manifest": experiment_manifest,
    }
    write_json(readiness_json, readiness_payload)

    result_flags: dict[str, Any] = {
        "training_enabled": bool(execute),
        "official_validation_executed": False,
        "stage2_allowed": False,
        "stage3_allowed": False,
        "stage4_allowed": False,
        "checkpoint_registered": False,
        "checkpoint_roundtrip_valid": False,
        "completion_status": "not_executed",
        "full_model_checkpoint_written": False,
    }

    if dry_run or validate_only:
        result = build_run_manifest(
            stage="stage1_formal_training",
            mode="validate_only" if validate_only else "dry_run",
            output_root=str(output_root_path),
            flags={
                **result_flags,
                "metadata": {
                    "required_assets_status": required_assets_status,
                    "assets_ready": assets_ready,
                    "training_plan": plan_payload,
                    "experiment_manifest": experiment_manifest,
                },
            },
            inputs={
                "protocol_spec": protocol_spec_path,
                "asset_registry": asset_registry_path,
                "base_config": base_config_path,
            },
        )
        write_json(manifest_json, result)
        return result

    if not assets_ready:
        missing = ",".join(sorted(name for name, status in required_assets_status.items() if not status.get("formal_ready")))
        raise ValueError(f"Stage 1 formal training requires formal-ready train/dev assets: {missing}")

    train_rows = _load_rows_for_assets(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_names=STAGE1_TRAIN_ASSET_NAMES,
    )
    dev_rows = _load_rows_for_assets(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_names=STAGE1_DEV_ASSET_NAMES,
    )
    train_samples = load_stage1_samples_from_rows(train_rows)
    dev_samples = load_stage1_samples_from_rows(dev_rows)
    training_config = _build_training_config(base_config=base_config, protocol_spec=protocol_spec)
    training_artifacts = fit_stage1_model_with_artifacts(training_config, train_samples)
    model = training_artifacts["model"]
    dev_metrics = evaluate_model(
        model,
        dev_samples,
        batch_size=int(training_config["batch_size"]),
        device=str(training_config["device"]),
    )

    training_log_rows = list(training_artifacts["training_log_rows"])
    write_jsonl(training_log_jsonl, training_log_rows)
    write_json(training_metrics_json, dev_metrics)

    backend = MicaModelBackendAdapter(model)
    manifest_hashes = input_asset_hashes(required_assets_status)
    payload = build_model_checkpoint_payload(
        stage="stage1",
        backend=backend,
        optimizer_state=training_artifacts["optimizer_state"],
        scheduler_state=training_artifacts["scheduler_state"],
        model_config=training_artifacts["model_config"],
        training_state={
            "epochs_completed": int(training_artifacts["epochs_completed"]),
            "global_step": int(training_artifacts["global_step"]),
            "seed": int(training_config["seed"]),
            "batch_size": int(training_config["batch_size"]),
            "train_sample_count": len(train_samples),
            "dev_sample_count": len(dev_samples),
            "scheduler_enabled": bool(training_artifacts["scheduler_enabled"]),
            "protocol_candidate_schedule": protocol_spec.get("candidate_schedule"),
        },
        threshold_version=None,
        data_manifest_hashes=manifest_hashes,
        git_commit=experiment_manifest.get("git_commit"),
        registry_hash=experiment_manifest.get("asset_registry_hash"),
        encoder_config={
            "text_vector_dim": training_artifacts["model_config"]["text_vector_dim"],
            "dense_feature_dim": training_artifacts["model_config"]["dense_feature_dim"],
        },
        relation_config={
            "use_pairwise_bias": training_artifacts["model_config"]["use_pairwise_bias"],
        },
        tokenizer_config={"type": "hashed_text_features"},
        random_seed=int(training_config["seed"]),
        kmax=int(training_config["Kmax"]),
        git_provenance=experiment_manifest.get("git_provenance"),
        environment=experiment_manifest.get("environment"),
    )
    save_checkpoint(checkpoint_path, payload)
    checkpoint_hash = sha256_file(checkpoint_path)
    loaded_checkpoint = load_checkpoint(checkpoint_path)
    checkpoint_validation = validate_checkpoint_payload(loaded_checkpoint, require_full_model_state=True)
    if not checkpoint_validation["valid"]:
        raise ValueError("Saved Stage 1 checkpoint failed validation: " + ",".join(checkpoint_validation["errors"]))

    roundtrip = _checkpoint_roundtrip(backend=backend, checkpoint_payload=loaded_checkpoint, sample_row=dev_rows[0])
    write_json(roundtrip_json, roundtrip)
    if not roundtrip["valid"]:
        raise ValueError("Stage 1 checkpoint round-trip validation failed.")

    checkpoint_artifact_id = build_stage1_checkpoint_artifact_id(
        git_commit=experiment_manifest.get("git_commit"),
        config_hash=str(experiment_manifest.get("config_hash") or ""),
        train_manifest_hashes=manifest_hashes,
        seed=int(training_config["seed"]),
    )
    checkpoint_metadata = {
        "schema_version": payload.get("schema_version"),
        "checkpoint_kind": payload.get("checkpoint_kind"),
        "artifact_id": checkpoint_artifact_id,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_hash": checkpoint_hash,
        "model_config": payload.get("model_config"),
        "training_state": payload.get("training_state"),
        "data_manifest_hashes": payload.get("data_manifest_hashes"),
        "registry_hash": payload.get("registry_hash"),
        "git_commit": payload.get("git_commit"),
        "git_provenance": payload.get("git_provenance"),
        "environment": payload.get("environment"),
        "model_config_hash": payload.get("model_config_hash"),
    }
    write_json(checkpoint_metadata_json, checkpoint_metadata)

    if register_checkpoint:
        update_stage1_checkpoint_registry(
            registry_path=asset_registry_path,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            checkpoint_artifact_id=checkpoint_artifact_id,
            training_manifest_hashes=manifest_hashes,
            git_commit=experiment_manifest.get("git_commit"),
            git_provenance=experiment_manifest.get("git_provenance"),
            model_config_hash=payload.get("model_config_hash"),
            environment=experiment_manifest.get("environment"),
            created_by="run_stage1_formal_training",
        )

    result = build_run_manifest(
        stage="stage1_formal_training",
        mode="execute",
        output_root=str(output_root_path),
        flags={
            **result_flags,
            "training_enabled": True,
            "checkpoint_registered": bool(register_checkpoint),
            "checkpoint_roundtrip_valid": bool(roundtrip["valid"]),
            "completion_status": "completed",
            "full_model_checkpoint_written": True,
            "metadata": {
                "required_assets_status": required_assets_status,
                "training_plan": plan_payload,
                "experiment_manifest": experiment_manifest,
                "train_sample_count": len(train_samples),
                "dev_sample_count": len(dev_samples),
                "checkpoint_path": str(checkpoint_path),
                "checkpoint_hash": checkpoint_hash,
                "checkpoint_artifact_id": checkpoint_artifact_id,
                "checkpoint_metadata_path": str(checkpoint_metadata_json),
                "roundtrip_path": str(roundtrip_json),
                "dev_metrics_path": str(training_metrics_json),
                "training_log_path": str(training_log_jsonl),
            },
        },
        inputs={
            "protocol_spec": protocol_spec_path,
            "asset_registry": asset_registry_path,
            "base_config": base_config_path,
        },
    )
    write_json(manifest_json, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_formal_training(
        protocol_spec_path=args.protocol_spec,
        asset_registry_path=args.asset_registry,
        output_root=args.output_root,
        base_config_path=args.base_config,
        overwrite=bool(args.overwrite),
        dry_run=bool(args.dry_run),
        validate_only=bool(args.validate_only),
        execute=bool(args.execute),
        register_checkpoint=bool(args.register_checkpoint),
    )
    return 0


def _build_training_plan(*, protocol_spec: dict[str, Any], base_config: dict[str, Any]) -> dict[str, Any]:
    schedule = dict(protocol_spec.get("schedule", {}))
    return {
        "candidate_schedule": protocol_spec.get("candidate_schedule"),
        "epochs": int(schedule.get("epochs", base_config.get("epochs", 3))),
        "lambda_align": float(schedule.get("lambda_align", base_config.get("lambda_align", 1.0))),
        "lambda_count": float(schedule.get("lambda_count", base_config.get("lambda_count", 0.5))),
        "lambda_exist": float(schedule.get("lambda_exist", base_config.get("lambda_exist", 0.5))),
        "kmax": int(base_config.get("Kmax", 4)),
        "null_slot_enabled": bool(protocol_spec.get("null_slot", {}).get("enabled", False)),
        "use_pairwise_bias": bool(protocol_spec.get("evidence_graph", {}).get("use_attention_bias", True)),
    }


def _build_training_config(*, base_config: dict[str, Any], protocol_spec: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base_config)
    schedule = dict(protocol_spec.get("schedule", {}))
    assignment_schedule = dict(protocol_spec.get("assignment_schedule", {}))
    dual_cardinality = dict(protocol_spec.get("dual_cardinality", {}))
    merged.update(
        {
            "epochs": int(schedule.get("epochs", merged.get("epochs", 3))),
            "lambda_align": float(schedule.get("lambda_align", merged.get("lambda_align", 1.0))),
            "lambda_count": float(schedule.get("lambda_count", merged.get("lambda_count", 0.5))),
            "lambda_exist": float(schedule.get("lambda_exist", merged.get("lambda_exist", 0.5))),
            "assignment_tau_start": float(assignment_schedule.get("tau_start", merged.get("assignment_tau_start", 1.5))),
            "assignment_tau_end": float(assignment_schedule.get("tau_end", merged.get("assignment_tau_end", 0.7))),
            "alpha_pb": float(dual_cardinality.get("alpha_pb", merged.get("alpha_pb", 0.5))),
            "use_null_slot": bool(protocol_spec.get("null_slot", {}).get("enabled", False)),
            "use_pairwise_bias": bool(protocol_spec.get("evidence_graph", {}).get("use_attention_bias", True)),
        }
    )
    merged["sanity_only"] = False
    return merged


def _load_rows_for_assets(
    *,
    asset_registry: dict[str, Any],
    asset_registry_validation: dict[str, Any],
    asset_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset_name in asset_names:
        resolved = resolve_formal_asset_entry(
            asset_registry=asset_registry,
            asset_registry_validation=asset_registry_validation,
            asset_name=asset_name,
            require_formal_ready=True,
        )
        rows.extend(load_formal_asset_rows(resolved["path"]))
    return rows


def _checkpoint_roundtrip(
    *,
    backend: MicaModelBackendAdapter,
    checkpoint_payload: dict[str, Any],
    sample_row: dict[str, Any],
) -> dict[str, Any]:
    batch = manifest_row_to_train_batch(sample_row)
    before = backend.forward(batch)
    restored_backend = instantiate_backend_from_checkpoint(checkpoint_payload)
    after = restored_backend.forward(batch)
    count_probs_max_abs_diff = float(torch.max(torch.abs(before.count_probs - after.count_probs)).item())
    slot_exist_max_abs_diff = float(torch.max(torch.abs(before.slot_exist_probs - after.slot_exist_probs)).item())
    valid = before.assignments == after.assignments and before.predicted_count == after.predicted_count and count_probs_max_abs_diff <= 1e-6
    return {
        "valid": valid,
        "sample_id": sample_row.get("sample_id"),
        "predicted_count_before": before.predicted_count,
        "predicted_count_after": after.predicted_count,
        "assignments_match": before.assignments == after.assignments,
        "count_probs_max_abs_diff": count_probs_max_abs_diff,
        "slot_exist_max_abs_diff": slot_exist_max_abs_diff,
    }


def _ensure_output_root(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if any(path.iterdir()) and not overwrite:
            raise FileExistsError(f"Output directory is not empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
