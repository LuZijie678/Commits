from __future__ import annotations

from code.mica.training.trainer_types import LearningRatePlan


def build_component_lr_groups(base_lr: float, *, encoder_lr_multiplier: float = 0.1, renderer_lr: float = 0.0) -> LearningRatePlan:
    component_lrs = {
        "encoder": base_lr * encoder_lr_multiplier,
        "slot_decoder": base_lr,
        "count_head": base_lr,
        "existence_head": base_lr,
        "thresholds": base_lr,
        "renderer": renderer_lr,
    }
    return LearningRatePlan(
        base_lr=base_lr,
        component_lrs=component_lrs,
        metadata={"encoder_lr_multiplier": encoder_lr_multiplier, "renderer_disabled": renderer_lr == 0.0},
    )
