from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap
from code.mica.data.schema import MicaSample
from code.mica.data.stage1_synthetic_structure import quantile, synthetic_k2_structure_features


SCHEDULE_CANDIDATE = "naive_balanced_mixed_large_scale"
ALLOWED_DATA_SOURCES = {
    "step1_atomic_k1": "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
    "step2_synthetic_k2": "local_runtime_synthetic_samples_step3_ready_jsonl",
}
FORBIDDEN_DATA_SOURCES = {
    "hard_b": False,
    "M_weak": False,
    "M_alignment": False,
    "RealDomainSplit": False,
    "RealDomainSelective": False,
    "stage2_loss": False,
    "M_censored_loss": False,
    "generation_outputs": False,
    "retrieval": False,
    "verifier": False,
    "llm_judge": False,
    "real_api": False,
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stable_order(samples: list[MicaSample], *, seed: int, namespace: str) -> list[MicaSample]:
    return sorted(
        samples,
        key=lambda sample: hashlib.sha1(f"{seed}:{namespace}:{sample.sample_id}".encode("utf-8")).hexdigest(),
    )


def _medium_primary(features: dict[str, Any]) -> bool:
    return (
        bool(features["gold_intents_nonempty"])
        and int(features["edit_unit_count"]) >= 4
        and int(features["min_intent_units"]) >= 2
        and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
        and float(features["random_gold_k_pairwise_f1"]) <= 0.80
    )


def _medium_relaxed(features: dict[str, Any]) -> bool:
    return (
        bool(features["gold_intents_nonempty"])
        and int(features["edit_unit_count"]) >= 4
        and int(features["min_intent_units"]) >= 2
        and float(features["file_path_baseline_pairwise_f1"]) <= 0.90
    )


def _medium_fallback(features: dict[str, Any]) -> bool:
    return bool(features["gold_intents_nonempty"]) and int(features["edit_unit_count"]) >= 4


def _select_k2_candidates(
    synthetic_samples: list[MicaSample],
    requested_count: int,
) -> tuple[list[tuple[MicaSample, dict[str, Any]]], bool, list[str], int]:
    feature_rows = [(sample, synthetic_k2_structure_features(sample)) for sample in synthetic_samples]
    primary = [(sample, features) for sample, features in feature_rows if _medium_primary(features)]
    if len(primary) >= requested_count:
        return primary[:requested_count], False, [], len(primary)

    relaxed = [(sample, features) for sample, features in feature_rows if _medium_relaxed(features)]
    if len(relaxed) >= requested_count:
        return relaxed[:requested_count], True, ["relax_random_gold_k_threshold"], len(primary)

    fallback = [(sample, features) for sample, features in feature_rows if _medium_fallback(features)]
    if len(fallback) >= requested_count:
        return fallback[:requested_count], True, ["relax_file_path_or_random_threshold"], len(primary)

    return fallback, True, ["insufficient_medium_k2_candidates"], len(primary)


def _split_selected(samples: list[Any], counts: dict[str, int]) -> dict[str, list[Any]]:
    train_end = counts["train"]
    dev_end = train_end + counts["dev"]
    return {
        "train": samples[:train_end],
        "dev": samples[train_end:dev_end],
        "test": samples[dev_end:dev_end + counts["test"]],
    }


def _sample_sha(sample: MicaSample) -> str | None:
    if sample.source_kind != "atomic_k1":
        return None
    prefix = "atomic::"
    return sample.sample_id[len(prefix):] if sample.sample_id.startswith(prefix) else sample.sample_id


def _normalized_subjects(sample: MicaSample) -> list[str]:
    subjects = sample.intent_subjects or []
    return [" ".join(str(subject).lower().split()) for subject in subjects if str(subject).strip()]


def _row_for_sample(sample: MicaSample, *, split: str, features: dict[str, Any] | None = None) -> dict[str, Any]:
    edit_unit_count = len(sample.edit_units)
    file_count = len({unit.file_path for unit in sample.edit_units})
    if features is None:
        intent_unit_counts = [edit_unit_count]
        file_path_baseline = 1.0
        random_gold_k = 1.0
        singleton_dominated = False
        path_dominated = False
        medium_candidate = False
    else:
        intent_unit_counts = list(features["intent_unit_counts"])
        file_path_baseline = float(features["file_path_baseline_pairwise_f1"])
        random_gold_k = float(features["random_gold_k_pairwise_f1"])
        singleton_dominated = bool(features["singleton_dominated"])
        path_dominated = bool(features["path_dominated"])
        medium_candidate = _medium_primary(features)

    return {
        "sample_id": sample.sample_id,
        "source_kind": sample.source_kind,
        "repo": sample.repo,
        "sha": _sample_sha(sample),
        "synthetic_id": sample.sample_id if sample.source_kind == "synthetic_k2" else None,
        "split": split,
        "gold_count": int(sample.gold_count),
        "is_multi_intent": bool(sample.is_multi_intent),
        "edit_unit_count": int(edit_unit_count),
        "hunk_count": int(edit_unit_count),
        "file_count": int(file_count),
        "intent_unit_counts": intent_unit_counts,
        "file_path_baseline_pairwise_f1": file_path_baseline,
        "random_gold_k_pairwise_f1": random_gold_k,
        "singleton_dominated": singleton_dominated,
        "path_dominated": path_dominated,
        "medium_candidate": medium_candidate,
        "sample_weight": float(sample.sample_weight),
        "normalized_subjects": _normalized_subjects(sample),
    }


def _counts_for_rows(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for split, rows in rows_by_split.items():
        counts[split] = {
            "atomic_k1": sum(1 for row in rows if row["source_kind"] == "atomic_k1"),
            "synthetic_k2": sum(1 for row in rows if row["source_kind"] == "synthetic_k2"),
            "total": len(rows),
        }
    return counts


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _split_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    k2_rows = [row for row in rows if row["source_kind"] == "synthetic_k2"]
    edit_counts = [float(row["edit_unit_count"]) for row in k2_rows]
    return {
        "singleton_intent_fraction": _mean([float(row["singleton_dominated"]) for row in k2_rows]),
        "file_path_baseline_mean": _mean([float(row["file_path_baseline_pairwise_f1"]) for row in k2_rows]),
        "random_gold_k_baseline_mean": _mean([float(row["random_gold_k_pairwise_f1"]) for row in k2_rows]),
        "avg_edit_units": _mean(edit_counts),
        "p50_edit_units": float(quantile(edit_counts, 0.50)),
        "p90_edit_units": float(quantile(edit_counts, 0.90)),
    }


def _pairwise_overlap_count(rows_by_split: dict[str, list[dict[str, Any]]], field: str) -> int:
    values_by_split = {
        split: {str(row[field]) for row in rows if row.get(field)}
        for split, rows in rows_by_split.items()
    }
    total = 0
    splits = list(values_by_split)
    for left_index, left in enumerate(splits):
        for right in splits[left_index + 1:]:
            total += len(values_by_split[left] & values_by_split[right])
    return total


def _subject_overlap_count(rows_by_split: dict[str, list[dict[str, Any]]]) -> int:
    values_by_split = {
        split: {subject for row in rows for subject in row.get("normalized_subjects", [])}
        for split, rows in rows_by_split.items()
    }
    total = 0
    splits = list(values_by_split)
    for left_index, left in enumerate(splits):
        for right in splits[left_index + 1:]:
            total += len(values_by_split[left] & values_by_split[right])
    return total


def _leakage_checks(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    repo_overlap_count = _pairwise_overlap_count(rows_by_split, "repo")
    return {
        "sample_id_overlap_count": _pairwise_overlap_count(rows_by_split, "sample_id"),
        "sample_id_hard_leakage_zero": _pairwise_overlap_count(rows_by_split, "sample_id") == 0,
        "sha_overlap_checks": {
            "available": any(row.get("sha") for rows in rows_by_split.values() for row in rows),
            "hard_overlap_count": _pairwise_overlap_count(rows_by_split, "sha"),
            "hard_leakage_zero": _pairwise_overlap_count(rows_by_split, "sha") == 0,
        },
        "synthetic_id_overlap_checks": {
            "available": any(row.get("synthetic_id") for rows in rows_by_split.values() for row in rows),
            "hard_overlap_count": _pairwise_overlap_count(rows_by_split, "synthetic_id"),
            "hard_leakage_zero": _pairwise_overlap_count(rows_by_split, "synthetic_id") == 0,
        },
        "normalized_subject_overlap_checks": {
            "available": any(row.get("normalized_subjects") for rows in rows_by_split.values() for row in rows),
            "overlap_count": _subject_overlap_count(rows_by_split),
        },
        "repo_overlap_count": repo_overlap_count,
        "repo_overlap_allowed_for_stage1_synthetic": True,
        "repo_overlap_reason": "Stage 1 synthetic attribution splits are sample-disjoint; repo-disjointness is not guaranteed by current local Step1/Step2 pools.",
    }


def _write_split_manifests(output_root: Path, rows_by_split: dict[str, list[dict[str, Any]]], payload: dict[str, Any]) -> None:
    _write_json(output_root / "stage1_formal_manifest.json", payload)
    for split, rows in rows_by_split.items():
        _write_json(
            output_root / f"stage1_formal_manifest_{split}.json",
            {
                "split": split,
                "schedule_candidate": SCHEDULE_CANDIDATE,
                "samples": rows,
            },
        )


def _write_manifest_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Formal Manifest Summary",
        "",
        f"- seed: {payload['seed']}",
        f"- schedule_candidate: {payload['schedule_candidate']}",
        f"- formal_manifest_status: {payload['formal_manifest_status']}",
        f"- formal_manifest_downgraded: {str(payload['formal_manifest_downgraded']).lower()}",
        f"- fallback_applied: {str(payload['fallback_applied']).lower()}",
        f"- fallback_reason: {payload['fallback_reason']}",
        f"- runtime_manifest_not_committed: {str(payload['runtime_manifest_not_committed']).lower()}",
        f"- runtime_manifest_path: {payload['runtime_manifest_path']}",
        f"- synthetic_source_path_is_local_runtime_only: {str(payload['synthetic_source_path_is_local_runtime_only']).lower()}",
        "",
        "## Counts",
        "",
    ]
    for split, counts in payload["counts"].items():
        lines.append(f"- {split}: total={counts['total']}, k1={counts['atomic_k1']}, k2={counts['synthetic_k2']}")
    lines.extend(["", "## Split Diagnostics", ""])
    for split, diagnostics in payload["split_diagnostics"].items():
        lines.extend(
            [
                f"### {split}",
                "",
                f"- singleton_intent_fraction: {diagnostics['singleton_intent_fraction']:.6f}",
                f"- file_path_baseline_mean: {diagnostics['file_path_baseline_mean']:.6f}",
                f"- random_gold_k_baseline_mean: {diagnostics['random_gold_k_baseline_mean']:.6f}",
                f"- avg_edit_units: {diagnostics['avg_edit_units']:.6f}",
                f"- p50_edit_units: {diagnostics['p50_edit_units']:.6f}",
                f"- p90_edit_units: {diagnostics['p90_edit_units']:.6f}",
                "",
            ]
        )
    leakage = payload["leakage_checks"]
    lines.extend(
        [
            "## Leakage Checks",
            "",
            f"- sample_id_overlap_count: {leakage['sample_id_overlap_count']}",
            f"- sha_overlap_count: {leakage['sha_overlap_checks']['hard_overlap_count']}",
            f"- synthetic_id_overlap_count: {leakage['synthetic_id_overlap_checks']['hard_overlap_count']}",
            f"- normalized_subject_overlap_count: {leakage['normalized_subject_overlap_checks']['overlap_count']}",
            f"- repo_overlap_count: {leakage['repo_overlap_count']}",
            f"- repo_overlap_allowed_for_stage1_synthetic: {str(leakage['repo_overlap_allowed_for_stage1_synthetic']).lower()}",
            f"- repo_overlap_reason: {leakage['repo_overlap_reason']}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_protocol_freeze_checkpoint(*, manifest_summary: dict[str, Any], reports_root: str | Path) -> dict[str, Any]:
    reports_root_path = Path(reports_root)
    checkpoint = {
        "protocol_status": "candidate_frozen",
        "candidate_schedule": SCHEDULE_CANDIDATE,
        "formal_manifest_status": manifest_summary["formal_manifest_status"],
        "stage2_allowed": False,
        "next_action": "run_official_stage1_validation",
        "runtime_manifest_not_committed": bool(manifest_summary["runtime_manifest_not_committed"]),
        "runtime_manifest_path": manifest_summary["runtime_manifest_path"],
        "formal_manifest_downgraded": bool(manifest_summary.get("formal_manifest_downgraded", False)),
        "counts": manifest_summary["counts"],
        "leakage_checks": manifest_summary["leakage_checks"],
        "explicitly_not_included": [
            "hard_b",
            "M weak",
            "M alignment",
            "RealDomainSplit final-test",
            "RealDomainSelective final-test",
            "Stage 2",
            "generation",
            "retrieval",
            "verifier",
            "LLM Judge",
            "real API",
        ],
    }
    _write_json(reports_root_path / "mica_stage1_protocol_freeze.json", checkpoint)
    _write_freeze_markdown(reports_root_path / "mica_stage1_protocol_freeze.md", checkpoint)
    return checkpoint


def _write_freeze_markdown(path: Path, checkpoint: dict[str, Any]) -> None:
    leakage = checkpoint["leakage_checks"]
    synthetic_overlap = leakage.get("synthetic_id_overlap_checks", {}).get("hard_overlap_count", 0)
    lines = [
        "# MICA Stage 1 Protocol Freeze",
        "",
        f"- protocol_status: {checkpoint['protocol_status']}",
        f"- candidate_schedule: {checkpoint['candidate_schedule']}",
        f"- formal_manifest_status: {checkpoint['formal_manifest_status']}",
        f"- stage2_allowed: {str(checkpoint['stage2_allowed']).lower()}",
        f"- next_action: {checkpoint['next_action']}",
        f"- runtime_manifest_not_committed: {str(checkpoint['runtime_manifest_not_committed']).lower()}",
        f"- runtime_manifest_path: {checkpoint['runtime_manifest_path']}",
        f"- formal_manifest_downgraded: {str(checkpoint['formal_manifest_downgraded']).lower()}",
        "",
        "## Explicitly Not Included",
        "",
    ]
    lines.extend(f"- {item}" for item in checkpoint["explicitly_not_included"])
    lines.extend(
        [
            "",
            "## Leakage Summary",
            "",
            f"- sample_id_overlap_count: {leakage['sample_id_overlap_count']}",
            f"- sha_overlap_count: {leakage['sha_overlap_checks']['hard_overlap_count']}",
            f"- synthetic_id_overlap_count: {synthetic_overlap}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_stage1_formal_manifest(
    *,
    atomic_csv: str | Path,
    synthetic_jsonl: str | Path,
    output_root: str | Path,
    reports_root: str | Path = "reports",
    seed: int = 42,
    train_k1: int = 1000,
    train_k2: int = 1000,
    dev_k1: int = 250,
    dev_k2: int = 250,
    test_k1: int = 250,
    test_k2: int = 250,
) -> dict[str, Any]:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)

    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=_resolve_path(atomic_csv),
        synthetic_jsonl_path=_resolve_path(synthetic_jsonl),
        split_seed=seed,
    )
    all_samples = bundle.train + bundle.dev + bundle.test
    atomic_pool = _stable_order([sample for sample in all_samples if sample.source_kind == "atomic_k1"], seed=seed, namespace="atomic")
    synthetic_pool = _stable_order(
        [sample for sample in all_samples if sample.source_kind == "synthetic_k2"],
        seed=seed,
        namespace="synthetic",
    )

    requested = {
        "train": {"atomic_k1": train_k1, "synthetic_k2": train_k2},
        "dev": {"atomic_k1": dev_k1, "synthetic_k2": dev_k2},
        "test": {"atomic_k1": test_k1, "synthetic_k2": test_k2},
    }
    requested_k1_total = train_k1 + dev_k1 + test_k1
    requested_k2_total = train_k2 + dev_k2 + test_k2

    selected_atomic = atomic_pool[: min(len(atomic_pool), requested_k1_total)]
    selected_k2_pairs, k2_fallback, k2_fallback_reasons, medium_candidate_count = _select_k2_candidates(
        synthetic_pool,
        requested_k2_total,
    )
    selected_synthetic = [sample for sample, _ in selected_k2_pairs]
    selected_features = {sample.sample_id: features for sample, features in selected_k2_pairs}

    actual_k1_counts = {
        "train": min(train_k1, len(selected_atomic)),
        "dev": min(dev_k1, max(len(selected_atomic) - train_k1, 0)),
        "test": min(test_k1, max(len(selected_atomic) - train_k1 - dev_k1, 0)),
    }
    actual_k2_counts = {
        "train": min(train_k2, len(selected_synthetic)),
        "dev": min(dev_k2, max(len(selected_synthetic) - train_k2, 0)),
        "test": min(test_k2, max(len(selected_synthetic) - train_k2 - dev_k2, 0)),
    }
    atomic_splits = _split_selected(selected_atomic, actual_k1_counts)
    synthetic_splits = _split_selected(selected_synthetic, actual_k2_counts)

    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "dev", "test"):
        atomic_rows = [_row_for_sample(sample, split=split) for sample in atomic_splits[split]]
        synthetic_rows = [
            _row_for_sample(sample, split=split, features=selected_features[sample.sample_id])
            for sample in synthetic_splits[split]
        ]
        rows_by_split[split] = atomic_rows + synthetic_rows

    manifest_payload = {
        "created_at_utc": _timestamp(),
        "seed": int(seed),
        "schedule_candidate": SCHEDULE_CANDIDATE,
        "candidate_schedule_definition": {
            "epochs": 15,
            "train_mixed_k1_k2_from_epoch": 1,
            "lambda_align": 1.0,
            "lambda_count": 0.5,
            "lambda_exist": 0.5,
            "replay": False,
            "staged_k2_warmup": False,
            "stage2_loss": False,
        },
        "allowed_data_sources": ALLOWED_DATA_SOURCES,
        "forbidden_data_sources": FORBIDDEN_DATA_SOURCES,
        "splits": rows_by_split,
    }
    _write_split_manifests(output_root_path, rows_by_split, manifest_payload)

    counts = _counts_for_rows(rows_by_split)
    formal_manifest_downgraded = (
        len(selected_atomic) < requested_k1_total
        or len(selected_synthetic) < requested_k2_total
        or k2_fallback
    )
    downgrade_reason: list[str] = []
    if len(selected_atomic) < requested_k1_total:
        downgrade_reason.append("insufficient_atomic_k1_samples")
    if len(selected_synthetic) < requested_k2_total:
        downgrade_reason.append("insufficient_synthetic_k2_samples")
    if k2_fallback:
        downgrade_reason.extend(k2_fallback_reasons)

    summary = {
        "created_at_utc": _timestamp(),
        "seed": int(seed),
        "schedule_candidate": SCHEDULE_CANDIDATE,
        "formal_manifest_status": "frozen_runtime_manifest_created",
        "runtime_manifest_path": str(output_root_path / "stage1_formal_manifest.json"),
        "runtime_manifest_not_committed": True,
        "synthetic_source_path_is_local_runtime_only": True,
        "allowed_data_sources": ALLOWED_DATA_SOURCES,
        "forbidden_data_sources": FORBIDDEN_DATA_SOURCES,
        "stage2_allowed": False,
        "requested_counts": requested,
        "counts": counts,
        "medium_candidate_count_available": int(medium_candidate_count),
        "fallback_applied": bool(k2_fallback or formal_manifest_downgraded),
        "fallback_reason": downgrade_reason,
        "formal_manifest_downgraded": bool(formal_manifest_downgraded),
        "downgrade_reason": downgrade_reason,
        "post_fallback_baseline_distribution": {
            split: {
                "file_path_baseline_mean": _split_distribution(rows)["file_path_baseline_mean"],
                "random_gold_k_baseline_mean": _split_distribution(rows)["random_gold_k_baseline_mean"],
            }
            for split, rows in rows_by_split.items()
        },
        "split_diagnostics": {
            split: _split_distribution(rows)
            for split, rows in rows_by_split.items()
        },
        "leakage_checks": _leakage_checks(rows_by_split),
        "source_stats": bundle.source_stats,
    }
    _write_json(reports_root_path / "mica_stage1_formal_manifest_summary.json", summary)
    _write_manifest_markdown(reports_root_path / "mica_stage1_formal_manifest_summary.md", summary)
    build_protocol_freeze_checkpoint(manifest_summary=summary, reports_root=reports_root_path)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze the MICA Stage 1 formal candidate split manifest.")
    parser.add_argument("--synthetic-jsonl", required=True)
    parser.add_argument("--atomic-csv", default="datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv")
    parser.add_argument("--output-root", default=str(ROOT / "outputs" / f"mica_stage1_formal_manifest_{_timestamp()}"))
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-k1", type=int, default=1000)
    parser.add_argument("--train-k2", type=int, default=1000)
    parser.add_argument("--dev-k1", type=int, default=250)
    parser.add_argument("--dev-k2", type=int, default=250)
    parser.add_argument("--test-k1", type=int, default=250)
    parser.add_argument("--test-k2", type=int, default=250)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = build_stage1_formal_manifest(
        atomic_csv=args.atomic_csv,
        synthetic_jsonl=args.synthetic_jsonl,
        output_root=args.output_root,
        reports_root=args.reports_root,
        seed=args.seed,
        train_k1=args.train_k1,
        train_k2=args.train_k2,
        dev_k1=args.dev_k1,
        dev_k2=args.dev_k2,
        test_k1=args.test_k1,
        test_k2=args.test_k2,
    )
    print(
        json.dumps(
            {
                "report_json": str(Path(args.reports_root) / "mica_stage1_formal_manifest_summary.json"),
                "freeze_json": str(Path(args.reports_root) / "mica_stage1_protocol_freeze.json"),
                "runtime_manifest_path": payload["runtime_manifest_path"],
                "formal_manifest_downgraded": payload["formal_manifest_downgraded"],
                "stage2_allowed": payload["stage2_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
