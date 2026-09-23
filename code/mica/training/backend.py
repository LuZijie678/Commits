from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn

from code.mica.data.collate import collate_mica_samples
from code.mica.data.schema import EditUnit, MicaSample
from code.mica.decoding import decode_active_slot_assignments
from code.mica.models.mica_model import MicaModel
from code.mica.release_decision import decide_release
from code.mica.selective_risk import compute_selective_risk
from code.mica.training.trainer_types import ComponentFreezePlan, TrainBatch, TrainOutputs


def _count_lines(unit: dict[str, Any], key: str) -> int:
    value = unit.get(key, [])
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len([line for line in value.splitlines() if line.strip()])
    return 0


def _role_ratio(edit_units: list[dict[str, Any]], role: str) -> float:
    if not edit_units:
        return 0.0
    return sum(1 for unit in edit_units if str(unit.get("file_role", "")).lower() == role) / len(edit_units)


def batch_feature_vector(batch: TrainBatch) -> torch.Tensor:
    edit_units = list(batch.edit_units)
    file_paths = [str(unit.get("file_path", "")) for unit in edit_units if unit.get("file_path")]
    identifiers = [item for unit in edit_units for item in list(unit.get("changed_identifiers", []) or [])]
    patch_line_count = sum(len(str(unit.get("patch_text", "")).splitlines()) for unit in edit_units)
    path_parents = {path.rsplit("/", 1)[0] if "/" in path else path for path in file_paths}
    values = [
        float(len(edit_units)),
        float(len({str(unit.get("hunk_id")) for unit in edit_units if unit.get("hunk_id") is not None})),
        float(len(set(file_paths))),
        float(sum(_count_lines(unit, "added_lines") for unit in edit_units)),
        float(sum(_count_lines(unit, "deleted_lines") for unit in edit_units)),
        float(patch_line_count),
        float(len(set(identifiers))),
        float(len(path_parents)),
        _role_ratio(edit_units, "source"),
        _role_ratio(edit_units, "test"),
        _role_ratio(edit_units, "doc"),
        _role_ratio(edit_units, "config"),
    ]
    return torch.tensor(values, dtype=torch.float32)


def unit_feature_matrix(batch: TrainBatch) -> torch.Tensor:
    rows: list[list[float]] = []
    for index, unit in enumerate(batch.edit_units):
        identifiers = list(unit.get("changed_identifiers", []) or [])
        patch_text = str(unit.get("patch_text", ""))
        path = str(unit.get("file_path", ""))
        rows.append(
            [
                float(index),
                float(len(path.split("/"))),
                float(len(identifiers)),
                float(_count_lines(unit, "added_lines")),
                float(_count_lines(unit, "deleted_lines")),
                float(len(patch_text.splitlines())),
                float("test" in path.lower()),
                float("doc" in path.lower() or path.lower().endswith(".md")),
            ]
        )
    if not rows:
        rows = [[0.0] * 8]
    return torch.tensor(rows, dtype=torch.float32)


def semantic_unit_mask_from_batch(batch: TrainBatch) -> torch.Tensor:
    semantic_values: list[bool] = []
    for unit in batch.edit_units:
        role = str(unit.get("file_role", "source") or "source").lower()
        semantic_values.append(role not in {"generated", "lockfile", "vendor", "minified", "unknown_auxiliary"})
    if not semantic_values:
        semantic_values = [True]
    return torch.tensor(semantic_values, dtype=torch.bool)


def selective_risk_diagnostics(
    *,
    count_probs: torch.Tensor,
    pb_count_probs: torch.Tensor,
    assignment_probs: torch.Tensor,
    null_assignment_probs: torch.Tensor | None,
    batch: TrainBatch,
) -> dict[str, Any]:
    semantic_mask = semantic_unit_mask_from_batch(batch).to(device=assignment_probs.device)
    result = compute_selective_risk(
        count_probs=count_probs,
        pb_count_probs=pb_count_probs,
        assignment_probs=assignment_probs,
        null_assignment_probs=null_assignment_probs,
        semantic_unit_mask=semantic_mask,
    )
    return {
        "selective_risk_score": float(result.risk_score.detach().cpu().item()),
        "selective_risk_components": {
            name: float(value.detach().cpu().item())
            for name, value in result.components.items()
        },
        "selective_risk_protocol": result.diagnostics,
    }


def release_decision_diagnostics(*, risk_score: float, batch: TrainBatch) -> dict[str, Any]:
    threshold_value = batch.metadata.get("selective_risk_threshold", batch.metadata.get("release_threshold"))
    threshold = None if threshold_value in (None, "") else float(threshold_value)
    overflow_evidence = batch.metadata.get("overflow_evidence", batch.metadata.get("out_of_scope_evidence", []))
    if isinstance(overflow_evidence, str):
        overflow_evidence = [overflow_evidence]
    decision = decide_release(
        risk_score=float(risk_score),
        threshold=threshold,
        overflow_evidence=list(overflow_evidence or []),
        overflow_labels_available=bool(batch.metadata.get("overflow_labels_available", False)),
        abstention_reason=batch.metadata.get("abstention_reason"),
    )
    return {
        "release_decision": decision.decision,
        "release_covered": decision.covered,
        "release_threshold": decision.threshold,
        "overflow_evidence": decision.overflow_evidence,
        "abstention_reason": decision.abstention_reason,
        "release_protocol": decision.diagnostics,
    }


class TrainableAttributionBackend(ABC):
    @abstractmethod
    def forward(self, batch: TrainBatch) -> TrainOutputs:
        raise NotImplementedError

    @abstractmethod
    def trainable_parameters(self) -> list[nn.Parameter]:
        raise NotImplementedError

    @abstractmethod
    def set_train_mode(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_eval_mode(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_freeze_plan(self, freeze_plan: ComponentFreezePlan) -> dict[str, Any]:
        raise NotImplementedError


class ToyAttributionBackend(nn.Module, TrainableAttributionBackend):
    def __init__(self, *, kmax: int = 4, hidden_dim: int = 32) -> None:
        super().__init__()
        self.kmax = kmax
        self.base_encoder = nn.Linear(12, hidden_dim)
        self.adapter = nn.Linear(hidden_dim, hidden_dim)
        self.unit_encoder = nn.Linear(8, hidden_dim)
        self.count_head = nn.Linear(hidden_dim, kmax)
        self.pb_head = nn.Linear(hidden_dim, kmax)
        self.exist_head = nn.Linear(hidden_dim, kmax)
        self.slot_queries = nn.Parameter(torch.randn(kmax, hidden_dim) * 0.02)
        self.null_query = nn.Parameter(torch.randn(hidden_dim) * 0.02)
        self.count_temperature_log = nn.Parameter(torch.tensor(0.0))
        self.existence_temperature_log = nn.Parameter(torch.tensor(0.0))
        self.selective_risk_bias = nn.Parameter(torch.tensor(0.0))
        self.low_rank_unit_adapter = nn.Linear(hidden_dim, 4, bias=False)
        self.low_rank_slot_adapter = nn.Linear(hidden_dim, 4, bias=False)
        self.low_rank_adapter_scale = nn.Parameter(torch.tensor(0.0))
        nn.init.normal_(self.low_rank_unit_adapter.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.low_rank_slot_adapter.weight, mean=0.0, std=0.02)

    def forward(self, batch: TrainBatch) -> TrainOutputs:
        batch_features = batch_feature_vector(batch).unsqueeze(0)
        unit_features = unit_feature_matrix(batch)
        shared_hidden = torch.tanh(self.adapter(torch.relu(self.base_encoder(batch_features))))
        count_logits = self.count_head(shared_hidden) / self.count_temperature_log.exp().clamp_min(1e-6)
        pb_count_logits = self.pb_head(shared_hidden)
        count_probs = F.softmax(count_logits, dim=-1)
        pb_count_probs = F.softmax(pb_count_logits, dim=-1)
        slot_exist_logits = self.exist_head(shared_hidden) / self.existence_temperature_log.exp().clamp_min(1e-6)
        slot_exist_probs = torch.sigmoid(slot_exist_logits)

        unit_hidden = torch.tanh(self.adapter(torch.relu(self.unit_encoder(unit_features))))
        assignment_logits_per_unit = unit_hidden @ self.slot_queries.t()
        low_rank_delta = self.low_rank_adapter_scale * (
            self.low_rank_unit_adapter(unit_hidden) @ self.low_rank_slot_adapter(self.slot_queries).t()
        )
        assignment_logits_per_unit = assignment_logits_per_unit + low_rank_delta
        null_assignment_logits_per_unit = unit_hidden @ self.null_query
        joint_assignment_logits_per_unit = torch.cat(
            [assignment_logits_per_unit, null_assignment_logits_per_unit.unsqueeze(-1)],
            dim=-1,
        )
        joint_assignment_probs_per_unit = F.softmax(joint_assignment_logits_per_unit, dim=-1)
        assignment_probs_per_unit = joint_assignment_probs_per_unit[:, : self.kmax]
        null_assignment_probs = joint_assignment_probs_per_unit[:, self.kmax].unsqueeze(0)
        assignment_logits = assignment_logits_per_unit.transpose(0, 1).unsqueeze(0)
        assignment_probs = assignment_probs_per_unit.transpose(0, 1).unsqueeze(0)

        slot_representations = {f"slot_{index + 1}": self.slot_queries[index] for index in range(self.kmax)}
        unit_mask = torch.ones(1, max(len(batch.edit_units), 1), dtype=torch.bool)
        unit_ids = [str(unit.get("unit_id", f"unit_{index}")) for index, unit in enumerate(batch.edit_units)]
        decoded = decode_active_slot_assignments(
            count_probs=count_probs[0],
            slot_exist_probs=slot_exist_probs[0],
            assignment_probs=assignment_probs[0],
            null_assignment_probs=null_assignment_probs[0],
            unit_mask=unit_mask[0],
            unit_ids=unit_ids,
        )
        risk_diagnostics = selective_risk_diagnostics(
            count_probs=count_probs[0],
            pb_count_probs=pb_count_probs[0],
            assignment_probs=assignment_probs[0],
            null_assignment_probs=null_assignment_probs[0],
            batch=batch,
        )
        risk_diagnostics["selective_risk_score"] += float(self.selective_risk_bias.detach().cpu().item())
        release_diagnostics = release_decision_diagnostics(
            risk_score=float(risk_diagnostics["selective_risk_score"]),
            batch=batch,
        )
        return TrainOutputs(
            count_logits=count_logits,
            count_probs=count_probs,
            pb_count_probs=pb_count_probs,
            slot_exist_probs=slot_exist_probs,
            assignments=decoded.unit_to_slot,
            assignment_scores=decoded.unit_assignment_scores,
            slot_representations=slot_representations,
            diagnostics={**decoded.diagnostics, **risk_diagnostics, **release_diagnostics},
            assignment_logits=assignment_logits,
            assignment_probs=assignment_probs,
            null_assignment_probs=null_assignment_probs,
            predicted_count=decoded.predicted_count,
            active_slot_indices=decoded.active_slot_indices,
            unit_mask=unit_mask,
        )

    def trainable_parameters(self) -> list[nn.Parameter]:
        return [parameter for parameter in self.parameters() if parameter.requires_grad]

    def set_train_mode(self) -> None:
        self.train(True)

    def set_eval_mode(self) -> None:
        self.train(False)

    def apply_freeze_plan(self, freeze_plan: ComponentFreezePlan) -> dict[str, Any]:
        for parameter in self.parameters():
            parameter.requires_grad = False
        named_groups = {
            "base_encoder": [*self.base_encoder.parameters()],
            "encoder.lower": [*self.base_encoder.parameters()],
            "encoder.top": [*self.base_encoder.parameters()],
            "slot_decoder": [self.slot_queries],
            "slot_decoder_adapter": [*self.adapter.parameters(), *self.unit_encoder.parameters()],
            "assignment_decoder": [self.slot_queries],
            "count_head": [*self.count_head.parameters(), *self.pb_head.parameters()],
            "existence_head": [*self.exist_head.parameters()],
            "count_temperature": [self.count_temperature_log],
            "existence_temperature": [self.existence_temperature_log],
            "selective_risk_calibration": [self.selective_risk_bias],
            "low_rank_assignment_adapter": [
                *self.low_rank_unit_adapter.parameters(),
                *self.low_rank_slot_adapter.parameters(),
                self.low_rank_adapter_scale,
            ],
            "slot_existence_temperature": [self.existence_temperature_log],
        }
        for component in freeze_plan.trainable_components:
            for parameter in named_groups.get(component, []):
                parameter.requires_grad = True
        return {
            "phase": freeze_plan.phase,
            "frozen_components": list(freeze_plan.frozen_components),
            "trainable_components": list(freeze_plan.trainable_components),
            "freeze_base_encoder": "base_encoder" in freeze_plan.frozen_components,
            "renderer_trainable": False,
        }


@dataclass(slots=True)
class MicaModelBackendAdapter(TrainableAttributionBackend):
    model: MicaModel

    def forward(self, batch: TrainBatch) -> TrainOutputs:
        tensor_batch = batch.metadata.get("tensor_batch")
        if tensor_batch is None:
            tensor_batch = self._collate_train_batch(batch)
        output = self.model(tensor_batch)
        sample_unit_ids = [str(unit.get("unit_id", f"unit_{index}")) for index, unit in enumerate(batch.edit_units)]
        decoded = decode_active_slot_assignments(
            count_probs=output.count_probs[0],
            slot_exist_probs=output.slot_exist_probs[0],
            assignment_probs=output.assignment_probs[0],
            null_assignment_probs=output.null_assignment_probs[0] if output.null_assignment_probs is not None else None,
            unit_mask=tensor_batch["unit_mask"][0],
            unit_ids=sample_unit_ids,
        )
        risk_diagnostics = selective_risk_diagnostics(
            count_probs=output.count_probs[0],
            pb_count_probs=output.pb_count_probs[0],
            assignment_probs=output.assignment_probs[0],
            null_assignment_probs=output.null_assignment_probs[0] if output.null_assignment_probs is not None else None,
            batch=batch,
        )
        risk_diagnostics["selective_risk_score"] += float(self.model.selective_risk_bias.detach().cpu().item())
        release_diagnostics = release_decision_diagnostics(
            risk_score=float(risk_diagnostics["selective_risk_score"]),
            batch=batch,
        )
        slot_representations = {f"slot_{index + 1}": output.slot_logits[0, index] for index in range(output.slot_logits.size(1))}
        return TrainOutputs(
            count_logits=output.count_logits,
            count_probs=output.count_probs,
            pb_count_probs=output.pb_count_probs,
            slot_exist_probs=output.slot_exist_probs,
            assignments=decoded.unit_to_slot,
            assignment_scores=decoded.unit_assignment_scores,
            slot_representations=slot_representations,
            diagnostics={**decoded.diagnostics, **risk_diagnostics, **release_diagnostics},
            assignment_logits=output.assignment_logits,
            assignment_probs=output.assignment_probs,
            null_assignment_probs=output.null_assignment_probs,
            predicted_count=decoded.predicted_count,
            active_slot_indices=decoded.active_slot_indices,
            unit_mask=tensor_batch["unit_mask"],
        )

    def trainable_parameters(self) -> list[nn.Parameter]:
        return [parameter for parameter in self.model.parameters() if parameter.requires_grad]

    def set_train_mode(self) -> None:
        self.model.train(True)

    def set_eval_mode(self) -> None:
        self.model.train(False)

    def apply_freeze_plan(self, freeze_plan: ComponentFreezePlan) -> dict[str, Any]:
        for parameter in self.model.parameters():
            parameter.requires_grad = False
        component_map = {
            "base_encoder": [*self.model.encoder.parameters()],
            "encoder.lower": [*self.model.encoder.parameters()],
            "encoder.top": [*self.model.encoder.parameters()],
            "slot_decoder": [*self.model.slot_decoder.parameters()],
            "slot_decoder_adapter": [*self.model.slot_decoder.parameters()],
            "assignment_decoder": [*self.model.slot_decoder.parameters()],
            "count_head": [*self.model.count_head.parameters()],
            "existence_head": [*self.model.slot_decoder.parameters()],
            "count_temperature": [self.model.count_temperature_log],
            "existence_temperature": [self.model.existence_temperature_log],
            "selective_risk_calibration": [self.model.selective_risk_bias],
            "low_rank_assignment_adapter": [
                *self.model.slot_decoder.low_rank_unit_adapter.parameters(),
                *self.model.slot_decoder.low_rank_slot_adapter.parameters(),
                self.model.slot_decoder.low_rank_adapter_scale,
            ],
            "slot_existence_temperature": [self.model.existence_temperature_log],
        }
        for component in freeze_plan.trainable_components:
            for parameter in component_map.get(component, []):
                parameter.requires_grad = True
        return {
            "phase": freeze_plan.phase,
            "frozen_components": list(freeze_plan.frozen_components),
            "trainable_components": list(freeze_plan.trainable_components),
            "freeze_base_encoder": "base_encoder" in freeze_plan.frozen_components,
            "renderer_trainable": False,
        }

    def _collate_train_batch(self, batch: TrainBatch) -> dict[str, Any]:
        gold_unit_to_intent = batch.gold_unit_to_intent or {}
        label_to_index = {label: index for index, label in enumerate(sorted(set(gold_unit_to_intent.values())))}
        edit_units: list[EditUnit] = []
        for unit in batch.edit_units:
            unit_id = str(unit.get("unit_id", "missing_unit"))
            label = gold_unit_to_intent.get(unit_id)
            edit_units.append(
                EditUnit(
                    unit_id=unit_id,
                    hunk_id=str(unit.get("hunk_id", unit_id)),
                    file_path=str(unit.get("file_path", "")),
                    patch_text=str(unit.get("patch_text", "")),
                    added_lines=list(unit.get("added_lines", []) or []),
                    deleted_lines=list(unit.get("deleted_lines", []) or []),
                    context_lines=list(unit.get("context_lines", []) or []),
                    file_role=str(unit.get("file_role", "source")),
                    language=unit.get("language"),
                    identifiers=list(unit.get("changed_identifiers", []) or []),
                    gold_intent_id=label_to_index[label] if label is not None else None,
                    enclosing_symbol_type=unit.get("enclosing_symbol_type"),
                    enclosing_symbol_name=unit.get("enclosing_symbol_name"),
                    enclosing_symbol_signature=unit.get("enclosing_symbol_signature"),
                    enclosing_symbol_old_span=tuple(unit["enclosing_symbol_old_span"]) if unit.get("enclosing_symbol_old_span") else None,
                    enclosing_symbol_new_span=tuple(unit["enclosing_symbol_new_span"]) if unit.get("enclosing_symbol_new_span") else None,
                    enclosing_symbol_old_text=unit.get("enclosing_symbol_old_text"),
                    enclosing_symbol_new_text=unit.get("enclosing_symbol_new_text"),
                    enclosing_symbol_resolution_status=str(unit.get("enclosing_symbol_resolution_status", "hunk_only")),
                    context_clipped=bool(unit.get("context_clipped", False)),
                    provenance_status=str(unit.get("provenance_status", "unknown")),
                    source_atomic_commit_ids=[str(item) for item in unit.get("source_atomic_commit_ids", [])],
                )
            )
        sample = MicaSample(
            sample_id=batch.sample_ids[0],
            repo="synthetic",
            split="train",
            k=batch.gold_count or max(len(label_to_index), 1),
            is_multi_intent=(batch.gold_count or 1) > 1,
            diff_text="",
            edit_units=edit_units,
            gold_count=batch.gold_count or max(len(label_to_index), 1),
            gold_intent_ids=sorted(label_to_index),
            gold_unit_to_intent={unit_id: label_to_index[label] for unit_id, label in gold_unit_to_intent.items()},
            intent_types=None,
            intent_subjects=None,
            sample_weight=batch.sample_weight,
            source_kind=batch.source_kind,
        )
        return collate_mica_samples([sample])
