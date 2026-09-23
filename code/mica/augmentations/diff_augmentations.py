from __future__ import annotations

import copy
import random
from typing import Any

from code.mica.training.trainer_types import TrainBatch


def path_mask_batch(batch: TrainBatch, spec: dict[str, Any]) -> TrainBatch:
    del spec
    cloned = _clone_batch(batch, "path_mask")
    for unit in cloned.edit_units:
        unit["file_path"] = "MASKED_PATH"
    return cloned


def identifier_mask_batch(batch: TrainBatch, spec: dict[str, Any]) -> TrainBatch:
    del spec
    cloned = _clone_batch(batch, "identifier_mask")
    for unit in cloned.edit_units:
        unit["changed_identifiers"] = ["MASKED_IDENTIFIER" for _ in list(unit.get("changed_identifiers", []) or [])]
    return cloned


def file_order_permute_batch(batch: TrainBatch, seed: int) -> TrainBatch:
    cloned = _clone_batch(batch, "file_order_permute")
    rng = random.Random(seed)
    rng.shuffle(cloned.edit_units)
    cloned.metadata["augmentation_seed"] = seed
    return cloned


def context_line_dropout_batch(batch: TrainBatch, spec: dict[str, Any]) -> TrainBatch:
    drop_fraction = float(spec.get("drop_fraction", spec.get("context_line_dropout_fraction", 1.0)))
    cloned = _clone_batch(batch, "context_line_dropout")
    for unit in cloned.edit_units:
        lines = list(unit.get("context_lines", []) or [])
        keep = int(round(len(lines) * max(0.0, 1.0 - drop_fraction)))
        unit["context_lines"] = lines[:keep]
    return cloned


def _clone_batch(batch: TrainBatch, augmentation_name: str) -> TrainBatch:
    cloned = TrainBatch(
        sample_ids=list(batch.sample_ids),
        source_kind=batch.source_kind,
        edit_units=copy.deepcopy(batch.edit_units),
        gold_count=batch.gold_count,
        gold_unit_to_intent=copy.deepcopy(batch.gold_unit_to_intent),
        gold_hunk_to_intent=copy.deepcopy(batch.gold_hunk_to_intent),
        weak_label=batch.weak_label,
        sample_weight=batch.sample_weight,
        metadata=copy.deepcopy(batch.metadata),
    )
    cloned.metadata.setdefault("augmentations", []).append(augmentation_name)
    return cloned

