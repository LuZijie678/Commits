from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, rel_path, repo_path, safe_text, write_json


def estimate_canary_cost(config: dict[str, Any], output_root: Path | None = None, *, write_reports: bool = True) -> dict[str, Any]:
    experiment_name = safe_text(config.get("experiment_name"))
    is_probe = "probe" in experiment_name
    pending_root = "outputs/llm_generation_real_api_probe_PENDING" if is_probe else "outputs/llm_generation_canary_PENDING"
    output_root = output_root or repo_path(config.get("output_root") or pending_root)
    sizes = {key: int(value) for key, value in config.get("pilot_sample_size", {}).items()}
    strategy_distribution: dict[str, int] = {}
    strategy_plan = config.get("strategy_plan") or {}
    if strategy_plan:
        for category, strategies in strategy_plan.items():
            for strategy in strategies:
                strategy_distribution[strategy] = strategy_distribution.get(strategy, 0) + sizes.get(category, 0)
    else:
        strategies = list(config.get("generation_strategies", []))
        for strategy in strategies:
            if strategy == "G5":
                strategy_distribution[strategy] = sizes.get("synthetic_multi", 0)
            else:
                strategy_distribution[strategy] = sum(sizes.values())
    planned_request_count = sum(strategy_distribution.values())
    prompt_summary_path = output_root / "prompts_rendered" / ("probe_prompt_summary.json" if is_probe else "canary_prompt_summary.json")
    prompt_summary = read_json(prompt_summary_path) if prompt_summary_path.exists() else {}
    backend = dict(config.get("backend", {}))
    output_tokens = int(backend.get("max_output_tokens", 64)) * planned_request_count
    estimated_input_tokens = int(prompt_summary.get("estimated_input_token_count", 0))
    estimated_tokens_by_strategy = {
        strategy: {
            "estimated_input_tokens": "requires_prompt_rendering" if not prompt_summary else "see canary_prompt_summary",
            "estimated_output_tokens": count * int(backend.get("max_output_tokens", 64)),
        }
        for strategy, count in strategy_distribution.items()
    }
    price = config.get("pricing", {})
    input_price = price.get("cache_miss_input_per_1m_tokens", price.get("input_per_1m_tokens"))
    output_price = price.get("output_per_1m_tokens")
    if input_price is None or output_price is None:
        estimated_cost: str | float = "not_available"
        cost_status = "requires_manual_provider_pricing"
        cost_formula = "input_tokens * input_per_1m / 1e6 + output_tokens * output_per_1m / 1e6"
    else:
        estimated_cost = (estimated_input_tokens * float(input_price) + output_tokens * float(output_price)) / 1_000_000
        cost_status = "estimated_from_configured_prices"
        cost_formula = f"{estimated_input_tokens} * {input_price} / 1e6 + {output_tokens} * {output_price} / 1e6"
    report = {
        "schema_version": "real_api_probe_execution_plan_v1" if is_probe else "real_api_canary_execution_plan_v1",
        "provider": safe_text(backend.get("provider")),
        "base_url": safe_text(backend.get("base_url")),
        "model": safe_text(backend.get("model")),
        "sample_count": sum(sizes.values()),
        "strategy_distribution": strategy_distribution,
        "planned_request_count": planned_request_count,
        "estimated_input_tokens": estimated_input_tokens if prompt_summary else "requires_prompt_rendering",
        "estimated_output_tokens": output_tokens,
        "estimated_input_tokens_total": estimated_input_tokens if prompt_summary else "requires_prompt_rendering",
        "estimated_output_tokens_total": output_tokens,
        "estimated_tokens_by_strategy": estimated_tokens_by_strategy,
        "few_shot_k": int(config.get("few_shot_k", 3)),
        "cache_enabled": bool(backend.get("cache_path")),
        "cache_path": safe_text(backend.get("cache_path")),
        "resume_enabled": bool(config.get("resume", True)),
        "output_root": rel_path(output_root),
        "api_key_env": safe_text(backend.get("api_key_env")),
        "context_window": config.get("context_window", "requires_user_input"),
        "rate_limit": config.get("rate_limit", "requires_user_input"),
        "probe_budget_cap": config.get("probe_budget_cap", "not_applicable"),
        "probe_budget_cap_usd": config.get("probe_budget_cap_usd", config.get("probe_budget_cap", "not_applicable")),
        "thinking_mode": safe_text((backend.get("thinking") or {}).get("type")),
        "estimated_cost": estimated_cost,
        "cost_formula": cost_formula,
        "cost_status": cost_status,
        "go_no_go_criteria": [
            "dataset leakage gate passed",
            "exemplar leakage gate passed",
            f"planned_request_count = {planned_request_count}",
            "G5 only runs on synthetic_multi",
            "prompt rendering completed",
            "no unexpected truncation",
            "cache works",
            "resume works",
            "evaluation schema works",
            "API key absent from logs and metadata",
        ],
    }
    if write_reports:
        json_path = "reports/real_api_probe_execution_plan.json" if is_probe else "reports/real_api_canary_execution_plan.json"
        md_path = "reports/real_api_probe_execution_plan.md" if is_probe else "reports/real_api_canary_execution_plan.md"
        write_json(repo_path(json_path), report)
        _write_markdown(report, repo_path(md_path))
    return report


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    title = "Real API Probe Execution Plan" if "probe" in report["schema_version"] else "Real API Canary Execution Plan"
    lines = [
        f"# {title}",
        "",
        f"- Provider: `{report['provider']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Model: `{report['model']}`",
        f"- Sample count: `{report['sample_count']}`",
        f"- Planned request count: `{report['planned_request_count']}`",
        f"- Strategy distribution: `{report['strategy_distribution']}`",
        f"- Estimated input tokens: `{report['estimated_input_tokens_total']}`",
        f"- Estimated output tokens: `{report['estimated_output_tokens_total']}`",
        f"- Estimated cost: `{report['estimated_cost']}`",
        f"- Cost status: `{report['cost_status']}`",
        f"- Cache path: `{report['cache_path']}`",
        f"- Output root: `{report['output_root']}`",
        "",
        "## Go / No-Go Criteria",
        "",
    ]
    lines.extend(f"- {item}" for item in report["go_no_go_criteria"])
    lines.extend(
        [
            "",
            "This Canary/Probe validates protocol and runtime stability only. It is not evidence for paper-level generation quality.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_canary.mock.json")
    parser.add_argument("--output-root")
    args = parser.parse_args()
    cfg = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    report = estimate_canary_cost(cfg, repo_path(args.output_root) if args.output_root else None)
    print(json.dumps({"planned_request_count": report["planned_request_count"], "estimated_cost": report["estimated_cost"]}, indent=2))


if __name__ == "__main__":
    main()
