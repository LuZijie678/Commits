from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STATUS_ORDER = {"reject": 0, "fallback": 1, "pass": 2}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_run(run_dir: Path, near_threshold_margin: float) -> dict[str, Any]:
    metadata = load_json(run_dir / "run_metadata.json")
    samples = load_jsonl(run_dir / "synthetic_samples.jsonl")
    thresholds = metadata.get("thresholds", {})
    t_reject = float(thresholds.get("t_reject", 0.0))
    t_pass = float(thresholds.get("t_pass", 0.0))

    pass_count = 0
    fallback_count = 0
    reject_count = 0
    near_reject = 0
    near_pass = 0
    sample_statuses: dict[str, dict[str, Any]] = {}

    for row in samples:
        sample_id = str(row.get("sample_id", ""))
        status = str(row.get("message_status", "reject"))
        weight = float((row.get("message_scores") or {}).get("message_quality_weight", 0.0) or 0.0)
        subject = str(row.get("synthetic_subject", ""))
        sample_statuses[sample_id] = {
            "message_status": status,
            "message_quality_weight": round(weight, 6),
            "synthetic_subject": subject,
        }
        if status == "pass":
            pass_count += 1
            if abs(weight - t_pass) <= near_threshold_margin:
                near_pass += 1
        elif status == "fallback":
            fallback_count += 1
        elif status == "reject":
            reject_count += 1
            if abs(weight - t_reject) <= near_threshold_margin:
                near_reject += 1

    step3_ready_count = int(
        (metadata.get("target_gate") or {}).get(
            "step3_ready_count",
            pass_count + fallback_count,
        )
    )
    generated_count = int(
        (metadata.get("target_gate") or {}).get(
            "generated_count",
            len(samples),
        )
    )

    return {
        "run_dir": str(run_dir),
        "run_name": run_dir.name,
        "thresholds": {
            "t_reject": round(t_reject, 6),
            "t_pass": round(t_pass, 6),
            "detail": thresholds.get("detail", {}),
        },
        "counts": {
            "step3_ready_count": step3_ready_count,
            "generated_count": generated_count,
            "pass": pass_count,
            "fallback": fallback_count,
            "reject": reject_count,
        },
        "near_threshold": {
            "margin": near_threshold_margin,
            "reject_within_margin_count": near_reject,
            "pass_within_margin_count": near_pass,
        },
        "sample_statuses": sample_statuses,
    }


def build_status_variability(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sample_ids = sorted({sample_id for run in runs for sample_id in run["sample_statuses"].keys()})
    variability: list[dict[str, Any]] = []
    for sample_id in sample_ids:
        by_run = []
        statuses = []
        for run in runs:
            payload = run["sample_statuses"].get(sample_id)
            if not payload:
                continue
            statuses.append(payload["message_status"])
            by_run.append(
                {
                    "run_name": run["run_name"],
                    "message_status": payload["message_status"],
                    "message_quality_weight": payload["message_quality_weight"],
                    "synthetic_subject": payload["synthetic_subject"],
                }
            )
        unique_statuses = sorted(set(statuses))
        if len(unique_statuses) > 1:
            variability.append(
                {
                    "sample_id": sample_id,
                    "statuses": unique_statuses,
                    "runs": by_run,
                }
            )
    return variability


def build_baseline_drift(runs: list[dict[str, Any]], baseline_run_name: str) -> list[dict[str, Any]]:
    baseline = next(run for run in runs if run["run_name"] == baseline_run_name)
    drift_rows: list[dict[str, Any]] = []
    for run in runs:
        if run["run_name"] == baseline_run_name:
            continue
        changed = 0
        worsened = 0
        improved = 0
        for sample_id, payload in baseline["sample_statuses"].items():
            other = run["sample_statuses"].get(sample_id)
            if not other:
                continue
            base_rank = STATUS_ORDER.get(payload["message_status"], -1)
            other_rank = STATUS_ORDER.get(other["message_status"], -1)
            if base_rank != other_rank:
                changed += 1
                if other_rank > base_rank:
                    improved += 1
                elif other_rank < base_rank:
                    worsened += 1
        drift_rows.append(
            {
                "run_name": run["run_name"],
                "changed_sample_count": changed,
                "improved_sample_count": improved,
                "worsened_sample_count": worsened,
                "step3_ready_delta_vs_baseline": run["counts"]["step3_ready_count"] - baseline["counts"]["step3_ready_count"],
                "t_reject_delta_vs_baseline": round(run["thresholds"]["t_reject"] - baseline["thresholds"]["t_reject"], 6),
                "t_pass_delta_vs_baseline": round(run["thresholds"]["t_pass"] - baseline["thresholds"]["t_pass"], 6),
            }
        )
    return drift_rows


def build_stability_report(
    run_dirs: list[Path],
    baseline_run_dir: Path | None = None,
    near_threshold_margin: float = 0.01,
) -> dict[str, Any]:
    if not run_dirs:
        raise ValueError("run_dirs must not be empty")
    resolved_run_dirs = [Path(path) for path in run_dirs]
    resolved_baseline = Path(baseline_run_dir) if baseline_run_dir else resolved_run_dirs[0]
    runs = [load_run(run_dir, near_threshold_margin) for run_dir in resolved_run_dirs]
    baseline = next(run for run in runs if Path(run["run_dir"]) == resolved_baseline)
    variability = build_status_variability(runs)
    t_reject_values = [run["thresholds"]["t_reject"] for run in runs]
    t_pass_values = [run["thresholds"]["t_pass"] for run in runs]
    step3_ready_values = [run["counts"]["step3_ready_count"] for run in runs]

    report = {
        "baseline_run": {
            "run_name": baseline["run_name"],
            "run_dir": baseline["run_dir"],
        },
        "aggregate": {
            "run_count": len(runs),
            "step3_ready_min": min(step3_ready_values),
            "step3_ready_max": max(step3_ready_values),
            "step3_ready_span": max(step3_ready_values) - min(step3_ready_values),
            "status_variability_sample_count": len(variability),
        },
        "threshold_drift": {
            "t_reject_min": min(t_reject_values),
            "t_reject_max": max(t_reject_values),
            "t_reject_span": round(max(t_reject_values) - min(t_reject_values), 6),
            "t_pass_min": min(t_pass_values),
            "t_pass_max": max(t_pass_values),
            "t_pass_span": round(max(t_pass_values) - min(t_pass_values), 6),
        },
        "runs": runs,
        "baseline_drift": build_baseline_drift(runs, baseline["run_name"]),
        "status_variability": variability,
    }
    return report


def build_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Step2 Message Threshold Stability Report",
        "",
        f"- Baseline run: `{report['baseline_run']['run_name']}`",
        f"- Run count: `{report['aggregate']['run_count']}`",
        f"- Step3-ready span: `{report['aggregate']['step3_ready_span']}` "
        f"(`{report['aggregate']['step3_ready_min']}` -> `{report['aggregate']['step3_ready_max']}`)",
        f"- t_reject span: `{report['threshold_drift']['t_reject_span']}`",
        f"- t_pass span: `{report['threshold_drift']['t_pass_span']}`",
        f"- Status-variability sample count: `{report['aggregate']['status_variability_sample_count']}`",
        "",
        "## Runs",
        "",
        "| run | step3_ready | pass | fallback | reject | t_reject | t_pass | near_reject | near_pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        counts = run["counts"]
        near = run["near_threshold"]
        thresholds = run["thresholds"]
        lines.append(
            f"| {run['run_name']} | {counts['step3_ready_count']} | {counts['pass']} | {counts['fallback']} | "
            f"{counts['reject']} | {thresholds['t_reject']:.6f} | {thresholds['t_pass']:.6f} | "
            f"{near['reject_within_margin_count']} | {near['pass_within_margin_count']} |"
        )

    lines.extend(["", "## Baseline Drift", "", "| run | changed | improved | worsened | step3_ready_delta | t_reject_delta | t_pass_delta |", "|---|---:|---:|---:|---:|---:|---:|"])
    for row in report["baseline_drift"]:
        lines.append(
            f"| {row['run_name']} | {row['changed_sample_count']} | {row['improved_sample_count']} | "
            f"{row['worsened_sample_count']} | {row['step3_ready_delta_vs_baseline']} | "
            f"{row['t_reject_delta_vs_baseline']:.6f} | {row['t_pass_delta_vs_baseline']:.6f} |"
        )

    lines.extend(["", "## Status Variability", ""])
    if not report["status_variability"]:
        lines.append("- none")
    else:
        for item in report["status_variability"]:
            lines.append(f"- `{item['sample_id']}`: `{', '.join(item['statuses'])}`")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze threshold drift and message-status stability across Step2 runs.")
    parser.add_argument("--run-dir", action="append", required=True, help="Run directory containing run_metadata.json and synthetic_samples.jsonl.")
    parser.add_argument("--baseline-run-dir", default="", help="Optional baseline run directory. Defaults to the first --run-dir.")
    parser.add_argument("--near-threshold-margin", type=float, default=0.01, help="Absolute margin used to count near-threshold samples.")
    parser.add_argument("--output-dir", default="", help="Optional output directory for JSON/Markdown reports.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dirs = [Path(item).resolve() for item in args.run_dir]
    baseline = Path(args.baseline_run_dir).resolve() if args.baseline_run_dir else run_dirs[0]
    report = build_stability_report(run_dirs, baseline_run_dir=baseline, near_threshold_margin=float(args.near_threshold_margin))
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "threshold_stability_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "threshold_stability_report.md").write_text(
            build_markdown_report(report),
            encoding="utf-8",
        )
        print(output_dir)
        return
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
