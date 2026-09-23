from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from itertools import combinations
from pathlib import Path
from typing import Any


MODULE_PATH = Path(__file__).resolve().with_name("construct_simple_two_intent.py")
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", MODULE_PATH)
CORE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CORE)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def is_eligible_for_threshold(row: dict[str, Any]) -> bool:
    scores = row.get("message_scores") or {}
    return int(scores.get("format", 0)) == 1 and int(scores.get("bertscore_compute_invalid", 0)) == 0


def estimate_step3_ready(row: dict[str, Any]) -> bool:
    if hasattr(CORE, "is_step3_ready_sample"):
        try:
            return bool(CORE.is_step3_ready_sample(row))
        except Exception:
            pass
    return str(row.get("message_status", "")) in {"pass", "fallback"} and bool(str(row.get("synthetic_subject", "")).strip())


def summarize_method(rows: list[dict[str, Any]], threshold_payload: dict[str, Any]) -> dict[str, Any]:
    pass_count = sum(1 for row in rows if row.get("message_status") == "pass")
    fallback_count = sum(1 for row in rows if row.get("message_status") == "fallback")
    reject_count = sum(1 for row in rows if row.get("message_status") == "reject")
    step3_ready_count = sum(1 for row in rows if estimate_step3_ready(row))
    sample_statuses = {
        str(row.get("sample_id", "")): {
            "message_status": str(row.get("message_status", "")),
            "message_quality_weight": float((row.get("message_scores") or {}).get("message_quality_weight", 0.0) or 0.0),
            "synthetic_subject": str(row.get("synthetic_subject", "")),
        }
        for row in rows
    }
    return {
        "thresholds": threshold_payload,
        "counts": {
            "pass": pass_count,
            "fallback": fallback_count,
            "reject": reject_count,
            "step3_ready_estimate": step3_ready_count,
        },
        "sample_statuses": sample_statuses,
    }


def build_pairwise_diffs(method_reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for left_method, right_method in combinations(sorted(method_reports.keys()), 2):
        left_statuses = method_reports[left_method]["sample_statuses"]
        right_statuses = method_reports[right_method]["sample_statuses"]
        changed_samples = []
        for sample_id in sorted(set(left_statuses.keys()) & set(right_statuses.keys())):
            left_status = left_statuses[sample_id]["message_status"]
            right_status = right_statuses[sample_id]["message_status"]
            if left_status != right_status:
                changed_samples.append(
                    {
                        "sample_id": sample_id,
                        "left_status": left_status,
                        "right_status": right_status,
                        "left_weight": left_statuses[sample_id]["message_quality_weight"],
                        "right_weight": right_statuses[sample_id]["message_quality_weight"],
                        "subject": left_statuses[sample_id]["synthetic_subject"] or right_statuses[sample_id]["synthetic_subject"],
                    }
                )
        items.append(
            {
                "left_method": left_method,
                "right_method": right_method,
                "changed_sample_count": len(changed_samples),
                "changed_samples": changed_samples,
            }
        )
    return items


def compare_threshold_methods(run_dir: Path, methods: list[str]) -> dict[str, Any]:
    run_dir = Path(run_dir)
    metadata = load_json(run_dir / "run_metadata.json")
    rows = load_jsonl(run_dir / "synthetic_samples.jsonl")
    values = [
        float((row.get("message_scores") or {}).get("message_quality_weight", 0.0) or 0.0)
        for row in rows
        if is_eligible_for_threshold(row)
    ]
    method_reports: dict[str, dict[str, Any]] = {}
    for method in methods:
        cloned_rows = copy.deepcopy(rows)
        threshold_payload = CORE.calibrate_message_thresholds(values, method)
        CORE.assign_message_status_and_weight(cloned_rows, threshold_payload)
        method_reports[method] = summarize_method(cloned_rows, threshold_payload)

    return {
        "run_name": run_dir.name,
        "run_dir": str(run_dir),
        "sample_count": len(rows),
        "eligible_weight_count": len(values),
        "recorded_thresholds": (metadata.get("thresholds") or {}),
        "methods": method_reports,
        "pairwise_diffs": build_pairwise_diffs(method_reports),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Step2 Fixed-Sample Threshold Method Comparison",
        "",
        f"- Run: `{report['run_name']}`",
        f"- Sample count: `{report['sample_count']}`",
        f"- Eligible weight count: `{report['eligible_weight_count']}`",
        "",
        "## Methods",
        "",
        "| method | step3_ready_estimate | pass | fallback | reject | t_reject | t_pass |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method in sorted(report["methods"].keys()):
        item = report["methods"][method]
        counts = item["counts"]
        thresholds = item["thresholds"]
        lines.append(
            f"| {method} | {counts['step3_ready_estimate']} | {counts['pass']} | {counts['fallback']} | "
            f"{counts['reject']} | {thresholds['t_reject']:.6f} | {thresholds['t_pass']:.6f} |"
        )

    lines.extend(["", "## Pairwise Diffs", ""])
    for diff in report["pairwise_diffs"]:
        lines.append(
            f"- `{diff['left_method']}` vs `{diff['right_method']}`: changed_sample_count=`{diff['changed_sample_count']}`"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare threshold methods on a fixed Step2 sample set without regenerating text.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--method",
        action="append",
        default=[],
        help="Threshold method to compare. Can be repeated. Defaults to kmeans_1d and reference_quantile_band.",
    )
    parser.add_argument("--output-dir", default="", help="Optional output directory for JSON/Markdown reports.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    methods = args.method or ["kmeans_1d", "reference_quantile_band"]
    report = compare_threshold_methods(Path(args.run_dir), methods)
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "threshold_method_comparison.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "threshold_method_comparison.md").write_text(
            render_markdown(report),
            encoding="utf-8",
        )
        print(output_dir)
        return
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
