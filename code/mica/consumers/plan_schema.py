from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from code.mica.schemas import EditUnitRecord, StructuredIntent as LegacyStructuredIntent, StructuredIntentPlan as LegacyStructuredIntentPlan


ALLOWED_DECISIONS = {"decompose", "abstain", "overflow"}
STRUCTURED_INTENT_PLAN_SCHEMA_VERSION = "mica-consumer-plan-v1"
SAFE_EVIDENCE_METADATA_KEYS = {
    "enclosing_symbol",
    "enclosing_symbol_name",
    "enclosing_symbol_type",
    "enclosing_symbol_signature",
    "enclosing_symbol_old_span",
    "enclosing_symbol_new_span",
    "enclosing_symbol_old_text",
    "enclosing_symbol_new_text",
    "enclosing_symbol_resolution_status",
    "operation",
    "change_kind",
    "changed_symbols",
}
SAFE_PLAN_METADATA_KEYS = {
    "background_units",
    "background_terms",
    "background_unit_records",
    "commit_id",
    "decision",
    "experimental_k_gt_2",
    "overflow_evidence",
    "prediction_source",
    "release_decision",
    "risk_score",
    "uncertain_units",
    "uncertain_unit_records",
}
BACKGROUND_REASON_ENUM = {
    "annotation_background",
    "dependency_metadata",
    "explicit_background",
    "format_only",
    "generated",
    "lockfile",
    "model_null_slot",
    "other_low_signal",
    "rule_verified_background",
    "vendor",
}
BACKGROUND_REASON_SOURCE_ENUM = {
    "parser_rule",
    "file_role_rule",
    "explicit_plan_metadata",
    "null_slot_assignment",
    "legacy_adapter",
    "unknown",
}
BACKGROUND_ASSIGNMENT_TYPE_ENUM = {
    "rule_verified_background",
    "model_assigned_background",
    "explicit_background",
    "unresolved_background",
}
BACKGROUND_RESOLUTION_STATUS_ENUM = {
    "complete",
    "partial",
    "id_only",
    "invalid",
}


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        token = str(value).strip()
        if token and token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def _validate_probability(value: float | None, *, field_name: str) -> None:
    if value is None:
        return
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be within [0, 1], got {value!r}")


def _normalize_file_role(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_background_reason(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("background_reason requires non-empty value")
    if normalized not in BACKGROUND_REASON_ENUM:
        raise ValueError(
            f"background_reason must be one of {sorted(BACKGROUND_REASON_ENUM)}, got {value!r}"
        )
    return normalized


def _normalize_background_reason_source(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return "legacy_adapter"
    if normalized not in BACKGROUND_REASON_SOURCE_ENUM:
        raise ValueError(
            f"background_reason_source must be one of {sorted(BACKGROUND_REASON_SOURCE_ENUM)}, got {value!r}"
        )
    return normalized


def _normalize_background_assignment_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return "unresolved_background"
    if normalized not in BACKGROUND_ASSIGNMENT_TYPE_ENUM:
        raise ValueError(
            "background_assignment_type must be one of "
            f"{sorted(BACKGROUND_ASSIGNMENT_TYPE_ENUM)}, got {value!r}"
        )
    return normalized


def _normalize_background_resolution_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return "partial"
    if normalized not in BACKGROUND_RESOLUTION_STATUS_ENUM:
        raise ValueError(
            "background_record_resolution_status must be one of "
            f"{sorted(BACKGROUND_RESOLUTION_STATUS_ENUM)}, got {value!r}"
        )
    return normalized


def _filter_safe_metadata(metadata: dict[str, Any] | None, *, allowed_keys: set[str]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        if key in allowed_keys:
            safe[key] = value
    return safe


@dataclass(slots=True)
class EvidenceUnit:
    unit_id: str
    hunk_id: str | None = None
    file_path: str = ""
    file_role: str | None = None
    language: str | None = None
    enclosing_symbol: str | None = None
    patch_text: str | None = None
    added_lines: list[str] = field(default_factory=list)
    deleted_lines: list[str] = field(default_factory=list)
    changed_identifiers: list[str] = field(default_factory=list)
    operation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.unit_id = str(self.unit_id).strip()
        self.hunk_id = str(self.hunk_id).strip() if self.hunk_id else None
        self.file_path = str(self.file_path).strip()
        self.file_role = _normalize_file_role(self.file_role) or None
        self.language = str(self.language).strip() if self.language else None
        self.enclosing_symbol = str(self.enclosing_symbol).strip() if self.enclosing_symbol else None
        self.patch_text = str(self.patch_text) if self.patch_text is not None else None
        self.added_lines = [str(item) for item in self.added_lines]
        self.deleted_lines = [str(item) for item in self.deleted_lines]
        self.changed_identifiers = _dedupe_preserve([str(item) for item in self.changed_identifiers])
        self.operation = str(self.operation).strip().lower() if self.operation else None
        self.metadata = dict(self.metadata)
        if not self.unit_id:
            raise ValueError("evidence unit requires non-empty unit_id")
        if not self.file_path:
            raise ValueError(f"evidence unit {self.unit_id!r} requires non-empty file_path")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "hunk_id": self.hunk_id,
            "file_path": self.file_path,
            "file_role": self.file_role,
            "language": self.language,
            "enclosing_symbol": self.enclosing_symbol,
            "patch_text": self.patch_text,
            "added_lines": list(self.added_lines),
            "deleted_lines": list(self.deleted_lines),
            "changed_identifiers": list(self.changed_identifiers),
            "operation": self.operation,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceUnit:
        metadata = _filter_safe_metadata(payload.get("metadata"), allowed_keys=SAFE_EVIDENCE_METADATA_KEYS)
        if payload.get("enclosing_symbol") and "enclosing_symbol_name" not in metadata:
            metadata["enclosing_symbol_name"] = payload.get("enclosing_symbol")
        return cls(
            unit_id=str(payload["unit_id"]),
            hunk_id=payload.get("hunk_id"),
            file_path=str(payload.get("file_path", "")),
            file_role=payload.get("file_role"),
            language=payload.get("language"),
            enclosing_symbol=payload.get("enclosing_symbol") or metadata.get("enclosing_symbol_name"),
            patch_text=payload.get("patch_text"),
            added_lines=[str(item) for item in payload.get("added_lines", [])],
            deleted_lines=[str(item) for item in payload.get("deleted_lines", [])],
            changed_identifiers=[str(item) for item in payload.get("changed_identifiers", [])],
            operation=payload.get("operation"),
            metadata=metadata,
        )


@dataclass(slots=True)
class BackgroundEvidenceRecord:
    unit_id: str
    hunk_id: str | None = None
    file_path: str = ""
    file_role: str | None = None
    changed_identifiers: list[str] = field(default_factory=list)
    patch_operation: str = ""
    background_reason: str = ""
    background_confidence: float = 0.0
    background_reason_source: str = "legacy_adapter"
    background_assignment_type: str = "unresolved_background"
    background_record_resolution_status: str = "partial"

    def __post_init__(self) -> None:
        self.unit_id = str(self.unit_id).strip()
        self.hunk_id = str(self.hunk_id).strip() if self.hunk_id else None
        self.file_path = str(self.file_path).strip()
        self.file_role = _normalize_file_role(self.file_role) or None
        self.changed_identifiers = _dedupe_preserve([str(item) for item in self.changed_identifiers])
        self.patch_operation = str(self.patch_operation).strip().lower()
        self.background_reason = _normalize_background_reason(self.background_reason)
        self.background_confidence = float(self.background_confidence)
        self.background_reason_source = _normalize_background_reason_source(self.background_reason_source)
        self.background_assignment_type = _normalize_background_assignment_type(self.background_assignment_type)
        self.background_record_resolution_status = _normalize_background_resolution_status(
            self.background_record_resolution_status
        )
        if not self.unit_id:
            raise ValueError("background record requires non-empty unit_id")
        if not self.file_path:
            raise ValueError(f"background record {self.unit_id!r} requires non-empty file_path")
        if not self.patch_operation:
            raise ValueError(f"background record {self.unit_id!r} requires non-empty patch_operation")
        _validate_probability(self.background_confidence, field_name="background_confidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "hunk_id": self.hunk_id,
            "file_path": self.file_path,
            "file_role": self.file_role,
            "changed_identifiers": list(self.changed_identifiers),
            "patch_operation": self.patch_operation,
            "background_reason": self.background_reason,
            "background_confidence": self.background_confidence,
            "background_reason_source": self.background_reason_source,
            "background_assignment_type": self.background_assignment_type,
            "background_record_resolution_status": self.background_record_resolution_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BackgroundEvidenceRecord:
        resolution_status = payload.get("background_record_resolution_status")
        if resolution_status is None:
            non_empty = sum(
                1
                for key in ("hunk_id", "file_path", "file_role", "changed_identifiers", "patch_operation")
                if payload.get(key) not in (None, "", [])
            )
            if non_empty <= 1:
                resolution_status = "id_only"
            else:
                resolution_status = "partial"
        return cls(
            unit_id=str(payload["unit_id"]),
            hunk_id=payload.get("hunk_id"),
            file_path=str(payload.get("file_path", "")),
            file_role=payload.get("file_role"),
            changed_identifiers=[str(item) for item in payload.get("changed_identifiers", [])],
            patch_operation=str(payload.get("patch_operation", payload.get("operation", ""))),
            background_reason=payload.get("background_reason"),
            background_confidence=float(payload.get("background_confidence", 0.0)),
            background_reason_source=payload.get("background_reason_source"),
            background_assignment_type=payload.get("background_assignment_type"),
            background_record_resolution_status=resolution_status,
        )


@dataclass(slots=True)
class IntentPlan:
    slot_id: str
    slot_confidence: float
    assigned_unit_ids: list[str] = field(default_factory=list)
    assigned_hunk_ids: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    changed_symbols: list[str] = field(default_factory=list)
    changed_identifiers: list[str] = field(default_factory=list)
    file_roles: list[str] = field(default_factory=list)
    evidence: list[EvidenceUnit] = field(default_factory=list)
    type: str | None = None
    scope: str | None = None
    action: str | None = None
    object: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.slot_id = str(self.slot_id).strip()
        self.assigned_unit_ids = _dedupe_preserve([str(item) for item in self.assigned_unit_ids])
        self.assigned_hunk_ids = _dedupe_preserve([str(item) for item in self.assigned_hunk_ids])
        self.files = _dedupe_preserve([str(item) for item in self.files])
        self.changed_symbols = _dedupe_preserve([str(item) for item in self.changed_symbols])
        self.changed_identifiers = _dedupe_preserve([str(item) for item in self.changed_identifiers])
        self.file_roles = _dedupe_preserve([_normalize_file_role(item) for item in self.file_roles if str(item).strip()])
        self.evidence = list(self.evidence)
        self.type = str(self.type).strip().lower() if self.type else None
        self.scope = str(self.scope).strip() if self.scope else None
        self.action = str(self.action).strip().lower() if self.action else None
        self.object = str(self.object).strip() if self.object else None
        self.metadata = dict(self.metadata)
        if not self.slot_id:
            raise ValueError("intent requires non-empty slot_id")
        _validate_probability(self.slot_confidence, field_name="slot_confidence")
        evidence_unit_ids = [unit.unit_id for unit in self.evidence]
        if evidence_unit_ids:
            missing = [unit_id for unit_id in evidence_unit_ids if unit_id not in self.assigned_unit_ids]
            if missing:
                raise ValueError(
                    f"intent {self.slot_id!r} evidence unit_ids must be a subset of assigned_unit_ids, missing {missing!r}"
                )
        if not self.files and self.evidence:
            self.files = _dedupe_preserve([unit.file_path for unit in self.evidence])
        if not self.file_roles and self.evidence:
            self.file_roles = _dedupe_preserve([unit.file_role or "unknown" for unit in self.evidence])
        if not self.changed_identifiers and self.evidence:
            self.changed_identifiers = _dedupe_preserve(
                [identifier for unit in self.evidence for identifier in unit.changed_identifiers]
            )
        if not self.changed_symbols and self.evidence:
            self.changed_symbols = _dedupe_preserve([unit.enclosing_symbol for unit in self.evidence if unit.enclosing_symbol])

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "slot_confidence": self.slot_confidence,
            "assigned_unit_ids": list(self.assigned_unit_ids),
            "assigned_hunk_ids": list(self.assigned_hunk_ids),
            "files": list(self.files),
            "changed_symbols": list(self.changed_symbols),
            "changed_identifiers": list(self.changed_identifiers),
            "file_roles": list(self.file_roles),
            "evidence": [unit.to_dict() for unit in self.evidence],
            "type": self.type,
            "scope": self.scope,
            "action": self.action,
            "object": self.object,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IntentPlan:
        return cls(
            slot_id=str(payload["slot_id"]),
            slot_confidence=float(payload.get("slot_confidence", 0.0)),
            assigned_unit_ids=[str(item) for item in payload.get("assigned_unit_ids", [])],
            assigned_hunk_ids=[str(item) for item in payload.get("assigned_hunk_ids", [])],
            files=[str(item) for item in payload.get("files", [])],
            changed_symbols=[str(item) for item in payload.get("changed_symbols", [])],
            changed_identifiers=[str(item) for item in payload.get("changed_identifiers", [])],
            file_roles=[str(item) for item in payload.get("file_roles", [])],
            evidence=[EvidenceUnit.from_dict(item) for item in payload.get("evidence", [])],
            type=payload.get("type"),
            scope=payload.get("scope"),
            action=payload.get("action"),
            object=payload.get("object"),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class StructuredIntentPlan:
    sample_id: str
    decision: str
    predicted_k: int
    intents: list[IntentPlan] = field(default_factory=list)
    commit_id: str | None = None
    overall_confidence: float | None = None
    background_units: list[str] = field(default_factory=list)
    background_unit_records: list[BackgroundEvidenceRecord | dict[str, Any]] = field(default_factory=list)
    uncertain_units: list[str] = field(default_factory=list)
    risk_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = STRUCTURED_INTENT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.sample_id = str(self.sample_id).strip()
        self.commit_id = str(self.commit_id).strip() if self.commit_id else None
        self.decision = str(self.decision).strip().lower()
        self.predicted_k = int(self.predicted_k)
        self.intents = list(self.intents)
        self.background_units = _dedupe_preserve([str(item) for item in self.background_units])
        self.background_unit_records = [
            item if isinstance(item, BackgroundEvidenceRecord) else BackgroundEvidenceRecord.from_dict(dict(item))
            for item in self.background_unit_records
        ]
        self.uncertain_units = _dedupe_preserve([str(item) for item in self.uncertain_units])
        self.metadata = dict(self.metadata)
        if not self.sample_id:
            raise ValueError("structured plan requires non-empty sample_id")
        if self.decision not in ALLOWED_DECISIONS:
            raise ValueError(f"unsupported decision {self.decision!r}; expected one of {sorted(ALLOWED_DECISIONS)}")
        _validate_probability(self.overall_confidence, field_name="overall_confidence")
        _validate_probability(self.risk_score, field_name="risk_score")
        if self.decision == "decompose":
            if self.predicted_k < 1:
                raise ValueError("decompose decision requires predicted_k >= 1")
            if not self.intents:
                raise ValueError("decompose decision requires at least one foreground intent")
            if self.predicted_k != len(self.intents):
                raise ValueError(
                    f"predicted_k must match number of intents for decompose plans: {self.predicted_k} != {len(self.intents)}"
                )
        else:
            if self.predicted_k != 0:
                raise ValueError(f"{self.decision} decision requires predicted_k == 0")
            if self.intents:
                raise ValueError(f"{self.decision} decision must not expose trusted foreground intents")
        slot_ids = [intent.slot_id for intent in self.intents]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError(f"duplicate slot_id detected in structured plan: {slot_ids!r}")
        assigned_units: dict[str, str] = {}
        assigned_hunks: dict[str, str] = {}
        for intent in self.intents:
            for unit_id in intent.assigned_unit_ids:
                owner = assigned_units.get(unit_id)
                if owner and owner != intent.slot_id:
                    raise ValueError(
                        f"assigned unit_id {unit_id!r} appears in multiple foreground intents: {owner!r} and {intent.slot_id!r}"
                    )
                assigned_units[unit_id] = intent.slot_id
            for hunk_id in intent.assigned_hunk_ids:
                owner = assigned_hunks.get(hunk_id)
                if owner and owner != intent.slot_id:
                    raise ValueError(
                        f"assigned hunk_id {hunk_id!r} appears in multiple foreground intents: {owner!r} and {intent.slot_id!r}"
                    )
                assigned_hunks[hunk_id] = intent.slot_id
        background_record_ids: dict[str, BackgroundEvidenceRecord] = {}
        for record in self.background_unit_records:
            if record.unit_id in background_record_ids:
                raise ValueError(f"duplicate background_unit_records entry detected for unit_id {record.unit_id!r}")
            if record.unit_id not in self.background_units:
                raise ValueError(
                    f"background_unit_records unit_id {record.unit_id!r} must belong to background_units"
                )
            background_record_ids[record.unit_id] = record
        foreground_background_overlap = [unit_id for unit_id in self.background_units if unit_id in assigned_units]
        if foreground_background_overlap:
            raise ValueError(
                "background unit_ids must not overlap with foreground primary assignments: "
                f"{foreground_background_overlap!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "commit_id": self.commit_id,
            "decision": self.decision,
            "predicted_k": self.predicted_k,
            "overall_confidence": self.overall_confidence,
            "intents": [intent.to_dict() for intent in self.intents],
            "background_units": list(self.background_units),
            "background_unit_records": [record.to_dict() for record in self.background_unit_records],
            "uncertain_units": list(self.uncertain_units),
            "risk_score": self.risk_score,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @property
    def background_contract(self) -> dict[str, Any]:
        record_ids = {record.unit_id for record in self.background_unit_records}
        missing_record_ids = [unit_id for unit_id in self.background_units if unit_id not in record_ids]
        diagnostic_codes: list[str] = []
        assignment_types = _dedupe_preserve([record.background_assignment_type for record in self.background_unit_records])
        reason_sources = _dedupe_preserve([record.background_reason_source for record in self.background_unit_records])
        resolution_statuses = _dedupe_preserve(
            [record.background_record_resolution_status for record in self.background_unit_records]
        )
        if any(record.background_record_resolution_status != "complete" for record in self.background_unit_records):
            diagnostic_codes.append("legacy_background_record_defaults_applied")
        return {
            "background_unit_ids": list(self.background_units),
            "background_record_ids": sorted(record_ids),
            "evidence_complete": not bool(missing_record_ids),
            "evidence_incomplete": bool(missing_record_ids),
            "missing_record_ids": missing_record_ids,
            "background_assignment_types": assignment_types,
            "background_reason_sources": reason_sources,
            "background_record_resolution_statuses": resolution_statuses,
            "diagnostic_codes": diagnostic_codes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StructuredIntentPlan:
        raw_metadata = dict(payload.get("metadata", {}))
        filtered_metadata = _filter_safe_metadata(raw_metadata, allowed_keys=SAFE_PLAN_METADATA_KEYS)
        background_unit_records = payload.get("background_unit_records")
        if background_unit_records is None:
            background_unit_records = filtered_metadata.get("background_unit_records", [])
        return cls(
            sample_id=str(payload["sample_id"]),
            commit_id=payload.get("commit_id"),
            decision=str(payload["decision"]),
            predicted_k=int(payload.get("predicted_k", 0)),
            overall_confidence=float(payload["overall_confidence"]) if payload.get("overall_confidence") is not None else None,
            intents=[IntentPlan.from_dict(item) for item in payload.get("intents", [])],
            background_units=[str(item) for item in payload.get("background_units", [])],
            background_unit_records=[dict(item) for item in background_unit_records or []],
            uncertain_units=[str(item) for item in payload.get("uncertain_units", [])],
            risk_score=float(payload["risk_score"]) if payload.get("risk_score") is not None else None,
            metadata={
                key: value
                for key, value in filtered_metadata.items()
                if key != "background_unit_records"
            },
            schema_version=str(payload.get("schema_version", STRUCTURED_INTENT_PLAN_SCHEMA_VERSION)),
        )


def _extract_evidence_unit(record: EditUnitRecord | dict[str, Any]) -> EvidenceUnit:
    if isinstance(record, dict):
        payload = dict(record)
        metadata = _filter_safe_metadata(payload.get("metadata"), allowed_keys=SAFE_EVIDENCE_METADATA_KEYS)
        enclosing_symbol = payload.get("enclosing_symbol") or metadata.get("enclosing_symbol_name")
        return EvidenceUnit(
            unit_id=str(payload["unit_id"]),
            hunk_id=payload.get("hunk_id"),
            file_path=str(payload.get("file_path", "")),
            file_role=payload.get("file_role"),
            language=payload.get("language"),
            enclosing_symbol=enclosing_symbol,
            patch_text=payload.get("patch_text"),
            added_lines=[str(item) for item in payload.get("added_lines", [])],
            deleted_lines=[str(item) for item in payload.get("deleted_lines", [])],
            changed_identifiers=[str(item) for item in payload.get("changed_identifiers", [])],
            operation=payload.get("operation") or metadata.get("operation"),
            metadata=metadata,
        )

    metadata = _filter_safe_metadata(record.metadata, allowed_keys=SAFE_EVIDENCE_METADATA_KEYS)
    enclosing_symbol = (
        metadata.get("enclosing_symbol")
        or metadata.get("enclosing_symbol_name")
        or metadata.get("enclosing_symbol_signature")
    )
    return EvidenceUnit(
        unit_id=record.unit_id,
        hunk_id=record.hunk_id,
        file_path=str(record.file_path or ""),
        file_role=record.file_role,
        language=record.language,
        enclosing_symbol=str(enclosing_symbol).strip() if enclosing_symbol else None,
        patch_text=record.patch_text,
        added_lines=[str(item) for item in record.added_lines],
        deleted_lines=[str(item) for item in record.deleted_lines],
        changed_identifiers=[str(item) for item in record.changed_identifiers],
        operation=metadata.get("operation"),
        metadata=metadata,
    )


def _legacy_intent_to_intent_plan(intent: LegacyStructuredIntent) -> IntentPlan:
    evidence = [_extract_evidence_unit(unit) for unit in intent.evidence_units]
    action = intent.diagnostics.get("action") if isinstance(intent.diagnostics, dict) else None
    object_value = intent.diagnostics.get("object") if isinstance(intent.diagnostics, dict) else None
    assigned_unit_ids = [str(item) for item in intent.edit_unit_ids] or [unit.unit_id for unit in evidence]
    assigned_hunk_ids = [str(item) for item in intent.hunk_ids] or [unit.hunk_id for unit in evidence if unit.hunk_id]
    return IntentPlan(
        slot_id=intent.slot_id,
        slot_confidence=float(intent.confidence or 0.0),
        assigned_unit_ids=assigned_unit_ids,
        assigned_hunk_ids=assigned_hunk_ids,
        files=_dedupe_preserve([unit.file_path for unit in evidence]),
        changed_symbols=_dedupe_preserve([unit.enclosing_symbol for unit in evidence if unit.enclosing_symbol]),
        changed_identifiers=_dedupe_preserve(
            [identifier for unit in evidence for identifier in unit.changed_identifiers]
        ),
        file_roles=_dedupe_preserve([unit.file_role or "unknown" for unit in evidence]),
        evidence=evidence,
        type=intent.type,
        scope=intent.scope,
        action=action,
        object=object_value,
        metadata={},
    )


def adapt_from_legacy_plan(
    plan: LegacyStructuredIntentPlan | dict[str, Any],
    *,
    decision: str | None = None,
    background_units: list[str] | None = None,
    background_unit_records: list[dict[str, Any]] | None = None,
    uncertain_units: list[str] | None = None,
    risk_score: float | None = None,
) -> StructuredIntentPlan:
    legacy = LegacyStructuredIntentPlan.from_dict(plan) if isinstance(plan, dict) else plan
    safe_metadata = _filter_safe_metadata(legacy.metadata, allowed_keys=SAFE_PLAN_METADATA_KEYS)
    resolved_decision = str(
        decision or safe_metadata.get("release_decision") or safe_metadata.get("decision") or "decompose"
    ).strip().lower()
    resolved_risk = risk_score if risk_score is not None else safe_metadata.get("risk_score")
    resolved_background = list(background_units or safe_metadata.get("background_units", []) or [])
    resolved_background_records = list(
        background_unit_records or safe_metadata.get("background_unit_records", []) or []
    )
    resolved_uncertain = list(uncertain_units or safe_metadata.get("uncertain_units", []) or [])
    commit_id = safe_metadata.get("commit_id") or legacy.sample_id
    intents = [_legacy_intent_to_intent_plan(intent) for intent in legacy.intents]
    predicted_k = legacy.intent_count if resolved_decision == "decompose" else 0
    return StructuredIntentPlan(
        sample_id=legacy.sample_id,
        commit_id=str(commit_id) if commit_id is not None else None,
        decision=resolved_decision,
        predicted_k=predicted_k,
        overall_confidence=None,
        intents=intents if resolved_decision == "decompose" else [],
        background_units=resolved_background,
        background_unit_records=resolved_background_records,
        uncertain_units=resolved_uncertain,
        risk_score=float(resolved_risk) if resolved_risk is not None else None,
        metadata={key: value for key, value in safe_metadata.items() if key != "background_unit_records"},
    )
