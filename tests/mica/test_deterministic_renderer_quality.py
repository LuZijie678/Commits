from __future__ import annotations

from code.mica.renderers.deterministic import DeterministicRenderer
from code.mica.schemas import EditUnitRecord, StructuredIntent, StructuredIntentPlan


def test_deterministic_renderer_uses_evidence_locked_subject_and_bullets() -> None:
    renderer = DeterministicRenderer()
    plan = StructuredIntentPlan(
        sample_id="s1",
        intent_count=2,
        is_multi_intent=True,
        intents=[
            StructuredIntent(
                intent_id="i1",
                slot_id="slot_1",
                edit_unit_ids=["u1"],
                evidence_units=[EditUnitRecord(unit_id="u1", file_path="src/auth.py", changed_identifiers=["token"], file_role="source")],
                type="update",
                scope="auth",
                subject="update auth token handling",
            ),
            StructuredIntent(
                intent_id="i2",
                slot_id="slot_2",
                edit_unit_ids=["u2"],
                evidence_units=[EditUnitRecord(unit_id="u2", file_path="tests/auth_test.py", changed_identifiers=["token"], file_role="test")],
                type="update",
                scope="tests",
                subject="update auth token tests",
            ),
        ],
    )

    rendered = renderer.render(plan)

    assert rendered.subject
    assert rendered.subject != "update auth token handling and update auth token tests"
    assert "token" in rendered.subject
    assert len(rendered.bullets) >= 1
    assert "memory leak" not in rendered.subject.lower()


def test_deterministic_renderer_falls_back_conservatively_on_degraded_plan() -> None:
    renderer = DeterministicRenderer()
    plan = StructuredIntentPlan(sample_id="s2", intent_count=1, is_multi_intent=False, intents=[], degraded=True)

    rendered = renderer.render(plan)

    assert rendered.degraded is True
    assert rendered.subject in {"update related changes", "update source changes"}
