from __future__ import annotations

import argparse
from pathlib import Path

from code.mica.baselines.baseline_runner import load_manifest_rows, run_configured_baselines, write_baseline_outputs
from code.mica.eval.baseline_registry import get_baseline_status
from code.mica.io_utils import read_json
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 baseline entrypoint.")
    parser.add_argument("--baseline-spec", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--advisor-approved", action="store_true")
    return parser


def run_stage1_baselines(
    *,
    baseline_spec_path: str | Path,
    manifest_path: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    execute: bool = False,
    advisor_approved: bool = False,
) -> dict:
    if not dry_run and not execute:
        raise ValueError("Stage 1 baselines runner requires explicit --dry-run or --execute.")
    spec = read_json(baseline_spec_path)
    approved = bool(advisor_approved or spec.get("advisor_stage1_baselines_approved", False))
    if execute and not approved:
        raise ValueError("Stage 1 baseline execution requires advisor approval.")
    baselines = [str(item) for item in spec.get("baselines", [])]
    non_attribution = [
        name
        for name in baselines
        if get_baseline_status(name).get("benchmark_domain") != "attribution"
    ]
    if non_attribution:
        raise ValueError(
            "Stage 1 baselines runner cannot execute message utility baselines: "
            + ", ".join(sorted(non_attribution))
        )
    rows = load_manifest_rows(manifest_path)
    predictions, summary = run_configured_baselines(rows, baselines)
    manifest = build_run_manifest(
        stage="stage1_baselines",
        mode="dry_run" if dry_run else "execute",
        output_root=str(output_root),
        flags={
            "execute_requested": bool(execute),
            "training_executed": False,
            "advisor_approved": approved,
            "thresholds_applied_to_pass_fail": False,
        },
        inputs={
            "baseline_spec": baseline_spec_path,
            "manifest": manifest_path,
        },
    )
    assert_no_forbidden_training_flags(manifest)
    write_baseline_outputs(output_root=output_root, predictions=predictions, summary=summary, manifest=manifest)
    if execute:
        raise RuntimeError("Stage 1 baseline execute path is wired but not run in this implementation step.")
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_baselines(
        baseline_spec_path=args.baseline_spec,
        manifest_path=args.manifest,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        execute=bool(args.execute),
        advisor_approved=bool(args.advisor_approved),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
