from __future__ import annotations

import torch

import pytest

from code.mica.selective_risk import build_dev_selective_calibration_artifact, compute_selective_risk


def test_selective_risk_reports_required_protocol_components() -> None:
    result = compute_selective_risk(
        count_probs=torch.tensor([0.1, 0.2, 0.7]),
        pb_count_probs=torch.tensor([0.7, 0.2, 0.1]),
        assignment_probs=torch.tensor([[0.45, 0.80], [0.40, 0.10], [0.05, 0.05]], dtype=torch.float32),
        null_assignment_probs=torch.tensor([0.10, 0.05], dtype=torch.float32),
        semantic_unit_mask=torch.tensor([True, True]),
        tau_fg=0.5,
        margin_delta=0.2,
    )

    assert result.risk_score.item() > 0.0
    assert set(result.components) >= {
        "capacity_saturation",
        "count_pb_js",
        "assignment_entropy",
        "residual_foreground_mass",
        "low_slot_margin",
        "foreground_plus_null_entropy",
    }
    assert result.diagnostics["final_test_tuning"] == "forbidden"


def test_selective_risk_masks_nonsemantic_units_for_residual_and_margin_terms() -> None:
    result = compute_selective_risk(
        count_probs=torch.tensor([0.9, 0.1]),
        pb_count_probs=torch.tensor([0.9, 0.1]),
        assignment_probs=torch.tensor([[0.95, 0.34], [0.03, 0.33]], dtype=torch.float32),
        semantic_unit_mask=torch.tensor([True, False]),
        tau_fg=0.5,
        margin_delta=0.2,
    )

    assert result.components["residual_foreground_mass"].item() == 0.0
    assert result.components["low_slot_margin"].item() == 0.0


def test_dev_selective_calibration_artifact_forbids_final_test_rows() -> None:
    with pytest.raises(ValueError, match="final-test rows are forbidden"):
        build_dev_selective_calibration_artifact([{"split": "final_test", "risk_score": 0.2}])


def test_dev_selective_calibration_artifact_freezes_dev_only_values() -> None:
    artifact = build_dev_selective_calibration_artifact(
        [
            {
                "split": "dev",
                "risk_score": 0.2,
                "risk_components": {
                    "capacity_saturation": 0.1,
                    "count_pb_js": 0.2,
                    "assignment_entropy": 0.3,
                    "residual_foreground_mass": 0.4,
                    "low_slot_margin": 0.5,
                },
            }
        ],
        target_coverage=1.0,
    )

    assert artifact["selection_split"] == "dev_only"
    assert artifact["final_test_tuning"] == "forbidden"
    assert artifact["threshold"]["status"] == "populated_from_dev_only"
    assert artifact["normalization"]["capacity_saturation"]["status"] == "populated_from_dev_only"


def test_dev_selective_calibration_artifact_keeps_missing_values_not_ready() -> None:
    artifact = build_dev_selective_calibration_artifact([{"split": "dev", "sample_id": "d1"}])

    assert artifact["status"] == "protocol_defined"
    assert artifact["values_status"] == "values_to_be_populated_by_dev_calibration_script"
    assert artifact["threshold"]["status"] == "values_to_be_populated"
    assert artifact["dev_row_count"] == 1
    assert artifact["dev_risk_score_count"] == 0
    assert artifact["paper_readiness"] == "not_final_paper_ready_until_dev_calibration_artifact_is_frozen"
