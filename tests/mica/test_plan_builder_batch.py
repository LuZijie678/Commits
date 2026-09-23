from __future__ import annotations

from code.mica.plan_builder import build_plan_from_dict, build_plans_from_jsonl
from code.mica.io_utils import read_json, read_jsonl, write_jsonl


def _embedded_prediction(sample_id: str = "sample_1") -> dict:
    return {
        "sample_id": sample_id,
        "predicted_count": 2,
        "count_probs": {"1": 0.1, "2": 0.9},
        "active_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}},
            {"slot_id": "slot_2", "existence_prob": 0.8, "edit_unit_ids": ["u2"], "hunk_ids": ["h2"], "confidence": 0.7, "assignment_scores": {"u2": 0.8}, "diagnostics": {}},
        ],
        "all_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}},
            {"slot_id": "slot_2", "existence_prob": 0.8, "edit_unit_ids": ["u2"], "hunk_ids": ["h2"], "confidence": 0.7, "assignment_scores": {"u2": 0.8}, "diagnostics": {}},
        ],
        "unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
        "unit_assignment_scores": {"u1": {"slot_1": 0.9}, "u2": {"slot_2": 0.8}},
        "source": "predicted_plan",
        "metadata": {},
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/auth.py", "hunk_id": "h1", "file_role": "source", "changed_identifiers": ["auth"], "added_lines": ["auth = 1"]},
            {"unit_id": "u2", "file_path": "docs/api.md", "hunk_id": "h2", "file_role": "doc", "changed_identifiers": ["api"], "added_lines": ["api = 1"]},
        ],
    }


def test_prediction_with_embedded_edit_units_builds_plan(tmp_path) -> None:
    prediction_path = tmp_path / "predictions.jsonl"
    output_path = tmp_path / "plans.jsonl"
    summary_json = tmp_path / "summary.json"
    summary_md = tmp_path / "summary.md"
    write_jsonl(prediction_path, [_embedded_prediction()])

    summary = build_plans_from_jsonl(
        prediction_jsonl=prediction_path,
        output_jsonl=output_path,
        summary_json_path=summary_json,
        summary_md_path=summary_md,
    )

    plans = read_jsonl(output_path)
    assert len(plans) == 1
    assert plans[0]["sample_id"] == "sample_1"
    assert plans[0]["degraded"] is False
    assert summary["plans_built"] == 1
    assert read_json(summary_json)["plans_built"] == 1


def test_prediction_plus_separate_edit_units_builds_plan(tmp_path) -> None:
    prediction = _embedded_prediction()
    prediction.pop("edit_units")
    prediction_path = tmp_path / "predictions.jsonl"
    edit_units_path = tmp_path / "edit_units.jsonl"
    output_path = tmp_path / "plans.jsonl"
    write_jsonl(prediction_path, [prediction])
    write_jsonl(edit_units_path, [{"sample_id": "sample_1", "edit_units": _embedded_prediction()["edit_units"]}])

    build_plans_from_jsonl(
        prediction_jsonl=prediction_path,
        edit_units_jsonl_or_manifest=edit_units_path,
        output_jsonl=output_path,
    )

    plans = read_jsonl(output_path)
    assert plans[0]["intent_count"] == 2
    assert len(plans[0]["intents"]) == 2


def test_missing_edit_units_yields_degraded_plan(tmp_path) -> None:
    prediction = _embedded_prediction()
    prediction.pop("edit_units")
    prediction_path = tmp_path / "predictions.jsonl"
    output_path = tmp_path / "plans.jsonl"
    write_jsonl(prediction_path, [prediction])

    summary = build_plans_from_jsonl(prediction_jsonl=prediction_path, output_jsonl=output_path)
    plan = read_jsonl(output_path)[0]
    codes = {item["code"] for item in plan["diagnostics"]}

    assert plan["degraded"] is True
    assert "missing_edit_units" in codes
    assert summary["missing_edit_units_count"] == 1


def test_sample_id_mismatch_adds_diagnostic() -> None:
    prediction = _embedded_prediction("sample_a")
    edit_units_container = {"sample_id": "sample_b", "edit_units": prediction["edit_units"]}

    plan = build_plan_from_dict(prediction, edit_units_container)
    assert "sample_id_mismatch" in {item.code for item in plan.diagnostics}


def test_batch_continues_after_bad_row_and_collects_histogram(tmp_path) -> None:
    good = _embedded_prediction("good")
    bad = {"predicted_count": 1, "active_slots": "not-a-list"}
    prediction_path = tmp_path / "predictions.jsonl"
    output_path = tmp_path / "plans.jsonl"
    summary_json = tmp_path / "summary.json"
    write_jsonl(prediction_path, [good, bad])

    summary = build_plans_from_jsonl(
        prediction_jsonl=prediction_path,
        output_jsonl=output_path,
        summary_json_path=summary_json,
    )

    plans = read_jsonl(output_path)
    assert len(plans) == 2
    assert summary["plans_built"] == 2
    assert summary["degraded_count"] == 1
    assert summary["diagnostic_histogram"]["plan_builder_exception"] == 1
    assert read_json(summary_json)["diagnostic_histogram"]["plan_builder_exception"] == 1


def test_diagnostic_histogram_counts_slot_collapse() -> None:
    prediction = _embedded_prediction("collapsed")
    prediction["active_slots"][0]["edit_unit_ids"] = ["u1", "u2"]
    prediction["active_slots"][1]["edit_unit_ids"] = []
    prediction["all_slots"] = prediction["active_slots"]
    prediction["unit_to_slot"] = {"u1": "slot_1", "u2": "slot_1"}
    prediction["unit_assignment_scores"] = {"u1": {"slot_1": 0.9}, "u2": {"slot_1": 0.9}}
    plan = build_plan_from_dict(prediction, prediction["edit_units"])
    assert "slot_collapse_detected" in {item.code for item in plan.diagnostics}
