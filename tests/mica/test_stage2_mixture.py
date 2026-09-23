from __future__ import annotations

import pytest

from code.mica.data.stage2_mixture import build_stage2_mixture_manifest, validate_stage2_data_boundaries


def _spec() -> dict:
    return {
        "mixture_weights": {
            "strict_replay": 0.55,
            "hard_b": 0.30,
            "m_weak": 0.15,
        }
    }


def test_validate_stage2_data_boundaries_rejects_m_final_test() -> None:
    result = validate_stage2_data_boundaries(
        _spec(),
        {
            "strict_replay": [{"sample_id": "s1"}],
            "m_final_test": [{"sample_id": "mf1", "split": "test"}],
        },
    )

    assert any("m_final_test_forbidden" in error for error in result["errors"])


def test_validate_stage2_data_boundaries_rejects_hard_b_test() -> None:
    result = validate_stage2_data_boundaries(
        _spec(),
        {
            "strict_replay": [{"sample_id": "s1"}],
            "hard_b_test": [{"sample_id": "hb1", "split": "test"}],
        },
    )

    assert any("hard_b_test_forbidden" in error for error in result["errors"])


def test_build_stage2_mixture_manifest_marks_m_weak_as_censored() -> None:
    manifest = build_stage2_mixture_manifest(
        _spec(),
        {
            "strict_replay": [{"sample_id": "s1"}],
            "hard_b_train": [{"sample_id": "hb1"}],
            "hard_b_dev": [{"sample_id": "hb2"}],
            "m_weak_train": [{"sample_id": "m1"}],
            "m_weak_dev": [{"sample_id": "m2"}],
        },
    )

    assert manifest["stage2_training_executed"] is False
    assert manifest["dataset_roles"]["m_weak"]["supervision"] == "censored_k_ge_2"
    assert manifest["m_final_test_used_for_training"] is False


def test_build_stage2_mixture_manifest_checks_weight_sum() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        build_stage2_mixture_manifest(
            {"mixture_weights": {"strict_replay": 0.50, "hard_b": 0.30, "m_weak": 0.30}},
            {"strict_replay": [{"sample_id": "s1"}]},
        )


def test_build_stage2_mixture_manifest_allows_optional_m_align_calib() -> None:
    manifest = build_stage2_mixture_manifest(
        {
            "mixture_weights": {
                "strict_replay": 0.50,
                "hard_b": 0.25,
                "m_weak": 0.15,
                "m_align_calib": 0.10,
            }
        },
        {
            "strict_replay": [{"sample_id": "s1"}],
            "hard_b_train": [{"sample_id": "hb1"}],
            "hard_b_dev": [{"sample_id": "hb2"}],
            "m_weak_train": [{"sample_id": "m1"}],
            "m_weak_dev": [{"sample_id": "m2"}],
        },
    )

    assert manifest["dataset_roles"]["m_align_calib"]["optional"] is True
