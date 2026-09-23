from __future__ import annotations

import inspect

from code.mica.renderers.deterministic import DeterministicRenderer
from code.mica.schemas import DegradationDiagnostic, EditUnitRecord, StructuredIntent, StructuredIntentPlan


def _intent(*, subject: str | None, file_path: str = "src/auth/token.py", role: str = "source") -> StructuredIntent:
    unit = EditUnitRecord(unit_id="u1", file_path=file_path, file_role=role, changed_identifiers=["token"], patch_text="SECRET_RAW_DIFF")
    return StructuredIntent(
        intent_id="intent_1",
        slot_id="slot_1",
        edit_unit_ids=["u1"],
        hunk_ids=["h1"],
        evidence_units=[unit],
        confidence=0.8,
        type=None,
        scope=None,
        subject=subject,
        body=None,
        core_units=["u1"],
        support_units=[],
        auxiliary_units=[],
        diagnostics={},
    )


def test_renderer_uses_structured_intent_subject_when_available() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_subject",
        intent_count=1,
        is_multi_intent=False,
        intents=[_intent(subject="fix token validation")],
        rendering_status="ready",
        degraded=False,
        diagnostics=[],
        metadata={},
    )

    rendered = DeterministicRenderer().render(plan)
    assert rendered.sample_id == "sample_subject"
    assert rendered.subject
    assert rendered.subject != "fix token validation"
    assert "token" in rendered.subject.lower()


def test_renderer_falls_back_conservatively_without_subject() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_fallback",
        intent_count=1,
        is_multi_intent=False,
        intents=[_intent(subject=None)],
        rendering_status="ready",
        degraded=False,
        diagnostics=[],
        metadata={},
    )

    rendered = DeterministicRenderer().render(plan)
    assert rendered.subject
    assert "SECRET_RAW_DIFF" not in rendered.subject
    assert "memory leak" not in rendered.subject.lower()


def test_renderer_marks_degraded_output_for_degraded_plan() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_degraded",
        intent_count=1,
        is_multi_intent=False,
        intents=[_intent(subject=None, file_path="docs/api.md", role="doc")],
        rendering_status="degraded",
        degraded=True,
        diagnostics=[DegradationDiagnostic(code="slot_collapse_detected", severity="warning", message="collapsed", metadata={})],
        metadata={},
    )

    rendered = DeterministicRenderer().render(plan)
    assert rendered.degraded is True
    assert rendered.diagnostics


def test_renderer_only_consumes_structured_intent_plan() -> None:
    signature = inspect.signature(DeterministicRenderer.render)
    assert "plan" in signature.parameters
    assert "raw_diff" not in signature.parameters


def test_renderer_does_not_import_external_api_clients() -> None:
    module_text = inspect.getsource(__import__("code.mica.renderers.deterministic", fromlist=["DeterministicRenderer"]))
    assert "openai" not in module_text
    assert "requests" not in module_text
    assert "httpx" not in module_text
