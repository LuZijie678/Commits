from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.data.schema import MicaSample


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def _balanced_subset(samples: list[MicaSample], limit: int) -> list[MicaSample]:
    if limit <= 0 or len(samples) <= limit:
        return list(samples)
    indexed = list(enumerate(samples))
    buckets: dict[int, list[tuple[int, MicaSample]]] = {
        1: [(idx, sample) for idx, sample in indexed if sample.gold_count == 1],
        2: [(idx, sample) for idx, sample in indexed if sample.gold_count == 2],
    }
    leftovers = [(idx, sample) for idx, sample in indexed if sample.gold_count not in {1, 2}]
    target_each = limit // 2
    selected: list[tuple[int, MicaSample]] = []
    used_indices: set[int] = set()
    for gold_count in (1, 2):
        for idx, sample in buckets[gold_count][:target_each]:
            selected.append((idx, sample))
            used_indices.add(idx)
    remaining = limit - len(selected)
    if remaining > 0:
        interleaved: list[tuple[int, MicaSample]] = []
        tails = [buckets[1][target_each:], buckets[2][target_each:], leftovers]
        max_tail = max((len(items) for items in tails), default=0)
        for offset in range(max_tail):
            for tail in tails:
                if offset < len(tail):
                    interleaved.append(tail[offset])
        for idx, sample in interleaved:
            if idx in used_indices:
                continue
            selected.append((idx, sample))
            used_indices.add(idx)
            if len(selected) >= limit:
                break
    selected.sort(key=lambda item: item[0])
    return [sample for _, sample in selected[:limit]]


def _quantile(sorted_values: list[int], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _sample_summary(sample: MicaSample) -> dict[str, Any]:
    return {
        "sample_id": sample.sample_id,
        "split": sample.split,
        "k": sample.gold_count,
        "source_kind": sample.source_kind,
        "repo": sample.repo,
        "edit_unit_count": len(sample.edit_units),
    }


def _build_audit(train_samples: list[MicaSample], dev_samples: list[MicaSample], source_stats: dict[str, object]) -> dict[str, Any]:
    selected_samples = train_samples + dev_samples
    unit_counts = sorted(len(sample.edit_units) for sample in selected_samples)
    file_roles = Counter(
        unit.file_role
        for sample in selected_samples
        for unit in sample.edit_units
    )
    audit = dict(source_stats)
    audit.update(
        {
            "train_count": len(train_samples),
            "dev_count": len(dev_samples),
            "k1_train": sum(1 for sample in train_samples if sample.gold_count == 1),
            "k2_train": sum(1 for sample in train_samples if sample.gold_count == 2),
            "k1_dev": sum(1 for sample in dev_samples if sample.gold_count == 1),
            "k2_dev": sum(1 for sample in dev_samples if sample.gold_count == 2),
            "avg_edit_units": float(mean(unit_counts)) if unit_counts else 0.0,
            "p50_edit_units": _quantile(unit_counts, 0.5),
            "p90_edit_units": _quantile(unit_counts, 0.9),
            "max_edit_units": max(unit_counts) if unit_counts else 0,
            "file_role_distribution": dict(sorted(file_roles.items())),
            "source_path_is_local_runtime_only": True,
            "sanity_only": True,
        }
    )
    return audit


def _write_audit_reports(audit: dict[str, Any], reports_root: Path) -> None:
    reports_root.mkdir(parents=True, exist_ok=True)
    json_path = reports_root / "mica_stage1_sanity_data_audit.json"
    md_path = reports_root / "mica_stage1_sanity_data_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# MICA Stage 1 Sanity Data Audit",
        "",
        f"- atomic_candidates_total: {audit['atomic_candidates_total']}",
        f"- atomic_loaded: {audit['atomic_loaded']}",
        f"- synthetic_candidates_total: {audit['synthetic_candidates_total']}",
        f"- synthetic_loaded: {audit['synthetic_loaded']}",
        f"- synthetic_skipped_missing_alignment: {audit['synthetic_skipped_missing_alignment']}",
        f"- synthetic_skipped_empty_units: {audit['synthetic_skipped_empty_units']}",
        f"- train_count: {audit['train_count']}",
        f"- dev_count: {audit['dev_count']}",
        f"- k1_train: {audit['k1_train']}",
        f"- k2_train: {audit['k2_train']}",
        f"- k1_dev: {audit['k1_dev']}",
        f"- k2_dev: {audit['k2_dev']}",
        f"- avg_edit_units: {audit['avg_edit_units']:.2f}",
        f"- p50_edit_units: {audit['p50_edit_units']:.2f}",
        f"- p90_edit_units: {audit['p90_edit_units']:.2f}",
        f"- max_edit_units: {audit['max_edit_units']}",
        f"- source_path_is_local_runtime_only: {str(audit['source_path_is_local_runtime_only']).lower()}",
        f"- sanity_only: {str(audit['sanity_only']).lower()}",
        "",
        "## File Role Distribution",
        "",
    ]
    for role, count in audit["file_role_distribution"].items():
        lines.append(f"- {role}: {count}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_stage1_sanity_manifest(
    *,
    atomic_csv: str | Path,
    synthetic_jsonl: str | Path,
    output_root: str | Path,
    reports_root: str | Path,
    max_train_samples: int,
    max_dev_samples: int,
    split_seed: int,
) -> dict[str, Any]:
    atomic_path = _resolve_path(atomic_csv)
    synthetic_path = _resolve_path(synthetic_jsonl)
    if atomic_path is None or not atomic_path.exists():
        raise FileNotFoundError(f"atomic csv not found: {atomic_csv}")
    if synthetic_path is None or not synthetic_path.exists():
        raise FileNotFoundError("synthetic jsonl not found for Stage 1 sanity manifest")

    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=atomic_path,
        synthetic_jsonl_path=synthetic_path,
        split_seed=split_seed,
    )
    train_samples = _balanced_subset(bundle.train, max_train_samples)
    dev_source = bundle.dev if bundle.dev else bundle.test
    dev_samples = _balanced_subset(dev_source, max_dev_samples)
    audit = _build_audit(train_samples, dev_samples, bundle.source_stats)

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root_path / "stage1_sanity_manifest.json"
    manifest_payload = {
        "created_at_utc": _timestamp(),
        "sanity_only": True,
        "synthetic_source": "local_runtime_only",
        "train_samples": [_sample_summary(sample) for sample in train_samples],
        "dev_samples": [_sample_summary(sample) for sample in dev_samples],
        "skipped_samples_preview": bundle.skipped[:50],
        "audit": audit,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_audit_reports(audit, Path(reports_root))
    return {
        "manifest_path": str(manifest_path),
        "audit": audit,
        "train_samples": train_samples,
        "dev_samples": dev_samples,
        "skipped_samples": bundle.skipped,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a local-only Stage 1 sanity manifest for MICA-v3.")
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--max-train-samples", type=int, default=200)
    parser.add_argument("--max-dev-samples", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = build_stage1_sanity_manifest(
        atomic_csv=args.atomic_csv,
        synthetic_jsonl=args.synthetic_jsonl,
        output_root=args.output_root,
        reports_root=args.reports_root,
        max_train_samples=args.max_train_samples,
        max_dev_samples=args.max_dev_samples,
        split_seed=args.seed,
    )
    print(
        json.dumps(
            {
                "manifest_path": result["manifest_path"],
                "audit": result["audit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
