from __future__ import annotations

from typing import Any


def build_experiment_report_schema(stage: str, metrics: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    git_info = provenance.get("git", provenance)
    if git_info.get("dirty") is True:
        warnings.append("dirty_worktree_not_fully_reproducible")
    return {
        "report_version": "mica-report-v1",
        "stage": stage,
        "schema_version": "mica-report-v1",
        "metrics": dict(metrics),
        "provenance": dict(provenance),
        "warnings": warnings,
    }
