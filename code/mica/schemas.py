from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _copy_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _copy_list(payload: list[Any] | None) -> list[Any]:
    return list(payload or [])


def _span_from_dict(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    raise ValueError(f"span must be a 2-item tuple/list, got: {value!r}")


@dataclass(slots=True)
class EditUnitRecord:
    unit_id: str
    file_path: str | None = None
    hunk_id: str | None = None
    old_span: tuple[int, int] | None = None
    new_span: tuple[int, int] | None = None
    patch_text: str | None = None
    added_lines: list[str] = field(default_factory=list)
    deleted_lines: list[str] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)
    changed_identifiers: list[str] = field(default_factory=list)
    file_role: str | None = None
    language: str | None = None
    source_sha: str | None = None
    gold_intent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "file_path": self.file_path,
            "hunk_id": self.hunk_id,
            "old_span": list(self.old_span) if self.old_span is not None else None,
            "new_span": list(self.new_span) if self.new_span is not None else None,
            "patch_text": self.patch_text,
            "added_lines": list(self.added_lines),
            "deleted_lines": list(self.deleted_lines),
            "context_lines": list(self.context_lines),
            "changed_identifiers": list(self.changed_identifiers),
            "file_role": self.file_role,
            "language": self.language,
            "source_sha": self.source_sha,
            "gold_intent_id": self.gold_intent_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EditUnitRecord:
        return cls(
            unit_id=str(payload["unit_id"]),
            file_path=payload.get("file_path"),
            hunk_id=payload.get("hunk_id"),
            old_span=_span_from_dict(payload.get("old_span")),
            new_span=_span_from_dict(payload.get("new_span")),
            patch_text=payload.get("patch_text"),
            added_lines=[str(item) for item in payload.get("added_lines", [])],
            deleted_lines=[str(item) for item in payload.get("deleted_lines", [])],
            context_lines=[str(item) for item in payload.get("context_lines", [])],
            changed_identifiers=[str(item) for item in payload.get("changed_identifiers", [])],
            file_role=payload.get("file_role"),
            language=payload.get("language"),
            source_sha=payload.get("source_sha"),
            gold_intent_id=payload.get("gold_intent_id"),
            metadata=_copy_dict(payload.get("metadata")),
        )


@dataclass(slots=True)
class DegradationDiagnostic:
    code: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DegradationDiagnostic:
        return cls(
            code=str(payload["code"]),
            severity=str(payload.get("severity", "info")),
            message=str(payload.get("message", "")),
            metadata=_copy_dict(payload.get("metadata")),
        )


@dataclass(slots=True)
class AttributionSlot:
    slot_id: str
    existence_prob: float | None = None
    edit_unit_ids: list[str] = field(default_factory=list)
    hunk_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    assignment_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "existence_prob": self.existence_prob,
            "edit_unit_ids": list(self.edit_unit_ids),
            "hunk_ids": list(self.hunk_ids),
            "confidence": self.confidence,
            "assignment_scores": dict(self.assignment_scores),
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AttributionSlot:
        return cls(
            slot_id=str(payload["slot_id"]),
            existence_prob=float(payload["existence_prob"]) if payload.get("existence_prob") is not None else None,
            edit_unit_ids=[str(item) for item in payload.get("edit_unit_ids", [])],
            hunk_ids=[str(item) for item in payload.get("hunk_ids", [])],
            confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
            assignment_scores={str(key): float(value) for key, value in _copy_dict(payload.get("assignment_scores")).items()},
            diagnostics=_copy_dict(payload.get("diagnostics")),
        )


@dataclass(slots=True)
class AttributionPrediction:
    sample_id: str
    predicted_count: int | None = None
    count_probs: dict[str, float] = field(default_factory=dict)
    active_slots: list[AttributionSlot] = field(default_factory=list)
    all_slots: list[AttributionSlot] = field(default_factory=list)
    unit_to_slot: dict[str, str] = field(default_factory=dict)
    unit_assignment_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    source: str = "predicted_plan"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "predicted_count": self.predicted_count,
            "count_probs": dict(self.count_probs),
            "active_slots": [slot.to_dict() for slot in self.active_slots],
            "all_slots": [slot.to_dict() for slot in self.all_slots],
            "unit_to_slot": dict(self.unit_to_slot),
            "unit_assignment_scores": {
                str(unit_id): {str(slot_id): float(score) for slot_id, score in scores.items()}
                for unit_id, scores in self.unit_assignment_scores.items()
            },
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AttributionPrediction:
        return cls(
            sample_id=str(payload["sample_id"]),
            predicted_count=int(payload["predicted_count"]) if payload.get("predicted_count") is not None else None,
            count_probs={str(key): float(value) for key, value in _copy_dict(payload.get("count_probs")).items()},
            active_slots=[AttributionSlot.from_dict(item) for item in payload.get("active_slots", [])],
            all_slots=[AttributionSlot.from_dict(item) for item in payload.get("all_slots", [])],
            unit_to_slot={str(key): str(value) for key, value in _copy_dict(payload.get("unit_to_slot")).items()},
            unit_assignment_scores={
                str(unit_id): {str(slot_id): float(score) for slot_id, score in _copy_dict(scores).items()}
                for unit_id, scores in _copy_dict(payload.get("unit_assignment_scores")).items()
            },
            source=str(payload.get("source", "predicted_plan")),
            metadata=_copy_dict(payload.get("metadata")),
        )


@dataclass(slots=True)
class StructuredIntent:
    intent_id: str
    slot_id: str
    edit_unit_ids: list[str] = field(default_factory=list)
    hunk_ids: list[str] = field(default_factory=list)
    evidence_units: list[EditUnitRecord] = field(default_factory=list)
    confidence: float | None = None
    type: str | None = None
    scope: str | None = None
    subject: str | None = None
    body: str | None = None
    core_units: list[str] = field(default_factory=list)
    support_units: list[str] = field(default_factory=list)
    auxiliary_units: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "slot_id": self.slot_id,
            "edit_unit_ids": list(self.edit_unit_ids),
            "hunk_ids": list(self.hunk_ids),
            "evidence_units": [unit.to_dict() for unit in self.evidence_units],
            "confidence": self.confidence,
            "type": self.type,
            "scope": self.scope,
            "subject": self.subject,
            "body": self.body,
            "core_units": list(self.core_units),
            "support_units": list(self.support_units),
            "auxiliary_units": list(self.auxiliary_units),
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StructuredIntent:
        return cls(
            intent_id=str(payload["intent_id"]),
            slot_id=str(payload["slot_id"]),
            edit_unit_ids=[str(item) for item in payload.get("edit_unit_ids", [])],
            hunk_ids=[str(item) for item in payload.get("hunk_ids", [])],
            evidence_units=[EditUnitRecord.from_dict(item) for item in payload.get("evidence_units", [])],
            confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
            type=payload.get("type"),
            scope=payload.get("scope"),
            subject=payload.get("subject"),
            body=payload.get("body"),
            core_units=[str(item) for item in payload.get("core_units", [])],
            support_units=[str(item) for item in payload.get("support_units", [])],
            auxiliary_units=[str(item) for item in payload.get("auxiliary_units", [])],
            diagnostics=_copy_dict(payload.get("diagnostics")),
        )


@dataclass(slots=True)
class StructuredIntentPlan:
    sample_id: str
    intent_count: int
    is_multi_intent: bool
    intents: list[StructuredIntent] = field(default_factory=list)
    rendering_status: str = "ready"
    degraded: bool = False
    diagnostics: list[DegradationDiagnostic] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "intent_count": self.intent_count,
            "is_multi_intent": self.is_multi_intent,
            "intents": [intent.to_dict() for intent in self.intents],
            "rendering_status": self.rendering_status,
            "degraded": self.degraded,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StructuredIntentPlan:
        return cls(
            sample_id=str(payload["sample_id"]),
            intent_count=int(payload.get("intent_count", 0)),
            is_multi_intent=bool(payload.get("is_multi_intent", False)),
            intents=[StructuredIntent.from_dict(item) for item in payload.get("intents", [])],
            rendering_status=str(payload.get("rendering_status", "ready")),
            degraded=bool(payload.get("degraded", False)),
            diagnostics=[DegradationDiagnostic.from_dict(item) for item in payload.get("diagnostics", [])],
            metadata=_copy_dict(payload.get("metadata")),
        )


@dataclass(slots=True)
class StageRunManifest:
    run_id: str
    stage: str
    protocol_spec_path: str | None = None
    manifest_path: str | None = None
    prediction_path: str | None = None
    output_root: str | None = None
    created_at: str = ""
    stage2_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "protocol_spec_path": self.protocol_spec_path,
            "manifest_path": self.manifest_path,
            "prediction_path": self.prediction_path,
            "output_root": self.output_root,
            "created_at": self.created_at,
            "stage2_allowed": self.stage2_allowed,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageRunManifest:
        return cls(
            run_id=str(payload["run_id"]),
            stage=str(payload["stage"]),
            protocol_spec_path=payload.get("protocol_spec_path"),
            manifest_path=payload.get("manifest_path"),
            prediction_path=payload.get("prediction_path"),
            output_root=payload.get("output_root"),
            created_at=str(payload.get("created_at", "")),
            stage2_allowed=bool(payload.get("stage2_allowed", False)),
            metadata=_copy_dict(payload.get("metadata")),
        )
