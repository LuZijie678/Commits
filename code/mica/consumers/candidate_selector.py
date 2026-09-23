from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from code.mica.consumers.message_generator import GeneratedCommitMessage


def _clone_candidate(candidate: GeneratedCommitMessage, *, subject: str | None = None) -> GeneratedCommitMessage:
    return GeneratedCommitMessage(
        subject=subject if subject is not None else candidate.subject,
        body=list(candidate.body),
        covered_slot_ids=list(candidate.covered_slot_ids),
        mentioned_entities=list(candidate.mentioned_entities),
        generator_type=candidate.generator_type,
        generator_version=candidate.generator_version,
        diagnostics=dict(candidate.diagnostics),
        status=candidate.status,
    )


@dataclass(slots=True)
class CandidateSelector:
    unsupported_entity_threshold: float = 0.34

    def select(
        self,
        evaluated_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for item in evaluated_candidates:
            candidate = item["candidate"]
            verification = item["verification"]
            repaired = self._repair(candidate, verification)
            if repaired is not candidate:
                item = dict(item)
                item["candidate"] = repaired
                item["verification"] = dict(verification)
                format_result = dict(verification["format"])
                format_result["errors"] = [error for error in format_result["errors"] if error != "subject_ends_with_period"]
                format_result["valid"] = len(format_result["errors"]) == 0
                item["verification"]["format"] = format_result
                candidate = repaired
                verification = item["verification"]
            rejection_reasons = self._rejection_reasons(verification)
            score = self._score(verification)
            item["score"] = score
            item["rejection_reasons"] = rejection_reasons
            if rejection_reasons:
                rejected.append(item)
            else:
                accepted.append(item)
        pool = accepted or rejected
        if not pool:
            return {
                "accepted": False,
                "candidate": None,
                "verification": {},
                "fallback_level": None,
                "rejection_reason": "no_candidates",
            }
        best = max(pool, key=lambda item: item["score"])
        return {
            "accepted": not best["rejection_reasons"],
            "candidate": best["candidate"],
            "verification": best["verification"],
            "fallback_level": best["candidate"].diagnostics.get("fallback_level"),
            "rejection_reason": ", ".join(best["rejection_reasons"]) if best["rejection_reasons"] else None,
        }

    def _repair(self, candidate: GeneratedCommitMessage, verification: dict[str, Any]) -> GeneratedCommitMessage:
        if "subject_ends_with_period" in verification["format"]["errors"]:
            return _clone_candidate(candidate, subject=candidate.subject.rstrip("."))
        return candidate

    def _rejection_reasons(self, verification: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        coverage = verification["slot_coverage"]
        if coverage.get("missing_slot_ids"):
            reasons.append("missing_foreground_slot")
        if verification["unsupported_claims"].get("unsupported_claims"):
            reasons.append("unsupported_claim")
        grounding = verification["entity_grounding"]
        unsupported_entities = list(grounding.get("unsupported_entities", []))
        if unsupported_entities and len(unsupported_entities) / max(len(grounding.get("mentioned_entities", [])), 1) > self.unsupported_entity_threshold:
            reasons.append("unsupported_entity_threshold")
        if verification["background_exclusion"].get("background_mentions"):
            reasons.append("background_only_mention")
        if not verification["format"].get("valid", False):
            reasons.append("format_invalid")
        return reasons

    def _score(self, verification: dict[str, Any]) -> float:
        coverage = float(verification["slot_coverage"].get("intent_coverage_rate", 0.0))
        unsupported_claim_penalty = 0.5 * len(verification["unsupported_claims"].get("unsupported_claims", []))
        missing_penalty = 0.5 * len(verification["slot_coverage"].get("missing_slot_ids", []))
        background_penalty = 0.3 * len(verification["background_exclusion"].get("background_mentions", []))
        format_penalty = 0.25 * len(verification["format"].get("errors", []))
        unsupported_entities = verification["entity_grounding"].get("unsupported_entities", [])
        entity_penalty = 0.1 * len(unsupported_entities)
        return coverage - unsupported_claim_penalty - missing_penalty - background_penalty - format_penalty - entity_penalty
