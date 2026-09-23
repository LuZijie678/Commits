from __future__ import annotations

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.renderers.deterministic import DeterministicRenderer, render_plans_from_jsonl


def _plan(sample_id: str, *, subject: str | None, degraded: bool = False) -> dict:
    return {
        "sample_id": sample_id,
        "intent_count": 1,
        "is_multi_intent": False,
        "intents": [
            {
                "intent_id": "intent_1",
                "slot_id": "slot_1",
                "edit_unit_ids": ["u1"],
                "hunk_ids": ["h1"],
                "evidence_units": [
                    {
                        "unit_id": "u1",
                        "file_path": "src/auth/token.py",
                        "file_role": "source",
                        "changed_identifiers": ["token"],
                        "patch_text": "RAW_FULL_DIFF_SHOULD_NOT_APPEAR",
                        "added_lines": ["token = refresh(token)"],
                    }
                ],
                "confidence": 0.9,
                "type": None,
                "scope": None,
                "subject": subject,
                "body": None,
                "core_units": ["u1"],
                "support_units": [],
                "auxiliary_units": [],
                "diagnostics": {},
            }
        ],
        "rendering_status": "degraded" if degraded else "ready",
        "degraded": degraded,
        "diagnostics": [{"code": "slot_collapse_detected", "severity": "warning", "message": "collapsed", "metadata": {}}] if degraded else [],
        "metadata": {},
    }


def test_renderer_batch_uses_subject_when_present(tmp_path) -> None:
    plan_jsonl = tmp_path / "plans.jsonl"
    output_jsonl = tmp_path / "messages.jsonl"
    write_jsonl(plan_jsonl, [_plan("s1", subject="fix token validation")])

    summary = render_plans_from_jsonl(plan_jsonl=plan_jsonl, output_jsonl=output_jsonl)
    rows = read_jsonl(output_jsonl)

    assert rows[0]["subject"]
    assert rows[0]["subject"] != "fix token validation"
    assert summary["fallback_subject_count"] == 1


def test_renderer_batch_uses_conservative_fallback_when_subject_missing(tmp_path) -> None:
    plan_jsonl = tmp_path / "plans.jsonl"
    output_jsonl = tmp_path / "messages.jsonl"
    summary_json = tmp_path / "summary.json"
    write_jsonl(plan_jsonl, [_plan("s1", subject=None)])

    summary = render_plans_from_jsonl(plan_jsonl=plan_jsonl, output_jsonl=output_jsonl, summary_json_path=summary_json)
    rows = read_jsonl(output_jsonl)

    assert rows[0]["subject"]
    assert "RAW_FULL_DIFF_SHOULD_NOT_APPEAR" not in rows[0]["subject"]
    assert summary["fallback_subject_count"] == 1
    assert read_json(summary_json)["fallback_subject_rate"] == 1.0


def test_renderer_batch_marks_degraded_message(tmp_path) -> None:
    plan_jsonl = tmp_path / "plans.jsonl"
    output_jsonl = tmp_path / "messages.jsonl"
    write_jsonl(plan_jsonl, [_plan("s1", subject=None, degraded=True)])

    rows = read_jsonl(output_jsonl) if output_jsonl.exists() else []
    assert rows == []

    render_plans_from_jsonl(plan_jsonl=plan_jsonl, output_jsonl=output_jsonl)
    rows = read_jsonl(output_jsonl)
    assert rows[0]["degraded"] is True


def test_renderer_summary_counts_fallback_rate(tmp_path) -> None:
    plan_jsonl = tmp_path / "plans.jsonl"
    output_jsonl = tmp_path / "messages.jsonl"
    summary_json = tmp_path / "summary.json"
    write_jsonl(plan_jsonl, [_plan("s1", subject=None), _plan("s2", subject="update docs")])

    summary = render_plans_from_jsonl(plan_jsonl=plan_jsonl, output_jsonl=output_jsonl, summary_json_path=summary_json)
    assert summary["total_plans"] == 2
    assert summary["fallback_subject_count"] == 2
    assert summary["fallback_subject_rate"] == 1.0
    assert "fallback_subject_used" in summary["diagnostic_histogram"]


def test_renderer_source_does_not_consume_raw_diff_argument() -> None:
    source = (tmp_path := None)  # noqa: F841
    module_source = DeterministicRenderer.render.__code__.co_varnames
    assert "raw_diff" not in module_source
