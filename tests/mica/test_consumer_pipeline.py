from __future__ import annotations

from dataclasses import replace

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
from code.mica.consumers.message_generator import GeneratedCommitMessage
from code.mica.consumers.pipeline import ConsumerPipeline
from code.mica.consumers.plan_schema import EvidenceUnit, IntentPlan, StructuredIntentPlan


def _evidence(
    unit_id: str,
    *,
    file_path: str,
    file_role: str,
    enclosing_symbol: str | None = None,
    changed_identifiers: list[str] | None = None,
    patch_text: str = "@@",
    added_lines: list[str] | None = None,
    deleted_lines: list[str] | None = None,
) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        hunk_id=f"h_{unit_id}",
        file_path=file_path,
        file_role=file_role,
        language="python" if file_role != "doc" else "markdown",
        enclosing_symbol=enclosing_symbol,
        patch_text=patch_text,
        added_lines=added_lines or ["+ change"],
        deleted_lines=deleted_lines or ["- old"],
        changed_identifiers=changed_identifiers or [],
    )


def _intent(
    slot_id: str,
    *,
    evidence: list[EvidenceUnit],
    action: str | None = None,
    object_value: str | None = None,
    scope: str | None = None,
) -> IntentPlan:
    return IntentPlan(
        slot_id=slot_id,
        slot_confidence=0.86,
        assigned_unit_ids=[unit.unit_id for unit in evidence],
        assigned_hunk_ids=[unit.hunk_id for unit in evidence],
        files=[unit.file_path for unit in evidence],
        changed_symbols=[unit.enclosing_symbol for unit in evidence if unit.enclosing_symbol],
        changed_identifiers=[identifier for unit in evidence for identifier in unit.changed_identifiers],
        file_roles=[unit.file_role for unit in evidence],
        evidence=evidence,
        action=action,
        object=object_value,
        scope=scope,
    )


def _plan() -> StructuredIntentPlan:
    return StructuredIntentPlan(
        sample_id="pipeline_case",
        decision="decompose",
        predicted_k=2,
        overall_confidence=0.91,
        intents=[
            _intent(
                "slot_1",
                evidence=[
                    _evidence(
                        "u1",
                        file_path="src/auth/token.py",
                        file_role="source",
                        enclosing_symbol="validate_token",
                        changed_identifiers=["token", "validate_token"],
                        patch_text="+ validate_token(token)",
                    ),
                    _evidence(
                        "u2",
                        file_path="tests/test_token.py",
                        file_role="test",
                        enclosing_symbol="test_validate_token",
                        changed_identifiers=["token"],
                        patch_text="+ test_validate_token()",
                    ),
                ],
                action="update",
                object_value="token validation",
                scope="auth",
            ),
            _intent(
                "slot_2",
                evidence=[
                    _evidence(
                        "u3",
                        file_path="docs/api/auth.md",
                        file_role="doc",
                        changed_identifiers=["auth", "api"],
                        patch_text="+ auth token docs",
                    )
                ],
                action="document",
                object_value="API docs",
                scope="docs",
            ),
        ],
        background_units=["u4", "u5"],
        background_unit_records=[
            {
                "unit_id": "u4",
                "hunk_id": "h_u4",
                "file_path": "package-lock.json",
                "file_role": "lockfile",
                "changed_identifiers": ["lockfile"],
                "patch_operation": "update",
                "background_reason": "lockfile",
                "background_confidence": 0.99,
            },
            {
                "unit_id": "u5",
                "hunk_id": "h_u5",
                "file_path": "src/auth/token.py",
                "file_role": "format-only",
                "changed_identifiers": [],
                "patch_operation": "update",
                "background_reason": "format_only",
                "background_confidence": 0.95,
            },
        ],
        uncertain_units=[],
        metadata={},
    )


def test_pipeline_generates_message_for_valid_decompose_plan() -> None:
    result = ConsumerPipeline().generate(structured_plan=_plan(), mode="deterministic", verify=True)

    assert result.status == "success"
    assert result.message is not None
    assert "lockfile" not in result.message.subject.lower()
    assert result.verification["slot_coverage"]["intent_coverage_rate"] == 1.0
    assert result.verification["unsupported_claims"]["unsupported_claims"] == []


def test_pipeline_rejects_abstain_plan_without_generating_normal_message() -> None:
    plan = StructuredIntentPlan(
        sample_id="abstain_case",
        decision="abstain",
        predicted_k=0,
        intents=[],
        background_units=[],
        uncertain_units=["u9"],
        risk_score=0.88,
        metadata={},
    )

    result = ConsumerPipeline().generate(structured_plan=plan, mode="deterministic", verify=True)

    assert result.status == "rejected"
    assert result.message is None
    assert result.errors


def test_pipeline_uses_conservative_fallback_for_weak_target() -> None:
    weak_plan = StructuredIntentPlan(
        sample_id="weak_case",
        decision="decompose",
        predicted_k=1,
        intents=[
            _intent(
                "slot_1",
                evidence=[
                    _evidence(
                        "u1",
                        file_path="src/legacy/handler.unknown",
                        file_role="source",
                        enclosing_symbol=None,
                        changed_identifiers=[],
                        patch_text="+ opaque",
                    )
                ],
            )
        ],
        background_units=[],
        uncertain_units=[],
        metadata={},
    )

    result = ConsumerPipeline().generate(structured_plan=weak_plan, mode="deterministic", verify=True)

    assert result.status in {"success", "rejected"}
    if result.message is not None:
        assert "performance" not in result.message.subject.lower()
        assert "security" not in result.message.subject.lower()


class _UnsafeGenerator:
    def generate_candidates(self, summaries: list[SlotEvidenceSummary], *, plan_decision: str, background_terms: set[str] | None = None) -> list[GeneratedCommitMessage]:
        return [
            GeneratedCommitMessage(
                subject="improve performance of token validation",
                body=[],
                covered_slot_ids=[summary.slot_id for summary in summaries],
                mentioned_entities=["token", "performance"],
                generator_type="unsafe-test-double",
                generator_version="v0",
                diagnostics={},
                status="success",
            )
        ]


def test_pipeline_rejects_candidate_with_unsupported_performance_claim() -> None:
    result = ConsumerPipeline(generator=_UnsafeGenerator()).generate(structured_plan=_plan(), mode="deterministic", verify=True)

    assert result.status == "rejected"
    assert result.message is None
    assert "performance" in " ".join(result.verification["unsupported_claims"]["unsupported_claims"])


def test_pipeline_is_deterministic_for_same_input() -> None:
    pipeline = ConsumerPipeline()
    left = pipeline.generate(structured_plan=_plan(), mode="deterministic", verify=True)
    right = pipeline.generate(structured_plan=replace(_plan()), mode="deterministic", verify=True)

    assert left.to_dict() == right.to_dict()
