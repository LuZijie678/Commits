from __future__ import annotations

from typing import Any


_MASKING_MODES = {
    "path_masked",
    "identifier_masked",
    "marker_masked",
    "template_subject_masked",
    "file_order_permuted",
}

DEFAULT_MASKING_MODES = ("path_masked", "marker_masked", "identifier_masked")


def build_path_masked_view(edit_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    masked: list[dict[str, Any]] = []
    for unit in edit_units:
        copied = dict(unit)
        if "file_path" in copied:
            copied["file_path"] = "<path_masked>"
        masked.append(copied)
    return masked


def build_diff_marker_masked_view(edit_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    masked: list[dict[str, Any]] = []
    for unit in edit_units:
        copied = dict(unit)
        patch_text = str(copied.get("patch_text", ""))
        normalized_lines = []
        for line in patch_text.splitlines():
            if line.startswith("+") or line.startswith("-"):
                normalized_lines.append(f"~{line[1:]}")
            else:
                normalized_lines.append(line)
        copied["patch_text"] = "\n".join(normalized_lines)
        masked.append(copied)
    return masked


def build_identifier_masked_view(edit_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    masked: list[dict[str, Any]] = []
    for unit in edit_units:
        copied = dict(unit)
        identifiers = list(copied.get("changed_identifiers", []))
        copied["changed_identifiers"] = ["<identifier_masked>" for _ in identifiers]
        masked.append(copied)
    return masked


def build_anti_shortcut_experiment_plan(spec: dict[str, Any], dataset_manifest: list[dict[str, Any]]) -> dict[str, Any]:
    masking_modes = resolve_masking_modes(spec)
    return {
        "experiment_kind": "anti_shortcut",
        "masking_modes": masking_modes,
        "sample_count": len(dataset_manifest),
        "execute_model_by_default": bool(spec.get("execute_model_by_default", False)),
        "model_execution_requires_advisor_approval": True,
        "shortcut_conclusion_made": False,
        "thresholds_tuned": False,
    }


def resolve_masking_modes(spec: dict[str, Any]) -> list[str]:
    explicit = [str(mode) for mode in spec.get("masking_modes", [])]
    selected = [mode for mode in explicit if mode in _MASKING_MODES]
    legacy_flags = {
        "path_masking_enabled_for_future": "path_masked",
        "diff_marker_masking_enabled_for_future": "marker_masked",
        "identifier_masking_enabled_for_future": "identifier_masked",
        "template_subject_masking_enabled_for_future": "template_subject_masked",
        "file_order_permutation_enabled_for_future": "file_order_permuted",
    }
    for flag, mode in legacy_flags.items():
        if bool(spec.get(flag, False)) and mode not in selected:
            selected.append(mode)
    return selected or list(DEFAULT_MASKING_MODES)


def build_masked_dataset_rows(rows: list[dict[str, Any]], masking_mode: str) -> list[dict[str, Any]]:
    if masking_mode not in _MASKING_MODES:
        raise ValueError(f"Unsupported masking mode: {masking_mode}")
    runtime: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        edit_units = [dict(unit) for unit in row.get("edit_units", [])]
        if masking_mode == "path_masked":
            copied["edit_units"] = build_path_masked_view(edit_units)
        elif masking_mode == "identifier_masked":
            copied["edit_units"] = build_identifier_masked_view(edit_units)
        elif masking_mode == "marker_masked":
            copied["edit_units"] = build_diff_marker_masked_view(edit_units)
        elif masking_mode == "template_subject_masked":
            copied["subject"] = "<subject_masked>"
            copied["edit_units"] = edit_units
        elif masking_mode == "file_order_permuted":
            copied["edit_units"] = list(reversed(edit_units))
        runtime.append(copied)
    return runtime


def build_model_rerun_request(masked_dataset_path: str, model_command: list[str], spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "masked_dataset_path": str(masked_dataset_path),
        "model_command": [str(item) for item in model_command],
        "execute_model": bool(spec.get("execute_model_by_default", False)),
        "advisor_approval_required": True,
        "api_calls_enabled": False,
        "retrieval_enabled": False,
        "verifier_enabled": False,
    }


def summarize_shortcut_sensitivity(original_metrics: dict[str, Any], masked_metrics: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in original_metrics.items():
        if key in masked_metrics and isinstance(value, (int, float)) and isinstance(masked_metrics[key], (int, float)):
            payload[f"delta_{key}"] = round(float(masked_metrics[key]) - float(value), 6)
    return payload


def summarize_shortcut_features(edit_units: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "unit_count": len(edit_units),
        "path_count": len({str(unit.get("file_path")) for unit in edit_units if unit.get("file_path")}),
        "identifier_count": sum(len(unit.get("changed_identifiers", [])) for unit in edit_units),
        "diff_marker_present_count": sum(1 for unit in edit_units if "+" in str(unit.get("patch_text", "")) or "-" in str(unit.get("patch_text", ""))),
    }


def audit_shortcut_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_samples = len(rows)
    total_units = 0
    for row in rows:
        total_units += len(row.get("edit_units", []))
    return {
        "readiness_checked": True,
        "shortcut_conclusion_made": False,
        "training_executed": False,
        "model_executed": False,
        "sample_count": total_samples,
        "edit_unit_count": total_units,
    }
