from __future__ import annotations

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_consumer_evaluation import build_arg_parser, main, run_consumer_evaluation


def _consumer_plan_row(
    sample_id: str,
    *,
    decision: str = "decompose",
    weak_target: bool = False,
    include_background_record: bool = True,
) -> dict[str, object]:
    if decision != "decompose":
        return {
            "sample_id": sample_id,
            "decision": decision,
            "predicted_k": 0,
            "intents": [],
            "background_units": [],
            "uncertain_units": ["u_uncertain"],
            "metadata": {},
        }

    background_records = (
        [
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
        if include_background_record
        else []
    )
    source_target = "token validation" if not weak_target else "assigned changes"
    source_symbol = "validate_token" if not weak_target else None
    source_identifiers = ["token", "validate_token"] if not weak_target else []

    return {
        "sample_id": sample_id,
        "decision": "decompose",
        "predicted_k": 1,
        "intents": [
            {
                "slot_id": "slot_1",
                "slot_confidence": 0.9,
                "assigned_unit_ids": ["u1"],
                "assigned_hunk_ids": ["h1"],
                "files": ["src/auth/token.py"],
                "changed_symbols": [source_symbol] if source_symbol else [],
                "changed_identifiers": source_identifiers,
                "file_roles": ["source"],
                "evidence": [
                    {
                        "unit_id": "u1",
                        "hunk_id": "h1",
                        "file_path": "src/auth/token.py",
                        "file_role": "source",
                        "language": "python",
                        "enclosing_symbol": source_symbol,
                        "patch_text": "@@",
                        "added_lines": ["+ validate_token(token)"] if not weak_target else ["+ opaque"],
                        "deleted_lines": ["- token"] if not weak_target else [],
                        "changed_identifiers": source_identifiers,
                        "operation": "update",
                        "metadata": {},
                    }
                ],
                "action": "update" if not weak_target else None,
                "object": source_target if not weak_target else None,
                "scope": "auth" if not weak_target else None,
            }
        ],
        "background_units": ["u_lock"],
        "background_unit_records": background_records,
        "uncertain_units": [],
        "metadata": {},
    }


def test_consumer_evaluation_runner_writes_per_sample_rows_and_aggregate_metrics(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    write_jsonl(
        plan_jsonl,
        [
            _consumer_plan_row("sample_success"),
            _consumer_plan_row("sample_fallback", weak_target=True, include_background_record=False),
            _consumer_plan_row("sample_abstain", decision="abstain"),
        ],
    )

    summary = run_consumer_evaluation(
        predicted_plan_jsonl=plan_jsonl,
        per_sample_output_jsonl=per_sample_jsonl,
        aggregate_output_json=aggregate_json,
    )

    rows = read_jsonl(per_sample_jsonl)
    persisted_summary = read_json(aggregate_json)

    assert len(rows) == 3
    assert summary["sample_counts"]["total"] == 3
    assert summary["sample_counts"]["verification_eligible"] == 2
    assert summary["sample_counts"]["excluded_non_decompose"] == 1
    assert "success_rate" in summary["aggregate_metrics"]
    assert "fallback_rate" in summary["aggregate_metrics"]
    assert "background_mention_rate" in summary["aggregate_metrics"]
    assert persisted_summary["aggregate_metrics"] == summary["aggregate_metrics"]
    fallback_row = next(row for row in rows if row["sample_id"] == "sample_fallback")
    assert fallback_row["verification"]["background_exclusion"]["evidence_incomplete"] is True
    assert fallback_row["verification"]["background_exclusion"]["missing_record_ids"] == ["u_lock"]


def test_consumer_evaluation_runner_does_not_require_raw_commit_messages(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    row = _consumer_plan_row("sample_no_message")
    row["metadata"] = {"commit_message": "forbidden runtime message input"}
    write_jsonl(plan_jsonl, [row])

    summary = run_consumer_evaluation(
        predicted_plan_jsonl=plan_jsonl,
        per_sample_output_jsonl=per_sample_jsonl,
        aggregate_output_json=aggregate_json,
    )

    rows = read_jsonl(per_sample_jsonl)
    assert summary["sample_counts"]["total"] == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["input_contract"]["used_raw_commit_message"] is False


def test_consumer_evaluation_runner_validate_only_writes_no_outputs(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    write_jsonl(plan_jsonl, [_consumer_plan_row("sample_validate_only")])

    summary = run_consumer_evaluation(
        predicted_plan_jsonl=plan_jsonl,
        per_sample_output_jsonl=per_sample_jsonl,
        aggregate_output_json=aggregate_json,
        validate_only=True,
    )

    assert summary["validate_only"] is True
    assert per_sample_jsonl.exists() is False
    assert aggregate_json.exists() is False


def test_consumer_evaluation_runner_output_exists_without_overwrite_fails(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    write_jsonl(plan_jsonl, [_consumer_plan_row("sample_exists")])
    per_sample_jsonl.write_text("exists\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_consumer_evaluation(
            predicted_plan_jsonl=plan_jsonl,
            per_sample_output_jsonl=per_sample_jsonl,
            aggregate_output_json=aggregate_json,
        )


def test_consumer_evaluation_runner_leniently_records_malformed_lines(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    plan_jsonl.write_text(
        "\n".join(
            [
                '{"sample_id":"sample_ok","decision":"decompose","predicted_k":1,"intents":[{"slot_id":"slot_1","slot_confidence":0.9,"assigned_unit_ids":["u1"],"assigned_hunk_ids":["h1"],"files":["src/auth/token.py"],"changed_symbols":["validate_token"],"changed_identifiers":["token"],"file_roles":["source"],"evidence":[{"unit_id":"u1","hunk_id":"h1","file_path":"src/auth/token.py","file_role":"source","language":"python","enclosing_symbol":"validate_token","patch_text":"@@","added_lines":["+ validate"],"deleted_lines":["- token"],"changed_identifiers":["token"],"operation":"update","metadata":{}}],"action":"update","object":"token validation","scope":"auth"}],"background_units":[],"uncertain_units":[],"metadata":{}}',
                '{"sample_id":"broken",',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_consumer_evaluation(
        predicted_plan_jsonl=plan_jsonl,
        per_sample_output_jsonl=per_sample_jsonl,
        aggregate_output_json=aggregate_json,
        strict=False,
        overwrite=True,
    )

    rows = read_jsonl(per_sample_jsonl)
    assert summary["sample_counts"]["errors"] == 1
    assert rows[1]["status"] == "invalid_plan"
    assert rows[1]["errors"][0]["error_type"] == "invalid_input"


def test_consumer_evaluation_runner_strict_malformed_line_raises(tmp_path) -> None:
    plan_jsonl = tmp_path / "predicted_plans.jsonl"
    per_sample_jsonl = tmp_path / "consumer_eval_rows.jsonl"
    aggregate_json = tmp_path / "consumer_eval_summary.json"
    plan_jsonl.write_text('{"sample_id":"broken",\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSONL"):
        run_consumer_evaluation(
            predicted_plan_jsonl=plan_jsonl,
            per_sample_output_jsonl=per_sample_jsonl,
            aggregate_output_json=aggregate_json,
        )


def test_consumer_evaluation_argparse_help_smoke() -> None:
    parser = build_arg_parser()
    help_text = parser.format_help()
    assert "--plans" in help_text
    assert "--plan-source" in help_text


def test_consumer_evaluation_main_returns_non_zero_when_input_missing(tmp_path) -> None:
    exit_code = main(
        [
            "--plans",
            str(tmp_path / "missing.jsonl"),
            "--per-sample-output",
            str(tmp_path / "rows.jsonl"),
            "--aggregate-output",
            str(tmp_path / "summary.json"),
        ]
    )

    assert exit_code != 0
