from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.runners.audit_future_stage2_inputs import audit_future_stage2_inputs, main as stage2_audit_main


def _write_stage1_freeze_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "next_action": "run_official_stage1_validation",
            }
        ),
        encoding="utf-8",
    )


def test_stage2_audit_runner_requires_audit_only_flag(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    _write_stage1_freeze_report(freeze)
    with pytest.raises(ValueError):
        stage2_audit_main(
            [
                "--stage1-freeze-report",
                str(freeze),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_stage2_audit_defaults_to_disabled_training_and_requires_stage1_validation(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    _write_stage1_freeze_report(freeze)

    result = audit_future_stage2_inputs(
        stage1_freeze_report_path=freeze,
        output_root=tmp_path / "out",
        audit_only=True,
    )

    assert result["stage2_training_enabled"] is False
    assert result["stage2_preparation_only"] is True
    assert result["requires_stage1_official_validation"] is True
    assert result["pseudo_label_generated"] is False
    assert result["threshold_tuning_performed"] is False
    assert result["training_invoked"] is False


def test_stage2_audit_does_not_generate_pseudolabels_or_train_with_optional_inputs(tmp_path: Path) -> None:
    freeze = tmp_path / "freeze.json"
    hard_b = tmp_path / "hard_b.jsonl"
    m_weak = tmp_path / "m_weak.jsonl"
    _write_stage1_freeze_report(freeze)
    hard_b.write_text('{"sample_id":"hb1"}\n', encoding="utf-8")
    m_weak.write_text('{"sample_id":"m1"}\n', encoding="utf-8")

    result = audit_future_stage2_inputs(
        stage1_freeze_report_path=freeze,
        hard_b_path=hard_b,
        m_weak_path=m_weak,
        output_root=tmp_path / "out",
        audit_only=True,
    )

    assert result["hard_b_loaded"] is True
    assert result["m_weak_loaded"] is True
    assert result["pseudo_label_generated"] is False
    assert result["training_invoked"] is False
    assert result["threshold_tuning_performed"] is False
