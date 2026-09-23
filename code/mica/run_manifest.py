from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.io_utils import safe_relpath_for_report


NON_EXECUTION_MODES = {"dry_run", "validate_only", "audit_only", "smoke_only"}


def build_run_manifest(
    stage: str,
    mode: str,
    output_root: str | None,
    flags: dict[str, Any],
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = {
        "run_id": f"{stage}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "mode": mode,
        "output_root": safe_relpath_for_report(output_root) if output_root else None,
        "training_enabled": False,
        "official_validation_executed": False,
        "stage2_training_enabled": False,
        "stage3_training_enabled": False,
        "stage4_training_enabled": False,
        "generation_training_enabled": False,
        "retrieval_enabled": False,
        "verifier_enabled": False,
        "api_calls_enabled": False,
        "thresholds_applied_to_pass_fail": False,
        "advisor_approval_required": False,
        "inputs": _normalize_inputs(inputs),
        "metadata": dict(metadata or {}),
    }
    manifest.update(dict(flags))
    return manifest


def assert_no_forbidden_training_flags(manifest: dict[str, Any]) -> None:
    if manifest.get("mode") not in NON_EXECUTION_MODES:
        return
    forbidden_true_flags = (
        "training_enabled",
        "official_validation_executed",
        "stage2_training_enabled",
        "stage3_training_enabled",
        "stage4_training_enabled",
        "generation_training_enabled",
        "thresholds_applied_to_pass_fail",
        "retrieval_enabled",
        "verifier_enabled",
        "api_calls_enabled",
    )
    for flag in forbidden_true_flags:
        if bool(manifest.get(flag, False)):
            raise ValueError(f"Non-execution manifest cannot set `{flag}`=true.")


def assert_stage2_not_training_without_approval(spec: dict[str, Any], train_requested: bool) -> None:
    if train_requested and not bool(spec.get("advisor_stage2_approved", False)):
        raise ValueError("Stage 2 training requires advisor_stage2_approved=true in the stage2 spec.")


def assert_renderer_does_not_update_attribution(spec: dict[str, Any]) -> None:
    if not bool(spec.get("attribution_frozen_required", False)):
        raise ValueError("Stage 4 renderer requires attribution_frozen_required=true.")
    if not bool(spec.get("renderer_reads_only_plan_and_assigned_evidence", False)):
        raise ValueError("Stage 4 renderer requires renderer_reads_only_plan_and_assigned_evidence=true.")
    if not bool(spec.get("raw_full_diff_forbidden_as_ungrounded_context", False)):
        raise ValueError("Stage 4 renderer requires raw_full_diff_forbidden_as_ungrounded_context=true.")


def _normalize_inputs(inputs: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in dict(inputs or {}).items():
        if value is None:
            normalized[key] = None
        elif isinstance(value, (str, Path)):
            normalized[key] = safe_relpath_for_report(value)
        else:
            normalized[key] = value
    return normalized
