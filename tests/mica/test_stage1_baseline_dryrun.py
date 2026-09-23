from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_stage1_baseline_dryrun import main as baseline_main
from code.mica.runners.run_stage1_baseline_dryrun import run_stage1_baseline_dryrun


def _write_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "baseline_status": "dryrun_diagnostic_only",
                "baselines": ["all_one", "file_path", "random_gold_k", "size_heuristic_count"],
                "flat_classifier_baseline_status": "pending_advisor_confirmation",
                "no_slot_decoder_baseline_status": "pending_advisor_confirmation",
                "thresholds_are_not_final": True,
            }
        ),
        encoding="utf-8",
    )


def _write_edit_units(path: Path) -> None:
    write_jsonl(
        path,
        [
            {
                "sample_id": "s1",
                "gold_count": 2,
                "edit_units": [
                    {"unit_id": "u1", "file_path": "src/auth/a.py", "gold_intent_id": "i1"},
                    {"unit_id": "u2", "file_path": "docs/api.md", "gold_intent_id": "i2"},
                ],
            }
        ],
    )


def test_baseline_runner_requires_dry_run(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    edit_units = tmp_path / "edit_units.jsonl"
    _write_spec(spec)
    _write_edit_units(edit_units)
    with pytest.raises(ValueError):
        baseline_main(
            [
                "--baseline-spec",
                str(spec),
                "--edit-units-jsonl",
                str(edit_units),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_baseline_runner_is_deterministic_and_trains_nothing(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    edit_units = tmp_path / "edit_units.jsonl"
    _write_spec(spec)
    _write_edit_units(edit_units)

    result = run_stage1_baseline_dryrun(
        baseline_spec_path=spec,
        edit_units_jsonl=edit_units,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    manifest = read_json(tmp_path / "out" / "stage1_baseline_dryrun_manifest.json")
    predictions = read_jsonl(tmp_path / "out" / "baseline_predictions.jsonl")
    assert result["training_enabled"] is False
    assert manifest["flat_classifier_trained"] is False
    assert manifest["no_slot_decoder_trained"] is False
    assert manifest["thresholds_applied_to_pass_fail"] is False
    assert predictions
