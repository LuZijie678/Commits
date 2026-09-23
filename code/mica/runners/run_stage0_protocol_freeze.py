from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.experiment.report_schema import build_experiment_report_schema
from code.mica.data.asset_registry import compute_file_sha256, load_asset_registry, resolve_asset_path
from code.mica.eval.kmax_coverage import build_kmax_coverage_report
from code.mica.io_utils import read_json, read_jsonl
from code.mica.reporting import write_json_report, write_markdown_report
from code.mica.stage0.data_card import read_data_card
from code.mica.stage0.eval_protocol import read_eval_protocol
from code.mica.stage0.protocol_freeze import build_stage0_protocol_freeze_readiness
from code.mica.stages.stage1_split_exposure import audit_stage1_split_exposure
from code.mica.training.checkpointing import load_checkpoint, validate_checkpoint_payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 0 protocol freeze readiness runner.")
    parser.add_argument("--data-card", required=True)
    parser.add_argument("--eval-protocol", required=True)
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--metric-thresholds")
    parser.add_argument("--threshold-approval-decision")
    parser.add_argument("--kmax-decision")
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--kmax-report")
    parser.add_argument("--kmax-coverage-rows-jsonl")
    parser.add_argument("--kmax", type=int, default=4)
    parser.add_argument("--kmax-tau", type=float)
    parser.add_argument("--selected-kmax", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run_stage0_protocol_freeze(
    *,
    data_card_path: str | Path,
    eval_protocol_path: str | Path,
    asset_registry_path: str | Path,
    metric_thresholds_path: str | Path | None = None,
    threshold_approval_decision_path: str | Path | None = None,
    kmax_decision_path: str | Path | None = None,
    output_report: str | Path,
    output_md: str | Path,
    kmax_report_path: str | Path | None = None,
    kmax_coverage_rows_jsonl: str | Path | None = None,
    kmax: int = 4,
    kmax_tau: float | None = None,
    selected_kmax: int | None = None,
    dry_run: bool = False,
) -> dict:
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage0_protocol_freeze",
        config_paths=[],
        asset_registry_path=str(asset_registry_path),
        seed=0,
        mode="dry_run",
        advisor_approval=False,
    )
    if not dry_run:
        raise ValueError("Stage 0 protocol freeze runner requires explicit --dry-run.")
    asset_registry = load_asset_registry(str(asset_registry_path))
    loaded_asset_rows = _load_leakage_rows_from_registry(asset_registry)
    if kmax_report_path is not None:
        kmax_report = read_json(kmax_report_path)
    else:
        kmax_rows = read_jsonl(kmax_coverage_rows_jsonl) if kmax_coverage_rows_jsonl else _load_kmax_rows_from_registry(asset_registry)
        kmax_report = build_kmax_coverage_report(
            kmax_rows,
            kmax=kmax,
            tau=kmax_tau,
            selected_kmax=selected_kmax,
        )
    checkpoint_validation = _load_stage1_checkpoint_validation(asset_registry)
    split_exposure_audit = _build_stage1_split_exposure_audit(asset_registry)
    result = build_stage0_protocol_freeze_readiness(
        data_card_text=read_data_card(data_card_path),
        eval_protocol_text=read_eval_protocol(eval_protocol_path),
        asset_registry=asset_registry,
        metric_thresholds=read_json(metric_thresholds_path) if metric_thresholds_path else None,
        loaded_asset_rows=loaded_asset_rows,
        threshold_approval_decision=read_json(threshold_approval_decision_path) if threshold_approval_decision_path else None,
        kmax_decision=read_json(kmax_decision_path) if kmax_decision_path else None,
        checkpoint_validation=checkpoint_validation,
        split_exposure_audit=split_exposure_audit,
    )
    result["kmax_coverage_report"] = kmax_report
    result["input_hashes"] = _build_stage0_input_hashes(
        data_card_path=data_card_path,
        eval_protocol_path=eval_protocol_path,
        asset_registry_path=asset_registry_path,
        metric_thresholds_path=metric_thresholds_path,
        threshold_approval_decision_path=threshold_approval_decision_path,
        kmax_decision_path=kmax_decision_path,
        kmax_report_path=kmax_report_path,
        kmax_coverage_rows_jsonl=kmax_coverage_rows_jsonl,
    )
    result["experiment_manifest"] = experiment_manifest
    result["report_schema"] = build_experiment_report_schema(
        stage="stage0",
        metrics={
            "protocol_freeze_ready": bool(result.get("protocol_freeze_ready", False)),
            "formal_ready": bool(result.get("formal_ready", False)),
            "asset_boundary_error_count": len(result.get("asset_boundary", {}).get("errors", [])),
            "kmax_train_dev_sample_count": result["kmax_coverage_report"]["train_dev_selection_basis"]["sample_count"],
            "kmax_train_dev_overflow_count": result["kmax_coverage_report"]["train_dev_selection_basis"]["overflow_count"],
            "checkpoint_full_model": bool(result.get("checkpoint_full_model", False)),
            "checkpoint_hash_verified": bool(result.get("checkpoint_hash_verified", False)),
            "thresholds_approved": bool(result.get("thresholds_approved", False)),
            "official_final_test_unexposed": bool(result.get("official_final_test_unexposed", False)),
        },
        provenance={
            "git": {
                "dirty": bool(experiment_manifest.get("dirty")),
                "git_commit": experiment_manifest.get("git_commit"),
            },
            "runner_manifest": experiment_manifest,
        },
    )
    write_json_report(output_report, result)
    write_markdown_report(
        output_md,
        "MICA Stage0 Protocol Freeze Readiness",
        {
            "Status": {
                "protocol_freeze_ready": result["protocol_freeze_ready"],
                "formal_ready": result["formal_ready"],
                "dry_run": result["dry_run"],
                "training_executed": result["training_executed"],
            },
            "Decisions": {
                "thresholds_approved": result["thresholds_approved"],
                "approved_threshold_version": result.get("approved_threshold_version"),
                "Kmax_protocol_frozen": result["Kmax_protocol_frozen"],
                "kmax_decision_version": result.get("kmax_decision_version"),
            },
            "Checkpoint": {
                "checkpoint_full_model": result["checkpoint_full_model"],
                "checkpoint_loadable": result["checkpoint_loadable"],
                "checkpoint_hash_verified": result["checkpoint_hash_verified"],
            },
            "Final Test": {
                "official_final_test_manifest_frozen": result["official_final_test_manifest_frozen"],
                "official_final_test_unexposed": result["official_final_test_unexposed"],
            },
            "Data Card": result["data_card"],
            "Eval Protocol": result["eval_protocol"],
            "Asset Boundary": {"valid": result["asset_boundary"]["valid"], "errors": len(result["asset_boundary"]["errors"])},
            "Kmax Coverage": result["kmax_coverage_report"],
        },
    )
    return result


def _load_stage1_checkpoint_validation(asset_registry: dict[str, Any]) -> dict[str, Any]:
    checkpoint_path = resolve_asset_path(asset_registry, "stage1_checkpoint_input")
    if not checkpoint_path:
        return {"valid": False, "checkpoint_kind": None, "errors": ["asset_not_materialized"]}
    try:
        payload = load_checkpoint(checkpoint_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return {"valid": False, "checkpoint_kind": None, "errors": ["invalid_checkpoint_payload"]}
    return validate_checkpoint_payload(payload, require_full_model_state=True)


def _load_leakage_rows_from_registry(asset_registry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    assets = asset_registry.get("assets", {})
    if not isinstance(assets, dict):
        return {}
    included_assets = {
        "step1_high_conf_single_train",
        "step1_high_conf_single_dev",
        "step1_high_conf_single_test",
        "strict_synthetic_train",
        "strict_synthetic_dev",
        "strict_synthetic_test",
    }
    loaded: dict[str, list[dict[str, Any]]] = {}
    for asset_name, payload in sorted(assets.items()):
        if asset_name not in included_assets or not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") != "frozen":
            continue
        if str(payload.get("schema_version") or "") != "mica-formal-asset-manifest-v1":
            continue
        path = payload.get("path")
        if not path:
            continue
        content = read_json(path)
        if not isinstance(content, dict) or not isinstance(content.get("rows"), list):
            continue
        loaded[str(asset_name)] = [row for row in content["rows"] if isinstance(row, dict)]
    return loaded


def _build_stage1_split_exposure_audit(asset_registry: dict[str, Any]) -> dict[str, Any]:
    return audit_stage1_split_exposure(
        candidate_manifest_path=resolve_asset_path(asset_registry, "stage1_official_validation_dev"),
        current_official_manifest_path=resolve_asset_path(asset_registry, "stage1_official_final_test"),
        proposed_final_test_manifest_paths=[
            path
            for path in (
                resolve_asset_path(asset_registry, "stage1_official_final_test"),
                resolve_asset_path(asset_registry, "step1_high_conf_single_test"),
                resolve_asset_path(asset_registry, "strict_synthetic_test"),
            )
            if path
        ],
    )


def _build_stage0_input_hashes(
    *,
    data_card_path: str | Path,
    eval_protocol_path: str | Path,
    asset_registry_path: str | Path,
    metric_thresholds_path: str | Path | None,
    threshold_approval_decision_path: str | Path | None,
    kmax_decision_path: str | Path | None,
    kmax_report_path: str | Path | None,
    kmax_coverage_rows_jsonl: str | Path | None,
) -> dict[str, str | None]:
    return {
        "data_card": compute_file_sha256(data_card_path),
        "eval_protocol": compute_file_sha256(eval_protocol_path),
        "asset_registry": compute_file_sha256(asset_registry_path),
        "metric_thresholds": compute_file_sha256(metric_thresholds_path) if metric_thresholds_path else None,
        "threshold_approval_decision": (
            compute_file_sha256(threshold_approval_decision_path) if threshold_approval_decision_path else None
        ),
        "kmax_decision": compute_file_sha256(kmax_decision_path) if kmax_decision_path else None,
        "kmax_report": compute_file_sha256(kmax_report_path) if kmax_report_path else None,
        "kmax_coverage_rows_jsonl": compute_file_sha256(kmax_coverage_rows_jsonl) if kmax_coverage_rows_jsonl else None,
    }


def _load_kmax_rows_from_registry(asset_registry: dict[str, Any]) -> list[dict[str, Any]]:
    assets = asset_registry.get("assets", {})
    if not isinstance(assets, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for asset_name, payload in sorted(assets.items()):
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") != "frozen":
            continue
        if str(payload.get("schema_version") or "") != "mica-formal-asset-manifest-v1":
            continue
        if str(asset_name) in {"stage1_official_validation_dev", "stage1_official_final_test", "m_final_test"}:
            continue
        path = payload.get("path")
        if not path:
            continue
        content = read_json(path)
        for row in content.get("rows", []) if isinstance(content, dict) else []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("sample_id") or ""),
                str(row.get("split") or ""),
                str(row.get("source_type") or row.get("source_kind") or ""),
                str(row.get("commit_id") or row.get("source_sha") or ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append(dict(row, asset_name=str(asset_name)))
    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage0_protocol_freeze(
        data_card_path=args.data_card,
        eval_protocol_path=args.eval_protocol,
        asset_registry_path=args.asset_registry,
        metric_thresholds_path=args.metric_thresholds,
        threshold_approval_decision_path=args.threshold_approval_decision,
        kmax_decision_path=args.kmax_decision,
        output_report=args.output_report,
        output_md=args.output_md,
        kmax_report_path=args.kmax_report,
        kmax_coverage_rows_jsonl=args.kmax_coverage_rows_jsonl,
        kmax=args.kmax,
        kmax_tau=args.kmax_tau,
        selected_kmax=args.selected_kmax,
        dry_run=bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
