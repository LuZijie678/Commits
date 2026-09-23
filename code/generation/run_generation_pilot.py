from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_generation_exemplar_pool import build_exemplar_pool
from build_generation_canary_dataset import build_canary_dataset
from build_generation_pilot_dataset import build_pilot_dataset
from common import read_jsonl, rel_path, repo_path, safe_text, utc_timestamp, write_json, write_jsonl
from llm_backend import LLMBackend
from prompting import render_prompt
from retrieve_generation_exemplars import retrieve_for_sample


STRATEGIES = ["G0", "G1", "G2", "G3", "G4", "G5"]
RETRIEVAL_BY_STRATEGY = {"G2": "random", "G3": "type_matched", "G4": "retrieval", "G5": "retrieval"}


def _generation_path(output_root: Path, run_kind: str) -> Path:
    return output_root / "generations" / run_kind / "generation_outputs.jsonl"


def run_generation_pilot(config: dict[str, Any], *, output_root: Path | None = None, allow_real_api: bool = False, dry_run: bool = False) -> dict[str, Any]:
    experiment_name = safe_text(config.get("experiment_name"))
    is_canary = "canary" in experiment_name
    is_probe = "probe" in experiment_name
    if is_probe:
        default_root = f"outputs/llm_generation_real_api_probe_{utc_timestamp()}"
    elif is_canary:
        default_root = f"outputs/llm_generation_canary_{utc_timestamp()}"
    else:
        default_root = f"outputs/llm_generation_pilot_{utc_timestamp()}"
    output_root = output_root or repo_path(config.get("output_root") or default_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_result = build_canary_dataset(config, output_root) if is_canary or is_probe else build_pilot_dataset(config, output_root)
    if not dataset_result["leakage"]["passed"]:
        raise RuntimeError("pilot leakage report failed")
    exemplar_result = build_exemplar_pool(config, output_root)
    samples = dataset_result["rows"]
    pool = exemplar_result["pool"]
    few_shot_k = int(config.get("few_shot_k", 3))
    seed = int(config.get("random_seed", 42))
    low_similarity_threshold = float(config.get("retrieval_low_similarity_threshold", 0.10))
    backend_cfg = dict(config.get("backend", {"provider": "mock", "model": "mock-model"}))
    backend = LLMBackend(backend_cfg, allow_real_api=allow_real_api, dry_run=dry_run)
    run_kind = "real" if allow_real_api and backend.provider != "mock" else "mock"
    out_path = _generation_path(output_root, run_kind)
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if bool(config.get("resume", True)) and out_path.exists():
        for row in read_jsonl(out_path):
            existing[(safe_text(row.get("sample_id")), safe_text(row.get("strategy")))] = row

    generations: list[dict[str, Any]] = list(existing.values())
    rendered_rows: list[dict[str, Any]] = []
    retrieval_log_path = output_root / "retrieval_logs" / "retrieval_logs.jsonl"
    retrieval_logs: list[dict[str, Any]] = read_jsonl(retrieval_log_path) if bool(config.get("resume", True)) and retrieval_log_path.exists() else []
    planned_request_count = 0
    abort_reason = ""
    for sample in samples:
        for strategy in _strategies_for_sample(config, sample):
            if strategy == "G5" and sample.get("data_category") != "synthetic_multi":
                if not is_canary:
                    generations.append(_skipped(sample, strategy, "oracle_structure_unavailable"))
                continue
            planned_request_count += 1
            key = (sample["sample_id"], strategy)
            if key in existing:
                continue
            exemplars: list[dict[str, Any]] = []
            retrieved_ids: list[str] = []
            if strategy in RETRIEVAL_BY_STRATEGY:
                exemplars, log = retrieve_for_sample(
                    sample,
                    pool,
                    strategy=RETRIEVAL_BY_STRATEGY[strategy],
                    k=few_shot_k,
                    seed=seed,
                    low_similarity_threshold=low_similarity_threshold,
                )
                retrieval_logs.append({**log, "generation_strategy": strategy})
                retrieved_ids = [safe_text(ex.get("exemplar_id")) for ex in exemplars]
            try:
                prompt = render_prompt(strategy, sample, exemplars)
                rendered_rows.append({"sample_id": sample["sample_id"], "strategy": strategy, "prompt": prompt})
                result = backend.generate(prompt)
                generations.append(
                    {
                        "sample_id": sample["sample_id"],
                        "data_category": sample.get("data_category", ""),
                        "strategy": strategy,
                        "generator_model": backend.model,
                        "prompt_version": "v1",
                        "retrieved_exemplar_ids": retrieved_ids,
                        "generated_subject": result.get("generated_subject", ""),
                        "status": result.get("status", "failed"),
                        "failure_reason": result.get("failure_reason", ""),
                        "latency_ms": result.get("latency_ms", 0),
                        "usage": result.get("usage", {}),
                        "cache_hit": result.get("cache_hit", False),
                        "retry_count": result.get("retry_count", 0),
                        "http_status": result.get("http_status", 0),
                        "thinking_mode": result.get("thinking_mode", backend.thinking_mode),
                        "oracle_only": strategy == "G5",
                        "deployable": strategy != "G5",
                    }
                )
                if _should_abort_real_probe(is_probe, allow_real_api, backend.provider, generations[-1]):
                    abort_reason = generations[-1]["failure_reason"] or f"HTTP {generations[-1]['http_status']}"
                    break
            except Exception as exc:  # noqa: BLE001 - failures must be recorded for pilot runs.
                generations.append(_skipped(sample, strategy, str(exc), status="failed"))
                if _should_abort_real_probe(is_probe, allow_real_api, backend.provider, generations[-1]):
                    abort_reason = generations[-1]["failure_reason"]
                    break
        if abort_reason:
            break

    write_jsonl(out_path, generations)
    prompt_file = "probe_prompts.jsonl" if is_probe else ("canary_prompts.jsonl" if is_canary else f"{run_kind}_prompts.jsonl")
    prompt_path = output_root / "prompts_rendered" / prompt_file
    prompt_rows_to_write = rendered_rows
    if not prompt_rows_to_write and existing and (not prompt_path.exists() or prompt_path.stat().st_size == 0):
        prompt_rows_to_write = _recover_rendered_rows(
            samples,
            pool,
            generations,
            few_shot_k=few_shot_k,
            seed=seed,
            low_similarity_threshold=low_similarity_threshold,
        )
    if prompt_rows_to_write or not prompt_path.exists():
        write_jsonl(prompt_path, prompt_rows_to_write)
    if is_canary or is_probe:
        summary_name = "probe_prompt_summary.json" if is_probe else "canary_prompt_summary.json"
        summary_path = output_root / "prompts_rendered" / summary_name
        if prompt_rows_to_write or not summary_path.exists():
            write_json(summary_path, _prompt_summary(prompt_rows_to_write, retrieval_logs))
    write_jsonl(retrieval_log_path, retrieval_logs)
    metadata = {
        "schema_version": "llm_generation_pilot_run_v1",
        "output_root": rel_path(output_root),
        "provider": backend.provider,
        "model": backend.model,
        "allow_real_api": allow_real_api,
        "dry_run": dry_run,
        "sample_count": len(samples),
        "strategy_count": len(_strategy_universe(config)),
        "planned_request_count": planned_request_count,
        "real_api_called": allow_real_api and backend.provider != "mock" and not dry_run,
        "thinking_mode": backend.thinking_mode,
        "backend_metadata": backend.metadata(),
        "dataset_manifest": dataset_result["manifest"],
        "exemplar_pool_manifest": exemplar_result["manifest"],
    }
    write_json(output_root / "run_metadata.json", metadata)
    if abort_reason:
        raise RuntimeError(abort_reason)
    return {"output_root": output_root, "metadata": metadata, "generation_count": len(generations)}


def _strategies_for_sample(config: dict[str, Any], sample: dict[str, Any]) -> list[str]:
    strategy_plan = config.get("strategy_plan") or {}
    category = safe_text(sample.get("data_category"))
    if category in strategy_plan:
        return list(strategy_plan[category])
    return list(config.get("generation_strategies", STRATEGIES))


def _strategy_universe(config: dict[str, Any]) -> list[str]:
    strategy_plan = config.get("strategy_plan") or {}
    if strategy_plan:
        values = [strategy for strategies in strategy_plan.values() for strategy in strategies]
        return sorted(set(values))
    return list(config.get("generation_strategies", STRATEGIES))


def _prompt_summary(rendered_rows: list[dict[str, Any]], retrieval_logs: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = sorted(len(safe_text(row.get("prompt"))) for row in rendered_rows)
    by_strategy: dict[str, int] = {}
    for row in rendered_rows:
        strategy = safe_text(row.get("strategy"))
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
    return {
        "schema_version": "llm_generation_canary_prompt_summary_v1",
        "prompt_count": len(rendered_rows),
        "strategy_distribution": by_strategy,
        "input_char_count": sum(lengths),
        "estimated_input_token_count": sum(max(1, length // 4) for length in lengths),
        "max_prompt_length": max(lengths) if lengths else 0,
        "p50_prompt_length": _percentile(lengths, 0.5),
        "p90_prompt_length": _percentile(lengths, 0.9),
        "truncation_count": 0,
        "retrieval_fallback_count": sum(1 for row in retrieval_logs if safe_text(row.get("fallback_reason"))),
        "g5_oracle_only": True,
        "g5_deployable": False,
    }


def _recover_rendered_rows(
    samples: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    generations: list[dict[str, Any]],
    *,
    few_shot_k: int,
    seed: int,
    low_similarity_threshold: float = 0.10,
) -> list[dict[str, Any]]:
    sample_map = {safe_text(sample.get("sample_id")): sample for sample in samples}
    recovered: list[dict[str, Any]] = []
    for row in generations:
        sample_id = safe_text(row.get("sample_id"))
        strategy = safe_text(row.get("strategy"))
        sample = sample_map.get(sample_id)
        if not sample or not strategy:
            continue
        exemplars: list[dict[str, Any]] = []
        if strategy in RETRIEVAL_BY_STRATEGY:
            exemplars, _ = retrieve_for_sample(
                sample,
                pool,
                strategy=RETRIEVAL_BY_STRATEGY[strategy],
                k=few_shot_k,
                seed=seed,
                low_similarity_threshold=low_similarity_threshold,
            )
        recovered.append(
            {
                "sample_id": sample_id,
                "strategy": strategy,
                "prompt": render_prompt(strategy, sample, exemplars),
            }
        )
    return recovered


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return values[index]


def _skipped(sample: dict[str, Any], strategy: str, reason: str, *, status: str = "skipped") -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "data_category": sample.get("data_category", ""),
        "strategy": strategy,
        "generator_model": "",
        "prompt_version": "v1",
        "retrieved_exemplar_ids": [],
        "generated_subject": "",
        "status": status,
        "failure_reason": reason,
        "latency_ms": 0,
        "usage": {},
        "cache_hit": False,
        "retry_count": 0,
        "http_status": 0,
        "thinking_mode": "",
        "oracle_only": strategy == "G5",
        "deployable": strategy != "G5",
    }


def _should_abort_real_probe(is_probe: bool, allow_real_api: bool, provider: str, row: dict[str, Any]) -> bool:
    if not (is_probe and allow_real_api and provider != "mock"):
        return False
    if safe_text(row.get("status")) != "failed":
        return False
    http_status = int(row.get("http_status", 0) or 0)
    failure_reason = safe_text(row.get("failure_reason")).lower()
    if http_status in {401, 402, 404, 429}:
        return True
    return "timeout" in failure_reason or "timed out" in failure_reason


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_pilot.mock.json")
    parser.add_argument("--output-root")
    parser.add_argument("--allow-real-api", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    result = run_generation_pilot(
        config,
        output_root=repo_path(args.output_root) if args.output_root else None,
        allow_real_api=args.allow_real_api,
        dry_run=args.dry_run,
    )
    print(f"wrote {result['generation_count']} generations to {rel_path(result['output_root'])}")


if __name__ == "__main__":
    main()
