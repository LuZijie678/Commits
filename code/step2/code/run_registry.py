#!/usr/bin/env python3
"""
Step2 run registry 汇总脚本。

目标：
1. 扫描 outputs 根目录下的 Step2 运行结果目录。
2. 汇总 run_metadata.json / message_gate_report.json 的关键字段。
3. 输出用于论文主结果筛选的 run registry。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


RUN_METADATA_NAME = "run_metadata.json"
MESSAGE_GATE_REPORT_NAME = "message_gate_report.json"



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs-root", required=True, help="Root directory containing Step2 run output folders.")
    parser.add_argument("--csv-out", default="", help="Optional path to write a flat CSV run registry.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload.")
    args = parser.parse_args()
    root = Path(args.outputs_root)
    if not root.exists() or not root.is_dir():
        parser.error(f"Invalid --outputs-root directory: {root}")
    return args



def _load_json_if_exists(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))



def _bool_or_none(value):
    if value is None:
        return None
    return bool(value)



def summarize_run(run_dir: Path) -> dict:
    metadata_path = run_dir / RUN_METADATA_NAME
    metadata = _load_json_if_exists(metadata_path)
    if metadata is None:
        raise RuntimeError(f"Missing {RUN_METADATA_NAME}: {run_dir}")

    gate_path = run_dir / MESSAGE_GATE_REPORT_NAME
    gate_payload = _load_json_if_exists(gate_path)
    gate_present = gate_payload is not None
    gate_passed = gate_payload.get("message_gate_passed") if gate_payload else None

    fewshot_pool = metadata.get("fewshot_pool", {}) or {}
    formal_assets = metadata.get("formal_assets", {}) or {}
    outputs = metadata.get("outputs", {}) or {}
    run_stats = metadata.get("run_stats", {}) or {}

    step3_ready_path = outputs.get("step3_ready_jsonl")
    step3_ready_exists = bool(step3_ready_path and Path(step3_ready_path).exists())
    step3_ready_count = run_stats.get("step3_ready_count")
    if step3_ready_count is None:
        step3_ready_count = 0

    row = {
        "run_dir": str(run_dir),
        "run_dir_name": run_dir.name,
        "run_metadata_path": str(metadata_path),
        "message_gate_report_path": str(gate_path) if gate_present else "",
        "run_purpose": metadata.get("run_purpose"),
        "run_valid_for_paper": bool(metadata.get("run_valid_for_paper", False)),
        "formal_run": bool(metadata.get("formal_run", False)),
        "message_gate_report_present": gate_present,
        "message_gate_passed": _bool_or_none(gate_passed),
        "fewshot_pool_formal_ready": bool(fewshot_pool.get("fewshot_pool_formal_ready", False)),
        "fewshot_pool_total_examples": int(fewshot_pool.get("fewshot_pool_total_examples", 0) or 0),
        "formal_assets_ready": bool(formal_assets.get("formal_assets_ready", False)),
        "step3_ready_path": str(step3_ready_path) if step3_ready_path else "",
        "step3_ready_exists": step3_ready_exists,
        "step3_ready_count": int(step3_ready_count or 0),
    }
    row["paper_valid_candidate"] = bool(
        row["run_valid_for_paper"]
        and row["fewshot_pool_formal_ready"]
        and row["formal_assets_ready"]
        and row["message_gate_passed"] is True
        and row["step3_ready_exists"]
    )
    return row



def build_payload(args: argparse.Namespace) -> dict:
    root = Path(args.outputs_root)
    run_dirs = sorted({path.parent for path in root.rglob(RUN_METADATA_NAME)})
    runs = [summarize_run(run_dir) for run_dir in run_dirs]
    payload = {
        "outputs_root": str(root),
        "run_count": len(runs),
        "paper_valid_candidate_count": sum(1 for row in runs if row["paper_valid_candidate"]),
        "runs": runs,
    }
    return payload



def render_text(payload: dict) -> str:
    lines = [
        f"outputs_root={payload['outputs_root']}",
        f"run_count={payload['run_count']}",
        f"paper_valid_candidate_count={payload['paper_valid_candidate_count']}",
    ]
    for row in payload["runs"]:
        lines.append(
            " | ".join(
                [
                    row["run_dir_name"],
                    f"run_purpose={row['run_purpose']}",
                    f"paper_valid_candidate={int(bool(row['paper_valid_candidate']))}",
                    f"message_gate_passed={row['message_gate_passed']}",
                    f"fewshot_pool_formal_ready={int(bool(row['fewshot_pool_formal_ready']))}",
                    f"formal_assets_ready={int(bool(row['formal_assets_ready']))}",
                    f"step3_ready_count={row['step3_ready_count']}",
                ]
            )
        )
    return "\n".join(lines)


def write_csv_registry(path: Path, runs: list[dict]) -> None:
    fieldnames = [
        "run_dir_name",
        "run_purpose",
        "run_valid_for_paper",
        "formal_run",
        "message_gate_report_present",
        "message_gate_passed",
        "fewshot_pool_formal_ready",
        "fewshot_pool_total_examples",
        "formal_assets_ready",
        "step3_ready_exists",
        "step3_ready_count",
        "paper_valid_candidate",
        "run_dir",
        "run_metadata_path",
        "message_gate_report_path",
        "step3_ready_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    csv_out = Path(args.csv_out) if getattr(args, "csv_out", "") else None
    if csv_out is not None:
        write_csv_registry(csv_out, payload["runs"])
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))


if __name__ == "__main__":
    main()
