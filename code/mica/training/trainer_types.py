from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TrainBatch:
    sample_ids: list[str]
    source_kind: str
    edit_units: list[dict[str, Any]]
    gold_count: int | None = None
    gold_unit_to_intent: dict[str, str] | None = None
    gold_hunk_to_intent: dict[str, str] | None = None
    weak_label: str | None = None
    sample_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrainOutputs:
    count_logits: Any
    count_probs: Any
    pb_count_probs: Any
    slot_exist_probs: Any
    assignments: dict[str, str]
    assignment_scores: dict[str, dict[str, float]]
    slot_representations: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    assignment_logits: Any | None = None
    assignment_probs: Any | None = None
    null_assignment_probs: Any | None = None
    predicted_count: int | None = None
    active_slot_indices: list[int] = field(default_factory=list)
    unit_mask: Any | None = None


@dataclass(slots=True)
class LossResult:
    loss: Any
    loss_name: str
    components: dict[str, Any]
    diagnostics: dict[str, Any]
    source_kind: str


@dataclass(slots=True)
class TrainStepResult:
    sample_ids: list[str]
    source_kind: str
    loss_total: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EpochResult:
    step_count: int
    mean_loss: float
    source_kind_counts: dict[str, int]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    gradient_step_count: int = 0
    nan_step_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ComponentFreezePlan:
    phase: str
    frozen_components: list[str]
    trainable_components: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningRatePlan:
    base_lr: float
    component_lrs: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CheckpointPlan:
    output_dir: str | None
    save_every_n_steps: int | None
    keep_last_k: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrainingPlan:
    stage: str
    mode: str
    approved: bool
    dry_run: bool
    trainable_components: list[str]
    frozen_components: list[str]
    loss_weights: dict[str, float]
    data_mixture: dict[str, Any]
    forbidden_assets: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
