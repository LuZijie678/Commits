from __future__ import annotations

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
from code.mica.consumers.message_generator import GeneratedCommitMessage
from code.mica.consumers.plan_schema import IntentPlan, StructuredIntentPlan
from code.mica.consumers.verifier import (
    BackgroundExclusionVerifier,
    EntityGroundingVerifier,
    FormatVerifier,
    SlotCoverageVerifier,
    UnsupportedClaimVerifier,
)


def _summary(
    slot_id: str,
    *,
    operation: str = "update",
    target: str = "token validation",
    scope: str = "auth",
    evidence_entities: list[str] | None = None,
    supported_claims: list[str] | None = None,
) -> SlotEvidenceSummary:
    return SlotEvidenceSummary(
        slot_id=slot_id,
        operation=operation,
        target=target,
        scope=scope,
        behavioral_effect=None,
        supporting_changes=[],
        evidence_entities=evidence_entities or ["token", "auth"],
        evidence_unit_ids=[f"{slot_id}_u1"],
        confidence=0.8,
        fallback_reason=None,
        supported_claims=supported_claims or [],
        stable_order_key=(scope, target, slot_id),
    )


def _message(subject: str, body: list[str] | None = None, covered: list[str] | None = None) -> GeneratedCommitMessage:
    return GeneratedCommitMessage(
        subject=subject,
        body=body or [],
        covered_slot_ids=covered or ["slot_1"],
        mentioned_entities=["token", "auth"],
        generator_type="deterministic",
        generator_version="v1",
        diagnostics={},
        status="success",
    )


def _plan(decision: str = "decompose", background_units: list[str] | None = None) -> StructuredIntentPlan:
    return StructuredIntentPlan(
        sample_id="verify_case",
        decision=decision,
        predicted_k=1 if decision == "decompose" else 0,
        intents=[] if decision != "decompose" else [
            IntentPlan(
                slot_id="slot_1",
                slot_confidence=0.8,
                assigned_unit_ids=["u1"],
                assigned_hunk_ids=["h1"],
                files=["src/auth/token.py"],
                changed_symbols=["validate_token"],
                changed_identifiers=["token"],
                file_roles=["source"],
                evidence=[],
            )
        ],
        background_units=background_units or [],
        uncertain_units=[],
        metadata={"background_terms": ["lockfile", "formatting"]},
    )


def test_slot_coverage_verifier_reports_full_coverage() -> None:
    result = SlotCoverageVerifier().verify(
        message=_message("update token validation", body=["- document API docs"], covered=["slot_1", "slot_2"]),
        summaries=[_summary("slot_1"), _summary("slot_2", target="API docs", scope="docs", evidence_entities=["api"])],
    )

    assert result["intent_coverage_rate"] == 1.0
    assert result["missing_slot_ids"] == []


def test_slot_coverage_verifier_reports_missing_slot() -> None:
    result = SlotCoverageVerifier().verify(
        message=_message("update token validation", covered=["slot_1"]),
        summaries=[_summary("slot_1"), _summary("slot_2", target="API docs", scope="docs", evidence_entities=["api"])],
    )

    assert result["intent_coverage_rate"] < 1.0
    assert result["missing_slot_ids"] == ["slot_2"]


def test_slot_coverage_verifier_ignores_declared_covered_slot_ids_when_text_misses_slot() -> None:
    result = SlotCoverageVerifier().verify(
        message=_message("update token validation", covered=["slot_1", "slot_2"]),
        summaries=[_summary("slot_1"), _summary("slot_2", target="API docs", scope="docs", evidence_entities=["api"])],
    )

    assert result["missing_slot_ids"] == ["slot_2"]
    assert result["declared_not_verified_slot_ids"] == ["slot_2"]


def test_unsupported_claim_verifier_flags_risky_claims_without_support() -> None:
    result = UnsupportedClaimVerifier().verify(
        message=_message("improve performance of token validation"),
        summaries=[_summary("slot_1")],
    )

    assert "performance" in result["unsupported_claims"]


def test_unsupported_claim_verifier_allows_explicit_supported_claim() -> None:
    result = UnsupportedClaimVerifier().verify(
        message=_message("improve performance of token validation"),
        summaries=[_summary("slot_1", supported_claims=["performance"])],
    )

    assert result["unsupported_claims"] == []


def test_entity_grounding_verifier_reports_unsupported_entity() -> None:
    result = EntityGroundingVerifier().verify(
        message=_message("update cache validation", covered=["slot_1"]),
        summaries=[_summary("slot_1", evidence_entities=["token", "auth"])],
    )

    assert "cache" in result["unsupported_entities"]


def test_background_exclusion_verifier_flags_background_mention() -> None:
    result = BackgroundExclusionVerifier().verify(
        plan=_plan(background_units=["u_lock"]),
        message=_message("update lockfile for token validation"),
        summaries=[_summary("slot_1")],
    )

    assert result["background_mentions"] != []


def test_background_exclusion_verifier_only_uses_assigned_background_units() -> None:
    plan = StructuredIntentPlan(
        sample_id="background_filter_case",
        decision="decompose",
        predicted_k=1,
        intents=[
            IntentPlan(
                slot_id="slot_1",
                slot_confidence=0.8,
                assigned_unit_ids=["u1"],
                assigned_hunk_ids=["h1"],
                files=["src/auth/token.py"],
                changed_symbols=["validate_token"],
                changed_identifiers=["token"],
                file_roles=["source"],
                evidence=[],
            )
        ],
        background_units=["u_lock"],
        background_unit_records=[
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
        ],
        uncertain_units=[],
        metadata={},
    )

    result = BackgroundExclusionVerifier().verify(
        plan=plan,
        message=_message("update vendorcache token validation"),
        summaries=[_summary("slot_1")],
    )

    assert "vendorcache" not in result["background_mentions"]


def test_format_verifier_reports_format_failure() -> None:
    result = FormatVerifier(max_subject_length=20).verify(
        message=_message("update token validation.", body=["- duplicate", "- duplicate"]),
    )

    assert result["valid"] is False
    assert "subject_ends_with_period" in result["errors"]
    assert "duplicate_body_bullets" in result["errors"]
