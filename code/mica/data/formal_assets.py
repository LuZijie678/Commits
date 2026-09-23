from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from code.mica.data.edit_unit import parse_unified_diff_to_edit_units
from code.mica.io_utils import write_json


FORMAL_ASSET_MANIFEST_SCHEMA_VERSION = "mica-formal-asset-manifest-v1"
REGISTRY_SCHEMA_VERSION = "mica-data-asset-registry-v2"


def build_formal_asset_manifests(
    *,
    step1_atomic_csv: str | Path,
    strict_synthetic_jsonl: str | Path,
    m_verified_csv: str | Path,
    hard_b_csv: str | Path,
    output_root: str | Path,
    stage1_counts: dict[str, int] | None = None,
    stage2_split_ratios: tuple[float, float, float] = (0.7, 0.15, 0.15),
    split_seed: int = 42,
) -> dict[str, Any]:
    stage1_counts = stage1_counts or {"train": 1000, "dev": 250, "test": 250}
    output_root_path = Path(output_root)
    stage1_root = output_root_path / "stage1"
    stage2_root = output_root_path / "stage2"
    stage3_root = output_root_path / "stage3"
    registry_path = output_root_path / "data_asset_registry.json"
    for path in (stage1_root, stage2_root, stage3_root):
        path.mkdir(parents=True, exist_ok=True)

    atomic_rows = _load_step1_atomic_rows(step1_atomic_csv)
    synthetic_rows = _load_strict_synthetic_rows(strict_synthetic_jsonl)
    m_verified_rows = _load_m_verified_rows(m_verified_csv)
    hard_b_rows = _load_hard_b_rows(hard_b_csv)

    stage1_atomic = _split_exact_rows(atomic_rows, stage1_counts, split_seed=split_seed, grouping_key="leakage_group")
    stage1_synth = _split_exact_rows(synthetic_rows, stage1_counts, split_seed=split_seed + 1, grouping_key="leakage_group")
    m_splits = _split_ratio_rows(m_verified_rows, stage2_split_ratios, split_seed=split_seed + 2, grouping_key="repo")
    hb_splits = _split_ratio_rows(hard_b_rows, stage2_split_ratios, split_seed=split_seed + 3, grouping_key="repo")

    manifest_records: dict[str, dict[str, Any]] = {}
    for split, rows in stage1_atomic.items():
        manifest_records[f"step1_high_conf_single_{split}"] = _write_manifest(
            stage1_root / f"step1_high_conf_single_{split}.json",
            asset_name=f"step1_high_conf_single_{split}",
            split=split,
            source_pool=str(step1_atomic_csv),
            rows=rows,
        )
    for split, rows in stage1_synth.items():
        manifest_records[f"strict_synthetic_{split}"] = _write_manifest(
            stage1_root / f"strict_synthetic_{split}.json",
            asset_name=f"strict_synthetic_{split}",
            split=split,
            source_pool=str(strict_synthetic_jsonl),
            rows=rows,
        )

    strict_replay_train_rows = [dict(row, source_kind="strict_replay", source_type="strict_replay") for row in stage1_synth["train"]]
    manifest_records["strict_replay"] = _write_manifest(
        stage2_root / "strict_replay.json",
        asset_name="strict_replay",
        split="train",
        source_pool=str(strict_synthetic_jsonl),
        rows=strict_replay_train_rows,
    )

    for split, rows in hb_splits.items():
        manifest_records[f"hard_b_{split}"] = _write_manifest(
            stage2_root / f"hard_b_{split}.json",
            asset_name=f"hard_b_{split}",
            split=split,
            source_pool=str(hard_b_csv),
            rows=rows,
        )
    for split, rows in m_splits.items():
        manifest_records[f"m_weak_{split}"] = _write_manifest(
            stage2_root / f"m_weak_{split}.json",
            asset_name=f"m_weak_{split}",
            split=split,
            source_pool=str(m_verified_csv),
            rows=rows,
        )

    combined_dev_rows = list(stage1_atomic["dev"]) + list(stage1_synth["dev"])
    manifest_records["stage1_official_validation_dev"] = _write_manifest(
        stage1_root / "stage1_official_validation_dev.json",
        asset_name="stage1_official_validation_dev",
        split="dev",
        source_pool="combined_stage1_dev_assets",
        rows=combined_dev_rows,
    )
    combined_test_rows = list(stage1_atomic["test"]) + list(stage1_synth["test"])
    manifest_records["stage1_official_final_test"] = _write_manifest(
        stage1_root / "stage1_official_final_test.json",
        asset_name="stage1_official_final_test",
        split="test",
        source_pool="combined_stage1_test_assets",
        rows=combined_test_rows,
    )

    registry = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_status": "formal_assets_populated",
        "generated_at_utc": _utc_now(),
        "assets": {
            "strict_synthetic_train": _registry_record(
                manifest_records["strict_synthetic_train"],
                leakage_group_key="source_atomic_commit_ids",
                allowed_stages=["stage1_train"],
                required_for=["stage1_train"],
            ),
            "strict_synthetic_dev": _registry_record(
                manifest_records["strict_synthetic_dev"],
                leakage_group_key="source_atomic_commit_ids",
                allowed_stages=["stage1_validation"],
                required_for=["stage1_validation"],
            ),
            "strict_synthetic_test": _registry_record(
                manifest_records["strict_synthetic_test"],
                leakage_group_key="source_atomic_commit_ids",
                allowed_stages=["stage1_eval_holdout"],
            ),
            "step1_high_conf_single_train": _registry_record(
                manifest_records["step1_high_conf_single_train"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage1_train"],
                required_for=["stage1_train"],
            ),
            "step1_high_conf_single_dev": _registry_record(
                manifest_records["step1_high_conf_single_dev"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage1_validation"],
                required_for=["stage1_validation"],
            ),
            "step1_high_conf_single_test": _registry_record(
                manifest_records["step1_high_conf_single_test"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage1_eval_holdout"],
            ),
            "stage1_official_validation_dev": _registry_record(
                manifest_records["stage1_official_validation_dev"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage1_candidate_validation", "stage1_threshold_selection"],
                required_for=["stage1_candidate_validation", "stage1_threshold_selection"],
            ),
            "stage1_official_final_test": _registry_record(
                manifest_records["stage1_official_final_test"],
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["stage1_validation_execute", "final_eval"],
                required_for=["stage1_validation_execute"],
                forbidden_stages=["stage1_threshold_selection", "stage1_candidate_validation", "tuning"],
            ),
            "stage1_checkpoint_input": _missing_registry_record(
                status="pending_generation",
                schema_version="mica-checkpoint-v2",
                source_pool=None,
                split="n/a",
                created_by="build_formal_asset_manifests",
                leakage_group_key="n/a",
                allowed_stages=["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                required_for=["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
            ),
            "strict_replay": _registry_record(
                manifest_records["strict_replay"],
                leakage_group_key="source_atomic_commit_ids",
                allowed_stages=["stage2_replay", "stage3_replay"],
                required_for=["stage2_train"],
            ),
            "hard_b_train": _registry_record(
                manifest_records["hard_b_train"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage2_train"],
                required_for=["stage2_train"],
            ),
            "hard_b_dev": _registry_record(
                manifest_records["hard_b_dev"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage2_dev", "stage2_tuning"],
                required_for=["stage2_dev"],
            ),
            "hard_b_test": _registry_record(
                manifest_records["hard_b_test"],
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                forbidden_stages=["stage2_train", "stage2_calibration", "tuning"],
            ),
            "m_weak_train": _registry_record(
                manifest_records["m_weak_train"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage2_train"],
                required_for=["stage2_train"],
            ),
            "m_weak_dev": _registry_record(
                manifest_records["m_weak_dev"],
                leakage_group_key="leakage_group",
                allowed_stages=["stage2_dev", "stage2_tuning"],
                required_for=["stage2_dev"],
            ),
            "m_weak_test": _registry_record(
                manifest_records["m_weak_test"],
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                forbidden_stages=["stage2_train", "stage2_calibration", "tuning"],
            ),
            "m_final_test": _registry_record(
                manifest_records["m_weak_test"],
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                forbidden_stages=["stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"],
                alias_of="m_weak_test",
            ),
            "m_align_calib": _missing_registry_record(
                status="pending_annotation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="calib",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                allowed_stages=["stage3_calibration"],
                required_for=["stage3_calibration"],
            ),
            "real_alignment_dev": _missing_registry_record(
                status="pending_annotation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="dev",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                allowed_stages=["stage3_calibration", "alignment_eval_dev"],
                required_for=["stage3_calibration"],
            ),
            "real_alignment_test": _missing_registry_record(
                status="pending_annotation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="test",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                required_for=["final_eval"],
                forbidden_stages=["stage3_train", "calibration", "tuning"],
            ),
            "real_alignment_final_test": _missing_registry_record(
                status="pending_annotation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="test",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                required_for=["final_eval"],
                forbidden_stages=["stage3_train", "calibration", "tuning"],
                alias_of="real_alignment_test",
            ),
            "real_domain_split_test": _missing_registry_record(
                status="pending_generation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="test",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                required_for=["final_eval"],
                forbidden_stages=["stage2_train", "stage3_train", "calibration", "tuning"],
            ),
            "real_domain_selective_test": _missing_registry_record(
                status="pending_generation",
                schema_version=FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
                source_pool=None,
                split="test",
                created_by="build_formal_asset_manifests",
                leakage_group_key="leakage_group",
                eval_only=True,
                allowed_stages=["final_eval"],
                required_for=["final_eval"],
                forbidden_stages=["stage2_train", "stage3_train", "calibration", "tuning"],
            ),
            "renderer_dataset": _missing_registry_record(
                status="pending_generation",
                schema_version="mica-renderer-dataset-v1",
                source_pool=None,
                split="train",
                created_by="build_formal_asset_manifests",
                leakage_group_key="commit_id",
                allowed_stages=["stage4_renderer"],
                required_for=["stage4_renderer_train"],
            ),
            "predicted_plans": _missing_registry_record(
                status="pending_generation",
                schema_version="mica-structured-intent-plan-v1",
                source_pool=None,
                split="eval",
                created_by="build_formal_asset_manifests",
                leakage_group_key="commit_id",
                allowed_stages=["stage4_eval"],
                required_for=["stage4_eval_predicted"],
            ),
            "oracle_plans": _missing_registry_record(
                status="pending_generation",
                schema_version="mica-structured-intent-plan-v1",
                source_pool=None,
                split="eval",
                created_by="build_formal_asset_manifests",
                leakage_group_key="commit_id",
                allowed_stages=["stage4_eval"],
                required_for=["stage4_eval_oracle"],
            ),
            "message_utility_manifest": _missing_registry_record(
                status="pending_generation",
                schema_version="mica-message-utility-manifest-v1",
                source_pool=None,
                split="eval",
                created_by="build_formal_asset_manifests",
                leakage_group_key="commit_id",
                allowed_stages=["message_utility_eval"],
                required_for=["message_utility_eval"],
            ),
            "human_pilot_annotations": _missing_registry_record(
                status="pending_annotation",
                schema_version="mica-human-pilot-annotations-v1",
                source_pool=None,
                split="eval",
                created_by="build_formal_asset_manifests",
                leakage_group_key="sample_id",
                allowed_stages=["message_utility_human_pilot"],
                required_for=["message_utility_human_pilot"],
            ),
        },
    }
    write_json(registry_path, registry)
    return {
        "registry_path": str(registry_path),
        "output_root": str(output_root_path),
        "generated_assets": sorted(manifest_records),
        "missing_assets": sorted(
            asset_name
            for asset_name, payload in registry["assets"].items()
            if payload.get("path") is None
        ),
    }


def _load_step1_atomic_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_csv_rows(path):
        sample_id = f"atomic::{row.get('sha', 'missing_sha')}"
        edit_units = parse_unified_diff_to_edit_units(
            str(row.get("git_diff") or ""),
            repo=str(row.get("repo") or ""),
            sample_id=sample_id,
        )
        if not edit_units:
            continue
        rows.append(
            {
                "sample_id": sample_id,
                "commit_id": str(row.get("sha") or sample_id),
                "repo": str(row.get("repo") or ""),
                "repository": str(row.get("repo") or ""),
                "source_sha": str(row.get("sha") or ""),
                "source_type": "step1_high_conf_single",
                "source_kind": "atomic_k1",
                "cardinality_label_type": "exact_k1_gold",
                "gold_provenance_status": "strict_unique_atomic",
                "leakage_group": f"sha:{row.get('sha')}",
                "construction_group": f"atomic:{row.get('sha')}",
                "source_atomic_commit_ids": [str(row.get("sha") or "")],
                "gold_count": 1,
                "sample_weight": float(row.get("source_confidence") or 1.0),
                "intent_subjects": [str(row.get("subject") or "")] if row.get("subject") else [],
                "intent_types": [str(row.get("type") or "")] if row.get("type") else [],
                "edit_units": _unit_records(edit_units),
                "gold_unit_to_intent": {unit.unit_id: "intent_0" for unit in edit_units},
                "gold_hunk_to_intent": {unit.hunk_id: "intent_0" for unit in edit_units},
            }
        )
    return rows


def _load_strict_synthetic_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_jsonl_rows(path):
        source_ids = [
            f"{item.get('repo', row.get('repo', ''))}@{item.get('sha', '')}"
            for item in list(row.get("sources", []) or [])
            if isinstance(item, dict) and item.get("sha")
        ]
        gold_alignment = [int(item) for item in list(row.get("edit_to_intent", []) or [])]
        edit_units = parse_unified_diff_to_edit_units(
            str(row.get("synthetic_diff") or ""),
            repo=str(row.get("repo") or ""),
            sample_id=str(row.get("sample_id") or "missing_sample_id"),
            gold_intent_ids=gold_alignment,
        )
        if not edit_units:
            continue
        rows.append(
            {
                "sample_id": str(row.get("sample_id") or "missing_sample_id"),
                "commit_id": str(row.get("sample_id") or "missing_sample_id"),
                "repo": str(row.get("repo") or ""),
                "repository": str(row.get("repo") or ""),
                "source_sha": source_ids[0] if source_ids else None,
                "source_type": "strict_synthetic",
                "source_kind": "strict_replay",
                "cardinality_label_type": "exact_k2_gold",
                "gold_provenance_status": "synthetic_construction_gold",
                "leakage_group": "|".join(sorted(source_ids)) if source_ids else str(row.get("sample_id") or ""),
                "construction_group": str(row.get("construction_type") or row.get("construction_route") or row.get("sample_id") or ""),
                "source_atomic_commit_ids": sorted(source_ids),
                "gold_count": 2,
                "sample_weight": float(row.get("final_sample_weight") or row.get("pair_quality_weight") or 1.0),
                "intent_subjects": [str(item) for item in list(row.get("intent_subjects", []) or [])],
                "intent_types": [str(item) for item in list(row.get("intent_types", []) or [])],
                "edit_units": _unit_records(edit_units),
                "gold_unit_to_intent": {
                    unit.unit_id: f"intent_{int(unit.gold_intent_id or 0)}"
                    for unit in edit_units
                },
                "gold_hunk_to_intent": {
                    unit.hunk_id: f"intent_{int(unit.gold_intent_id or 0)}"
                    for unit in edit_units
                },
            }
        )
    return rows


def _load_m_verified_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_csv_rows(path):
        diff_text = str(row.get("git_diff") or "")
        edit_units = parse_unified_diff_to_edit_units(
            diff_text,
            repo=str(row.get("repo") or ""),
            sample_id=f"mweak::{row.get('sha', 'missing_sha')}",
        )
        if not edit_units:
            continue
        rows.append(
            {
                "sample_id": f"mweak::{row.get('sha', 'missing_sha')}",
                "commit_id": str(row.get("sha") or ""),
                "repo": str(row.get("repo") or ""),
                "repository": str(row.get("repo") or ""),
                "source_sha": str(row.get("sha") or ""),
                "source_type": "m_weak",
                "source_kind": "m_weak",
                "cardinality_label_type": "censored_k_ge_2",
                "gold_provenance_status": "weak_multi_intent_boundary_only",
                "leakage_group": f"repo_sha:{row.get('repo')}::{row.get('sha')}",
                "construction_group": f"repo_sha:{row.get('repo')}::{row.get('sha')}",
                "source_atomic_commit_ids": [f"{row.get('repo')}@{row.get('sha')}"],
                "weak_label": "censored_k_ge_2",
                "gold_count": None,
                "sample_weight": 1.0,
                "intent_subjects": [],
                "intent_types": [],
                "edit_units": _unit_records(edit_units),
                "llm_intent_count_estimate": _optional_int(row.get("llm_intent_count_estimate")),
            }
        )
    return rows


def _load_hard_b_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_csv_rows(path):
        diff_text = str(row.get("git_diff") or "")
        sample_id = f"hardb::{row.get('sha', 'missing_sha')}"
        edit_units = parse_unified_diff_to_edit_units(
            diff_text,
            repo=str(row.get("repo") or ""),
            sample_id=sample_id,
        )
        if not edit_units:
            continue
        rows.append(
            {
                "sample_id": sample_id,
                "commit_id": str(row.get("sha") or ""),
                "repo": str(row.get("repo") or ""),
                "repository": str(row.get("repo") or ""),
                "source_sha": str(row.get("sha") or ""),
                "source_type": "hard_b",
                "source_kind": "hard_b",
                "cardinality_label_type": "exact_k1_gold",
                "gold_provenance_status": "real_single_intent_boundary_only",
                "leakage_group": f"repo_sha:{row.get('repo')}::{row.get('sha')}",
                "construction_group": f"repo_sha:{row.get('repo')}::{row.get('sha')}",
                "source_atomic_commit_ids": [f"{row.get('repo')}@{row.get('sha')}"],
                "gold_count": 1,
                "sample_weight": 1.0,
                "intent_subjects": [],
                "intent_types": [],
                "edit_units": _unit_records(edit_units),
            }
        )
    return rows


def _read_csv_rows(path: str | Path) -> Iterable[dict[str, str]]:
    _set_large_csv_field_limit()
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield dict(row)


def _read_jsonl_rows(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def _split_exact_rows(
    rows: list[dict[str, Any]],
    counts: dict[str, int],
    *,
    split_seed: int,
    grouping_key: str,
) -> dict[str, list[dict[str, Any]]]:
    groups = _group_rows(rows, grouping_key)
    remaining = list(groups)
    result: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    for split in ("train", "dev", "test"):
        target = int(counts.get(split, 0) or 0)
        selected, remaining = _select_groups(remaining, target, split_seed=split_seed, split=split)
        result[split] = [row for _group_key, group_rows in selected for row in group_rows]
        for row in result[split]:
            row["split"] = split
    return result


def _split_ratio_rows(
    rows: list[dict[str, Any]],
    ratios: tuple[float, float, float],
    *,
    split_seed: int,
    grouping_key: str,
) -> dict[str, list[dict[str, Any]]]:
    total = len(rows)
    train_target = int(round(total * ratios[0]))
    dev_target = int(round(total * ratios[1]))
    test_target = max(total - train_target - dev_target, 0)
    return _split_exact_rows(
        rows,
        {"train": train_target, "dev": dev_target, "test": test_target},
        split_seed=split_seed,
        grouping_key=grouping_key,
    )


def _group_rows(rows: list[dict[str, Any]], grouping_key: str) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if grouping_key == "repo":
            key = str(row.get("repo") or row.get("repository") or row.get("sample_id"))
        else:
            key = str(row.get(grouping_key) or row.get("sample_id"))
        grouped[key].append(dict(row))
    return sorted(grouped.items(), key=lambda item: _stable_rank(item[0]))


def _select_groups(
    remaining: list[tuple[str, list[dict[str, Any]]]],
    target_count: int,
    *,
    split_seed: int,
    split: str,
) -> tuple[list[tuple[str, list[dict[str, Any]]]], list[tuple[str, list[dict[str, Any]]]]]:
    chosen: list[tuple[str, list[dict[str, Any]]]] = []
    pool = list(remaining)
    current = 0
    while pool and current < target_count:
        need = target_count - current
        fitting = [
            item
            for item in pool
            if len(item[1]) <= need
        ]
        if fitting:
            fitting.sort(key=lambda item: (-len(item[1]), _stable_rank(f"{split_seed}:{split}:{item[0]}")))
            candidate = fitting[0]
        else:
            pool.sort(key=lambda item: (len(item[1]), _stable_rank(f"{split_seed}:{split}:{item[0]}")))
            candidate = pool[0]
        pool.remove(candidate)
        chosen.append(candidate)
        current += len(candidate[1])
    return chosen, pool


def _write_manifest(
    path: Path,
    *,
    asset_name: str,
    split: str,
    source_pool: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
        "asset_name": asset_name,
        "split": split,
        "source_pool": source_pool,
        "created_at_utc": _utc_now(),
        "formal_ready": True,
        "summary": _build_manifest_summary(rows),
        "rows": rows,
    }
    write_json(path, payload)
    return {
        "path": str(path),
        "status": "frozen",
        "schema_version": FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
        "source_pool": source_pool,
        "split": split,
        "record_count": int(payload["summary"]["record_count"]),
        "checksum": _sha256_file(path),
        "created_by": "build_formal_asset_manifests",
        "formal_ready": bool(payload["formal_ready"]),
    }


def _build_manifest_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_ids = [str(row.get("sample_id")) for row in rows]
    duplicates = len(sample_ids) - len(set(sample_ids))
    source_type_distribution = Counter(str(row.get("source_type") or "unknown") for row in rows)
    label_distribution = Counter(str(row.get("cardinality_label_type") or "unknown") for row in rows)
    leakage_groups = [str(row.get("leakage_group")) for row in rows if row.get("leakage_group")]
    leakage_duplicates = len(leakage_groups) - len(set(leakage_groups))
    return {
        "record_count": len(rows),
        "repo_count": len({str(row.get("repo") or row.get("repository") or "") for row in rows}),
        "duplicate_count": duplicates,
        "leakage_group_overlap_count": leakage_duplicates,
        "source_type_distribution": dict(sorted(source_type_distribution.items())),
        "label_distribution": dict(sorted(label_distribution.items())),
    }


def _registry_record(
    manifest_record: dict[str, Any],
    *,
    leakage_group_key: str,
    eval_only: bool = False,
    allowed_stages: list[str] | None = None,
    forbidden_stages: list[str] | None = None,
    required_for: list[str] | None = None,
    alias_of: str | None = None,
) -> dict[str, Any]:
    payload = {
        "path": manifest_record["path"],
        "status": manifest_record["status"],
        "schema_version": manifest_record["schema_version"],
        "source_pool": manifest_record["source_pool"],
        "split": manifest_record["split"],
        "record_count": manifest_record["record_count"],
        "checksum": manifest_record["checksum"],
        "created_by": manifest_record["created_by"],
        "leakage_group_key": leakage_group_key,
        "allowed_stages": list(allowed_stages or []),
        "forbidden_stages": list(forbidden_stages or (["stage2_train", "stage2_calibration", "tuning"] if eval_only else [])),
        "required_for": list(required_for or []),
        "eval_only": bool(eval_only),
    }
    if alias_of:
        payload["alias_of"] = alias_of
    return payload


def _missing_registry_record(
    *,
    status: str,
    schema_version: str,
    source_pool: str | None,
    split: str,
    created_by: str,
    leakage_group_key: str,
    eval_only: bool = False,
    allowed_stages: list[str] | None = None,
    forbidden_stages: list[str] | None = None,
    required_for: list[str] | None = None,
    alias_of: str | None = None,
) -> dict[str, Any]:
    payload = {
        "path": None,
        "status": status,
        "schema_version": schema_version,
        "source_pool": source_pool,
        "split": split,
        "record_count": None,
        "checksum": None,
        "created_by": created_by,
        "leakage_group_key": leakage_group_key,
        "allowed_stages": list(allowed_stages or []),
        "forbidden_stages": list(forbidden_stages or (["stage2_train", "stage2_calibration", "tuning"] if eval_only else [])),
        "required_for": list(required_for or []),
        "eval_only": bool(eval_only),
    }
    if alias_of:
        payload["alias_of"] = alias_of
    return payload


def _unit_records(edit_units: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "unit_id": str(unit.unit_id),
            "hunk_id": str(unit.hunk_id),
            "file_path": str(unit.file_path),
            "file_role": str(unit.file_role),
            "language": unit.language,
            "patch_text": str(unit.patch_text),
            "added_lines": list(unit.added_lines),
            "deleted_lines": list(unit.deleted_lines),
            "changed_identifiers": list(unit.identifiers),
            "metadata": {
                "enclosing_symbol_name": unit.enclosing_symbol_name,
                "enclosing_symbol_type": unit.enclosing_symbol_type,
                "enclosing_symbol_signature": unit.enclosing_symbol_signature,
                "enclosing_symbol_resolution_status": unit.enclosing_symbol_resolution_status,
                "source_atomic_commit_ids": list(unit.source_atomic_commit_ids),
            },
        }
        for unit in edit_units
    ]


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_rank(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _set_large_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit = limit // 10
