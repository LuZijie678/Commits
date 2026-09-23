from __future__ import annotations

from collections import Counter


def renderer_surface_distance(pred: str, target: str) -> dict[str, object]:
    pred_tokens = pred.split()
    target_tokens = target.split()
    if not target_tokens and not pred_tokens:
        mismatch = 0.0
    else:
        overlap = sum((Counter(pred_tokens) & Counter(target_tokens)).values())
        mismatch = 1.0 - (2.0 * overlap / max(len(pred_tokens) + len(target_tokens), 1))
    return {
        "surface_distance": mismatch,
        "loss_total": mismatch,
        "proxy_only": True,
        "training_executed": False,
    }


def entity_copy_loss(message: str, evidence_entities: list[str], lambda_copy: float = 0.1) -> dict[str, object]:
    normalized_message = message.lower()
    normalized_entities = [entity.lower() for entity in evidence_entities if entity]
    if not normalized_entities:
        return {
            "loss_total": 0.0,
            "entity_copy_coverage": 1.0,
            "proxy_only": True,
            "missing_entities": [],
        }
    covered = [entity for entity in normalized_entities if entity in normalized_message]
    coverage = len(covered) / len(normalized_entities)
    missing = [entity for entity in normalized_entities if entity not in covered]
    return {
        "loss_total": lambda_copy * (1.0 - coverage),
        "entity_copy_coverage": coverage,
        "proxy_only": True,
        "missing_entities": missing,
    }
