from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import torch

from code.mica.models.mica_model import MicaModel
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.trainer_types import CheckpointPlan


CHECKPOINT_SCHEMA_VERSION = "mica-checkpoint-v2"
FULL_MODEL_CHECKPOINT_KIND = "full_model_state"
METADATA_ONLY_CHECKPOINT_KIND = "metadata_only"


def build_checkpoint_plan(output_dir: str | None, *, save_every_n_steps: int | None = None, keep_last_k: int = 1) -> CheckpointPlan:
    return CheckpointPlan(
        output_dir=output_dir,
        save_every_n_steps=save_every_n_steps,
        keep_last_k=keep_last_k,
        metadata={"runtime_outputs_enabled": False},
    )


def build_checkpoint_payload(
    *,
    stage: str,
    spec_snapshot: dict[str, Any],
    asset_registry_snapshot: dict[str, Any],
    seed: int,
    epoch: int,
    metrics: dict[str, Any],
    trainable_components: list[str],
    frozen_components: list[str],
    forbidden_assets_not_used: list[str],
    backend_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec_hash = hashlib.sha256(json.dumps(spec_snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_kind": METADATA_ONLY_CHECKPOINT_KIND,
        "stage": stage,
        "spec_snapshot": spec_snapshot,
        "spec_hash": spec_hash,
        "asset_registry_snapshot": asset_registry_snapshot,
        "git_commit": _git_commit(),
        "seed": int(seed),
        "epoch": int(epoch),
        "metrics": metrics,
        "trainable_components": list(trainable_components),
        "frozen_components": list(frozen_components),
        "forbidden_assets_not_used": list(forbidden_assets_not_used),
        "backend_state": _jsonify(backend_state or {}),
    }


def build_model_checkpoint_payload(
    *,
    stage: str,
    backend: MicaModelBackendAdapter,
    optimizer_state: dict[str, Any] | None,
    scheduler_state: dict[str, Any] | None,
    model_config: dict[str, Any],
    training_state: dict[str, Any],
    threshold_version: str | None,
    data_manifest_hashes: dict[str, str],
    git_commit: str | None = None,
    registry_hash: str | None = None,
    encoder_config: dict[str, Any] | None = None,
    relation_config: dict[str, Any] | None = None,
    tokenizer_config: dict[str, Any] | None = None,
    random_seed: int | None = None,
    kmax: int | None = None,
    git_provenance: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_config_hash = hashlib.sha256(
        json.dumps(dict(model_config), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_kind": FULL_MODEL_CHECKPOINT_KIND,
        "stage": stage,
        "model_class": "MicaModel",
        "backend_class": "MicaModelBackendAdapter",
        "model_config": dict(model_config),
        "model_config_hash": model_config_hash,
        "model_state": backend.model.state_dict(),
        "optimizer_state": optimizer_state or {},
        "scheduler_state": scheduler_state or {},
        "training_state": dict(training_state),
        "threshold_version": threshold_version,
        "data_manifest_hashes": dict(data_manifest_hashes),
        "registry_hash": registry_hash,
        "encoder_config": dict(encoder_config or {}),
        "relation_config": dict(relation_config or {}),
        "tokenizer_config": dict(tokenizer_config or {}),
        "random_seed": random_seed,
        "kmax": kmax if kmax is not None else model_config.get("kmax"),
        "git_commit": git_commit or _git_commit(),
        "git_provenance": dict(git_provenance or {}),
        "environment": dict(environment or {}),
    }


def save_checkpoint(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in {".pt", ".pth"} or payload.get("checkpoint_kind") == FULL_MODEL_CHECKPOINT_KIND:
        torch.save(payload, target)
        return
    target.write_text(json.dumps(_jsonify(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.suffix.lower() in {".pt", ".pth"}:
        payload = torch.load(target, map_location="cpu", weights_only=False)
        if not isinstance(payload, dict):
            raise ValueError("Checkpoint payload must be a dict.")
        return payload
    return json.loads(target.read_text(encoding="utf-8"))


def validate_checkpoint_payload(payload: dict[str, Any], *, require_full_model_state: bool = False) -> dict[str, Any]:
    checkpoint_kind = str(payload.get("checkpoint_kind") or METADATA_ONLY_CHECKPOINT_KIND)
    errors: list[str] = []
    if "stage" not in payload:
        errors.append("missing_stage")
    if checkpoint_kind == FULL_MODEL_CHECKPOINT_KIND:
        required = [
            "schema_version",
            "checkpoint_kind",
            "model_config",
            "model_state",
            "training_state",
            "data_manifest_hashes",
        ]
        errors.extend(f"missing_{field}" for field in required if field not in payload)
    else:
        required = [
            "stage",
            "spec_snapshot",
            "spec_hash",
            "asset_registry_snapshot",
            "seed",
            "epoch",
            "metrics",
            "trainable_components",
            "frozen_components",
            "forbidden_assets_not_used",
        ]
        errors.extend(field for field in required if field not in payload)
    if require_full_model_state and checkpoint_kind != FULL_MODEL_CHECKPOINT_KIND:
        errors.append("missing_model_state")
    return {"valid": not errors, "errors": errors, "checkpoint_kind": checkpoint_kind}


def instantiate_backend_from_checkpoint(payload: dict[str, Any]) -> MicaModelBackendAdapter:
    validation = validate_checkpoint_payload(payload, require_full_model_state=True)
    if not validation["valid"]:
        raise ValueError("Invalid full-model checkpoint payload: " + ",".join(validation["errors"]))
    model = MicaModel(**dict(payload["model_config"]))
    model.load_state_dict(payload["model_state"])
    return MicaModelBackendAdapter(model)


def _jsonify(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    return value


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
