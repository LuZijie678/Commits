from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.io_utils import write_json
from code.mica.plan_builder import build_plans_from_jsonl
from code.mica.renderers.deterministic import render_plans_from_jsonl
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline smoke runner for attribution prediction -> plan -> deterministic message.")
    parser.add_argument("--prediction-jsonl", required=True)
    parser.add_argument("--edit-units-jsonl")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--smoke-only", action="store_true")
    return parser


def run_plan_renderer_smoke(
    *,
    prediction_jsonl: str | Path,
    output_root: str | Path,
    mode: str,
    smoke_only: bool = False,
    edit_units_jsonl: str | Path | None = None,
) -> dict[str, Any]:
    if not smoke_only:
        raise ValueError("Offline plan/message smoke runner requires explicit --smoke-only.")

    output_root_path = Path(output_root)
    plans_path = output_root_path / "plans.jsonl"
    messages_path = output_root_path / "rendered_messages.jsonl"
    plan_summary = build_plans_from_jsonl(
        prediction_jsonl=prediction_jsonl,
        edit_units_jsonl_or_manifest=edit_units_jsonl,
        output_jsonl=plans_path,
        summary_json_path=output_root_path / "plan_builder_summary.json",
        summary_md_path=output_root_path / "plan_builder_summary.md",
    )
    renderer_summary = render_plans_from_jsonl(
        plan_jsonl=plans_path,
        output_jsonl=messages_path,
        mode=mode,
        summary_json_path=output_root_path / "renderer_summary.json",
        summary_md_path=output_root_path / "renderer_summary.md",
    )
    manifest = build_run_manifest(
        stage="downstream_offline_smoke",
        mode="smoke_only",
        output_root=str(output_root),
        flags={
            "smoke_only": True,
            "advisor_approval_required": False,
            "plan_summary": plan_summary,
            "renderer_summary": renderer_summary,
        },
        inputs={
            "prediction_jsonl": prediction_jsonl,
            "edit_units_jsonl": edit_units_jsonl,
            "render_mode": mode,
        },
    )
    assert_no_forbidden_training_flags(manifest)
    write_json(output_root_path / "smoke_run_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_plan_renderer_smoke(
        prediction_jsonl=args.prediction_jsonl,
        edit_units_jsonl=args.edit_units_jsonl,
        output_root=args.output_root,
        mode=args.mode,
        smoke_only=bool(args.smoke_only),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
