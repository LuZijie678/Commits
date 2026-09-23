from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.data.asset_registry import compute_file_sha256
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl
from code.mica.stage1_v2.campaign import (
    build_annotation_audit_log_template,
    build_annotation_campaign_plan,
    build_annotation_campaign_progress,
    build_annotation_queue_overlap_report,
    build_annotator_registry_template,
    build_calibration_round_assets,
    build_campaign_role_assignment,
    build_deduplicated_human_workload_report,
    build_qualification_execution_assets,
    build_role_conflict_report,
    build_unified_pilot_annotation_index,
)
from code.mica.stage1_v2.materialization import build_annotation_readiness_report, utc_now_iso
from code.mica.stage1_v2.synthetic_scale import materialize_synthetic_scale_and_review_assets


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Stage1-v2 annotation campaign and synthetic scale candidate plan.")
    parser.add_argument("--protocol-spec", default="configs/mica/stage1_v2_protocol_spec.json")
    parser.add_argument("--asset-registry", default="configs/mica/stage1_v2_asset_registry.json")
    parser.add_argument("--output-root", default="datasets/mica/stage1_v2")
    parser.add_argument("--creation-git-sha", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--update-registry", action="store_true")
    return parser


def run_stage1_v2_prepare_campaign(
    *,
    protocol_spec_path: str | Path,
    asset_registry_path: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    validate_only: bool = False,
    update_registry: bool = False,
) -> dict[str, Any]:
    protocol_spec = read_json(protocol_spec_path)
    asset_registry = read_json(asset_registry_path)
    output_root_path = Path(output_root)
    if validate_only:
        return {
            "validate_only": True,
            "protocol_version": str(protocol_spec.get("protocol_version") or "stage1-v2-protocol"),
            "output_root": str(output_root_path),
            "creation_git_sha": creation_git_sha,
        }

    synthetic_root = output_root_path / "synthetic"
    atomic_root = output_root_path / "atomic_source_pool"
    real_count_root = output_root_path / "real_count"
    real_alignment_root = output_root_path / "real_alignment"
    background_root = output_root_path / "background"
    qualification_root = output_root_path / "qualification"
    campaign_root = output_root_path / "campaign"
    readiness_root = output_root_path / "readiness"
    protocol_version = str(protocol_spec.get("protocol_version") or "stage1-v2-protocol")
    created_at = utc_now_iso()

    scale_assets = materialize_synthetic_scale_and_review_assets(
        protocol_spec=protocol_spec,
        train_path=synthetic_root / "synthetic_train.jsonl",
        dev_path=synthetic_root / "synthetic_dev.jsonl",
        control_path=synthetic_root / "synthetic_control_test.jsonl",
        accepted_atomic_sources_path=atomic_root / "accepted_atomic_sources.jsonl",
        manual_review_path=atomic_root / "manual_review_queue.jsonl",
        output_root=synthetic_root,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )

    real_count_rows = read_jsonl(real_count_root / "real_count_annotation_queue_pilot.jsonl")
    real_alignment_rows = read_jsonl(real_alignment_root / "real_adjudicated_pilot_candidates.jsonl")
    background_rows = read_jsonl(background_root / "background_annotation_queue_pilot.jsonl")
    critical_review_rows = read_jsonl(scale_assets["critical_review_path"])
    qualification_test_rows = read_jsonl(qualification_root / "qualification_test.jsonl")

    overlap_report = build_annotation_queue_overlap_report(
        real_count_rows=real_count_rows,
        real_alignment_rows=real_alignment_rows,
        background_rows=background_rows,
        atomic_source_review_rows=critical_review_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    unified_index = build_unified_pilot_annotation_index(
        real_count_rows=real_count_rows,
        real_alignment_rows=real_alignment_rows,
        background_rows=background_rows,
        atomic_source_review_rows=critical_review_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    deduplicated_report = build_deduplicated_human_workload_report(
        unified_index_rows=unified_index,
        overlap_report=overlap_report,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    annotator_registry = build_annotator_registry_template(
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    qualification_assets = build_qualification_execution_assets(
        qualification_test_rows=qualification_test_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    calibration_assets = build_calibration_round_assets(
        pilot_rows=real_alignment_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    campaign_manifest = build_annotation_campaign_plan(
        real_count_rows=real_count_rows,
        real_alignment_rows=real_alignment_rows,
        background_rows=background_rows,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    role_assignment = build_campaign_role_assignment(
        campaign_manifest=campaign_manifest,
        annotator_registry=annotator_registry,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    role_conflict_report = build_role_conflict_report(
        annotator_registry=annotator_registry,
        role_assignment=role_assignment,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    campaign_progress = build_annotation_campaign_progress(
        campaign_manifest=campaign_manifest,
        role_conflict_report=role_conflict_report,
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )
    audit_log_template = build_annotation_audit_log_template(
        protocol_version=protocol_version,
        creation_git_sha=creation_git_sha,
        created_at=created_at,
    )

    campaign_root.mkdir(parents=True, exist_ok=True)
    overlap_path = campaign_root / "annotation_queue_overlap_report.json"
    unified_index_path = campaign_root / "unified_pilot_annotation_index.jsonl"
    workload_path = campaign_root / "deduplicated_human_workload_report.json"
    annotator_registry_path = campaign_root / "annotator_registry.json"
    role_assignment_path = campaign_root / "campaign_role_assignment.json"
    role_conflict_path = campaign_root / "role_conflict_report.json"
    campaign_manifest_path = campaign_root / "annotation_campaign_manifest.json"
    batch_schedule_path = campaign_root / "annotation_batch_schedule.json"
    progress_path = campaign_root / "annotation_campaign_progress.json"
    audit_log_spec_path = campaign_root / "annotation_event_log_spec.json"
    audit_log_path = campaign_root / "annotation_event_log.jsonl"

    qualification_package_a_path = qualification_root / "qualification_package_annotator_a.jsonl"
    qualification_package_b_path = qualification_root / "qualification_package_annotator_b.jsonl"
    qualification_scoring_manifest_path = qualification_root / "qualification_scoring_manifest.json"
    qualification_result_template_path = qualification_root / "qualification_result_template.json"

    calibration_package_a_path = real_alignment_root / "calibration_round_1_annotator_a.jsonl"
    calibration_package_b_path = real_alignment_root / "calibration_round_1_annotator_b.jsonl"
    calibration_blinding_map_path = real_alignment_root / "calibration_round_1_blinding_map.json"
    calibration_adjudication_template_path = real_alignment_root / "calibration_round_1_adjudication_template.jsonl"
    calibration_result_template_path = real_alignment_root / "calibration_round_1_result_template.json"
    calibration_sampling_report_path = real_alignment_root / "calibration_round_1_sampling_report.json"

    write_json(overlap_path, overlap_report)
    write_jsonl(unified_index_path, unified_index)
    write_json(workload_path, deduplicated_report)
    write_json(annotator_registry_path, annotator_registry)
    write_json(role_assignment_path, role_assignment)
    write_json(role_conflict_path, role_conflict_report)
    write_json(campaign_manifest_path, campaign_manifest)
    write_json(batch_schedule_path, {"schema_version": campaign_manifest["schema_version"], "batches": campaign_manifest["batches"]})
    write_json(progress_path, campaign_progress)
    write_json(audit_log_spec_path, audit_log_template)
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path.write_text("", encoding="utf-8")

    write_jsonl(qualification_package_a_path, qualification_assets["annotator_a_package"])
    write_jsonl(qualification_package_b_path, qualification_assets["annotator_b_package"])
    write_json(qualification_scoring_manifest_path, qualification_assets["scoring_manifest"])
    write_json(qualification_result_template_path, qualification_assets["result_template"])

    write_jsonl(calibration_package_a_path, calibration_assets["annotator_a_package"])
    write_jsonl(calibration_package_b_path, calibration_assets["annotator_b_package"])
    write_json(calibration_blinding_map_path, calibration_assets["blinding_map"])
    write_jsonl(calibration_adjudication_template_path, calibration_assets["adjudication_template"])
    write_json(calibration_result_template_path, calibration_assets["result_template"])
    write_json(calibration_sampling_report_path, calibration_assets["sampling_report"])

    readiness = build_annotation_readiness_report(
        protocol_spec=protocol_spec,
        asset_registry=asset_registry,
        real_count_queue_path=real_count_root / "real_count_annotation_queue_pilot.jsonl",
        real_adjudicated_pilot_path=real_alignment_root / "real_adjudicated_pilot_candidates.jsonl",
        background_queue_path=background_root / "background_annotation_queue_pilot.jsonl",
        synthetic_scale_gap_report_path=scale_assets["synthetic_scale_gap_report_path"],
        required_atomic_sources_path=scale_assets["required_atomic_sources_path"],
        role_conflict_report_path=role_conflict_path,
        qualification_result_path=qualification_result_template_path,
        calibration_result_path=calibration_result_template_path,
        campaign_progress_path=progress_path,
    )
    readiness_path = readiness_root / "stage1_v2_annotation_readiness.json"
    readiness_root.mkdir(parents=True, exist_ok=True)
    write_json(readiness_path, readiness)

    if update_registry:
        _update_stage1_v2_asset_registry(
            registry_path=asset_registry_path,
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            path_updates={
                "stage1_v2_synthetic_scale_audit": ("candidate_materialized", scale_assets["synthetic_scale_audit_path"]),
                "stage1_v2_synthetic_scale_gap_report": ("candidate_materialized", scale_assets["synthetic_scale_gap_report_path"]),
                "stage1_v2_synthetic_formal_target_plan": ("candidate_materialized", scale_assets["synthetic_formal_target_plan_path"]),
                "stage1_v2_formal_synthetic_composition_plan": ("candidate_materialized", scale_assets["formal_synthetic_composition_plan_path"]),
                "stage1_v2_required_atomic_sources": ("annotation_pending", scale_assets["required_atomic_sources_path"]),
                "stage1_v2_unresolved_atomic_sources": ("annotation_pending", scale_assets["unresolved_atomic_sources_path"]),
                "stage1_v2_atomic_source_review_critical": ("annotation_pending", scale_assets["critical_review_path"]),
                "stage1_v2_atomic_source_review_deferred": ("annotation_pending", scale_assets["deferred_review_path"]),
                "stage1_v2_annotation_queue_overlap_report": ("candidate_materialized", str(overlap_path)),
                "stage1_v2_unified_pilot_annotation_index": ("candidate_materialized", str(unified_index_path)),
                "stage1_v2_deduplicated_human_workload_report": ("candidate_materialized", str(workload_path)),
                "stage1_v2_annotator_registry": ("candidate_materialized", str(annotator_registry_path)),
                "stage1_v2_campaign_role_assignment": ("annotation_pending", str(role_assignment_path)),
                "stage1_v2_role_conflict_report": ("candidate_materialized", str(role_conflict_path)),
                "stage1_v2_qualification_package_annotator_a": ("annotation_pending", str(qualification_package_a_path)),
                "stage1_v2_qualification_package_annotator_b": ("annotation_pending", str(qualification_package_b_path)),
                "stage1_v2_qualification_scoring_manifest": ("candidate_materialized", str(qualification_scoring_manifest_path)),
                "stage1_v2_qualification_result_template": ("annotation_pending", str(qualification_result_template_path)),
                "stage1_v2_calibration_round_1_annotator_a": ("annotation_pending", str(calibration_package_a_path)),
                "stage1_v2_calibration_round_1_annotator_b": ("annotation_pending", str(calibration_package_b_path)),
                "stage1_v2_calibration_round_1_blinding_map": ("candidate_materialized", str(calibration_blinding_map_path)),
                "stage1_v2_calibration_round_1_adjudication_template": ("annotation_pending", str(calibration_adjudication_template_path)),
                "stage1_v2_calibration_round_1_result_template": ("annotation_pending", str(calibration_result_template_path)),
                "stage1_v2_annotation_campaign_manifest": ("candidate_materialized", str(campaign_manifest_path)),
                "stage1_v2_annotation_batch_schedule": ("candidate_materialized", str(batch_schedule_path)),
                "stage1_v2_annotation_campaign_progress": ("candidate_materialized", str(progress_path)),
                "stage1_v2_annotation_audit_log": ("candidate_materialized", str(audit_log_path)),
                "stage1_v2_annotation_audit_log_spec": ("candidate_materialized", str(audit_log_spec_path)),
            },
        )

    return {
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "synthetic_scale_assets": scale_assets,
        "overlap_report_path": str(overlap_path),
        "unified_index_path": str(unified_index_path),
        "deduplicated_workload_report_path": str(workload_path),
        "role_conflict_report_path": str(role_conflict_path),
        "qualification_scoring_manifest_path": str(qualification_scoring_manifest_path),
        "calibration_sampling_report_path": str(calibration_sampling_report_path),
        "campaign_manifest_path": str(campaign_manifest_path),
        "campaign_progress_path": str(progress_path),
        "annotation_readiness_path": str(readiness_path),
    }


def _update_stage1_v2_asset_registry(
    *,
    registry_path: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    path_updates: dict[str, tuple[str, str]],
) -> None:
    registry = read_json(registry_path)
    assets = dict(registry.get("assets") or {})
    updated_at = utc_now_iso()
    defaults = _default_asset_metadata()
    for asset_name, (status, path_value) in path_updates.items():
        payload = dict(assets.get(asset_name) or defaults.get(asset_name) or _fallback_asset_metadata(asset_name))
        payload["artifact_id"] = str(payload.get("artifact_id") or asset_name)
        payload["status"] = status
        payload["path"] = str(path_value)
        payload["protocol_version"] = protocol_version
        payload["created_by"] = creation_git_sha
        payload["created_at"] = updated_at
        target = Path(path_value)
        payload["sha256"] = compute_file_sha256(target) if target.exists() else None
        payload["record_count"] = _estimate_record_count(target)
        assets[asset_name] = payload
    registry["assets"] = assets
    write_json(registry_path, registry)


def _estimate_record_count(path: str | Path) -> int | None:
    target = Path(path)
    if not target.exists():
        return None
    if target.suffix == ".jsonl":
        with target.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for line in handle if line.strip())
    if target.suffix == ".json":
        payload = read_json(target)
        if isinstance(payload, dict):
            if isinstance(payload.get("rows"), list):
                return len(payload["rows"])
            if isinstance(payload.get("batches"), list):
                return len(payload["batches"])
            if payload.get("row_count") is not None:
                return int(payload["row_count"])
            if payload.get("sample_count") is not None:
                return int(payload["sample_count"])
    return None


def _default_asset_metadata() -> dict[str, dict[str, Any]]:
    return {
        "stage1_v2_synthetic_scale_audit": _asset_template("stage1_v2_synthetic_scale_audit", "mica-stage1-v2-synthetic-scale-audit-v1", "stage1_v2_synthetic_train", "n/a"),
        "stage1_v2_synthetic_scale_gap_report": _asset_template("stage1_v2_synthetic_scale_gap_report", "mica-stage1-v2-synthetic-scale-audit-v1", "stage1_v2_synthetic_train", "n/a"),
        "stage1_v2_synthetic_formal_target_plan": _asset_template("stage1_v2_synthetic_formal_target_plan", "mica-stage1-v2-synthetic-target-plan-v1", "stage1_v2_synthetic_train", "n/a"),
        "stage1_v2_formal_synthetic_composition_plan": _asset_template("stage1_v2_formal_synthetic_composition_plan", "mica-stage1-v2-synthetic-composition-plan-v1", "stage1_v2_synthetic_train", "candidate_plan"),
        "stage1_v2_required_atomic_sources": _asset_template("stage1_v2_required_atomic_sources", "mica-stage1-v2-atomic-source-review-queue-v1", "stage1_v2_atomic_source_quality_report", "candidate_plan"),
        "stage1_v2_unresolved_atomic_sources": _asset_template("stage1_v2_unresolved_atomic_sources", "mica-stage1-v2-atomic-source-review-queue-v1", "stage1_v2_atomic_source_quality_report", "candidate_plan"),
        "stage1_v2_atomic_source_review_critical": _asset_template("stage1_v2_atomic_source_review_critical", "mica-stage1-v2-atomic-source-review-queue-v1", "stage1_v2_atomic_source_quality_report", "critical_review"),
        "stage1_v2_atomic_source_review_deferred": _asset_template("stage1_v2_atomic_source_review_deferred", "mica-stage1-v2-atomic-source-review-queue-v1", "stage1_v2_atomic_source_quality_report", "deferred_review"),
        "stage1_v2_annotation_queue_overlap_report": _asset_template("stage1_v2_annotation_queue_overlap_report", "mica-stage1-v2-annotation-overlap-v1", "stage1_v2_campaign", "n/a"),
        "stage1_v2_unified_pilot_annotation_index": _asset_template("stage1_v2_unified_pilot_annotation_index", "mica-stage1-v2-unified-annotation-index-v1", "stage1_v2_campaign", "pilot"),
        "stage1_v2_deduplicated_human_workload_report": _asset_template("stage1_v2_deduplicated_human_workload_report", "mica-stage1-v2-annotation-overlap-v1", "stage1_v2_campaign", "pilot"),
        "stage1_v2_annotator_registry": _asset_template("stage1_v2_annotator_registry", "mica-stage1-v2-annotator-registry-v1", "stage1_v2_campaign", "staffing"),
        "stage1_v2_campaign_role_assignment": _asset_template("stage1_v2_campaign_role_assignment", "mica-stage1-v2-role-assignment-v1", "stage1_v2_campaign", "staffing"),
        "stage1_v2_role_conflict_report": _asset_template("stage1_v2_role_conflict_report", "mica-stage1-v2-role-conflict-report-v1", "stage1_v2_campaign", "staffing"),
        "stage1_v2_qualification_package_annotator_a": _asset_template("stage1_v2_qualification_package_annotator_a", "mica-stage1-v2-qualification-record-v1", "stage1_v2_qualification", "annotator_a"),
        "stage1_v2_qualification_package_annotator_b": _asset_template("stage1_v2_qualification_package_annotator_b", "mica-stage1-v2-qualification-record-v1", "stage1_v2_qualification", "annotator_b"),
        "stage1_v2_qualification_scoring_manifest": _asset_template("stage1_v2_qualification_scoring_manifest", "mica-stage1-v2-qualification-execution-v1", "stage1_v2_qualification", "n/a"),
        "stage1_v2_qualification_result_template": _asset_template("stage1_v2_qualification_result_template", "mica-stage1-v2-qualification-execution-v1", "stage1_v2_qualification", "pending_result"),
        "stage1_v2_calibration_round_1_annotator_a": _asset_template("stage1_v2_calibration_round_1_annotator_a", "mica-stage1-v2-calibration-round-v1", "stage1_v2_real_adjudicated_queue", "annotator_a"),
        "stage1_v2_calibration_round_1_annotator_b": _asset_template("stage1_v2_calibration_round_1_annotator_b", "mica-stage1-v2-calibration-round-v1", "stage1_v2_real_adjudicated_queue", "annotator_b"),
        "stage1_v2_calibration_round_1_blinding_map": _asset_template("stage1_v2_calibration_round_1_blinding_map", "mica-stage1-v2-calibration-round-v1", "stage1_v2_real_adjudicated_queue", "private"),
        "stage1_v2_calibration_round_1_adjudication_template": _asset_template("stage1_v2_calibration_round_1_adjudication_template", "mica-stage1-v2-calibration-round-v1", "stage1_v2_real_adjudicated_queue", "adjudication"),
        "stage1_v2_calibration_round_1_result_template": _asset_template("stage1_v2_calibration_round_1_result_template", "mica-stage1-v2-calibration-round-v1", "stage1_v2_real_adjudicated_queue", "pending_result"),
        "stage1_v2_annotation_campaign_manifest": _asset_template("stage1_v2_annotation_campaign_manifest", "mica-stage1-v2-annotation-campaign-v1", "stage1_v2_campaign", "manifest"),
        "stage1_v2_annotation_batch_schedule": _asset_template("stage1_v2_annotation_batch_schedule", "mica-stage1-v2-annotation-campaign-v1", "stage1_v2_campaign", "schedule"),
        "stage1_v2_annotation_campaign_progress": _asset_template("stage1_v2_annotation_campaign_progress", "mica-stage1-v2-annotation-progress-v1", "stage1_v2_campaign", "progress"),
        "stage1_v2_annotation_audit_log": _asset_template("stage1_v2_annotation_audit_log", "mica-stage1-v2-annotation-audit-log-v1", "stage1_v2_campaign", "audit_log"),
        "stage1_v2_annotation_audit_log_spec": _asset_template("stage1_v2_annotation_audit_log_spec", "mica-stage1-v2-annotation-audit-log-template-v1", "stage1_v2_campaign", "audit_log_spec"),
    }


def _asset_template(asset_id: str, schema_version: str, source_pool: str, split: str) -> dict[str, Any]:
    return {
        "artifact_id": asset_id,
        "path": None,
        "status": "pending_generation",
        "schema_version": schema_version,
        "source_pool": source_pool,
        "split": split,
        "record_count": None,
        "checksum": None,
        "created_by": "run_stage1_v2_prepare_campaign",
        "created_at": None,
        "leakage_group_key": "sample_id",
        "required_for": ["stage1_v2_annotation_campaign"],
    }


def _fallback_asset_metadata(asset_id: str) -> dict[str, Any]:
    return _asset_template(asset_id, "unknown", "stage1_v2_campaign", "unknown")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_prepare_campaign(
        protocol_spec_path=args.protocol_spec,
        asset_registry_path=args.asset_registry,
        output_root=args.output_root,
        creation_git_sha=args.creation_git_sha,
        validate_only=bool(args.validate_only),
        update_registry=bool(args.update_registry),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
