from __future__ import annotations

from typing import Any


def build_stage2_mixture_manifest(spec: dict[str, Any], source_manifests: dict[str, Any]) -> dict[str, Any]:
    weights = dict(spec.get("mixture_weights", {}))
    weight_sum = sum(float(value) for value in weights.values())
    if weights and abs(weight_sum - 1.0) > 1e-6:
        raise ValueError("Stage 2 mixture weights must sum to 1.0.")

    boundary = validate_stage2_data_boundaries(spec, source_manifests)
    if boundary["errors"]:
        raise ValueError("; ".join(boundary["errors"]))

    dataset_roles = {
        "strict_replay": {
            "required": True,
            "row_count": len(_rows(source_manifests.get("strict_replay"))),
            "weight": float(weights.get("strict_replay", 0.0)),
            "supervision": "stage1_main_replay",
        },
        "hard_b": {
            "required": True,
            "row_count": len(_rows(source_manifests.get("hard_b_train"))) + len(_rows(source_manifests.get("hard_b_dev"))),
            "weight": float(weights.get("hard_b", 0.0)),
            "supervision": "anti_over_split_k1",
        },
        "m_weak": {
            "required": True,
            "row_count": len(_rows(source_manifests.get("m_weak_train"))) + len(_rows(source_manifests.get("m_weak_dev"))),
            "weight": float(weights.get("m_weak", 0.0)),
            "supervision": "censored_k_ge_2",
        },
        "m_align_calib": {
            "optional": True,
            "row_count": len(_rows(source_manifests.get("m_align_calib"))),
            "weight": float(weights.get("m_align_calib", 0.0)),
            "supervision": "real_alignment_optional",
        },
    }
    return {
        "stage": "stage2_real_domain_calibration",
        "training_entry_prepared": True,
        "stage2_training_executed": False,
        "m_final_test_used_for_training": False,
        "hard_b_test_used_for_training": False,
        "real_domain_split_test_used_for_training": False,
        "real_domain_selective_test_used_for_training": False,
        "dataset_roles": dataset_roles,
        "boundary_validation": boundary,
    }


def validate_stage2_data_boundaries(spec: dict[str, Any], source_manifests: dict[str, Any]) -> dict[str, Any]:
    del spec
    errors: list[str] = []
    warnings: list[str] = []

    if _rows(source_manifests.get("m_final_test")):
        errors.append("m_final_test_forbidden")
    if _rows(source_manifests.get("hard_b_test")):
        errors.append("hard_b_test_forbidden")
    if _rows(source_manifests.get("real_domain_split_test")):
        errors.append("real_domain_split_test_forbidden")
    if _rows(source_manifests.get("real_domain_selective_test")):
        errors.append("real_domain_selective_test_forbidden")
    if not _rows(source_manifests.get("strict_replay")):
        errors.append("strict_replay_required")
    if _rows(source_manifests.get("m_align_calib")) and _rows(source_manifests.get("m_final_test")):
        errors.append("m_align_calib_must_be_isolated_from_m_final_test")

    dataset_presence = {key: len(_rows(value)) for key, value in source_manifests.items()}
    if dataset_presence.get("m_weak_train", 0) == 0 and dataset_presence.get("m_weak_dev", 0) == 0:
        warnings.append("m_weak_missing")

    return {
        "stage": "stage2_real_domain_calibration",
        "training_entry_prepared": True,
        "stage2_training_executed": False,
        "m_final_test_used_for_training": False,
        "hard_b_test_used_for_training": False,
        "real_domain_split_test_used_for_training": False,
        "real_domain_selective_test_used_for_training": False,
        "dataset_presence": dataset_presence,
        "m_weak_supervision": "censored_k_ge_2",
        "warnings": warnings,
        "errors": errors,
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        if "rows" in payload and isinstance(payload["rows"], list):
            return [row for row in payload["rows"] if isinstance(row, dict)]
        if "splits" in payload and isinstance(payload["splits"], dict):
            rows: list[dict[str, Any]] = []
            for split, split_rows in payload["splits"].items():
                if not isinstance(split_rows, list):
                    continue
                for row in split_rows:
                    if isinstance(row, dict):
                        copied = dict(row)
                        copied.setdefault("split", split)
                        rows.append(copied)
            return rows
    return []
