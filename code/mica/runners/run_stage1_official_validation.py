from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.experiment.report_schema import build_experiment_report_schema
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl
from code.mica.runners.export_consumer_plans import export_consumer_plans
from code.mica.runners.stage1_runtime import (
    STAGE1_CHECKPOINT_ASSET_NAME,
    STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME,
    build_threshold_metric_snapshot,
    build_required_asset_status,
    derive_official_blockers,
    evaluate_metric_thresholds,
    generate_stage1_prediction_rows,
    input_asset_hashes as build_input_asset_hashes,
    load_stage1_samples_from_rows,
    required_assets_ready,
    sha256_file,
    validate_clean_checkpoint_provenance,
    validate_registry_bound_checkpoint,
    validate_registry_bound_manifest,
)
from code.mica.schema_validation import validate_attribution_prediction_contract
from code.mica.stage0.leakage_report import build_global_leakage_report
from code.mica.training.checkpointing import instantiate_backend_from_checkpoint, load_checkpoint, validate_checkpoint_payload
from code.mica.reporting import write_markdown_report
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest
from code.mica.stages.stage1_official_validation import (
    build_stage1_official_summary,
    build_stage1_official_validation_plan,
    build_stage1_validation_dataset,
    evaluate_stage1_predictions,
    evaluate_stage1_with_baselines,
    load_stage1_manifest_rows,
)
from code.mica.train.eval_stage1_sanity import evaluate_model


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 official validation entrypoint.")
    parser.add_argument("--protocol-spec", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--asset-registry")
    parser.add_argument("--checkpoint")
    parser.add_argument("--prediction-jsonl")
    parser.add_argument("--edit-units-jsonl")
    parser.add_argument("--baseline-spec")
    parser.add_argument("--stage0-readiness")
    parser.add_argument("--official-preflight")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--advisor-approved", action="store_true")
    parser.add_argument("--export-consumer-plans", action="store_true")
    parser.add_argument("--consumer-plan-review-ready", action="store_true")
    return parser


def run_stage1_official_validation(
    *,
    protocol_spec_path: str | Path,
    metric_thresholds_path: str | Path,
    manifest_path: str | Path,
    asset_registry_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    prediction_jsonl: str | Path | None = None,
    edit_units_jsonl: str | Path | None = None,
    baseline_spec_path: str | Path | None = None,
    stage0_readiness_path: str | Path | None = None,
    official_preflight_path: str | Path | None = None,
    output_root: str | Path,
    dry_run: bool = False,
    execute: bool = False,
    advisor_approved: bool = False,
    export_consumer_plans_artifact: bool = False,
    consumer_plan_review_ready: bool = False,
) -> dict:
    if not dry_run and not execute:
        raise ValueError("Stage 1 official validation requires explicit --dry-run or --execute.")
    if consumer_plan_review_ready:
        export_consumer_plans_artifact = True
    if export_consumer_plans_artifact and prediction_jsonl is None:
        if not execute or checkpoint_path is None:
            raise ValueError("Stage 1 consumer plan export requires prediction_jsonl.")

    protocol_spec = read_json(protocol_spec_path)
    metric_thresholds = read_json(metric_thresholds_path)
    manifest_rows = load_stage1_manifest_rows(manifest_path)
    manifest_payload = read_json(manifest_path) if Path(manifest_path).suffix.lower() != ".jsonl" else {"rows": manifest_rows}
    asset_registry = load_asset_registry(str(asset_registry_path)) if asset_registry_path is not None else None
    asset_registry_validation = validate_asset_registry(asset_registry) if asset_registry is not None else None
    stage0_readiness = read_json(stage0_readiness_path) if stage0_readiness_path is not None else None
    official_preflight = read_json(official_preflight_path) if official_preflight_path is not None else None

    approved = bool(advisor_approved or protocol_spec.get("advisor_stage1_validation_approved", False))
    if execute and not approved:
        raise ValueError("Stage 1 official validation execute path requires advisor approval.")
    if execute and checkpoint_path is None:
        raise ValueError("Stage 1 official validation execute path requires checkpoint_path.")
    if execute and asset_registry is None:
        raise ValueError("Stage 1 official validation execute path requires asset_registry_path.")
    if execute and stage0_readiness is None:
        raise ValueError("Stage 1 official validation execute path requires stage0_readiness_path.")

    execution_plan = build_stage1_official_validation_plan(protocol_spec, metric_thresholds, manifest_rows)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage1_official_validation",
        config_paths=[str(protocol_spec_path), str(metric_thresholds_path)],
        asset_registry_path=str(asset_registry_path) if asset_registry_path is not None else None,
        seed=0,
        mode="execute" if execute else "dry_run",
        advisor_approval=approved,
    )
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    generated_prediction_jsonl = output_root_path / "stage1_official_validation_predictions.jsonl"
    prediction_error_jsonl = output_root_path / "stage1_official_validation_prediction_export_errors.jsonl"
    metrics_json = output_root_path / "stage1_official_validation_metrics.json"
    aggregate_metrics_json = output_root_path / "stage1_official_validation_aggregate_metrics.json"
    readiness_json = output_root_path / "stage1_official_validation_readiness.json"
    leakage_json = output_root_path / "stage1_official_validation_leakage_report.json"
    checkpoint_metadata_json = output_root_path / "stage1_official_validation_checkpoint_metadata.json"
    stage0_snapshot_json = output_root_path / "stage1_official_validation_stage0_readiness_snapshot.json"
    preflight_snapshot_json = output_root_path / "stage1_official_validation_preflight_snapshot.json"
    completion_json = output_root_path / "stage1_official_validation_completion.json"
    consumer_plan_output_jsonl = output_root_path / "stage1_official_validation_consumer_plans.jsonl"
    consumer_plan_error_jsonl = output_root_path / "stage1_official_validation_consumer_plan_export_errors.jsonl"
    consumer_plan_summary_json = output_root_path / "stage1_official_validation_consumer_plan_export_summary.json"
    consumer_plan_export_summary: dict[str, Any] | None = None
    summary_payload: dict[str, Any] | None = None
    runtime_prediction_jsonl = prediction_jsonl
    prediction_contracts: list[dict[str, Any]] = []
    checkpoint_validation: dict[str, Any] | None = None
    checkpoint_hash: str | None = None
    checkpoint_metadata: dict[str, Any] | None = None
    execution_failure_reason: str | None = None
    required_assets_status: dict[str, Any] = {}
    completion_status = "not_executed"
    final_paper_ready = False
    official_validation_executed = False
    thresholds_applied_to_pass_fail = False
    input_asset_hashes: dict[str, str | None] = {}
    official_blockers: list[str] = []
    output_paths = {
        "predictions": generated_prediction_jsonl.name,
        "prediction_export_errors": prediction_error_jsonl.name,
        "metrics": metrics_json.name,
        "aggregate_metrics": aggregate_metrics_json.name,
        "readiness": readiness_json.name,
        "leakage_report": leakage_json.name,
        "checkpoint_metadata": checkpoint_metadata_json.name,
        "stage0_readiness_snapshot": stage0_snapshot_json.name if stage0_readiness is not None else None,
        "preflight_snapshot": preflight_snapshot_json.name if official_preflight is not None else None,
        "completion_report": completion_json.name,
        "consumer_plan_output": consumer_plan_output_jsonl.name if export_consumer_plans_artifact else None,
        "consumer_plan_errors": consumer_plan_error_jsonl.name if export_consumer_plans_artifact else None,
        "consumer_plan_summary": consumer_plan_summary_json.name if export_consumer_plans_artifact else None,
    }

    if execute:
        validate_registry_bound_manifest(
            manifest_path=manifest_path,
            asset_registry=asset_registry,
            asset_registry_validation=asset_registry_validation,
            asset_name=STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME,
        )
        validate_registry_bound_checkpoint(
            checkpoint_path=checkpoint_path,
            asset_registry=asset_registry,
            asset_registry_validation=asset_registry_validation,
            asset_name=STAGE1_CHECKPOINT_ASSET_NAME,
        )
        official_blockers = derive_official_blockers(
            stage0_readiness=stage0_readiness,
            threshold_spec=metric_thresholds,
        )
        if official_preflight is not None and str(official_preflight.get("status") or "") != "ready":
            official_blockers.append("official_preflight_not_ready")
        if official_blockers:
            raise ValueError("Stage 1 official validation remains blocked: " + ",".join(official_blockers))
        loaded_checkpoint = load_checkpoint(str(checkpoint_path))
        checkpoint_validation = validate_checkpoint_payload(loaded_checkpoint, require_full_model_state=True)
        if not checkpoint_validation["valid"]:
            raise ValueError("Stage 1 execute requires full model checkpoint: " + ",".join(checkpoint_validation["errors"]))
        checkpoint_entry_metadata = dict(asset_registry.get("assets", {}).get(STAGE1_CHECKPOINT_ASSET_NAME, {}).get("metadata", {}))
        checkpoint_provenance_validation = validate_clean_checkpoint_provenance(
            loaded_checkpoint,
            fallback_metadata=checkpoint_entry_metadata,
        )
        if not checkpoint_provenance_validation["valid"]:
            raise ValueError(
                "Stage 1 execute requires clean checkpoint provenance: "
                + ",".join(checkpoint_provenance_validation["errors"])
            )
        backend = instantiate_backend_from_checkpoint(loaded_checkpoint)
        checkpoint_hash = sha256_file(Path(checkpoint_path))
        checkpoint_metadata = _checkpoint_metadata(loaded_checkpoint, checkpoint_hash=checkpoint_hash, checkpoint_path=checkpoint_path)
        write_json(checkpoint_metadata_json, checkpoint_metadata)
        write_json(stage0_snapshot_json, stage0_readiness)
        if official_preflight is not None:
            write_json(preflight_snapshot_json, official_preflight)
        required_assets_status = build_required_asset_status(
            asset_registry_validation,
            (STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, STAGE1_CHECKPOINT_ASSET_NAME),
        )
        if not required_assets_ready(required_assets_status):
            missing = ",".join(sorted(name for name, item in required_assets_status.items() if not item.get("formal_ready")))
            raise ValueError(f"Stage 1 execute requires formal-ready registry assets: {missing}")
        input_asset_hashes = build_input_asset_hashes(required_assets_status)
        prediction_rows = generate_stage1_prediction_rows(
            backend=backend,
            manifest_rows=manifest_rows,
            source="stage1_official_validation_execute",
        )
        prediction_contracts = [validate_attribution_prediction_contract(row, mode="review_ready") for row in prediction_rows]
        if not all(item["valid"] for item in prediction_contracts):
            raise ValueError("Stage 1 execute generated invalid prediction rows.")
        write_jsonl(generated_prediction_jsonl, prediction_rows)
        write_jsonl(prediction_error_jsonl, [])
        runtime_prediction_jsonl = generated_prediction_jsonl
        thresholds_applied_to_pass_fail = True
        official_validation_executed = True
        completion_status = "executed_official"

    if runtime_prediction_jsonl is not None:
        prediction_rows = read_jsonl(runtime_prediction_jsonl)
        if not prediction_contracts:
            prediction_contracts = [validate_attribution_prediction_contract(row) for row in prediction_rows]
        dataset = build_stage1_validation_dataset(manifest_rows, prediction_rows)
        prediction_metrics = evaluate_stage1_predictions(dataset["gold_rows"], dataset["prediction_rows"], {"report_oracle_k": True})
        baseline_metrics = evaluate_stage1_with_baselines(
            dataset["gold_rows"],
            dataset["prediction_rows"],
            read_json(baseline_spec_path) if baseline_spec_path is not None else {"baselines": []},
        )
        official_gate_metrics: dict[str, Any] = {}
        official_gate_results: dict[str, Any] = {}
        if execute and checkpoint_metadata is not None:
            final_samples = load_stage1_samples_from_rows(manifest_rows)
            batch_size = int(checkpoint_metadata.get("training_state", {}).get("batch_size", 8) or 8)
            loaded_checkpoint = load_checkpoint(str(checkpoint_path))
            backend = instantiate_backend_from_checkpoint(loaded_checkpoint)
            evaluated_metrics = evaluate_model(backend.model, final_samples, batch_size=batch_size, device="cpu")
            official_gate_metrics = build_threshold_metric_snapshot(evaluated_metrics, metric_thresholds)
            official_gate_results = evaluate_metric_thresholds(evaluated_metrics, metric_thresholds)
            final_paper_ready = bool(official_gate_results) and all(
                bool(item.get("passed")) for item in official_gate_results.values()
            )
        summary_payload = build_stage1_official_summary(
            dataset=dataset,
            prediction_metrics=prediction_metrics,
            baseline_metrics=baseline_metrics,
            official_validation_executed=official_validation_executed,
            thresholds_applied_to_pass_fail=thresholds_applied_to_pass_fail,
            completion_status=completion_status,
            final_paper_ready=final_paper_ready,
        )
        summary_payload["prediction_contracts"] = prediction_contracts
        summary_payload["experiment_manifest"] = experiment_manifest
        summary_payload["checkpoint_metadata"] = checkpoint_metadata
        summary_payload["official_gate_metrics"] = official_gate_metrics
        summary_payload["official_gate_results"] = official_gate_results
        summary_payload["paper_ready"] = bool(final_paper_ready)
        write_json(metrics_json, summary_payload)
        write_json(
            aggregate_metrics_json,
            {
                "schema_version": "mica-stage1-official-aggregate-metrics-v1",
                "official_validation_executed": official_validation_executed,
                "paper_ready": bool(final_paper_ready),
                "dataset_row_count": summary_payload["dataset_row_count"],
                "prediction_row_count": summary_payload["prediction_row_count"],
                "prediction_metrics": prediction_metrics,
                "official_gate_metrics": official_gate_metrics,
                "official_gate_results": official_gate_results,
            },
        )
        if export_consumer_plans_artifact:
            consumer_plan_export_summary = export_consumer_plans(
                prediction_jsonl=runtime_prediction_jsonl,
                output_jsonl=consumer_plan_output_jsonl,
                error_jsonl=consumer_plan_error_jsonl,
                edit_units_jsonl_or_manifest=edit_units_jsonl or manifest_path,
                overwrite=True,
                strict=False,
                review_ready=consumer_plan_review_ready,
            )
            write_json(consumer_plan_summary_json, consumer_plan_export_summary)
            summary_payload["consumer_plan_export"] = consumer_plan_export_summary
        summary_payload["report_schema"] = build_experiment_report_schema(
            stage="stage1",
            metrics={
                "dataset_row_count": summary_payload["dataset_row_count"],
                "prediction_row_count": summary_payload["prediction_row_count"],
                "predicted_k_pairwise_f1": summary_payload["prediction_metrics"].get("predicted_k", {}).get("mean_pairwise_f1", 0.0),
            },
            provenance={
                "git": {
                    "dirty": bool(experiment_manifest.get("dirty")),
                    "git_commit": experiment_manifest.get("git_commit"),
                },
                "runner_manifest": experiment_manifest,
            },
        )
        leakage_payload = build_global_leakage_report(
            asset_registry or {"assets": {}},
            _load_stage1_registry_rows(required_assets_status),
        )
        write_json(leakage_json, leakage_payload)
        write_json(
            readiness_json,
            {
                "asset_registry_validation": asset_registry_validation,
                "required_assets_status": required_assets_status,
                "checkpoint_validation": checkpoint_validation,
                "threshold_status": metric_thresholds.get("threshold_status"),
                "official_blockers": official_blockers,
                "official_validation_executed": official_validation_executed,
                "completion_status": completion_status,
                "stage0_formal_ready": bool(stage0_readiness.get("formal_ready")) if stage0_readiness else False,
                "preflight_status": official_preflight.get("status") if official_preflight else None,
            },
        )
    result = build_run_manifest(
        stage="stage1_official_validation",
        mode="dry_run" if dry_run else "execute",
        output_root=str(output_root),
        flags={
            "official_validation_executed": official_validation_executed,
            "validation_run_executed": official_validation_executed,
            "execute_requested": bool(execute),
            "advisor_approved": approved,
            "thresholds_applied_to_pass_fail": thresholds_applied_to_pass_fail,
            "completion_status": completion_status,
            "execution_tier": "official" if official_validation_executed else "dry_run",
            "formal_ready": bool(stage0_readiness.get("formal_ready")) if stage0_readiness else False,
            "paper_ready": bool(final_paper_ready),
            "final_paper_ready": final_paper_ready,
            "stage2_allowed": False,
            "training_enabled": False,
            "checkpoint_valid": checkpoint_validation["valid"] if checkpoint_validation else False,
            "metadata": {
                "execution_plan": execution_plan,
                "summary_available": summary_payload is not None,
                "experiment_manifest": experiment_manifest,
                "asset_registry_validation": asset_registry_validation,
                "registry_schema_version": asset_registry.get("schema_version") if asset_registry is not None else None,
                "registry_hash": experiment_manifest.get("asset_registry_hash"),
                "required_assets_status": required_assets_status,
                "input_asset_hashes": input_asset_hashes,
                "checkpoint_metadata": checkpoint_metadata,
                "checkpoint_artifact_id": (
                    asset_registry.get("assets", {}).get(STAGE1_CHECKPOINT_ASSET_NAME, {}).get("artifact_id")
                    if asset_registry is not None
                    else None
                ),
                "official_blockers": official_blockers,
                "output_paths": output_paths,
                "sample_counts": {
                    "manifest_rows": len(manifest_rows),
                    "prediction_rows": len(prediction_contracts),
                    "prediction_export_errors": 0 if official_validation_executed else None,
                },
                "excluded_counts": {
                    "excluded_manifest_rows": 0,
                },
                "failure_reason": execution_failure_reason,
                "threshold_version": metric_thresholds.get("approved_threshold_version") or metric_thresholds.get("threshold_status"),
                "kmax_decision_version": stage0_readiness.get("kmax_decision_version") if stage0_readiness else None,
                "selected_kmax": checkpoint_metadata.get("kmax") if checkpoint_metadata else None,
                "consumer_plan_export": {
                    "requested": export_consumer_plans_artifact,
                    "review_ready": consumer_plan_review_ready,
                    "output_jsonl": consumer_plan_output_jsonl.name if export_consumer_plans_artifact else None,
                    "error_jsonl": consumer_plan_error_jsonl.name if export_consumer_plans_artifact else None,
                    "summary_json": consumer_plan_summary_json.name if export_consumer_plans_artifact else None,
                    "summary": consumer_plan_export_summary,
                },
            },
        },
        inputs={
            "protocol_spec": protocol_spec_path,
            "metric_thresholds": metric_thresholds_path,
            "manifest": manifest_path,
            "asset_registry": asset_registry_path,
            "checkpoint": checkpoint_path,
            "prediction_jsonl": runtime_prediction_jsonl,
            "edit_units_jsonl": edit_units_jsonl,
            "stage0_readiness": stage0_readiness_path,
            "official_preflight": official_preflight_path,
            "export_consumer_plans": export_consumer_plans_artifact,
            "consumer_plan_review_ready": consumer_plan_review_ready,
        },
    )
    assert_no_forbidden_training_flags(result)
    manifest_path_out = output_root_path / "stage1_official_validation_manifest.json"
    write_json(manifest_path_out, result)
    write_json(output_root_path / "stage1_official_validation_plan.json", execution_plan)
    if summary_payload is not None:
        write_json(output_root_path / "stage1_official_validation_summary.json", summary_payload)
        write_markdown_report(
            output_root_path / "stage1_official_validation_summary.md",
            "Stage1 Official Validation Summary",
            {
                "Dataset": {
                    "dataset_row_count": summary_payload["dataset_row_count"],
                    "prediction_row_count": summary_payload["prediction_row_count"],
                },
                "PredictedK": summary_payload["prediction_metrics"].get("predicted_k", {}),
            },
        )
    output_hashes = _build_output_hashes(
        [
            manifest_path_out,
            output_root_path / "stage1_official_validation_plan.json",
            output_root_path / "stage1_official_validation_summary.json",
            metrics_json,
            aggregate_metrics_json,
            readiness_json,
            leakage_json,
            checkpoint_metadata_json,
            generated_prediction_jsonl,
            prediction_error_jsonl,
            completion_json,
            stage0_snapshot_json if stage0_readiness is not None else None,
            preflight_snapshot_json if official_preflight is not None else None,
            consumer_plan_output_jsonl if export_consumer_plans_artifact else None,
            consumer_plan_error_jsonl if export_consumer_plans_artifact else None,
            consumer_plan_summary_json if export_consumer_plans_artifact else None,
        ]
    )
    completion_payload = {
        "schema_version": "mica-stage1-official-validation-completion-v1",
        "run_id": result["run_id"],
        "execution_tier": result["execution_tier"],
        "official_validation_executed": official_validation_executed,
        "formal_ready": result["formal_ready"],
        "paper_ready": result["paper_ready"],
        "thresholds_applied_to_pass_fail": thresholds_applied_to_pass_fail,
        "threshold_version": result["metadata"].get("threshold_version"),
        "kmax_decision_version": result["metadata"].get("kmax_decision_version"),
        "selected_kmax": result["metadata"].get("selected_kmax"),
        "checkpoint_artifact_id": result["metadata"].get("checkpoint_artifact_id"),
        "checkpoint_hash": checkpoint_hash,
        "input_asset_hashes": input_asset_hashes,
        "output_hashes": output_hashes,
        "completion_status": completion_status,
    }
    write_json(completion_json, completion_payload)
    output_hashes = _build_output_hashes(
        [
            manifest_path_out,
            output_root_path / "stage1_official_validation_plan.json",
            output_root_path / "stage1_official_validation_summary.json",
            metrics_json,
            aggregate_metrics_json,
            readiness_json,
            leakage_json,
            checkpoint_metadata_json,
            generated_prediction_jsonl,
            prediction_error_jsonl,
            completion_json,
            stage0_snapshot_json if stage0_readiness is not None else None,
            preflight_snapshot_json if official_preflight is not None else None,
            consumer_plan_output_jsonl if export_consumer_plans_artifact else None,
            consumer_plan_error_jsonl if export_consumer_plans_artifact else None,
            consumer_plan_summary_json if export_consumer_plans_artifact else None,
        ]
    )
    result["metadata"]["output_hashes"] = output_hashes
    write_json(manifest_path_out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_official_validation(
        protocol_spec_path=args.protocol_spec,
        metric_thresholds_path=args.metric_thresholds,
        manifest_path=args.manifest,
        asset_registry_path=args.asset_registry,
        checkpoint_path=args.checkpoint,
        prediction_jsonl=args.prediction_jsonl,
        edit_units_jsonl=args.edit_units_jsonl,
        baseline_spec_path=args.baseline_spec,
        stage0_readiness_path=args.stage0_readiness,
        official_preflight_path=args.official_preflight,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        execute=bool(args.execute),
        advisor_approved=bool(args.advisor_approved),
        export_consumer_plans_artifact=bool(args.export_consumer_plans),
        consumer_plan_review_ready=bool(args.consumer_plan_review_ready),
    )
    return 0

def _load_stage1_registry_rows(required_assets_status: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    loaded: dict[str, list[dict[str, Any]]] = {}
    for asset_name, status in required_assets_status.items():
        if str(asset_name) == "stage1_checkpoint_input":
            continue
        path = status.get("path")
        if not path:
            continue
        payload = read_json(path)
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        loaded[asset_name] = [row for row in rows if isinstance(row, dict)]
    return loaded


def _checkpoint_metadata(payload: dict[str, Any], *, checkpoint_hash: str, checkpoint_path: str | Path) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "checkpoint_kind": payload.get("checkpoint_kind"),
        "stage": payload.get("stage"),
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_path": str(checkpoint_path),
        "model_config": payload.get("model_config"),
        "encoder_config": payload.get("encoder_config"),
        "relation_config": payload.get("relation_config"),
        "tokenizer_config": payload.get("tokenizer_config"),
        "training_state": payload.get("training_state"),
        "threshold_version": payload.get("threshold_version"),
        "data_manifest_hashes": payload.get("data_manifest_hashes"),
        "registry_hash": payload.get("registry_hash"),
        "random_seed": payload.get("random_seed"),
        "kmax": payload.get("kmax"),
        "git_commit": payload.get("git_commit"),
        "git_provenance": payload.get("git_provenance"),
        "environment": payload.get("environment"),
    }


def _build_output_hashes(paths: list[Path | None]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        if path is None or not path.exists():
            continue
        hashes[path.name] = sha256_file(path)
    return hashes


if __name__ == "__main__":
    raise SystemExit(main())
