from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, rel_path, repo_path, safe_text, utc_timestamp, write_json
from llm_backend import LLMBackend
from real_api_probe import INPUT_PRICE_PER_1M, OUTPUT_PRICE_PER_1M


def build_targeted_regression_plan(
    *,
    output_root: Path,
    sample_id: str,
    strategy: str,
    budget_cap_usd: float,
    reports_root: Path | None = None,
    report_timestamp: str | None = None,
) -> dict[str, Any]:
    report_timestamp = report_timestamp or utc_timestamp()
    reports_root = reports_root or output_root / "reports"
    samples = {row["sample_id"]: row for row in read_jsonl(output_root / "dataset" / "canary_all.jsonl")}
    retrieval_logs = read_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl")
    exclusions = read_jsonl(output_root / "exemplar_pool" / "exemplar_pool_exclusion_log.jsonl")
    prompts = {
        (row["sample_id"], row["strategy"]): row
        for row in read_jsonl(output_root / "prompts_rendered" / "probe_prompts.jsonl")
    }
    sample = samples.get(sample_id)
    if not sample:
        raise RuntimeError(f"Unknown sample_id: {sample_id}")
    if strategy != "G4":
        raise RuntimeError(f"Unsupported strategy for targeted regression: {strategy}")
    retrieval_log = None
    for log in retrieval_logs:
        if safe_text(log.get("query_sample_id")) == sample_id and safe_text(log.get("generation_strategy") or log.get("strategy")) == strategy:
            retrieval_log = log
            break
    if not retrieval_log:
        raise RuntimeError(f"Missing retrieval log for {sample_id} / {strategy}")
    same_repo_canonical_any = bool((retrieval_log.get("leakage_checks") or {}).get("same_repo_canonical"))
    source_sha_overlap_any = bool((retrieval_log.get("leakage_checks") or {}).get("source_sha_overlap"))
    diff_fingerprint_overlap_any = bool((retrieval_log.get("leakage_checks") or {}).get("diff_fingerprint_overlap"))
    normalized_subject_overlap_any = bool((retrieval_log.get("leakage_checks") or {}).get("normalized_subject_overlap"))
    if same_repo_canonical_any:
        raise RuntimeError("canonical same-repo leakage detected")
    retrieved_repo_canonical = retrieval_log.get("retrieved_repo_canonical") or []
    if any(repo == "arthursonzogni/ftxui" for repo in retrieved_repo_canonical):
        raise RuntimeError("same_repo_canonical exemplar entered retrieved exemplars")
    prompt_row = prompts.get((sample_id, strategy))
    if not prompt_row:
        raise RuntimeError(f"Missing prompt for {sample_id} / {strategy}")
    estimated_input_tokens_total = max(1, len(safe_text(prompt_row.get("prompt"))) // 4)
    estimated_output_tokens_total = 64
    estimated_cost_usd = (estimated_input_tokens_total * INPUT_PRICE_PER_1M + estimated_output_tokens_total * OUTPUT_PRICE_PER_1M) / 1_000_000
    if estimated_cost_usd > budget_cap_usd:
        raise RuntimeError("targeted regression budget exceeded")
    repo_guard_candidates = []
    for row in exclusions:
        if safe_text(row.get("candidate_repo_canonical")) == "arthursonzogni/ftxui":
            normalized = dict(row)
            if "reason" not in normalized:
                normalized["reason"] = (normalized.get("reasons") or [""])[0]
            repo_guard_candidates.append(normalized)
    exclusion_summary = {
        "repo_guard_excluded_candidates": repo_guard_candidates,
        "repo_guard_exclusion_count": len(repo_guard_candidates),
    }
    plan = {
        "sample": sample,
        "strategy": strategy,
        "planned_request_count": 1,
        "retrieval_log": retrieval_log,
        "leakage_gate": {
            "same_repo_canonical_any": same_repo_canonical_any,
            "source_sha_overlap_any": source_sha_overlap_any,
            "diff_fingerprint_overlap_any": diff_fingerprint_overlap_any,
            "normalized_subject_overlap_any": normalized_subject_overlap_any,
        },
        "exclusion_summary": exclusion_summary,
        "estimated_input_tokens_total": estimated_input_tokens_total,
        "estimated_output_tokens_total": estimated_output_tokens_total,
        "estimated_cost_usd": estimated_cost_usd,
    }
    execution_plan = {
        "schema_version": "targeted_ftxui_regression_execution_plan_v1",
        "report_timestamp": report_timestamp,
        "planned_request_count": 1,
        "sample_id": sample_id,
        "strategy": strategy,
        "query_repo_original": safe_text(sample.get("repo")),
        "query_repo_canonical": safe_text(sample.get("repo_canonical")),
        "estimated_input_tokens_total": estimated_input_tokens_total,
        "estimated_output_tokens_total": estimated_output_tokens_total,
        "estimated_cost_usd": estimated_cost_usd,
    }
    write_json(reports_root / f"targeted_ftxui_regression_execution_plan_{report_timestamp}.json", execution_plan)
    (reports_root / f"targeted_ftxui_regression_execution_plan_{report_timestamp}.md").write_text(
        "\n".join(
            [
                "# Targeted FTXUI Regression Execution Plan",
                "",
                f"- sample_id: `{sample_id}`",
                f"- strategy: `{strategy}`",
                f"- query_repo_original: `{sample.get('repo')}`",
                f"- query_repo_canonical: `{sample.get('repo_canonical')}`",
                f"- estimated_input_tokens_total: `{estimated_input_tokens_total}`",
                f"- estimated_output_tokens_total: `{estimated_output_tokens_total}`",
                f"- estimated_cost_usd: `{estimated_cost_usd}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(output_root / "retrieval_logs" / "targeted_ftxui_retrieval_log.json", retrieval_log)
    write_json(output_root / "retrieval_logs" / "targeted_ftxui_exclusion_summary.json", exclusion_summary)
    return plan


def run_targeted_generation_regression(
    *,
    output_root: Path,
    sample_id: str,
    strategy: str,
    config: dict[str, Any],
    allow_real_api: bool,
    budget_cap_usd: float = 0.03,
    reports_root: Path | None = None,
) -> dict[str, Any]:
    if not allow_real_api:
        raise RuntimeError("Real API calls are disabled. Pass --allow-real-api explicitly.")
    reports_root = reports_root or output_root / "reports"
    gen_path = output_root / "generations" / "real" / "generation_outputs.jsonl"
    existing = read_jsonl(gen_path) if gen_path.exists() else []
    previous_matching_count = len(
        [
            row
            for row in existing
            if safe_text(row.get("sample_id")) == sample_id and safe_text(row.get("strategy")) == strategy
        ]
    )
    plan = build_targeted_regression_plan(
        output_root=output_root,
        sample_id=sample_id,
        strategy=strategy,
        budget_cap_usd=budget_cap_usd,
        reports_root=reports_root,
    )
    backend = LLMBackend(dict(config.get("backend", {})), allow_real_api=True, dry_run=False)
    prompt_rows = {
        (row["sample_id"], row["strategy"]): row
        for row in read_jsonl(output_root / "prompts_rendered" / "probe_prompts.jsonl")
    }
    prompt = safe_text(prompt_rows[(sample_id, strategy)]["prompt"])
    result = backend.generate(prompt)
    result_row = {
        "sample_id": sample_id,
        "data_category": plan["sample"]["data_category"],
        "strategy": strategy,
        "generator_model": backend.model,
        "thinking_mode": backend.thinking_mode,
        "status": result.get("status", ""),
        "http_status": result.get("http_status", 0),
        "retry_count": result.get("retry_count", 0),
        "latency_ms": result.get("latency_ms", 0),
        "usage": result.get("usage", {}),
        "cache_hit": result.get("cache_hit", False),
        "generated_subject": result.get("generated_subject", ""),
        "retrieved_exemplar_ids": plan["retrieval_log"].get("retrieved_exemplar_ids", []),
        "retrieval_quality_status": plan["retrieval_log"].get("retrieval_quality_status", ""),
        "key_leakage_detected": False,
    }
    rows = [row for row in existing if not (safe_text(row.get("sample_id")) == sample_id and safe_text(row.get("strategy")) == strategy)]
    rows.append(result_row)
    from common import write_jsonl

    write_jsonl(gen_path, rows)
    report_timestamp = utc_timestamp()
    resumed_from_cache = previous_matching_count > 0 and bool(result_row["cache_hit"])
    report = {
        "schema_version": "targeted_ftxui_regression_result_v1",
        "report_timestamp": report_timestamp,
        "planned_request_count": 1,
        "completed_request_count": 1 if result_row["status"] == "generated" else 0,
        "failed_request_count": 0 if result_row["status"] == "generated" else 1,
        "new_real_request_count": 0 if resumed_from_cache else 1,
        "cache_hit_count": 1 if result_row["cache_hit"] else 0,
        "resume_skip_count": previous_matching_count if resumed_from_cache else 0,
        "actual_input_tokens_total": (result_row["usage"] or {}).get("prompt_tokens", "not_available"),
        "actual_output_tokens_total": (result_row["usage"] or {}).get("completion_tokens", "not_available"),
        "estimated_actual_cost_usd": (
            (((result_row["usage"] or {}).get("prompt_tokens", 0) * INPUT_PRICE_PER_1M) + ((result_row["usage"] or {}).get("completion_tokens", 0) * OUTPUT_PRICE_PER_1M)) / 1_000_000
            if isinstance((result_row["usage"] or {}).get("prompt_tokens"), int)
            else "not_available"
        ),
        "generated_subject": result_row["generated_subject"],
        "retrieved_exemplar_ids": result_row["retrieved_exemplar_ids"],
        "retrieval_quality_status": result_row["retrieval_quality_status"],
    }
    write_json(reports_root / f"targeted_ftxui_regression_result_{report_timestamp}.json", report)
    (reports_root / f"targeted_ftxui_regression_result_{report_timestamp}.md").write_text(
        "\n".join(
            [
                "# Targeted FTXUI Regression Result",
                "",
                f"- sample_id: `{sample_id}`",
                f"- strategy: `{strategy}`",
                f"- generated_subject: `{result_row['generated_subject']}`",
                f"- actual_input_tokens_total: `{report['actual_input_tokens_total']}`",
                f"- actual_output_tokens_total: `{report['actual_output_tokens_total']}`",
                f"- estimated_actual_cost_usd: `{report['estimated_actual_cost_usd']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {"plan": plan, "result": result_row, "report": report}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--allow-real-api", action="store_true")
    args = parser.parse_args()
    config = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    output_root = repo_path(args.output_root)
    result = run_targeted_generation_regression(
        output_root=output_root,
        sample_id=args.sample_id,
        strategy=args.strategy,
        config=config,
        allow_real_api=args.allow_real_api,
    )
    print(json.dumps({"generated_subject": result["result"]["generated_subject"]}, indent=2))


if __name__ == "__main__":
    main()
