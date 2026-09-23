from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, rel_path, repo_path, utc_timestamp, write_json


def evaluate_probe_go_no_go(
    *,
    probe_result_json: Path,
    manual_review_validation_json: Path,
    preflight_json: Path | None = None,
    reports_root: Path = repo_path("reports"),
    report_timestamp: str | None = None,
    require_manual_count: int | None = None,
) -> dict[str, Any]:
    report_timestamp = report_timestamp or utc_timestamp()
    probe_result = read_json(probe_result_json)
    manual_validation = read_json(manual_review_validation_json)
    preflight_json = preflight_json or _find_preflight_report(reports_root)
    preflight = read_json(preflight_json)

    manual_count_gate = _as_int(manual_validation.get("expected_record_count"), 0) == int(require_manual_count) if require_manual_count else True
    failed_gates = {
        "preflight_passed": bool(preflight.get("passed")) is True,
        "completed_request_count": _as_int(probe_result.get("completed_request_count"), 0) == 5,
        "failed_request_count": _as_int(probe_result.get("failed_request_count"), 0) == 0,
        "api_success_rate": _as_float(probe_result.get("api_success_rate"), 0.0) == 1.0,
        "parse_success_rate": _as_float(probe_result.get("parse_success_rate"), 0.0) == 1.0,
        "empty_output_rate": _as_float(probe_result.get("empty_output_rate"), 1.0) == 0.0,
        "single_line_rate": _as_float(probe_result.get("single_line_rate"), 0.0) >= 0.8,
        "key_leakage_detected": bool(probe_result.get("key_leakage_detected")) is False,
        "cache_works": _as_int(probe_result.get("cache_hit_count"), 0) >= 5,
        "resume_works": _as_int(probe_result.get("new_real_request_count"), -1) == 0 and _as_int(probe_result.get("resume_skip_count"), 0) >= 5,
        "manual_review_completed": bool(manual_validation.get("manual_review_completed")) is True,
        "manual_expected_record_count": manual_count_gate,
        "manual_format_ok_rate": _as_float(manual_validation.get("manual_format_ok_rate"), 0.0) >= 0.8,
        "manual_faithful_rate": _as_float(manual_validation.get("faithful_rate"), 0.0) >= 0.8,
        "manual_complete_rate": _as_float(manual_validation.get("complete_rate"), 0.0) >= 0.8,
        "manual_hallucination_rate": _as_float(manual_validation.get("hallucination_rate"), 1.0) <= 0.2,
        "prompt_defect_count": _as_int(manual_validation.get("prompt_defect_count"), 999) == 0,
    }
    recommend = all(failed_gates.values())
    if not failed_gates["manual_review_completed"]:
        reason = "manual_review_incomplete"
    elif not failed_gates["prompt_defect_count"]:
        reason = "prompt_revision_required"
    elif recommend:
        reason = "all_gates_passed"
    else:
        reason = "quality_gate_failed"
    report = {
        "schema_version": "real_api_probe_go_no_go_v1",
        "report_timestamp": report_timestamp,
        "probe_result_json": rel_path(probe_result_json),
        "manual_review_validation_json": rel_path(manual_review_validation_json),
        "preflight_json": rel_path(preflight_json),
        "preflight_passed": bool(preflight.get("passed")) is True,
        "cache_works": failed_gates["cache_works"],
        "resume_works": failed_gates["resume_works"],
        "failed_gates": failed_gates,
        "recommend_65_request_canary": recommend,
        "reason": reason,
        "notes": "The 5-request real API probe is a protocol gate only, not a paper-quality evaluation.",
    }
    json_path = reports_root / f"real_api_probe_go_no_go_{report_timestamp}.json"
    md_path = reports_root / f"real_api_probe_go_no_go_{report_timestamp}.md"
    report["report_json_path"] = rel_path(json_path)
    report["report_md_path"] = rel_path(md_path)
    write_json(json_path, report)
    _write_markdown(report, md_path)
    return report


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _find_preflight_report(reports_root: Path) -> Path:
    candidates = sorted(reports_root.glob("real_api_probe_preflight_*.json"))
    if not candidates:
        raise FileNotFoundError("No real_api_probe_preflight_*.json report found")
    return candidates[-1]


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real API Probe Go / No-Go",
        "",
        f"- Probe result JSON: `{report['probe_result_json']}`",
        f"- Manual review validation JSON: `{report['manual_review_validation_json']}`",
        f"- Preflight JSON: `{report['preflight_json']}`",
        f"- Preflight passed: `{report['preflight_passed']}`",
        f"- Cache works: `{report['cache_works']}`",
        f"- Resume works: `{report['resume_works']}`",
        f"- Recommend 65-request Canary: `{report['recommend_65_request_canary']}`",
        f"- Reason: `{report['reason']}`",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in report["failed_gates"].items())
    lines.extend(["", report["notes"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-result-json", required=True)
    parser.add_argument("--manual-review-validation-json", required=True)
    parser.add_argument("--preflight-json")
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--require-manual-count", type=int)
    args = parser.parse_args()
    report = evaluate_probe_go_no_go(
        probe_result_json=repo_path(args.probe_result_json),
        manual_review_validation_json=repo_path(args.manual_review_validation_json),
        preflight_json=repo_path(args.preflight_json) if args.preflight_json else None,
        reports_root=repo_path(args.reports_root),
        require_manual_count=args.require_manual_count,
    )
    print(
        json.dumps(
            {
                "recommend_65_request_canary": report["recommend_65_request_canary"],
                "reason": report["reason"],
                "report_json_path": report["report_json_path"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
