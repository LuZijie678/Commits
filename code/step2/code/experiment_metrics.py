#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from experiment_tooling_common import (
    infer_generation_attempted,
    is_generated_and_scored,
    is_step3_ready_row,
    load_json,
    nearest_rank_percentile,
    read_csv_rows,
    read_jsonl_rows,
    safe_float,
    safe_strip,
    write_json,
    write_markdown,
)


def _count_fewshot_source(label: str) -> str:
    text = safe_strip(label)
    if text == "exact_kway":
        return "exact"
    if text in {"type_overlap", "pairwise_overlap", "single_type_overlap"}:
        return "partial"
    if text == "generic_fallback":
        return "generic"
    if text == "failed":
        return "failed"
    return "other"


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    return round(float(nearest_rank_percentile(values, p)), 6)


def _distribution_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": _mean(values),
        "p50": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
    }


def _scalar_from_row(row: dict[str, Any], top_level: str, nested_group: str | None, nested_key: str | None) -> float | None:
    if row.get(top_level) is not None:
        return safe_float(row.get(top_level))
    if nested_group and nested_key:
        payload = row.get(nested_group, {}) or {}
        if payload.get(nested_key) is not None:
            return safe_float(payload.get(nested_key))
    return None


def _extract_difficulty_realism(rows: list[dict[str, Any]], run_metadata: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    summary = ((run_metadata.get("run_stats", {}) or {}).get("difficulty_realism_summary", {}) or {})
    runtime_cfg = dict(run_metadata.get("difficulty_realism", {}) or {})

    level_counter = Counter(safe_strip(row.get("difficulty_level", "")) for row in rows if safe_strip(row.get("difficulty_level", "")))
    intent_counter = Counter(safe_strip(row.get("intent_cardinality", "")) for row in rows if safe_strip(row.get("intent_cardinality", "")))
    structure_counter = Counter(safe_strip(row.get("structure_pattern", "")) for row in rows if safe_strip(row.get("structure_pattern", "")))
    route_counter = Counter(safe_strip(row.get("construction_route", "")) for row in rows if safe_strip(row.get("construction_route", "")))

    realism_scores = [safe_float(row.get("realism_score")) for row in rows if row.get("realism_score") is not None]
    rho_values = [safe_float(row.get("rho")) for row in rows if row.get("rho") is not None]
    identifier_overlap_values = []
    dependency_hint_values = []
    main_topic_coherence_values = []
    shared_file_ratio_values = []
    realism_weight_config = {}

    for row in rows:
        features = row.get("difficulty_features", {}) or {}
        if features.get("identifier_overlap_score") is not None:
            identifier_overlap_values.append(safe_float(features.get("identifier_overlap_score")))
        if features.get("dependency_hint_score") is not None:
            dependency_hint_values.append(safe_float(features.get("dependency_hint_score")))
        if features.get("main_topic_coherence") is not None:
            main_topic_coherence_values.append(safe_float(features.get("main_topic_coherence")))
        if features.get("shared_file_ratio") is not None:
            shared_file_ratio_values.append(safe_float(features.get("shared_file_ratio")))
        if not realism_weight_config and isinstance(row.get("realism_weight_config"), dict):
            realism_weight_config = dict(row.get("realism_weight_config", {}) or {})

    if not level_counter and summary.get("difficulty_level_counts"):
        level_counter.update(summary.get("difficulty_level_counts", {}))
    if not level_counter and summary.get("level_distribution"):
        level_counter.update(summary.get("level_distribution", {}))
    if not intent_counter and summary.get("intent_cardinality_counts"):
        intent_counter.update(summary.get("intent_cardinality_counts", {}))
    if not intent_counter and summary.get("intent_cardinality_distribution"):
        intent_counter.update(summary.get("intent_cardinality_distribution", {}))
    if not structure_counter and summary.get("structure_pattern_counts"):
        structure_counter.update(summary.get("structure_pattern_counts", {}))
    if not structure_counter and summary.get("structure_pattern_distribution"):
        structure_counter.update(summary.get("structure_pattern_distribution", {}))
    if not route_counter and summary.get("construction_route_distribution"):
        route_counter.update(summary.get("construction_route_distribution", {}))

    if not realism_weight_config and isinstance(summary.get("realism_weight_config"), dict):
        realism_weight_config = dict(summary.get("realism_weight_config", {}) or {})

    if not rows:
        warnings.append("difficulty_realism_missing:no_rows")
    elif not (level_counter or realism_scores or rho_values or identifier_overlap_values or dependency_hint_values):
        warnings.append("difficulty_realism_missing:sample_fields")

    tau_low = safe_float(
        runtime_cfg.get("tau_realism_low", (summary.get("realism_score_summary", {}) or {}).get("tau_realism_low", 0.5)),
        0.5,
    )
    low_count = sum(1 for value in realism_scores if value < tau_low)
    if not realism_scores and isinstance(summary.get("realism_score_summary"), dict):
        realism_summary = dict(summary.get("realism_score_summary", {}) or {})
        realism_score_payload = {
            "mean": realism_summary.get("mean"),
            "p50": realism_summary.get("p50"),
            "p90": realism_summary.get("p90"),
            "low_count": realism_summary.get("low_realism_count", 0),
            "tau_low": realism_summary.get("tau_realism_low", tau_low),
        }
    else:
        realism_score_payload = {
            **_distribution_summary(realism_scores),
            "low_count": low_count,
            "tau_low": tau_low,
        }

    rho_summary = _distribution_summary(rho_values)
    if not rho_values and isinstance(summary.get("rho_summary"), dict):
        rho_summary = {
            "mean": (summary.get("rho_summary", {}) or {}).get("mean"),
            "p50": (summary.get("rho_summary", {}) or {}).get("p50"),
            "p90": (summary.get("rho_summary", {}) or {}).get("p90"),
        }

    return {
        "difficulty_level_counts": dict(level_counter),
        "intent_cardinality_counts": dict(intent_counter),
        "structure_pattern_counts": dict(structure_counter),
        "construction_route_counts": dict(route_counter),
        "realism_score": realism_score_payload,
        "rho": rho_summary,
        "identifier_overlap_score": _distribution_summary(identifier_overlap_values),
        "dependency_hint_score": _distribution_summary(dependency_hint_values),
        "main_topic_coherence": _distribution_summary(main_topic_coherence_values),
        "shared_file_ratio": _distribution_summary(shared_file_ratio_values),
        "realism_weight_formula": safe_strip(summary.get("realism_weight_formula", "")),
        "realism_weight_config": realism_weight_config,
        "pipeline_owner": safe_strip(summary.get("pipeline_owner", runtime_cfg.get("pipeline_owner", ""))),
        "pipeline_order": list(summary.get("pipeline_order", runtime_cfg.get("pipeline_order", [])) or []),
        "tau_realism_low_source": safe_strip(runtime_cfg.get("tau_realism_low_source", "")),
        "level_a_b_route_status": safe_strip(runtime_cfg.get("level_a_b_route_status", "")),
    }


def aggregate_experiment_metrics(
    *,
    output_dir: Path,
    synthetic_samples_path: Path | None = None,
    synthetic_index_path: Path | None = None,
    step3_ready_path: Path | None = None,
    run_metadata_path: Path | None = None,
    gate_report_path: Path | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    samples_path = synthetic_samples_path or (output_dir / "synthetic_samples.jsonl")
    index_path = synthetic_index_path or (output_dir / "synthetic_index.csv")
    ready_path = step3_ready_path or (output_dir / "synthetic_samples_step3_ready.jsonl")
    metadata_path = run_metadata_path or (output_dir / "run_metadata.json")
    report_path = gate_report_path or (output_dir / "message_gate_report.json")

    rows, row_warnings = read_jsonl_rows(samples_path)
    warnings.extend(row_warnings)
    _index_rows, index_warnings = read_csv_rows(index_path)
    warnings.extend(index_warnings)
    step3_rows, step3_warnings = read_jsonl_rows(ready_path)
    warnings.extend(step3_warnings)

    run_metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            run_metadata = load_json(metadata_path)
        except Exception as exc:
            warnings.append(f"run_metadata_parse_error:{metadata_path.name}:{exc}")
    else:
        warnings.append(f"missing_file:{metadata_path}")

    gate_report: dict[str, Any] = {}
    if report_path.exists():
        try:
            gate_report = load_json(report_path)
        except Exception as exc:
            warnings.append(f"gate_report_parse_error:{report_path.name}:{exc}")
    else:
        warnings.append(f"missing_file:{report_path}")

    total_samples = len(rows)
    precheck_skip = sum(1 for row in rows if safe_strip(row.get("precheck_status")) == "skip")
    generation_attempted = sum(1 for row in rows if infer_generation_attempted(row))
    generation_success = sum(1 for row in rows if safe_strip(row.get("generation_status")) == "generated")
    generation_failed_rows = [row for row in rows if safe_strip(row.get("generation_status")) == "generation_failed"]
    generation_failed = len(generation_failed_rows)
    judge_failed = sum(1 for row in rows if safe_strip(row.get("generation_status")) in {"judge_failed", "scoring_failed"})

    scored_rows = [row for row in rows if is_generated_and_scored(row)]
    true_reject = sum(1 for row in scored_rows if row.get("message_status") == "reject")
    message_pass = sum(1 for row in scored_rows if row.get("message_status") == "pass")
    message_fallback = sum(1 for row in scored_rows if row.get("message_status") == "fallback")
    step3_ready = len(step3_rows) if step3_rows else sum(1 for row in rows if is_step3_ready_row(row))

    fewshot_bucket_counter = Counter()
    for row in rows:
        if safe_strip(row.get("precheck_status")) == "skip":
            continue
        fewshot_bucket_counter[_count_fewshot_source(row.get("few_shot_source", ""))] += 1

    generated_scored_count = len(scored_rows)
    quality_rows = [row for row in scored_rows if row.get("message_status") in {"pass", "fallback"}]
    coverage_values = [safe_float((row.get("message_scores") or {}).get("coverage_min_r")) for row in quality_rows]
    message_weight_values = [safe_float((row.get("message_scores") or {}).get("message_quality_weight")) for row in scored_rows]
    final_weight_values = [safe_float(row.get("final_sample_weight")) for row in rows if safe_float(row.get("final_sample_weight")) > 0]

    error_counter = Counter()
    for row in generation_failed_rows:
        reason = safe_strip((row.get("message_meta") or {}).get("generation_failure_reason")) or "unknown"
        error_counter[f"generation_failure:{reason}"] += 1
    for row in rows:
        status = safe_strip(row.get("generation_status"))
        if status in {"judge_failed", "scoring_failed"}:
            error_counter[status] += 1

    payload: dict[str, Any] = {
        "output_dir": str(output_dir),
        "counts": {
            "total_samples": total_samples,
            "precheck_skip": precheck_skip,
            "generation_attempted": generation_attempted,
            "generation_success": generation_success,
            "generation_failed": generation_failed,
            "judge_failed": judge_failed,
            "message_pass": message_pass,
            "message_fallback": message_fallback,
            "true_message_reject": true_reject,
            "step3_ready": step3_ready,
        },
        "rates": {
            "precheck_skip_rate": round(precheck_skip / total_samples, 6) if total_samples else 0.0,
            "generation_failure_rate_attempted": round(generation_failed / generation_attempted, 6) if generation_attempted else 0.0,
            "true_message_reject_rate_scored": round(true_reject / generated_scored_count, 6) if generated_scored_count else 0.0,
            "message_pass_rate_scored": round(message_pass / generated_scored_count, 6) if generated_scored_count else 0.0,
            "message_fallback_rate_scored": round(message_fallback / generated_scored_count, 6) if generated_scored_count else 0.0,
            "step3_ready_ratio_total": round(step3_ready / total_samples, 6) if total_samples else 0.0,
        },
        "quality": {
            "coverage_min_mean": _mean(coverage_values),
            "coverage_min_p10": _percentile(coverage_values, 0.1),
            "message_quality_weight_mean": _mean(message_weight_values),
            "final_sample_weight_mean": _mean(final_weight_values),
        },
        "fewshot": {
            "exact_count": fewshot_bucket_counter.get("exact", 0),
            "partial_count": fewshot_bucket_counter.get("partial", 0),
            "generic_count": fewshot_bucket_counter.get("generic", 0),
            "failed_count": fewshot_bucket_counter.get("failed", 0),
            "generic_rate": round(fewshot_bucket_counter.get("generic", 0) / max(1, sum(fewshot_bucket_counter.values())), 6) if fewshot_bucket_counter else 0.0,
            "failed_rate": round(fewshot_bucket_counter.get("failed", 0) / max(1, sum(fewshot_bucket_counter.values())), 6) if fewshot_bucket_counter else 0.0,
        },
        "errors": {
            "by_error_code": dict(error_counter),
        },
        "denominators": {
            "generation_failure_rate_attempted": "generation_attempted",
            "true_message_reject_rate_scored": "generated_and_scored",
            "message_pass_rate_scored": "generated_and_scored",
            "message_fallback_rate_scored": "generated_and_scored",
            "step3_ready_ratio_total": "total_samples",
        },
        "metadata_hints": {
            "run_purpose": run_metadata.get("run_purpose"),
            "run_valid_for_paper": run_metadata.get("run_valid_for_paper"),
            "message_gate_passed": (gate_report or run_metadata.get("message_gate") or {}).get("message_gate_passed"),
        },
        "difficulty_realism": _extract_difficulty_realism(rows, run_metadata, warnings),
        "warnings": warnings,
    }
    return payload


def render_markdown(metrics: dict[str, Any]) -> str:
    counts = metrics["counts"]
    rates = metrics["rates"]
    quality = metrics["quality"]
    fewshot = metrics["fewshot"]
    difficulty = metrics.get("difficulty_realism", {})
    warnings = metrics.get("warnings", [])
    lines = [
        "# Experiment Metrics",
        "",
        f"- output_dir: `{metrics.get('output_dir', '')}`",
        f"- total_samples: `{counts['total_samples']}`",
        f"- generation_attempted / success / failed: `{counts['generation_attempted']}` / `{counts['generation_success']}` / `{counts['generation_failed']}`",
        f"- judge_failed: `{counts['judge_failed']}`",
        f"- message_pass / fallback / true_reject: `{counts['message_pass']}` / `{counts['message_fallback']}` / `{counts['true_message_reject']}`",
        f"- step3_ready: `{counts['step3_ready']}`",
        f"- precheck_skip_rate: `{rates['precheck_skip_rate']:.6f}`",
        f"- generation_failure_rate_attempted: `{rates['generation_failure_rate_attempted']:.6f}`",
        f"- true_message_reject_rate_scored: `{rates['true_message_reject_rate_scored']:.6f}`",
        f"- step3_ready_ratio_total: `{rates['step3_ready_ratio_total']:.6f}`",
        f"- coverage_min_mean / p10: `{quality['coverage_min_mean']}` / `{quality['coverage_min_p10']}`",
        f"- message_quality_weight_mean: `{quality['message_quality_weight_mean']}`",
        f"- final_sample_weight_mean: `{quality['final_sample_weight_mean']}`",
        f"- fewshot exact / partial / generic / failed: `{fewshot['exact_count']}` / `{fewshot['partial_count']}` / `{fewshot['generic_count']}` / `{fewshot['failed_count']}`",
        "",
        "## Difficulty / Realism",
        f"- difficulty_level_counts: `{json.dumps(difficulty.get('difficulty_level_counts', {}), ensure_ascii=False)}`",
        f"- intent_cardinality_counts: `{json.dumps(difficulty.get('intent_cardinality_counts', {}), ensure_ascii=False)}`",
        f"- structure_pattern_counts: `{json.dumps(difficulty.get('structure_pattern_counts', {}), ensure_ascii=False)}`",
        f"- construction_route_counts: `{json.dumps(difficulty.get('construction_route_counts', {}), ensure_ascii=False)}`",
        f"- realism_score: `{json.dumps(difficulty.get('realism_score', {}), ensure_ascii=False)}`",
        f"- rho: `{json.dumps(difficulty.get('rho', {}), ensure_ascii=False)}`",
        f"- identifier_overlap_score: `{json.dumps(difficulty.get('identifier_overlap_score', {}), ensure_ascii=False)}`",
        f"- dependency_hint_score: `{json.dumps(difficulty.get('dependency_hint_score', {}), ensure_ascii=False)}`",
        f"- main_topic_coherence: `{json.dumps(difficulty.get('main_topic_coherence', {}), ensure_ascii=False)}`",
        f"- shared_file_ratio: `{json.dumps(difficulty.get('shared_file_ratio', {}), ensure_ascii=False)}`",
        f"- tau_realism_low_source: `{difficulty.get('tau_realism_low_source')}`",
        f"- realism_weight_formula: `{difficulty.get('realism_weight_formula')}`",
        f"- realism_weight_config: `{json.dumps(difficulty.get('realism_weight_config', {}), ensure_ascii=False)}`",
        f"- pipeline_owner: `{difficulty.get('pipeline_owner')}`",
        f"- pipeline_order: `{json.dumps(difficulty.get('pipeline_order', []), ensure_ascii=False)}`",
        "",
        f"- warnings: `{json.dumps(warnings, ensure_ascii=False)}`",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate offline Step2 run metrics from an output directory.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--synthetic-samples", default="")
    parser.add_argument("--synthetic-index", default="")
    parser.add_argument("--step3-ready", default="")
    parser.add_argument("--run-metadata", default="")
    parser.add_argument("--gate-report", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--markdown", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = aggregate_experiment_metrics(
        output_dir=Path(args.output_dir),
        synthetic_samples_path=Path(args.synthetic_samples) if args.synthetic_samples else None,
        synthetic_index_path=Path(args.synthetic_index) if args.synthetic_index else None,
        step3_ready_path=Path(args.step3_ready) if args.step3_ready else None,
        run_metadata_path=Path(args.run_metadata) if args.run_metadata else None,
        gate_report_path=Path(args.gate_report) if args.gate_report else None,
    )
    write_json(Path(args.out), metrics)
    if args.markdown:
        write_markdown(Path(args.markdown), render_markdown(metrics))


if __name__ == "__main__":
    main()
