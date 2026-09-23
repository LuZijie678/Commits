from __future__ import annotations

from typing import Any

from code.mica.training.trainer_types import TrainBatch


def adapt_strict_replay_batch(row: dict[str, Any]) -> TrainBatch:
    return TrainBatch(
        sample_ids=[str(row.get("sample_id", "missing_sample_id"))],
        source_kind="strict_replay",
        edit_units=list(row.get("edit_units", [])),
        gold_count=_optional_int(row.get("gold_count")),
        gold_unit_to_intent=_optional_dict(row.get("gold_unit_to_intent")),
        gold_hunk_to_intent=_optional_dict(row.get("gold_hunk_to_intent")),
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        metadata={"source_kind": row.get("source_kind", "strict_replay")},
    )


def adapt_hard_b_batch(row: dict[str, Any]) -> TrainBatch:
    return TrainBatch(
        sample_ids=[str(row.get("sample_id", "missing_sample_id"))],
        source_kind="hard_b",
        edit_units=list(row.get("edit_units", [])),
        gold_count=1,
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        metadata={"hard_b_alignment_required": False},
    )


def adapt_m_weak_batch(row: dict[str, Any]) -> TrainBatch:
    return TrainBatch(
        sample_ids=[str(row.get("sample_id", "missing_sample_id"))],
        source_kind="m_weak",
        edit_units=list(row.get("edit_units", [])),
        weak_label="censored_k_ge_2",
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        metadata={
            "weak_label_semantics": "censored_k_ge_2",
            "exact_k_supervision_used": False,
        },
    )


def adapt_real_alignment_batch(row: dict[str, Any]) -> TrainBatch:
    return TrainBatch(
        sample_ids=[str(row.get("sample_id", "missing_sample_id"))],
        source_kind="real_alignment",
        edit_units=list(row.get("edit_units", [])),
        gold_count=_optional_int(row.get("gold_count")),
        gold_unit_to_intent=_optional_dict(row.get("gold_unit_to_intent")),
        gold_hunk_to_intent=_optional_dict(row.get("gold_hunk_to_intent")),
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        metadata={"split": row.get("split")},
    )


def validate_train_batch(batch: TrainBatch) -> dict[str, Any]:
    diagnostics: list[str] = []
    if not batch.sample_ids or batch.sample_ids == ["missing_sample_id"]:
        diagnostics.append("missing_sample_id")
    if batch.source_kind in {"strict_replay", "real_alignment"}:
        if batch.gold_count is None:
            diagnostics.append("missing_gold_count")
        if not batch.gold_unit_to_intent and not batch.gold_hunk_to_intent:
            diagnostics.append("missing_alignment_gold")
    if batch.source_kind == "m_weak":
        if batch.weak_label != "censored_k_ge_2":
            diagnostics.append("invalid_weak_label")
        if batch.gold_count is not None:
            diagnostics.append("m_weak_should_not_have_exact_k")
    return {
        "valid": not diagnostics,
        "diagnostics": diagnostics,
        "source_kind": batch.source_kind,
    }


def _optional_dict(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
