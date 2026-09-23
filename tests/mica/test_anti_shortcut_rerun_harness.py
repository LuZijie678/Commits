from __future__ import annotations

import json

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_anti_shortcut_audit_dryrun import run_anti_shortcut_audit_dryrun


def test_anti_shortcut_harness_materializes_masked_views_and_rerun_request(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"audit_status": "rerun_ready", "model_command": ["python", "fake.py"]}), encoding="utf-8")
    write_jsonl(
        rows,
        [
            {
                "sample_id": "s1",
                "ood_slice": "shared-file",
                "edit_units": [
                    {
                        "unit_id": "u1",
                        "file_path": "src/auth/token.py",
                        "patch_text": "+ token = refresh(token)\n- token = token",
                        "changed_identifiers": ["token", "refresh"],
                    }
                ],
            }
        ],
    )

    result = run_anti_shortcut_audit_dryrun(
        audit_spec_path=spec,
        edit_units_jsonl=rows,
        output_root=tmp_path / "out",
        dry_run=True,
    )
    manifest = read_json(tmp_path / "out" / "anti_shortcut_audit_dryrun_manifest.json")
    rerun = read_json(tmp_path / "out" / "anti_shortcut_rerun_request.json")

    assert result["model_executed"] is False
    assert manifest["rerun_ready"] is True
    assert manifest["masked_variant_count"] == 3
    assert rerun["masked_variant_manifest"] == "anti_shortcut_masked_variant_manifest.json"
    assert read_jsonl(tmp_path / "out" / "path_masked_edit_units.jsonl")


def test_anti_shortcut_harness_rejects_execute_without_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    rows = tmp_path / "rows.jsonl"
    spec.write_text(json.dumps({"audit_status": "rerun_ready", "model_command": ["python", "fake.py"]}), encoding="utf-8")
    write_jsonl(rows, [{"sample_id": "s1", "edit_units": []}])

    with pytest.raises(ValueError, match="approval"):
        run_anti_shortcut_audit_dryrun(
            audit_spec_path=spec,
            edit_units_jsonl=rows,
            output_root=tmp_path / "out",
            dry_run=True,
            execute_model=True,
        )
