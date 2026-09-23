from __future__ import annotations

import torch

from code.mica.evidence.graph_features import build_attention_bias_matrix, build_relation_matrix


def test_evidence_graph_helpers_build_relation_and_bias_matrices() -> None:
    edit_units = [
        {"unit_id": "u1", "file_path": "src/auth.py", "hunk_id": "h1", "file_role": "source", "language": "python", "changed_identifiers": ["token"]},
        {"unit_id": "u2", "file_path": "tests/test_auth.py", "hunk_id": "h2", "file_role": "test", "language": "python", "changed_identifiers": ["token"]},
    ]
    spec = {"relation_weights": {"same_file": 1.0, "test_target": 0.7, "identifier_jaccard": 0.5}}

    matrix = build_relation_matrix(edit_units, spec)
    bias = build_attention_bias_matrix(edit_units, spec)

    assert matrix["unit_ids"] == ["u1", "u2"]
    assert matrix["relations"]["u1"]["u2"]["test_target"] is True
    assert isinstance(bias, torch.Tensor)
    assert tuple(bias.shape) == (2, 2)

