from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_stability_module():
    module_path = Path(__file__).resolve().with_name("analyze_message_threshold_stability.py")
    spec = importlib.util.spec_from_file_location("analyze_message_threshold_stability", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def summarize_run(run_dir: Path) -> dict[str, Any]:
    run_metadata_path = run_dir / "run_metadata.json"
    summary = {
        "run_dir": str(run_dir),
        "exists": run_dir.exists(),
    }
    if not run_metadata_path.exists():
        return summary
    payload = load_json(run_metadata_path)
    thresholds = payload.get("thresholds") or {}
    stability = load_stability_module().load_run(run_dir, near_threshold_margin=0.01)
    message_gate_report_path = run_dir / "message_gate_report.json"
    message_gate = load_json(message_gate_report_path) if message_gate_report_path.exists() else {}
    counts = stability.get("counts") or {}
    summary.update(
        {
            "threshold_method": thresholds.get("threshold_method"),
            "t_reject": thresholds.get("t_reject"),
            "t_pass": thresholds.get("t_pass"),
            "step3_ready_count": counts.get("step3_ready_count"),
            "generated_count": counts.get("generated_count"),
            "pass": counts.get("pass"),
            "fallback": counts.get("fallback"),
            "reject": counts.get("reject"),
            "message_gate_passed": message_gate.get("message_gate_passed"),
            "target_gate_passed": message_gate.get("target_gate_passed"),
        }
    )
    return summary


def build_run_command(
    *,
    config_path: Path,
    output_dir: Path,
    seed: int,
    target_count: int | None,
    threshold_method: str | None,
) -> list[str]:
    cmd = [
        sys.executable,
        "code/construct_simple_two_intent.py",
        "--config",
        str(config_path),
        "--output-dir",
        str(output_dir),
        "--seed",
        str(seed),
    ]
    if target_count is not None:
        cmd.extend(["--target-count", str(target_count)])
    if threshold_method:
        cmd.extend(["--threshold-method", threshold_method])
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step2 baseline multiple times with different seeds.")
    parser.add_argument("--config", default="configs/step2_runtime_config.local.json")
    parser.add_argument("--seed", action="append", type=int, required=True, help="Seed to run. Can be repeated.")
    parser.add_argument("--output-root", required=True, help="Directory where per-seed outputs and aggregate summary will be written.")
    parser.add_argument("--target-count", type=int, default=None, help="Optional target_count override.")
    parser.add_argument("--threshold-method", default="", help="Optional threshold method override.")
    parser.add_argument("--keep-going", action="store_true", help="Continue after failed seed runs.")
    parser.add_argument("--skip-stability-report", action="store_true", help="Skip calling analyze_message_threshold_stability.py after runs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    results = []
    run_dirs: list[Path] = []
    for seed in args.seed:
        run_dir = output_root / f"seed_{seed}"
        run_dirs.append(run_dir)
        cmd = build_run_command(
            config_path=config_path,
            output_dir=run_dir,
            seed=seed,
            target_count=args.target_count,
            threshold_method=args.threshold_method or None,
        )
        proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
        result = {
            "seed": seed,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
            **summarize_run(run_dir),
        }
        results.append(result)
        if proc.returncode != 0 and not args.keep_going:
            break

    summary_path = output_root / "multiseed_summary.json"
    summary_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_stability_report:
        successful_run_dirs = [Path(item["run_dir"]) for item in results if item.get("exists")]
        if successful_run_dirs:
            stability_dir = output_root / "stability"
            stability_cmd = [
                sys.executable,
                "code/analyze_message_threshold_stability.py",
                "--baseline-run-dir",
                str(successful_run_dirs[0]),
                "--output-dir",
                str(stability_dir),
            ]
            for run_dir in successful_run_dirs:
                stability_cmd.extend(["--run-dir", str(run_dir)])
            subprocess.run(
                stability_cmd,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

    print(output_root)


if __name__ == "__main__":
    main()
