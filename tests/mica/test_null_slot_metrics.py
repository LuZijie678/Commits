from __future__ import annotations

from code.mica.eval.null_slot_metrics import (
    compute_background_absorption_rate,
    compute_background_slot_audit_metrics,
    compute_gold_to_null_error,
    compute_null_assignment_metrics,
)


def test_null_slot_metrics_ignore_null_for_foreground_count_and_track_errors() -> None:
    rows = [
        {
            "unit_to_slot": {"u1": "slot_1", "u2": "slot_null", "u3": "slot_2"},
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/a.py", "file_role": "source"},
                {"unit_id": "u2", "file_path": "package-lock.json", "file_role": "lockfile"},
                {"unit_id": "u3", "file_path": "tests/test_a.py", "file_role": "test"},
            ],
            "gold_unit_to_intent": {"u1": "i1", "u3": "i2"},
        },
        {
            "unit_to_slot": {"u4": "slot_null"},
            "edit_units": [{"unit_id": "u4", "file_path": "src/b.py", "file_role": "source"}],
            "gold_unit_to_intent": {"u4": "i1"},
        },
    ]

    metrics = compute_null_assignment_metrics(rows)
    gold_error = compute_gold_to_null_error(rows)
    absorption = compute_background_absorption_rate(rows)

    assert metrics["null_assignment_ratio"] > 0.0
    assert gold_error["gold_to_null_error_rate"] > 0.0
    assert absorption["background_absorption_rate"] > 0.0
    assert "missing_intent_rate_by_file_role" in metrics


def test_background_slot_audit_reports_required_protocol_metrics() -> None:
    rows = [
        {
            "unit_to_slot": {
                "u1": "slot_1",
                "u2": "slot_null",
                "u3": "slot_null",
                "u4": "slot_null",
                "u5": "slot_null",
            },
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/a.py", "file_role": "source"},
                {"unit_id": "u2", "file_path": "src/b.py", "file_role": "source"},
                {"unit_id": "u3", "file_path": "package-lock.json", "file_role": "lockfile"},
                {"unit_id": "u4", "file_path": "generated/schema.json", "file_role": "generated"},
                {"unit_id": "u5", "file_path": "src/ambiguous.py", "file_role": "source"},
            ],
            "gold_unit_to_intent": {"u1": "intent_1", "u2": "intent_1"},
            "background_units": ["u3", "u4"],
            "uncertain_units": ["u5"],
        }
    ]

    audit = compute_background_slot_audit_metrics(rows)

    assert audit["background_assignment_rate"] == 4 / 5
    assert audit["foreground_evidence_swallowed_by_background"] == 1 / 2
    assert audit["foreground_to_background_error"] == 1 / 2
    assert audit["missing_intent_rate_by_file_role"]["source"] == 1 / 2
    assert audit["background_precision_on_rule_verified_background_units"] == 2 / 3
    assert audit["background_recall_on_rule_verified_background_units"] == 1.0
    assert audit["audit_denominators"]["excluded_unknown_or_ambiguous_units"] == 1
    assert audit["reporting_rules"]["semantic_uncertainty_counted_as_correct_background"] is False
