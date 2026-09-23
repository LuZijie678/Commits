from __future__ import annotations

from code.mica.eval.anti_shortcut_audit import (
    build_anti_shortcut_experiment_plan,
    build_masked_dataset_rows,
    build_model_rerun_request,
    resolve_masking_modes,
    summarize_shortcut_sensitivity,
)


def test_build_masked_dataset_rows_supports_template_subject_masked() -> None:
    rows = [{"sample_id": "s1", "subject": "fix auth issue", "edit_units": [{"file_path": "src/auth.py"}]}]

    masked = build_masked_dataset_rows(rows, "template_subject_masked")

    assert masked[0]["subject"] == "<subject_masked>"


def test_build_anti_shortcut_experiment_plan_lists_masking_modes() -> None:
    plan = build_anti_shortcut_experiment_plan({"masking_modes": ["path_masked", "identifier_masked"]}, [{"sample_id": "s1"}])

    assert plan["masking_modes"] == ["path_masked", "identifier_masked"]
    assert plan["sample_count"] == 1
    assert plan["model_execution_requires_advisor_approval"] is True
    assert plan["shortcut_conclusion_made"] is False


def test_resolve_masking_modes_supports_legacy_flags_and_default() -> None:
    assert resolve_masking_modes({}) == ["path_masked", "marker_masked", "identifier_masked"]
    assert resolve_masking_modes({"template_subject_masking_enabled_for_future": True}) == ["template_subject_masked"]


def test_build_model_rerun_request_stays_non_executing_by_default() -> None:
    request = build_model_rerun_request("/tmp/masked.jsonl", ["python", "runner.py"], {"execute_model_by_default": False})

    assert request["execute_model"] is False
    assert request["api_calls_enabled"] is False


def test_summarize_shortcut_sensitivity_returns_metric_deltas() -> None:
    summary = summarize_shortcut_sensitivity({"pairwise_f1": 0.8}, {"pairwise_f1": 0.6})

    assert summary["delta_pairwise_f1"] == -0.2
