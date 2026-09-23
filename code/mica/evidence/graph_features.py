from __future__ import annotations

from typing import Any

import torch

from code.mica.evidence.relation_bias import relation_features_to_bias
from code.mica.evidence.relations import compute_edit_unit_relations


def build_relation_matrix(edit_units: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    unit_ids = [str(unit.get("unit_id", f"unit_{index}")) for index, unit in enumerate(edit_units)]
    relations: dict[str, dict[str, dict[str, Any]]] = {unit_id: {} for unit_id in unit_ids}
    for left_index, left in enumerate(edit_units):
        left_id = unit_ids[left_index]
        for right_index, right in enumerate(edit_units):
            right_id = unit_ids[right_index]
            if left_index == right_index:
                relations[left_id][right_id] = {"same_file": True, "same_hunk": True, "path_distance": 0.0, "identifier_jaccard": 1.0}
            else:
                relations[left_id][right_id] = compute_edit_unit_relations(left, right, spec)
    return {"unit_ids": unit_ids, "relations": relations}


def build_attention_bias_matrix(edit_units: list[dict[str, Any]], spec: dict[str, Any]) -> torch.Tensor:
    relation_matrix = build_relation_matrix(edit_units, spec)
    weights = dict(spec.get("relation_weights", {}))
    unit_ids = relation_matrix["unit_ids"]
    size = len(unit_ids)
    matrix = torch.zeros(size, size, dtype=torch.float32)
    for row_index, left_id in enumerate(unit_ids):
        for col_index, right_id in enumerate(unit_ids):
            matrix[row_index, col_index] = relation_features_to_bias(relation_matrix["relations"][left_id][right_id], weights)
    return matrix

