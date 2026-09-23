from __future__ import annotations

from typing import Any

from code.mica.baselines.pretrained_generation_baseline import build_pretrained_generation_manifest


def build_pretrained_classifier_placeholder(model_name: str) -> dict[str, Any]:
    payload = build_pretrained_generation_manifest(model_name=model_name, sample={})
    payload.update(
        {
            "implemented": True,
            "requires_external_model": True,
            "not_run": True,
            "status": "deprecated_alias_for_pretrained_generation",
            "deprecated_alias_for": "pretrained_generation",
        }
    )
    return payload
