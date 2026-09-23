from __future__ import annotations

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
from code.mica.consumers.message_generator import DeterministicMessageGenerator


def _summary(
    slot_id: str,
    *,
    operation: str,
    target: str,
    scope: str,
    evidence_entities: list[str],
    supporting_changes: list[str] | None = None,
    confidence: float = 0.8,
    stable_order_key: tuple[str, ...] | None = None,
) -> SlotEvidenceSummary:
    return SlotEvidenceSummary(
        slot_id=slot_id,
        operation=operation,
        target=target,
        scope=scope,
        behavioral_effect=None,
        supporting_changes=supporting_changes or [],
        evidence_entities=evidence_entities,
        evidence_unit_ids=[f"{slot_id}_u1"],
        confidence=confidence,
        fallback_reason=None,
        supported_claims=[],
        stable_order_key=stable_order_key or (scope, target, slot_id),
    )


def test_generator_renders_single_intent_subject() -> None:
    candidate = DeterministicMessageGenerator().generate_candidates(
        summaries=[_summary("slot_1", operation="update", target="token validation", scope="auth", evidence_entities=["token"])],
        plan_decision="decompose",
    )[0]

    assert candidate.subject.startswith("update ")
    assert "token validation" in candidate.subject
    assert not candidate.subject.endswith(".")


def test_generator_renders_two_short_intents_in_subject() -> None:
    candidate = DeterministicMessageGenerator().generate_candidates(
        summaries=[
            _summary("slot_1", operation="update", target="token validation", scope="auth", evidence_entities=["token"]),
            _summary("slot_2", operation="document", target="API usage", scope="docs", evidence_entities=["api"]),
        ],
        plan_decision="decompose",
    )[0]

    assert " and " in candidate.subject
    assert candidate.body == []


def test_generator_renders_multi_intent_subject_with_bullets_when_needed() -> None:
    candidate = DeterministicMessageGenerator().generate_candidates(
        summaries=[
            _summary("slot_1", operation="update", target="token validation", scope="auth", evidence_entities=["token"]),
            _summary("slot_2", operation="document", target="API usage guidance", scope="docs", evidence_entities=["api"]),
            _summary("slot_3", operation="configure", target="token_ttl", scope="config", evidence_entities=["token_ttl"]),
        ],
        plan_decision="decompose",
    )[0]

    assert candidate.subject
    assert len(candidate.body) == 3
    assert all(line.startswith("- ") for line in candidate.body)


def test_generator_enforces_72_char_subject_limit_via_fallback_shape() -> None:
    candidate = DeterministicMessageGenerator().generate_candidates(
        summaries=[
            _summary(
                "slot_1",
                operation="update",
                target="extremely long token validation pipeline for authentication gateways",
                scope="auth",
                evidence_entities=["token", "gateway"],
            ),
            _summary(
                "slot_2",
                operation="document",
                target="extremely long API migration note for authentication gateway consumers",
                scope="docs",
                evidence_entities=["api", "gateway"],
            ),
        ],
        plan_decision="decompose",
    )[0]

    assert len(candidate.subject) <= 72


def test_generator_excludes_background_only_mentions() -> None:
    candidate = DeterministicMessageGenerator().generate_candidates(
        summaries=[_summary("slot_1", operation="update", target="token validation", scope="auth", evidence_entities=["token"])],
        plan_decision="decompose",
        background_terms={"lockfile", "formatting"},
    )[0]

    assert "lockfile" not in candidate.subject.lower()
    assert "formatting" not in "\n".join(candidate.body).lower()


def test_generator_is_stable_under_slot_id_permutation() -> None:
    generator = DeterministicMessageGenerator()
    left = generator.generate_candidates(
        summaries=[
            _summary(
                "slot_9",
                operation="update",
                target="token validation",
                scope="auth",
                evidence_entities=["token"],
                stable_order_key=("src/auth/token.py", "h1"),
            ),
            _summary(
                "slot_2",
                operation="document",
                target="API usage",
                scope="docs",
                evidence_entities=["api"],
                stable_order_key=("docs/api.md", "h2"),
            ),
        ],
        plan_decision="decompose",
    )[0]
    right = generator.generate_candidates(
        summaries=[
            _summary(
                "slot_1",
                operation="document",
                target="API usage",
                scope="docs",
                evidence_entities=["api"],
                stable_order_key=("docs/api.md", "h2"),
            ),
            _summary(
                "slot_7",
                operation="update",
                target="token validation",
                scope="auth",
                evidence_entities=["token"],
                stable_order_key=("src/auth/token.py", "h1"),
            ),
        ],
        plan_decision="decompose",
    )[0]

    assert left.subject == right.subject
    assert left.body == right.body
