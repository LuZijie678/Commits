from __future__ import annotations

from typing import Iterable


def normalize_text(value: str) -> str:
    return " ".join(str(value).lower().split())


def summary_cues(summary: object) -> list[str]:
    cues: list[str] = []
    for attr in ("operation", "target", "scope"):
        value = getattr(summary, attr, None)
        if value:
            cues.append(normalize_text(str(value)))
    for value in getattr(summary, "evidence_entities", []) or []:
        cues.append(normalize_text(str(value)))
    deduped: list[str] = []
    seen: set[str] = set()
    for cue in cues:
        if cue and cue not in seen:
            seen.add(cue)
            deduped.append(cue)
    return deduped


def summary_is_covered(message: str, summary: object) -> bool:
    normalized = normalize_text(message)
    cues = summary_cues(summary)
    if not cues:
        return False
    target = normalize_text(str(getattr(summary, "target", "")))
    if target and target in normalized:
        return True
    evidence_entities = [
        normalize_text(str(value))
        for value in getattr(summary, "evidence_entities", []) or []
        if normalize_text(str(value))
    ]
    if evidence_entities and any(entity in normalized for entity in evidence_entities):
        operation = normalize_text(str(getattr(summary, "operation", "")))
        scope = normalize_text(str(getattr(summary, "scope", "")))
        if not operation or operation in normalized:
            if not scope or scope in normalized:
                return True
    return False


def intent_coverage_rate(message: str, summaries: Iterable[object]) -> dict[str, object]:
    covered_slot_ids: list[str] = []
    missing_slot_ids: list[str] = []
    for summary in summaries:
        slot_id = str(getattr(summary, "slot_id"))
        if summary_is_covered(message, summary):
            covered_slot_ids.append(slot_id)
        else:
            missing_slot_ids.append(slot_id)
    total = len(covered_slot_ids) + len(missing_slot_ids)
    return {
        "covered_slot_ids": covered_slot_ids,
        "missing_slot_ids": missing_slot_ids,
        "intent_coverage_rate": (len(covered_slot_ids) / total) if total else 0.0,
    }
