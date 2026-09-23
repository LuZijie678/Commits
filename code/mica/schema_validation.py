from __future__ import annotations

from typing import Any


FORBIDDEN_SNAPSHOT_FIELDS = {
    "commit_message",
    "gold_count",
    "gold_hunk_to_intent",
    "gold_intent_id",
    "gold_unit_to_intent",
    "issue_text",
    "pr_text",
    "pr_title",
    "synthetic_metadata",
}


def validate_attribution_prediction_contract(
    row: dict[str, Any],
    *,
    mode: str = "minimal",
    external_edit_units_available: bool = False,
) -> dict[str, Any]:
    if mode not in {"minimal", "review_ready"}:
        raise ValueError(f"unsupported prediction contract mode {mode!r}")
    errors: list[str] = []
    warnings: list[str] = []
    if not row.get("sample_id"):
        errors.append("missing_sample_id")
    if row.get("predicted_count") is None:
        errors.append("missing_predicted_count")
    if not row.get("count_probs"):
        warnings.append("missing_count_probs")
    if not row.get("active_slots"):
        warnings.append("missing_active_slots")
    if not row.get("unit_to_slot"):
        errors.append("missing_unit_to_slot")
    has_assignment_scores = bool(row.get("unit_assignment_scores") or row.get("assignment_scores"))
    if row.get("unit_to_slot") and not has_assignment_scores:
        warnings.append("limited_prediction_format")
    if mode == "review_ready":
        if not row.get("count_probs"):
            errors.append("missing_count_probs")
        if not has_assignment_scores:
            errors.append("missing_assignment_scores")
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
        release_decision = (
            row.get("release_decision")
            or metadata.get("release_decision")
            or metadata.get("decision")
        )
        if not release_decision:
            errors.append("missing_release_decision")
        has_edit_units = bool(
            row.get("edit_units")
            or row.get("unit_records")
            or external_edit_units_available
        )
        if not has_edit_units:
            errors.append("missing_edit_units")
        background_units = row.get("background_units")
        if not background_units and isinstance(metadata, dict):
            background_units = metadata.get("background_units")
        background_records = row.get("background_unit_records")
        if background_records is None and isinstance(metadata, dict):
            background_records = metadata.get("background_unit_records")
        if background_units and not background_records and "slot_null" not in {
            str(value) for value in dict(row.get("unit_to_slot", {})).values()
        }:
            warnings.append("missing_background_unit_records")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_backend_snapshot_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    train_batch = row.get("train_batch")
    train_outputs = row.get("train_outputs")
    if not isinstance(train_batch, dict):
        errors.append("missing_train_batch")
        train_batch = {}
    if not isinstance(train_outputs, dict):
        errors.append("missing_train_outputs")
        train_outputs = {}

    sample_ids = train_batch.get("sample_ids")
    if not isinstance(sample_ids, list) or not sample_ids:
        errors.append("missing_sample_ids")
    elif len(sample_ids) != 1:
        errors.append("multi_sample_snapshot_not_exportable")

    if not train_batch.get("source_kind"):
        errors.append("missing_source_kind")
    edit_units = train_batch.get("edit_units")
    if not isinstance(edit_units, list) or not edit_units:
        errors.append("missing_edit_units")
    if _is_missing_payload(train_outputs.get("count_probs")):
        errors.append("missing_count_probs")
    if _is_missing_payload(train_outputs.get("slot_exist_probs")):
        errors.append("missing_slot_exist_probs")
    if _is_missing_payload(train_outputs.get("assignments")):
        errors.append("missing_unit_to_slot")
    if _is_missing_payload(train_outputs.get("assignment_scores")):
        errors.append("missing_assignment_scores")

    batch_metadata = train_batch.get("metadata", {}) if isinstance(train_batch.get("metadata"), dict) else {}
    diagnostics = train_outputs.get("diagnostics", {}) if isinstance(train_outputs.get("diagnostics"), dict) else {}
    release_decision = diagnostics.get("release_decision") or batch_metadata.get("release_decision")
    if not release_decision:
        errors.append("missing_release_decision")

    forbidden_fields = _find_forbidden_snapshot_fields(
        batch_metadata=batch_metadata,
        diagnostics=diagnostics,
        edit_units=edit_units if isinstance(edit_units, list) else [],
    )
    errors.extend(f"forbidden_snapshot_field:{field_name}" for field_name in forbidden_fields)
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_structured_intent_plan_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not row.get("sample_id"):
        errors.append("missing_sample_id")
    if row.get("intent_count") is None:
        errors.append("missing_intent_count")
    intents = row.get("intents")
    if not isinstance(intents, list):
        errors.append("missing_intents")
        intents = []
    if row.get("degraded"):
        warnings.append("degraded_plan")
    for intent in intents:
        if not intent.get("evidence_units"):
            warnings.append("missing_evidence_units")
            break
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_train_batch_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not row.get("sample_ids"):
        errors.append("missing_sample_ids")
    source_kind = row.get("source_kind")
    if not source_kind:
        errors.append("missing_source_kind")
    if not isinstance(row.get("edit_units"), list):
        errors.append("missing_edit_units")
    if source_kind == "strict_replay":
        if row.get("gold_count") is None:
            errors.append("strict_replay_missing_gold_count")
        if not row.get("gold_unit_to_intent") and not row.get("gold_hunk_to_intent"):
            errors.append("strict_replay_missing_gold_alignment")
    if source_kind == "m_weak":
        if row.get("weak_label") != "censored_k_ge_2":
            errors.append("m_weak_must_be_censored_k_ge_2")
        if row.get("gold_count") == 2:
            warnings.append("m_weak_exact_k_should_not_be_used")
    if source_kind == "real_alignment":
        if row.get("gold_count") is None:
            errors.append("real_alignment_missing_gold_count")
        if not row.get("gold_unit_to_intent") and not row.get("gold_hunk_to_intent"):
            errors.append("real_alignment_missing_gold_alignment")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_eval_prediction_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not row.get("sample_id"):
        errors.append("missing_sample_id")
    if not any(key in row for key in ("pred_unit_to_slot", "label", "message")):
        errors.append("missing_eval_payload")
    if "proxy_not_human_eval" in row and row.get("proxy_not_human_eval") is not True:
        warnings.append("proxy_flag_false")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_paper_table_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    metrics = row.get("metrics")
    if not row.get("row_name"):
        errors.append("missing_row_name")
    if not row.get("comparison_group"):
        errors.append("missing_comparison_group")
    if not isinstance(metrics, dict):
        errors.append("missing_metrics")
        metrics = {}
    for metric_name, cell in metrics.items():
        if "value" not in cell:
            errors.append(f"metric_{metric_name}_missing_value")
        if "higher_is_better" not in cell:
            errors.append(f"metric_{metric_name}_missing_higher_is_better")
        if "is_proxy_metric" not in cell:
            errors.append(f"metric_{metric_name}_missing_is_proxy_metric")
        if "is_primary_metric" not in cell:
            errors.append(f"metric_{metric_name}_missing_is_primary_metric")
        if "requires_human_eval" not in cell:
            errors.append(f"metric_{metric_name}_missing_requires_human_eval")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": []}


def validate_renderer_input_contract(row: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not row.get("sample_id"):
        errors.append("missing_sample_id")
    if "message" not in row:
        errors.append("missing_message")
    plan = row.get("structured_intent_plan")
    if not isinstance(plan, dict):
        errors.append("missing_structured_intent_plan")
    elif not plan.get("sample_id"):
        warnings.append("plan_missing_sample_id")
    if row.get("proxy_not_human_eval") is not True:
        errors.append("missing_proxy_not_human_eval")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_cross_stage_contracts(rows: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    if "stage1_prediction" in rows:
        checks["stage1_prediction"] = validate_attribution_prediction_contract(rows["stage1_prediction"])
    if "backend_snapshot" in rows:
        checks["backend_snapshot"] = validate_backend_snapshot_contract(rows["backend_snapshot"])
    if "structured_intent_plan" in rows:
        checks["structured_intent_plan"] = validate_structured_intent_plan_contract(rows["structured_intent_plan"])
    if "train_batch" in rows:
        checks["train_batch"] = validate_train_batch_contract(rows["train_batch"])
    if "eval_prediction" in rows:
        checks["eval_prediction"] = validate_eval_prediction_contract(rows["eval_prediction"])
    if "paper_table_row" in rows:
        checks["paper_table_row"] = validate_paper_table_contract(rows["paper_table_row"])
    if "renderer_input" in rows:
        checks["renderer_input"] = validate_renderer_input_contract(rows["renderer_input"])
    valid = all(item["valid"] for item in checks.values()) if checks else True
    return {"valid": valid, "checks": checks}


def _find_forbidden_snapshot_fields(
    *,
    batch_metadata: dict[str, Any],
    diagnostics: dict[str, Any],
    edit_units: list[Any],
) -> list[str]:
    found: set[str] = set()
    for key in batch_metadata:
        if key in FORBIDDEN_SNAPSHOT_FIELDS:
            found.add(str(key))
    for key in diagnostics:
        if key in FORBIDDEN_SNAPSHOT_FIELDS:
            found.add(str(key))
    for row in edit_units:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key in FORBIDDEN_SNAPSHOT_FIELDS:
                found.add(str(key))
        metadata = row.get("metadata")
        if isinstance(metadata, dict):
            for key in metadata:
                if key in FORBIDDEN_SNAPSHOT_FIELDS:
                    found.add(str(key))
    return sorted(found)


def _is_missing_payload(value: Any) -> bool:
    if value is None:
        return True
    if hasattr(value, "numel"):
        try:
            return int(value.numel()) == 0
        except TypeError:
            return False
    if isinstance(value, (dict, list, tuple, str)):
        return len(value) == 0
    return False
