from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.runners.consumer_runner_utils import (
    atomic_write_jsonl,
    build_runner_error,
    ensure_writable_output,
    read_jsonl_records_with_errors,
)
from code.mica.schema_validation import (
    validate_attribution_prediction_contract,
    validate_backend_snapshot_contract,
)
from code.mica.training.trainer_types import TrainBatch, TrainOutputs


SAFE_EDIT_UNIT_KEYS = {
    "unit_id",
    "hunk_id",
    "file_path",
    "file_role",
    "language",
    "patch_text",
    "added_lines",
    "deleted_lines",
    "changed_identifiers",
    "metadata",
    "old_span",
    "new_span",
    "old_text",
    "new_text",
}
FORBIDDEN_METADATA_KEYS = {
    "commit_message",
    "gold_count",
    "gold_hunk_to_intent",
    "gold_intent_id",
    "gold_unit_to_intent",
    "issue_text",
    "pr_text",
    "pr_title",
    "synthetic_metadata",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Stage 1 backend snapshots into canonical prediction JSONL.")
    parser.add_argument("--backend-snapshot-jsonl", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--error-jsonl")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--lenient", action="store_true")
    return parser


def build_prediction_row_from_backend(
    *,
    batch: TrainBatch | dict[str, Any],
    outputs: TrainOutputs | dict[str, Any],
    source: str = "mica_model_backend_export",
) -> dict[str, Any]:
    snapshot = build_backend_snapshot_row(batch=batch, outputs=outputs, source=source)
    contract = validate_backend_snapshot_contract(snapshot)
    if not contract["valid"]:
        raise ValueError("; ".join(contract["errors"]))

    batch_payload = dict(snapshot["train_batch"])
    outputs_payload = dict(snapshot["train_outputs"])
    sample_ids = [str(item) for item in batch_payload.get("sample_ids", [])]
    if len(sample_ids) != 1:
        raise ValueError("multi_sample_snapshot_not_exportable")
    sample_id = sample_ids[0]
    edit_units = [dict(unit) for unit in batch_payload.get("edit_units", [])]
    if not edit_units:
        raise ValueError("missing_edit_units")

    count_probs = _coerce_probability_dict(outputs_payload.get("count_probs"))
    if not count_probs:
        raise ValueError("missing_count_probs")
    predicted_count = int(outputs_payload.get("predicted_count") or _argmax_prediction(count_probs))

    slot_exist_probs = _coerce_probability_list(outputs_payload.get("slot_exist_probs"))
    if not slot_exist_probs:
        raise ValueError("missing_slot_exist_probs")

    assignments = {str(key): str(value) for key, value in dict(outputs_payload.get("assignments", {})).items()}
    if not assignments:
        raise ValueError("missing_unit_to_slot")
    assignment_scores = _normalize_assignment_scores(outputs_payload.get("assignment_scores", {}))
    if not assignment_scores:
        raise ValueError("missing_assignment_scores")

    diagnostics = dict(outputs_payload.get("diagnostics", {}))
    batch_metadata = dict(batch_payload.get("metadata", {}))
    release_decision = diagnostics.get("release_decision") or batch_metadata.get("release_decision")
    if not release_decision:
        raise ValueError("missing_release_decision")
    risk_score = diagnostics.get("selective_risk_score", batch_metadata.get("risk_score"))

    active_slot_indices = [
        int(index) for index in list(outputs_payload.get("active_slot_indices", []))
    ] or _topk_slot_indices(slot_exist_probs, predicted_count)

    all_slots = _build_slot_rows(
        slot_indices=list(range(len(slot_exist_probs))),
        slot_exist_probs=slot_exist_probs,
        assignments=assignments,
        assignment_scores=assignment_scores,
    )
    active_slots = _build_slot_rows(
        slot_indices=active_slot_indices,
        slot_exist_probs=slot_exist_probs,
        assignments=assignments,
        assignment_scores=assignment_scores,
    )
    background_units = _dedupe_preserve(
        [str(item) for item in batch_metadata.get("background_units", [])]
        + [unit_id for unit_id, slot_id in assignments.items() if slot_id == "slot_null"]
    )
    background_records = _resolve_background_records(
        edit_units=edit_units,
        background_units=background_units,
        explicit_records=batch_metadata.get("background_unit_records", []),
        assignment_scores=assignment_scores,
        assignments=assignments,
    )
    metadata = {
        **batch_metadata,
        "commit_id": str(batch_metadata.get("commit_id") or sample_id),
        "release_decision": str(release_decision),
        "risk_score": float(risk_score) if risk_score is not None else None,
        "background_units": background_units,
        "background_unit_records": background_records,
    }
    row = {
        "sample_id": sample_id,
        "predicted_count": predicted_count,
        "count_probs": count_probs,
        "active_slots": active_slots,
        "all_slots": all_slots,
        "unit_to_slot": assignments,
        "unit_assignment_scores": assignment_scores,
        "unit_records": edit_units,
        "source": source,
        "metadata": metadata,
    }
    contract = validate_attribution_prediction_contract(row, mode="review_ready")
    if not contract["valid"]:
        raise ValueError("; ".join(contract["errors"]))
    return row


def build_backend_snapshot_row(
    *,
    batch: TrainBatch | dict[str, Any],
    outputs: TrainOutputs | dict[str, Any],
    source: str = "mica_model_backend_export",
) -> dict[str, Any]:
    batch_payload = _batch_to_dict(batch)
    outputs_payload = _outputs_to_dict(outputs)
    sample_ids = [str(item) for item in batch_payload.get("sample_ids", [])]
    sanitized_batch = {
        "sample_ids": sample_ids,
        "source_kind": batch_payload.get("source_kind"),
        "edit_units": [_sanitize_edit_unit(unit) for unit in batch_payload.get("edit_units", [])],
        "metadata": _sanitize_metadata(batch_payload.get("metadata", {})),
    }
    sanitized_outputs = {
        "count_probs": outputs_payload.get("count_probs"),
        "pb_count_probs": outputs_payload.get("pb_count_probs"),
        "slot_exist_probs": outputs_payload.get("slot_exist_probs"),
        "assignments": {str(key): str(value) for key, value in dict(outputs_payload.get("assignments", {})).items()},
        "assignment_scores": _normalize_assignment_scores(outputs_payload.get("assignment_scores", {})),
        "diagnostics": _sanitize_metadata(outputs_payload.get("diagnostics", {})),
        "predicted_count": outputs_payload.get("predicted_count"),
        "active_slot_indices": list(outputs_payload.get("active_slot_indices", [])),
    }
    snapshot = {
        "train_batch": sanitized_batch,
        "train_outputs": sanitized_outputs,
        "source": source,
    }
    if len(sample_ids) == 1:
        snapshot["sample_id"] = sample_ids[0]
    return snapshot


def build_backend_snapshot_rows_from_samples(
    *,
    batch_samples: list[Any],
    tensor_batch: dict[str, Any],
    backend: Any,
    source: str = "mica_model_backend_export",
) -> list[dict[str, Any]]:
    snapshot_rows: list[dict[str, Any]] = []
    batch_size = len(batch_samples)
    for sample_offset, sample in enumerate(batch_samples):
        sample_tensor_batch = _slice_tensor_batch_for_sample(
            tensor_batch=tensor_batch,
            sample_offset=sample_offset,
            batch_size=batch_size,
        )
        train_batch = _build_sample_train_batch(sample=sample, tensor_batch=sample_tensor_batch)
        outputs = backend.forward(train_batch)
        snapshot_rows.append(
            build_backend_snapshot_row(
                batch=train_batch,
                outputs=outputs,
                source=source,
            )
        )
    return snapshot_rows


def export_stage1_predictions(
    *,
    backend_snapshot_jsonl: str | Path,
    output_jsonl: str | Path,
    error_jsonl: str | Path | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    if not validate_only:
        ensure_writable_output(output_jsonl, overwrite=overwrite)
        if error_jsonl is not None:
            ensure_writable_output(error_jsonl, overwrite=overwrite)

    rows, parse_errors = read_jsonl_records_with_errors(backend_snapshot_jsonl, strict=strict)
    exported_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = list(parse_errors)
    source_kind_distribution: dict[str, int] = {}
    release_decision_distribution: dict[str, int] = {}
    exported_samples_preview: list[str] = []

    for index, row in enumerate(rows, 1):
        sample_id = str(row.get("sample_id") or row.get("train_batch", {}).get("sample_ids", [f"__row_{index}__"])[0])
        try:
            sanitized_snapshot = build_backend_snapshot_row(
                batch=dict(row.get("train_batch", {})),
                outputs=dict(row.get("train_outputs", {})),
                source=str(row.get("source", "mica_model_backend_export")),
            )
            snapshot_contract = validate_backend_snapshot_contract(sanitized_snapshot)
            if not snapshot_contract["valid"]:
                raise ValueError("; ".join(snapshot_contract["errors"]))
            prediction_row = build_prediction_row_from_backend(
                batch=dict(sanitized_snapshot.get("train_batch", {})),
                outputs=dict(sanitized_snapshot.get("train_outputs", {})),
                source=str(sanitized_snapshot.get("source", "mica_model_backend_export")),
            )
            exported_rows.append(prediction_row)
            source_kind = sanitized_snapshot.get("train_batch", {}).get("source_kind")
            if source_kind:
                source_kind_key = str(source_kind)
                source_kind_distribution[source_kind_key] = source_kind_distribution.get(source_kind_key, 0) + 1
            release_decision = prediction_row.get("metadata", {}).get("release_decision")
            if release_decision:
                release_key = str(release_decision)
                release_decision_distribution[release_key] = release_decision_distribution.get(release_key, 0) + 1
            if len(exported_samples_preview) < 20:
                exported_samples_preview.append(str(prediction_row["sample_id"]))
        except Exception as exc:  # noqa: BLE001 - keep exporting remaining rows.
            error_rows.append(
                build_runner_error(
                    error_type="schema_validation_error",
                    message=str(exc),
                    sample_id=sample_id,
                    record_index=index,
                )
            )

    error_type_counts: dict[str, int] = {}
    for row in error_rows:
        error_type = row.get("error_type")
        if error_type is None:
            continue
        error_type_key = str(error_type)
        error_type_counts[error_type_key] = error_type_counts.get(error_type_key, 0) + 1
    summary = {
        "schema_version": "mica-stage1-prediction-export-v1",
        "validate_only": validate_only,
        "sample_counts": {
            "total": len(rows) + len(parse_errors),
            "exported": len(exported_rows),
            "errors": len(error_rows),
        },
        "source_kind_distribution": source_kind_distribution,
        "release_decision_distribution": release_decision_distribution,
        "error_type_counts": error_type_counts,
        "exported_samples_preview": exported_samples_preview,
    }
    if not validate_only:
        atomic_write_jsonl(output_jsonl, exported_rows, overwrite=overwrite)
        if error_jsonl is not None and error_rows:
            atomic_write_jsonl(error_jsonl, error_rows, overwrite=overwrite)
    return summary


def _slice_tensor_batch_for_sample(
    *,
    tensor_batch: dict[str, Any],
    sample_offset: int,
    batch_size: int,
) -> dict[str, Any]:
    sliced: dict[str, Any] = {}
    for key, value in dict(tensor_batch).items():
        if hasattr(value, "shape") and getattr(value, "shape", None):
            if getattr(value, "shape")[0] == batch_size:
                sliced[key] = value[sample_offset : sample_offset + 1]
                continue
        if isinstance(value, list) and len(value) == batch_size:
            sliced[key] = [value[sample_offset]]
            continue
        sliced[key] = value
    return sliced


def _build_sample_train_batch(*, sample: Any, tensor_batch: dict[str, Any]) -> TrainBatch:
    edit_units = [_sample_edit_unit_to_record(unit) for unit in list(getattr(sample, "edit_units", []))]
    return TrainBatch(
        sample_ids=[str(getattr(sample, "sample_id"))],
        source_kind=str(getattr(sample, "source_kind", "debug_sample")),
        edit_units=edit_units,
        metadata={
            "commit_id": str(getattr(sample, "sample_id")),
            "tensor_batch": tensor_batch,
        },
    )


def _sample_edit_unit_to_record(unit: Any) -> dict[str, Any]:
    return {
        "unit_id": str(getattr(unit, "unit_id")),
        "hunk_id": str(getattr(unit, "hunk_id", getattr(unit, "unit_id"))),
        "file_path": str(getattr(unit, "file_path")),
        "file_role": str(getattr(unit, "file_role", "source")),
        "language": getattr(unit, "language", None),
        "patch_text": getattr(unit, "patch_text", None),
        "added_lines": list(getattr(unit, "added_lines", []) or []),
        "deleted_lines": list(getattr(unit, "deleted_lines", []) or []),
        "changed_identifiers": list(getattr(unit, "identifiers", getattr(unit, "changed_identifiers", [])) or []),
        "metadata": {
            "enclosing_symbol_type": getattr(unit, "enclosing_symbol_type", None),
            "enclosing_symbol_name": getattr(unit, "enclosing_symbol_name", None),
            "enclosing_symbol_signature": getattr(unit, "enclosing_symbol_signature", None),
            "enclosing_symbol_resolution_status": getattr(unit, "enclosing_symbol_resolution_status", None),
            "context_clipped": bool(getattr(unit, "context_clipped", False)),
            "provenance_status": getattr(unit, "provenance_status", None),
            "source_atomic_commit_ids": list(getattr(unit, "source_atomic_commit_ids", []) or []),
        },
        "old_span": getattr(unit, "enclosing_symbol_old_span", None),
        "new_span": getattr(unit, "enclosing_symbol_new_span", None),
        "old_text": getattr(unit, "enclosing_symbol_old_text", None),
        "new_text": getattr(unit, "enclosing_symbol_new_text", None),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        export_stage1_predictions(
            backend_snapshot_jsonl=args.backend_snapshot_jsonl,
            output_jsonl=args.output_jsonl,
            error_jsonl=args.error_jsonl,
            overwrite=args.overwrite,
            validate_only=args.validate_only,
            strict=not args.lenient,
        )
    except (FileNotFoundError, FileExistsError, ValueError):
        return 2
    except Exception:
        return 3
    return 0


def _batch_to_dict(batch: TrainBatch | dict[str, Any]) -> dict[str, Any]:
    if isinstance(batch, TrainBatch):
        return {
            "sample_ids": list(batch.sample_ids),
            "source_kind": batch.source_kind,
            "edit_units": [dict(item) for item in batch.edit_units],
            "metadata": dict(batch.metadata),
        }
    return dict(batch)


def _outputs_to_dict(outputs: TrainOutputs | dict[str, Any]) -> dict[str, Any]:
    if isinstance(outputs, TrainOutputs):
        return {
            "count_probs": outputs.count_probs,
            "pb_count_probs": outputs.pb_count_probs,
            "slot_exist_probs": outputs.slot_exist_probs,
            "assignments": dict(outputs.assignments),
            "assignment_scores": {
                str(unit_id): {str(slot_id): float(score) for slot_id, score in slot_scores.items()}
                for unit_id, slot_scores in outputs.assignment_scores.items()
            },
            "diagnostics": dict(outputs.diagnostics),
            "predicted_count": outputs.predicted_count,
            "active_slot_indices": list(outputs.active_slot_indices),
        }
    return dict(outputs)


def _coerce_probability_dict(payload: Any) -> dict[str, float]:
    if isinstance(payload, dict):
        return {str(index): float(value) for index, value in payload.items()}
    values = _coerce_probability_list(payload)
    return {str(index + 1): float(value) for index, value in enumerate(values)}


def _coerce_probability_list(payload: Any) -> list[float]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        items = sorted(((int(key), float(value)) for key, value in payload.items()), key=lambda item: item[0])
        return [value for _, value in items]
    if hasattr(payload, "detach") and hasattr(payload, "cpu"):
        payload = payload.detach().cpu().tolist()
    if isinstance(payload, (list, tuple)):
        if payload and isinstance(payload[0], (list, tuple)):
            payload = payload[0]
        return [float(value) for value in payload]
    return []


def _argmax_prediction(count_probs: dict[str, float]) -> int:
    ranked = sorted(((int(key), float(value)) for key, value in count_probs.items()), key=lambda item: item[1], reverse=True)
    if not ranked:
        raise ValueError("missing_count_probs")
    return ranked[0][0]


def _topk_slot_indices(slot_exist_probs: list[float], predicted_count: int) -> list[int]:
    k_select = max(1, min(int(predicted_count), len(slot_exist_probs)))
    ranked = sorted(enumerate(slot_exist_probs), key=lambda item: item[1], reverse=True)
    return [index for index, _ in ranked[:k_select]]


def _normalize_assignment_scores(payload: Any) -> dict[str, dict[str, float]]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for unit_id, slot_scores in payload.items():
        if not isinstance(slot_scores, dict):
            continue
        normalized[str(unit_id)] = {str(slot_id): float(score) for slot_id, score in slot_scores.items()}
    return normalized


def _build_slot_rows(
    *,
    slot_indices: list[int],
    slot_exist_probs: list[float],
    assignments: dict[str, str],
    assignment_scores: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slot_index in slot_indices:
        slot_id = f"slot_{slot_index + 1}"
        rows.append(
            {
                "slot_id": slot_id,
                "existence_prob": float(slot_exist_probs[slot_index]),
                "edit_unit_ids": [unit_id for unit_id, assigned_slot in assignments.items() if assigned_slot == slot_id],
                "hunk_ids": [],
                "confidence": float(slot_exist_probs[slot_index]),
                "assignment_scores": {
                    unit_id: float(slot_scores[slot_id])
                    for unit_id, slot_scores in assignment_scores.items()
                    if slot_id in slot_scores
                },
                "diagnostics": {},
            }
        )
    return rows


def _sanitize_edit_unit(unit: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key in SAFE_EDIT_UNIT_KEYS:
        if key not in unit:
            continue
        if key == "metadata":
            raw_metadata = unit.get("metadata", {})
            sanitized["metadata"] = _sanitize_metadata(raw_metadata)
        elif isinstance(unit[key], list):
            sanitized[key] = [str(item) for item in unit[key]]
        else:
            sanitized[key] = unit[key]
    return sanitized


def _sanitize_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        lowered = key_text.lower()
        if key_text in FORBIDDEN_METADATA_KEYS:
            continue
        if any(token in lowered for token in ("gold", "synthetic", "provenance", "commit_message", "issue", "pr_title", "pr_text")):
            continue
        sanitized[key_text] = value
    return sanitized


def _resolve_background_records(
    *,
    edit_units: list[dict[str, Any]],
    background_units: list[str],
    explicit_records: Any,
    assignment_scores: dict[str, dict[str, float]],
    assignments: dict[str, str],
) -> list[dict[str, Any]]:
    edit_unit_index = {
        str(unit.get("unit_id")): unit
        for unit in edit_units
        if unit.get("unit_id") is not None
    }
    record_by_unit: dict[str, dict[str, Any]] = {}
    for record in explicit_records or []:
        if not isinstance(record, dict):
            continue
        unit_id = str(record.get("unit_id", "")).strip()
        if unit_id and unit_id in background_units:
            record_by_unit[unit_id] = _normalize_background_record(
                unit_id=unit_id,
                row=dict(record),
                fallback_unit=edit_unit_index.get(unit_id),
                assignment_scores=assignment_scores.get(unit_id, {}),
                assignments=assignments,
            )
    for unit_id in background_units:
        if unit_id in record_by_unit:
            continue
        fallback_unit = edit_unit_index.get(unit_id)
        if fallback_unit is None:
            continue
        record_by_unit[unit_id] = _normalize_background_record(
            unit_id=unit_id,
            row={},
            fallback_unit=fallback_unit,
            assignment_scores=assignment_scores.get(unit_id, {}),
            assignments=assignments,
        )
    return [record_by_unit[unit_id] for unit_id in background_units if unit_id in record_by_unit]


def _normalize_background_record(
    *,
    unit_id: str,
    row: dict[str, Any],
    fallback_unit: dict[str, Any] | None,
    assignment_scores: dict[str, float],
    assignments: dict[str, str],
) -> dict[str, Any]:
    fallback_unit = fallback_unit or {}
    is_null_assignment = assignments.get(unit_id) == "slot_null"
    file_role = str(row.get("file_role", fallback_unit.get("file_role", "")) or "")
    reason = str(row.get("background_reason") or _background_reason(file_role))
    return {
        "unit_id": unit_id,
        "hunk_id": row.get("hunk_id", fallback_unit.get("hunk_id")),
        "file_path": str(row.get("file_path", fallback_unit.get("file_path", "")) or ""),
        "file_role": file_role or None,
        "changed_identifiers": [
            str(item)
            for item in row.get("changed_identifiers", fallback_unit.get("changed_identifiers", [])) or []
        ],
        "patch_operation": str(row.get("patch_operation") or _patch_operation(fallback_unit) or "update"),
        "background_reason": reason,
        "background_confidence": float(row.get("background_confidence", assignment_scores.get("slot_null", 1.0))),
        "background_reason_source": str(
            row.get("background_reason_source")
            or ("null_slot_assignment" if is_null_assignment else "explicit_plan_metadata")
        ),
        "background_assignment_type": str(
            row.get("background_assignment_type")
            or ("model_assigned_background" if is_null_assignment else "explicit_background")
        ),
        "background_record_resolution_status": str(
            row.get("background_record_resolution_status")
            or ("complete" if is_null_assignment else "partial")
        ),
    }


def _background_reason(file_role: str) -> str:
    role = file_role.strip().lower()
    if role == "lockfile":
        return "lockfile"
    if role == "generated":
        return "generated"
    if role in {"format", "format-only"}:
        return "format_only"
    if role == "vendor":
        return "vendor"
    return "model_null_slot"


def _patch_operation(unit: dict[str, Any]) -> str:
    added = bool(unit.get("added_lines"))
    deleted = bool(unit.get("deleted_lines"))
    if added and deleted:
        return "update"
    if added:
        return "add"
    if deleted:
        return "remove"
    return "update"


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip()
        if token and token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())
