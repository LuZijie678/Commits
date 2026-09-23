from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from code.mica.consumers.evidence_summarizer import DeterministicEvidenceSummarizer
from code.mica.consumers.message_generator import DeterministicMessageGenerator, FrozenLLMRenderer, GeneratedCommitMessage
from code.mica.consumers.plan_schema import StructuredIntentPlan as ConsumerStructuredIntentPlan
from code.mica.consumers.plan_schema import adapt_from_legacy_plan
from code.mica.losses.renderer_losses import entity_copy_loss, renderer_surface_distance
from code.mica.renderers.deterministic import RenderedMessage
from code.mica.schemas import StructuredIntentPlan as LegacyStructuredIntentPlan


FEATURE_NAMES = (
    "surface_match",
    "entity_copy_coverage",
    "fallback_penalty",
    "subject_length_ratio",
    "body_line_count",
    "summary_count",
)
CHECKPOINT_SCHEMA_VERSION = "mica-trainable-reranker-checkpoint-v1"
TRAINING_SCHEMA_VERSION = "mica-trainable-reranker-training-v1"
PREVIEW_SCHEMA_VERSION = "mica-trainable-reranker-preview-v1"


@dataclass(slots=True)
class CandidateTrainingRow:
    sample_id: str
    candidate: GeneratedCommitMessage
    features: list[float]
    label: float
    target_message: str


class CandidateReranker(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(input_dim, 1)

    @property
    def input_dim(self) -> int:
        return int(self.linear.in_features)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.linear(inputs)).squeeze(-1)


def train_candidate_reranker(
    *,
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[RenderedMessage], dict[str, Any]]:
    grouped_rows = _build_candidate_groups(rows=rows, spec=spec)
    training_rows = [item for _, sample_rows in grouped_rows for item in sample_rows]

    if not training_rows:
        raise ValueError("Stage 4 trainable reranker requires at least one decompose sample with candidates.")

    input_tensor = torch.tensor([item.features for item in training_rows], dtype=torch.float32)
    label_tensor = torch.tensor([item.label for item in training_rows], dtype=torch.float32)
    epochs = int(spec.get("reranker_epochs", 20) or 20)
    learning_rate = float(spec.get("reranker_learning_rate", 0.05) or 0.05)

    model = CandidateReranker(len(FEATURE_NAMES))
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.MSELoss()
    losses: list[float] = []
    for _ in range(epochs):
        optimizer.zero_grad()
        predictions = model(input_tensor)
        loss = loss_fn(predictions, label_tensor)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu().item()))

    rendered_rows: list[RenderedMessage] = []
    with torch.no_grad():
        for sample_id, candidate_rows in grouped_rows:
            sample_tensor = torch.tensor([item.features for item in candidate_rows], dtype=torch.float32)
            sample_scores = model(sample_tensor).detach().cpu().tolist()
            ranked = sorted(
                zip(candidate_rows, sample_scores),
                key=lambda item: (-float(item[1]), int(item[0].candidate.diagnostics.get("fallback_level", 0))),
            )
            winner, score = ranked[0]
            rendered_rows.append(
                RenderedMessage(
                    sample_id=sample_id,
                    subject=winner.candidate.subject,
                    body="\n".join(winner.candidate.body),
                    bullets=[line[2:] if line.startswith("- ") else line for line in winner.candidate.body],
                    degraded=bool(winner.candidate.diagnostics.get("fallback_level", 0)),
                    diagnostics=[
                        {
                            "code": "candidate_reranker_selected",
                            "severity": "info",
                            "message": "Trainable candidate reranker selected this candidate.",
                            "metadata": {"score": float(score), "target_message": winner.target_message},
                        }
                    ],
                    used_fallback_subject=bool(winner.candidate.diagnostics.get("fallback_level", 0)),
                    status=winner.candidate.status,
                    covered_slot_ids=list(winner.candidate.covered_slot_ids),
                    verification={},
                    fallback={
                        "fallback_used": bool(winner.candidate.diagnostics.get("fallback_level", 0)),
                        "fallback_level": winner.candidate.diagnostics.get("fallback_level", 0),
                    },
                )
            )

    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "training_schema_version": TRAINING_SCHEMA_VERSION,
        "model_type": "candidate_reranker",
        "feature_names": list(FEATURE_NAMES),
        "weights": [float(value) for value in model.linear.weight.detach().cpu().view(-1).tolist()],
        "bias": float(model.linear.bias.detach().cpu().item()),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "spec_hash": _spec_hash(spec),
    }
    metrics = {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "training_executed": True,
        "model_type": "candidate_reranker",
        "sample_count": len(grouped_rows),
        "candidate_count": len(training_rows),
        "train_loss": losses[-1],
        "best_label": max(item.label for item in training_rows),
        "mean_label": sum(item.label for item in training_rows) / len(training_rows),
        "feature_names": list(FEATURE_NAMES),
    }
    return checkpoint, rendered_rows, metrics


def load_candidate_reranker_checkpoint(checkpoint_payload: dict[str, Any]) -> CandidateReranker:
    feature_names = [str(item) for item in checkpoint_payload.get("feature_names", [])]
    if not feature_names:
        raise ValueError("candidate reranker checkpoint missing feature_names")
    weights = [float(item) for item in checkpoint_payload.get("weights", [])]
    if len(weights) != len(feature_names):
        raise ValueError("candidate reranker checkpoint weights do not match feature_names")
    model = CandidateReranker(len(feature_names))
    with torch.no_grad():
        model.linear.weight.copy_(torch.tensor([weights], dtype=torch.float32))
        model.linear.bias.copy_(torch.tensor([float(checkpoint_payload.get("bias", 0.0))], dtype=torch.float32))
    model.eval()
    return model


def score_candidates_with_checkpoint(
    *,
    rows: list[dict[str, Any]],
    checkpoint_payload: dict[str, Any],
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grouped_rows = _build_candidate_groups(rows=rows, spec=dict(spec or {"llm_api_enabled": False}))
    model = load_candidate_reranker_checkpoint(checkpoint_payload)
    result_rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for sample_id, candidate_rows in grouped_rows:
            sample_tensor = torch.tensor([item.features for item in candidate_rows], dtype=torch.float32)
            sample_scores = model(sample_tensor).detach().cpu().tolist()
            ranked = sorted(
                zip(candidate_rows, sample_scores),
                key=lambda item: (-float(item[1]), int(item[0].candidate.diagnostics.get("fallback_level", 0))),
            )
            result_rows.append(
                {
                    "sample_id": sample_id,
                    "winner": _candidate_preview(ranked[0][0], ranked[0][1]),
                    "candidates": [_candidate_preview(candidate_row, score) for candidate_row, score in ranked],
                }
            )
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "feature_names": list(checkpoint_payload.get("feature_names", [])),
        "rows": result_rows,
    }


def _coerce_plan(payload: dict[str, Any] | LegacyStructuredIntentPlan | ConsumerStructuredIntentPlan) -> ConsumerStructuredIntentPlan:
    if isinstance(payload, ConsumerStructuredIntentPlan):
        return payload
    if isinstance(payload, LegacyStructuredIntentPlan):
        return adapt_from_legacy_plan(payload)
    if "decision" in payload:
        return ConsumerStructuredIntentPlan.from_dict(payload)
    return adapt_from_legacy_plan(LegacyStructuredIntentPlan.from_dict(payload))


def _candidate_features(
    *,
    candidate: GeneratedCommitMessage,
    target_message: str,
    evidence_terms: list[str],
    summary_count: int,
) -> tuple[list[float], float]:
    surface = renderer_surface_distance(candidate.subject, target_message)
    entity_copy = entity_copy_loss(candidate.subject, evidence_terms, lambda_copy=0.1)
    fallback_level = int(candidate.diagnostics.get("fallback_level", 0) or 0)
    features = [
        1.0 - float(surface["surface_distance"]),
        float(entity_copy["entity_copy_coverage"]),
        float(fallback_level > 0),
        min(len(candidate.subject), 72) / 72.0,
        min(len(candidate.body), 4) / 4.0,
        min(summary_count, 4) / 4.0,
    ]
    label = 0.7 * features[0] + 0.3 * features[1]
    return features, label


def _build_candidate_groups(
    *,
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> list[tuple[str, list[CandidateTrainingRow]]]:
    deterministic_generator = DeterministicMessageGenerator()
    summarizer = DeterministicEvidenceSummarizer()
    llm_renderer = _build_optional_llm_renderer(spec)
    grouped_rows: list[tuple[str, list[CandidateTrainingRow]]] = []

    for row in rows:
        plan = _coerce_plan(row.get("structured_intent_plan", {}))
        if plan.decision != "decompose":
            continue
        summaries = [summarizer.summarize(intent) for intent in plan.intents]
        candidates = deterministic_generator.generate_candidates(
            summaries,
            plan_decision=plan.decision,
            background_terms=set(),
        )
        if llm_renderer is not None:
            try:
                candidates = llm_renderer.generate_candidates(
                    summaries,
                    plan_decision=plan.decision,
                    background_terms=set(),
                ) + candidates
            except Exception:
                pass
        sample_training_rows: list[CandidateTrainingRow] = []
        for candidate in candidates:
            features, label = _candidate_features(
                candidate=candidate,
                target_message=str(row.get("target_message", "")),
                evidence_terms=[str(item) for item in row.get("evidence_terms", [])],
                summary_count=len(summaries),
            )
            sample_training_rows.append(
                CandidateTrainingRow(
                    sample_id=str(row.get("sample_id", "")),
                    candidate=candidate,
                    features=features,
                    label=label,
                    target_message=str(row.get("target_message", "")),
                )
            )
        if sample_training_rows:
            grouped_rows.append((str(row.get("sample_id", "")), sample_training_rows))
    return grouped_rows


def _candidate_preview(candidate_row: CandidateTrainingRow, score: float) -> dict[str, Any]:
    return {
        "subject": candidate_row.candidate.subject,
        "body": list(candidate_row.candidate.body),
        "score": float(score),
        "fallback_level": int(candidate_row.candidate.diagnostics.get("fallback_level", 0)),
        "features": list(candidate_row.features),
        "target_message": candidate_row.target_message,
    }


def _spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _build_optional_llm_renderer(spec: dict[str, Any]) -> FrozenLLMRenderer | None:
    if not bool(spec.get("llm_api_enabled", False)):
        return None
    llm_config = dict(spec.get("frozen_llm_renderer", {}))
    if not llm_config:
        raise ValueError("Stage 4 llm_api_enabled=true requires frozen_llm_renderer config.")
    return FrozenLLMRenderer(
        config=llm_config,
        allow_real_api=bool(spec.get("allow_real_api", False)),
        dry_run=bool(spec.get("llm_dry_run", False)),
    )
