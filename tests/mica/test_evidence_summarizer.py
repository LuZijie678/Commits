from __future__ import annotations

from code.mica.consumers.evidence_summarizer import DeterministicEvidenceSummarizer
from code.mica.consumers.plan_schema import EvidenceUnit, IntentPlan


def _intent(
    *,
    slot_id: str = "slot_1",
    evidence: list[EvidenceUnit],
    action: str | None = None,
    object_value: str | None = None,
    scope: str | None = None,
) -> IntentPlan:
    return IntentPlan(
        slot_id=slot_id,
        slot_confidence=0.81,
        assigned_unit_ids=[unit.unit_id for unit in evidence],
        assigned_hunk_ids=[unit.hunk_id for unit in evidence if unit.hunk_id],
        files=[unit.file_path for unit in evidence],
        changed_symbols=[unit.enclosing_symbol for unit in evidence if unit.enclosing_symbol],
        changed_identifiers=[identifier for unit in evidence for identifier in unit.changed_identifiers],
        file_roles=[unit.file_role for unit in evidence if unit.file_role],
        evidence=evidence,
        action=action,
        object=object_value,
        scope=scope,
    )


def _evidence(
    unit_id: str,
    *,
    file_path: str,
    file_role: str,
    patch_text: str,
    language: str | None = "python",
    enclosing_symbol: str | None = None,
    changed_identifiers: list[str] | None = None,
    added_lines: list[str] | None = None,
    deleted_lines: list[str] | None = None,
) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        hunk_id=f"h_{unit_id}",
        file_path=file_path,
        file_role=file_role,
        language=language,
        enclosing_symbol=enclosing_symbol,
        patch_text=patch_text,
        added_lines=added_lines or ["+ new_line"],
        deleted_lines=deleted_lines or ["- old_line"],
        changed_identifiers=changed_identifiers or [],
    )


def test_summarizer_handles_source_and_test_in_same_slot() -> None:
    summarizer = DeterministicEvidenceSummarizer()
    intent = _intent(
        evidence=[
            _evidence(
                "u1",
                file_path="src/auth/token.py",
                file_role="source",
                patch_text="+ validate_token",
                enclosing_symbol="validate_token",
                changed_identifiers=["token", "validate_token"],
            ),
            _evidence(
                "u2",
                file_path="tests/test_token.py",
                file_role="test",
                patch_text="+ test_validate_token",
                enclosing_symbol="test_validate_token",
                changed_identifiers=["token"],
            ),
        ],
        action="update",
        object_value="token validation",
        scope="auth",
    )

    summary = summarizer.summarize(intent)

    assert summary.operation == "update"
    assert "token validation" in summary.target
    assert any("test" in item.lower() for item in summary.supporting_changes)


def test_summarizer_handles_docs_only_intent() -> None:
    summary = DeterministicEvidenceSummarizer().summarize(
        _intent(
            evidence=[
                _evidence(
                    "u1",
                    file_path="docs/api/auth.md",
                    file_role="doc",
                    patch_text="+ auth token docs",
                    language="markdown",
                    changed_identifiers=["auth", "token"],
                )
            ]
        )
    )

    assert summary.operation == "document"
    assert "doc" in summary.scope.lower() or "api" in summary.target.lower()


def test_summarizer_handles_config_intent() -> None:
    summary = DeterministicEvidenceSummarizer().summarize(
        _intent(
            evidence=[
                _evidence(
                    "u1",
                    file_path="config/auth.yaml",
                    file_role="config",
                    patch_text="+ token_ttl: 60",
                    language="yaml",
                    changed_identifiers=["token_ttl"],
                )
            ]
        )
    )

    assert summary.operation == "configure"
    assert "token_ttl" in " ".join(summary.evidence_entities)


def test_summarizer_uses_no_symbol_fallback() -> None:
    summary = DeterministicEvidenceSummarizer().summarize(
        _intent(
            evidence=[
                _evidence(
                    "u1",
                    file_path="src/auth/token_manager.py",
                    file_role="source",
                    patch_text="+ manager",
                    enclosing_symbol=None,
                    changed_identifiers=["token_manager"],
                )
            ]
        )
    )

    assert "token_manager" in summary.target or "token" in summary.target


def test_summarizer_does_not_invent_risky_fix_claim() -> None:
    summary = DeterministicEvidenceSummarizer().summarize(
        _intent(
            evidence=[
                _evidence(
                    "u1",
                    file_path="src/auth/token.py",
                    file_role="source",
                    patch_text="+ if token:",
                    enclosing_symbol="validate_token",
                    changed_identifiers=["token"],
                )
            ]
        )
    )

    assert summary.operation != "fix"
    assert summary.behavioral_effect is None


def test_summarizer_handles_unknown_language_and_empty_identifiers() -> None:
    summary = DeterministicEvidenceSummarizer().summarize(
        _intent(
            evidence=[
                _evidence(
                    "u1",
                    file_path="src/legacy/handler.unknown",
                    file_role="source",
                    patch_text="+ opaque change",
                    language=None,
                    enclosing_symbol=None,
                    changed_identifiers=[],
                )
            ]
        )
    )

    assert summary.target
    assert summary.fallback_reason is not None


def test_summarizer_is_deterministic_for_same_input() -> None:
    summarizer = DeterministicEvidenceSummarizer()
    intent = _intent(
        evidence=[
            _evidence(
                "u1",
                file_path="src/auth/token.py",
                file_role="source",
                patch_text="+ validate_token",
                enclosing_symbol="validate_token",
                changed_identifiers=["token"],
            )
        ]
    )

    first = summarizer.summarize(intent).to_dict()
    second = summarizer.summarize(intent).to_dict()

    assert first == second
