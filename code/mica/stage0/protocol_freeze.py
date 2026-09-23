from __future__ import annotations

from typing import Any

from code.mica.data.asset_registry import validate_asset_registry
from code.mica.stage0.data_card import validate_data_card_text
from code.mica.stage0.eval_protocol import validate_eval_protocol_text
from code.mica.stage0.leakage_report import build_global_leakage_report, check_asset_boundary


def build_stage0_protocol_freeze_readiness(
    *,
    data_card_text: str,
    eval_protocol_text: str,
    asset_registry: dict[str, Any],
    metric_thresholds: dict[str, Any] | None = None,
    loaded_asset_rows: dict[str, list[dict[str, Any]]] | None = None,
    threshold_approval_decision: dict[str, Any] | None = None,
    kmax_decision: dict[str, Any] | None = None,
    checkpoint_validation: dict[str, Any] | None = None,
    split_exposure_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_card = validate_data_card_text(data_card_text)
    eval_protocol = validate_eval_protocol_text(eval_protocol_text)
    boundary = check_asset_boundary(asset_registry)
    registry_validation = validate_asset_registry(asset_registry)
    leakage = build_global_leakage_report(asset_registry, loaded_asset_rows or {})
    thresholds = metric_thresholds or {}
    threshold_decision = threshold_approval_decision or {}
    kmax_decision_payload = kmax_decision or {}
    checkpoint_status = dict(registry_validation.get("asset_status", {}).get("stage1_checkpoint_input", {}))
    final_test_status = dict(registry_validation.get("asset_status", {}).get("stage1_official_final_test", {}))
    checkpoint_payload_validation = checkpoint_validation or {"valid": False, "checkpoint_kind": None, "errors": ["checkpoint_validation_missing"]}
    split_exposure = split_exposure_audit or {}
    threshold_status = str(thresholds.get("threshold_status") or "missing_threshold_status")
    approved_threshold_version = str(threshold_decision.get("approved_threshold_version") or "")
    thresholds_frozen = (
        str(threshold_decision.get("status") or "") == "approved"
        and bool(approved_threshold_version)
        and approved_threshold_version == str(thresholds.get("approved_threshold_version") or "")
        and approved_threshold_version == threshold_status
    )
    kmax_protocol_frozen = (
        str(kmax_decision_payload.get("status") or "") == "approved"
        and kmax_decision_payload.get("selected_Kmax") is not None
        and str(kmax_decision_payload.get("amendment_type") or "") in {"pre_test_protocol_amendment", "predeclared"}
        and bool(kmax_decision_payload.get("approved_by"))
        and bool(kmax_decision_payload.get("approved_at"))
        and bool(kmax_decision_payload.get("final_test_used") is False)
    )
    protocol_schema_valid = data_card["valid"] and eval_protocol["valid"] and boundary["valid"]
    assets_materialized = registry_validation["assets_materialized"]
    assets_content_valid = registry_validation["assets_content_valid"]
    splits_leakage_clean = all(int(value or 0) == 0 for value in leakage.get("cross_asset_overlap", {}).values())
    checkpoint_full_model = bool(checkpoint_payload_validation.get("valid")) and str(checkpoint_payload_validation.get("checkpoint_kind") or "") == "full_model_state"
    checkpoint_loadable = bool(checkpoint_payload_validation.get("valid"))
    checkpoint_hash_verified = checkpoint_status.get("checksum_match") is True
    official_final_test_manifest_frozen = bool(final_test_status.get("formal_ready"))
    official_final_test_unexposed = (
        str(split_exposure.get("conclusion") or "") == "dev_only_unexposed_final_test"
        and bool(split_exposure.get("candidate_validation_split_must_not_equal_official_final_test_split"))
        and int(split_exposure.get("proposed_final_sample_overlap_count", 0) or 0) == 0
        and int(split_exposure.get("proposed_final_leakage_overlap_count", 0) or 0) == 0
    )
    ready = (
        protocol_schema_valid
        and registry_validation["schema_valid"]
        and assets_materialized
        and assets_content_valid
        and checkpoint_full_model
        and checkpoint_loadable
        and checkpoint_hash_verified
        and splits_leakage_clean
        and official_final_test_manifest_frozen
        and official_final_test_unexposed
        and kmax_protocol_frozen
        and thresholds_frozen
    )
    return {
        "stage": "stage0_protocol_freeze",
        "dry_run": True,
        "training_executed": False,
        "protocol_freeze_ready": protocol_schema_valid,
        "protocol_schema_valid": protocol_schema_valid,
        "registry_schema_valid": registry_validation["schema_valid"],
        "assets_materialized": assets_materialized,
        "assets_content_valid": assets_content_valid,
        "checkpoint_full_model": checkpoint_full_model,
        "checkpoint_loadable": checkpoint_loadable,
        "checkpoint_hash_verified": checkpoint_hash_verified,
        "splits_leakage_clean": splits_leakage_clean,
        "official_final_test_manifest_frozen": official_final_test_manifest_frozen,
        "official_final_test_unexposed": official_final_test_unexposed,
        "Kmax_protocol_frozen": kmax_protocol_frozen,
        "thresholds_frozen": thresholds_frozen,
        "thresholds_approved": thresholds_frozen,
        "formal_ready": ready,
        "threshold_status": threshold_status,
        "threshold_approval_status": threshold_decision.get("status"),
        "approved_threshold_version": approved_threshold_version or None,
        "kmax_decision_status": kmax_decision_payload.get("status"),
        "kmax_decision_version": kmax_decision_payload.get("decision_version"),
        "data_card": data_card,
        "eval_protocol": eval_protocol,
        "asset_registry_validation": registry_validation,
        "asset_boundary": boundary,
        "checkpoint_validation": checkpoint_payload_validation,
        "leakage_report": leakage,
        "split_exposure_audit": split_exposure,
    }
