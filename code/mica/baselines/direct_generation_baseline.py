from __future__ import annotations

from typing import Any


def run_direct_generation_baseline(row: dict[str, Any]) -> dict[str, Any]:
    roles = {str(unit.get("file_role", "")).lower() for unit in row.get("edit_units", [])}
    if "test" in roles:
        message = "update tests"
    elif "doc" in roles or "docs" in roles:
        message = "update docs"
    else:
        message = "update files"
    return {
        "message": message,
        "baseline_strength": "weak_deterministic",
        "not_neural_generation": True,
        "metadata": {"baseline": "direct_generation"},
    }
