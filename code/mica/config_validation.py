from __future__ import annotations

from typing import Any


FORBIDDEN_ATTRIBUTION_LOSS_KEYS = {
    "lambda_multi": "L_multi is forbidden in attribution configs",
    "lambda_gen": "L_gen must not enter attribution configs",
    "lambda_faith": "L_faith must not enter attribution configs",
}


def validate_stage1_protocol_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []
    if spec.get("advisor_stage1_validation_approved") not in {True, False}:
        errors.append("advisor_stage1_validation_approved must exist")
    if spec.get("stage2_allowed") is not False:
        errors.append("stage2_allowed must remain false in stage1 protocol freeze spec")
    if "null_slot" not in spec:
        warnings.append("missing null_slot config")
    if "dual_cardinality" not in spec:
        warnings.append("missing dual_cardinality config")
    if "assignment_schedule" not in spec:
        warnings.append("missing assignment_schedule config")
    if "evidence_graph" not in spec:
        warnings.append("missing evidence_graph config")
    errors.extend(_forbidden_loss_errors(spec))
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_stage2_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []
    if "advisor_stage2_approved" not in spec:
        errors.append("missing advisor_stage2_approved")
    if spec.get("m_final_test_forbidden") is not True:
        errors.append("m_final_test_forbidden must be true")
    if spec.get("hard_b_test_forbidden") is not True:
        errors.append("hard_b_test_forbidden must be true")
    if spec.get("strict_replay_required") is not True:
        errors.append("strict_replay_required must be true")
    if spec.get("m_weak_label_semantics") != "censored_k_ge_2":
        errors.append("m_weak_label_semantics must be censored_k_ge_2")
    if "null_slot" not in spec:
        warnings.append("missing null_slot config")
    if "dual_cardinality" not in spec:
        warnings.append("missing dual_cardinality config")
    if "assignment_schedule" not in spec:
        warnings.append("missing assignment_schedule config")
    if "evidence_graph" not in spec:
        warnings.append("missing evidence_graph config")
    if spec.get("consistency", {}).get("enabled", False) not in {True, False}:
        errors.append("consistency.enabled must be boolean")
    errors.extend(_forbidden_loss_errors(spec))
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_stage3_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if "advisor_stage3_approved" not in spec:
        errors.append("missing advisor_stage3_approved")
    if spec.get("m_final_test_forbidden") is not True:
        errors.append("m_final_test_forbidden must be true")
    if spec.get("freeze_base_encoder") is not True:
        errors.append("freeze_base_encoder must be true")
    errors.extend(_forbidden_loss_errors(spec))
    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def validate_stage4_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if "advisor_stage4_approved" not in spec:
        errors.append("missing advisor_stage4_approved")
    if "advisor_stage4_trainable_renderer_approved" not in spec:
        errors.append("missing advisor_stage4_trainable_renderer_approved")
    if spec.get("attribution_frozen_required") is not True:
        errors.append("attribution_frozen=true / attribution_frozen_required must be true")
    if spec.get("stage4_scope") != "deterministic_evidence_locked_renderer":
        errors.append("stage4_scope must be deterministic_evidence_locked_renderer")
    if spec.get("trainable_renderer_main_result") is not False:
        errors.append("trainable_renderer_main_result must be false")
    if spec.get("renderer_updates_attribution") is not False:
        errors.append("renderer_updates_attribution must be false")
    if spec.get("renderer_reads_only_plan_and_assigned_evidence") is not True:
        errors.append("renderer_reads_only_plan_and_assigned_evidence must be true")
    if spec.get("raw_full_diff_forbidden_as_ungrounded_context") is not True:
        errors.append("raw_full_diff_forbidden_as_ungrounded_context must be true")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def validate_eval_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if not any(
        spec.get(flag) is True
        for flag in (
            "final_test_eval_only",
            "real_domain_split_test_forbidden_for_training",
            "real_domain_selective_test_forbidden_for_training",
            "final_test_forbidden_for_calibration",
        )
    ):
        errors.append("final-test must be marked eval-only")
    if spec.get("no_threshold_tuning_on_final_test") is not True:
        errors.append("no_threshold_tuning_on_final_test must be true")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def validate_threshold_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = []
    threshold_status = str(spec.get("threshold_status") or "")
    if "threshold_status" not in spec:
        errors.append("missing threshold_status")
    if not any(key.endswith(("_min", "_max")) for key in spec):
        errors.append("no threshold bounds found")
    if threshold_status and "candidate" not in threshold_status and "pending" not in threshold_status:
        if not spec.get("approved_threshold_version"):
            errors.append("frozen threshold spec requires approved_threshold_version")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def _forbidden_loss_errors(spec: dict[str, Any]) -> list[str]:
    loss_weights = dict(spec.get("loss_weights", {}))
    auxiliary_losses = dict(spec.get("auxiliary_losses", {}))
    merged = {**loss_weights, **auxiliary_losses}
    errors: list[str] = []
    for key, message in FORBIDDEN_ATTRIBUTION_LOSS_KEYS.items():
        if key in merged and float(merged.get(key, 0.0) or 0.0) != 0.0:
            errors.append(message)
    return errors
