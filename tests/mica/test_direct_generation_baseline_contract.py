from __future__ import annotations

from code.mica.baselines.direct_generation_baseline import run_direct_generation_baseline


def test_direct_generation_baseline_is_weak_deterministic() -> None:
    result = run_direct_generation_baseline({"edit_units": [{"file_role": "test"}]})

    assert result["baseline_strength"] == "weak_deterministic"
    assert result["not_neural_generation"] is True
    assert isinstance(result["message"], str)
