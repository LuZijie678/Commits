from __future__ import annotations

import pytest

from code.mica.consumers.plan_schema import EvidenceUnit, IntentPlan, StructuredIntentPlan, adapt_from_legacy_plan
from code.mica.schemas import EditUnitRecord, StructuredIntent, StructuredIntentPlan as LegacyStructuredIntentPlan


def _evidence(
    unit_id: str,
    *,
    hunk_id: str | None = None,
    file_path: str = "src/auth/token.py",
    file_role: str = "source",
    language: str | None = "python",
    enclosing_symbol: str | None = "validate_token",
    changed_identifiers: list[str] | None = None,
    patch_text: str = "@@",
    added_lines: list[str] | None = None,
    deleted_lines: list[str] | None = None,
) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        hunk_id=hunk_id or f"h_{unit_id}",
        file_path=file_path,
        file_role=file_role,
        language=language,
        enclosing_symbol=enclosing_symbol,
        patch_text=patch_text,
        added_lines=added_lines or ["+ token = normalize(token)"],
        deleted_lines=deleted_lines or ["- token = token.strip()"],
        changed_identifiers=changed_identifiers or ["token"],
    )


def _intent(
    slot_id: str,
    unit_id: str,
    *,
    slot_confidence: float = 0.8,
    file_path: str = "src/auth/token.py",
    file_role: str = "source",
    changed_identifiers: list[str] | None = None,
    evidence: list[EvidenceUnit] | None = None,
) -> IntentPlan:
    current_evidence = evidence or [
        _evidence(
            unit_id,
            file_path=file_path,
            file_role=file_role,
            changed_identifiers=changed_identifiers,
        )
    ]
    return IntentPlan(
        slot_id=slot_id,
        slot_confidence=slot_confidence,
        assigned_unit_ids=[unit_id],
        assigned_hunk_ids=[current_evidence[0].hunk_id],
        files=[file_path],
        changed_symbols=[current_evidence[0].enclosing_symbol] if current_evidence[0].enclosing_symbol else [],
        changed_identifiers=list(changed_identifiers or current_evidence[0].changed_identifiers),
        file_roles=[file_role],
        evidence=current_evidence,
        action="update",
        object="token validation",
        scope="auth",
    )


def _background_record(
    unit_id: str,
    *,
    hunk_id: str | None = None,
    file_path: str = "package-lock.json",
    file_role: str = "lockfile",
    changed_identifiers: list[str] | None = None,
    patch_operation: str = "update",
    background_reason: str = "lockfile",
    background_confidence: float = 0.99,
    background_reason_source: str | None = "file_role_rule",
    background_assignment_type: str | None = "rule_verified_background",
    background_record_resolution_status: str | None = "complete",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "unit_id": unit_id,
        "hunk_id": hunk_id or f"h_{unit_id}",
        "file_path": file_path,
        "file_role": file_role,
        "changed_identifiers": list(changed_identifiers or ["lockfile"]),
        "patch_operation": patch_operation,
        "background_reason": background_reason,
        "background_confidence": background_confidence,
    }
    if background_reason_source is not None:
        payload["background_reason_source"] = background_reason_source
    if background_assignment_type is not None:
        payload["background_assignment_type"] = background_assignment_type
    if background_record_resolution_status is not None:
        payload["background_record_resolution_status"] = background_record_resolution_status
    return payload


def test_consumer_plan_accepts_valid_single_intent_plan() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_single",
        commit_id="commit_single",
        decision="decompose",
        predicted_k=1,
        overall_confidence=0.92,
        intents=[_intent("slot_1", "u1")],
        background_units=[],
        uncertain_units=[],
        risk_score=0.12,
        metadata={},
    )

    assert plan.sample_id == "sample_single"
    assert plan.predicted_k == 1
    assert len(plan.intents) == 1


def test_consumer_plan_accepts_valid_multi_intent_plan() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_multi",
        decision="decompose",
        predicted_k=2,
        intents=[
            _intent("slot_1", "u1", changed_identifiers=["token"]),
            _intent(
                "slot_2",
                "u2",
                file_path="docs/api.md",
                file_role="doc",
                changed_identifiers=["api"],
            ),
        ],
        background_units=["u3"],
        background_unit_records=[_background_record("u3")],
        uncertain_units=["u4"],
        metadata={},
    )

    assert plan.predicted_k == 2
    assert {intent.slot_id for intent in plan.intents} == {"slot_1", "slot_2"}
    assert plan.background_contract["evidence_incomplete"] is False
    assert plan.background_contract["missing_record_ids"] == []
    assert plan.background_contract["evidence_complete"] is True
    assert plan.to_dict()["background_unit_records"][0]["background_reason"] == "lockfile"


def test_consumer_plan_rejects_duplicate_slot_id() -> None:
    with pytest.raises(ValueError, match="duplicate slot_id"):
        StructuredIntentPlan(
            sample_id="dup_slots",
            decision="decompose",
            predicted_k=2,
            intents=[_intent("slot_1", "u1"), _intent("slot_1", "u2")],
            background_units=[],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_rejects_predicted_k_mismatch() -> None:
    with pytest.raises(ValueError, match="predicted_k"):
        StructuredIntentPlan(
            sample_id="mismatch",
            decision="decompose",
            predicted_k=2,
            intents=[_intent("slot_1", "u1")],
            background_units=[],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_rejects_duplicate_primary_assignment_units() -> None:
    with pytest.raises(ValueError, match="assigned unit_id"):
        StructuredIntentPlan(
            sample_id="dup_units",
            decision="decompose",
            predicted_k=2,
            intents=[
                _intent("slot_1", "u1"),
                _intent(
                    "slot_2",
                    "u1",
                    file_path="src/cache/token.py",
                    changed_identifiers=["cache"],
                ),
            ],
            background_units=[],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_rejects_background_record_outside_background_units() -> None:
    with pytest.raises(ValueError, match="background_unit_records"):
        StructuredIntentPlan(
            sample_id="background_record_mismatch",
            decision="decompose",
            predicted_k=1,
            intents=[_intent("slot_1", "u1")],
            background_units=["u_bg"],
            background_unit_records=[_background_record("u_other")],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_rejects_foreground_background_overlap() -> None:
    with pytest.raises(ValueError, match="background"):
        StructuredIntentPlan(
            sample_id="foreground_background_overlap",
            decision="decompose",
            predicted_k=1,
            intents=[_intent("slot_1", "u1")],
            background_units=["u1"],
            background_unit_records=[_background_record("u1")],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="slot_confidence"):
        StructuredIntentPlan(
            sample_id="bad_conf",
            decision="decompose",
            predicted_k=1,
            intents=[_intent("slot_1", "u1", slot_confidence=1.5)],
            background_units=[],
            uncertain_units=[],
            metadata={},
        )


def test_consumer_plan_accepts_abstain_and_overflow_without_trusted_intents() -> None:
    abstain = StructuredIntentPlan(
        sample_id="abstain_case",
        decision="abstain",
        predicted_k=0,
        intents=[],
        background_units=[],
        uncertain_units=["u7"],
        risk_score=0.91,
        metadata={},
    )
    overflow = StructuredIntentPlan(
        sample_id="overflow_case",
        decision="overflow",
        predicted_k=0,
        intents=[],
        background_units=[],
        uncertain_units=[],
        risk_score=0.97,
        metadata={"overflow_evidence": ["capacity_saturation"]},
    )

    assert abstain.decision == "abstain"
    assert overflow.decision == "overflow"


def test_consumer_plan_reports_incomplete_background_contract_when_records_missing() -> None:
    plan = StructuredIntentPlan(
        sample_id="background_missing_record",
        decision="decompose",
        predicted_k=1,
        intents=[_intent("slot_1", "u1")],
        background_units=["u_lock", "u_vendor"],
        background_unit_records=[_background_record("u_lock")],
        uncertain_units=[],
        metadata={},
    )

    assert plan.background_contract["evidence_incomplete"] is True
    assert plan.background_contract["missing_record_ids"] == ["u_vendor"]
    assert plan.background_contract["evidence_complete"] is False


def test_background_record_preserves_rule_verified_background_audit_fields() -> None:
    plan = StructuredIntentPlan(
        sample_id="background_rule_verified",
        decision="decompose",
        predicted_k=1,
        intents=[_intent("slot_1", "u1")],
        background_units=["u_lock"],
        background_unit_records=[_background_record("u_lock")],
        uncertain_units=[],
        metadata={},
    )

    record = plan.background_unit_records[0]
    assert record.background_reason_source == "file_role_rule"
    assert record.background_assignment_type == "rule_verified_background"
    assert record.background_record_resolution_status == "complete"


def test_background_record_from_null_slot_is_not_rule_verified() -> None:
    plan = StructuredIntentPlan(
        sample_id="background_model_assigned",
        decision="decompose",
        predicted_k=1,
        intents=[_intent("slot_1", "u1")],
        background_units=["u_lock"],
        background_unit_records=[
            _background_record(
                "u_lock",
                background_reason="model_null_slot",
                background_reason_source="null_slot_assignment",
                background_assignment_type="model_assigned_background",
            )
        ],
        uncertain_units=[],
        metadata={},
    )

    record = plan.background_unit_records[0]
    assert record.background_reason_source == "null_slot_assignment"
    assert record.background_assignment_type == "model_assigned_background"


def test_background_record_accepts_unresolved_id_only_compatibility_shape() -> None:
    plan = StructuredIntentPlan.from_dict(
        {
            "sample_id": "background_id_only",
            "decision": "decompose",
            "predicted_k": 1,
            "intents": [_intent("slot_1", "u1").to_dict()],
            "background_units": ["u_lock"],
            "background_unit_records": [
                {
                    "unit_id": "u_lock",
                    "file_path": "package-lock.json",
                    "patch_operation": "update",
                    "background_reason": "lockfile",
                    "background_confidence": 0.9,
                }
            ],
            "uncertain_units": [],
            "metadata": {},
        }
    )

    record = plan.background_unit_records[0]
    assert record.background_assignment_type == "unresolved_background"
    assert record.background_reason_source == "legacy_adapter"
    assert record.background_record_resolution_status == "partial"
    assert "legacy_background_record_defaults_applied" in plan.background_contract["diagnostic_codes"]


def test_consumer_plan_allows_empty_evidence_for_compatibility_fallback() -> None:
    plan = StructuredIntentPlan(
        sample_id="empty_evidence",
        decision="decompose",
        predicted_k=1,
        intents=[
            IntentPlan(
                slot_id="slot_1",
                slot_confidence=0.5,
                assigned_unit_ids=["u1"],
                assigned_hunk_ids=["h1"],
                files=["src/auth/token.py"],
                changed_symbols=[],
                changed_identifiers=[],
                file_roles=["source"],
                evidence=[],
            )
        ],
        background_units=[],
        uncertain_units=[],
        metadata={},
    )

    assert plan.intents[0].evidence == []


def test_consumer_plan_adapter_preserves_safe_fields_from_legacy_plan() -> None:
    legacy = LegacyStructuredIntentPlan(
        sample_id="legacy_sample",
        intent_count=1,
        is_multi_intent=False,
        intents=[
            StructuredIntent(
                intent_id="intent_1",
                slot_id="slot_1",
                edit_unit_ids=["u1"],
                hunk_ids=["h1"],
                evidence_units=[
                    EditUnitRecord(
                        unit_id="u1",
                        file_path="src/auth/token.py",
                        hunk_id="h1",
                        patch_text="+ validate",
                        added_lines=["+ validate_token(token)"],
                        deleted_lines=["- token"],
                        changed_identifiers=["token"],
                        file_role="source",
                        language="python",
                        gold_intent_id="gold_should_not_leak",
                        metadata={
                            "enclosing_symbol_name": "validate_token",
                            "synthetic_construction_id": "forbidden",
                            "commit_message": "forbidden",
                        },
                    )
                ],
                confidence=0.84,
                type="update",
                scope="auth",
                subject=None,
                body=None,
                diagnostics={"action": "update", "object": "token validation"},
            )
        ],
        metadata={"prediction_source": "predicted_plan"},
    )

    adapted = adapt_from_legacy_plan(legacy)

    assert adapted.sample_id == "legacy_sample"
    assert adapted.decision == "decompose"
    assert adapted.predicted_k == 1
    assert adapted.intents[0].evidence[0].enclosing_symbol == "validate_token"
    assert "commit_message" not in adapted.intents[0].evidence[0].metadata
    assert "synthetic_construction_id" not in adapted.intents[0].evidence[0].metadata


def test_consumer_plan_adapter_drops_legacy_subject_surface_text() -> None:
    legacy = LegacyStructuredIntentPlan(
        sample_id="legacy_subject_case",
        intent_count=1,
        is_multi_intent=False,
        intents=[
            StructuredIntent(
                intent_id="intent_1",
                slot_id="slot_1",
                edit_unit_ids=["u1"],
                hunk_ids=["h1"],
                evidence_units=[
                    EditUnitRecord(
                        unit_id="u1",
                        file_path="src/auth/token.py",
                        hunk_id="h1",
                        patch_text="+ validate",
                        added_lines=["+ validate_token(token)"],
                        deleted_lines=["- token"],
                        changed_identifiers=["token"],
                        file_role="source",
                        language="python",
                        metadata={"enclosing_symbol_name": "validate_token"},
                    )
                ],
                confidence=0.84,
                type=None,
                scope="auth",
                subject="forbidden gold surface text",
                body="forbidden body text",
                diagnostics={},
            )
        ],
        metadata={},
    )

    adapted = adapt_from_legacy_plan(legacy)

    assert adapted.intents[0].action is None
    assert adapted.intents[0].object is None
    assert adapted.intents[0].metadata == {}


def test_consumer_plan_round_trip_preserves_schema_version_and_background_contract() -> None:
    plan = StructuredIntentPlan(
        sample_id="round_trip",
        decision="decompose",
        predicted_k=1,
        intents=[_intent("slot_1", "u1")],
        background_units=["u_lock"],
        background_unit_records=[_background_record("u_lock")],
        uncertain_units=[],
        metadata={},
    )

    reloaded = StructuredIntentPlan.from_dict(plan.to_dict())

    assert reloaded.to_dict()["schema_version"] == plan.to_dict()["schema_version"]
    assert reloaded.background_contract == plan.background_contract
