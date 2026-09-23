from __future__ import annotations

from pathlib import Path
from typing import Any

from code.mica.data.asset_registry import validate_asset_registry
from code.mica.eval.baseline_registry import list_baselines
from code.mica.stage1_v2.protocol import validate_stage1_v2_protocol_spec
from code.mica.stage1_v2.statistics import build_seed_matrix


def build_stage1_v2_readiness(
    *,
    protocol_spec: dict[str, Any],
    asset_registry: dict[str, Any],
    synthetic_leakage_report: dict[str, Any] | None = None,
    real_count_report: dict[str, Any] | None = None,
    real_adjudicated_report: dict[str, Any] | None = None,
    null_background_report: dict[str, Any] | None = None,
    baseline_matrix_report: dict[str, Any] | None = None,
    anti_shortcut_report: dict[str, Any] | None = None,
    annotation_campaign_report: dict[str, Any] | None = None,
    official_test_unexposed: bool = False,
) -> dict[str, Any]:
    protocol_validation = validate_stage1_v2_protocol_spec(protocol_spec)
    registry_validation = validate_asset_registry(asset_registry)
    seed_matrix = build_seed_matrix(protocol_spec)
    synthetic_leakage = synthetic_leakage_report or {"leakage_clean": False}
    real_count = real_count_report or {}
    real_adjudicated = real_adjudicated_report or {}
    null_background = null_background_report or {"null_slot_enabled": False, "assets_ready": False}
    baseline_matrix = baseline_matrix_report or build_stage1_v2_baseline_matrix(protocol_spec)
    anti_shortcut = anti_shortcut_report or build_stage1_v2_anti_shortcut_readiness(protocol_spec)
    annotation_campaign = annotation_campaign_report or {}
    legacy_isolation = _check_legacy_stage1_v1_isolation(asset_registry)
    required_readiness = registry_validation.get("readiness_by_requirement", {})
    synthetic_ready = _requirement_ready(required_readiness, "stage1_v2_synthetic_split")
    real_count_asset_ready = _requirement_ready(required_readiness, "stage1_v2_real_count")
    real_adjudicated_ready = _requirement_ready(required_readiness, "stage1_v2_real_adjudicated")
    baseline_matrix_ready = bool(baseline_matrix.get("matrix_defined")) and bool(baseline_matrix.get("runner_interface_defined"))
    anti_shortcut_ready = bool(anti_shortcut.get("probe_plan_defined")) and bool(anti_shortcut.get("masking_support_defined"))
    agreement_gates_passed = bool(real_adjudicated.get("agreement_gates")) and all(
        bool(payload.get("passed")) for payload in dict(real_adjudicated.get("agreement_gates") or {}).values()
    )
    benchmark_strata_ready = bool(dict(real_adjudicated.get("benchmark_strata") or {}).get("formal_ready"))
    repository_concentration_passed = bool(dict(real_adjudicated.get("benchmark_strata") or {}).get("repository_concentration_passed"))
    double_annotation_complete = bool(real_adjudicated.get("double_annotation_complete"))
    adjudication_complete = bool(real_adjudicated.get("adjudication_complete"))
    kmax_frozen = bool(real_count.get("selected_kmax") is not None and real_count.get("status") == "candidate_ready_for_freeze")
    synthetic_scale_sufficient = bool(annotation_campaign.get("synthetic_scale_sufficient"))
    required_atomic_sources_human_verified = bool(annotation_campaign.get("required_atomic_sources_human_verified"))
    annotation_staffing_complete = bool(annotation_campaign.get("annotation_staffing_complete"))
    annotators_qualified = bool(annotation_campaign.get("annotators_qualified"))
    calibration_round_complete = bool(annotation_campaign.get("calibration_round_complete"))
    calibration_agreement_passed = bool(annotation_campaign.get("calibration_agreement_passed"))
    pilot_guideline_frozen = bool(annotation_campaign.get("pilot_guideline_frozen"))
    pilot_double_annotation_complete = bool(annotation_campaign.get("pilot_double_annotation_complete"))
    pilot_adjudication_complete = bool(annotation_campaign.get("pilot_adjudication_complete"))
    pilot_quality_gates_passed = bool(annotation_campaign.get("pilot_quality_gates_passed"))
    formal_ready = (
        protocol_validation["valid"]
        and registry_validation["schema_valid"]
        and synthetic_ready
        and bool(synthetic_leakage.get("leakage_clean"))
        and synthetic_scale_sufficient
        and required_atomic_sources_human_verified
        and real_count_asset_ready
        and kmax_frozen
        and real_adjudicated_ready
        and double_annotation_complete
        and adjudication_complete
        and agreement_gates_passed
        and benchmark_strata_ready
        and repository_concentration_passed
        and bool(null_background.get("null_slot_enabled"))
        and bool(null_background.get("assets_ready"))
        and baseline_matrix_ready
        and bool(baseline_matrix.get("all_required_baselines_declared"))
        and anti_shortcut_ready
        and bool(seed_matrix.get("seed_matrix_frozen"))
        and annotation_staffing_complete
        and annotators_qualified
        and calibration_round_complete
        and calibration_agreement_passed
        and pilot_guideline_frozen
        and pilot_double_annotation_complete
        and pilot_adjudication_complete
        and pilot_quality_gates_passed
        and official_test_unexposed
        and legacy_isolation["passed"]
    )
    return {
        "schema_version": "mica-stage1-v2-readiness-v1",
        "protocol_frozen": protocol_validation["valid"],
        "protocol_validation": protocol_validation,
        "registry_schema_valid": registry_validation["schema_valid"],
        "asset_registry_validation": registry_validation,
        "synthetic_family_split_ready": synthetic_ready,
        "leakage_clean": bool(synthetic_leakage.get("leakage_clean")),
        "real_count_asset_ready": real_count_asset_ready,
        "Kmax_frozen": kmax_frozen,
        "real_alignment_test_ready": real_adjudicated_ready,
        "double_annotation_complete": double_annotation_complete,
        "adjudication_complete": adjudication_complete,
        "agreement_gates_passed": agreement_gates_passed,
        "benchmark_strata_ready": benchmark_strata_ready,
        "repository_concentration_passed": repository_concentration_passed,
        "null_background_assets_ready": bool(null_background.get("null_slot_enabled")) and bool(null_background.get("assets_ready")),
        "baseline_matrix_ready": baseline_matrix_ready,
        "anti_shortcut_ready": anti_shortcut_ready,
        "seed_matrix_frozen": bool(seed_matrix.get("seed_matrix_frozen")),
        "statistical_protocol_frozen": True,
        "synthetic_scale_sufficient": synthetic_scale_sufficient,
        "required_atomic_sources_human_verified": required_atomic_sources_human_verified,
        "annotation_staffing_complete": annotation_staffing_complete,
        "annotators_qualified": annotators_qualified,
        "calibration_round_complete": calibration_round_complete,
        "calibration_agreement_passed": calibration_agreement_passed,
        "pilot_guideline_frozen": pilot_guideline_frozen,
        "pilot_double_annotation_complete": pilot_double_annotation_complete,
        "pilot_adjudication_complete": pilot_adjudication_complete,
        "pilot_quality_gates_passed": pilot_quality_gates_passed,
        "official_test_unexposed": official_test_unexposed,
        "legacy_stage1_v1_isolation_passed": legacy_isolation["passed"],
        "formal_ready": formal_ready,
        "stage2_entry_allowed": formal_ready,
        "legacy_isolation": legacy_isolation,
        "baseline_matrix_report": baseline_matrix,
        "anti_shortcut_report": anti_shortcut,
        "seed_matrix": seed_matrix,
        "null_background_report": null_background,
        "real_count_report": real_count,
        "real_adjudicated_report": real_adjudicated,
        "synthetic_leakage_report": synthetic_leakage,
        "annotation_campaign_report": annotation_campaign,
    }


def build_stage1_v2_baseline_matrix(protocol_spec: dict[str, Any]) -> dict[str, Any]:
    required = list(dict(protocol_spec.get("baseline_matrix") or {}).get("required_baselines") or [])
    existing = {row["name"]: row for row in list_baselines()}
    mappings = {
        "all_one": {"implemented": "all_one" in existing, "status": "local_runner_available", "mapped_to": "all_one"},
        "file_hunk_heuristic": {"implemented": False, "status": "execution_interface_pending", "mapped_to": None},
        "tfidf_clustering_predicted_k": {"implemented": False, "status": "execution_interface_pending", "mapped_to": None},
        "tfidf_clustering_oracle_k": {"implemented": bool(existing.get("oracle_k_clustering")), "status": "partial_oracle_k_only", "mapped_to": "oracle_k_clustering"},
        "frozen_code_embedding_clustering_predicted_k": {"implemented": False, "status": "executable_pending_assets", "mapped_to": None},
        "frozen_code_embedding_clustering_oracle_k": {"implemented": False, "status": "executable_pending_assets", "mapped_to": None},
        "supervised_pairwise_baseline": {"implemented": False, "status": "execution_interface_pending", "mapped_to": None},
        "mica_oracle_k": {"implemented": False, "status": "execution_interface_pending", "mapped_to": None},
    }
    declared = all(name in mappings for name in required)
    return {
        "required_baselines": required,
        "matrix_defined": True,
        "runner_interface_defined": True,
        "all_required_baselines_declared": declared,
        "baseline_status": mappings,
    }


def build_stage1_v2_anti_shortcut_readiness(protocol_spec: dict[str, Any]) -> dict[str, Any]:
    required_probes = list(dict(protocol_spec.get("anti_shortcut") or {}).get("required_probes") or [])
    supported_probes = {
        "metadata_only_count_probe": True,
        "real_vs_synthetic_probe": True,
        "path_anonymization": True,
        "identifier_anonymization": True,
        "unit_order_shuffle": True,
        "file_order_shuffle": True,
        "file_role_removal": True,
        "repository_disjoint_evaluation": True,
    }
    return {
        "probe_plan_defined": True,
        "masking_support_defined": True,
        "required_probes": required_probes,
        "supported_probes": supported_probes,
        "all_required_probes_declared": all(supported_probes.get(name, False) for name in required_probes),
    }


def build_null_background_preflight(
    protocol_spec: dict[str, Any],
    real_adjudicated_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    null_slot_enabled = bool(dict(protocol_spec.get("model_requirements") or {}).get("use_null_slot"))
    background_units = 0
    background_types: dict[str, int] = {}
    background_heavy_dev_exists = False
    for row in real_adjudicated_rows:
        adjudicated = row.get("adjudicated_annotation")
        if not isinstance(adjudicated, dict):
            continue
        unit_labels = dict(adjudicated.get("unit_labels") or {})
        foreground_ids = set()
        background_ids = set()
        for unit_id, payload in unit_labels.items():
            info = dict(payload or {})
            label = str(info.get("label") or "")
            if label == "foreground":
                foreground_ids.add(str(unit_id))
            if label == "background":
                background_ids.add(str(unit_id))
                background_units += 1
                background_type = str(info.get("background_type") or "unspecified")
                background_types[background_type] = background_types.get(background_type, 0) + 1
        if background_ids and str(row.get("split_candidate") or "") == "dev" and "background_heavy" in list(row.get("candidate_tags") or []):
            background_heavy_dev_exists = True
        if foreground_ids & background_ids:
            return {
                "null_slot_enabled": null_slot_enabled,
                "assets_ready": False,
                "error": "foreground_background_overlap_detected",
            }
    return {
        "null_slot_enabled": null_slot_enabled,
        "assets_ready": null_slot_enabled and background_units > 0 and background_heavy_dev_exists,
        "background_unit_count": background_units,
        "background_type_distribution": dict(sorted(background_types.items())),
        "background_heavy_dev_exists": background_heavy_dev_exists,
    }


def _requirement_ready(readiness: dict[str, Any], requirement: str) -> bool:
    payload = dict(readiness.get(requirement) or {})
    return bool(payload.get("ready"))


def load_optional_json(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    target = Path(path)
    if not target.exists():
        return None
    import json

    return json.loads(target.read_text(encoding="utf-8"))


def _check_legacy_stage1_v1_isolation(asset_registry: dict[str, Any]) -> dict[str, Any]:
    assets = dict(asset_registry.get("assets") or {})
    legacy_blocklist = dict(asset_registry.get("legacy_blocklist") or {})
    blocked_artifact_ids = {str(item) for item in list(legacy_blocklist.get("stage1_v1_checkpoint_artifact_ids") or []) if str(item)}
    blocked_paths = {str(item) for item in list(legacy_blocklist.get("stage1_v1_result_records") or []) if str(item)}
    violations: list[dict[str, Any]] = []
    for asset_name, payload in assets.items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "")
        if status not in {"candidate", "candidate_validated", "frozen"}:
            continue
        artifact_id = str(payload.get("artifact_id") or "")
        path = str(payload.get("path") or "")
        if artifact_id and artifact_id in blocked_artifact_ids:
            violations.append({"asset": str(asset_name), "reason": "legacy_stage1_v1_artifact_id_reused"})
        if path and path in blocked_paths:
            violations.append({"asset": str(asset_name), "reason": "legacy_stage1_v1_result_record_reused"})
    return {"passed": not violations, "violations": violations}
