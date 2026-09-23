from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.eval.anti_shortcut_audit import (
    audit_shortcut_readiness,
    build_diff_marker_masked_view,
    build_identifier_masked_view,
    build_path_masked_view,
)
from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_anti_shortcut_audit_dryrun import main as audit_main
from code.mica.runners.run_anti_shortcut_audit_dryrun import run_anti_shortcut_audit_dryrun


def _units() -> list[dict]:
    return [
        {
            "unit_id": "u1",
            "file_path": "src/auth/token.py",
            "patch_text": "+ token = refresh(token)\n- token = token",
            "changed_identifiers": ["token", "refresh"],
        }
    ]


def test_masked_views_remove_paths_markers_and_identifiers() -> None:
    path_masked = build_path_masked_view(_units())
    diff_masked = build_diff_marker_masked_view(_units())
    identifier_masked = build_identifier_masked_view(_units())

    assert path_masked[0]["file_path"] != "src/auth/token.py"
    assert "+" not in diff_masked[0]["patch_text"]
    assert "-" not in diff_masked[0]["patch_text"]
    assert "token" not in identifier_masked[0]["changed_identifiers"]


def test_shortcut_audit_readiness_does_not_make_conclusion() -> None:
    summary = audit_shortcut_readiness([{"sample_id": "s1", "edit_units": _units()}])
    assert summary["shortcut_conclusion_made"] is False
    assert summary["readiness_checked"] is True


def test_runner_requires_dry_run(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    edit_units = tmp_path / "edit_units.jsonl"
    spec.write_text(json.dumps({"audit_status": "dryrun_readiness_only"}), encoding="utf-8")
    write_jsonl(edit_units, [{"sample_id": "s1", "edit_units": _units()}])

    with pytest.raises(ValueError):
        audit_main(
            [
                "--audit-spec",
                str(spec),
                "--edit-units-jsonl",
                str(edit_units),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_runner_writes_manifest_without_executing_model(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    edit_units = tmp_path / "edit_units.jsonl"
    spec.write_text(
        json.dumps(
            {
                "audit_status": "dryrun_readiness_only",
                "masking_modes": ["path_masked", "marker_masked", "identifier_masked", "template_subject_masked", "file_order_permuted"],
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(edit_units, [{"sample_id": "s1", "edit_units": _units()}])

    result = run_anti_shortcut_audit_dryrun(
        audit_spec_path=spec,
        edit_units_jsonl=edit_units,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    manifest = read_json(tmp_path / "out" / "anti_shortcut_audit_dryrun_manifest.json")
    variant_manifest = read_json(tmp_path / "out" / "anti_shortcut_masked_variant_manifest.json")
    readiness = read_json(tmp_path / "out" / "anti_shortcut_readiness_summary.json")
    assert result["model_executed"] is False
    assert manifest["training_executed"] is False
    assert manifest["shortcut_conclusion_made"] is False
    assert manifest["masked_variant_count"] == 5
    assert readiness["masking_modes_materialized"] == ["path_masked", "marker_masked", "identifier_masked", "template_subject_masked", "file_order_permuted"]
    assert {variant["masking_mode"] for variant in variant_manifest["variants"]} == {"path_masked", "marker_masked", "identifier_masked", "template_subject_masked", "file_order_permuted"}
    assert read_jsonl(tmp_path / "out" / "path_masked_edit_units.jsonl")
    assert read_jsonl(tmp_path / "out" / "marker_masked_edit_units.jsonl")
    assert read_jsonl(tmp_path / "out" / "diff_marker_masked_edit_units.jsonl")
    assert read_jsonl(tmp_path / "out" / "template_subject_masked_edit_units.jsonl")
    assert read_jsonl(tmp_path / "out" / "file_order_permuted_edit_units.jsonl")
