from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

from code.mica.data.edit_unit import parse_unified_diff_to_edit_units
from code.mica.data.schema import MicaSample, Stage1SplitBundle


def _set_large_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit = limit // 10


def _stable_split(sample_id: str, split_ratios: tuple[float, float, float], split_seed: int) -> str:
    train_ratio, dev_ratio, _test_ratio = split_ratios
    fingerprint = hashlib.sha1(f"{split_seed}:{sample_id}".encode("utf-8")).hexdigest()
    value = int(fingerprint[:8], 16) / 0xFFFFFFFF
    if value < train_ratio:
        return "train"
    if value < train_ratio + dev_ratio:
        return "dev"
    return "test"


def _append_sample(bundle: Stage1SplitBundle, sample: MicaSample) -> None:
    if sample.split == "train":
        bundle.train.append(sample)
    elif sample.split == "dev":
        bundle.dev.append(sample)
    else:
        bundle.test.append(sample)


def _build_atomic_sample(row: dict[str, str], *, split: str) -> MicaSample | None:
    diff_text = str(row.get("git_diff") or "")
    edit_units = parse_unified_diff_to_edit_units(
        diff_text,
        repo=str(row.get("repo") or ""),
        sample_id=f"atomic::{row.get('sha', 'unknown')}",
    )
    if not edit_units:
        return None
    for unit in edit_units:
        unit.gold_intent_id = 0
    return MicaSample(
        sample_id=f"atomic::{row.get('sha', 'unknown')}",
        repo=str(row.get("repo") or ""),
        split=split,
        k=1,
        is_multi_intent=False,
        diff_text=diff_text,
        edit_units=edit_units,
        gold_count=1,
        gold_intent_ids=["intent_0"],
        gold_unit_to_intent={unit.unit_id: 0 for unit in edit_units},
        intent_types=[str(row.get("type") or "")] if row.get("type") else None,
        intent_subjects=[str(row.get("subject") or "")] if row.get("subject") else None,
        sample_weight=float(row.get("source_confidence") or 1.0),
        source_kind="atomic_k1",
    )


def _build_synthetic_sample(row: dict[str, object], *, split: str) -> tuple[MicaSample | None, str | None]:
    sample_id = str(row.get("sample_id") or "synthetic::unknown")
    edit_to_intent = row.get("edit_to_intent")
    if not isinstance(edit_to_intent, list) or not edit_to_intent:
        return None, "missing_edit_to_intent"
    gold_count = int(row.get("intent_count") or row.get("intent_k") or 0)
    if gold_count != 2:
        return None, "non_k2_synthetic"
    diff_text = str(row.get("synthetic_diff") or "")
    if not diff_text.strip():
        return None, "no_edit_units"
    try:
        edit_units = parse_unified_diff_to_edit_units(
            diff_text,
            repo=str(row.get("repo") or ""),
            sample_id=sample_id,
            gold_intent_ids=[int(item) for item in edit_to_intent],
        )
    except ValueError:
        return None, "edit_to_intent_length_mismatch"
    if not edit_units:
        return None, "no_edit_units"
    gold_unit_to_intent = {
        unit.unit_id: int(unit.gold_intent_id or 0)
        for unit in edit_units
    }
    return (
        MicaSample(
            sample_id=sample_id,
            repo=str(row.get("repo") or ""),
            split=split,
            k=2,
            is_multi_intent=True,
            diff_text=diff_text,
            edit_units=edit_units,
            gold_count=2,
            gold_intent_ids=[f"intent_{index}" for index in range(2)],
            gold_unit_to_intent=gold_unit_to_intent,
            intent_types=list(row.get("intent_types") or []) or None,
            intent_subjects=list(row.get("intent_subjects") or []) or None,
            sample_weight=float(row.get("final_sample_weight") or row.get("pair_quality_weight") or 1.0),
            source_kind="synthetic_k2",
        ),
        None,
    )


def load_stage1_strict_bootstrap(
    *,
    atomic_csv_path: str | Path,
    synthetic_jsonl_path: str | Path | None,
    max_atomic_samples: int | None = None,
    max_synthetic_samples: int | None = None,
    split_ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
    split_seed: int = 42,
) -> Stage1SplitBundle:
    _set_large_csv_field_limit()
    bundle = Stage1SplitBundle(
        source_stats={
            "atomic_candidates_total": 0,
            "atomic_loaded": 0,
            "atomic_skipped_empty_units": 0,
            "synthetic_candidates_total": 0,
            "synthetic_loaded": 0,
            "synthetic_skipped": 0,
            "synthetic_skipped_missing_alignment": 0,
            "synthetic_skipped_empty_units": 0,
            "synthetic_skipped_non_k2": 0,
            "synthetic_skipped_length_mismatch": 0,
            "synthetic_skipped_other": 0,
        }
    )

    atomic_path = Path(atomic_csv_path)
    with atomic_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if max_atomic_samples is not None and index >= max_atomic_samples:
                break
            bundle.source_stats["atomic_candidates_total"] = int(bundle.source_stats["atomic_candidates_total"]) + 1
            sample_id = f"atomic::{row.get('sha', 'unknown')}"
            split = _stable_split(sample_id, split_ratios, split_seed)
            sample = _build_atomic_sample(row, split=split)
            if sample is None:
                bundle.source_stats["atomic_skipped_empty_units"] = (
                    int(bundle.source_stats["atomic_skipped_empty_units"]) + 1
                )
                bundle.skipped.append({"sample_id": sample_id, "reason": "no_edit_units"})
                continue
            bundle.source_stats["atomic_loaded"] = int(bundle.source_stats["atomic_loaded"]) + 1
            _append_sample(bundle, sample)

    if synthetic_jsonl_path:
        synthetic_path = Path(synthetic_jsonl_path)
        if synthetic_path.exists():
            with synthetic_path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if max_synthetic_samples is not None and index >= max_synthetic_samples:
                        break
                    bundle.source_stats["synthetic_candidates_total"] = (
                        int(bundle.source_stats["synthetic_candidates_total"]) + 1
                    )
                    row = json.loads(line)
                    sample_id = str(row.get("sample_id") or f"synthetic::{index:06d}")
                    split = _stable_split(sample_id, split_ratios, split_seed)
                    sample, skip_reason = _build_synthetic_sample(row, split=split)
                    if sample is None:
                        bundle.source_stats["synthetic_skipped"] = int(bundle.source_stats["synthetic_skipped"]) + 1
                        reason_key = {
                            "missing_edit_to_intent": "synthetic_skipped_missing_alignment",
                            "edit_to_intent_length_mismatch": "synthetic_skipped_length_mismatch",
                            "no_edit_units": "synthetic_skipped_empty_units",
                            "non_k2_synthetic": "synthetic_skipped_non_k2",
                        }.get(str(skip_reason or ""), "synthetic_skipped_other")
                        bundle.source_stats[reason_key] = int(bundle.source_stats[reason_key]) + 1
                        bundle.skipped.append({"sample_id": sample_id, "reason": str(skip_reason or "unknown_skip")})
                        continue
                    bundle.source_stats["synthetic_loaded"] = int(bundle.source_stats["synthetic_loaded"]) + 1
                    _append_sample(bundle, sample)
    return bundle
