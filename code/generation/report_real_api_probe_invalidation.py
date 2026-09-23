from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, rel_path, repo_path, safe_text, utc_timestamp, write_json
from repo_identity import describe_repo_identity


def write_repo_identity_invalidation_report(
    *,
    output_root: Path,
    probe_result_json: Path,
    reports_root: Path = repo_path("reports"),
    report_prefix: str = "real_api_probe_invalidation_20260610_repo_identity_leakage",
) -> dict[str, Any]:
    samples = {row["sample_id"]: row for row in read_jsonl(output_root / "dataset" / "canary_all.jsonl")}
    logs = read_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl")
    exemplars = {row["exemplar_id"]: row for row in read_jsonl(output_root / "exemplar_pool" / "exemplar_pool.jsonl")}
    offending = None
    for log in logs:
        sample = samples.get(safe_text(log.get("query_sample_id")))
        if not sample:
            continue
        query_repo = describe_repo_identity(sample.get("repo"))
        for exemplar_id in log.get("retrieved_exemplar_ids", []):
            exemplar = exemplars.get(exemplar_id)
            if not exemplar:
                continue
            exemplar_repo = describe_repo_identity(exemplar.get("repo"))
            if query_repo["canonical"] and query_repo["canonical"] == exemplar_repo["canonical"]:
                offending = {
                    "sample": sample,
                    "log": log,
                    "exemplar": exemplar,
                    "query_repo": query_repo,
                    "exemplar_repo": exemplar_repo,
                }
                break
        if offending:
            break
    if not offending:
        raise RuntimeError("No canonical repo-identity leakage found in the provided probe output")
    report = {
        "schema_version": "real_api_probe_invalidation_v1",
        "report_timestamp": utc_timestamp(),
        "invalidated": True,
        "invalidated_probe_root": rel_path(output_root),
        "invalidated_probe_result": rel_path(probe_result_json),
        "reason": "canonical_repo_identity_leakage",
        "affected_sample_id": offending["sample"]["sample_id"],
        "query_repo_original": offending["query_repo"]["original"],
        "retrieved_repo_original": offending["exemplar_repo"]["original"],
        "query_repo_canonical": offending["query_repo"]["canonical"],
        "retrieved_repo_canonical": offending["exemplar_repo"]["canonical"],
        "same_repo_canonical": offending["query_repo"]["canonical"] == offending["exemplar_repo"]["canonical"],
        "retrieved_exemplar_id": offending["exemplar"]["exemplar_id"],
        "retrieval_strategy": offending["log"].get("generation_strategy") or offending["log"].get("strategy"),
        "recommend_65_request_canary": False,
        "note": "The invalidated probe may still be used for debugging and qualitative inspection, but not as the formal gate into the 65-request Canary.",
    }
    json_path = reports_root / f"{report_prefix}.json"
    md_path = reports_root / f"{report_prefix}.md"
    report["report_json_path"] = rel_path(json_path)
    report["report_md_path"] = rel_path(md_path)
    write_json(json_path, report)
    _write_markdown(report, md_path)
    return report


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Real API Probe Invalidation",
        "",
        f"- invalidated: `{report['invalidated']}`",
        f"- invalidated_probe_root: `{report['invalidated_probe_root']}`",
        f"- invalidated_probe_result: `{report['invalidated_probe_result']}`",
        f"- reason: `{report['reason']}`",
        f"- affected_sample_id: `{report['affected_sample_id']}`",
        f"- query_repo_original: `{report['query_repo_original']}`",
        f"- retrieved_repo_original: `{report['retrieved_repo_original']}`",
        f"- query_repo_canonical: `{report['query_repo_canonical']}`",
        f"- retrieved_repo_canonical: `{report['retrieved_repo_canonical']}`",
        f"- same_repo_canonical: `{report['same_repo_canonical']}`",
        f"- recommend_65_request_canary: `{report['recommend_65_request_canary']}`",
        "",
        report["note"],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--probe-result-json", required=True)
    parser.add_argument("--reports-root", default="reports")
    args = parser.parse_args()
    report = write_repo_identity_invalidation_report(
        output_root=repo_path(args.output_root),
        probe_result_json=repo_path(args.probe_result_json),
        reports_root=repo_path(args.reports_root),
    )
    print(json.dumps({"report_json_path": report["report_json_path"], "invalidated": report["invalidated"]}, indent=2))


if __name__ == "__main__":
    main()
