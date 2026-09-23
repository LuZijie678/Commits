from __future__ import annotations

from typing import Any


_RUNNER_POLICIES: dict[str, dict[str, Any]] = {
    "run_stage0_protocol_freeze": {
        "stage": "stage0",
        "purpose": "protocol freeze readiness",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": False,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_official_validation": {
        "stage": "stage1",
        "purpose": "official synthetic attribution validation",
        "can_train": False,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_formal_training": {
        "stage": "stage1",
        "purpose": "formal Stage 1 attribution training over frozen synthetic and high-confidence single-intent assets",
        "can_train": True,
        "requires_advisor_approval": False,
        "default_mode": "validate_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": True,
        "attribution_update_scope": "stage1_training_only",
    },
    "run_stage1_threshold_selection": {
        "stage": "stage1",
        "purpose": "dev-only threshold candidate selection for Stage 1 metric gates",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "validate_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_candidate_validation": {
        "stage": "stage1",
        "purpose": "real full-checkpoint non-formal candidate validation over the frozen Stage 1 dev manifest",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "validate_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_generate_approval_packets": {
        "stage": "stage1",
        "purpose": "generate pending human-approval packets for Stage 1 threshold and Kmax decisions",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "execute",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_official_preflight": {
        "stage": "stage1",
        "purpose": "read-only gate check before any future official Stage 1 validation execution",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "validate_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_kmax_exact_count_audit": {
        "stage": "stage0",
        "purpose": "exact-count Kmax readiness audit and annotation queue export",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "validate_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage1_baselines": {
        "stage": "stage1",
        "purpose": "baseline execution",
        "can_train": True,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_stage2_calibration": {
        "stage": "stage2",
        "purpose": "real-domain count and release calibration over frozen assignment",
        "can_train": True,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
        "attribution_update_scope": "none_core_assignment_frozen",
    },
    "run_stage3_alignment_calibration": {
        "stage": "stage3",
        "purpose": "real alignment temperature calibration with separately gated Stage3-Plus adapter",
        "can_train": True,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
        "attribution_update_scope": "core_assignment_frozen_stage3_plus_adapter_separately_gated",
    },
    "run_stage4_renderer_training": {
        "stage": "stage4",
        "purpose": "renderer ablation training",
        "can_train": True,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": True,
        "can_update_attribution": False,
    },
    "run_real_domain_detection_eval": {
        "stage": "eval",
        "purpose": "real-domain detection evaluation",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_alignment_eval": {
        "stage": "eval",
        "purpose": "alignment evaluation",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_message_utility_eval": {
        "stage": "eval",
        "purpose": "message utility evaluation",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": False,
        "can_use_renderer": True,
        "can_update_attribution": False,
    },
    "run_message_baseline_generation": {
        "stage": "eval",
        "purpose": "message utility external reference baseline generation",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": True,
        "can_use_renderer": True,
        "can_update_attribution": False,
    },
    "run_plan_renderer_smoke": {
        "stage": "downstream_smoke",
        "purpose": "offline plan to deterministic renderer smoke",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "smoke_only",
        "can_write_outputs": True,
        "can_use_final_test": False,
        "can_call_api": False,
        "can_use_renderer": True,
        "can_update_attribution": False,
    },
    "run_anti_shortcut_audit_dryrun": {
        "stage": "eval",
        "purpose": "anti-shortcut masked rerun planning",
        "can_train": False,
        "requires_advisor_approval": True,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
    "run_ood_stress_eval": {
        "stage": "eval",
        "purpose": "OOD slice aggregation",
        "can_train": False,
        "requires_advisor_approval": False,
        "default_mode": "dry_run",
        "can_write_outputs": True,
        "can_use_final_test": True,
        "can_call_api": False,
        "can_use_renderer": False,
        "can_update_attribution": False,
    },
}


def list_mica_runners() -> list[dict[str, Any]]:
    return [{"name": name, **policy} for name, policy in _RUNNER_POLICIES.items()]


def get_runner_policy(name: str) -> dict[str, Any]:
    if name not in _RUNNER_POLICIES:
        raise KeyError(f"Unknown runner: {name}")
    return {"name": name, **_RUNNER_POLICIES[name]}


def validate_runner_policy(name: str, policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    required = {
        "stage",
        "purpose",
        "can_train",
        "requires_advisor_approval",
        "default_mode",
        "can_write_outputs",
        "can_use_final_test",
        "can_call_api",
        "can_use_renderer",
        "can_update_attribution",
    }
    missing = sorted(required - set(policy))
    errors.extend(f"missing_{field}" for field in missing)
    if policy.get("can_train") and policy.get("requires_advisor_approval") is not True and name != "run_stage1_formal_training":
        errors.append("train_runner_must_require_advisor_approval")
    if name == "run_stage4_renderer_training" and policy.get("can_update_attribution") is not False:
        errors.append("stage4_renderer_must_not_update_attribution")
    if policy.get("can_call_api") not in {True, False}:
        errors.append("can_call_api_must_be_boolean")
    return {"valid": len(errors) == 0, "errors": errors}


def build_runner_registry_markdown() -> str:
    lines = [
        "# MICA Runner Registry",
        "",
        "| runner | stage | default_mode | can_train | requires_advisor_approval | can_use_final_test | can_call_api | can_update_attribution |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in list_mica_runners():
        lines.append(
            f"| {row['name']} | {row['stage']} | {row['default_mode']} | {row['can_train']} | {row['requires_advisor_approval']} | {row['can_use_final_test']} | {row['can_call_api']} | {row['can_update_attribution']} |"
        )
    return "\n".join(lines) + "\n"
