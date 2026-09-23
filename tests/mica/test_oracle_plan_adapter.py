from __future__ import annotations

import pytest

from code.mica.adapters.oracle_plan_adapter import adapt_oracle_plan_record


def _oracle_row(*, gold_k: int = 2, scope_status: str = "in_scope") -> dict[str, object]:
    return {
        "sample_id": "oracle_sample",
        "commit_id": "abc123",
        "scope_status": scope_status,
        "gold_k": gold_k,
        "edit_units": [
            {
                "unit_id": "u1",
                "hunk_id": "h1",
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
                "unit_id": "u2",
                "hunk_id": "h2",
                "file_path": "docs/api/auth.md",
                "file_role": "doc",
                "language": "markdown",
                "patch_text": "@@",
                "added_lines": ["+ auth docs"],
                "deleted_lines": [],
                "changed_identifiers": ["auth", "api"],
                "metadata": {},
            },
            {
                "unit_id": "u_lock",
                "hunk_id": "h_lock",
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
        "foreground_intents": [
            {"intent_id": "intent_1", "unit_ids": ["u1"]},
            {"intent_id": "intent_2", "unit_ids": ["u2"]},
        ],
        "background_units": ["u_lock"],
        "shared_support_units": ["u_shared"],
        "uncertain_units": ["u_uncertain"],
        "human_intent_statements": {
            "intent_1": "manually adjudicated token validation change",
            "intent_2": "manually adjudicated docs update",
        },
        "annotation_metadata": {"annotator_id": "ann_1", "annotation_round": 2},
    }


def test_oracle_adapter_builds_valid_k1_plan() -> None:
    row = _oracle_row(gold_k=1)
    row["foreground_intents"] = [{"intent_id": "intent_1", "unit_ids": ["u1"]}]

    plan = adapt_oracle_plan_record(row)

    assert plan.decision == "decompose"
    assert plan.predicted_k == 1
    assert plan.metadata["plan_source"] == "oracle"
    assert plan.metadata["annotation_source"] == "manual_adjudicated"


def test_oracle_adapter_builds_valid_k2_plan_and_excludes_shared_uncertain_units() -> None:
    plan = adapt_oracle_plan_record(_oracle_row())

    assert plan.predicted_k == 2
    assert plan.intents[0].assigned_unit_ids == ["u1"]
    assert plan.intents[1].assigned_unit_ids == ["u2"]
    assert "u_shared" not in {unit_id for intent in plan.intents for unit_id in intent.assigned_unit_ids}
    assert "u_uncertain" not in {unit_id for intent in plan.intents for unit_id in intent.assigned_unit_ids}


def test_oracle_adapter_attaches_background_assignment_records() -> None:
    plan = adapt_oracle_plan_record(_oracle_row())

    assert plan.background_units == ["u_lock"]
    assert plan.background_unit_records[0].background_assignment_type == "explicit_background"


def test_oracle_adapter_rejects_gold_k_mismatch() -> None:
    with pytest.raises(ValueError, match="gold_k"):
        adapt_oracle_plan_record(_oracle_row(gold_k=3))


def test_oracle_adapter_rejects_foreground_background_overlap() -> None:
    row = _oracle_row()
    row["background_units"] = ["u1"]

    with pytest.raises(ValueError, match="background"):
        adapt_oracle_plan_record(row)


def test_oracle_adapter_marks_out_of_scope_as_overflow() -> None:
    plan = adapt_oracle_plan_record(_oracle_row(scope_status="out_of_scope"))

    assert plan.decision == "overflow"
    assert plan.predicted_k == 0
    assert plan.intents == []


def test_oracle_adapter_keeps_human_statement_as_annotation_metadata_only() -> None:
    plan = adapt_oracle_plan_record(_oracle_row())

    assert plan.intents[0].action is None
    assert plan.intents[0].object is None
    assert plan.intents[0].metadata["human_intent_statement"] == "manually adjudicated token validation change"
