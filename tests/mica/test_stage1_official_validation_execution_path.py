from __future__ import annotations

from code.mica.stages.stage1_official_validation import (
    build_stage1_official_summary,
    build_stage1_validation_dataset,
    evaluate_stage1_predictions,
    evaluate_stage1_with_baselines,
)


def _manifest_rows() -> list[dict]:
    return [
        {
            "sample_id": "s1",
            "split": "dev",
            "gold_count": 2,
            "edit_units": [
                {"unit_id": "u1", "gold_intent_id": "i1", "file_path": "src/auth.py", "changed_identifiers": ["auth"]},
                {"unit_id": "u2", "gold_intent_id": "i2", "file_path": "tests/auth_test.py", "changed_identifiers": ["auth"]},
            ],
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "gold_hunk_to_intent": {"h1": "i1", "h2": "i2"},
        }
    ]


def _prediction_rows() -> list[dict]:
    return [
        {
            "sample_id": "s1",
            "predicted_count": 2,
            "unit_to_slot": {"u1": "slot_1", "u2": "slot_2"},
            "active_slots": [{"slot_id": "slot_1"}, {"slot_id": "slot_2"}],
        }
    ]


def test_stage1_validation_execution_path_builds_dataset_and_metrics() -> None:
    dataset = build_stage1_validation_dataset(_manifest_rows(), _prediction_rows())
    metrics = evaluate_stage1_predictions(dataset["gold_rows"], dataset["prediction_rows"], {"report_oracle_k": True})
    baselines = evaluate_stage1_with_baselines(dataset["gold_rows"], dataset["prediction_rows"], {"baselines": ["all_one", "no_slot_decoder"]})
    summary = build_stage1_official_summary(dataset=dataset, prediction_metrics=metrics, baseline_metrics=baselines)

    assert dataset["row_count"] == 1
    assert metrics["predicted_k"]["mean_unit_accuracy"] == 1.0
    assert "all_one" in baselines["baselines"]
    assert summary["official_validation_executed"] is False
    assert summary["thresholds_applied_to_pass_fail"] is False
