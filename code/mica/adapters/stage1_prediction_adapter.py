from __future__ import annotations

from typing import Any

from code.mica.schemas import AttributionPrediction, EditUnitRecord


NULL_SLOT_ID = "slot_null"


def detect_stage1_prediction_format(row: dict[str, Any]) -> str:
    if _has_standard_shape(row):
        return "standard"
    if _has_legacy_aliases(row):
        return "legacy_aliases"
    if row.get("sample_id") is not None and _extract_unit_to_slot(row):
        return "top1_only"
    return "unknown"


def validate_stage1_prediction_row(row: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    fmt = detect_stage1_prediction_format(row)

    sample_id = row.get("sample_id")
    if sample_id in {None, ""}:
        diagnostics.append(_diag("missing_sample_id", "error", "Prediction row is missing sample_id."))

    predicted_count = _extract_predicted_count(row)
    if predicted_count is None:
        diagnostics.append(_diag("missing_predicted_count", "warning", "Prediction row is missing predicted_count/k_hat."))

    if not _extract_count_probs(row):
        diagnostics.append(_diag("missing_count_probs", "warning", "Prediction row is missing count probabilities."))

    unit_to_slot = _extract_unit_to_slot(row)
    if not unit_to_slot:
        diagnostics.append(_diag("missing_unit_to_slot", "error", "Prediction row is missing unit-to-slot assignments."))

    active_slots = _extract_active_slots(row, unit_to_slot)
    if not active_slots and not unit_to_slot:
        diagnostics.append(_diag("missing_active_slots", "warning", "Prediction row is missing active slot descriptors."))

    if not _extract_edit_units_raw(row):
        diagnostics.append(_diag("missing_edit_units", "warning", "Prediction row is missing embedded edit-unit records."))

    if not _extract_assignment_scores(row):
        diagnostics.append(_diag("assignment_scores_missing", "warning", "Prediction row is missing assignment scores."))
        diagnostics.append(_diag("missing_assignment_scores", "warning", "Prediction row is missing assignment scores."))

    if not _has_slot_existence(row, active_slots):
        diagnostics.append(_diag("slot_existence_missing", "warning", "Prediction row is missing slot existence information."))

    if fmt == "top1_only":
        diagnostics.append(_diag("limited_prediction_format", "warning", "Prediction row only contains top-1 assignments."))
    if fmt == "unknown":
        diagnostics.append(_diag("unknown_prediction_format", "warning", "Prediction row format is unknown to the adapter."))

    return {
        "format": fmt,
        "diagnostics": diagnostics,
        "degraded": any(item["severity"] in {"warning", "error"} for item in diagnostics),
        "has_error": any(item["severity"] == "error" for item in diagnostics),
    }


def normalize_stage1_prediction_row(row: dict[str, Any]) -> dict[str, Any]:
    validation = validate_stage1_prediction_row(row)
    unit_to_slot = _extract_unit_to_slot(row)
    active_slots = _extract_active_slots(row, unit_to_slot)
    edit_units = _extract_edit_units_raw(row)

    metadata = dict(row.get("metadata", {}))
    metadata["adapter_format"] = validation["format"]
    metadata["adapter_diagnostics"] = list(validation["diagnostics"])
    for key in ("background_units", "background_unit_records", "uncertain_units", "release_decision", "risk_score", "commit_id"):
        if key in row and key not in metadata:
            metadata[key] = row[key]

    normalized = {
        "sample_id": str(row.get("sample_id") or "__missing_sample_id__"),
        "predicted_count": _extract_predicted_count(row),
        "count_probs": _extract_count_probs(row),
        "active_slots": active_slots,
        "all_slots": _extract_all_slots(row, active_slots),
        "unit_to_slot": unit_to_slot,
        "unit_assignment_scores": _extract_assignment_scores(row),
        "source": str(row.get("source", "stage1_prediction_adapter")),
        "metadata": metadata,
        "edit_units": edit_units,
    }
    return normalized


def prediction_row_to_attribution_prediction(row: dict[str, Any]) -> AttributionPrediction:
    normalized = normalize_stage1_prediction_row(row)
    payload = dict(normalized)
    payload.pop("edit_units", None)
    return AttributionPrediction.from_dict(payload)


def extract_edit_units_from_prediction_row(row: dict[str, Any]) -> list[EditUnitRecord]:
    return [EditUnitRecord.from_dict(item) for item in _extract_edit_units_raw(row)]


def _has_standard_shape(row: dict[str, Any]) -> bool:
    if row.get("sample_id") is None:
        return False
    rich_fields = sum(1 for key in ("count_probs", "active_slots", "edit_units", "unit_assignment_scores") if key in row)
    return ("predicted_count" in row or "pred_count" in row) and rich_fields >= 1


def _has_legacy_aliases(row: dict[str, Any]) -> bool:
    legacy_keys = {"k_hat", "pred_count", "assignment", "assignments", "slot_probs", "slot_exist", "unit_records", "hunks"}
    return row.get("sample_id") is not None and any(key in row for key in legacy_keys)


def _extract_predicted_count(row: dict[str, Any]) -> int | None:
    value = row.get("predicted_count", row.get("pred_count", row.get("k_hat")))
    return int(value) if value is not None else None


def _extract_count_probs(row: dict[str, Any]) -> dict[str, float]:
    payload = row.get("count_probs", row.get("slot_probs", row.get("count_probabilities", {})))
    if not isinstance(payload, dict):
        return {}
    return {str(key): float(value) for key, value in payload.items()}


def _extract_assignment_scores(row: dict[str, Any]) -> dict[str, dict[str, float]]:
    payload = row.get("unit_assignment_scores", row.get("assignment_scores", {}))
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for unit_id, scores in payload.items():
        if isinstance(scores, dict):
            normalized[str(unit_id)] = {str(slot_id): float(score) for slot_id, score in scores.items()}
    return normalized


def _extract_unit_to_slot(row: dict[str, Any]) -> dict[str, str]:
    payload = row.get("unit_to_slot", row.get("assignments", row.get("assignment", {})))
    if isinstance(payload, dict):
        return {str(key): str(value) for key, value in payload.items()}
    if isinstance(payload, list):
        mapping: dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            unit_id = item.get("unit_id")
            slot_id = item.get("slot_id", item.get("slot"))
            if unit_id is not None and slot_id is not None:
                mapping[str(unit_id)] = str(slot_id)
        return mapping
    return {}


def _extract_active_slots(row: dict[str, Any], unit_to_slot: dict[str, str]) -> list[dict[str, Any]]:
    raw_slots = row.get("active_slots")
    if isinstance(raw_slots, list) and raw_slots:
        slots: list[dict[str, Any]] = []
        for item in raw_slots:
            slot = _normalize_slot_dict(item)
            if slot["slot_id"] == NULL_SLOT_ID:
                continue
            slots.append(slot)
        return slots

    slot_exist = row.get("slot_exist")
    if isinstance(slot_exist, dict) and slot_exist:
        slots: list[dict[str, Any]] = []
        for slot_id, existence_prob in slot_exist.items():
            if str(slot_id) == NULL_SLOT_ID:
                continue
            slots.append(
                {
                    "slot_id": str(slot_id),
                    "existence_prob": float(existence_prob) if existence_prob is not None else None,
                    "edit_unit_ids": [unit_id for unit_id, assigned_slot in unit_to_slot.items() if assigned_slot == str(slot_id)],
                    "hunk_ids": [],
                    "confidence": None,
                    "assignment_scores": {},
                    "diagnostics": {},
                }
            )
        return slots

    if unit_to_slot:
        slots: list[dict[str, Any]] = []
        for slot_id in sorted(set(unit_to_slot.values())):
            if slot_id == NULL_SLOT_ID:
                continue
            slots.append(
                {
                    "slot_id": slot_id,
                    "existence_prob": None,
                    "edit_unit_ids": [unit_id for unit_id, assigned_slot in unit_to_slot.items() if assigned_slot == slot_id],
                    "hunk_ids": [],
                    "confidence": None,
                    "assignment_scores": {},
                    "diagnostics": {},
                }
            )
        return slots
    return []


def _extract_all_slots(row: dict[str, Any], active_slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_all_slots = row.get("all_slots")
    if isinstance(raw_all_slots, list) and raw_all_slots:
        return [_normalize_slot_dict(item) for item in raw_all_slots]
    return list(active_slots)


def _extract_edit_units_raw(row: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(row.get("edit_units"), list):
        return [item for item in row["edit_units"] if isinstance(item, dict)]
    if isinstance(row.get("unit_records"), list):
        return [item for item in row["unit_records"] if isinstance(item, dict)]
    if isinstance(row.get("hunks"), list):
        rows: list[dict[str, Any]] = []
        for hunk in row["hunks"]:
            if not isinstance(hunk, dict):
                continue
            for unit in hunk.get("edit_units", []):
                if isinstance(unit, dict):
                    copied = dict(unit)
                    copied.setdefault("hunk_id", hunk.get("hunk_id"))
                    rows.append(copied)
        return rows
    return []


def _normalize_slot_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        return {
            "slot_id": payload,
            "existence_prob": None,
            "edit_unit_ids": [],
            "hunk_ids": [],
            "confidence": None,
            "assignment_scores": {},
            "diagnostics": {},
        }
    if isinstance(payload, dict):
        return {
            "slot_id": str(payload.get("slot_id", payload.get("slot", "unknown_slot"))),
            "existence_prob": float(payload["existence_prob"]) if payload.get("existence_prob") is not None else None,
            "edit_unit_ids": [str(item) for item in payload.get("edit_unit_ids", [])],
            "hunk_ids": [str(item) for item in payload.get("hunk_ids", [])],
            "confidence": float(payload["confidence"]) if payload.get("confidence") is not None else None,
            "assignment_scores": {
                str(key): float(value) for key, value in dict(payload.get("assignment_scores", {})).items()
            },
            "diagnostics": dict(payload.get("diagnostics", {})),
        }
    return {
        "slot_id": "unknown_slot",
        "existence_prob": None,
        "edit_unit_ids": [],
        "hunk_ids": [],
        "confidence": None,
        "assignment_scores": {},
        "diagnostics": {},
    }


def _has_slot_existence(row: dict[str, Any], active_slots: list[dict[str, Any]]) -> bool:
    if isinstance(row.get("slot_exist"), dict) and row["slot_exist"]:
        return True
    return any(slot.get("existence_prob") is not None for slot in active_slots)


def _diag(code: str, severity: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}
