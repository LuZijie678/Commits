from __future__ import annotations

from typing import Any

from code.mica.data.renderer_dataset import build_renderer_training_samples, summarize_renderer_dataset


def prepare_stage4_renderer_training(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage": spec.get("stage", "stage4_evidence_locked_renderer"),
        "dataset_summary": summarize_renderer_dataset(rows),
        "training_samples": build_renderer_training_samples(rows),
        "training_executed": False,
    }
