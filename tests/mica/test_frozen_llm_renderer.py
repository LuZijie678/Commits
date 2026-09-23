from __future__ import annotations

import json

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
import pytest

from code.mica.consumers.message_generator import FrozenLLMRenderer, NotConfiguredError
from code.mica.consumers.pipeline import ConsumerPipeline
from code.mica.consumers.plan_schema import EvidenceUnit, IntentPlan, StructuredIntentPlan


def _summary() -> SlotEvidenceSummary:
    return SlotEvidenceSummary(
        slot_id="slot_1",
        operation="update",
        target="token validation",
        scope="auth",
        behavioral_effect=None,
        supporting_changes=["update tests in tests/test_token.py"],
        evidence_entities=["token", "validate_token", "auth"],
        evidence_unit_ids=["u1", "u2"],
        confidence=0.91,
        stable_order_key=("src/auth/token.py", "h_u1", "token validation"),
    )


def _plan(*, decision: str = "decompose") -> StructuredIntentPlan:
    return StructuredIntentPlan(
        sample_id="consumer-llm-case",
        decision=decision,
        predicted_k=1 if decision == "decompose" else 0,
        overall_confidence=0.91 if decision == "decompose" else None,
        intents=(
            [
                IntentPlan(
                    slot_id="slot_1",
                    slot_confidence=0.91,
                    assigned_unit_ids=["u1", "u2"],
                    assigned_hunk_ids=["h_u1", "h_u2"],
                    files=["src/auth/token.py", "tests/test_token.py"],
                    changed_symbols=["validate_token"],
                    changed_identifiers=["token", "validate_token"],
                    file_roles=["source", "test"],
                    evidence=[
                        EvidenceUnit(
                            unit_id="u1",
                            hunk_id="h_u1",
                            file_path="src/auth/token.py",
                            file_role="source",
                            language="python",
                            enclosing_symbol="validate_token",
                            patch_text="@@ -1 +1 @@\n- old\n+ new",
                            added_lines=["+ validate_token(token)"],
                            deleted_lines=["- validate_token(token)"],
                            changed_identifiers=["token", "validate_token"],
                        ),
                        EvidenceUnit(
                            unit_id="u2",
                            hunk_id="h_u2",
                            file_path="tests/test_token.py",
                            file_role="test",
                            language="python",
                            enclosing_symbol="test_validate_token",
                            patch_text="@@ -1 +1 @@\n- old\n+ new",
                            added_lines=["+ test_validate_token()"],
                            deleted_lines=["- test_validate_token()"],
                            changed_identifiers=["token"],
                        ),
                    ],
                    action="update",
                    object="token validation",
                    scope="auth",
                )
            ]
            if decision == "decompose"
            else []
        ),
        background_units=[],
        uncertain_units=[],
        metadata={},
    )


def _llm_config(tmp_path) -> dict[str, object]:
    return {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_TEST_KEY",
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "top_p": 1.0,
        "max_output_tokens": 64,
        "max_retries": 0,
        "timeout_seconds": 10,
        "thinking": {"type": "disabled"},
        "cache_path": str(tmp_path / "llm_cache.json"),
    }


def test_frozen_llm_renderer_uses_openai_compatible_backend_without_leakage(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "Update token validation"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    generator = FrozenLLMRenderer(config=_llm_config(tmp_path), allow_real_api=True)

    candidates = generator.generate_candidates([_summary()], plan_decision="decompose", background_terms={"lockfile"})

    assert len(candidates) == 1
    assert candidates[0].subject == "Update token validation"
    prompt = captured["body"]["messages"][0]["content"]
    assert "@@" not in prompt
    assert "commit message" not in prompt.lower()
    assert "pr title" not in prompt.lower()
    assert "issue text" not in prompt.lower()
    assert "synthetic" not in prompt.lower()


def test_pipeline_falls_back_when_frozen_llm_candidate_is_rejected(tmp_path, monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "Improve performance of token validation"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            ).encode("utf-8")

    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: FakeResponse())
    pipeline = ConsumerPipeline(
        frozen_llm_renderer=FrozenLLMRenderer(config=_llm_config(tmp_path), allow_real_api=True)
    )

    result = pipeline.generate(structured_plan=_plan(), mode="frozen_llm", verify=True)

    assert result.status == "success"
    assert result.message is not None
    assert "performance" not in result.message.subject.lower()
    assert result.generator_metadata["mode"] == "frozen_llm"
    assert result.generator_metadata["llm_attempted"] is True


def test_pipeline_does_not_call_frozen_llm_for_abstain_or_overflow(tmp_path, monkeypatch) -> None:
    attempts = {"count": 0}

    def fake_urlopen(request, timeout=0):
        attempts["count"] += 1
        raise AssertionError("urlopen should not be called for abstain/overflow plans")

    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    pipeline = ConsumerPipeline(
        frozen_llm_renderer=FrozenLLMRenderer(config=_llm_config(tmp_path), allow_real_api=True)
    )

    abstain = pipeline.generate(structured_plan=_plan(decision="abstain"), mode="frozen_llm", verify=True)
    overflow = pipeline.generate(structured_plan=_plan(decision="overflow"), mode="frozen_llm", verify=True)

    assert abstain.status == "rejected"
    assert overflow.status == "rejected"
    assert attempts["count"] == 0


def test_frozen_llm_renderer_rejects_disabled_config(tmp_path) -> None:
    disabled = _llm_config(tmp_path)
    disabled["enabled"] = False

    with pytest.raises(NotConfiguredError, match="disabled"):
        FrozenLLMRenderer(config=disabled, allow_real_api=True)
