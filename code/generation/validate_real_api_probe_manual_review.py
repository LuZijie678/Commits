from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from common import read_json, rel_path, repo_path, safe_text, utc_timestamp, write_json


BOOL_FIELDS = {
    "manual_format_ok",
    "manual_faithful",
    "manual_complete",
    "manual_concise",
    "manual_oversegmentation",
    "manual_omission",
    "manual_hallucination",
    "manual_prompt_defect_detected",
    "manual_overall_accept",
}
ALLOWED_FAILURE_CATEGORIES = {
    "format",
    "unfaithful",
    "omission",
    "hallucination",
    "oversegmentation",
    "oracle_copying",
    "retrieval_irrelevant",
    "prompt_defect",
    "other",
    "none",
}


def validate_manual_review(
    *,
    review_csv: Path,
    probe_result_json: Path,
    reports_root: Path = repo_path("reports"),
    report_timestamp: str | None = None,
    expected_record_count: int | None = None,
) -> dict[str, Any]:
    report_timestamp = report_timestamp or utc_timestamp()
    rows = list(csv.DictReader(review_csv.open(encoding="utf-8")))
    probe_result = read_json(probe_result_json)
    errors: list[str] = []
    expected_record_count = int(expected_record_count or probe_result.get("planned_request_count", 5) or 5)
    if len(rows) != expected_record_count:
        errors.append(f"expected {expected_record_count} rows, found {len(rows)}")
    if expected_record_count == int(probe_result.get("planned_request_count", 5) or 5):
        if dict(Counter(row["strategy"] for row in rows)) != dict(probe_result.get("strategy_distribution", {})):
            errors.append("strategy_distribution mismatch with probe result")
        if dict(Counter(row["data_category"] for row in rows)) != dict(probe_result.get("category_distribution", {})):
            errors.append("category_distribution mismatch with probe result")

    reviewed_record_count = 0
    accepted_record_count = 0
    rejected_record_count = 0
    failure_distribution: Counter[str] = Counter()
    true_counts = Counter()
    applicable_counts = {"oracle_copying": 0, "retrieval_reasonable": 0}
    applicable_true_counts = {"oracle_copying": 0, "retrieval_reasonable": 0}
    row_errors: list[str] = []

    for index, row in enumerate(rows, 1):
        row_id = f"row {index} ({row.get('sample_id','?')} / {row.get('strategy','?')})"
        row_complete = True
        for field in BOOL_FIELDS:
            value = safe_text(row.get(field)).lower()
            if value not in {"true", "false"}:
                row_errors.append(f"{row_id}: missing or invalid {field}")
                row_complete = False
        if safe_text(row.get("strategy")) == "G5":
            value = safe_text(row.get("manual_oracle_plan_copying")).lower()
            applicable_counts["oracle_copying"] += 1
            if value not in {"true", "false"}:
                row_errors.append(f"{row_id}: missing manual_oracle_plan_copying")
                row_complete = False
            elif value == "true":
                applicable_true_counts["oracle_copying"] += 1
        elif safe_text(row.get("manual_oracle_plan_copying")).lower() != "not_applicable":
            row_errors.append(f"{row_id}: manual_oracle_plan_copying must be not_applicable outside G5")
            row_complete = False
        if safe_text(row.get("strategy")) in {"G4", "G5"}:
            value = safe_text(row.get("manual_retrieval_example_reasonable")).lower()
            applicable_counts["retrieval_reasonable"] += 1
            if value not in {"true", "false"}:
                row_errors.append(f"{row_id}: missing manual_retrieval_example_reasonable")
                row_complete = False
            elif value == "true":
                applicable_true_counts["retrieval_reasonable"] += 1
        elif safe_text(row.get("manual_retrieval_example_reasonable")).lower() != "not_applicable":
            row_errors.append(f"{row_id}: manual_retrieval_example_reasonable must be not_applicable outside G4/G5")
            row_complete = False
        if not safe_text(row.get("reviewer")):
            row_errors.append(f"{row_id}: reviewer is required")
            row_complete = False
        if not safe_text(row.get("reviewed_at")):
            row_errors.append(f"{row_id}: reviewed_at is required")
            row_complete = False
        if not safe_text(row.get("manual_confidence")):
            row_errors.append(f"{row_id}: manual_confidence is required")
            row_complete = False
        if not safe_text(row.get("manual_failure_category")):
            row_errors.append(f"{row_id}: manual_failure_category is required")
            row_complete = False
        categories = _parse_failure_categories(row, row_id=row_id, errors=row_errors)
        _validate_consistency(row, categories, row_id=row_id, errors=row_errors)
        if row_complete and not any(error.startswith(row_id) for error in row_errors):
            reviewed_record_count += 1
        if safe_text(row.get("manual_overall_accept")).lower() == "true":
            accepted_record_count += 1
        elif safe_text(row.get("manual_overall_accept")).lower() == "false":
            rejected_record_count += 1
        for field in ["manual_format_ok", "manual_faithful", "manual_complete", "manual_concise"]:
            if safe_text(row.get(field)).lower() == "true":
                true_counts[field] += 1
        for field in ["manual_oversegmentation", "manual_omission", "manual_hallucination", "manual_prompt_defect_detected"]:
            if safe_text(row.get(field)).lower() == "true":
                true_counts[field] += 1
        for category in categories:
            failure_distribution[category] += 1

    errors.extend(row_errors)
    manual_review_completed = len(errors) == 0 and reviewed_record_count == expected_record_count
    report = {
        "schema_version": "real_api_probe_manual_review_validation_v1",
        "report_timestamp": report_timestamp,
        "review_csv": rel_path(review_csv),
        "probe_result_json": rel_path(probe_result_json),
        "manual_review_completed": manual_review_completed,
        "reviewed_record_count": reviewed_record_count,
        "expected_record_count": expected_record_count,
        "accepted_record_count": accepted_record_count,
        "rejected_record_count": rejected_record_count,
        "manual_format_ok_rate": true_counts["manual_format_ok"] / expected_record_count if expected_record_count else 0.0,
        "faithful_rate": true_counts["manual_faithful"] / expected_record_count if expected_record_count else 0.0,
        "complete_rate": true_counts["manual_complete"] / expected_record_count if expected_record_count else 0.0,
        "concise_rate": true_counts["manual_concise"] / expected_record_count if expected_record_count else 0.0,
        "oversegmentation_rate": true_counts["manual_oversegmentation"] / expected_record_count if expected_record_count else 0.0,
        "omission_rate": true_counts["manual_omission"] / expected_record_count if expected_record_count else 0.0,
        "hallucination_rate": true_counts["manual_hallucination"] / expected_record_count if expected_record_count else 0.0,
        "oracle_copying_rate": (
            applicable_true_counts["oracle_copying"] / applicable_counts["oracle_copying"]
            if applicable_counts["oracle_copying"]
            else "not_applicable"
        ),
        "retrieval_reasonable_rate": (
            applicable_true_counts["retrieval_reasonable"] / applicable_counts["retrieval_reasonable"]
            if applicable_counts["retrieval_reasonable"]
            else "not_applicable"
        ),
        "prompt_defect_count": true_counts["manual_prompt_defect_detected"],
        "failure_category_distribution": dict(sorted(failure_distribution.items())),
        "errors": errors,
    }
    json_path = reports_root / f"real_api_probe_manual_review_validation_{report_timestamp}.json"
    md_path = reports_root / f"real_api_probe_manual_review_validation_{report_timestamp}.md"
    report["report_json_path"] = rel_path(json_path)
    report["report_md_path"] = rel_path(md_path)
    write_json(json_path, report)
    _write_validation_markdown(report, md_path)
    return report


def _parse_failure_categories(row: dict[str, str], *, row_id: str, errors: list[str]) -> set[str]:
    raw = safe_text(row.get("manual_failure_category"))
    categories = {item.strip() for item in raw.split("|") if item.strip()}
    if not categories:
        return set()
    unknown = sorted(category for category in categories if category not in ALLOWED_FAILURE_CATEGORIES)
    if unknown:
        errors.append(f"{row_id}: unknown manual_failure_category values {unknown}")
    if "none" in categories and len(categories) > 1:
        errors.append(f"{row_id}: manual_failure_category cannot combine none with other values")
    return categories


def _validate_consistency(row: dict[str, str], categories: set[str], *, row_id: str, errors: list[str]) -> None:
    checks = [
        ("manual_format_ok", "format", False),
        ("manual_faithful", "unfaithful", False),
        ("manual_oversegmentation", "oversegmentation", True),
        ("manual_omission", "omission", True),
        ("manual_hallucination", "hallucination", True),
        ("manual_prompt_defect_detected", "prompt_defect", True),
    ]
    for field, category, expect_true in checks:
        value = safe_text(row.get(field)).lower()
        if value not in {"true", "false"}:
            continue
        triggered = value == "true" if expect_true else value == "false"
        if triggered and category not in categories:
            errors.append(f"{row_id}: {field} requires failure category {category}")
        if not triggered and category in categories:
            errors.append(f"{row_id}: failure category {category} conflicts with {field}")
    if safe_text(row.get("manual_complete")).lower() == "false" and "omission" not in categories:
        errors.append(f"{row_id}: manual_complete=false requires omission category")
    oracle_value = safe_text(row.get("manual_oracle_plan_copying")).lower()
    if oracle_value == "true" and "oracle_copying" not in categories:
        errors.append(f"{row_id}: manual_oracle_plan_copying=true requires oracle_copying category")
    if oracle_value in {"false", "not_applicable"} and "oracle_copying" in categories:
        errors.append(f"{row_id}: oracle_copying category conflicts with manual_oracle_plan_copying")
    retrieval_value = safe_text(row.get("manual_retrieval_example_reasonable")).lower()
    if retrieval_value == "false" and "retrieval_irrelevant" not in categories:
        errors.append(f"{row_id}: retrieval_irrelevant category required when manual_retrieval_example_reasonable=false")
    if retrieval_value in {"true", "not_applicable"} and "retrieval_irrelevant" in categories:
        errors.append(f"{row_id}: retrieval_irrelevant category conflicts with manual_retrieval_example_reasonable")
    overall_accept = safe_text(row.get("manual_overall_accept")).lower()
    if overall_accept == "true" and categories != {"none"}:
        errors.append(f"{row_id}: manual_overall_accept=true requires manual_failure_category=none")
    if overall_accept == "false" and (not categories or categories == {"none"}):
        errors.append(f"{row_id}: manual_overall_accept=false requires a non-none failure category")


def _write_validation_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real API Probe Manual Review Validation",
        "",
        f"- Review CSV: `{report['review_csv']}`",
        f"- Probe result JSON: `{report['probe_result_json']}`",
        f"- Manual review completed: `{report['manual_review_completed']}`",
        f"- Reviewed record count: `{report['reviewed_record_count']}` / `{report['expected_record_count']}`",
        f"- Accepted record count: `{report['accepted_record_count']}`",
        f"- Rejected record count: `{report['rejected_record_count']}`",
        f"- manual_format_ok_rate: `{report['manual_format_ok_rate']}`",
        f"- faithful_rate: `{report['faithful_rate']}`",
        f"- complete_rate: `{report['complete_rate']}`",
        f"- concise_rate: `{report['concise_rate']}`",
        f"- oversegmentation_rate: `{report['oversegmentation_rate']}`",
        f"- omission_rate: `{report['omission_rate']}`",
        f"- hallucination_rate: `{report['hallucination_rate']}`",
        f"- oracle_copying_rate: `{report['oracle_copying_rate']}`",
        f"- retrieval_reasonable_rate: `{report['retrieval_reasonable_rate']}`",
        f"- prompt_defect_count: `{report['prompt_defect_count']}`",
        f"- failure_category_distribution: `{report['failure_category_distribution']}`",
        "",
        "## Errors",
        "",
    ]
    if report["errors"]:
        lines.extend(f"- {error}" for error in report["errors"])
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--probe-result-json", required=True)
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--expected-record-count", type=int)
    args = parser.parse_args()
    report = validate_manual_review(
        review_csv=repo_path(args.review_csv),
        probe_result_json=repo_path(args.probe_result_json),
        reports_root=repo_path(args.reports_root),
        expected_record_count=args.expected_record_count,
    )
    print(
        json.dumps(
            {
                "manual_review_completed": report["manual_review_completed"],
                "report_json_path": report["report_json_path"],
                "error_count": len(report["errors"]),
            },
            indent=2,
        )
    )
    if not report["manual_review_completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
