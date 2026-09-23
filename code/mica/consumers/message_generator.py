from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
from code.mica.llm_backend_config import validate_llm_backend_config


GENERIC_MULTI_INTENT_SUBJECT = "update multiple intent areas"


def _truncate_subject(subject: str, limit: int) -> str:
    normalized = " ".join(subject.split()).strip()
    if len(normalized) <= limit:
        return normalized
    truncated = normalized[: limit - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.strip()


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip()
        if token and token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


@dataclass(slots=True)
class GeneratedCommitMessage:
    subject: str
    body: list[str]
    covered_slot_ids: list[str]
    mentioned_entities: list[str]
    generator_type: str
    generator_version: str
    diagnostics: dict[str, object] = field(default_factory=dict)
    status: str = "success"

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "body": list(self.body),
            "covered_slot_ids": list(self.covered_slot_ids),
            "mentioned_entities": list(self.mentioned_entities),
            "generator_type": self.generator_type,
            "generator_version": self.generator_version,
            "diagnostics": dict(self.diagnostics),
            "status": self.status,
        }


class NotConfiguredError(RuntimeError):
    """Raised when an optional frozen external renderer is requested but not configured."""


class FrozenLLMRenderer:
    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        allow_real_api: bool = False,
        dry_run: bool = False,
        generator_version: str = "frozen-llm-v1",
    ) -> None:
        self.config = dict(config or {})
        self.allow_real_api = bool(allow_real_api)
        self.dry_run = bool(dry_run)
        self.generator_version = generator_version
        if not self.config:
            raise NotConfiguredError("FrozenLLMRenderer requires explicit backend config.")
        validation = validate_llm_backend_config(self.config, require_enabled=True)
        if not validation["valid"]:
            if "backend_disabled" in validation["errors"]:
                raise NotConfiguredError("FrozenLLMRenderer config is disabled.")
            raise NotConfiguredError("; ".join(validation["errors"]))

    def generate_candidates(
        self,
        summaries: list[SlotEvidenceSummary],
        *,
        plan_decision: str,
        background_terms: set[str] | None = None,
    ) -> list[GeneratedCommitMessage]:
        if plan_decision != "decompose":
            return []
        if not summaries:
            return []
        backend = self._build_backend()
        prompt = self._build_prompt(summaries, background_terms=background_terms or set())
        result = backend.generate(prompt)
        subject = " ".join(str(result.get("generated_subject", "")).split()).strip()
        if str(result.get("status")) != "generated" or not subject:
            return []
        return [
            GeneratedCommitMessage(
                subject=subject.rstrip("."),
                body=[],
                covered_slot_ids=[summary.slot_id for summary in summaries],
                mentioned_entities=_dedupe_preserve(
                    [summary.target for summary in summaries]
                    + [summary.scope for summary in summaries]
                    + [entity for summary in summaries for entity in summary.evidence_entities]
                ),
                generator_type="frozen_llm",
                generator_version=self.generator_version,
                diagnostics={
                    "backend_status": result.get("status"),
                    "retry_count": result.get("retry_count"),
                    "http_status": result.get("http_status"),
                    "latency_ms": result.get("latency_ms"),
                    "fallback_level": 0,
                },
                status="success",
            )
        ]

    def _build_backend(self):  # type: ignore[no-untyped-def]
        from code.generation.llm_backend import LLMBackend

        return LLMBackend(self.config, allow_real_api=self.allow_real_api, dry_run=self.dry_run)

    def _build_prompt(self, summaries: list[SlotEvidenceSummary], *, background_terms: set[str]) -> str:
        lines = [
            "Write one imperative subject line using only the frozen structured evidence below.",
            "Do not use any information outside the listed slot summaries.",
            "Do not mention background-only terms.",
            "Do not claim performance, security, crash prevention, reliability, or breaking change unless directly supported.",
            "Return only the subject line.",
            "",
            "Slot summaries:",
        ]
        for index, summary in enumerate(sorted(summaries, key=lambda item: item.stable_order_key), 1):
            lines.append(f"{index}. operation: {summary.operation}")
            lines.append(f"   target: {summary.target}")
            lines.append(f"   scope: {summary.scope}")
            if summary.supporting_changes:
                lines.append(f"   supporting changes: {'; '.join(summary.supporting_changes[:3])}")
            if summary.evidence_entities:
                lines.append(f"   evidence entities: {', '.join(summary.evidence_entities[:8])}")
            lines.append(f"   evidence unit ids: {', '.join(summary.evidence_unit_ids[:8])}")
        if background_terms:
            lines.extend(
                [
                    "",
                    f"Background-only terms to avoid: {', '.join(sorted(background_terms)[:12])}",
                ]
            )
        return "\n".join(lines).strip() + "\n"


class DeterministicMessageGenerator:
    """Deterministic, evidence-locked message generator with fixed fallback levels."""

    def __init__(self, *, max_subject_length: int = 72, generator_version: str = "deterministic-v1") -> None:
        self.max_subject_length = max_subject_length
        self.generator_version = generator_version

    def generate_candidates(
        self,
        summaries: list[SlotEvidenceSummary],
        *,
        plan_decision: str,
        background_terms: set[str] | None = None,
    ) -> list[GeneratedCommitMessage]:
        if plan_decision != "decompose":
            return []
        ordered = sorted(summaries, key=lambda summary: summary.stable_order_key)
        return [
            self._primary_candidate(ordered),
            self._conservative_candidate(ordered),
            self._minimal_candidate(ordered),
        ]

    def _primary_candidate(self, summaries: list[SlotEvidenceSummary]) -> GeneratedCommitMessage:
        phrases = [self._summary_phrase(summary, minimal=False) for summary in summaries]
        if len(phrases) == 1:
            subject = phrases[0]
            body: list[str] = []
            if summaries[0].supporting_changes:
                body = [f"- {change}" for change in summaries[0].supporting_changes]
        elif len(phrases) == 2 and len(f"{phrases[0]} and {phrases[1]}") <= self.max_subject_length:
            subject = f"{phrases[0]} and {phrases[1]}"
            body = []
        else:
            subject = self._aggregate_subject(summaries)
            body = [f"- {self._summary_bullet(summary, include_support=True)}" for summary in summaries]
        return self._build_candidate(subject=subject, body=body, summaries=summaries, fallback_level=0)

    def _conservative_candidate(self, summaries: list[SlotEvidenceSummary]) -> GeneratedCommitMessage:
        subject = _truncate_subject(GENERIC_MULTI_INTENT_SUBJECT if len(summaries) > 1 else self._summary_phrase(summaries[0], minimal=True), self.max_subject_length)
        body = [f"- {self._summary_bullet(summary, include_support=False)}" for summary in summaries]
        return self._build_candidate(subject=subject, body=body, summaries=summaries, fallback_level=1)

    def _minimal_candidate(self, summaries: list[SlotEvidenceSummary]) -> GeneratedCommitMessage:
        if len(summaries) == 1:
            subject = self._summary_phrase(summaries[0], minimal=True)
            body: list[str] = []
        else:
            subject = _truncate_subject(GENERIC_MULTI_INTENT_SUBJECT, self.max_subject_length)
            body = [f"- {summary.operation} {summary.target}".strip() for summary in summaries]
        return self._build_candidate(subject=subject, body=body, summaries=summaries, fallback_level=2)

    def _build_candidate(
        self,
        *,
        subject: str,
        body: list[str],
        summaries: list[SlotEvidenceSummary],
        fallback_level: int,
    ) -> GeneratedCommitMessage:
        clean_subject = _truncate_subject(subject.rstrip("."), self.max_subject_length)
        mentioned_entities = _dedupe_preserve(
            [summary.target for summary in summaries]
            + [summary.scope for summary in summaries]
            + [entity for summary in summaries for entity in summary.evidence_entities]
        )
        return GeneratedCommitMessage(
            subject=clean_subject,
            body=[line.rstrip(".") for line in body],
            covered_slot_ids=[summary.slot_id for summary in summaries],
            mentioned_entities=mentioned_entities,
            generator_type="deterministic",
            generator_version=self.generator_version,
            diagnostics={"fallback_level": fallback_level, "summary_count": len(summaries)},
        )

    def _aggregate_subject(self, summaries: list[SlotEvidenceSummary]) -> str:
        if not summaries:
            return GENERIC_MULTI_INTENT_SUBJECT
        first = summaries[0]
        if first.scope and first.scope not in {"code", "docs", "config"}:
            return _truncate_subject(f"{first.operation} {first.scope} and related intent areas", self.max_subject_length)
        return _truncate_subject(GENERIC_MULTI_INTENT_SUBJECT, self.max_subject_length)

    def _summary_phrase(self, summary: SlotEvidenceSummary, *, minimal: bool) -> str:
        target = summary.target or "assigned changes"
        phrase = f"{summary.operation} {target}"
        if summary.scope and summary.scope not in {"code", "docs", "config"} and summary.scope.lower() not in target.lower():
            phrase = f"{phrase} in {summary.scope}"
        if not minimal and summary.behavioral_effect:
            phrase = f"{phrase} to {summary.behavioral_effect}"
        return _truncate_subject(" ".join(phrase.split()).rstrip("."), self.max_subject_length)

    def _summary_bullet(self, summary: SlotEvidenceSummary, *, include_support: bool) -> str:
        bullet = self._summary_phrase(summary, minimal=False)
        if include_support and summary.supporting_changes:
            bullet = f"{bullet} ({'; '.join(summary.supporting_changes[:2])})"
        return bullet.rstrip(".")
