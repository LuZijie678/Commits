from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, validate_asset_registry
from code.mica.experiment.provenance import capture_git_provenance
from code.mica.io_utils import read_json, write_json
from code.mica.runners.registry import get_runner_policy
from code.mica.runners.stage1_runtime import STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, STAGE1_VALIDATION_ASSET_NAME, validate_clean_checkpoint_provenance
from code.mica.stages.stage1_split_exposure import audit_stage1_split_exposure
from code.mica.training.checkpointing import load_checkpoint, validate_checkpoint_payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only preflight for future official Stage 1 validation.")
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--threshold-approval-packet", required=True)
    parser.add_argument("--kmax-decision-packet", required=True)
    parser.add_argument("--stage0-readiness", required=True)
    parser.add_argument("--planned-output-root", required=True)
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def run_stage1_official_preflight(
    *,
    asset_registry_path: str | Path,
    metric_thresholds_path: str | Path,
    threshold_approval_packet_path: str | Path,
    kmax_decision_packet_path: str | Path,
    stage0_readiness_path: str | Path,
    planned_output_root: str | Path,
    output_report: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_report)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Preflight report already exists: {output_path}")
    asset_registry = load_asset_registry(asset_registry_path)
    asset_registry_validation = validate_asset_registry(asset_registry)
    threshold_spec = read_json(metric_thresholds_path)
    threshold_packet = read_json(threshold_approval_packet_path)
    kmax_packet = read_json(kmax_decision_packet_path)
    stage0_readiness = read_json(stage0_readiness_path)
    git_provenance = capture_git_provenance(str(ROOT))
    checkpoint_path = asset_registry_validation.get("asset_status", {}).get("stage1_checkpoint_input", {}).get("path")
    checkpoint_payload = load_checkpoint(checkpoint_path) if checkpoint_path else {}
    checkpoint_validation = validate_checkpoint_payload(checkpoint_payload, require_full_model_state=True) if checkpoint_path else {
        "valid": False,
        "errors": ["asset_not_materialized"],
    }
    checkpoint_entry_metadata = dict(asset_registry.get("assets", {}).get("stage1_checkpoint_input", {}).get("metadata", {}))
    checkpoint_provenance_validation = validate_clean_checkpoint_provenance(
        checkpoint_payload,
        fallback_metadata=checkpoint_entry_metadata,
    ) if checkpoint_payload else {
        "valid": False,
        "errors": ["asset_not_materialized"],
        "git_provenance": {},
    }
    checkpoint_git_provenance = dict(checkpoint_payload.get("git_provenance", {})) if isinstance(checkpoint_payload, dict) else {}
    split_audit = audit_stage1_split_exposure(
        candidate_manifest_path=asset_registry_validation.get("asset_status", {}).get(STAGE1_VALIDATION_ASSET_NAME, {}).get("path"),
        current_official_manifest_path=asset_registry_validation.get("asset_status", {}).get(STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, {}).get("path"),
        proposed_final_test_manifest_paths=[
            path
            for path in (
                asset_registry_validation.get("asset_status", {}).get(STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, {}).get("path"),
                asset_registry_validation.get("asset_status", {}).get("step1_high_conf_single_test", {}).get("path"),
                asset_registry_validation.get("asset_status", {}).get("strict_synthetic_test", {}).get("path"),
            )
            if path
        ],
    )
    planned_output_root_path = Path(planned_output_root)
    final_test_status = dict(asset_registry_validation.get("asset_status", {}).get(STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, {}))
    checkpoint_status = dict(asset_registry_validation.get("asset_status", {}).get("stage1_checkpoint_input", {}))
    local_checkpoint_match = checkpoint_status.get("checksum_match")
    threshold_version_approved = (
        str(threshold_packet.get("status") or "") == "approved"
        and str(threshold_packet.get("approved_threshold_version") or "")
        == str(threshold_spec.get("approved_threshold_version") or "")
        == str(threshold_spec.get("threshold_status") or "")
    )
    kmax_decision_approved = str(kmax_packet.get("status") or "") == "approved"
    official_final_test_unexposed = str(split_audit.get("conclusion") or "") == "dev_only_unexposed_final_test"
    output_destination_available = (not planned_output_root_path.exists()) or (not any(planned_output_root_path.iterdir()))
    runner_policy = get_runner_policy("run_stage1_official_validation")
    gates = {
        "clean_execution_code_state": not bool(git_provenance.get("dirty")),
        "checkpoint_clean_provenance": bool(checkpoint_provenance_validation.get("valid")),
        "logical_checkpoint_active_and_frozen": str(checkpoint_status.get("status") or "") == "frozen",
        "checkpoint_materialized": bool(checkpoint_status.get("file_exists")),
        "checkpoint_hash_match": local_checkpoint_match is True,
        "checkpoint_loadable": bool(checkpoint_validation.get("valid")),
        "threshold_version_approved": threshold_version_approved,
        "kmax_decision_approved": kmax_decision_approved,
        "stage0_formal_ready": bool(stage0_readiness.get("formal_ready")),
        "candidate_validation_split_must_not_equal_official_final_test_split": bool(
            split_audit.get("candidate_validation_split_must_not_equal_official_final_test_split")
        ),
        "official_final_test_unexposed": official_final_test_unexposed,
        "final_test_manifest_frozen": bool(final_test_status.get("formal_ready")),
        "leakage_clean": int(split_audit.get("proposed_final_leakage_overlap_count", 0) or 0) == 0,
        "output_destination_available": output_destination_available,
        "non_fixture": runner_policy.get("default_mode") != "fixture",
        "non_sanity": "sanity" not in str(runner_policy.get("purpose") or "").lower(),
        "non_dry_run": True,
        "non_validate_only": True,
    }
    gates.update(
        {
            "clean_git_worktree": gates["clean_execution_code_state"],
            "clean_commit_checkpoint_provenance": gates["checkpoint_clean_provenance"],
            "logical_registry_materialized_hash_match": gates["checkpoint_hash_match"],
            "thresholds_approved": gates["threshold_version_approved"],
            "kmax_approved": gates["kmax_decision_approved"],
            "official_final_test_manifest_frozen": gates["final_test_manifest_frozen"],
            "required_output_location_empty": gates["output_destination_available"],
            "not_fixture_or_sanity": gates["non_fixture"] and gates["non_sanity"],
            "checkpoint_payload_valid": gates["checkpoint_loadable"],
            "threshold_checkpoint_hash_matches_spec": threshold_packet.get("checkpoint_hash") == threshold_spec.get("selected_checkpoint_hash"),
        }
    )
    result = {
        "schema_version": "mica-stage1-official-preflight-v1",
        "status": "ready" if all(gates.values()) else "blocked",
        "gates": gates,
        "git_provenance": git_provenance,
        "checkpoint_git_provenance": checkpoint_git_provenance,
        "checkpoint_validation": checkpoint_validation,
        "checkpoint_provenance_validation": checkpoint_provenance_validation,
        "stage0_readiness": {
            "formal_ready": bool(stage0_readiness.get("formal_ready")),
            "thresholds_approved": bool(stage0_readiness.get("thresholds_approved")),
            "Kmax_protocol_frozen": bool(stage0_readiness.get("Kmax_protocol_frozen")),
            "official_final_test_unexposed": bool(stage0_readiness.get("official_final_test_unexposed")),
        },
        "split_exposure_audit": split_audit,
        "threshold_packet_status": threshold_packet.get("status"),
        "kmax_packet_status": kmax_packet.get("status"),
        "threshold_version": threshold_packet.get("approved_threshold_version"),
        "kmax_decision_version": kmax_packet.get("decision_version"),
        "official_runner_target_asset": STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME,
        "candidate_validation_asset": STAGE1_VALIDATION_ASSET_NAME,
        "future_official_final_test_asset": STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME,
    }
    write_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_official_preflight(
        asset_registry_path=args.asset_registry,
        metric_thresholds_path=args.metric_thresholds,
        threshold_approval_packet_path=args.threshold_approval_packet,
        kmax_decision_packet_path=args.kmax_decision_packet,
        stage0_readiness_path=args.stage0_readiness,
        planned_output_root=args.planned_output_root,
        output_report=args.output_report,
        overwrite=bool(args.overwrite),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
