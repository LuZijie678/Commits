from __future__ import annotations

import hashlib
from typing import Any

import torch

from code.mica.data.context_protocol import build_commit_context_bundle, summarize_context_resolution
from code.mica.data.schema import MicaSample
from code.mica.features.evidence_features import build_edit_unit_features, build_pairwise_features
from code.mica.features.identifiers import extract_identifier_tokens, tokenize_path
from code.mica.model.null_slot import build_null_slot_mask


TEXT_VECTOR_DIM = 256
DENSE_FEATURE_NAMES = [
    "changed_line_count",
    "added_deleted_ratio",
    "hunk_index",
    "is_test",
    "is_doc",
    "is_config",
    "is_build",
    "is_lockfile",
    "is_generated_like",
]


def _stable_hash_index(token: str, dim: int) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % dim


def _vectorize_text(unit: Any, context_view: Any, dim: int) -> torch.Tensor:
    metadata = context_view.h_metadata
    metadata_tokens = [
        str(metadata.get("file_path") or ""),
        str(metadata.get("language") or ""),
        str(metadata.get("file_role") or ""),
        str(metadata.get("enclosing_symbol_type") or ""),
        str(metadata.get("enclosing_symbol_name") or ""),
        str(metadata.get("enclosing_symbol_signature") or ""),
        str(metadata.get("enclosing_symbol_resolution_status") or ""),
        *(metadata.get("changed_identifiers") or []),
    ]
    text = " ".join(
        [
            context_view.h_patch,
            context_view.h_symbol,
            *metadata_tokens,
            *unit.identifiers,
            *extract_identifier_tokens(context_view.h_patch),
            *extract_identifier_tokens(context_view.h_symbol),
            *tokenize_path(unit.file_path),
        ]
    )
    vector = torch.zeros(dim, dtype=torch.float32)
    for token in text.split():
        index = _stable_hash_index(token.lower(), dim)
        vector[index] += 1.0
    norm = vector.norm(p=2)
    if norm > 0:
        vector = vector / norm
    return vector


def collate_mica_samples(samples: list[MicaSample], *, text_vector_dim: int = TEXT_VECTOR_DIM) -> dict[str, Any]:
    if not samples:
        raise ValueError("collate_mica_samples requires at least one sample")
    batch_size = len(samples)
    max_units = max(len(sample.edit_units) for sample in samples)
    dense_dim = len(DENSE_FEATURE_NAMES)

    text_features = torch.zeros(batch_size, max_units, text_vector_dim, dtype=torch.float32)
    dense_features = torch.zeros(batch_size, max_units, dense_dim, dtype=torch.float32)
    pairwise_bias = torch.zeros(batch_size, max_units, max_units, dtype=torch.float32)
    unit_mask = torch.zeros(batch_size, max_units, dtype=torch.bool)
    background_targets = torch.zeros(batch_size, max_units, dtype=torch.float32)
    background_mask = torch.zeros(batch_size, max_units, dtype=torch.float32)
    gold_counts = torch.zeros(batch_size, dtype=torch.long)
    gold_assignment_masks: list[torch.Tensor] = []
    context_resolution_summaries: list[dict[str, Any]] = []
    context_bundle_diagnostics: list[dict[str, Any]] = []

    for batch_index, sample in enumerate(samples):
        gold_counts[batch_index] = sample.gold_count
        gold_masks = torch.zeros(sample.gold_count, max_units, dtype=torch.float32)
        null_mask = build_null_slot_mask([_unit_to_null_mask_row(unit) for unit in sample.edit_units], {"null_slot": {"null_slot_id": "slot_null"}})
        context_bundle = build_commit_context_bundle(sample.edit_units)
        context_views_by_unit_id = {view.unit_id: view for view in context_bundle.unit_views}
        context_resolution_summaries.append(summarize_context_resolution(sample.edit_units))
        context_bundle_diagnostics.append(context_bundle.diagnostics)
        for unit_index, unit in enumerate(sample.edit_units):
            unit_mask[batch_index, unit_index] = True
            text_features[batch_index, unit_index] = _vectorize_text(unit, context_views_by_unit_id[unit.unit_id], text_vector_dim)
            feature_payload = build_edit_unit_features(unit, hunk_index=unit_index)
            dense_features[batch_index, unit_index] = torch.tensor(
                [
                    float(feature_payload["changed_line_count"]),
                    float(feature_payload["added_deleted_ratio"]),
                    float(feature_payload["hunk_index"]),
                    float(bool(feature_payload["is_test"])),
                    float(bool(feature_payload["is_doc"])),
                    float(bool(feature_payload["is_config"])),
                    float(bool(feature_payload["is_build"])),
                    float(bool(feature_payload["is_lockfile"])),
                    float(bool(feature_payload["is_generated_like"])),
                ],
                dtype=torch.float32,
            )
            if unit.gold_intent_id is not None and 0 <= unit.gold_intent_id < sample.gold_count:
                gold_masks[unit.gold_intent_id, unit_index] = 1.0
                background_targets[batch_index, unit_index] = 0.0
                background_mask[batch_index, unit_index] = 1.0
            elif null_mask["eligible_by_unit_id"].get(unit.unit_id, False):
                background_targets[batch_index, unit_index] = 1.0
                background_mask[batch_index, unit_index] = 1.0
        gold_assignment_masks.append(gold_masks)
        for left_index, left_unit in enumerate(sample.edit_units):
            for right_index, right_unit in enumerate(sample.edit_units):
                pairwise = build_pairwise_features(left_unit, right_unit)
                pairwise_bias[batch_index, left_index, right_index] = (
                    float(bool(pairwise["same_file"]))
                    + 0.5 * float(bool(pairwise["same_directory"]))
                    + 0.5 * float(bool(pairwise["same_file_role"]))
                    + float(pairwise["identifier_jaccard"])
                    + float(pairwise["path_token_jaccard"])
                    + 0.5 * float(bool(pairwise["test_target_hint"]))
                    + 0.5 * float(bool(pairwise["doc_ref_hint"]))
                )

    return {
        "samples": samples,
        "text_features": text_features,
        "dense_features": dense_features,
        "pairwise_bias": pairwise_bias,
        "unit_mask": unit_mask,
        "gold_counts": gold_counts,
        "gold_assignment_masks": gold_assignment_masks,
        "background_targets": background_targets,
        "background_mask": background_mask,
        "dense_feature_names": list(DENSE_FEATURE_NAMES),
        "input_context_protocol": "patch_plus_marked_enclosing_symbol_context_hashed_features",
        "context_resolution_summary": context_resolution_summaries,
        "context_bundle_diagnostics": context_bundle_diagnostics,
    }


def _unit_to_null_mask_row(unit: Any) -> dict[str, Any]:
    return {
        "unit_id": unit.unit_id,
        "file_path": unit.file_path,
        "file_role": unit.file_role,
        "patch_text": unit.patch_text,
        "added_lines": list(unit.added_lines),
        "deleted_lines": list(unit.deleted_lines),
        "changed_identifiers": list(unit.identifiers),
    }
