from __future__ import annotations

import json

import pytest

from code.mica.io_utils import read_json
from code.mica.runners.run_stage1_baselines import run_stage1_baselines


def test_stage1_baselines_runner_supports_dry_run_only_without_execute(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    manifest = tmp_path / "manifest.json"
    spec.write_text(
        json.dumps(
            {
                "baseline_status": "candidate",
                "baselines": ["flat_classifier", "no_slot_decoder"],
                "advisor_stage1_baselines_approved": False,
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "sample_id": "s1",
                        "gold_count": 2,
                        "edit_units": [
                            {"unit_id": "u1", "file_path": "src/a.py", "gold_intent_id": "i1", "changed_identifiers": ["auth"]},
                            {"unit_id": "u2", "file_path": "docs/a.md", "gold_intent_id": "i2", "changed_identifiers": ["docs"]},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_stage1_baselines(
        baseline_spec_path=spec,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    saved = read_json(tmp_path / "out" / "stage1_baselines_manifest.json")
    assert result["training_executed"] is False
    assert saved["execute_requested"] is False


def test_stage1_baselines_runner_rejects_execute_without_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    manifest = tmp_path / "manifest.json"
    spec.write_text(json.dumps({"baselines": ["flat_classifier"], "advisor_stage1_baselines_approved": False}), encoding="utf-8")
    manifest.write_text(json.dumps({"rows": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="advisor approval"):
        run_stage1_baselines(
            baseline_spec_path=spec,
            manifest_path=manifest,
            output_root=tmp_path / "out",
            execute=True,
        )


def test_stage1_baselines_runner_rejects_message_utility_baselines(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    manifest = tmp_path / "manifest.json"
    spec.write_text(
        json.dumps(
            {
                "baselines": ["flat_classifier", "llm_prompting", "direct_generation"],
                "advisor_stage1_baselines_approved": False,
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(json.dumps({"rows": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="message utility baselines"):
        run_stage1_baselines(
            baseline_spec_path=spec,
            manifest_path=manifest,
            output_root=tmp_path / "out",
            dry_run=True,
        )
