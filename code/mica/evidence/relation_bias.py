from __future__ import annotations

from typing import Any


def relation_features_to_bias(features: dict[str, Any], weights: dict[str, float]) -> float:
    bias = 0.0
    for key, weight in weights.items():
        value = features.get(key)
        if isinstance(value, bool):
            numeric = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            numeric = float(value)
        else:
            numeric = 0.0
        bias += float(weight) * numeric
    return bias

