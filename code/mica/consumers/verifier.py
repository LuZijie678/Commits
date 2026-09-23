from __future__ import annotations

from dataclasses import dataclass, field

from code.mica.consumers.evidence_summarizer import SlotEvidenceSummary
from code.mica.consumers.message_generator import GeneratedCommitMessage
from code.mica.consumers.plan_schema import StructuredIntentPlan
from code.mica.eval.entity_grounding import extract_message_entities, grounded_entity_terms
from code.mica.eval.message_coverage import intent_coverage_rate, summary_is_covered
from code.mica.eval.unsupported_claims import DEFAULT_RISKY_CLAIM_LEXICON, find_unsupported_claims


def _message_text(message: GeneratedCommitMessage) -> str:
    if message.body:
        return message.subject + "\n" + "\n".join(message.body)
    return message.subject


@dataclass(slots=True)
class SlotCoverageVerifier:
    def verify(self, *, message: GeneratedCommitMessage, summaries: list[SlotEvidenceSummary]) -> dict[str, object]:
        text = _message_text(message)
        base = intent_coverage_rate(text, summaries)
        verified_covered_slot_ids = list(base["covered_slot_ids"])
        missing_slot_ids = list(base["missing_slot_ids"])
        declared_covered_slot_ids = [str(slot_id) for slot_id in message.covered_slot_ids]
        declared_not_verified = [slot_id for slot_id in declared_covered_slot_ids if slot_id not in verified_covered_slot_ids]
        verified_not_declared = [slot_id for slot_id in verified_covered_slot_ids if slot_id not in declared_covered_slot_ids]
        return {
            "covered_slot_ids": verified_covered_slot_ids,
            "missing_slot_ids": missing_slot_ids,
            "intent_coverage_rate": base["intent_coverage_rate"],
            "declared_covered_slot_ids": declared_covered_slot_ids,
            "declared_not_verified_slot_ids": declared_not_verified,
            "verified_not_declared_slot_ids": verified_not_declared,
        }


@dataclass(slots=True)
class UnsupportedClaimVerifier:
    lexicon: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_RISKY_CLAIM_LEXICON)
    )

    def verify(self, *, message: GeneratedCommitMessage, summaries: list[SlotEvidenceSummary]) -> dict[str, object]:
        supported_claims = [claim for summary in summaries for claim in summary.supported_claims]
        unsupported = find_unsupported_claims(
            _message_text(message),
            supported_claims=supported_claims,
            lexicon=self.lexicon,
        )
        return {
            "unsupported_claims": unsupported,
            "supported_claims": sorted(set(supported_claims)),
            "claim_lexicon": sorted(self.lexicon),
        }


@dataclass(slots=True)
class EntityGroundingVerifier:
    def verify(self, *, message: GeneratedCommitMessage, summaries: list[SlotEvidenceSummary]) -> dict[str, object]:
        grounded_terms = grounded_entity_terms(
            [summary.target for summary in summaries]
            + [summary.scope for summary in summaries]
            + [entity for summary in summaries for entity in summary.evidence_entities]
        )
        mentioned_entities = extract_message_entities(_message_text(message))
        grounded_entities = [entity for entity in mentioned_entities if entity in grounded_terms]
        unsupported_entities = [entity for entity in mentioned_entities if entity not in grounded_terms]
        precision = (len(grounded_entities) / len(mentioned_entities)) if mentioned_entities else 1.0
        return {
            "mentioned_entities": mentioned_entities,
            "grounded_entities": grounded_entities,
            "unsupported_entities": unsupported_entities,
            "entity_grounding_precision": precision,
        }


@dataclass(slots=True)
class BackgroundExclusionVerifier:
    def verify(
        self,
        *,
        plan: StructuredIntentPlan,
        message: GeneratedCommitMessage,
        summaries: list[SlotEvidenceSummary],
    ) -> dict[str, object]:
        text = _message_text(message).lower()
        contract = plan.background_contract
        assigned_background_ids = {str(unit_id) for unit_id in contract["background_unit_ids"]}
        background_terms = set(str(item).lower() for item in plan.metadata.get("background_terms", []) or []) if assigned_background_ids else set()
        for record in plan.background_unit_records:
            background_terms.update(
                grounded_entity_terms(
                    [record.file_path, record.file_role or ""]
                    + list(record.changed_identifiers)
                )
            )
        foreground_terms = grounded_entity_terms(
            [summary.target for summary in summaries]
            + [summary.scope for summary in summaries]
            + [entity for summary in summaries for entity in summary.evidence_entities]
        )
        mentions = sorted(term for term in background_terms if term in text and term not in foreground_terms)
        return {
            "background_unit_ids": sorted(assigned_background_ids),
            "background_record_ids": contract["background_record_ids"],
            "evidence_incomplete": contract["evidence_incomplete"],
            "missing_record_ids": contract["missing_record_ids"],
            "background_terms": sorted(background_terms),
            "background_mentions": mentions,
        }


@dataclass(slots=True)
class FormatVerifier:
    max_subject_length: int = 72

    def verify(self, *, message: GeneratedCommitMessage) -> dict[str, object]:
        errors: list[str] = []
        warnings: list[str] = []
        subject = str(message.subject or "")
        if not subject.strip():
            errors.append("empty_subject")
        if len(subject) > self.max_subject_length:
            errors.append("subject_too_long")
        if subject.endswith("."):
            errors.append("subject_ends_with_period")
        normalized_body = [line.strip() for line in message.body if line.strip()]
        if len(normalized_body) != len(set(normalized_body)):
            errors.append("duplicate_body_bullets")
        if subject.lower() in {"misc changes", "various updates", "update related changes"} and not normalized_body:
            errors.append("generic_fallback_without_body")
        if any(not line.startswith("- ") for line in normalized_body):
            warnings.append("body_lines_should_start_with_bullet_prefix")
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }
