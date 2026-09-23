#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiment_tooling_common import load_json, recursive_redact, redact_argv, utc_now_iso, write_json, write_markdown


def _build_difficulty_and_realism_summary(metrics: dict[str, Any], run_metadata: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    difficulty = dict(metrics.get("difficulty_realism", {}) or {})
    runtime_cfg = dict(run_metadata.get("difficulty_realism", {}) or {})
    if not difficulty:
        warnings.append("difficulty_realism_summary_missing")
        return {
            "status": "missing",
            "tau_realism_low": runtime_cfg.get("tau_realism_low"),
            "tau_realism_low_source": runtime_cfg.get("tau_realism_low_source"),
            "level_a_b_route_status": runtime_cfg.get("level_a_b_route_status", "schema_ready_route_not_implemented"),
        }
    realism_score = dict(difficulty.get("realism_score", {}) or {})
    return {
        "status": "available",
        "difficulty_level_counts": dict(difficulty.get("difficulty_level_counts", {}) or {}),
        "intent_cardinality_counts": dict(difficulty.get("intent_cardinality_counts", {}) or {}),
        "structure_pattern_counts": dict(difficulty.get("structure_pattern_counts", {}) or {}),
        "construction_route_counts": dict(difficulty.get("construction_route_counts", {}) or {}),
        "realism_score": realism_score,
        "rho": dict(difficulty.get("rho", {}) or {}),
        "identifier_overlap_score": dict(difficulty.get("identifier_overlap_score", {}) or {}),
        "dependency_hint_score": dict(difficulty.get("dependency_hint_score", {}) or {}),
        "main_topic_coherence": dict(difficulty.get("main_topic_coherence", {}) or {}),
        "shared_file_ratio": dict(difficulty.get("shared_file_ratio", {}) or {}),
        "tau_realism_low": realism_score.get("tau_low", runtime_cfg.get("tau_realism_low")),
        "tau_realism_low_source": runtime_cfg.get("tau_realism_low_source", ""),
        "realism_weight_formula": difficulty.get("realism_weight_formula", ""),
        "realism_weight_config": dict(difficulty.get("realism_weight_config", {}) or {}),
        "pipeline_owner": difficulty.get("pipeline_owner", runtime_cfg.get("pipeline_owner", "")),
        "pipeline_order": list(difficulty.get("pipeline_order", runtime_cfg.get("pipeline_order", [])) or []),
        "level_a_b_route_status": runtime_cfg.get("level_a_b_route_status", "schema_ready_route_not_implemented"),
    }


def _build_fewshot_audit_section(fewshot_audit: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any]:
    if not fewshot_audit:
        warnings.append("fewshot_audit_report_missing")
        return {"status": "not_provided", "passed": None, "blockers": [], "warnings": []}
    audit_payload = dict(fewshot_audit.get("audit", {}) or {})
    retrieval_probe = dict(fewshot_audit.get("retrieval_probe", audit_payload.get("probe_summary", {}) or {}) or {})
    row_counts = dict(fewshot_audit.get("row_counts", {}) or {})
    return {
        "status": "provided",
        "passed": bool(fewshot_audit.get("passed", fewshot_audit.get("audit_pass", False))),
        "pool_path": fewshot_audit.get("db_path", fewshot_audit.get("pool_path", "")),
        "examples_count": audit_payload.get("total_examples", row_counts.get("raw_rows")),
        "verified_examples": audit_payload.get("verified_examples", row_counts.get("eligible_rows")),
        "blockers": list(audit_payload.get("blockers", []) or []),
        "warnings": list(audit_payload.get("warnings", []) or []),
        "probe_summary": {
            "retrieval_status": retrieval_probe.get("retrieval_status", ""),
            "retrieval_result_count": retrieval_probe.get("retrieval_result_count", 0),
            "few_shot_source": retrieval_probe.get("few_shot_source", ""),
        },
        "raw": fewshot_audit,
    }


def build_experiment_report(
    *,
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    run_metadata: dict[str, Any] | None,
    gate_report: dict[str, Any] | None,
    fewshot_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    run_metadata = recursive_redact(run_metadata or {})
    gate_report = recursive_redact(gate_report or {})
    fewshot_audit = recursive_redact(fewshot_audit or {})
    warnings = list(metrics.get("warnings", []))
    if not gate_report:
        warnings.append("message_gate_report_missing")

    run_blockers = list((manifest.get("protocol", {}) or {}).get("blockers", []))
    limitations = list(run_blockers)
    fewshot_pool_audit = _build_fewshot_audit_section(fewshot_audit or None, warnings)
    if fewshot_pool_audit["status"] == "provided" and not bool(fewshot_pool_audit.get("passed", False)):
        limitations.append("fewshot_audit_not_passed")
    if run_metadata.get("run_purpose") != "formal":
        limitations.append("non_formal_run")

    difficulty_and_realism_summary = _build_difficulty_and_realism_summary(metrics, run_metadata, warnings)
    report = {
        "report_version": "step2_experiment_report_v1",
        "generated_at_utc": utc_now_iso(),
        "run_identity": {
            "run_id": ((manifest.get("run", {}) or {}).get("run_id")),
            "run_purpose": ((manifest.get("run", {}) or {}).get("run_purpose")),
            "git_commit": ((manifest.get("git", {}) or {}).get("commit")),
            "git_branch": ((manifest.get("git", {}) or {}).get("branch")),
            "config_hash": (((manifest.get("inputs", {}) or {}).get("config", {}) or {}).get("sha256")),
            "source_hash": (((manifest.get("inputs", {}) or {}).get("source_data", {}) or {}).get("sha256")),
            "fewshot_pool_hash": (((manifest.get("inputs", {}) or {}).get("fewshot_pool", {}) or {}).get("sha256")),
            "created_at_utc": manifest.get("created_at_utc"),
        },
        "protocol_status": {
            "paper_valid": bool((manifest.get("protocol", {}) or {}).get("run_valid_for_paper", False)),
            "formal_assets_ready": bool((manifest.get("protocol", {}) or {}).get("formal_assets_ready", False)),
            "blockers": run_blockers,
            "message_stage_mandatory": bool((manifest.get("protocol", {}) or {}).get("message_stage_mandatory", False)),
            "message_gate_mandatory": bool((manifest.get("protocol", {}) or {}).get("message_gate_mandatory", False)),
            "few_shot_mandatory": bool((manifest.get("protocol", {}) or {}).get("few_shot_mandatory", False)),
            "message_gate_passed": (gate_report or (run_metadata.get("message_gate") or {})).get("message_gate_passed"),
            "message_gate_reason": (gate_report or (run_metadata.get("message_gate") or {})).get("reason"),
        },
        "data_and_inputs": manifest.get("inputs", {}),
        "generation_and_gate_summary": {
            "counts": metrics.get("counts", {}),
            "rates": metrics.get("rates", {}),
            "gate_report_present": bool(gate_report),
            "gate_passed": (gate_report or (run_metadata.get("message_gate") or {})).get("message_gate_passed"),
        },
        "failure_taxonomy": {
            "precheck_skip": (metrics.get("counts", {}) or {}).get("precheck_skip", 0),
            "generation_api_failure": (metrics.get("counts", {}) or {}).get("generation_failed", 0),
            "fewshot_failure": (metrics.get("fewshot", {}) or {}).get("failed_count", 0),
            "judge_scoring_failure": (metrics.get("counts", {}) or {}).get("judge_failed", 0),
            "quality_reject": (metrics.get("counts", {}) or {}).get("true_message_reject", 0),
            "errors_by_code": ((metrics.get("errors", {}) or {}).get("by_error_code", {})),
        },
        "quality_metrics": metrics.get("quality", {}),
        "difficulty_and_realism_summary": difficulty_and_realism_summary,
        "reproducibility_notes": {
            "random_seed": ((manifest.get("run", {}) or {}).get("random_seed")),
            "config_path": ((manifest.get("run", {}) or {}).get("config_path")),
            "output_dir": ((manifest.get("run", {}) or {}).get("output_dir")),
            "argv": redact_argv(list(run_metadata.get("argv", []))) if isinstance(run_metadata.get("argv"), list) else [],
            "python_version": run_metadata.get("python_version"),
            "formal_protocol_version": run_metadata.get("formal_protocol_version"),
        },
        "fewshot_pool_audit": fewshot_pool_audit,
        "limitations": limitations,
        "warnings": warnings,
    }
    return recursive_redact(report)


def render_markdown(report: dict[str, Any]) -> str:
    identity = report["run_identity"]
    protocol = report["protocol_status"]
    generation = report["generation_and_gate_summary"]
    failure = report["failure_taxonomy"]
    quality = report["quality_metrics"]
    difficulty = report["difficulty_and_realism_summary"]
    fewshot = report["fewshot_pool_audit"]
    repro = report["reproducibility_notes"]
    lines = [
        "# Experiment Report",
        "",
        "## Run Identity",
        f"- run_id: `{identity.get('run_id')}`",
        f"- run_purpose: `{identity.get('run_purpose')}`",
        f"- git_commit: `{identity.get('git_commit')}`",
        f"- git_branch: `{identity.get('git_branch')}`",
        f"- config_hash: `{identity.get('config_hash')}`",
        f"- source_hash: `{identity.get('source_hash')}`",
        f"- fewshot_pool_hash: `{identity.get('fewshot_pool_hash')}`",
        f"- created_at_utc: `{identity.get('created_at_utc')}`",
        "",
        "## Protocol Status",
        f"- paper_valid: `{int(bool(protocol.get('paper_valid')))} `",
        f"- formal_assets_ready: `{int(bool(protocol.get('formal_assets_ready')))} `",
        f"- blockers: `{json.dumps(protocol.get('blockers', []), ensure_ascii=False)}`",
        f"- message_stage_mandatory: `{int(bool(protocol.get('message_stage_mandatory')))} `",
        f"- message_gate_mandatory: `{int(bool(protocol.get('message_gate_mandatory')))} `",
        f"- few_shot_mandatory: `{int(bool(protocol.get('few_shot_mandatory')))} `",
        f"- gate_passed: `{protocol.get('message_gate_passed')}`",
        f"- gate_reason: `{protocol.get('message_gate_reason')}`",
        "",
        "## Data and Inputs",
        f"- source_data: `{json.dumps((report.get('data_and_inputs', {}) or {}).get('source_data', {}), ensure_ascii=False)}`",
        f"- fewshot_pool: `{json.dumps((report.get('data_and_inputs', {}) or {}).get('fewshot_pool', {}), ensure_ascii=False)}`",
        f"- config: `{json.dumps((report.get('data_and_inputs', {}) or {}).get('config', {}), ensure_ascii=False)}`",
        "",
        "## Generation and Gate Summary",
        f"- counts: `{json.dumps(generation.get('counts', {}), ensure_ascii=False)}`",
        f"- rates: `{json.dumps(generation.get('rates', {}), ensure_ascii=False)}`",
        f"- gate_report_present: `{int(bool(generation.get('gate_report_present')))} `",
        f"- gate_passed: `{generation.get('gate_passed')}`",
        "",
        "## Failure Taxonomy",
        f"- precheck_skip: `{failure.get('precheck_skip')}`",
        f"- generation_api_failure: `{failure.get('generation_api_failure')}`",
        f"- fewshot_failure: `{failure.get('fewshot_failure')}`",
        f"- judge_scoring_failure: `{failure.get('judge_scoring_failure')}`",
        f"- quality_reject: `{failure.get('quality_reject')}`",
        f"- errors_by_code: `{json.dumps(failure.get('errors_by_code', {}), ensure_ascii=False)}`",
        "",
        "## Quality Metrics",
        f"- quality: `{json.dumps(quality, ensure_ascii=False)}`",
        "",
        "## Difficulty and Realism Summary",
        f"- status: `{difficulty.get('status')}`",
        f"- difficulty_level_counts: `{json.dumps(difficulty.get('difficulty_level_counts', {}), ensure_ascii=False)}`",
        f"- intent_cardinality_counts: `{json.dumps(difficulty.get('intent_cardinality_counts', {}), ensure_ascii=False)}`",
        f"- structure_pattern_counts: `{json.dumps(difficulty.get('structure_pattern_counts', {}), ensure_ascii=False)}`",
        f"- construction_route_counts: `{json.dumps(difficulty.get('construction_route_counts', {}), ensure_ascii=False)}`",
        f"- realism_score: `{json.dumps(difficulty.get('realism_score', {}), ensure_ascii=False)}`",
        f"- rho: `{json.dumps(difficulty.get('rho', {}), ensure_ascii=False)}`",
        f"- tau_realism_low: `{difficulty.get('tau_realism_low')}`",
        f"- tau_realism_low_source: `{difficulty.get('tau_realism_low_source')}`",
        f"- realism_weight_formula: `{difficulty.get('realism_weight_formula')}`",
        f"- realism_weight_config: `{json.dumps(difficulty.get('realism_weight_config', {}), ensure_ascii=False)}`",
        f"- pipeline_owner: `{difficulty.get('pipeline_owner')}`",
        f"- pipeline_order: `{json.dumps(difficulty.get('pipeline_order', []), ensure_ascii=False)}`",
        f"- level_a_b_route_status: `{difficulty.get('level_a_b_route_status')}`",
        "",
        "## Few-shot Pool Audit",
        f"- status: `{fewshot.get('status')}`",
        f"- passed: `{fewshot.get('passed')}`",
        f"- pool_path: `{fewshot.get('pool_path', '')}`",
        f"- examples_count: `{fewshot.get('examples_count')}`",
        f"- verified_examples: `{fewshot.get('verified_examples')}`",
        f"- blockers: `{json.dumps(fewshot.get('blockers', []), ensure_ascii=False)}`",
        f"- warnings: `{json.dumps(fewshot.get('warnings', []), ensure_ascii=False)}`",
        f"- probe_summary: `{json.dumps(fewshot.get('probe_summary', {}), ensure_ascii=False)}`",
        "",
        "## Reproducibility Notes",
        f"- random_seed: `{repro.get('random_seed')}`",
        f"- config_path: `{repro.get('config_path')}`",
        f"- output_dir: `{repro.get('output_dir')}`",
        f"- argv: `{json.dumps(repro.get('argv', []), ensure_ascii=False)}`",
        f"- python_version: `{repro.get('python_version')}`",
        f"- formal_protocol_version: `{repro.get('formal_protocol_version')}`",
        "",
        "## Limitations / Blockers",
        f"- limitations: `{json.dumps(report.get('limitations', []), ensure_ascii=False)}`",
        f"- warnings: `{json.dumps(report.get('warnings', []), ensure_ascii=False)}`",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a paper-style offline experiment report for one Step2 run.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--run-metadata", required=True)
    parser.add_argument("--gate-report", default="")
    parser.add_argument("--fewshot-audit-report", default="")
    parser.add_argument("--fewshot-audit", default="", help=argparse.SUPPRESS)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--out-json", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_json(Path(args.manifest))
    metrics = load_json(Path(args.metrics))
    run_metadata = load_json(Path(args.run_metadata))
    gate_report = load_json(Path(args.gate_report)) if args.gate_report and Path(args.gate_report).exists() else None
    fewshot_path = args.fewshot_audit_report or args.fewshot_audit
    fewshot_audit = load_json(Path(fewshot_path)) if fewshot_path and Path(fewshot_path).exists() else None
    report = build_experiment_report(
        manifest=manifest,
        metrics=metrics,
        run_metadata=run_metadata,
        gate_report=gate_report,
        fewshot_audit=fewshot_audit,
    )
    write_json(Path(args.out_json), report)
    write_markdown(Path(args.out_md), render_markdown(report))


if __name__ == "__main__":
    main()
