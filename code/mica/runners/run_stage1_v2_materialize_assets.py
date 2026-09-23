from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.data.asset_registry import compute_file_sha256
from code.mica.io_utils import read_json, write_json
from code.mica.stage1_v2.materialization import (
    DEFAULT_ANNOTATION_VERSION,
    DEFAULT_COUNT_GUIDELINE_VERSION,
    DEFAULT_PILOT_GUIDELINE_VERSION,
    audit_atomic_source_pool,
    build_background_annotation_assets,
    build_qualification_materials,
    build_real_adjudicated_assets,
    build_real_count_candidate_assets,
    build_annotation_readiness_report,
    materialize_family_safe_synthetic_assets,
    utc_now_iso,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize Stage1-v2 candidate assets and pilot annotation packages.")
    parser.add_argument("--protocol-spec", default="configs/mica/stage1_v2_protocol_spec.json")
    parser.add_argument("--asset-registry", default="configs/mica/stage1_v2_asset_registry.json")
    parser.add_argument("--atomic-source-csv", default="datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv")
    parser.add_argument("--m-verified-csv", default="datasets/m_verified/canonical/usable_m_with_real_diff.csv")
    parser.add_argument("--hard-b-csv", default="datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv")
    parser.add_argument("--stage1-v1-final-test", default="datasets/mica/formal_assets/stage1/stage1_official_final_test.json")
    parser.add_argument("--output-root", default="datasets/mica/stage1_v2")
    parser.add_argument("--creation-git-sha", required=True)
    parser.add_argument("--guideline-version", default=DEFAULT_PILOT_GUIDELINE_VERSION)
    parser.add_argument("--count-guideline-version", default=DEFAULT_COUNT_GUIDELINE_VERSION)
    parser.add_argument("--annotation-version", default=DEFAULT_ANNOTATION_VERSION)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--update-registry", action="store_true")
    return parser


def run_stage1_v2_materialize_assets(
    *,
    protocol_spec_path: str | Path,
    asset_registry_path: str | Path,
    atomic_source_csv: str | Path,
    m_verified_csv: str | Path,
    hard_b_csv: str | Path,
    stage1_v1_final_test_manifest: str | Path,
    output_root: str | Path,
    creation_git_sha: str,
    guideline_version: str,
    count_guideline_version: str,
    annotation_version: str,
    validate_only: bool = False,
    update_registry: bool = False,
) -> dict[str, Any]:
    protocol_spec = read_json(protocol_spec_path)
    asset_registry = read_json(asset_registry_path)
    protocol_version = str(protocol_spec.get("protocol_version") or "stage1-v2-protocol")
    if validate_only:
        return {
            "validate_only": True,
            "protocol_version": protocol_version,
            "output_root": str(output_root),
            "creation_git_sha": creation_git_sha,
        }

    output_root_path = Path(output_root)
    atomic_root = output_root_path / "atomic_source_pool"
    synthetic_root = output_root_path / "synthetic"
    real_count_root = output_root_path / "real_count"
    real_alignment_root = output_root_path / "real_alignment"
    background_root = output_root_path / "background"
    qualification_root = output_root_path / "qualification"
    readiness_root = output_root_path / "readiness"

    atomic_audit = audit_atomic_source_pool(
        source_csv=atomic_source_csv,
        output_root=atomic_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
    )
    synthetic = materialize_family_safe_synthetic_assets(
        accepted_atomic_source_path=atomic_audit["accepted_path"],
        output_root=synthetic_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
    )
    real_count = build_real_count_candidate_assets(
        accepted_atomic_source_path=atomic_audit["accepted_path"],
        m_verified_csv=m_verified_csv,
        hard_b_csv=hard_b_csv,
        stage1_v1_final_test_manifest=stage1_v1_final_test_manifest,
        output_root=real_count_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
        guideline_version=count_guideline_version,
        annotation_version=annotation_version,
    )
    real_alignment = build_real_adjudicated_assets(
        real_count_candidate_pool_path=real_count["pool_path"],
        output_root=real_alignment_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
        guideline_version=guideline_version,
        annotation_version=annotation_version,
    )
    background = build_background_annotation_assets(
        real_adjudicated_candidate_pool_path=real_alignment["candidate_pool_path"],
        output_root=background_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
        guideline_version=guideline_version,
    )
    qualification = build_qualification_materials(
        synthetic_control_test_path=synthetic["split_paths"]["synthetic_control_test"],
        output_root=qualification_root,
        creation_git_sha=creation_git_sha,
        protocol_version=protocol_version,
    )
    readiness_registry = asset_registry
    if update_registry:
        _update_stage1_v2_asset_registry(
            registry_path=asset_registry_path,
            creation_git_sha=creation_git_sha,
            protocol_version=protocol_version,
            atomic_audit=atomic_audit,
            synthetic=synthetic,
            real_count=real_count,
            real_alignment=real_alignment,
            background=background,
            readiness_path=readiness_root / "stage1_v2_annotation_readiness.json",
        )
        readiness_registry = read_json(asset_registry_path)
    readiness = build_annotation_readiness_report(
        protocol_spec=protocol_spec,
        asset_registry=readiness_registry,
        real_count_queue_path=real_count["pilot_queue_path"],
        real_adjudicated_pilot_path=real_alignment["pilot_candidates_path"],
        background_queue_path=background["queue_path"],
    )
    readiness_json = readiness_root / "stage1_v2_annotation_readiness.json"
    write_json(readiness_json, readiness)

    return {
        "protocol_version": protocol_version,
        "creation_git_sha": creation_git_sha,
        "atomic_audit": atomic_audit,
        "synthetic": synthetic,
        "real_count": real_count,
        "real_alignment": real_alignment,
        "background": background,
        "qualification": qualification,
        "annotation_readiness_path": str(readiness_json),
    }


def _update_stage1_v2_asset_registry(
    *,
    registry_path: str | Path,
    creation_git_sha: str,
    protocol_version: str,
    atomic_audit: dict[str, Any],
    synthetic: dict[str, Any],
    real_count: dict[str, Any],
    real_alignment: dict[str, Any],
    background: dict[str, Any],
    readiness_path: str | Path,
) -> None:
    registry = read_json(registry_path)
    assets = dict(registry.get("assets") or {})
    registry_updated_at = utc_now_iso()
    synthetic_status = "candidate_materialized"
    if (not bool(synthetic.get("leakage_clean"))) or int(synthetic.get("fatal_construction_error_count") or 0) > 0:
        synthetic_status = "invalid"
    updates = {
        "stage1_v2_synthetic_train": (synthetic_status, synthetic["split_paths"].get("train")),
        "stage1_v2_synthetic_dev": (synthetic_status, synthetic["split_paths"].get("dev")),
        "stage1_v2_synthetic_control_test": (synthetic_status, synthetic["split_paths"].get("synthetic_control_test")),
        "stage1_v2_synthetic_family_map": (synthetic_status, synthetic["family_map_path"]),
        "stage1_v2_synthetic_leakage_report": (synthetic_status, synthetic["leakage_path"]),
        "stage1_v2_real_count_candidate_pool": ("candidate_materialized", real_count["pool_path"]),
        "stage1_v2_real_count_queue": ("annotation_pending", real_count["pilot_queue_path"]),
        "stage1_v2_real_alignment_candidate_pool": ("candidate_materialized", real_alignment["candidate_pool_path"]),
        "stage1_v2_real_adjudicated_queue": ("annotation_pending", real_alignment["pilot_candidates_path"]),
        "stage1_v2_background_annotation_pilot": ("annotation_pending", background["queue_path"]),
        "stage1_v2_atomic_source_quality_report": ("candidate_materialized", atomic_audit["report_path"]),
    }
    for asset_name, (status, path_value) in updates.items():
        payload = dict(assets.get(asset_name) or {})
        if not payload:
            continue
        payload["status"] = status
        payload["path"] = str(path_value) if path_value else None
        if path_value and Path(path_value).exists():
            payload["sha256"] = compute_file_sha256(path_value)
            payload["record_count"] = _estimate_record_count(path_value)
        payload["protocol_version"] = protocol_version
        payload["created_by"] = creation_git_sha
        payload["created_at"] = registry_updated_at
        assets[asset_name] = payload
    blind_review_payload = dict(assets.get("stage1_v2_blind_review_asset") or {})
    if blind_review_payload:
        blind_review_payload["status"] = "pending_generation"
        blind_review_payload["path"] = None
        blind_review_payload["sha256"] = None
        blind_review_payload["record_count"] = None
        blind_review_payload["protocol_version"] = protocol_version
        blind_review_payload["created_by"] = creation_git_sha
        blind_review_payload["created_at"] = None
        assets["stage1_v2_blind_review_asset"] = blind_review_payload
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
        payload = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("rows", "samples"):
                if isinstance(payload.get(key), list):
                    return len(payload[key])
            if payload.get("row_count") is not None:
                return int(payload["row_count"])
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_materialize_assets(
        protocol_spec_path=args.protocol_spec,
        asset_registry_path=args.asset_registry,
        atomic_source_csv=args.atomic_source_csv,
        m_verified_csv=args.m_verified_csv,
        hard_b_csv=args.hard_b_csv,
        stage1_v1_final_test_manifest=args.stage1_v1_final_test,
        output_root=args.output_root,
        creation_git_sha=args.creation_git_sha,
        guideline_version=args.guideline_version,
        count_guideline_version=args.count_guideline_version,
        annotation_version=args.annotation_version,
        validate_only=bool(args.validate_only),
        update_registry=bool(args.update_registry),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
