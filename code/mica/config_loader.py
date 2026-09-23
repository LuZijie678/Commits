from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from code.mica.config_validation import (
    validate_eval_spec,
    validate_stage1_protocol_spec,
    validate_stage2_spec,
    validate_stage3_spec,
    validate_stage4_spec,
    validate_threshold_spec,
)
from code.mica.data.asset_registry import validate_asset_registry
from code.mica.io_utils import read_json


def load_mica_config(path: str) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"MICA config at {path} must be a JSON object.")
    return payload


def load_all_stage_configs(config_root: str = "configs/mica") -> dict[str, dict[str, Any]]:
    root = Path(config_root)
    if not root.is_absolute():
        root = (Path(__file__).resolve().parents[2] / root).resolve()
    payload: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        payload[path.stem] = load_mica_config(str(path))
    return payload


def validate_config_family(configs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {}

    stage1 = configs.get("stage1_protocol_spec")
    stage2 = configs.get("stage2_calibration_spec")
    stage3 = configs.get("stage3_alignment_calibration_spec")
    stage4 = configs.get("stage4_renderer_spec")
    thresholds = configs.get("stage1_metric_thresholds")
    asset_registry = configs.get("data_asset_registry")
    evidence_spec = configs.get("evidence_relation_spec")

    if stage1 is not None:
        result = validate_stage1_protocol_spec(stage1)
        errors.extend(f"stage1_protocol_spec:{item}" for item in result["errors"])
        warnings.extend(f"stage1_protocol_spec:{item}" for item in result["warnings"])
    if stage2 is not None:
        result = validate_stage2_spec(stage2)
        errors.extend(f"stage2_calibration_spec:{item}" for item in result["errors"])
        warnings.extend(f"stage2_calibration_spec:{item}" for item in result["warnings"])
        summary["stage2_consistency_default_enabled"] = bool(stage2.get("consistency", {}).get("enabled", False))
        if stage2.get("advisor_stage2_approved") is not False:
            errors.append("stage2_calibration_spec:advisor_stage2_approved must default to false")
    if stage3 is not None:
        result = validate_stage3_spec(stage3)
        errors.extend(f"stage3_alignment_calibration_spec:{item}" for item in result["errors"])
        warnings.extend(f"stage3_alignment_calibration_spec:{item}" for item in result["warnings"])
        if stage3.get("advisor_stage3_approved") is not False:
            errors.append("stage3_alignment_calibration_spec:advisor_stage3_approved must default to false")
    if stage4 is not None:
        result = validate_stage4_spec(stage4)
        errors.extend(f"stage4_renderer_spec:{item}" for item in result["errors"])
        warnings.extend(f"stage4_renderer_spec:{item}" for item in result["warnings"])
        if stage4.get("advisor_stage4_approved") is not False:
            errors.append("stage4_renderer_spec:advisor_stage4_approved must default to false")
        if stage4.get("advisor_stage4_trainable_renderer_approved") is not False:
            errors.append("stage4_renderer_spec:advisor_stage4_trainable_renderer_approved must default to false")
    if thresholds is not None:
        result = validate_threshold_spec(thresholds)
        errors.extend(f"stage1_metric_thresholds:{item}" for item in result["errors"])
        if "pending" in str(thresholds.get("threshold_status", "")):
            warnings.append("stage1_metric_thresholds:advisor_pending_thresholds_cannot_define_final_pass_fail")
    for eval_name in ("eval_real_domain_spec", "eval_alignment_spec", "eval_message_utility_spec"):
        if configs.get(eval_name) is not None:
            result = validate_eval_spec(configs[eval_name])
            errors.extend(f"{eval_name}:{item}" for item in result["errors"])
    if asset_registry is not None:
        asset_result = validate_asset_registry(asset_registry)
        errors.extend(f"data_asset_registry:{item['code']}" for item in asset_result["errors"])
        errors.extend(_validate_eval_only_assets(asset_registry))
    if evidence_spec is not None:
        errors.extend(_validate_evidence_spec(evidence_spec))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }


def compute_config_family_hash(configs: dict[str, dict[str, Any]]) -> str:
    canonical = json.dumps(configs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_eval_only_assets(registry: dict[str, Any]) -> list[str]:
    assets = dict(registry.get("assets", {}))
    errors: list[str] = []
    for asset_name in ("hard_b_test", "m_final_test", "real_domain_split_test", "real_domain_selective_test"):
        payload = dict(assets.get(asset_name, {}))
        if payload.get("eval_only") is not True:
            errors.append(f"{asset_name} must be eval_only")
    return errors


def _validate_evidence_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in spec.get("relations", {}):
        if "gold" in str(name).lower():
            errors.append("evidence_relation_spec:gold-leakage relation forbidden")
    return errors
