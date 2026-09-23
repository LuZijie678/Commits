from __future__ import annotations

from typing import Any

from code.mica.eval.manifest_checks import check_stage1_manifest_compatibility


def summarize_stage0_protocol(protocol_spec: dict[str, Any], manifest_rows: list[dict[str, Any]]) -> dict[str, Any]:
    compatibility = check_stage1_manifest_compatibility(manifest_rows, protocol_spec)
    return {
        "stage": "stage0_protocol",
        "protocol_status": protocol_spec.get("protocol_status", "unknown"),
        "candidate_schedule": protocol_spec.get("candidate_schedule"),
        "stage2_allowed": protocol_spec.get("stage2_allowed", False),
        "compatibility": compatibility,
    }
