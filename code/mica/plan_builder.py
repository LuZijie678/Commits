from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from code.mica.io_utils import read_json, read_jsonl, safe_relpath_for_report, write_json, write_jsonl
from code.mica.runners.consumer_runner_utils import load_sample_indexed_rows
from code.mica.schemas import (
    AttributionPrediction,
    DegradationDiagnostic,
    EditUnitRecord,
    StructuredIntentPlan,
    StructuredIntent,
)

NULL_SLOT_ID = "slot_null"


@dataclass(slots=True)
class StructuredIntentPlanBuilder:
    collapse_ratio_threshold: float = 0.90

    def build(self, *, prediction: AttributionPrediction, edit_units: list[EditUnitRecord]) -> StructuredIntentPlan:
        diagnostics: list[DegradationDiagnostic] = []
        unit_index = {unit.unit_id: unit for unit in edit_units}
        slot_index = {slot.slot_id: slot for slot in prediction.all_slots or prediction.active_slots}
        active_slots = list(prediction.active_slots)
        explicit_background_units = self._explicit_background_units(prediction.metadata)
        explicit_background_records = self._explicit_background_records(prediction.metadata)
        null_background_units = [
            unit_id for unit_id, slot_id in prediction.unit_to_slot.items() if str(slot_id) == NULL_SLOT_ID
        ]
        background_units = self._dedupe_preserve(explicit_background_units + null_background_units)

        if not prediction.count_probs:
            diagnostics.append(self._diag("missing_count_probs", "warning", "Prediction count probabilities are missing."))
        if any(slot.existence_prob is None for slot in prediction.all_slots or active_slots):
            diagnostics.append(self._diag("missing_slot_existence", "warning", "At least one slot is missing existence probability."))
        if not prediction.unit_assignment_scores or any(not scores for scores in prediction.unit_assignment_scores.values()):
            diagnostics.append(self._diag("missing_assignment_scores", "warning", "Unit assignment scores are missing or incomplete."))
        if not active_slots:
            diagnostics.append(self._diag("empty_active_slots", "error", "No active foreground slots are available for plan construction."))

        predicted_count = prediction.predicted_count if prediction.predicted_count is not None else len(active_slots)
        if predicted_count != len(active_slots):
            diagnostics.append(
                self._diag(
                    "k_hat_mismatch_active_slots",
                    "warning",
                    "Predicted count does not match number of active foreground slots.",
                    {"predicted_count": predicted_count, "active_slot_count": len(active_slots)},
                )
            )
        if predicted_count > 2:
            diagnostics.append(
                self._diag(
                    "unsupported_k_experimental",
                    "warning",
                    "K>2 structured plan building is supported only as an experimental path.",
                    {"predicted_count": predicted_count},
                )
            )

        known_slot_ids = set(slot_index) | {slot.slot_id for slot in active_slots}
        known_unit_ids = set(unit_index)
        for unit in edit_units:
            if unit.unit_id not in prediction.unit_to_slot and unit.unit_id not in background_units:
                diagnostics.append(
                    self._diag(
                        "unit_without_assignment",
                        "warning",
                        "Edit unit is missing a slot assignment.",
                        {"unit_id": unit.unit_id},
                    )
                )
            if unit.file_path is None or unit.file_role is None:
                diagnostics.append(
                    self._diag(
                        "missing_unit_metadata",
                        "warning",
                        "Edit unit metadata is incomplete for plan display.",
                        {"unit_id": unit.unit_id},
                    )
                )
        for unit_id, slot_id in prediction.unit_to_slot.items():
            if slot_id == NULL_SLOT_ID:
                continue
            if slot_id not in known_slot_ids:
                diagnostics.append(
                    self._diag(
                        "assignment_to_unknown_slot",
                        "warning",
                        "Unit assignment points to a slot not present in the prediction slots.",
                        {"unit_id": unit_id, "slot_id": slot_id},
                    )
                )
            if unit_id not in known_unit_ids:
                diagnostics.append(
                    self._diag(
                        "missing_unit_metadata",
                        "warning",
                        "Assigned unit is not present in the supplied edit-unit records.",
                        {"unit_id": unit_id},
                    )
                )

        intents: list[StructuredIntent] = []
        for index, slot in enumerate(active_slots, 1):
            slot_unit_ids = list(slot.edit_unit_ids)
            if not slot_unit_ids:
                slot_unit_ids = [unit_id for unit_id, assigned_slot in prediction.unit_to_slot.items() if assigned_slot == slot.slot_id]
            evidence_units = [unit_index[unit_id] for unit_id in slot_unit_ids if unit_id in unit_index]
            if not evidence_units:
                diagnostics.append(
                    self._diag(
                        "slot_without_units",
                        "warning",
                        "Active slot has no attached edit units.",
                        {"slot_id": slot.slot_id},
                    )
                )
            role_groups = self._split_roles(evidence_units)
            intents.append(
                StructuredIntent(
                    intent_id=f"intent_{index}",
                    slot_id=slot.slot_id,
                    edit_unit_ids=slot_unit_ids,
                    hunk_ids=list(slot.hunk_ids),
                    evidence_units=evidence_units,
                    confidence=slot.confidence if slot.confidence is not None else slot.existence_prob,
                    type=None,
                    scope=None,
                    subject=None,
                    body=None,
                    core_units=role_groups["core"],
                    support_units=role_groups["support"],
                    auxiliary_units=role_groups["auxiliary"],
                    diagnostics=self._intent_diagnostics(evidence_units),
                )
            )

        assigned_total = sum(len(intent.edit_unit_ids) for intent in intents)
        max_assigned = max((len(intent.edit_unit_ids) for intent in intents), default=0)
        if predicted_count >= 2 and assigned_total > 0 and (max_assigned / assigned_total) >= self.collapse_ratio_threshold:
            diagnostics.append(
                self._diag(
                    "slot_collapse_detected",
                    "warning",
                    "Most edit units are assigned to one foreground slot.",
                    {"max_slot_unit_count": max_assigned, "total_assigned_units": assigned_total},
                )
            )

        degraded = any(item.severity in {"warning", "error"} for item in diagnostics)
        background_records = self._resolve_background_records(
            prediction=prediction,
            unit_index=unit_index,
            background_units=background_units,
            explicit_background_records=explicit_background_records,
        )
        return StructuredIntentPlan(
            sample_id=prediction.sample_id,
            intent_count=max(predicted_count, 0),
            is_multi_intent=max(predicted_count, 0) > 1,
            intents=intents,
            rendering_status="degraded" if degraded else "ready",
            degraded=degraded,
            diagnostics=diagnostics,
            metadata={
                "prediction_source": prediction.source,
                "experimental_k_gt_2": predicted_count > 2,
                "background_units": background_units,
                "background_unit_records": background_records,
                "release_decision": prediction.metadata.get("release_decision"),
                "risk_score": prediction.metadata.get("risk_score"),
                "uncertain_units": list(prediction.metadata.get("uncertain_units", []) or []),
            },
        )

    def _resolve_background_records(
        self,
        *,
        prediction: AttributionPrediction,
        unit_index: dict[str, EditUnitRecord],
        background_units: list[str],
        explicit_background_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        record_by_unit: dict[str, dict[str, Any]] = {}
        for row in explicit_background_records:
            unit_id = str(row.get("unit_id", "")).strip()
            if unit_id and unit_id in background_units:
                record_by_unit[unit_id] = self._normalize_background_record(
                    row=row,
                    unit=unit_index.get(unit_id),
                )
        for unit_id in background_units:
            if unit_id in record_by_unit:
                continue
            if prediction.unit_to_slot.get(unit_id) == NULL_SLOT_ID and unit_id in unit_index:
                record_by_unit[unit_id] = self._build_background_record_from_unit(
                    unit=unit_index[unit_id],
                    assignment_scores=prediction.unit_assignment_scores.get(unit_id, {}),
                )
        return [record_by_unit[unit_id] for unit_id in background_units if unit_id in record_by_unit]

    def _split_roles(self, evidence_units: list[EditUnitRecord]) -> dict[str, list[str]]:
        roles = {"core": [], "support": [], "auxiliary": []}
        for unit in evidence_units:
            bucket = self._classify_role(unit.file_role)
            roles[bucket].append(unit.unit_id)
        return roles

    def _classify_role(self, file_role: str | None) -> str:
        role = (file_role or "").lower()
        if role in {"test", "doc", "docs"}:
            return "support"
        if role in {"lockfile", "generated", "format", "format-only"}:
            return "auxiliary"
        return "core"

    def _intent_diagnostics(self, evidence_units: list[EditUnitRecord]) -> dict[str, Any]:
        unknown_role_units = [unit.unit_id for unit in evidence_units if not unit.file_role]
        diagnostics: dict[str, Any] = {}
        if unknown_role_units:
            diagnostics["missing_role_units"] = unknown_role_units
        return diagnostics

    def _explicit_background_units(self, metadata: dict[str, Any]) -> list[str]:
        return self._dedupe_preserve([str(item) for item in metadata.get("background_units", []) or []])

    def _explicit_background_records(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        rows = metadata.get("background_unit_records", []) or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _normalize_background_record(self, *, row: dict[str, Any], unit: EditUnitRecord | None) -> dict[str, Any]:
        normalized = dict(row)
        had_reason_source = "background_reason_source" in normalized
        had_assignment_type = "background_assignment_type" in normalized
        had_resolution_status = "background_record_resolution_status" in normalized
        normalized.setdefault("unit_id", unit.unit_id if unit is not None else "")
        normalized.setdefault("hunk_id", unit.hunk_id if unit is not None else None)
        normalized.setdefault("file_path", unit.file_path if unit is not None else "")
        normalized.setdefault("file_role", unit.file_role if unit is not None else None)
        normalized.setdefault("changed_identifiers", list(unit.changed_identifiers) if unit is not None else [])
        normalized.setdefault("patch_operation", self._infer_patch_operation(unit) if unit is not None else "update")
        normalized.setdefault("background_reason", self._background_reason(unit))
        normalized.setdefault("background_confidence", 1.0)
        normalized.setdefault("background_reason_source", "explicit_plan_metadata")
        normalized.setdefault("background_assignment_type", "explicit_background")
        if not had_resolution_status:
            normalized["background_record_resolution_status"] = (
                "complete" if had_reason_source and had_assignment_type else "partial"
            )
        return {
            "unit_id": str(normalized.get("unit_id", "")),
            "hunk_id": normalized.get("hunk_id"),
            "file_path": str(normalized.get("file_path", "") or ""),
            "file_role": normalized.get("file_role"),
            "changed_identifiers": [str(item) for item in normalized.get("changed_identifiers", []) or []],
            "patch_operation": str(normalized.get("patch_operation", "update") or "update"),
            "background_reason": str(normalized.get("background_reason", self._background_reason(unit)) or self._background_reason(unit)),
            "background_confidence": float(normalized.get("background_confidence", 1.0)),
            "background_reason_source": str(normalized.get("background_reason_source", "explicit_plan_metadata")),
            "background_assignment_type": str(normalized.get("background_assignment_type", "explicit_background")),
            "background_record_resolution_status": str(
                normalized.get("background_record_resolution_status", "partial")
            ),
        }

    def _build_background_record_from_unit(
        self,
        *,
        unit: EditUnitRecord,
        assignment_scores: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "unit_id": unit.unit_id,
            "hunk_id": unit.hunk_id,
            "file_path": str(unit.file_path or ""),
            "file_role": unit.file_role,
            "changed_identifiers": [str(item) for item in unit.changed_identifiers],
            "patch_operation": self._infer_patch_operation(unit),
            "background_reason": self._background_reason(unit),
            "background_confidence": float(assignment_scores.get(NULL_SLOT_ID, 1.0)),
            "background_reason_source": "null_slot_assignment",
            "background_assignment_type": "model_assigned_background",
            "background_record_resolution_status": "complete",
        }

    def _background_reason(self, unit: EditUnitRecord | None) -> str:
        role = str(unit.file_role or "").strip().lower() if unit is not None else ""
        if role in {"lockfile"}:
            return "lockfile"
        if role in {"generated"}:
            return "generated"
        if role in {"format", "format-only"}:
            return "format_only"
        if role in {"vendor"}:
            return "vendor"
        return "model_null_slot"

    def _infer_patch_operation(self, unit: EditUnitRecord) -> str:
        has_added = bool(unit.added_lines)
        has_deleted = bool(unit.deleted_lines)
        if has_added and has_deleted:
            return "update"
        if has_added:
            return "add"
        if has_deleted:
            return "remove"
        return "update"

    def _dedupe_preserve(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            token = str(value).strip()
            if token and token not in seen:
                seen.add(token)
                deduped.append(token)
        return deduped

    def _diag(self, code: str, severity: str, message: str, metadata: dict[str, Any] | None = None) -> DegradationDiagnostic:
        return DegradationDiagnostic(code=code, severity=severity, message=message, metadata=metadata or {})


def build_plan_from_dict(
    prediction_dict: dict[str, Any],
    edit_units_dict_or_list: dict[str, Any] | list[dict[str, Any]] | list[EditUnitRecord] | None = None,
    *,
    builder: StructuredIntentPlanBuilder | None = None,
) -> StructuredIntentPlan:
    active_builder = builder or StructuredIntentPlanBuilder()
    diagnostics: list[DegradationDiagnostic] = []
    prediction_payload = dict(prediction_dict)

    embedded_edit_units = prediction_payload.pop("edit_units", None)
    prediction = AttributionPrediction.from_dict(prediction_payload)
    edit_units_rows, extra_diagnostics = _resolve_edit_units(
        sample_id=prediction.sample_id,
        embedded_edit_units=embedded_edit_units,
        external_edit_units=edit_units_dict_or_list,
    )
    diagnostics.extend(extra_diagnostics)
    plan = active_builder.build(
        prediction=prediction,
        edit_units=[EditUnitRecord.from_dict(row) if isinstance(row, dict) else row for row in edit_units_rows],
    )
    if diagnostics:
        plan.diagnostics.extend(diagnostics)
        plan.degraded = True
        plan.rendering_status = "degraded"
    plan.metadata["edit_units_embedded"] = embedded_edit_units is not None
    plan.metadata["prediction_source"] = prediction.source
    return plan


def build_plans_from_jsonl(
    *,
    prediction_jsonl: str | Any,
    output_jsonl: str | Any,
    edit_units_jsonl_or_manifest: str | Any | None = None,
    summary_json_path: str | Any | None = None,
    summary_md_path: str | Any | None = None,
    builder: StructuredIntentPlanBuilder | None = None,
) -> dict[str, Any]:
    prediction_rows = read_jsonl(prediction_jsonl)
    external_edit_units_index = load_sample_indexed_rows(edit_units_jsonl_or_manifest) if edit_units_jsonl_or_manifest else {}
    built_plans: list[StructuredIntentPlan] = []

    for row_index, prediction_row in enumerate(prediction_rows, 1):
        sample_id = str(prediction_row.get("sample_id") or f"__row_{row_index}__")
        external_payload = external_edit_units_index.get(sample_id)
        try:
            plan = build_plan_from_dict(prediction_row, external_payload, builder=builder)
        except Exception as exc:  # noqa: BLE001 - batch conversion must continue.
            plan = StructuredIntentPlan(
                sample_id=sample_id,
                intent_count=0,
                is_multi_intent=False,
                intents=[],
                rendering_status="degraded",
                degraded=True,
                diagnostics=[
                    DegradationDiagnostic(
                        code="plan_builder_exception",
                        severity="error",
                        message=str(exc),
                        metadata={"row_index": row_index},
                    )
                ],
                metadata={},
            )
        built_plans.append(plan)

    write_jsonl(output_jsonl, [plan.to_dict() for plan in built_plans])
    summary = summarize_plans(built_plans)
    summary["prediction_jsonl"] = safe_relpath_for_report(prediction_jsonl)
    summary["output_jsonl"] = safe_relpath_for_report(output_jsonl)
    if edit_units_jsonl_or_manifest is not None:
        summary["edit_units_source"] = safe_relpath_for_report(edit_units_jsonl_or_manifest)
    if summary_json_path is not None:
        write_json(summary_json_path, summary)
    if summary_md_path is not None:
        _write_plan_summary_markdown(summary_md_path, summary)
    return summary


def summarize_plans(plans: list[StructuredIntentPlan]) -> dict[str, Any]:
    diagnostic_histogram: Counter[str] = Counter()
    intent_count_distribution: Counter[str] = Counter()
    degraded_count = 0
    slot_collapse_count = 0
    missing_edit_units_count = 0
    unsupported_k_experimental_count = 0
    total_units = 0
    total_intents = 0

    for plan in plans:
        if plan.degraded:
            degraded_count += 1
        intent_count_distribution[str(plan.intent_count)] += 1
        total_intents += len(plan.intents)
        for intent in plan.intents:
            total_units += len(intent.edit_unit_ids)
        for diagnostic in plan.diagnostics:
            diagnostic_histogram[diagnostic.code] += 1
            if diagnostic.code == "slot_collapse_detected":
                slot_collapse_count += 1
            if diagnostic.code == "missing_edit_units":
                missing_edit_units_count += 1
            if diagnostic.code == "unsupported_k_experimental":
                unsupported_k_experimental_count += 1

    total_samples = len(plans)
    return {
        "total_samples": total_samples,
        "plans_built": total_samples,
        "degraded_count": degraded_count,
        "degraded_rate": (degraded_count / total_samples) if total_samples else 0.0,
        "intent_count_distribution": dict(intent_count_distribution),
        "diagnostic_histogram": dict(diagnostic_histogram),
        "slot_collapse_count": slot_collapse_count,
        "missing_edit_units_count": missing_edit_units_count,
        "unsupported_k_experimental_count": unsupported_k_experimental_count,
        "avg_intents_per_plan": (total_intents / total_samples) if total_samples else 0.0,
        "avg_units_per_intent": (total_units / total_intents) if total_intents else 0.0,
    }


def _resolve_edit_units(
    *,
    sample_id: str,
    embedded_edit_units: Any,
    external_edit_units: dict[str, Any] | list[dict[str, Any]] | list[EditUnitRecord] | None,
) -> tuple[list[dict[str, Any] | EditUnitRecord], list[DegradationDiagnostic]]:
    diagnostics: list[DegradationDiagnostic] = []
    payload = external_edit_units if external_edit_units is not None else embedded_edit_units
    if payload is None:
        diagnostics.append(
            DegradationDiagnostic(
                code="missing_edit_units",
                severity="warning",
                message="No edit-unit payload was supplied for this prediction.",
                metadata={"sample_id": sample_id},
            )
        )
        return [], diagnostics
    if isinstance(payload, dict):
        container_sample_id = payload.get("sample_id")
        if container_sample_id is not None and str(container_sample_id) != sample_id:
            diagnostics.append(
                DegradationDiagnostic(
                    code="sample_id_mismatch",
                    severity="warning",
                    message="Prediction sample_id does not match the supplied edit-unit payload sample_id.",
                    metadata={"prediction_sample_id": sample_id, "edit_units_sample_id": str(container_sample_id)},
                )
            )
        payload = payload.get("edit_units", [])
    if not isinstance(payload, list):
        raise ValueError("edit_units payload must be a list or a dict containing an edit_units list")
    if not payload:
        diagnostics.append(
            DegradationDiagnostic(
                code="missing_edit_units",
                severity="warning",
                message="Edit-unit payload is empty.",
                metadata={"sample_id": sample_id},
            )
        )
    return payload, diagnostics


def _write_plan_summary_markdown(path: str | Any, summary: dict[str, Any]) -> None:
    from pathlib import Path

    lines = [
        "# Structured Intent Plan Builder Summary",
        "",
        f"- `total_samples`: {summary['total_samples']}",
        f"- `plans_built`: {summary['plans_built']}",
        f"- `degraded_count`: {summary['degraded_count']}",
        f"- `degraded_rate`: {summary['degraded_rate']:.6f}",
        f"- `slot_collapse_count`: {summary['slot_collapse_count']}",
        f"- `missing_edit_units_count`: {summary['missing_edit_units_count']}",
        f"- `unsupported_k_experimental_count`: {summary['unsupported_k_experimental_count']}",
        "",
        "## Diagnostic Histogram",
        "",
    ]
    for code, count in sorted(summary["diagnostic_histogram"].items()):
        lines.append(f"- `{code}`: {count}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
