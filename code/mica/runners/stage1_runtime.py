from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from code.mica.data.asset_registry import (
    DEFAULT_LOCAL_MATERIALIZATION_REGISTRY,
    register_local_materialization,
)
from code.mica.data.schema import EditUnit, MicaSample
from code.mica.io_utils import REPO_ROOT, read_json, safe_relpath_for_report, write_json
from code.mica.runners.export_stage1_predictions import build_prediction_row_from_backend
from code.mica.training.trainer_types import TrainBatch


STAGE1_TRAIN_ASSET_NAMES = ("step1_high_conf_single_train", "strict_synthetic_train")
STAGE1_DEV_ASSET_NAMES = ("step1_high_conf_single_dev", "strict_synthetic_dev")
STAGE1_VALIDATION_ASSET_NAME = "stage1_official_validation_dev"
STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME = "stage1_official_final_test"
STAGE1_CHECKPOINT_ASSET_NAME = "stage1_checkpoint_input"
THRESHOLD_BOUND_SUFFIXES = ("_min", "_max")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with _repo_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_required_asset_status(
    asset_registry_validation: dict[str, Any] | None,
    asset_names: tuple[str, ...] | list[str],
) -> dict[str, dict[str, Any]]:
    if not asset_registry_validation:
        return {}
    asset_status = dict(asset_registry_validation.get("asset_status", {}))
    return {
        asset_name: dict(asset_status.get(asset_name, {}))
        for asset_name in asset_names
    }


def required_assets_ready(required_assets_status: dict[str, dict[str, Any]]) -> bool:
    return bool(required_assets_status) and all(bool(item.get("formal_ready")) for item in required_assets_status.values())


def input_asset_hashes(required_assets_status: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    return {
        asset_name: sha256_file(path) if path else None
        for asset_name, status in required_assets_status.items()
        for path in [status.get("path")]
    }


def load_formal_asset_rows(path: str | Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Formal asset manifest must be a JSON object: {path}")
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError(f"Formal asset manifest rows must be a list: {path}")
    return [row for row in rows if isinstance(row, dict)]


def resolve_formal_asset_entry(
    *,
    asset_registry: dict[str, Any],
    asset_registry_validation: dict[str, Any] | None,
    asset_name: str,
    require_formal_ready: bool = True,
) -> dict[str, Any]:
    assets = dict(asset_registry.get("assets", {}))
    if asset_name not in assets or not isinstance(assets[asset_name], dict):
        raise ValueError(f"Missing asset registry entry: {asset_name}")
    entry = dict(assets[asset_name])
    status = dict(asset_registry_validation.get("asset_status", {}).get(asset_name, {})) if asset_registry_validation else {}
    if require_formal_ready and not bool(status.get("formal_ready")):
        raise ValueError(f"Asset `{asset_name}` is not formal-ready in the asset registry.")
    path = status.get("path") or entry.get("path")
    if not path:
        raise ValueError(f"Asset `{asset_name}` does not define a path.")
    return {"entry": entry, "status": status, "path": _repo_path(path)}


def load_stage1_samples_from_rows(rows: list[dict[str, Any]]) -> list[MicaSample]:
    return [manifest_row_to_mica_sample(row) for row in rows]


def manifest_row_to_mica_sample(row: dict[str, Any]) -> MicaSample:
    sample_id = str(row.get("sample_id") or "__missing_sample_id__")
    gold_count = int(row.get("gold_count") or 0)
    if gold_count < 1:
        raise ValueError(f"Stage 1 formal sample requires positive gold_count: {sample_id}")
    gold_unit_to_intent = _gold_unit_to_intent(row)
    if not gold_unit_to_intent:
        raise ValueError(f"Stage 1 formal sample requires gold_unit_to_intent: {sample_id}")
    label_to_index = {label: index for index, label in enumerate(sorted(set(gold_unit_to_intent.values())))}
    if len(label_to_index) != gold_count:
        raise ValueError(
            f"Stage 1 formal sample gold_count mismatch for {sample_id}: "
            f"gold_count={gold_count}, distinct_labels={len(label_to_index)}"
        )
    edit_units = [
        _manifest_unit_to_edit_unit(
            unit,
            gold_intent_label=gold_unit_to_intent.get(str(unit.get("unit_id", ""))),
            label_to_index=label_to_index,
        )
        for unit in list(row.get("edit_units", []))
        if isinstance(unit, dict)
    ]
    if not edit_units:
        raise ValueError(f"Stage 1 formal sample requires edit_units: {sample_id}")
    return MicaSample(
        sample_id=sample_id,
        repo=str(row.get("repo") or row.get("repository") or ""),
        split=str(row.get("split") or "unspecified"),
        k=gold_count,
        is_multi_intent=gold_count > 1,
        diff_text=_diff_text_from_units(row.get("edit_units", [])),
        edit_units=edit_units,
        gold_count=gold_count,
        gold_intent_ids=[label for label, _index in sorted(label_to_index.items(), key=lambda item: item[1])],
        gold_unit_to_intent={unit_id: label_to_index[label] for unit_id, label in gold_unit_to_intent.items()},
        intent_types=[str(item) for item in list(row.get("intent_types", []) or [])] or None,
        intent_subjects=[str(item) for item in list(row.get("intent_subjects", []) or [])] or None,
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        source_kind=str(row.get("source_kind") or row.get("source_type") or "unknown"),
    )


def manifest_row_to_train_batch(
    row: dict[str, Any],
    *,
    selective_risk_threshold: float | None = None,
) -> TrainBatch:
    metadata = {
        "commit_id": str(row.get("commit_id") or row.get("sample_id") or ""),
        "background_units": list(row.get("background_units", []) or []),
        "background_unit_records": list(row.get("background_unit_records", []) or []),
    }
    if selective_risk_threshold is not None:
        metadata["selective_risk_threshold"] = float(selective_risk_threshold)
    return TrainBatch(
        sample_ids=[str(row.get("sample_id") or "__missing_sample_id__")],
        source_kind=str(row.get("source_kind") or row.get("source_type") or "unknown"),
        edit_units=[dict(unit) for unit in list(row.get("edit_units", []) or []) if isinstance(unit, dict)],
        gold_count=int(row.get("gold_count")) if row.get("gold_count") is not None else None,
        gold_unit_to_intent=_gold_unit_to_intent(row) or None,
        gold_hunk_to_intent={
            str(key): str(value)
            for key, value in dict(row.get("gold_hunk_to_intent", {})).items()
        }
        if isinstance(row.get("gold_hunk_to_intent"), dict)
        else None,
        weak_label=row.get("weak_label"),
        sample_weight=float(row.get("sample_weight", 1.0) or 1.0),
        metadata=metadata,
    )


def generate_stage1_prediction_rows(
    *,
    backend: Any,
    manifest_rows: list[dict[str, Any]],
    source: str,
    selective_risk_threshold: float | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        batch = manifest_row_to_train_batch(row, selective_risk_threshold=selective_risk_threshold)
        outputs = backend.forward(batch)
        rows.append(
            build_prediction_row_from_backend(
                batch=batch,
                outputs=outputs,
                source=source,
            )
        )
    return rows


def build_threshold_metric_snapshot(
    metrics: dict[str, Any],
    threshold_spec: dict[str, Any],
) -> dict[str, float | None]:
    snapshot: dict[str, float | None] = {}
    for bound_name in sorted(key for key in threshold_spec if key.endswith(THRESHOLD_BOUND_SUFFIXES)):
        metric_name = bound_name[:-4]
        value = metrics.get(metric_name)
        snapshot[metric_name] = float(value) if value is not None else None
    return snapshot


def evaluate_metric_thresholds(
    metrics: dict[str, Any],
    threshold_spec: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for bound_name in sorted(key for key in threshold_spec if key.endswith(THRESHOLD_BOUND_SUFFIXES)):
        metric_name = bound_name[:-4]
        observed = metrics.get(metric_name)
        comparator = "min" if bound_name.endswith("_min") else "max"
        threshold_value = float(threshold_spec[bound_name])
        if observed is None:
            passed = False
        elif comparator == "min":
            passed = float(observed) >= threshold_value
        else:
            passed = float(observed) <= threshold_value
        results[metric_name] = {
            "bound_name": bound_name,
            "comparator": comparator,
            "threshold": threshold_value,
            "observed": float(observed) if observed is not None else None,
            "passed": passed,
        }
    return results


def threshold_status_is_frozen(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return bool(normalized) and "candidate" not in normalized and "pending" not in normalized


def validate_registry_bound_manifest(
    *,
    manifest_path: str | Path,
    asset_registry: dict[str, Any],
    asset_registry_validation: dict[str, Any] | None,
    asset_name: str = STAGE1_VALIDATION_ASSET_NAME,
) -> None:
    resolved = resolve_formal_asset_entry(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_name=asset_name,
        require_formal_ready=True,
    )
    _validate_bound_file(
        candidate_path=_repo_path(manifest_path),
        frozen_path=resolved["path"],
        expected_checksum=resolved["entry"].get("checksum"),
        error_message=f"Stage 1 execution requires the frozen `{asset_name}` manifest from the registry.",
    )


def validate_registry_bound_checkpoint(
    *,
    checkpoint_path: str | Path,
    asset_registry: dict[str, Any],
    asset_registry_validation: dict[str, Any] | None,
    asset_name: str = STAGE1_CHECKPOINT_ASSET_NAME,
) -> None:
    resolved = resolve_formal_asset_entry(
        asset_registry=asset_registry,
        asset_registry_validation=asset_registry_validation,
        asset_name=asset_name,
        require_formal_ready=True,
    )
    _validate_bound_file(
        candidate_path=_repo_path(checkpoint_path),
        frozen_path=resolved["path"],
        expected_checksum=resolved["entry"].get("sha256") or resolved["entry"].get("checksum"),
        error_message=f"Stage 1 execution requires the frozen `{asset_name}` checkpoint from the registry.",
    )


def validate_clean_checkpoint_provenance(
    checkpoint_payload: dict[str, Any],
    *,
    require_git_commit: bool = True,
    fallback_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = dict(checkpoint_payload.get("git_provenance", {})) if isinstance(checkpoint_payload, dict) else {}
    metadata = dict(fallback_metadata or {})
    errors: list[str] = []
    if require_git_commit and not provenance.get("git_commit"):
        errors.append("checkpoint_git_commit_missing")
    if provenance.get("dirty") is True:
        errors.append("dirty_checkpoint_provenance")
    if not provenance:
        errors.append("checkpoint_git_provenance_missing")
        if metadata.get("provenance_status") == "dirty_worktree_candidate":
            errors.append("dirty_checkpoint_provenance")
        if metadata.get("produced_from_clean_commit") is False:
            errors.append("dirty_checkpoint_provenance")
    return {
        "valid": len(errors) == 0,
        "errors": sorted(set(errors)),
        "git_provenance": provenance,
        "fallback_metadata": metadata,
    }


def update_stage1_checkpoint_registry(
    *,
    registry_path: str | Path,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    checkpoint_artifact_id: str,
    training_manifest_hashes: dict[str, str],
    git_commit: str | None,
    git_provenance: dict[str, Any] | None,
    model_config_hash: str | None,
    environment: dict[str, Any] | None,
    created_by: str,
    local_materialization_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    registry = read_json(registry_path)
    if not isinstance(registry, dict):
        raise ValueError("Asset registry must be a JSON object.")
    assets = dict(registry.get("assets", {}))
    entry = dict(assets.get(STAGE1_CHECKPOINT_ASSET_NAME, {}))
    entry.update(
        {
            "path": None,
            "artifact_id": checkpoint_artifact_id,
            "status": "candidate_validated",
            "schema_version": "mica-checkpoint-v2",
            "sha256": checkpoint_hash,
            "storage_uri": None,
            "source_pool": "stage1_formal_training_runtime",
            "split": "n/a",
            "record_count": 1,
            "checksum": checkpoint_hash,
            "created_by": created_by,
            "leakage_group_key": "n/a",
            "allowed_stages": ["stage1_validation_execute"],
            "forbidden_stages": [],
            "required_for": ["stage1_validation_execute"],
            "eval_only": False,
            "metadata": {
                "training_manifest_hashes": dict(training_manifest_hashes),
                "git_commit": git_commit,
                "git_provenance": dict(git_provenance or {}),
                "model_config_hash": model_config_hash,
                "environment": dict(environment or {}),
            },
        }
    )
    assets[STAGE1_CHECKPOINT_ASSET_NAME] = entry
    registry["assets"] = assets
    write_json(registry_path, registry)
    register_local_materialization(
        registry_path=local_materialization_registry_path
        or (Path(registry_path).with_name(Path(DEFAULT_LOCAL_MATERIALIZATION_REGISTRY).name)),
        artifact_id=checkpoint_artifact_id,
        path=safe_relpath_for_report(checkpoint_path),
        sha256=checkpoint_hash,
        created_by=created_by,
        git_commit=git_commit,
    )
    return registry


def build_stage1_checkpoint_artifact_id(
    *,
    git_commit: str | None,
    config_hash: str,
    train_manifest_hashes: dict[str, str],
    seed: int,
) -> str:
    manifest_fingerprint = hashlib.sha256(
        "|".join(f"{name}:{value}" for name, value in sorted(train_manifest_hashes.items())).encode("utf-8")
    ).hexdigest()[:12]
    commit_fragment = str(git_commit or "unknown")[:12]
    return f"stage1_candidate_{commit_fragment}_{config_hash[:12]}_{manifest_fingerprint}_seed{int(seed)}"


def derive_official_blockers(
    *,
    stage0_readiness: dict[str, Any] | None,
    threshold_spec: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    threshold_status = str(threshold_spec.get("threshold_status") or "")
    if not threshold_status_is_frozen(threshold_status):
        blockers.append("thresholds_pending_approval")
    if stage0_readiness is None:
        blockers.append("stage0_readiness_report_missing")
        return blockers
    if not bool(stage0_readiness.get("Kmax_protocol_frozen")):
        blockers.append("kmax_coverage_not_frozen")
    kmax_report = dict(stage0_readiness.get("kmax_coverage_report", {}))
    train_dev_basis = dict(kmax_report.get("train_dev_selection_basis", {}))
    if int(train_dev_basis.get("exact_real_multi_intent_row_count", 0) or 0) <= 0:
        blockers.append("exact_real_multi_intent_count_asset_missing")
    if not bool(stage0_readiness.get("formal_ready")):
        blockers.append("stage0_formal_ready_false")
    return sorted(set(blockers))


def _manifest_unit_to_edit_unit(
    unit: dict[str, Any],
    *,
    gold_intent_label: str | None,
    label_to_index: dict[str, int],
) -> EditUnit:
    metadata = dict(unit.get("metadata", {})) if isinstance(unit.get("metadata"), dict) else {}
    old_span = metadata.get("enclosing_symbol_old_span")
    new_span = metadata.get("enclosing_symbol_new_span")
    return EditUnit(
        unit_id=str(unit.get("unit_id", "missing_unit")),
        hunk_id=str(unit.get("hunk_id", unit.get("unit_id", "missing_hunk"))),
        file_path=str(unit.get("file_path", "")),
        patch_text=str(unit.get("patch_text", "")),
        added_lines=[str(item) for item in list(unit.get("added_lines", []) or [])],
        deleted_lines=[str(item) for item in list(unit.get("deleted_lines", []) or [])],
        context_lines=[str(item) for item in list(unit.get("context_lines", []) or [])],
        file_role=str(unit.get("file_role", "source") or "source"),
        language=str(unit.get("language")) if unit.get("language") is not None else None,
        identifiers=[str(item) for item in list(unit.get("changed_identifiers", []) or [])],
        gold_intent_id=label_to_index[gold_intent_label] if gold_intent_label is not None else None,
        enclosing_symbol_type=metadata.get("enclosing_symbol_type"),
        enclosing_symbol_name=metadata.get("enclosing_symbol_name"),
        enclosing_symbol_signature=metadata.get("enclosing_symbol_signature"),
        enclosing_symbol_old_span=tuple(old_span) if isinstance(old_span, (list, tuple)) and len(old_span) == 2 else None,
        enclosing_symbol_new_span=tuple(new_span) if isinstance(new_span, (list, tuple)) and len(new_span) == 2 else None,
        enclosing_symbol_old_text=metadata.get("enclosing_symbol_old_text"),
        enclosing_symbol_new_text=metadata.get("enclosing_symbol_new_text"),
        enclosing_symbol_resolution_status=str(metadata.get("enclosing_symbol_resolution_status", "hunk_only")),
        context_clipped=bool(metadata.get("context_clipped", False)),
        provenance_status=str(metadata.get("provenance_status", "unknown")),
        source_atomic_commit_ids=[str(item) for item in list(unit.get("source_atomic_commit_ids", []) or [])],
    )


def _gold_unit_to_intent(row: dict[str, Any]) -> dict[str, str]:
    if isinstance(row.get("gold_unit_to_intent"), dict):
        return {
            str(unit_id): str(intent_id)
            for unit_id, intent_id in dict(row.get("gold_unit_to_intent", {})).items()
        }
    mapping: dict[str, str] = {}
    for unit in list(row.get("edit_units", []) or []):
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("unit_id")
        intent_id = unit.get("gold_intent_id")
        if unit_id is None or intent_id is None:
            continue
        mapping[str(unit_id)] = str(intent_id)
    return mapping


def _diff_text_from_units(units: list[dict[str, Any]]) -> str:
    parts = [str(unit.get("patch_text", "")) for unit in units if isinstance(unit, dict)]
    return "\n".join(part for part in parts if part).strip()


def _validate_bound_file(
    *,
    candidate_path: Path,
    frozen_path: Path,
    expected_checksum: Any,
    error_message: str,
) -> None:
    if not candidate_path.exists():
        raise ValueError(f"Bound file does not exist: {candidate_path}")
    placeholder_values = {None, "", "placeholder", "to_be_filled_by_validator", "null"}
    if expected_checksum not in placeholder_values:
        actual_checksum = sha256_file(candidate_path)
        if actual_checksum != str(expected_checksum):
            raise ValueError(error_message)
        return
    if candidate_path.resolve() != frozen_path.resolve():
        raise ValueError(error_message)


def _repo_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return (REPO_ROOT / target).resolve()
