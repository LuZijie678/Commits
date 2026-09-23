from __future__ import annotations

from dataclasses import dataclass, field

from code.mica.consumers.plan_schema import EvidenceUnit, IntentPlan


OPERATION_VALUES = {"add", "update", "fix", "remove", "rename", "refactor", "document", "test", "configure"}
DOC_ROLES = {"doc", "docs"}
TEST_ROLES = {"test"}
CONFIG_ROLES = {"config", "build"}
BACKGROUNDISH_ROLES = {"lockfile", "generated", "format", "format-only", "vendor"}


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip()
        if token and token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def _normalize_path_scope(file_path: str) -> str:
    tokens = [token for token in str(file_path).replace("\\", "/").split("/") if token]
    ignored = {"src", "lib", "source", "tests", "test", "docs", "doc", "config", "configs"}
    for token in tokens:
        lowered = token.lower()
        if lowered in ignored:
            continue
        if "." in lowered:
            lowered = lowered.split(".", 1)[0]
        if lowered:
            return lowered
    return ""


def _dominant_identifier(evidence: list[EvidenceUnit]) -> str:
    counts: dict[str, int] = {}
    for unit in evidence:
        for identifier in unit.changed_identifiers:
            normalized = str(identifier).strip()
            if normalized:
                counts[normalized] = counts.get(normalized, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _first_non_supporting_unit(evidence: list[EvidenceUnit]) -> EvidenceUnit | None:
    ranked = sorted(
        evidence,
        key=lambda unit: (
            0 if (unit.file_role or "") not in DOC_ROLES | TEST_ROLES | CONFIG_ROLES | BACKGROUNDISH_ROLES else 1,
            unit.file_path,
            unit.hunk_id or unit.unit_id,
        ),
    )
    return ranked[0] if ranked else None


@dataclass(slots=True)
class SlotEvidenceSummary:
    slot_id: str
    operation: str
    target: str
    scope: str
    behavioral_effect: str | None
    supporting_changes: list[str]
    evidence_entities: list[str]
    evidence_unit_ids: list[str]
    confidence: float
    fallback_reason: str | None = None
    supported_claims: list[str] = field(default_factory=list)
    stable_order_key: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "operation": self.operation,
            "target": self.target,
            "scope": self.scope,
            "behavioral_effect": self.behavioral_effect,
            "supporting_changes": list(self.supporting_changes),
            "evidence_entities": list(self.evidence_entities),
            "evidence_unit_ids": list(self.evidence_unit_ids),
            "confidence": self.confidence,
            "fallback_reason": self.fallback_reason,
            "supported_claims": list(self.supported_claims),
            "stable_order_key": list(self.stable_order_key),
        }


class DeterministicEvidenceSummarizer:
    """Summarize one frozen foreground slot using assigned evidence only."""

    def summarize(self, intent: IntentPlan) -> SlotEvidenceSummary:
        evidence = sorted(intent.evidence, key=lambda unit: (unit.file_path, unit.hunk_id or unit.unit_id, unit.unit_id))
        if not evidence:
            return SlotEvidenceSummary(
                slot_id=intent.slot_id,
                operation=self._normalize_operation(intent.action or intent.type, evidence),
                target=self._fallback_target(intent),
                scope=self._derive_scope(intent, evidence),
                behavioral_effect=None,
                supporting_changes=[],
                evidence_entities=_dedupe_preserve(intent.changed_identifiers + intent.changed_symbols + intent.files),
                evidence_unit_ids=list(intent.assigned_unit_ids),
                confidence=float(intent.slot_confidence),
                fallback_reason="empty_evidence",
                supported_claims=self._supported_claims(intent),
                stable_order_key=(intent.files[0] if intent.files else "", intent.assigned_hunk_ids[0] if intent.assigned_hunk_ids else "", intent.slot_id),
            )

        primary = _first_non_supporting_unit(evidence) or evidence[0]
        operation = self._normalize_operation(intent.action or intent.type, evidence)
        scope = self._derive_scope(intent, evidence)
        target, fallback_reason = self._derive_target(intent, evidence)
        supporting_changes = self._supporting_changes(evidence, primary)
        evidence_entities = self._evidence_entities(intent, evidence, target, scope)
        behavioral_effect = self._behavioral_effect(intent)
        return SlotEvidenceSummary(
            slot_id=intent.slot_id,
            operation=operation,
            target=target,
            scope=scope,
            behavioral_effect=behavioral_effect,
            supporting_changes=supporting_changes,
            evidence_entities=evidence_entities,
            evidence_unit_ids=[unit.unit_id for unit in evidence],
            confidence=float(intent.slot_confidence),
            fallback_reason=fallback_reason,
            supported_claims=self._supported_claims(intent),
            stable_order_key=(primary.file_path, primary.hunk_id or primary.unit_id, target),
        )

    def _normalize_operation(self, explicit_action: str | None, evidence: list[EvidenceUnit]) -> str:
        explicit = str(explicit_action or "").strip().lower()
        if explicit in OPERATION_VALUES:
            return explicit
        flat_roles = set(_dedupe_preserve([unit.file_role or "" for unit in evidence]))
        if flat_roles and flat_roles <= DOC_ROLES:
            return "document"
        if flat_roles and flat_roles <= TEST_ROLES:
            return "test"
        if flat_roles and flat_roles <= CONFIG_ROLES:
            return "configure"
        if any("rename " in (unit.patch_text or "").lower() or "rename_" in " ".join(unit.changed_identifiers).lower() for unit in evidence):
            return "rename"
        added = any(unit.added_lines for unit in evidence)
        deleted = any(unit.deleted_lines for unit in evidence)
        if added and not deleted:
            return "add"
        if deleted and not added:
            return "remove"
        return "update"

    def _derive_target(self, intent: IntentPlan, evidence: list[EvidenceUnit]) -> tuple[str, str | None]:
        explicit_object = str(intent.object or "").strip()
        if explicit_object:
            return explicit_object, None
        for unit in evidence:
            if unit.enclosing_symbol:
                return str(unit.enclosing_symbol), "enclosing_symbol_fallback"
        dominant_identifier = _dominant_identifier(evidence)
        if dominant_identifier:
            return dominant_identifier, "identifier_fallback"
        if intent.changed_symbols:
            return intent.changed_symbols[0], "symbol_list_fallback"
        if intent.files:
            scope = _normalize_path_scope(intent.files[0])
            if scope:
                return scope, "path_scope_fallback"
        return "assigned changes", "generic_fallback"

    def _fallback_target(self, intent: IntentPlan) -> str:
        if intent.object:
            return str(intent.object)
        if intent.changed_identifiers:
            return intent.changed_identifiers[0]
        if intent.files:
            return _normalize_path_scope(intent.files[0]) or "assigned changes"
        return "assigned changes"

    def _derive_scope(self, intent: IntentPlan, evidence: list[EvidenceUnit]) -> str:
        if intent.scope:
            return str(intent.scope)
        for unit in evidence:
            role = unit.file_role or ""
            if role in DOC_ROLES:
                return "docs"
            if role in CONFIG_ROLES:
                return "config"
            derived = _normalize_path_scope(unit.file_path)
            if derived:
                return derived
        return "code"

    def _behavioral_effect(self, intent: IntentPlan) -> str | None:
        explicit = str(intent.action or intent.type or "").strip().lower()
        if explicit in {"performance", "security", "prevent crash", "improve reliability"}:
            return explicit
        return None

    def _supporting_changes(self, evidence: list[EvidenceUnit], primary: EvidenceUnit) -> list[str]:
        changes: list[str] = []
        for unit in evidence:
            if unit.unit_id == primary.unit_id:
                continue
            role = unit.file_role or "source"
            if role in TEST_ROLES:
                changes.append(f"update tests in {unit.file_path}")
            elif role in DOC_ROLES:
                changes.append(f"update documentation in {unit.file_path}")
            elif role in CONFIG_ROLES:
                changes.append(f"update configuration in {unit.file_path}")
            elif role in BACKGROUNDISH_ROLES:
                changes.append(f"include auxiliary change in {unit.file_path}")
            else:
                target = unit.enclosing_symbol or _dominant_identifier([unit]) or _normalize_path_scope(unit.file_path)
                if target:
                    changes.append(f"update supporting change for {target}")
        return _dedupe_preserve(changes)

    def _evidence_entities(self, intent: IntentPlan, evidence: list[EvidenceUnit], target: str, scope: str) -> list[str]:
        entities: list[str] = [target, scope]
        entities.extend(intent.changed_symbols)
        entities.extend(intent.changed_identifiers)
        for unit in evidence:
            if unit.enclosing_symbol:
                entities.append(unit.enclosing_symbol)
            entities.extend(unit.changed_identifiers)
            entities.append(_normalize_path_scope(unit.file_path))
        return _dedupe_preserve([entity for entity in entities if entity and entity != "code"])

    def _supported_claims(self, intent: IntentPlan) -> list[str]:
        claims: list[str] = []
        explicit = str(intent.action or intent.type or "").strip().lower()
        if explicit == "fix":
            claims.append("fix")
        if explicit in {"performance", "security", "crash", "reliability", "breaking change"}:
            claims.append(explicit)
        return claims
