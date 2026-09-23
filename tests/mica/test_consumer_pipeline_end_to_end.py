from __future__ import annotations

from code.mica.adapters.stage1_prediction_adapter import normalize_stage1_prediction_row
from code.mica.consumers.pipeline import ConsumerPipeline
from code.mica.plan_builder import build_plan_from_dict


def _raw_prediction_row(
    *,
    include_slot_null_background: bool = True,
    explicit_background_units: list[str] | None = None,
    include_background_records: bool = True,
    release_decision: str = "decompose",
    slot_names: tuple[str, str] = ("slot_auth", "slot_docs"),
) -> dict[str, object]:
    slot_auth, slot_docs = slot_names
    assignments: dict[str, str] = {
        "u_src": slot_auth,
        "u_test": slot_auth,
        "u_doc": slot_docs,
    }
    if include_slot_null_background:
        assignments["u_lock"] = "slot_null"

    metadata: dict[str, object] = {"release_decision": release_decision}
    if explicit_background_units is not None:
        metadata["background_units"] = list(explicit_background_units)
    if include_background_records and explicit_background_units:
        metadata["background_unit_records"] = [
            {
                "unit_id": unit_id,
                "hunk_id": f"h_{unit_id}",
                "file_path": "package-lock.json",
                "file_role": "lockfile",
                "changed_identifiers": ["lockfile"],
                "patch_operation": "update",
                "background_reason": "lockfile",
                "background_confidence": 0.99,
            }
            for unit_id in explicit_background_units
        ]

    return {
        "sample_id": "e2e_sample",
        "k_hat": 2,
        "count_probs": {"1": 0.08, "2": 0.9, "3": 0.02},
        "slot_exist": {
            slot_auth: 0.95,
            slot_docs: 0.88,
        },
        "assignments": assignments,
        "assignment_scores": {
            "u_src": {slot_auth: 0.97, "slot_null": 0.01},
            "u_test": {slot_auth: 0.91, "slot_null": 0.02},
            "u_doc": {slot_docs: 0.94, "slot_null": 0.01},
            "u_lock": {"slot_null": 0.99, slot_auth: 0.01},
        },
        "unit_records": [
            {
                "unit_id": "u_src",
                "file_path": "src/auth/token.py",
                "hunk_id": "h_u_src",
                "file_role": "source",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ validate_token(token)"],
                "deleted_lines": ["- token"],
                "changed_identifiers": ["token", "validate_token"],
                "metadata": {"enclosing_symbol_name": "validate_token"},
            },
            {
                "unit_id": "u_test",
                "file_path": "tests/test_token.py",
                "hunk_id": "h_u_test",
                "file_role": "test",
                "language": "python",
                "patch_text": "@@",
                "added_lines": ["+ test_validate_token()"],
                "deleted_lines": [],
                "changed_identifiers": ["token", "test_validate_token"],
                "metadata": {"enclosing_symbol_name": "test_validate_token"},
            },
            {
                "unit_id": "u_doc",
                "file_path": "docs/api/auth.md",
                "hunk_id": "h_u_doc",
                "file_role": "doc",
                "language": "markdown",
                "patch_text": "@@",
                "added_lines": ["+ token auth docs"],
                "deleted_lines": [],
                "changed_identifiers": ["token", "auth", "api"],
                "metadata": {},
            },
            {
                "unit_id": "u_lock",
                "file_path": "package-lock.json",
                "hunk_id": "h_u_lock",
                "file_role": "lockfile",
                "language": "json",
                "patch_text": "@@",
                "added_lines": ["+ lockfile update"],
                "deleted_lines": [],
                "changed_identifiers": ["lockfile"],
                "metadata": {},
            },
        ],
        "metadata": metadata,
    }


def _legacy_plan_from_raw_row(raw_row: dict[str, object]):
    normalized = normalize_stage1_prediction_row(raw_row)
    return build_plan_from_dict(normalized)


def test_inference_row_flows_through_adapter_builder_and_pipeline() -> None:
    plan = _legacy_plan_from_raw_row(_raw_prediction_row())

    result = ConsumerPipeline().generate(structured_plan=plan, verify=True)

    assert plan.metadata["background_units"] == ["u_lock"]
    assert plan.metadata["background_unit_records"][0]["background_reason"] == "lockfile"
    assert plan.metadata["background_unit_records"][0]["background_assignment_type"] == "model_assigned_background"
    assert plan.metadata["background_unit_records"][0]["background_reason_source"] == "null_slot_assignment"
    assert result.status == "success"
    assert result.message is not None
    assert "lockfile" not in result.message.subject.lower()
    assert result.verification["slot_coverage"]["intent_coverage_rate"] == 1.0
    assert result.verification["background_exclusion"]["background_mentions"] == []


def test_inference_row_without_background_records_reports_incomplete_contract() -> None:
    raw_row = _raw_prediction_row(
        include_slot_null_background=False,
        explicit_background_units=["u_lock"],
        include_background_records=False,
    )
    plan = _legacy_plan_from_raw_row(raw_row)

    result = ConsumerPipeline().generate(structured_plan=plan, verify=True)

    assert result.status == "success"
    assert result.verification["background_exclusion"]["evidence_incomplete"] is True
    assert result.verification["background_exclusion"]["missing_record_ids"] == ["u_lock"]


def test_explicit_background_metadata_without_new_fields_is_marked_partial() -> None:
    raw_row = _raw_prediction_row(
        include_slot_null_background=False,
        explicit_background_units=["u_lock"],
        include_background_records=True,
    )
    raw_row["metadata"]["background_unit_records"] = [
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
    plan = _legacy_plan_from_raw_row(raw_row)
    adapted = ConsumerPipeline()._coerce_plan(plan)

    assert adapted.background_unit_records[0].background_assignment_type == "explicit_background"
    assert adapted.background_unit_records[0].background_reason_source == "explicit_plan_metadata"
    assert adapted.background_unit_records[0].background_record_resolution_status == "partial"


def test_legacy_subject_is_not_reused_in_end_to_end_pipeline() -> None:
    plan = _legacy_plan_from_raw_row(_raw_prediction_row())
    plan.intents[0].subject = "forbidden gold commit subject"
    plan.intents[0].body = "forbidden gold body"

    result = ConsumerPipeline().generate(structured_plan=plan, verify=True)

    assert result.status == "success"
    assert result.message is not None
    assert result.message.subject != "forbidden gold commit subject"
    assert "forbidden gold" not in "\n".join(result.message.body)


def test_slot_id_permutation_keeps_end_to_end_semantics_stable() -> None:
    left = ConsumerPipeline().generate(structured_plan=_legacy_plan_from_raw_row(_raw_prediction_row()), verify=True)
    right = ConsumerPipeline().generate(
        structured_plan=_legacy_plan_from_raw_row(_raw_prediction_row(slot_names=("slot_9", "slot_3"))),
        verify=True,
    )

    assert left.status == "success"
    assert right.status == "success"
    assert left.message is not None
    assert right.message is not None
    assert left.message.subject == right.message.subject
    assert left.message.body == right.message.body


def test_release_decision_abstain_from_inference_row_rejects_message_generation() -> None:
    plan = _legacy_plan_from_raw_row(_raw_prediction_row(release_decision="abstain"))

    result = ConsumerPipeline().generate(structured_plan=plan, verify=True)

    assert result.status == "rejected"
    assert result.message is None
    assert result.verification["decision"] == "abstain"
