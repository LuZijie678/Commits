from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from build_real_api_probe_review_bundle import MANUAL_REVIEW_FIELDS, load_probe_review_records
from common import rel_path, repo_path, utc_timestamp


def build_combined_probe_review_bundle(
    *,
    base_probe_output_root: Path,
    base_probe_result_json: Path,
    targeted_output_root: Path,
    reports_root: Path = repo_path("reports"),
    report_timestamp: str | None = None,
) -> dict[str, Any]:
    report_timestamp = report_timestamp or utc_timestamp()
    base_records = load_probe_review_records(output_root=base_probe_output_root, probe_result_json=base_probe_result_json)
    targeted_records = load_probe_review_records(output_root=targeted_output_root, probe_result_json=None)
    records = base_records + targeted_records
    bundle_path = reports_root / f"combined_real_api_probe_manual_review_bundle_{report_timestamp}.md"
    form_path = reports_root / f"combined_real_api_probe_manual_review_form_{report_timestamp}.csv"
    _write_bundle(bundle_path, records, base_probe_output_root=base_probe_output_root, targeted_output_root=targeted_output_root)
    _write_form(form_path, records)
    return {"bundle_path": bundle_path, "form_path": form_path, "record_count": len(records)}


def _write_bundle(path: Path, records: list[dict[str, Any]], *, base_probe_output_root: Path, targeted_output_root: Path) -> None:
    lines = [
        "# Combined Real API Probe Manual Review Bundle",
        "",
        f"- Base probe root: `{rel_path(base_probe_output_root)}`",
        f"- Targeted regression root: `{rel_path(targeted_output_root)}`",
        f"- Record count: `{len(records)}`",
        "",
    ]
    for idx, record in enumerate(records, 1):
        sample = record["sample"]
        generation = record["generation"]
        retrieval = record["retrieval"]
        lines.extend(
            [
                f"## Record {idx}",
                "",
                f"- Sample ID: `{sample['sample_id']}`",
                f"- Category: `{sample['data_category']}`",
                f"- Strategy: `{generation['strategy']}`",
                f"- Repo original: `{sample.get('repo')}`",
                f"- Repo canonical: `{record['sample_repo_identity']['canonical']}`",
                f"- Generated subject: `{generation.get('generated_subject')}`",
                f"- Reference subject: `{sample.get('subject_reference')}`",
                "",
                "### Original Commit Message",
                "",
                "```text",
                sample.get("message_reference", ""),
                "```",
                "",
                "### Retrieval Diagnostics",
                "",
                f"- retrieved_repo_original: `{retrieval.get('retrieved_repo_original', [])}`",
                f"- retrieved_repo_canonical: `{retrieval.get('retrieved_repo_canonical', [])}`",
                f"- similarity_scores: `{retrieval.get('similarity_scores', [])}`",
                f"- retrieval_quality_status: `{retrieval.get('retrieval_quality_status', 'not_available')}`",
                f"- low_similarity_warning: `{retrieval.get('low_similarity_warning', 'not_available')}`",
                f"- repo_guard_excluded_candidates: `{retrieval.get('repo_guard_excluded_candidates', [])}`",
                "",
            ]
        )
        if sample["sample_id"] == "M_real_multi:7da239a00c1c6f17":
            lines.extend(
                [
                    "### FTXUI Targeted Review Focus",
                    "",
                    "- Check that all retrieved exemplars are cross-repo.",
                    "- Check whether the new subject faithfully covers ABI stability and rendering performance.",
                    "- Check whether the subject over-attributes everything to ABI stability.",
                    "- Check whether Surface flattening / performance optimization is omitted.",
                    "- Check whether any unsupported motivation or effect is introduced.",
                    "",
                ]
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_form(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_REVIEW_FIELDS)
        writer.writeheader()
        for record in records:
            sample = record["sample"]
            generation = record["generation"]
            writer.writerow(
                {
                    "sample_id": sample["sample_id"],
                    "data_category": sample["data_category"],
                    "strategy": generation["strategy"],
                    "generated_subject": generation["generated_subject"],
                    "reference_subject": sample["subject_reference"],
                    "manual_format_ok": "",
                    "manual_faithful": "",
                    "manual_complete": "",
                    "manual_concise": "",
                    "manual_oversegmentation": "",
                    "manual_omission": "",
                    "manual_hallucination": "",
                    "manual_oracle_plan_copying": "" if generation["strategy"] == "G5" else "not_applicable",
                    "manual_retrieval_example_reasonable": "" if generation["strategy"] in {"G4", "G5"} else "not_applicable",
                    "manual_prompt_defect_detected": "",
                    "manual_overall_accept": "",
                    "manual_confidence": "",
                    "manual_failure_category": "",
                    "notes": "",
                    "reviewer": "",
                    "reviewed_at": "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-probe-output-root", required=True)
    parser.add_argument("--base-probe-result-json", required=True)
    parser.add_argument("--targeted-output-root", required=True)
    parser.add_argument("--reports-root", default="reports")
    args = parser.parse_args()
    result = build_combined_probe_review_bundle(
        base_probe_output_root=repo_path(args.base_probe_output_root),
        base_probe_result_json=repo_path(args.base_probe_result_json),
        targeted_output_root=repo_path(args.targeted_output_root),
        reports_root=repo_path(args.reports_root),
    )
    print(json.dumps({"bundle_path": rel_path(result["bundle_path"]), "form_path": rel_path(result["form_path"]), "record_count": result["record_count"]}, indent=2))


if __name__ == "__main__":
    main()
