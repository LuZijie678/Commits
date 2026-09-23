import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from fixtures import create_targeted_regression_fixture
from run_targeted_generation_regression import build_targeted_regression_plan, run_targeted_generation_regression


def test_targeted_regression_plan_locks_sample_and_strategy(tmp_path):
    fixture = create_targeted_regression_fixture(tmp_path)
    plan = build_targeted_regression_plan(
        output_root=fixture["output_root"],
        sample_id="M_real_multi:7da239a00c1c6f17",
        strategy="G4",
        budget_cap_usd=0.03,
    )
    assert plan["sample"]["sample_id"] == "M_real_multi:7da239a00c1c6f17"
    assert plan["strategy"] == "G4"
    assert plan["planned_request_count"] == 1
    assert plan["leakage_gate"]["same_repo_canonical_any"] is False
    assert all(repo != "arthursonzogni/ftxui" for repo in plan["retrieval_log"]["retrieved_repo_canonical"])
    assert plan["exclusion_summary"]["repo_guard_excluded_candidates"][0]["reason"] == "same_repo_canonical"


def test_targeted_regression_requires_allow_real_api(tmp_path):
    fixture = create_targeted_regression_fixture(tmp_path)
    with pytest.raises(RuntimeError, match="disabled"):
        run_targeted_generation_regression(
            output_root=fixture["output_root"],
            sample_id="M_real_multi:7da239a00c1c6f17",
            strategy="G4",
            config={"backend": {"provider": "openai_compatible", "model": "deepseek-v4-flash"}},
            allow_real_api=False,
        )


def test_targeted_regression_budget_gate_blocks(tmp_path):
    fixture = create_targeted_regression_fixture(tmp_path)
    with pytest.raises(RuntimeError, match="budget"):
        build_targeted_regression_plan(
            output_root=fixture["output_root"],
            sample_id="M_real_multi:7da239a00c1c6f17",
            strategy="G4",
            budget_cap_usd=0.0000001,
        )


def test_targeted_regression_resume_uses_cache(tmp_path):
    fixture = create_targeted_regression_fixture(tmp_path)
    config = {"backend": {"provider": "mock", "model": "mock-model", "cache_path": str(tmp_path / "cache.json")}}
    first = run_targeted_generation_regression(
        output_root=fixture["output_root"],
        sample_id="M_real_multi:7da239a00c1c6f17",
        strategy="G4",
        config=config,
        allow_real_api=True,
    )
    second = run_targeted_generation_regression(
        output_root=fixture["output_root"],
        sample_id="M_real_multi:7da239a00c1c6f17",
        strategy="G4",
        config=config,
        allow_real_api=True,
    )
    assert first["report"]["new_real_request_count"] == 1
    assert first["report"]["cache_hit_count"] == 0
    assert first["report"]["resume_skip_count"] == 0
    assert second["result"]["cache_hit"] is True
    assert second["report"]["new_real_request_count"] == 0
    assert second["report"]["cache_hit_count"] == 1
    assert second["report"]["resume_skip_count"] == 1
