from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from code.mica.consumers.candidate_selector import CandidateSelector
from code.mica.consumers.evidence_summarizer import DeterministicEvidenceSummarizer, SlotEvidenceSummary
from code.mica.consumers.message_generator import (
    DeterministicMessageGenerator,
    FrozenLLMRenderer,
    GeneratedCommitMessage,
    NotConfiguredError,
)
from code.mica.consumers.plan_schema import StructuredIntentPlan, adapt_from_legacy_plan
from code.mica.consumers.verifier import (
    BackgroundExclusionVerifier,
    EntityGroundingVerifier,
    FormatVerifier,
    SlotCoverageVerifier,
    UnsupportedClaimVerifier,
)
from code.mica.schemas import StructuredIntentPlan as LegacyStructuredIntentPlan


@dataclass(slots=True)
class ConsumerResult:
    schema_version: str
    status: str
    message: GeneratedCommitMessage | None
    summaries: list[SlotEvidenceSummary]
    verification: dict[str, Any]
    generator_metadata: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "message": self.message.to_dict() if self.message else None,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "verification": dict(self.verification),
            "generator_metadata": dict(self.generator_metadata),
            "fallback": dict(self.fallback),
            "errors": list(self.errors),
        }


class ConsumerPipeline:
    """Frozen structured-plan consumer: summarize, render, verify, and select."""

    def __init__(
        self,
        *,
        summarizer: DeterministicEvidenceSummarizer | None = None,
        generator: Any | None = None,
        frozen_llm_renderer: FrozenLLMRenderer | None = None,
        slot_coverage_verifier: SlotCoverageVerifier | None = None,
        unsupported_claim_verifier: UnsupportedClaimVerifier | None = None,
        entity_grounding_verifier: EntityGroundingVerifier | None = None,
        background_exclusion_verifier: BackgroundExclusionVerifier | None = None,
        format_verifier: FormatVerifier | None = None,
        selector: CandidateSelector | None = None,
    ) -> None:
        self.summarizer = summarizer or DeterministicEvidenceSummarizer()
        self.generator = generator or DeterministicMessageGenerator()
        self.frozen_llm_renderer = frozen_llm_renderer
        self.slot_coverage_verifier = slot_coverage_verifier or SlotCoverageVerifier()
        self.unsupported_claim_verifier = unsupported_claim_verifier or UnsupportedClaimVerifier()
        self.entity_grounding_verifier = entity_grounding_verifier or EntityGroundingVerifier()
        self.background_exclusion_verifier = background_exclusion_verifier or BackgroundExclusionVerifier()
        self.format_verifier = format_verifier or FormatVerifier()
        self.selector = selector or CandidateSelector()

    def generate(
        self,
        *,
        structured_plan: StructuredIntentPlan | LegacyStructuredIntentPlan | dict[str, Any],
        mode: str = "deterministic",
        verify: bool = True,
    ) -> ConsumerResult:
        try:
            plan = self._coerce_plan(structured_plan)
        except Exception as exc:  # noqa: BLE001 - caller needs explicit invalid-plan diagnostics.
            return ConsumerResult(
                schema_version="mica-consumer-result-v1",
                status="invalid_plan",
                message=None,
                summaries=[],
                verification={},
                generator_metadata={"mode": mode},
                fallback={},
                errors=[str(exc)],
            )

        if plan.decision != "decompose":
            return ConsumerResult(
                schema_version="mica-consumer-result-v1",
                status="rejected",
                message=None,
                summaries=[],
                verification={"decision": plan.decision, "risk_score": plan.risk_score},
                generator_metadata={"mode": mode},
                fallback={"fallback_used": False, "fallback_level": None, "rejection_reason": f"decision={plan.decision}"},
                errors=[f"decision={plan.decision}"],
            )

        summaries = [self.summarizer.summarize(intent) for intent in plan.intents]
        background_terms = self._background_terms(plan)
        candidates, generator_metadata = self._generate_candidates(
            summaries=summaries,
            plan_decision=plan.decision,
            background_terms=background_terms,
            mode=mode,
        )
        if not candidates:
            return ConsumerResult(
                schema_version="mica-consumer-result-v1",
                status="rejected",
                message=None,
                summaries=summaries,
                verification={},
                generator_metadata=generator_metadata,
                fallback={"fallback_used": False, "fallback_level": None, "rejection_reason": "no_candidates"},
                errors=["no_candidates"],
            )
        if not verify:
            winner = candidates[0]
            return ConsumerResult(
                schema_version="mica-consumer-result-v1",
                status="success",
                message=winner,
                summaries=summaries,
                verification={},
                generator_metadata={**generator_metadata, "candidate_count": len(candidates)},
                fallback={"fallback_used": bool(winner.diagnostics.get("fallback_level")), "fallback_level": winner.diagnostics.get("fallback_level")},
                errors=[],
            )

        evaluated: list[dict[str, Any]] = []
        for candidate in candidates:
            verification_result = self._verify_candidate(plan=plan, message=candidate, summaries=summaries)
            evaluated.append({"candidate": candidate, "verification": verification_result})
        selected = self.selector.select(evaluated)
        accepted = bool(selected["accepted"])
        candidate = selected["candidate"]
        verification_result = dict(selected["verification"])
        if accepted and candidate is not None:
            return ConsumerResult(
                schema_version="mica-consumer-result-v1",
                status="success",
                message=candidate,
                summaries=summaries,
                verification=verification_result,
                generator_metadata={**generator_metadata, "candidate_count": len(candidates)},
                fallback={
                    "fallback_used": int(candidate.diagnostics.get("fallback_level", 0)) > 0,
                    "fallback_level": candidate.diagnostics.get("fallback_level"),
                    "rejection_reason": None,
                },
                errors=[],
            )
        return ConsumerResult(
            schema_version="mica-consumer-result-v1",
            status="rejected",
            message=None,
            summaries=summaries,
            verification=verification_result,
            generator_metadata={**generator_metadata, "candidate_count": len(candidates)},
            fallback={
                "fallback_used": False,
                "fallback_level": selected.get("fallback_level"),
                "rejection_reason": selected.get("rejection_reason") or "verification_failed",
            },
            errors=[selected.get("rejection_reason") or "verification_failed"],
        )

    def _coerce_plan(self, payload: StructuredIntentPlan | LegacyStructuredIntentPlan | dict[str, Any]) -> StructuredIntentPlan:
        if isinstance(payload, StructuredIntentPlan):
            return payload
        if isinstance(payload, LegacyStructuredIntentPlan):
            return adapt_from_legacy_plan(payload)
        if "decision" in payload:
            return StructuredIntentPlan.from_dict(payload)
        return adapt_from_legacy_plan(payload)

    def _background_terms(self, plan: StructuredIntentPlan) -> set[str]:
        if not plan.background_units:
            return set()
        terms = set(str(item).lower() for item in plan.metadata.get("background_terms", []) or [])
        for record in plan.background_unit_records:
            file_path = str(record.file_path).lower()
            file_role = str(record.file_role or "").lower()
            changed_identifiers = [str(item).lower() for item in record.changed_identifiers]
            terms.update(token for token in file_path.replace("/", " ").replace(".", " ").split() if token)
            if file_role:
                terms.add(file_role)
            terms.update(changed_identifiers)
        return terms

    def _generate_candidates(
        self,
        *,
        summaries: list[SlotEvidenceSummary],
        plan_decision: str,
        background_terms: set[str],
        mode: str,
    ) -> tuple[list[GeneratedCommitMessage], dict[str, Any]]:
        metadata: dict[str, Any] = {"mode": mode, "llm_attempted": False}
        deterministic_candidates = self.generator.generate_candidates(
            summaries,
            plan_decision=plan_decision,
            background_terms=background_terms,
        )
        if mode != "frozen_llm":
            return deterministic_candidates, metadata
        llm_candidates: list[GeneratedCommitMessage] = []
        if self.frozen_llm_renderer is None:
            metadata["llm_status"] = "not_configured"
            return deterministic_candidates, metadata
        metadata["llm_attempted"] = True
        try:
            llm_candidates = self.frozen_llm_renderer.generate_candidates(
                summaries,
                plan_decision=plan_decision,
                background_terms=background_terms,
            )
            metadata["llm_status"] = "generated" if llm_candidates else "empty"
        except NotConfiguredError as exc:
            metadata["llm_status"] = "not_configured"
            metadata["llm_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - keep deterministic fallback active.
            metadata["llm_status"] = "failed"
            metadata["llm_error"] = str(exc)
        return llm_candidates + deterministic_candidates, metadata

    def _verify_candidate(
        self,
        *,
        plan: StructuredIntentPlan,
        message: GeneratedCommitMessage,
        summaries: list[SlotEvidenceSummary],
    ) -> dict[str, Any]:
        return {
            "slot_coverage": self.slot_coverage_verifier.verify(message=message, summaries=summaries),
            "unsupported_claims": self.unsupported_claim_verifier.verify(message=message, summaries=summaries),
            "entity_grounding": self.entity_grounding_verifier.verify(message=message, summaries=summaries),
            "background_exclusion": self.background_exclusion_verifier.verify(plan=plan, message=message, summaries=summaries),
            "format": self.format_verifier.verify(message=message),
        }
