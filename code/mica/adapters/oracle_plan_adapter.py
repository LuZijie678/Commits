from __future__ import annotations

from typing import Any

from code.mica.consumers.plan_schema import BackgroundEvidenceRecord, EvidenceUnit, IntentPlan, StructuredIntentPlan


def adapt_oracle_plan_record(row: dict[str, Any]) -> StructuredIntentPlan:
    sample_id = str(row.get("sample_id") or row.get("commit_id") or "").strip()
    if not sample_id:
        raise ValueError("oracle plan row requires sample_id or commit_id")
    commit_id = str(row.get("commit_id") or sample_id)
    scope_status = str(row.get("scope_status", "in_scope")).strip().lower()
    gold_k = int(row.get("gold_k", 0) or 0)
    edit_unit_index = {
        str(unit["unit_id"]): EvidenceUnit.from_dict(unit)
        for unit in row.get("edit_units", [])
        if isinstance(unit, dict) and unit.get("unit_id") is not None
    }
    foreground_intents = [dict(item) for item in row.get("foreground_intents", [])]
    background_units = [str(item) for item in row.get("background_units", [])]
    shared_support_units = {str(item) for item in row.get("shared_support_units", [])}
    uncertain_units = {str(item) for item in row.get("uncertain_units", [])}

    if scope_status == "out_of_scope":
        return StructuredIntentPlan(
            sample_id=sample_id,
            commit_id=commit_id,
            decision="overflow",
            predicted_k=0,
            intents=[],
            background_units=background_units,
            background_unit_records=_background_records(background_units, edit_unit_index),
            uncertain_units=sorted(uncertain_units),
            risk_score=None,
            metadata={
                "plan_source": "oracle",
                "annotation_source": "manual_adjudicated",
                "scope_status": scope_status,
                "gold_k": gold_k,
                "shared_support_units": sorted(shared_support_units),
            },
        )
    if scope_status == "uncertain":
        return StructuredIntentPlan(
            sample_id=sample_id,
            commit_id=commit_id,
            decision="abstain",
            predicted_k=0,
            intents=[],
            background_units=background_units,
            background_unit_records=_background_records(background_units, edit_unit_index),
            uncertain_units=sorted(uncertain_units),
            risk_score=None,
            metadata={
                "plan_source": "oracle",
                "annotation_source": "manual_adjudicated",
                "scope_status": scope_status,
                "gold_k": gold_k,
                "shared_support_units": sorted(shared_support_units),
            },
        )

    if gold_k != len(foreground_intents):
        raise ValueError(f"gold_k must match foreground intent count: {gold_k} != {len(foreground_intents)}")

    foreground_unit_ids: set[str] = set()
    intents: list[IntentPlan] = []
    human_statements = dict(row.get("human_intent_statements", {}))
    for index, item in enumerate(foreground_intents, 1):
        intent_id = str(item.get("intent_id") or f"intent_{index}")
        unit_ids = [str(unit_id) for unit_id in item.get("unit_ids", [])]
        filtered_unit_ids = [unit_id for unit_id in unit_ids if unit_id not in shared_support_units and unit_id not in uncertain_units]
        evidence = [edit_unit_index[unit_id] for unit_id in filtered_unit_ids if unit_id in edit_unit_index]
        for unit_id in filtered_unit_ids:
            if unit_id in foreground_unit_ids:
                raise ValueError(f"duplicate foreground unit assignment detected for oracle plan: {unit_id!r}")
            foreground_unit_ids.add(unit_id)
        intents.append(
            IntentPlan(
                slot_id=f"oracle_slot_{index}",
                slot_confidence=1.0,
                assigned_unit_ids=filtered_unit_ids,
                assigned_hunk_ids=[unit.hunk_id for unit in evidence if unit.hunk_id],
                files=[unit.file_path for unit in evidence],
                changed_symbols=[unit.enclosing_symbol for unit in evidence if unit.enclosing_symbol],
                changed_identifiers=[identifier for unit in evidence for identifier in unit.changed_identifiers],
                file_roles=[unit.file_role or "unknown" for unit in evidence],
                evidence=evidence,
                metadata={
                    "oracle_intent_id": intent_id,
                    "human_intent_statement": human_statements.get(intent_id),
                },
            )
        )

    overlap = sorted(unit_id for unit_id in background_units if unit_id in foreground_unit_ids)
    if overlap:
        raise ValueError(f"background units must not overlap with foreground units: {overlap!r}")

    return StructuredIntentPlan(
        sample_id=sample_id,
        commit_id=commit_id,
        decision="decompose",
        predicted_k=gold_k,
        overall_confidence=1.0,
        intents=intents,
        background_units=background_units,
        background_unit_records=_background_records(background_units, edit_unit_index),
        uncertain_units=sorted(uncertain_units),
        risk_score=None,
        metadata={
            "plan_source": "oracle",
            "annotation_source": "manual_adjudicated",
            "scope_status": scope_status,
            "gold_k": gold_k,
            "shared_support_units": sorted(shared_support_units),
            "annotation_metadata": dict(row.get("annotation_metadata", {})),
        },
    )


def _background_records(
    background_units: list[str],
    edit_unit_index: dict[str, EvidenceUnit],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit_id in background_units:
        unit = edit_unit_index.get(unit_id)
        if unit is None:
            rows.append(
                BackgroundEvidenceRecord(
                    unit_id=unit_id,
                    file_path=f"background/{unit_id}",
                    patch_operation="update",
                    background_reason="annotation_background",
                    background_confidence=1.0,
                    background_reason_source="explicit_plan_metadata",
                    background_assignment_type="explicit_background",
                    background_record_resolution_status="id_only",
                ).to_dict()
            )
            continue
        rows.append(
            BackgroundEvidenceRecord(
                unit_id=unit_id,
                hunk_id=unit.hunk_id,
                file_path=unit.file_path,
                file_role=unit.file_role,
                changed_identifiers=list(unit.changed_identifiers),
                patch_operation=_patch_operation(unit),
                background_reason=_background_reason(unit),
                background_confidence=1.0,
                background_reason_source="explicit_plan_metadata",
                background_assignment_type="explicit_background",
                background_record_resolution_status="complete",
            ).to_dict()
        )
    return rows


def _patch_operation(unit: EvidenceUnit) -> str:
    has_added = bool(unit.added_lines)
    has_deleted = bool(unit.deleted_lines)
    if has_added and has_deleted:
        return "update"
    if has_added:
        return "add"
    if has_deleted:
        return "remove"
    return "update"


def _background_reason(unit: EvidenceUnit) -> str:
    role = str(unit.file_role or "").strip().lower()
    if role in {"lockfile"}:
        return "lockfile"
    if role in {"generated"}:
        return "generated"
    if role in {"format", "format-only"}:
        return "format_only"
    if role in {"vendor"}:
        return "vendor"
    return "annotation_background"
