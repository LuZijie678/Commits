from __future__ import annotations

from code.mica.schema_validation import (
    validate_attribution_prediction_contract,
    validate_cross_stage_contracts,
    validate_paper_table_contract,
    validate_renderer_input_contract,
    validate_structured_intent_plan_contract,
)


def test_stage1_prediction_and_plan_contracts_allow_degraded_top1_format() -> None:
    prediction = {
        "sample_id": "s1",
        "predicted_count": 2,
        "unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
        "schema_version": "v1",
        "source_stage": "stage1",
    }
    plan = {
        "sample_id": "s1",
        "intent_count": 2,
        "is_multi_intent": True,
        "degraded": True,
        "intents": [{"intent_id": "i1", "slot_id": "slot_1", "edit_unit_ids": ["u1"], "evidence_units": []}],
        "diagnostics": [{"code": "missing_evidence", "severity": "warning", "message": "fixture"}],
    }

    prediction_result = validate_attribution_prediction_contract(prediction)
    plan_result = validate_structured_intent_plan_contract(plan)

    assert prediction_result["valid"] is True
    assert "limited_prediction_format" in prediction_result["warnings"]
    assert plan_result["valid"] is True
    assert "degraded_plan" in plan_result["warnings"]


def test_missing_sample_id_fails_and_renderer_requires_proxy_flag() -> None:
    bad_prediction = {"predicted_count": 1}
    bad_renderer_input = {"sample_id": "s1", "message": "update auth", "structured_intent_plan": {"sample_id": "s1", "intents": []}}

    prediction_result = validate_attribution_prediction_contract(bad_prediction)
    renderer_result = validate_renderer_input_contract(bad_renderer_input)

    assert prediction_result["valid"] is False
    assert "missing_sample_id" in prediction_result["errors"]
    assert renderer_result["valid"] is False
    assert "missing_proxy_not_human_eval" in renderer_result["errors"]


def test_review_ready_prediction_contract_requires_release_decision_and_scores() -> None:
    prediction = {
        "sample_id": "s1",
        "predicted_count": 2,
        "count_probs": {"1": 0.1, "2": 0.9},
        "unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
        "unit_records": [
            {"unit_id": "u1", "file_path": "src/auth.py"},
            {"unit_id": "u2", "file_path": "tests/test_auth.py"},
        ],
    }

    result = validate_attribution_prediction_contract(prediction, mode="review_ready")

    assert result["valid"] is False
    assert "missing_release_decision" in result["errors"]
    assert "missing_assignment_scores" in result["errors"]


def test_review_ready_prediction_contract_accepts_external_edit_units_flag() -> None:
    prediction = {
        "sample_id": "s1",
        "predicted_count": 1,
        "count_probs": {"1": 0.95},
        "unit_to_slot": {"u1": "slot_1"},
        "assignment_scores": {"u1": {"slot_1": 0.95}},
        "metadata": {"release_decision": "decompose"},
    }

    result = validate_attribution_prediction_contract(
        prediction,
        mode="review_ready",
        external_edit_units_available=True,
    )

    assert result["valid"] is True


def test_paper_table_contract_requires_metric_metadata_cells() -> None:
    bad_row = {
        "row_name": "model_a",
        "comparison_group": "predicted_k",
        "metrics": {"pairwise_f1": {"value": 0.8}},
    }

    result = validate_paper_table_contract(bad_row)

    assert result["valid"] is False
    assert "metric_pairwise_f1_missing_higher_is_better" in result["errors"]


def test_cross_stage_contracts_produce_diagnostics_instead_of_silent_pass() -> None:
    rows = {
        "stage1_prediction": {"sample_id": "s1", "predicted_count": 1, "unit_to_slot": {"u1": "slot_1"}},
        "structured_intent_plan": {"sample_id": "s1", "intent_count": 1, "is_multi_intent": False, "intents": []},
        "renderer_input": {
            "sample_id": "s1",
            "message": "update auth",
            "proxy_not_human_eval": True,
            "structured_intent_plan": {"sample_id": "s1", "intent_count": 1, "is_multi_intent": False, "intents": []},
        },
        "paper_table_row": {
            "row_name": "m",
            "comparison_group": "g",
            "metrics": {
                "pairwise_f1": {
                    "value": 0.8,
                    "higher_is_better": True,
                    "is_proxy_metric": False,
                    "is_primary_metric": True,
                    "requires_human_eval": False,
                }
            },
        },
    }

    result = validate_cross_stage_contracts(rows)

    assert result["valid"] is True
    assert "stage1_prediction" in result["checks"]
    assert "renderer_input" in result["checks"]
