from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONSUMER_EVAL_ROW_SCHEMA_VERSION = "mica-consumer-eval-row-v1"
CONSUMER_EVAL_AGGREGATE_SCHEMA_VERSION = "mica-consumer-eval-aggregate-v1"
CONSUMER_RUN_COMPARISON_SCHEMA_VERSION = "mica-consumer-comparison-v1"
HUMAN_PILOT_CANDIDATE_SCHEMA_VERSION = "mica-human-pilot-candidate-v1"
HUMAN_PILOT_MAPPING_SCHEMA_VERSION = "mica-human-pilot-mapping-v1"
CONSUMER_RUN_COMPARISON_SCHEMA_VERSION = "mica-consumer-comparison-v1"


@dataclass(slots=True)
class ConsumerEvaluationRecord:
    sample_id: str
    commit_id: str | None
    status: str
    decision: str | None
    plan_source: str
    predicted_k: int | None
    gold_k: int | None
    message: dict[str, Any] | None
    verification: dict[str, Any]
    fallback: dict[str, Any]
    errors: list[Any] = field(default_factory=list)
    background_contract: dict[str, Any] = field(default_factory=dict)
    verification_eligible: bool = False
    excluded_reason: str | None = None
    strata: dict[str, Any] = field(default_factory=dict)
    input_contract: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONSUMER_EVAL_ROW_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "commit_id": self.commit_id,
            "status": self.status,
            "decision": self.decision,
            "plan_source": self.plan_source,
            "predicted_k": self.predicted_k,
            "gold_k": self.gold_k,
            "message": dict(self.message) if self.message is not None else None,
            "verification": dict(self.verification),
            "fallback": dict(self.fallback),
            "errors": list(self.errors),
            "background_contract": dict(self.background_contract),
            "verification_eligible": self.verification_eligible,
            "excluded_reason": self.excluded_reason,
            "strata": dict(self.strata),
            "input_contract": dict(self.input_contract),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConsumerEvaluationRecord:
        return cls(
            schema_version=str(payload.get("schema_version", CONSUMER_EVAL_ROW_SCHEMA_VERSION)),
            sample_id=str(payload.get("sample_id", "")),
            commit_id=str(payload.get("commit_id")) if payload.get("commit_id") is not None else None,
            status=str(payload.get("status", "")),
            decision=str(payload.get("decision")) if payload.get("decision") is not None else None,
            plan_source=str(payload.get("plan_source", "predicted")),
            predicted_k=int(payload["predicted_k"]) if payload.get("predicted_k") is not None else None,
            gold_k=int(payload["gold_k"]) if payload.get("gold_k") is not None else None,
            message=dict(payload.get("message")) if payload.get("message") is not None else None,
            verification=dict(payload.get("verification", {})),
            fallback=dict(payload.get("fallback", {})),
            errors=list(payload.get("errors", [])),
            background_contract=dict(payload.get("background_contract", {})),
            verification_eligible=bool(payload.get("verification_eligible", False)),
            excluded_reason=payload.get("excluded_reason"),
            strata=dict(payload.get("strata", {})),
            input_contract=dict(payload.get("input_contract", {})),
        )


@dataclass(slots=True)
class ConsumerAggregateRecord:
    mode: str
    plan_source: str
    sample_counts: dict[str, Any]
    aggregate_metrics: dict[str, Any]
    denominators: dict[str, Any]
    excluded_samples: dict[str, Any]
    validate_only: bool = False
    micro: dict[str, Any] = field(default_factory=dict)
    macro: dict[str, Any] = field(default_factory=dict)
    stratified: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CONSUMER_EVAL_AGGREGATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "plan_source": self.plan_source,
            "validate_only": self.validate_only,
            "sample_counts": dict(self.sample_counts),
            "aggregate_metrics": dict(self.aggregate_metrics),
            "micro": dict(self.micro),
            "macro": dict(self.macro),
            "denominators": dict(self.denominators),
            "excluded_samples": dict(self.excluded_samples),
            "stratified": dict(self.stratified),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConsumerAggregateRecord:
        return cls(
            schema_version=str(payload.get("schema_version", CONSUMER_EVAL_AGGREGATE_SCHEMA_VERSION)),
            mode=str(payload.get("mode", "deterministic")),
            plan_source=str(payload.get("plan_source", "predicted")),
            validate_only=bool(payload.get("validate_only", False)),
            sample_counts=dict(payload.get("sample_counts", {})),
            aggregate_metrics=dict(payload.get("aggregate_metrics", {})),
            micro=dict(payload.get("micro", {})),
            macro=dict(payload.get("macro", {})),
            denominators=dict(payload.get("denominators", {})),
            excluded_samples=dict(payload.get("excluded_samples", {})),
            stratified=dict(payload.get("stratified", {})),
        )


@dataclass(slots=True)
class HumanPilotCandidateRecord:
    sample_id: str
    evidence_display: dict[str, Any]
    candidate_id: str
    subject: str
    body: list[str]
    faithfulness_rating: int | None = None
    completeness_rating: int | None = None
    conciseness_rating: int | None = None
    usefulness_rating: int | None = None
    unsupported_claim: bool | None = None
    missing_intent: bool | None = None
    notes: str = ""
    schema_version: str = HUMAN_PILOT_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "evidence_display": dict(self.evidence_display),
            "candidate_id": self.candidate_id,
            "subject": self.subject,
            "body": list(self.body),
            "faithfulness_rating": self.faithfulness_rating,
            "completeness_rating": self.completeness_rating,
            "conciseness_rating": self.conciseness_rating,
            "usefulness_rating": self.usefulness_rating,
            "unsupported_claim": self.unsupported_claim,
            "missing_intent": self.missing_intent,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanPilotCandidateRecord:
        return cls(
            schema_version=str(payload.get("schema_version", HUMAN_PILOT_CANDIDATE_SCHEMA_VERSION)),
            sample_id=str(payload.get("sample_id", "")),
            evidence_display=dict(payload.get("evidence_display", {})),
            candidate_id=str(payload.get("candidate_id", "")),
            subject=str(payload.get("subject", "")),
            body=[str(item) for item in payload.get("body", [])],
            faithfulness_rating=payload.get("faithfulness_rating"),
            completeness_rating=payload.get("completeness_rating"),
            conciseness_rating=payload.get("conciseness_rating"),
            usefulness_rating=payload.get("usefulness_rating"),
            unsupported_claim=payload.get("unsupported_claim"),
            missing_intent=payload.get("missing_intent"),
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class HumanPilotBlindMappingRecord:
    sample_id: str
    candidate_id: str
    original_system_name: str
    plan_source: str
    original_record_id: str
    schema_version: str = HUMAN_PILOT_MAPPING_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "candidate_id": self.candidate_id,
            "original_system_name": self.original_system_name,
            "plan_source": self.plan_source,
            "original_record_id": self.original_record_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanPilotBlindMappingRecord:
        return cls(
            schema_version=str(payload.get("schema_version", HUMAN_PILOT_MAPPING_SCHEMA_VERSION)),
            sample_id=str(payload.get("sample_id", "")),
            candidate_id=str(payload.get("candidate_id", "")),
            original_system_name=str(payload.get("original_system_name", "")),
            plan_source=str(payload.get("plan_source", "")),
            original_record_id=str(payload.get("original_record_id", "")),
        )


@dataclass(slots=True)
class ConsumerRunComparisonRecord:
    paired_sample_count: int
    predicted_only_count: int
    oracle_only_count: int
    duplicate_commit_ids: list[str]
    excluded_pairs: list[dict[str, Any]]
    aggregate_predicted_metrics: dict[str, Any]
    aggregate_oracle_metrics: dict[str, Any]
    paired_deltas: dict[str, Any]
    per_sample_deltas: list[dict[str, Any]]
    schema_version: str = CONSUMER_RUN_COMPARISON_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "paired_sample_count": self.paired_sample_count,
            "predicted_only_count": self.predicted_only_count,
            "oracle_only_count": self.oracle_only_count,
            "duplicate_commit_ids": list(self.duplicate_commit_ids),
            "excluded_pairs": list(self.excluded_pairs),
            "aggregate_predicted_metrics": dict(self.aggregate_predicted_metrics),
            "aggregate_oracle_metrics": dict(self.aggregate_oracle_metrics),
            "paired_deltas": dict(self.paired_deltas),
            "per_sample_deltas": list(self.per_sample_deltas),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConsumerRunComparisonRecord:
        return cls(
            schema_version=str(payload.get("schema_version", CONSUMER_RUN_COMPARISON_SCHEMA_VERSION)),
            paired_sample_count=int(payload.get("paired_sample_count", 0)),
            predicted_only_count=int(payload.get("predicted_only_count", 0)),
            oracle_only_count=int(payload.get("oracle_only_count", 0)),
            duplicate_commit_ids=[str(item) for item in payload.get("duplicate_commit_ids", [])],
            excluded_pairs=[dict(item) for item in payload.get("excluded_pairs", [])],
            aggregate_predicted_metrics=dict(payload.get("aggregate_predicted_metrics", {})),
            aggregate_oracle_metrics=dict(payload.get("aggregate_oracle_metrics", {})),
            paired_deltas=dict(payload.get("paired_deltas", {})),
            per_sample_deltas=[dict(item) for item in payload.get("per_sample_deltas", [])],
        )
