from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.data.stage1_synthetic_structure import (
    counter_to_sorted_dict,
    quantile,
    round_distribution,
    synthetic_k2_structure_features,
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Synthetic Structure Audit",
        "",
        f"- synthetic_total: {payload['synthetic_total']}",
        f"- synthetic_loaded: {payload['synthetic_loaded']}",
        f"- synthetic_skipped_missing_alignment: {payload['synthetic_skipped_missing_alignment']}",
        f"- synthetic_skipped_empty_units: {payload['synthetic_skipped_empty_units']}",
        f"- singleton_intent_fraction: {payload['singleton_intent_fraction']:.6f}",
        f"- both_intents_singleton_fraction: {payload['both_intents_singleton_fraction']:.6f}",
        f"- same_file_k2_fraction: {payload['same_file_k2_fraction']:.6f}",
        f"- cross_file_k2_fraction: {payload['cross_file_k2_fraction']:.6f}",
        f"- same_directory_k2_fraction: {payload['same_directory_k2_fraction']:.6f}",
        f"- different_file_role_k2_fraction: {payload['different_file_role_k2_fraction']:.6f}",
        f"- file_path_baseline_mean: {payload['file_path_baseline_mean']:.6f}",
        f"- file_path_baseline_p50: {payload['file_path_baseline_p50']:.6f}",
        f"- file_path_baseline_p90: {payload['file_path_baseline_p90']:.6f}",
        f"- random_gold_k_mean: {payload['random_gold_k_mean']:.6f}",
        f"- random_gold_k_p50: {payload['random_gold_k_p50']:.6f}",
        f"- random_gold_k_p90: {payload['random_gold_k_p90']:.6f}",
        f"- nondegenerate_candidate_count: {payload['nondegenerate_candidate_count']}",
        f"- path_dominated_candidate_count: {payload['path_dominated_candidate_count']}",
        f"- singleton_dominated_candidate_count: {payload['singleton_dominated_candidate_count']}",
        f"- source_path_is_local_runtime_only: {str(payload['source_path_is_local_runtime_only']).lower()}",
        f"- sanity_only: {str(payload['sanity_only']).lower()}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_stage1_synthetic_structure(
    *,
    synthetic_jsonl: str | Path,
    atomic_csv: str | Path,
    output_root: str | Path,
    reports_root: str | Path,
) -> dict[str, Any]:
    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=_resolve_path(atomic_csv),
        synthetic_jsonl_path=_resolve_path(synthetic_jsonl),
        split_seed=42,
    )
    synthetic_samples = [sample for sample in (bundle.train + bundle.dev + bundle.test) if sample.source_kind == "synthetic_k2"]
    details = [synthetic_k2_structure_features(sample) for sample in synthetic_samples]

    edit_unit_counter: Counter[int] = Counter()
    hunk_counter: Counter[int] = Counter()
    file_counter: Counter[int] = Counter()
    intent_unit_counter: Counter[int] = Counter()
    min_counter: Counter[int] = Counter()
    max_counter: Counter[int] = Counter()
    file_path_values: list[float] = []
    all_one_values: list[float] = []
    random_values: list[float] = []
    singleton_count = 0
    both_singleton_count = 0
    same_file_count = 0
    cross_file_count = 0
    same_directory_count = 0
    different_file_role_count = 0
    nondegenerate_count = 0
    path_dominated_count = 0
    singleton_dominated_count = 0

    for row in details:
        edit_unit_counter[int(row["edit_unit_count"])] += 1
        hunk_counter[int(row["hunk_count"])] += 1
        file_counter[int(row["file_count"])] += 1
        for intent_size in row["intent_unit_counts"]:
            intent_unit_counter[int(intent_size)] += 1
        min_counter[int(row["min_intent_units"])] += 1
        max_counter[int(row["max_intent_units"])] += 1
        file_path_values.append(float(row["file_path_baseline_pairwise_f1"]))
        all_one_values.append(float(row["all_one_baseline_pairwise_f1"]))
        random_values.append(float(row["random_gold_k_pairwise_f1"]))
        singleton_count += int(bool(row["singleton_dominated"]))
        both_singleton_count += int(bool(row["both_intents_singleton"]))
        same_file_count += int(bool(row["same_file"]))
        cross_file_count += int(bool(row["cross_file"]))
        same_directory_count += int(bool(row["same_directory"]))
        different_file_role_count += int(bool(row["different_file_role"]))
        nondegenerate_count += int(bool(row["nondegenerate_candidate"]))
        path_dominated_count += int(bool(row["path_dominated"]))
        singleton_dominated_count += int(bool(row["singleton_dominated"]))

    total = max(len(details), 1)
    summary = {
        "synthetic_total": int(bundle.source_stats["synthetic_candidates_total"]),
        "synthetic_loaded": int(bundle.source_stats["synthetic_loaded"]),
        "synthetic_skipped_missing_alignment": int(bundle.source_stats["synthetic_skipped_missing_alignment"]),
        "synthetic_skipped_empty_units": int(bundle.source_stats["synthetic_skipped_empty_units"]),
        "k2_edit_unit_count_distribution": counter_to_sorted_dict(edit_unit_counter),
        "k2_hunk_count_distribution": counter_to_sorted_dict(hunk_counter),
        "k2_file_count_distribution": counter_to_sorted_dict(file_counter),
        "intent_unit_count_distribution": counter_to_sorted_dict(intent_unit_counter),
        "singleton_intent_fraction": singleton_count / total,
        "both_intents_singleton_fraction": both_singleton_count / total,
        "min_intent_units_distribution": counter_to_sorted_dict(min_counter),
        "max_intent_units_distribution": counter_to_sorted_dict(max_counter),
        "same_file_k2_fraction": same_file_count / total,
        "cross_file_k2_fraction": cross_file_count / total,
        "same_directory_k2_fraction": same_directory_count / total,
        "different_file_role_k2_fraction": different_file_role_count / total,
        "file_path_baseline_distribution": round_distribution(file_path_values),
        "all_one_baseline_distribution": round_distribution(all_one_values),
        "random_gold_k_baseline_distribution": round_distribution(random_values),
        "file_path_baseline_mean": float(sum(file_path_values) / max(len(file_path_values), 1)),
        "file_path_baseline_p50": quantile(file_path_values, 0.5),
        "file_path_baseline_p90": quantile(file_path_values, 0.9),
        "random_gold_k_mean": float(sum(random_values) / max(len(random_values), 1)),
        "random_gold_k_p50": quantile(random_values, 0.5),
        "random_gold_k_p90": quantile(random_values, 0.9),
        "nondegenerate_candidate_count": nondegenerate_count,
        "path_dominated_candidate_count": path_dominated_count,
        "singleton_dominated_candidate_count": singleton_dominated_count,
        "source_path_is_local_runtime_only": True,
        "sanity_only": True,
    }

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_root_path / "synthetic_structure_details.jsonl", details)
    _write_jsonl(
        output_root_path / "nondegenerate_candidates.jsonl",
        [row for row in details if bool(row["nondegenerate_candidate"])],
    )
    _write_jsonl(
        output_root_path / "degenerate_candidates.jsonl",
        [row for row in details if bool(row["singleton_dominated"]) or bool(row["path_dominated"])],
    )

    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    _write_json(reports_root_path / "mica_stage1_synthetic_structure_audit.json", summary)
    _write_markdown(reports_root_path / "mica_stage1_synthetic_structure_audit.md", summary)
    return {
        "summary": summary,
        "details": details,
        "output_root": str(output_root_path),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Stage 1 synthetic k=2 structure for MICA-v3 sanity.")
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = audit_stage1_synthetic_structure(
        synthetic_jsonl=args.synthetic_jsonl,
        atomic_csv=args.atomic_csv,
        output_root=args.output_root,
        reports_root=args.reports_root,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
