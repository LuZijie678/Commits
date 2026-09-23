from __future__ import annotations

from code.mica.renderers.deterministic import DeterministicRenderer
from code.mica.schemas import EditUnitRecord, StructuredIntent, StructuredIntentPlan


def _legacy_plan(*, decision: str = "decompose") -> StructuredIntentPlan:
    return StructuredIntentPlan(
        sample_id="legacy_consumer_case",
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
                        patch_text="+ validate_token(token)",
                        added_lines=["+ validate_token(token)"],
                        deleted_lines=["- token"],
                        changed_identifiers=["token", "validate_token"],
                        file_role="source",
                        language="python",
                        metadata={"enclosing_symbol_name": "validate_token"},
                    )
                ],
                confidence=0.87,
                type="update",
                scope="auth",
                subject=None,
                body=None,
                diagnostics={"action": "update", "object": "token validation"},
            )
        ],
        rendering_status="ready",
        degraded=False,
        diagnostics=[],
        metadata={} if decision == "decompose" else {"release_decision": decision},
    )


def test_legacy_renderer_uses_consumer_pipeline_for_decompose_plans() -> None:
    rendered = DeterministicRenderer().render(_legacy_plan())

    assert rendered.status == "success"
    assert rendered.subject
    assert "token validation" in rendered.subject
    assert any(diagnostic["code"] == "consumer_pipeline_status" for diagnostic in rendered.diagnostics)


def test_legacy_renderer_ignores_legacy_surface_subject_text() -> None:
    plan = _legacy_plan()
    plan.intents[0].subject = "forbidden gold commit message"

    rendered = DeterministicRenderer().render(plan)

    assert rendered.status == "success"
    assert rendered.subject != "forbidden gold commit message"


def test_legacy_renderer_does_not_fabricate_message_for_abstain_plan() -> None:
    rendered = DeterministicRenderer().render(_legacy_plan(decision="abstain"))

    assert rendered.status == "rejected"
    assert rendered.subject == ""
    assert any(diagnostic["code"] == "consumer_pipeline_status" for diagnostic in rendered.diagnostics)
