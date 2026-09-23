from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, rel_path, repo_path, safe_text, utc_timestamp, write_csv, write_json
from estimate_generation_canary_cost import estimate_canary_cost
from llm_backend import LLMBackend
from run_generation_pilot import run_generation_pilot


INPUT_PRICE_PER_1M = 0.14
OUTPUT_PRICE_PER_1M = 0.28
PREFLIGHT_SYSTEM = "You write concise Git commit subjects."
PREFLIGHT_USER = "Output exactly one short commit subject for a change that fixes a null check."


class ProbeBlockedError(RuntimeError):
    pass


def require_deepseek_probe_config(config: dict[str, Any]) -> dict[str, Any]:
    backend = dict(config.get("backend", {}))
    required = {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
    }
    for key, expected in required.items():
        actual = safe_text(backend.get(key))
        if actual != expected:
            raise ProbeBlockedError(f"Invalid {key}: expected {expected}, got {actual}")
    if (backend.get("thinking") or {}).get("type") != "disabled":
        raise ProbeBlockedError("DeepSeek probe requires thinking.type=disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise ProbeBlockedError("Missing DEEPSEEK_API_KEY")
    return backend


def _request_json(url: str, *, api_key: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 60) -> tuple[int, dict[str, Any], int]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method=method,
    )
    start = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        status = int(getattr(response, "status", 200))
    return status, payload, int((time.time() - start) * 1000)


def preflight_deepseek_probe(
    config: dict[str, Any],
    reports_dir: Path = repo_path("reports"),
    *,
    report_timestamp: str | None = None,
) -> dict[str, Any]:
    backend = require_deepseek_probe_config(config)
    api_key = os.environ["DEEPSEEK_API_KEY"]
    report_timestamp = report_timestamp or utc_timestamp()
    base_url = safe_text(backend["base_url"]).rstrip("/")
    model = safe_text(backend["model"])
    timeout = int(backend.get("timeout_seconds", 60))
    json_path = reports_dir / f"real_api_probe_preflight_{report_timestamp}.json"
    md_path = reports_dir / f"real_api_probe_preflight_{report_timestamp}.md"
    report: dict[str, Any] = {
        "schema_version": "real_api_probe_preflight_v1",
        "report_timestamp": report_timestamp,
        "provider": safe_text(backend["provider"]),
        "base_url": base_url,
        "model": model,
        "api_key_env": "DEEPSEEK_API_KEY",
        "key_present": True,
        "http_status": 0,
        "available_model_match": False,
        "parse_success": False,
        "content_non_empty": False,
        "single_line": False,
        "latency_ms": 0,
        "usage": {},
        "usage_available": False,
        "thinking_mode": "disabled",
        "key_leakage_detected": False,
        "report_json_path": rel_path(json_path),
        "report_md_path": rel_path(md_path),
        "passed": False,
        "blocker": "",
    }
    try:
        models_status, models_payload, models_latency = _request_json(f"{base_url}/models", api_key=api_key, timeout=timeout)
        model_ids = [safe_text(row.get("id")) for row in models_payload.get("data", []) if isinstance(row, dict)]
        report["models_http_status"] = models_status
        report["models_latency_ms"] = models_latency
        report["available_model_match"] = model in model_ids
        if not report["available_model_match"]:
            report["blocker"] = "deepseek-v4-flash not found in /models"
            _write_preflight_reports(report, json_path, md_path, api_key=api_key)
            return report
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": PREFLIGHT_SYSTEM},
                {"role": "user", "content": PREFLIGHT_USER},
            ],
            "temperature": float(backend.get("temperature", 0.2)),
            "top_p": float(backend.get("top_p", 1.0)),
            "max_tokens": min(int(backend.get("max_output_tokens", 64)), 32),
            "thinking": {"type": "disabled"},
        }
        status, payload, latency = _request_json(f"{base_url}/chat/completions", api_key=api_key, method="POST", body=body, timeout=timeout)
        content = safe_text(payload["choices"][0]["message"]["content"])
        report.update(
            {
                "http_status": status,
                "parse_success": True,
                "content_non_empty": bool(content),
                "single_line": bool(content) and len(content.splitlines()) == 1,
                "latency_ms": latency,
                "usage": payload.get("usage", {}),
                "usage_available": isinstance(payload.get("usage"), dict) and bool(payload.get("usage")),
            }
        )
    except urllib.error.HTTPError as exc:
        report["http_status"] = int(exc.code)
        report["blocker"] = f"HTTP {exc.code}: {safe_text(exc.reason)}"
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        report["blocker"] = safe_text(exc)
    _write_preflight_reports(report, json_path, md_path, api_key=api_key)
    return report


def _write_preflight_reports(report: dict[str, Any], json_path: Path, md_path: Path, *, api_key: str) -> None:
    lines = [
        "# Real API Probe Preflight",
        "",
        f"- Provider: `{report['provider']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Model: `{report['model']}`",
        f"- API key env: `{report['api_key_env']}`",
        f"- Key present: `{report['key_present']}`",
        f"- HTTP status: `{report['http_status']}`",
        f"- Available model match: `{report['available_model_match']}`",
        f"- Parse success: `{report['parse_success']}`",
        f"- Content non-empty: `{report['content_non_empty']}`",
        f"- Single line: `{report['single_line']}`",
        f"- Latency ms: `{report['latency_ms']}`",
        f"- Usage: `{report['usage']}`",
        f"- Usage available: `{report['usage_available']}`",
        f"- Thinking mode: `{report['thinking_mode']}`",
        f"- Key leakage detected: `{report['key_leakage_detected']}`",
        f"- Passed: `{report['passed']}`",
        f"- Blocker: `{report['blocker']}`",
    ]
    report["key_leakage_detected"] = _detect_key_leakage(api_key, report, lines)
    report["passed"] = bool(
        report.get("models_http_status") == 200
        and report["available_model_match"] is True
        and report["http_status"] == 200
        and report["parse_success"] is True
        and report["content_non_empty"] is True
        and report["single_line"] is True
        and report["key_leakage_detected"] is False
    )
    lines[-3] = f"- Key leakage detected: `{report['key_leakage_detected']}`"
    lines[-2] = f"- Passed: `{report['passed']}`"
    write_json(json_path, report)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def estimate_probe_budget(config: dict[str, Any], output_root: Path, *, enforce_cap: bool = True) -> dict[str, Any]:
    report = estimate_canary_cost(config, output_root, write_reports=False)
    input_tokens = int(report["estimated_input_tokens_total"] if isinstance(report["estimated_input_tokens_total"], int) else 0)
    output_tokens = int(report["estimated_output_tokens_total"])
    price = config.get("pricing", {})
    input_price = float(price.get("cache_miss_input_per_1m_tokens", price.get("input_per_1m_tokens", INPUT_PRICE_PER_1M)))
    output_price = float(price.get("output_per_1m_tokens", OUTPUT_PRICE_PER_1M))
    cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    report["estimated_cost"] = cost
    report["estimated_cost_usd"] = cost
    report["cost_status"] = "estimated_from_deepseek_v4_flash_prices"
    report["cost_formula"] = f"{input_tokens} * {input_price} / 1e6 + {output_tokens} * {output_price} / 1e6"
    cap = _probe_budget_cap(config)
    report["probe_budget_cap_usd"] = cap
    if enforce_cap and cost > cap:
        raise ProbeBlockedError(f"Probe budget exceeded: estimated {cost:.6f} USD > cap {cap:.6f} USD")
    return report


def prepare_probe_execution_plan(config: dict[str, Any], output_root: Path, *, reports_root: Path = repo_path("reports")) -> dict[str, Any]:
    planning_root = output_root / "_planning"
    dry_run_result = run_generation_pilot(config, output_root=planning_root, allow_real_api=True, dry_run=True)
    report = estimate_probe_budget(config, planning_root, enforce_cap=False)
    report["output_root"] = rel_path(output_root)
    write_json(reports_root / "real_api_probe_execution_plan.json", report)
    _write_execution_plan_markdown(report, reports_root / "real_api_probe_execution_plan.md")
    return {"planning_root": planning_root, "dry_run_result": dry_run_result, "report": report}


def write_probe_result_report(
    config: dict[str, Any],
    output_root: Path,
    *,
    run_kind: str = "real",
    previous_generation_count: int = 0,
    cache_hit_count_override: int | None = None,
    reports_root: Path = repo_path("reports"),
    report_timestamp: str | None = None,
) -> dict[str, Any]:
    rows = read_jsonl(output_root / "generations" / run_kind / "generation_outputs.jsonl")
    report_timestamp = report_timestamp or utc_timestamp()
    statuses = [safe_text(row.get("status")) for row in rows]
    successes = [row for row in rows if row.get("status") == "generated"]
    latencies = sorted(int(row.get("latency_ms", 0)) for row in successes)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    usage_available = bool(rows) and len(successes) == len(rows) and all(
        isinstance((row.get("usage") or {}).get("prompt_tokens"), int) and isinstance((row.get("usage") or {}).get("completion_tokens"), int)
        for row in successes
    )
    input_tokens = sum(int((row.get("usage") or {}).get("prompt_tokens", 0)) for row in successes) if usage_available else "not_available"
    output_tokens = sum(int((row.get("usage") or {}).get("completion_tokens", 0)) for row in successes) if usage_available else "not_available"
    estimated_cost = ((input_tokens * INPUT_PRICE_PER_1M + output_tokens * OUTPUT_PRICE_PER_1M) / 1_000_000) if usage_available else "not_available"
    strategy_distribution = _count_by(rows, "strategy")
    sample_rows = {row["sample_id"]: row for row in read_jsonl(output_root / "dataset" / "canary_all.jsonl")}
    retrieval_logs = read_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl")
    category_distribution: dict[str, int] = {}
    manual_rows: list[dict[str, Any]] = []
    for row in rows:
        sample = sample_rows.get(row["sample_id"], {})
        category = safe_text(sample.get("data_category"))
        category_distribution[category] = category_distribution.get(category, 0) + 1
        manual_rows.append(
            {
                "sample_id": row.get("sample_id", ""),
                "data_category": category,
                "strategy": row.get("strategy", ""),
                "generated_subject": row.get("generated_subject", ""),
                "reference_subject": sample.get("subject_reference", ""),
                "manual_format_ok": "",
                "manual_faithful": "",
                "manual_complete": "",
                "manual_concise": "",
                "manual_oversegmentation": "",
                "manual_omission": "",
                "manual_hallucination": "",
                "notes": "",
            }
        )
    retrieval_quality_summary = _summarize_retrieval_quality(retrieval_logs)
    leakage_summary = _summarize_retrieval_leakage(retrieval_logs)
    report = {
        "schema_version": "real_api_probe_result_v1",
        "report_timestamp": report_timestamp,
        "probe_valid": False,
        "invalidated_by_repo_leakage": False,
        "planned_request_count": 5,
        "completed_request_count": len(successes),
        "failed_request_count": len([status for status in statuses if status == "failed"]),
        "api_success_rate": len(successes) / len(rows) if rows else 0.0,
        "parse_success_rate": len(successes) / len(rows) if rows else 0.0,
        "empty_output_rate": len([row for row in rows if not safe_text(row.get("generated_subject"))]) / len(rows) if rows else 0.0,
        "single_line_rate": len([row for row in rows if safe_text(row.get("generated_subject")) and len(safe_text(row.get("generated_subject")).splitlines()) == 1]) / len(rows) if rows else 0.0,
        "artifact_rate": len([row for row in rows if _has_artifact(row.get("generated_subject", ""))]) / len(rows) if rows else 0.0,
        "retry_count": sum(int(row.get("retry_count", 0)) for row in rows),
        "timeout_count": len([row for row in rows if "timeout" in safe_text(row.get("failure_reason")).lower()]),
        "cache_hit_count": cache_hit_count_override if cache_hit_count_override is not None else len([row for row in rows if row.get("cache_hit") is True]),
        "resume_skip_count": max(0, previous_generation_count),
        "new_real_request_count": max(0, len(rows) - previous_generation_count),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p90_ms": _percentile(latencies, 0.9),
        "actual_usage_available": usage_available,
        "actual_input_tokens_total": input_tokens,
        "actual_output_tokens_total": output_tokens,
        "estimated_actual_cost_usd": estimated_cost,
        "strategy_distribution": strategy_distribution,
        "category_distribution": category_distribution,
        "thinking_mode": "disabled",
        "key_leakage_detected": False,
        "same_repo_canonical_any": leakage_summary["same_repo_canonical_any"],
        "source_sha_overlap_any": leakage_summary["source_sha_overlap_any"],
        "diff_fingerprint_overlap_any": leakage_summary["diff_fingerprint_overlap_any"],
        "normalized_subject_overlap_any": leakage_summary["normalized_subject_overlap_any"],
        "retrieval_quality_summary": retrieval_quality_summary,
        "low_similarity_warning_count": retrieval_quality_summary["low_similarity_warning_count"],
        "manual_review_completed": bool(config.get("manual_review_completed", False)),
        "recommend_65_request_canary": False,
    }
    result_json_path = reports_root / f"real_api_probe_result_{report_timestamp}.json"
    result_md_path = reports_root / f"real_api_probe_result_{report_timestamp}.md"
    manual_review_path = reports_root / f"real_api_probe_manual_review_{report_timestamp}.csv"
    report["report_json_path"] = rel_path(result_json_path)
    report["report_md_path"] = rel_path(result_md_path)
    report["manual_review_path"] = rel_path(manual_review_path)
    report["key_leakage_detected"] = _detect_key_leakage(api_key, report, manual_rows)
    automatic_gate_passed = bool(
        report["completed_request_count"] == 5
        and report["failed_request_count"] == 0
        and report["api_success_rate"] == 1.0
        and report["parse_success_rate"] == 1.0
        and report["empty_output_rate"] == 0
        and report["single_line_rate"] >= 0.8
        and report["key_leakage_detected"] is False
        and report["same_repo_canonical_any"] is False
        and report["source_sha_overlap_any"] is False
        and report["diff_fingerprint_overlap_any"] is False
        and report["normalized_subject_overlap_any"] is False
    )
    report["probe_valid"] = automatic_gate_passed
    report["automatic_gate_passed"] = automatic_gate_passed
    report["manual_review_completed"] = False
    report["recommend_65_request_canary"] = False
    report["reason"] = "pending_manual_review"
    report["recommend_65_request_canary"] = bool(
        False
    )
    write_json(result_json_path, report)
    _write_result_markdown(report, result_md_path)
    write_csv(manual_review_path, manual_rows)
    write_csv(output_root / "reports" / f"real_api_probe_manual_review_{report_timestamp}.csv", manual_rows)
    return report


def run_real_api_probe_with_preflight(
    config: dict[str, Any],
    output_root: Path | None = None,
    *,
    skip_preflight: bool = False,
    reports_root: Path = repo_path("reports"),
) -> dict[str, Any]:
    run_timestamp = utc_timestamp()
    output_root = output_root or repo_path(config.get("output_root") or f"outputs/llm_generation_real_api_probe_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
    output_root.mkdir(parents=True, exist_ok=True)
    previous_generation_count = 0
    out_path = output_root / "generations" / "real" / "generation_outputs.jsonl"
    if out_path.exists():
        previous_generation_count = len(read_jsonl(out_path))
    if not skip_preflight:
        preflight = preflight_deepseek_probe(config, reports_dir=reports_root, report_timestamp=run_timestamp)
        if not preflight.get("passed"):
            raise ProbeBlockedError(safe_text(preflight.get("blocker")) or "preflight failed")
    plan = prepare_probe_execution_plan(config, output_root, reports_root=reports_root)
    budget = dict(plan["report"])
    if float(budget["estimated_cost_usd"]) > _probe_budget_cap(config):
        raise ProbeBlockedError("estimated probe budget exceeded cap")
    if int(budget["planned_request_count"]) != 5:
        raise ProbeBlockedError(f"planned_request_count must be 5, got {budget['planned_request_count']}")
    result = run_generation_pilot(config, output_root=output_root, allow_real_api=True, dry_run=False)
    cache_hit_count_override = _count_cached_prompts(config, output_root) if previous_generation_count > 0 else None
    result_report = write_probe_result_report(
        config,
        output_root,
        previous_generation_count=previous_generation_count,
        cache_hit_count_override=cache_hit_count_override,
        reports_root=reports_root,
        report_timestamp=run_timestamp,
    )
    if result_report["estimated_actual_cost_usd"] != "not_available" and float(result_report["estimated_actual_cost_usd"]) > _probe_budget_cap(config):
        raise ProbeBlockedError("actual estimated probe cost exceeded budget cap")
    return {
        "output_root": output_root,
        "dry_run": plan["dry_run_result"],
        "result": result,
        "metadata": result.get("metadata", {}),
        "report_timestamp": run_timestamp,
        "budget": budget,
        "result_report": result_report,
    }


def _write_result_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real API Probe Result",
        "",
        f"- Probe valid: `{report['probe_valid']}`",
        f"- Invalidated by repo leakage: `{report['invalidated_by_repo_leakage']}`",
        f"- Planned request count: `{report['planned_request_count']}`",
        f"- Completed request count: `{report['completed_request_count']}`",
        f"- Failed request count: `{report['failed_request_count']}`",
        f"- API success rate: `{report['api_success_rate']}`",
        f"- Single-line rate: `{report['single_line_rate']}`",
        f"- Retry count: `{report['retry_count']}`",
        f"- Cache hit count: `{report['cache_hit_count']}`",
        f"- Resume skip count: `{report['resume_skip_count']}`",
        f"- Actual usage available: `{report['actual_usage_available']}`",
        f"- Actual input tokens total: `{report['actual_input_tokens_total']}`",
        f"- Actual output tokens total: `{report['actual_output_tokens_total']}`",
        f"- Estimated actual cost USD: `{report['estimated_actual_cost_usd']}`",
        f"- Strategy distribution: `{report['strategy_distribution']}`",
        f"- Category distribution: `{report['category_distribution']}`",
        f"- Thinking mode: `{report['thinking_mode']}`",
        f"- Key leakage detected: `{report['key_leakage_detected']}`",
        f"- same_repo_canonical_any: `{report['same_repo_canonical_any']}`",
        f"- source_sha_overlap_any: `{report['source_sha_overlap_any']}`",
        f"- diff_fingerprint_overlap_any: `{report['diff_fingerprint_overlap_any']}`",
        f"- normalized_subject_overlap_any: `{report['normalized_subject_overlap_any']}`",
        f"- Retrieval quality summary: `{report['retrieval_quality_summary']}`",
        f"- Low similarity warning count: `{report['low_similarity_warning_count']}`",
        f"- Automatic gate passed: `{report['automatic_gate_passed']}`",
        f"- Manual review completed: `{report['manual_review_completed']}`",
        f"- Recommend 65-request Canary: `{report['recommend_65_request_canary']}`",
        f"- Reason: `{report['reason']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_execution_plan_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real API Probe Execution Plan",
        "",
        f"- Provider: `{report['provider']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Model: `{report['model']}`",
        f"- Planned request count: `{report['planned_request_count']}`",
        f"- Estimated input tokens: `{report['estimated_input_tokens_total']}`",
        f"- Estimated output tokens: `{report['estimated_output_tokens_total']}`",
        f"- Estimated cost USD: `{report['estimated_cost_usd']}`",
        f"- Cache path: `{report['cache_path']}`",
        f"- Output root: `{report['output_root']}`",
        f"- Thinking mode: `{report['thinking_mode']}`",
        f"- Probe budget cap USD: `{report['probe_budget_cap_usd']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = safe_text(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return values[index]


def _has_artifact(text: str) -> bool:
    lowered = safe_text(text).lower()
    return any(marker in lowered for marker in ["change 1", "intent 1", "```", "- "])


def _count_cached_prompts(config: dict[str, Any], output_root: Path) -> int:
    backend = LLMBackend(dict(config.get("backend", {})), allow_real_api=True, dry_run=False)
    prompt_rows = read_jsonl(output_root / "prompts_rendered" / "probe_prompts.jsonl")
    count = 0
    for row in prompt_rows:
        raw_prompt = row.get("prompt", "")
        prompt = raw_prompt if isinstance(raw_prompt, str) else str(raw_prompt)
        if backend._cache_key(prompt) in backend.cache:
            count += 1
    return count


def _summarize_retrieval_leakage(logs: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "same_repo_canonical_any": any(bool((log.get("leakage_checks") or {}).get("same_repo_canonical")) for log in logs),
        "source_sha_overlap_any": any(bool((log.get("leakage_checks") or {}).get("source_sha_overlap")) for log in logs),
        "diff_fingerprint_overlap_any": any(bool((log.get("leakage_checks") or {}).get("diff_fingerprint_overlap")) for log in logs),
        "normalized_subject_overlap_any": any(bool((log.get("leakage_checks") or {}).get("normalized_subject_overlap")) for log in logs),
    }


def _summarize_retrieval_quality(logs: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_logs = [log for log in logs if safe_text(log.get("generation_strategy") or log.get("strategy")) in {"G4", "G5"}]
    status_counts: dict[str, int] = {}
    for log in retrieval_logs:
        status = safe_text(log.get("retrieval_quality_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "log_count": len(retrieval_logs),
        "status_counts": status_counts,
        "low_similarity_warning_count": sum(1 for log in retrieval_logs if bool(log.get("low_similarity_warning"))),
    }


def _probe_budget_cap(config: dict[str, Any]) -> float:
    for candidate in [config.get("probe_budget_cap_usd"), config.get("probe_budget_cap"), 0.10]:
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return 0.10


def _detect_key_leakage(api_key: str, *objects: Any) -> bool:
    if not api_key:
        return False
    for obj in objects:
        if isinstance(obj, (dict, list, tuple)):
            text = json.dumps(obj, ensure_ascii=False)
        elif isinstance(obj, str):
            text = obj
        else:
            text = safe_text(obj)
        if api_key in text:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_real_api_probe.template.json")
    parser.add_argument("--output-root")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()
    config = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    if args.preflight_only:
        report = preflight_deepseek_probe(config)
        print(json.dumps({"passed": report["passed"], "blocker": report["blocker"]}, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
        return
    result = run_real_api_probe_with_preflight(
        config,
        output_root=repo_path(args.output_root) if args.output_root else None,
        skip_preflight=args.skip_preflight,
    )
    print(json.dumps({"output_root": rel_path(result["output_root"]), "planned_request_count": result["result_report"]["planned_request_count"]}, indent=2))


if __name__ == "__main__":
    main()
