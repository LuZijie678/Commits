from __future__ import annotations

import json

from code.mica.adapters.stage1_prediction_adapter import (
    detect_stage1_prediction_format,
    extract_edit_units_from_prediction_row,
    normalize_stage1_prediction_row,
    prediction_row_to_attribution_prediction,
    validate_stage1_prediction_row,
)
from code.mica.schemas import AttributionPrediction


def _standard_row() -> dict:
    return {
        "sample_id": "sample-standard",
        "predicted_count": 2,
        "count_probs": {"1": 0.1, "2": 0.8},
        "active_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["e1"]},
            {"slot_id": "slot_2", "existence_prob": 0.7, "edit_unit_ids": ["e2"]},
        ],
        "unit_to_slot": {"e1": "slot_1", "e2": "slot_2"},
        "unit_assignment_scores": {
            "e1": {"slot_1": 0.95, "slot_2": 0.05},
            "e2": {"slot_1": 0.10, "slot_2": 0.90},
        },
        "edit_units": [
            {"unit_id": "e1", "file_path": "src/auth.py", "gold_intent_id": "i1"},
            {"unit_id": "e2", "file_path": "tests/test_auth.py", "gold_intent_id": "i2"},
        ],
    }


def test_standard_row_adapts_to_attribution_prediction() -> None:
    row = _standard_row()

    prediction = prediction_row_to_attribution_prediction(row)
    validation = validate_stage1_prediction_row(row)

    assert detect_stage1_prediction_format(row) == "standard"
    assert prediction.sample_id == "sample-standard"
    assert prediction.predicted_count == 2
    assert len(prediction.active_slots) == 2
    assert prediction.unit_to_slot["e2"] == "slot_2"
    assert validation["degraded"] is False


def test_legacy_aliases_adapt_with_best_effort_compatibility() -> None:
    row = {
        "sample_id": "sample-legacy",
        "k_hat": 2,
        "slot_probs": {"1": 0.15, "2": 0.75},
        "slot_exist": {"slot_1": 0.9, "slot_2": 0.4},
        "assignments": {"e1": "slot_1", "e2": "slot_2"},
        "unit_records": [
            {"unit_id": "e1", "file_path": "src/a.py"},
            {"unit_id": "e2", "file_path": "src/b.py"},
        ],
    }

    normalized = normalize_stage1_prediction_row(row)
    prediction = prediction_row_to_attribution_prediction(row)

    assert detect_stage1_prediction_format(row) == "legacy_aliases"
    assert normalized["predicted_count"] == 2
    assert prediction.count_probs["2"] == 0.75
    assert len(prediction.active_slots) == 2
    assert prediction.unit_to_slot["e1"] == "slot_1"


def test_top1_only_row_is_marked_as_limited_prediction_format() -> None:
    row = {
        "sample_id": "sample-top1",
        "predicted_count": 2,
        "unit_to_slot": {
            "e1": "slot_1",
            "e2": "slot_2",
        },
    }

    validation = validate_stage1_prediction_row(row)
    codes = {item["code"] for item in validation["diagnostics"]}

    assert detect_stage1_prediction_format(row) == "top1_only"
    assert "missing_assignment_scores" in codes
    assert "limited_prediction_format" in codes
    assert "slot_existence_missing" in codes


def test_missing_sample_id_returns_error_diagnostic() -> None:
    row = {"predicted_count": 1, "unit_to_slot": {"e1": "slot_1"}}

    validation = validate_stage1_prediction_row(row)

    assert validation["has_error"] is True
    assert "missing_sample_id" in {item["code"] for item in validation["diagnostics"]}


def test_unknown_format_returns_diagnostic() -> None:
    row = {"foo": "bar"}

    validation = validate_stage1_prediction_row(row)

    assert detect_stage1_prediction_format(row) == "unknown"
    assert "unknown_prediction_format" in {item["code"] for item in validation["diagnostics"]}


def test_edit_units_can_be_extracted_from_prediction_row() -> None:
    units = extract_edit_units_from_prediction_row(_standard_row())

    assert len(units) == 2
    assert units[0].unit_id == "e1"


def test_prediction_json_roundtrip_preserves_sample_id() -> None:
    prediction = prediction_row_to_attribution_prediction(_standard_row())
    payload = json.loads(json.dumps(prediction.to_dict()))
    reloaded = AttributionPrediction.from_dict(payload)

    assert reloaded.sample_id == prediction.sample_id
    assert reloaded.predicted_count == prediction.predicted_count


def test_null_slot_is_not_promoted_to_foreground_active_slot() -> None:
    row = {
        "sample_id": "sample-null-slot",
        "k_hat": 1,
        "slot_exist": {"slot_1": 0.9, "slot_null": 0.99},
        "assignments": {"e1": "slot_1", "e_noise": "slot_null"},
        "unit_records": [
            {"unit_id": "e1", "file_path": "src/auth.py"},
            {"unit_id": "e_noise", "file_path": "package-lock.json"},
        ],
    }

    normalized = normalize_stage1_prediction_row(row)

    assert [slot["slot_id"] for slot in normalized["active_slots"]] == ["slot_1"]
