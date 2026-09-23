from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json
from code.mica.runners.audit_future_stage2_inputs import audit_future_stage2_inputs, main as audit_main


def _freeze(path: Path) -> None:
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


def test_rejects_train_calibrate_and_pseudolabel_flags(tmp_path) -> None:
    freeze = tmp_path / "freeze.json"
    _freeze(freeze)

    for flag in ("--train", "--calibrate", "--pseudo-label"):
        with pytest.raises(ValueError, match="forbidden before official Stage 1 validation"):
            audit_main(
                [
                    "--stage1-freeze-report",
                    str(freeze),
                    "--output-root",
                    str(tmp_path / "out"),
                    "--audit-only",
                    flag,
                ]
            )


def test_guard_fields_remain_false(tmp_path) -> None:
    freeze = tmp_path / "freeze.json"
    hard_b = tmp_path / "hard_b.jsonl"
    m_weak = tmp_path / "m_weak.jsonl"
    _freeze(freeze)
    hard_b.write_text('{"sample_id":"hb1","repo":"r","sha":"a1","git_diff":"diff","split":"train"}\n', encoding="utf-8")
    m_weak.write_text('{"sample_id":"m1","repo":"r","sha":"b1","weak_label":1,"git_diff":"diff","split":"dev"}\n', encoding="utf-8")

    result = audit_future_stage2_inputs(
        stage1_freeze_report_path=freeze,
        hard_b_path=hard_b,
        m_weak_path=m_weak,
        output_root=tmp_path / "out",
        audit_only=True,
    )
    saved = read_json(tmp_path / "out" / "future_stage2_input_audit.json")

    assert result["stage2_training_enabled"] is False
    assert result["pseudo_label_enabled"] is False
    assert result["threshold_tuning_enabled"] is False
    assert saved["hard_b_summary"]["field_presence_summary"]["sample_id"] is True
    assert saved["m_weak_summary"]["field_presence_summary"]["weak_label"] is True
