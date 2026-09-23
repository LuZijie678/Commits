from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from code.mica.eval.stage1_unit_accuracy_supplement import (
    build_stage1_official_status_revision,
    build_stage1_unit_accuracy_observability_audit,
    build_stage1_unit_accuracy_supplement,
    compute_unit_accuracy_gain_from_frozen_rows,
)
from code.mica.io_utils import read_json, write_json, write_jsonl
from code.mica.runners.run_stage1_unit_accuracy_supplement import run_stage1_unit_accuracy_supplement


def _gold_rows() -> list[dict]:
    return [
        {
            "sample_id": "k1",
            "gold_count": 1,
            "gold_unit_to_intent": {"u1": "intent_0"},
            "edit_units": [
                {
                    "unit_id": "u1",
                    "hunk_id": "h1",
                    "file_path": "src/auth.py",
                    "file_role": "source",
                }
            ],
        },
        {
            "sample_id": "k2",
            "gold_count": 2,
            "gold_unit_to_intent": {"u2": "intent_0", "u3": "intent_1"},
            "edit_units": [
                {
                    "unit_id": "u2",
                    "hunk_id": "h2",
                    "file_path": "src/token.py",
                    "file_role": "source",
                },
                {
                    "unit_id": "u3",
                    "hunk_id": "h3",
                    "file_path": "tests/token_test.py",
                    "file_role": "test",
                },
            ],
        },
    ]


def _prediction_rows() -> list[dict]:
    return [
        {
            "sample_id": "k1",
            "predicted_count": 1,
            "unit_to_slot": {"u1": "slot_a"},
        },
        {
            "sample_id": "k2",
            "predicted_count": 2,
            "unit_to_slot": {"u2": "slot_b", "u3": "slot_a"},
        },
    ]


def test_compute_unit_accuracy_gain_from_frozen_rows_recovers_sample_mean_gain() -> None:
    result = compute_unit_accuracy_gain_from_frozen_rows(
        gold_rows=_gold_rows(),
        prediction_rows=_prediction_rows(),
    )

    assert result["eligible_samples"] == 2
    assert result["eligible_units"] == 3
    assert result["mica_unit_accuracy"] == 1.0
    assert result["all_one_baseline_accuracy"] == 0.75
    assert result["observed_value"] == 0.25


def test_compute_unit_accuracy_gain_excludes_uncertain_shared_and_mixed_units() -> None:
    rows = [
        {
            "sample_id": "mixed",
            "gold_count": 2,
            "gold_unit_to_intent": {
                "u1": "intent_0",
                "u2": "intent_0",
                "u3": "intent_1",
                "u4": "intent_1",
            },
            "uncertain_units": ["u2"],
            "shared_support_units": ["u3"],
            "mixed_units": ["u4"],
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/a.py", "file_role": "source"},
                {"unit_id": "u2", "file_path": "src/b.py", "file_role": "source"},
                {"unit_id": "u3", "file_path": "tests/b.py", "file_role": "test"},
                {"unit_id": "u4", "file_path": "docs/b.md", "file_role": "docs"},
            ],
        }
    ]
    predictions = [{"sample_id": "mixed", "predicted_count": 2, "unit_to_slot": {"u1": "slot_a", "u2": "slot_a", "u3": "slot_b", "u4": "slot_b"}}]

    result = compute_unit_accuracy_gain_from_frozen_rows(gold_rows=rows, prediction_rows=predictions)

    assert result["eligible_samples"] == 1
    assert result["eligible_units"] == 1
    assert result["excluded_units"] == 3
    assert result["observed_value"] == 0.0


def test_compute_unit_accuracy_gain_returns_zero_denominator_when_all_units_are_excluded() -> None:
    rows = [
        {
            "sample_id": "uncertain_only",
            "gold_count": 1,
            "gold_unit_to_intent": {"u1": "intent_0"},
            "uncertain_units": ["u1"],
            "edit_units": [{"unit_id": "u1", "file_path": "src/auth.py", "file_role": "source"}],
        }
    ]
    predictions = [{"sample_id": "uncertain_only", "predicted_count": 1, "unit_to_slot": {"u1": "slot_a"}}]

    result = compute_unit_accuracy_gain_from_frozen_rows(gold_rows=rows, prediction_rows=predictions)

    assert result["eligible_samples"] == 0
    assert result["observed_value"] is None
    assert result["null_reason"] == "no_eligible_samples:no_eligible_gold_units_after_exclusion"


def test_observability_audit_classifies_missing_metric_as_computation_bug(tmp_path: Path) -> None:
    official_manifest = tmp_path / "official_manifest.json"
    predictions = tmp_path / "predictions.jsonl"
    aggregate = tmp_path / "aggregate.json"
    manifest = tmp_path / "final_test_manifest.json"
    thresholds = tmp_path / "thresholds.json"
    official_result = tmp_path / "official_result.json"

    write_json(official_manifest, {"run_id": "stage1_official_validation_20260723T091921Z", "paper_ready": False})
    write_json(
        aggregate,
        {
            "official_gate_results": {
                "unit_accuracy_gain_over_all_one": {
                    "bound_name": "unit_accuracy_gain_over_all_one_min",
                    "threshold": 0.03,
                    "observed": None,
                    "passed": False,
                }
            }
        },
    )
    write_json(manifest, {"rows": _gold_rows()})
    write_json(thresholds, {"unit_accuracy_gain_over_all_one_min": 0.03})
    write_json(
        official_result,
        {
            "run_id": "stage1_official_validation_20260723T091921Z",
            "checkpoint_sha256": "ckpt",
            "threshold_version": "frozen_dev_thresholds_v1",
            "kmax_decision_version": "stage1-kmax-v1",
            "paper_ready": False,
        },
    )
    write_jsonl(predictions, _prediction_rows())

    audit = build_stage1_unit_accuracy_observability_audit(
        official_run_id="stage1_official_validation_20260723T091921Z",
        official_manifest_path=official_manifest,
        predictions_path=predictions,
        aggregate_metrics_path=aggregate,
        final_test_manifest_path=manifest,
        threshold_spec_path=thresholds,
        official_result_path=official_result,
        checkpoint_sha256="ckpt",
    )

    assert audit["root_cause_class"] == "metric_computation_bug"
    assert audit["recomputation_allowed"] is True
    assert audit["observed_value"] == 0.25
    assert audit["eligible_samples"] == 2
    assert audit["eligible_units"] == 3


def test_observability_audit_reports_missing_prediction_fields(tmp_path: Path) -> None:
    official_manifest = tmp_path / "official_manifest.json"
    predictions = tmp_path / "predictions.jsonl"
    aggregate = tmp_path / "aggregate.json"
    manifest = tmp_path / "final_test_manifest.json"
    thresholds = tmp_path / "thresholds.json"
    official_result = tmp_path / "official_result.json"

    write_json(official_manifest, {"run_id": "stage1_official_validation_20260723T091921Z"})
    write_json(aggregate, {"official_gate_results": {"unit_accuracy_gain_over_all_one": {"observed": None}}})
    write_json(manifest, {"rows": _gold_rows()})
    write_json(thresholds, {"unit_accuracy_gain_over_all_one_min": 0.03})
    write_json(
        official_result,
        {
            "run_id": "stage1_official_validation_20260723T091921Z",
            "checkpoint_sha256": "ckpt",
            "threshold_version": "frozen_dev_thresholds_v1",
            "kmax_decision_version": "stage1-kmax-v1",
        },
    )
    write_jsonl(predictions, [{"sample_id": "k1", "predicted_count": 1}])

    audit = build_stage1_unit_accuracy_observability_audit(
        official_run_id="stage1_official_validation_20260723T091921Z",
        official_manifest_path=official_manifest,
        predictions_path=predictions,
        aggregate_metrics_path=aggregate,
        final_test_manifest_path=manifest,
        threshold_spec_path=thresholds,
        official_result_path=official_result,
        checkpoint_sha256="ckpt",
    )

    assert "prediction.unit_to_slot" in audit["missing_input_fields"]
    assert audit["root_cause_class"] == "metric_inputs_missing"
    assert audit["recomputation_allowed"] is False


def test_supplement_and_status_revision_do_not_mutate_original_result(tmp_path: Path) -> None:
    official_result = {
        "run_id": "stage1_official_validation_20260723T091921Z",
        "checkpoint_sha256": "ckpt",
        "threshold_version": "frozen_dev_thresholds_v1",
        "kmax_decision_version": "stage1-kmax-v1",
        "paper_ready": False,
    }
    official_result_before = deepcopy(official_result)
    observability_audit = {
        "root_cause_class": "metric_computation_bug",
        "eligible_samples": 2,
        "eligible_units": 3,
        "excluded_samples": 0,
        "excluded_units": 0,
        "observed_value": 0.25,
        "denominator": 2,
        "numerator": {
            "mica_unit_accuracy_sum": 2.0,
            "all_one_unit_accuracy_sum": 1.5,
            "gain_sum_difference": 0.5,
        },
        "source_artifact_hashes": {
            "official_manifest": "a",
            "predictions": "b",
            "aggregate_metrics": "c",
            "final_test_manifest": "d",
            "threshold_spec": "e",
            "official_result": "f",
        },
    }
    threshold_spec = {"unit_accuracy_gain_over_all_one_min": 0.03}

    supplement = build_stage1_unit_accuracy_supplement(
        official_result=official_result,
        observability_audit=observability_audit,
        threshold_spec=threshold_spec,
        computation_git_sha="85ed7bb0cb2643ea98e0c1fee55c25d7e08e2533",
    )
    supplement_path = tmp_path / "supplement.json"
    write_json(supplement_path, supplement)
    revision = build_stage1_official_status_revision(
        official_result=official_result,
        supplement_record=supplement,
        supplement_record_path=str(supplement_path),
        computation_git_sha="85ed7bb0cb2643ea98e0c1fee55c25d7e08e2533",
    )

    assert official_result == official_result_before
    assert supplement["status"] == "metric_recovered_from_frozen_artifacts"
    assert revision["paper_ready"] is True
    assert revision["status"] == "paper_ready"


def test_supplement_runner_writes_outputs_without_mutating_predictions(tmp_path: Path) -> None:
    official_result = tmp_path / "official_result.json"
    official_manifest = tmp_path / "official_manifest.json"
    predictions = tmp_path / "predictions.jsonl"
    aggregate = tmp_path / "aggregate.json"
    manifest = tmp_path / "final_test_manifest.json"
    thresholds = tmp_path / "thresholds.json"
    audit_output = tmp_path / "audit.json"
    supplement_output = tmp_path / "supplement.json"
    revision_output = tmp_path / "revision.json"

    write_json(
        official_result,
        {
            "run_id": "stage1_official_validation_20260723T091921Z",
            "checkpoint_sha256": "ckpt",
            "threshold_version": "frozen_dev_thresholds_v1",
            "kmax_decision_version": "stage1-kmax-v1",
            "paper_ready": False,
        },
    )
    write_json(official_manifest, {"run_id": "stage1_official_validation_20260723T091921Z", "paper_ready": False})
    write_json(
        aggregate,
        {
            "official_gate_results": {
                "unit_accuracy_gain_over_all_one": {
                    "bound_name": "unit_accuracy_gain_over_all_one_min",
                    "threshold": 0.03,
                    "observed": None,
                    "passed": False,
                }
            }
        },
    )
    write_json(manifest, {"rows": _gold_rows()})
    write_json(thresholds, {"unit_accuracy_gain_over_all_one_min": 0.03})
    write_jsonl(predictions, _prediction_rows())
    original_prediction_bytes = predictions.read_bytes()

    result = run_stage1_unit_accuracy_supplement(
        official_result_path=official_result,
        official_manifest_path=official_manifest,
        predictions_path=predictions,
        aggregate_metrics_path=aggregate,
        final_test_manifest_path=manifest,
        threshold_spec_path=thresholds,
        checkpoint_sha256="ckpt",
        computation_git_sha="85ed7bb0cb2643ea98e0c1fee55c25d7e08e2533",
        observability_audit_output_path=audit_output,
        supplement_output_path=supplement_output,
        status_revision_output_path=revision_output,
    )

    assert predictions.read_bytes() == original_prediction_bytes
    assert result["supplement_record"]["absolute_gain"] == 0.25
    assert read_json(audit_output)["root_cause_class"] == "metric_computation_bug"
    assert read_json(revision_output)["paper_ready"] is True
