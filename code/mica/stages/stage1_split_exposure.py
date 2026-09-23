from __future__ import annotations

from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json


def audit_stage1_split_exposure(
    *,
    candidate_manifest_path: str | Path,
    current_official_manifest_path: str | Path | None,
    proposed_final_test_manifest_paths: list[str | Path],
) -> dict[str, Any]:
    candidate_rows = _load_rows(candidate_manifest_path)
    current_official_rows = _load_rows(current_official_manifest_path) if current_official_manifest_path is not None else []
    proposed_final_rows = []
    for path in proposed_final_test_manifest_paths:
        proposed_final_rows.extend(_load_rows(path))

    candidate_sample_ids = {str(row.get("sample_id") or "") for row in candidate_rows}
    current_official_sample_ids = {str(row.get("sample_id") or "") for row in current_official_rows}
    proposed_final_sample_ids = {str(row.get("sample_id") or "") for row in proposed_final_rows}
    candidate_leakage_groups = _leakage_groups(candidate_rows)
    current_official_leakage_groups = _leakage_groups(current_official_rows)
    proposed_final_leakage_groups = _leakage_groups(proposed_final_rows)

    current_runner_collision = bool(candidate_sample_ids & current_official_sample_ids) or bool(
        candidate_leakage_groups & current_official_leakage_groups
    )
    proposed_final_collision = bool(candidate_sample_ids & proposed_final_sample_ids) or bool(
        candidate_leakage_groups & proposed_final_leakage_groups
    )
    candidate_splits = sorted({_normalize_split(row.get("split")) for row in candidate_rows if row.get("split") is not None})
    current_official_splits = sorted(
        {_normalize_split(row.get("split")) for row in current_official_rows if row.get("split") is not None}
    )
    proposed_final_splits = sorted(
        {_normalize_split(row.get("split")) for row in proposed_final_rows if row.get("split") is not None}
    )

    if current_runner_collision:
        conclusion = "final_test_already_exposed"
        remediation = "redefine_current_stage1_official_validation_dev_as_dev_and_freeze_new_stage1_official_final_test"
    elif proposed_final_rows and not proposed_final_collision and set(candidate_splits) <= {"dev"} and set(proposed_final_splits) <= {"test"}:
        conclusion = "dev_only_unexposed_final_test"
        remediation = "freeze_new_stage1_official_final_test_before_official_validation"
    else:
        conclusion = "unknown"
        remediation = "freeze_unambiguous_stage1_official_final_test_before_official_validation"

    return {
        "conclusion": conclusion,
        "candidate_validation_split_must_not_equal_official_final_test_split": conclusion != "final_test_already_exposed",
        "candidate_manifest_path": str(candidate_manifest_path),
        "current_official_manifest_path": str(current_official_manifest_path) if current_official_manifest_path is not None else None,
        "proposed_final_test_manifest_paths": [str(path) for path in proposed_final_test_manifest_paths],
        "candidate_splits": candidate_splits,
        "current_official_splits": current_official_splits,
        "proposed_final_splits": proposed_final_splits,
        "candidate_sample_count": len(candidate_rows),
        "current_official_sample_count": len(current_official_rows),
        "proposed_final_sample_count": len(proposed_final_rows),
        "current_runner_sample_overlap_count": len(candidate_sample_ids & current_official_sample_ids),
        "current_runner_leakage_overlap_count": len(candidate_leakage_groups & current_official_leakage_groups),
        "proposed_final_sample_overlap_count": len(candidate_sample_ids & proposed_final_sample_ids),
        "proposed_final_leakage_overlap_count": len(candidate_leakage_groups & proposed_final_leakage_groups),
        "remediation": remediation,
    }


def _load_rows(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Stage 1 exposure manifest must be a JSON object: {path}")
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError(f"Stage 1 exposure manifest rows must be a list: {path}")
    return [row for row in rows if isinstance(row, dict)]


def _normalize_split(value: Any) -> str:
    return str(value or "unspecified").strip().lower().replace("-", "_")


def _leakage_groups(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("leakage_group") or "") for row in rows if str(row.get("leakage_group") or "")}
