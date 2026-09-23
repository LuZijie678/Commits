from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.io_utils import read_json, write_json, write_jsonl
from code.mica.run_manifest import build_run_manifest
from code.mica.runners.stage1_runtime import (
    STAGE1_CHECKPOINT_ASSET_NAME,
    STAGE1_VALIDATION_ASSET_NAME,
    build_required_asset_status,
    derive_official_blockers,
    evaluate_metric_thresholds,
    generate_stage1_prediction_rows,
    input_asset_hashes,
    load_formal_asset_rows,
    load_stage1_samples_from_rows,
    required_assets_ready,
    resolve_formal_asset_entry,
    sha256_file,
    validate_registry_bound_checkpoint,
    validate_registry_bound_manifest,
)
from code.mica.stage0.leakage_report import build_global_leakage_report
from code.mica.stages.stage1_official_validation import (
    build_stage1_official_summary,
    build_stage1_validation_dataset,
    evaluate_stage1_predictions,
    evaluate_stage1_with_baselines,
)
from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.training.checkpointing import instantiate_backend_from_checkpoint, load_checkpoint, validate_checkpoint_payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute a real but non-formal Stage 1 candidate validation run.")
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--manifest")
    parser.add_argument("--baseline-spec")
    parser.add_argument("--stage0-readiness")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def run_stage1_candidate_validation(
    *,
    asset_registry_path: str | Path,
    metric_thresholds_path: str | Path,
    output_root: str | Path,
    checkpoint_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    baseline_spec_path: str | Path | None = None,
    stage0_readiness_path: str | Path | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    if bool(validate_only) == bool(execute):
        raise ValueError("Stage 1 candidate validation requires exactly one of --validate-only or --execute.")

    asset_registry = load_asset_registry(str(asset_registry_path))
    asset_registry_validation = validate_asset_registry(asset_registry)
    threshold_spec = read_json(metric_thresholds_path)
    stage0_readiness = read_json(stage0_readiness_path) if stage0_readiness_path is not None else None
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage1_candidate_validation",
        config_paths=[str(metric_thresholds_path)],
        asset_registry_path=str(asset_registry_path),
        seed=0,
        mode="execute" if execute else "validate_only",
        advisor_approval=False,
    )

    output_root_path = Path(output_root)
    _ensure_output_root(output_root_path, overwrite=overwrite)
    manifest_json = output_root_path / "stage1_candidate_validation_manifest.json"
    summary_json = output_root_path / "stage1_candidate_validation_summary.json"
    metrics_json = output_root_path / "stage1_candidate_validation_metrics.json"
    predictions_jsonl = output_root_path / "stage1_candidate_validation_predictions.jsonl"
    prediction_errors_jsonl = output_root_path / "stage1_candidate_validation_prediction_export_errors.jsonl"
    readiness_json = output_root_path / "stage1_candidate_validation_readiness.json"
    leakage_json = output_root_path / "stage1_candidate_validation_leakage_report.json"

    checkpoint_target = checkpoint_path or resolve_formal_asset_entry(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_name=STAGE1_CHECKPOINT_ASSET_NAME,
        require_formal_ready=execute,
    )["path"]
    manifest_target = manifest_path or resolve_formal_asset_entry(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_name=STAGE1_VALIDATION_ASSET_NAME,
        require_formal_ready=True,
    )["path"]
    required_assets_status = build_required_asset_status(
        asset_registry_validation,
        ("step1_high_conf_single_dev", "strict_synthetic_dev", STAGE1_VALIDATION_ASSET_NAME, STAGE1_CHECKPOINT_ASSET_NAME),
    )
    official_blockers = derive_official_blockers(
        stage0_readiness=stage0_readiness,
        threshold_spec=threshold_spec,
    )
    readiness_payload = {
        "asset_registry_validation": asset_registry_validation,
        "required_assets_status": required_assets_status,
        "checkpoint_target": str(checkpoint_target),
        "manifest_target": str(manifest_target),
        "official_blockers": official_blockers,
        "execution_tier": "candidate_nonformal",
        "experiment_manifest": experiment_manifest,
    }
    write_json(readiness_json, readiness_payload)

    if validate_only:
        result = build_run_manifest(
            stage="stage1_candidate_validation",
            mode="validate_only",
            output_root=str(output_root_path),
            flags={
                "training_enabled": False,
                "official_validation_executed": False,
                "validation_run_executed": False,
                "formal_ready": False,
                "paper_ready": False,
                "execution_tier": "candidate_nonformal",
                "completion_status": "not_executed",
                "metadata": readiness_payload,
            },
            inputs={
                "asset_registry": asset_registry_path,
                "metric_thresholds": metric_thresholds_path,
                "checkpoint": checkpoint_target,
                "manifest": manifest_target,
                "stage0_readiness": stage0_readiness_path,
            },
        )
        write_json(manifest_json, result)
        return result

    if not required_assets_ready(required_assets_status):
        missing = ",".join(sorted(name for name, status in required_assets_status.items() if not status.get("formal_ready")))
        raise ValueError(f"Stage 1 candidate validation requires formal-ready dev assets and checkpoint: {missing}")
    threshold_status = str(threshold_spec.get("threshold_status") or "")
    if "candidate_selected" not in threshold_status and "frozen" not in threshold_status:
        raise ValueError("Stage 1 candidate validation requires a selected candidate or frozen threshold payload.")

    validate_registry_bound_checkpoint(
        checkpoint_path=checkpoint_target,
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
    )
    validate_registry_bound_manifest(
        manifest_path=manifest_target,
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
    )
    checkpoint_payload = load_checkpoint(checkpoint_target)
    checkpoint_validation = validate_checkpoint_payload(checkpoint_payload, require_full_model_state=True)
    if not checkpoint_validation["valid"]:
        raise ValueError("Stage 1 candidate validation requires a full-model checkpoint: " + ",".join(checkpoint_validation["errors"]))

    backend = instantiate_backend_from_checkpoint(checkpoint_payload)
    manifest_rows = load_formal_asset_rows(manifest_target)
    prediction_rows = generate_stage1_prediction_rows(
        backend=backend,
        manifest_rows=manifest_rows,
        source="stage1_candidate_validation_execute",
    )
    write_jsonl(predictions_jsonl, prediction_rows)
    write_jsonl(prediction_errors_jsonl, [])

    dataset = build_stage1_validation_dataset(manifest_rows, prediction_rows)
    prediction_metrics = evaluate_stage1_predictions(dataset["gold_rows"], dataset["prediction_rows"], {"report_oracle_k": True})
    baseline_metrics = evaluate_stage1_with_baselines(
        dataset["gold_rows"],
        dataset["prediction_rows"],
        read_json(baseline_spec_path) if baseline_spec_path is not None else {"baselines": []},
    )
    summary_payload = build_stage1_official_summary(
        dataset=dataset,
        prediction_metrics=prediction_metrics,
        baseline_metrics=baseline_metrics,
        official_validation_executed=False,
        thresholds_applied_to_pass_fail=True,
        completion_status="executed_nonformal",
        final_paper_ready=False,
    )
    dev_samples = load_stage1_samples_from_rows(manifest_rows)
    dev_gate_metrics = evaluate_model(
        backend.model,
        dev_samples,
        batch_size=int(checkpoint_payload.get("training_state", {}).get("batch_size", 8) or 8),
        device="cpu",
    )
    gate_results = evaluate_metric_thresholds(dev_gate_metrics, threshold_spec)
    summary_payload["dev_gate_metrics"] = dev_gate_metrics
    summary_payload["dev_gate_results"] = gate_results
    summary_payload["execution_tier"] = "candidate_nonformal"
    summary_payload["official_blockers"] = official_blockers
    write_json(metrics_json, summary_payload)
    write_json(summary_json, summary_payload)
    leakage_payload = build_global_leakage_report(
        asset_registry,
        {
            "stage1_candidate_validation_manifest": manifest_rows,
        },
    )
    write_json(leakage_json, leakage_payload)
    write_json(
        readiness_json,
        {
            **readiness_payload,
            "checkpoint_validation": checkpoint_validation,
            "threshold_status": threshold_status,
            "validation_run_executed": True,
        },
    )
    result = build_run_manifest(
        stage="stage1_candidate_validation",
        mode="execute",
        output_root=str(output_root_path),
        flags={
            "training_enabled": False,
            "official_validation_executed": False,
            "validation_run_executed": True,
            "formal_ready": False,
            "paper_ready": False,
            "execution_tier": "candidate_nonformal",
            "thresholds_applied_to_pass_fail": True,
            "completion_status": "executed_nonformal",
            "metadata": {
                "official_blockers": official_blockers,
                "required_assets_status": required_assets_status,
                "input_asset_hashes": input_asset_hashes(required_assets_status),
                "checkpoint_hash": sha256_file(checkpoint_target),
                "manifest_hash": sha256_file(manifest_target),
                "output_paths": {
                    "predictions": predictions_jsonl.name,
                    "prediction_errors": prediction_errors_jsonl.name,
                    "metrics": metrics_json.name,
                    "summary": summary_json.name,
                    "readiness": readiness_json.name,
                    "leakage_report": leakage_json.name,
                },
                "experiment_manifest": experiment_manifest,
            },
        },
        inputs={
            "asset_registry": asset_registry_path,
            "metric_thresholds": metric_thresholds_path,
            "checkpoint": checkpoint_target,
            "manifest": manifest_target,
            "stage0_readiness": stage0_readiness_path,
        },
    )
    write_json(manifest_json, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_candidate_validation(
        asset_registry_path=args.asset_registry,
        metric_thresholds_path=args.metric_thresholds,
        output_root=args.output_root,
        checkpoint_path=args.checkpoint,
        manifest_path=args.manifest,
        baseline_spec_path=args.baseline_spec,
        stage0_readiness_path=args.stage0_readiness,
        overwrite=bool(args.overwrite),
        validate_only=bool(args.validate_only),
        execute=bool(args.execute),
    )
    return 0


def _ensure_output_root(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if any(path.iterdir()) and not overwrite:
            raise FileExistsError(f"Output directory is not empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
