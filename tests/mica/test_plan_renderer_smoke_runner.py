from __future__ import annotations

from pathlib import Path

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_plan_renderer_smoke import main as smoke_main
from code.mica.runners.run_plan_renderer_smoke import run_plan_renderer_smoke


def _prediction_row() -> dict:
    return {
        "sample_id": "sample_1",
        "predicted_count": 1,
        "count_probs": {"1": 0.9},
        "active_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}}
        ],
        "all_slots": [
            {"slot_id": "slot_1", "existence_prob": 0.9, "edit_unit_ids": ["u1"], "hunk_ids": ["h1"], "confidence": 0.8, "assignment_scores": {"u1": 0.9}, "diagnostics": {}}
        ],
        "unit_to_slot": {"u1": "slot_1"},
        "unit_assignment_scores": {"u1": {"slot_1": 0.9}},
        "source": "predicted_plan",
        "metadata": {},
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/auth.py", "hunk_id": "h1", "file_role": "source", "changed_identifiers": ["auth"], "added_lines": ["auth = 1"]}
        ],
    }


def test_smoke_runner_requires_smoke_only_flag(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row()])
    with pytest.raises(ValueError):
        smoke_main(
            [
                "--prediction-jsonl",
                str(prediction_jsonl),
                "--output-root",
                str(tmp_path / "out"),
                "--mode",
                "predicted_plan",
            ]
        )


def test_smoke_runner_requires_prediction_jsonl(tmp_path) -> None:
    with pytest.raises(SystemExit):
        smoke_main(
            [
                "--output-root",
                str(tmp_path / "out"),
                "--mode",
                "predicted_plan",
                "--smoke-only",
            ]
        )


def test_smoke_runner_does_not_train_and_writes_manifest_flags(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_root = tmp_path / "out"
    write_jsonl(prediction_jsonl, [_prediction_row()])

    result = run_plan_renderer_smoke(
        prediction_jsonl=prediction_jsonl,
        output_root=output_root,
        mode="predicted_plan",
        smoke_only=True,
    )

    manifest = read_json(output_root / "smoke_run_manifest.json")
    assert result["training_enabled"] is False
    assert manifest["smoke_only"] is True
    assert manifest["training_enabled"] is False
    assert manifest["stage2_training_enabled"] is False
    assert manifest["generation_training_enabled"] is False
    assert manifest["retrieval_enabled"] is False
    assert manifest["verifier_enabled"] is False
    assert manifest["api_calls_enabled"] is False
    assert read_jsonl(output_root / "plans.jsonl")
    assert read_jsonl(output_root / "rendered_messages.jsonl")


def test_smoke_runner_source_does_not_import_generation_pilot() -> None:
    source = Path("code/mica/runners/run_plan_renderer_smoke.py").read_text(encoding="utf-8")
    assert "run_generation_pilot" not in source
