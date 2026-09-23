from __future__ import annotations

import json
import runpy
import sys

import pytest

from code.mica.io_utils import read_jsonl, write_jsonl
from code.mica.runners.export_consumer_plans import build_arg_parser, export_consumer_plans, main


def _prediction_row(
    sample_id: str,
    *,
    include_background_record: bool = True,
    include_release_decision: bool = True,
    include_unit_records: bool = True,
    include_assignment_scores: bool = True,
    include_explicit_background_units: bool = True,
    include_slot_null_assignment: bool = True,
) -> dict[str, object]:
    metadata: dict[str, object] = {"commit_message": "forbidden commit message input"}
    if include_release_decision:
        metadata["release_decision"] = "decompose"
    if include_background_record:
        metadata["background_unit_records"] = [
            {
                "unit_id": "u_lock",
                "hunk_id": "h_u_lock",
                "file_path": "package-lock.json",
                "file_role": "lockfile",
                "changed_identifiers": ["lockfile"],
                "patch_operation": "update",
                "background_reason": "lockfile",
                "background_confidence": 0.99,
            }
        ]
    if include_explicit_background_units:
        metadata["background_units"] = ["u_lock"]

    assignments = {"u_src": "slot_auth"}
    if include_slot_null_assignment:
        assignments["u_lock"] = "slot_null"

    assignment_scores = {"u_src": {"slot_auth": 0.95}}
    if include_assignment_scores and include_slot_null_assignment:
        assignment_scores["u_lock"] = {"slot_null": 0.99}
    if include_assignment_scores and not include_slot_null_assignment:
        assignment_scores["u_lock"] = {"slot_auth": 0.01}

    row: dict[str, object] = {
        "sample_id": sample_id,
        "k_hat": 1,
        "count_probs": {"1": 0.96},
        "slot_exist": {"slot_auth": 0.95, "slot_null": 0.99},
        "assignments": assignments,
        "subject": "forbidden legacy subject",
        "body": "forbidden legacy body",
        "metadata": metadata,
    }
    if include_assignment_scores:
        row["assignment_scores"] = assignment_scores
    if include_unit_records:
        row["unit_records"] = [
            {
                "unit_id": "u_src",
                "hunk_id": "h_u_src",
                "file_path": "src/auth/token.py",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ validate_token(token)"],
                "deleted_lines": ["- token"],
                "changed_identifiers": ["token", "validate_token"],
                "metadata": {"enclosing_symbol_name": "validate_token"},
            },
            {
                "unit_id": "u_lock",
                "hunk_id": "h_u_lock",
                "file_path": "package-lock.json",
                "file_role": "lockfile",
                "language": "json",
                "patch_text": "@@",
                "added_lines": ["+ lockfile"],
                "deleted_lines": [],
                "changed_identifiers": ["lockfile"],
                "metadata": {},
            },
        ]
    return row


def test_export_consumer_plans_writes_canonical_rows_and_error_rows(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "consumer_plan_errors.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row("sample_ok"), {"sample_id": "broken"}])

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        strict=False,
    )

    exported = read_jsonl(output_jsonl)
    errors = read_jsonl(error_jsonl)

    assert summary["sample_counts"]["exported"] == 1
    assert summary["sample_counts"]["errors"] == 1
    assert exported[0]["schema_version"].startswith("mica-consumer-plan-")
    assert exported[0]["background_contract"]["evidence_complete"] is True
    assert exported[0]["source_metadata"]["adapter_format"] == "legacy_aliases"
    assert "commit_message" not in exported[0]["source_metadata"]
    assert exported[0]["intents"][0]["object"] is None
    assert errors[0]["error_type"] == "schema_validation_error"


def test_export_consumer_plans_validate_only_writes_no_outputs(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    aggregate_error_jsonl = tmp_path / "errors.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row("sample_validate_only")])

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=aggregate_error_jsonl,
        validate_only=True,
    )

    assert summary["validate_only"] is True
    assert output_jsonl.exists() is False
    assert aggregate_error_jsonl.exists() is False


def test_export_consumer_plans_protects_existing_outputs(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row("sample_exists")])
    output_jsonl.write_text("already here\n", encoding="utf-8")

    try:
        export_consumer_plans(
            prediction_jsonl=prediction_jsonl,
            output_jsonl=output_jsonl,
            error_jsonl=error_jsonl,
        )
    except FileExistsError as exc:
        assert "consumer_plans.jsonl" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_export_consumer_plans_leniently_records_malformed_json_lines(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    prediction_jsonl.write_text(
        "\n".join(
            [
                '{"sample_id":"sample_a","k_hat":1,"assignments":{"u1":"slot_1"},"unit_records":[{"unit_id":"u1","file_path":"src/a.py"}]}',
                '{"sample_id":"broken",',
                '{"sample_id":"sample_b","k_hat":1,"assignments":{"u2":"slot_1"},"unit_records":[{"unit_id":"u2","file_path":"src/b.py"}]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        strict=False,
    )

    exported = read_jsonl(output_jsonl)
    errors = read_jsonl(error_jsonl)
    assert [row["sample_id"] for row in exported] == ["sample_a", "sample_b"]
    assert summary["sample_counts"]["errors"] == 1
    assert errors[0]["error_type"] == "invalid_input"


def test_export_consumer_plans_argparse_help_smoke() -> None:
    assert "--prediction-jsonl" in build_arg_parser().format_help()
    assert "--edit-units-jsonl-or-manifest" in build_arg_parser().format_help()
    assert "--review-ready" in build_arg_parser().format_help()


def test_export_consumer_plans_main_returns_non_zero_when_input_missing(tmp_path) -> None:
    exit_code = main(
        [
            "--prediction-jsonl",
            str(tmp_path / "missing.jsonl"),
            "--output-jsonl",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert exit_code != 0


def test_export_consumer_plans_main_validate_only_succeeds(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row("sample_cli_validate_only")])

    exit_code = main(
        [
            "--prediction-jsonl",
            str(prediction_jsonl),
            "--output-jsonl",
            str(tmp_path / "out.jsonl"),
            "--validate-only",
        ]
    )

    assert exit_code == 0


def test_export_consumer_plans_review_ready_requires_release_decision(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    write_jsonl(
        prediction_jsonl,
        [_prediction_row("sample_missing_decision", include_release_decision=False)],
    )

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        review_ready=True,
        strict=False,
    )

    assert summary["sample_counts"]["exported"] == 0
    assert summary["sample_counts"]["errors"] == 1
    assert summary["missing_release_decision_count"] == 1
    assert read_jsonl(output_jsonl) == []
    errors = read_jsonl(error_jsonl)
    assert errors[0]["error_type"] == "schema_validation_error"
    assert "missing_release_decision" in errors[0]["message"]


def test_export_consumer_plans_review_ready_joins_external_edit_units(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    edit_units_jsonl = tmp_path / "edit_units.jsonl"
    write_jsonl(
        prediction_jsonl,
        [_prediction_row("sample_join", include_unit_records=False)],
    )
    write_jsonl(
        edit_units_jsonl,
        [
            {
                "sample_id": "sample_join",
                "edit_units": [
                    {
                        "unit_id": "u_src",
                        "hunk_id": "h_u_src",
                        "file_path": "src/auth/token.py",
                        "file_role": "source",
                        "language": "python",
                        "patch_text": "@@",
                        "added_lines": ["+ validate_token(token)"],
                        "deleted_lines": ["- token"],
                        "changed_identifiers": ["token", "validate_token"],
                        "metadata": {"enclosing_symbol_name": "validate_token"},
                    },
                    {
                        "unit_id": "u_lock",
                        "hunk_id": "h_u_lock",
                        "file_path": "package-lock.json",
                        "file_role": "lockfile",
                        "language": "json",
                        "patch_text": "@@",
                        "added_lines": ["+ lockfile"],
                        "deleted_lines": [],
                        "changed_identifiers": ["lockfile"],
                        "metadata": {},
                    },
                ],
            }
        ],
    )

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        edit_units_jsonl_or_manifest=edit_units_jsonl,
        review_ready=True,
        strict=False,
    )

    exported = read_jsonl(output_jsonl)
    assert summary["sample_counts"]["exported"] == 1
    assert summary["review_ready_exported_count"] == 1
    assert summary["joined_from_external_edit_units_count"] == 1
    assert summary["embedded_edit_units_count"] == 0
    assert exported[0]["background_contract"]["evidence_complete"] is True
    assert exported[0]["source_metadata"]["adapter_format"] == "legacy_aliases"


def test_export_consumer_plans_review_ready_background_incomplete_is_not_counted_ready(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "consumer_plans.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    write_jsonl(
        prediction_jsonl,
        [
            _prediction_row(
                "sample_bg_incomplete",
                include_background_record=False,
                include_slot_null_assignment=False,
                include_explicit_background_units=True,
            )
        ],
    )

    summary = export_consumer_plans(
        prediction_jsonl=prediction_jsonl,
        output_jsonl=output_jsonl,
        error_jsonl=error_jsonl,
        review_ready=True,
        strict=False,
    )

    exported = read_jsonl(output_jsonl)
    assert summary["sample_counts"]["exported"] == 1
    assert summary["review_ready_exported_count"] == 0
    assert summary["background_contract_incomplete_count"] == 1
    assert summary["review_ready_blocker_counts"] == {"background_evidence_incomplete": 1}
    assert summary["blocked_sample_count"] == 1
    assert summary["blocked_samples_preview"] == [
        {
            "sample_id": "sample_bg_incomplete",
            "blockers": ["background_evidence_incomplete"],
        }
    ]
    assert exported[0]["background_contract"]["evidence_incomplete"] is True


def test_export_consumer_plans_main_review_ready_lenient_succeeds(tmp_path) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "out.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    prediction_jsonl.write_text(
        json.dumps(_prediction_row("sample_ok")) + "\n" + '{"sample_id":"broken",\n',
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--prediction-jsonl",
            str(prediction_jsonl),
            "--output-jsonl",
            str(output_jsonl),
            "--error-jsonl",
            str(error_jsonl),
            "--review-ready",
            "--lenient",
        ]
    )

    assert exit_code == 0


def test_export_consumer_plans_module_main_runs_with_external_edit_units(tmp_path, monkeypatch) -> None:
    prediction_jsonl = tmp_path / "predictions.jsonl"
    output_jsonl = tmp_path / "out.jsonl"
    error_jsonl = tmp_path / "errors.jsonl"
    edit_units_jsonl = tmp_path / "edit_units.jsonl"
    write_jsonl(prediction_jsonl, [_prediction_row("sample_join", include_unit_records=False)])
    write_jsonl(
        edit_units_jsonl,
        [
            {
                "sample_id": "sample_join",
                "edit_units": [
                    {
                        "unit_id": "u_src",
                        "hunk_id": "h_u_src",
                        "file_path": "src/auth/token.py",
                        "file_role": "source",
                        "language": "python",
                        "patch_text": "@@",
                        "added_lines": ["+ validate_token(token)"],
                        "deleted_lines": ["- token"],
                        "changed_identifiers": ["token", "validate_token"],
                        "metadata": {"enclosing_symbol_name": "validate_token"},
                    },
                    {
                        "unit_id": "u_lock",
                        "hunk_id": "h_u_lock",
                        "file_path": "package-lock.json",
                        "file_role": "lockfile",
                        "language": "json",
                        "patch_text": "@@",
                        "added_lines": ["+ lockfile"],
                        "deleted_lines": [],
                        "changed_identifiers": ["lockfile"],
                        "metadata": {},
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_consumer_plans.py",
            "--prediction-jsonl",
            str(prediction_jsonl),
            "--output-jsonl",
            str(output_jsonl),
            "--error-jsonl",
            str(error_jsonl),
            "--edit-units-jsonl-or-manifest",
            str(edit_units_jsonl),
            "--review-ready",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("code.mica.runners.export_consumer_plans", run_name="__main__")

    assert excinfo.value.code == 0
