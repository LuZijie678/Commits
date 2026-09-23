from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.data.schema import MicaSample
from code.mica.data.stage1_synthetic_structure import sample_summary_row, synthetic_k2_structure_features


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = ["# MICA Stage 1 Curriculum Manifest Summary", ""]
    for level in ("easy", "medium", "hard"):
        summary = payload[level]
        lines.extend(
            [
                f"## {level}",
                "",
                f"- train_count: {summary['train_count']}",
                f"- dev_count: {summary['dev_count']}",
                f"- k1_train: {summary['k1_train']}",
                f"- k2_train: {summary['k2_train']}",
                f"- k1_dev: {summary['k1_dev']}",
                f"- k2_dev: {summary['k2_dev']}",
                f"- avg_edit_units: {summary['avg_edit_units']:.6f}",
                f"- singleton_intent_fraction: {summary['singleton_intent_fraction']:.6f}",
                f"- file_path_baseline_mean: {summary['file_path_baseline_mean']:.6f}",
                f"- random_gold_k_baseline_mean: {summary['random_gold_k_baseline_mean']:.6f}",
                f"- fallback_applied: {str(summary['fallback_applied']).lower()}",
                f"- fallback_reason: {summary['fallback_reason']}",
                f"- sanity_only: {str(summary['sanity_only']).lower()}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _choose_atomic(samples: list[MicaSample], requested_count: int) -> list[MicaSample]:
    return list(samples[: min(len(samples), requested_count)])


def _select_with_relaxation(
    candidates: list[tuple[MicaSample, dict[str, Any]]],
    requested_count: int,
    predicates: list[tuple[str, Callable[[dict[str, Any]], bool]]],
) -> tuple[list[tuple[MicaSample, dict[str, Any]]], bool, list[str]]:
    selected: list[tuple[MicaSample, dict[str, Any]]] = []
    fallback_applied = False
    reasons: list[str] = []
    for index, (reason, predicate) in enumerate(predicates):
        filtered = [(sample, features) for sample, features in candidates if predicate(features)]
        if len(filtered) >= requested_count:
            return filtered[:requested_count], fallback_applied or index > 0, reasons
        fallback_applied = True
        reasons.append(reason)
        selected = filtered
    return selected[:requested_count], fallback_applied, reasons or ["insufficient_candidates"]


def _summary_for_subset(
    *,
    train_samples: list[MicaSample],
    dev_samples: list[MicaSample],
    train_features: list[dict[str, Any]],
    dev_features: list[dict[str, Any]],
    fallback_applied: bool,
    fallback_reason: list[str],
) -> dict[str, Any]:
    selected_samples = train_samples + dev_samples
    selected_features = train_features + dev_features
    avg_edit_units = (
        sum(len(sample.edit_units) for sample in selected_samples) / max(len(selected_samples), 1)
        if selected_samples
        else 0.0
    )
    singleton_fraction = (
        sum(int(bool(features.get("singleton_dominated"))) for features in selected_features) / max(len(selected_features), 1)
        if selected_features
        else 0.0
    )
    file_path_mean = (
        sum(float(features["file_path_baseline_pairwise_f1"]) for features in selected_features) / max(len(selected_features), 1)
        if selected_features
        else 0.0
    )
    random_mean = (
        sum(float(features["random_gold_k_pairwise_f1"]) for features in selected_features) / max(len(selected_features), 1)
        if selected_features
        else 0.0
    )
    return {
        "train_count": len(train_samples),
        "dev_count": len(dev_samples),
        "k1_train": sum(1 for sample in train_samples if sample.gold_count == 1),
        "k2_train": sum(1 for sample in train_samples if sample.gold_count == 2),
        "k1_dev": sum(1 for sample in dev_samples if sample.gold_count == 1),
        "k2_dev": sum(1 for sample in dev_samples if sample.gold_count == 2),
        "avg_edit_units": float(avg_edit_units),
        "singleton_intent_fraction": float(singleton_fraction),
        "file_path_baseline_mean": float(file_path_mean),
        "random_gold_k_baseline_mean": float(random_mean),
        "fallback_applied": bool(fallback_applied),
        "fallback_reason": list(fallback_reason),
        "sanity_only": True,
    }


def _build_level_payload(
    *,
    level: str,
    atomic_train: list[MicaSample],
    atomic_dev: list[MicaSample],
    synthetic_train: list[tuple[MicaSample, dict[str, Any]]],
    synthetic_dev: list[tuple[MicaSample, dict[str, Any]]],
    k1_train_count: int,
    k2_train_count: int,
    k1_dev_count: int,
    k2_dev_count: int,
    output_root: Path,
) -> dict[str, Any]:
    atomic_train_selected = _choose_atomic(atomic_train, k1_train_count)
    atomic_dev_selected = _choose_atomic(atomic_dev, k1_dev_count)

    if level == "easy":
        predicates = [
            (
                "easy_primary",
                lambda features: bool(features["gold_intents_nonempty"]) and int(features["edit_unit_count"]) >= 2,
            ),
        ]
    elif level == "medium":
        predicates = [
            (
                "medium_primary",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and int(features["min_intent_units"]) >= 2
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
                    and float(features["random_gold_k_pairwise_f1"]) <= 0.80
                ),
            ),
            (
                "relax_random_threshold",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and int(features["min_intent_units"]) >= 2
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
                ),
            ),
            (
                "relax_singleton_constraint",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.95
                ),
            ),
            (
                "fallback_to_easy_like",
                lambda features: bool(features["gold_intents_nonempty"]) and int(features["edit_unit_count"]) >= 2,
            ),
        ]
    else:
        predicates = [
            (
                "hard_primary",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and int(features["min_intent_units"]) >= 2
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.75
                ),
            ),
            (
                "relax_file_path_ceiling",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and int(features["min_intent_units"]) >= 2
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.85
                ),
            ),
            (
                "relax_singleton_constraint",
                lambda features: (
                    bool(features["gold_intents_nonempty"])
                    and int(features["edit_unit_count"]) >= 4
                    and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
                ),
            ),
            (
                "fallback_to_medium_like",
                lambda features: bool(features["gold_intents_nonempty"]) and int(features["edit_unit_count"]) >= 2,
            ),
        ]

    train_selected, train_fallback, train_reasons = _select_with_relaxation(synthetic_train, k2_train_count, predicates)
    dev_selected, dev_fallback, dev_reasons = _select_with_relaxation(synthetic_dev, k2_dev_count, predicates)

    train_samples = atomic_train_selected + [sample for sample, _ in train_selected]
    dev_samples = atomic_dev_selected + [sample for sample, _ in dev_selected]
    train_features = [features for _, features in train_selected]
    dev_features = [features for _, features in dev_selected]
    summary = _summary_for_subset(
        train_samples=train_samples,
        dev_samples=dev_samples,
        train_features=train_features,
        dev_features=dev_features,
        fallback_applied=train_fallback or dev_fallback,
        fallback_reason=train_reasons + dev_reasons,
    )

    manifest_payload = {
        "created_at_utc": _timestamp(),
        "curriculum_level": level,
        "sanity_only": True,
        "fallback_applied": summary["fallback_applied"],
        "fallback_reason": summary["fallback_reason"],
        "summary": summary,
        "train_samples": [
            sample_summary_row(sample, extra=synthetic_k2_structure_features(sample) if sample.gold_count == 2 else None)
            for sample in train_samples
        ],
        "dev_samples": [
            sample_summary_row(sample, extra=synthetic_k2_structure_features(sample) if sample.gold_count == 2 else None)
            for sample in dev_samples
        ],
    }
    manifest_path = output_root / f"manifest_{level}.json"
    _write_json(manifest_path, manifest_payload)
    return {
        "manifest_path": str(manifest_path),
        "summary": summary,
        "train_samples": train_samples,
        "dev_samples": dev_samples,
    }


def build_stage1_curriculum_manifests(
    *,
    atomic_csv: str | Path,
    synthetic_jsonl: str | Path,
    output_root: str | Path,
    reports_root: str | Path,
    split_seed: int = 42,
    k1_train_count: int = 100,
    k2_train_count: int = 100,
    k1_dev_count: int = 25,
    k2_dev_count: int = 25,
) -> dict[str, Any]:
    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=_resolve_path(atomic_csv),
        synthetic_jsonl_path=_resolve_path(synthetic_jsonl),
        split_seed=split_seed,
    )
    atomic_train = [sample for sample in bundle.train if sample.source_kind == "atomic_k1"]
    atomic_dev_pool = [sample for sample in (bundle.dev + bundle.test) if sample.source_kind == "atomic_k1"]

    synthetic_train = [
        (sample, synthetic_k2_structure_features(sample))
        for sample in bundle.train
        if sample.source_kind == "synthetic_k2"
    ]
    synthetic_dev_pool = [
        (sample, synthetic_k2_structure_features(sample))
        for sample in (bundle.dev + bundle.test)
        if sample.source_kind == "synthetic_k2"
    ]

    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    payload = {
        level: _build_level_payload(
            level=level,
            atomic_train=atomic_train,
            atomic_dev=atomic_dev_pool,
            synthetic_train=synthetic_train,
            synthetic_dev=synthetic_dev_pool,
            k1_train_count=k1_train_count,
            k2_train_count=k2_train_count,
            k1_dev_count=k1_dev_count,
            k2_dev_count=k2_dev_count,
            output_root=output_root_path,
        )
        for level in ("easy", "medium", "hard")
    }

    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)
    summary_payload = {level: payload[level]["summary"] for level in payload}
    _write_json(reports_root_path / "mica_stage1_curriculum_manifest_summary.json", summary_payload)
    _write_markdown(reports_root_path / "mica_stage1_curriculum_manifest_summary.md", summary_payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage 1 curriculum manifests for MICA-v3 sanity.")
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--k1-train-count", type=int, default=100)
    parser.add_argument("--k2-train-count", type=int, default=100)
    parser.add_argument("--k1-dev-count", type=int, default=25)
    parser.add_argument("--k2-dev-count", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = build_stage1_curriculum_manifests(
        atomic_csv=args.atomic_csv,
        synthetic_jsonl=args.synthetic_jsonl,
        output_root=args.output_root,
        reports_root=args.reports_root,
        split_seed=args.split_seed,
        k1_train_count=args.k1_train_count,
        k2_train_count=args.k2_train_count,
        k1_dev_count=args.k1_dev_count,
        k2_dev_count=args.k2_dev_count,
    )
    print(
        json.dumps(
            {
                level: {
                    "manifest_path": result[level]["manifest_path"],
                    "summary": result[level]["summary"],
                }
                for level in ("easy", "medium", "hard")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build easy/medium/hard Stage 1 curriculum manifests for MICA-v3.")
    parser.add_argument("--atomic-csv", required=True)
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--k1-train-count", type=int, default=100)
    parser.add_argument("--k2-train-count", type=int, default=100)
    parser.add_argument("--k1-dev-count", type=int, default=25)
    parser.add_argument("--k2-dev-count", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = build_stage1_curriculum_manifests(
        atomic_csv=args.atomic_csv,
        synthetic_jsonl=args.synthetic_jsonl,
        output_root=args.output_root,
        reports_root=args.reports_root,
        split_seed=args.split_seed,
        k1_train_count=args.k1_train_count,
        k2_train_count=args.k2_train_count,
        k1_dev_count=args.k1_dev_count,
        k2_dev_count=args.k2_dev_count,
    )
    print(json.dumps({level: payload[level]["summary"] for level in payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
