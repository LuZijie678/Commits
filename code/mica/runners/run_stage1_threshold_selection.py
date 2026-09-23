from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.config_validation import validate_threshold_spec
from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.io_utils import read_json, write_json
from code.mica.run_manifest import build_run_manifest
from code.mica.runners.stage1_runtime import (
    STAGE1_CHECKPOINT_ASSET_NAME,
    STAGE1_VALIDATION_ASSET_NAME,
    build_threshold_metric_snapshot,
    evaluate_metric_thresholds,
    load_formal_asset_rows,
    load_stage1_samples_from_rows,
    resolve_formal_asset_entry,
    sha256_file,
    validate_registry_bound_checkpoint,
    validate_registry_bound_manifest,
)
from code.mica.train.eval_stage1_sanity import evaluate_model
from code.mica.training.checkpointing import instantiate_backend_from_checkpoint, load_checkpoint, validate_checkpoint_payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select a real dev-backed Stage 1 threshold candidate.")
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--manifest")
    parser.add_argument("--write-thresholds-path")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def run_stage1_threshold_selection(
    *,
    asset_registry_path: str | Path,
    metric_thresholds_path: str | Path,
    output_root: str | Path,
    checkpoint_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    write_thresholds_path: str | Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    mode_count = sum(bool(flag) for flag in (dry_run, validate_only, execute))
    if mode_count != 1:
        raise ValueError("Stage 1 threshold selection requires exactly one of --dry-run, --validate-only, or --execute.")

    asset_registry = load_asset_registry(str(asset_registry_path))
    asset_registry_validation = validate_asset_registry(asset_registry)
    threshold_spec = read_json(metric_thresholds_path)
    threshold_validation = validate_threshold_spec(threshold_spec)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage1_threshold_selection",
        config_paths=[str(metric_thresholds_path)],
        asset_registry_path=str(asset_registry_path),
        seed=0,
        mode="execute" if execute else ("validate_only" if validate_only else "dry_run"),
        advisor_approval=False,
    )

    output_root_path = Path(output_root)
    _ensure_output_root(output_root_path, overwrite=overwrite)
    manifest_json = output_root_path / "stage1_threshold_selection_manifest.json"
    report_json = output_root_path / "stage1_threshold_selection_report.json"
    readiness_json = output_root_path / "stage1_threshold_selection_readiness.json"

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
    readiness_payload = {
        "asset_registry_validation": asset_registry_validation,
        "threshold_validation": threshold_validation,
        "checkpoint_target": str(checkpoint_target),
        "manifest_target": str(manifest_target),
        "mode": "execute" if execute else ("validate_only" if validate_only else "dry_run"),
        "experiment_manifest": experiment_manifest,
    }
    write_json(readiness_json, readiness_payload)

    if dry_run or validate_only:
        result = build_run_manifest(
            stage="stage1_threshold_selection",
            mode="validate_only" if validate_only else "dry_run",
            output_root=str(output_root_path),
            flags={
                "training_enabled": False,
                "official_validation_executed": False,
                "completion_status": "not_executed",
                "threshold_candidate_selected": False,
                "metadata": readiness_payload,
            },
            inputs={
                "asset_registry": asset_registry_path,
                "metric_thresholds": metric_thresholds_path,
                "checkpoint": checkpoint_target,
                "manifest": manifest_target,
            },
        )
        write_json(manifest_json, result)
        return result

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
        raise ValueError("Stage 1 threshold selection requires a full-model checkpoint: " + ",".join(checkpoint_validation["errors"]))

    backend = instantiate_backend_from_checkpoint(checkpoint_payload)
    model = backend.model
    manifest_rows = load_formal_asset_rows(manifest_target)
    dev_samples = load_stage1_samples_from_rows(manifest_rows)
    batch_size = int(checkpoint_payload.get("training_state", {}).get("batch_size", 8) or 8)
    dev_metrics = evaluate_model(model, dev_samples, batch_size=batch_size, device="cpu")
    checkpoint_hash = sha256_file(checkpoint_target)
    manifest_hash = sha256_file(manifest_target)
    gate_results = evaluate_metric_thresholds(dev_metrics, threshold_spec)
    updated_thresholds = _build_updated_threshold_spec(
        threshold_spec=threshold_spec,
        checkpoint_hash=checkpoint_hash,
        dev_manifest_hash=manifest_hash,
        dev_metrics=dev_metrics,
        gate_results=gate_results,
        experiment_manifest=experiment_manifest,
    )
    updated_validation = validate_threshold_spec(updated_thresholds)
    if not updated_validation["valid"]:
        raise ValueError("Updated Stage 1 threshold candidate is invalid: " + ",".join(updated_validation["errors"]))
    write_json(write_thresholds_path or metric_thresholds_path, updated_thresholds)
    report_payload = {
        "status": updated_thresholds["threshold_status"],
        "checkpoint_hash": checkpoint_hash,
        "dev_manifest_hash": manifest_hash,
        "sample_count": len(dev_samples),
        "excluded_count": 0,
        "selection_split": "dev_only",
        "selection_criterion": updated_thresholds["selection_criterion"],
        "selected_operating_point": updated_thresholds["selected_operating_point"],
        "candidate_thresholds": {
            key: value for key, value in updated_thresholds.items() if key.endswith(("_min", "_max"))
        },
        "observed_dev_metrics": updated_thresholds["observed_dev_metrics"],
        "gate_results": gate_results,
        "git_commit": experiment_manifest.get("git_commit"),
        "approved_threshold_version": updated_thresholds.get("approved_threshold_version"),
    }
    write_json(report_json, report_payload)
    result = build_run_manifest(
        stage="stage1_threshold_selection",
        mode="execute",
        output_root=str(output_root_path),
        flags={
            "training_enabled": False,
            "official_validation_executed": False,
            "completion_status": "completed",
            "threshold_candidate_selected": True,
            "metadata": {
                "checkpoint_hash": checkpoint_hash,
                "dev_manifest_hash": manifest_hash,
                "gate_results": gate_results,
                "report_path": str(report_json),
                "thresholds_path": str(write_thresholds_path or metric_thresholds_path),
                "experiment_manifest": experiment_manifest,
            },
        },
        inputs={
            "asset_registry": asset_registry_path,
            "metric_thresholds": metric_thresholds_path,
            "checkpoint": checkpoint_target,
            "manifest": manifest_target,
        },
    )
    write_json(manifest_json, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_threshold_selection(
        asset_registry_path=args.asset_registry,
        metric_thresholds_path=args.metric_thresholds,
        output_root=args.output_root,
        checkpoint_path=args.checkpoint,
        manifest_path=args.manifest,
        write_thresholds_path=args.write_thresholds_path,
        overwrite=bool(args.overwrite),
        dry_run=bool(args.dry_run),
        validate_only=bool(args.validate_only),
        execute=bool(args.execute),
    )
    return 0


def _build_updated_threshold_spec(
    *,
    threshold_spec: dict[str, Any],
    checkpoint_hash: str,
    dev_manifest_hash: str,
    dev_metrics: dict[str, Any],
    gate_results: dict[str, dict[str, Any]],
    experiment_manifest: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(threshold_spec)
    updated["threshold_status"] = "candidate_selected_pending_approval"
    updated["approved_threshold_version"] = None
    updated["candidate_threshold_version"] = f"stage1_dev_candidate_{checkpoint_hash[:12]}"
    updated["selection_split"] = "dev_only"
    updated["selection_criterion"] = "stage1_dev_metric_gate"
    updated["selected_operating_point"] = "stage1_dev_metric_gate_v1"
    updated["selected_checkpoint_hash"] = checkpoint_hash
    updated["selected_dev_manifest_hash"] = dev_manifest_hash
    updated["selected_on_utc"] = datetime.now(timezone.utc).isoformat()
    updated["observed_dev_metrics"] = build_threshold_metric_snapshot(dev_metrics, threshold_spec)
    updated["gate_results"] = gate_results
    updated["all_candidate_gates_pass"] = all(item["passed"] for item in gate_results.values()) if gate_results else False
    updated["selection_provenance"] = {
        "runner_name": experiment_manifest.get("runner_name"),
        "git_commit": experiment_manifest.get("git_commit"),
        "asset_registry_hash": experiment_manifest.get("asset_registry_hash"),
    }
    return updated


def _ensure_output_root(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if any(path.iterdir()) and not overwrite:
            raise FileExistsError(f"Output directory is not empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
