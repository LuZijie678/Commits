from __future__ import annotations

from code.mica.evidence.relation_bias import relation_features_to_bias


def test_relation_bias_uses_configured_weights_and_can_penalize_generated_files() -> None:
    features = {
        "same_file": True,
        "same_hunk": False,
        "path_distance": 2.0,
        "generated_file": True,
        "identifier_jaccard": 0.5,
    }
    weights = {
        "same_file": 1.0,
        "path_distance": -0.1,
        "generated_file": -0.5,
        "identifier_jaccard": 0.8,
    }

    bias = relation_features_to_bias(features, weights)

    assert bias != 0.0
    assert bias < 1.0

