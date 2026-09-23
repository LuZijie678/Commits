from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.baselines.direct_generation_baseline import run_direct_generation_baseline
from code.mica.baselines.llm_prompting_baseline import coerce_structured_plan, run_llm_prompting_baseline
from code.mica.baselines.pretrained_generation_baseline import run_pretrained_generation_baseline
from code.mica.eval.baseline_registry import get_baseline_status
from code.mica.io_utils import read_json
from code.mica.runners.consumer_runner_utils import (
    atomic_write_json,
    atomic_write_jsonl,
    build_runner_error,
    ensure_writable_output,
    read_jsonl_records_with_errors,
)
from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate message-level external reference baselines from structured plans.")
    parser.add_argument("--baseline-spec", required=True)
    parser.add_argument("--plans-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--error-jsonl")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--lenient", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-real-api", action="store_true")
    return parser


def run_message_baseline_generation(
    *,
    baseline_spec_path: str | Path,
    plans_jsonl: str | Path,
    output_root: str | Path,
    error_jsonl: str | Path | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
    strict: bool = True,
    dry_run: bool = False,
    allow_real_api: bool = False,
) -> dict[str, Any]:
    spec = read_json(baseline_spec_path)
    baselines = [str(item) for item in spec.get("baselines", [])]
    backend_config = dict(spec.get("backend", {"provider": "mock", "model": "mock-model"}))
    rows, parse_errors = read_jsonl_records_with_errors(plans_jsonl, strict=strict)

    output_root_path = Path(output_root)
    rows_output_path = output_root_path / "message_baseline_rows.jsonl"
    manifest_output_path = output_root_path / "message_baseline_generation_manifest.json"
    summary_output_path = output_root_path / "message_baseline_generation_summary.json"
    if not validate_only:
        ensure_writable_output(rows_output_path, overwrite=overwrite)
        ensure_writable_output(manifest_output_path, overwrite=overwrite)
        ensure_writable_output(summary_output_path, overwrite=overwrite)
        if error_jsonl is not None:
            ensure_writable_output(error_jsonl, overwrite=overwrite)

    output_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = list(parse_errors)
    baseline_counts = {baseline_name: 0 for baseline_name in baselines}
    for row in rows:
        line_number = int(row.pop("__line_number__", 0))
        sample_id = str(row.get("sample_id", ""))
        for baseline_name in baselines:
            try:
                status = get_baseline_status(baseline_name)
                if status["benchmark_domain"] != "message_utility":
                    raise ValueError(f"Baseline `{baseline_name}` is not a message utility baseline.")
                rendered = _run_message_baseline(
                    baseline_name,
                    row,
                    backend_config=backend_config,
                    allow_real_api=allow_real_api,
                    dry_run=dry_run,
                )
                output_rows.append(
                    {
                        **rendered,
                        "baseline": baseline_name,
                        "rendering_mode": baseline_name,
                    }
                )
                baseline_counts[baseline_name] = baseline_counts.get(baseline_name, 0) + 1
            except Exception as exc:  # noqa: BLE001 - keep exporting remaining rows.
                error_rows.append(
                    build_runner_error(
                        error_type="schema_validation_error",
                        message=str(exc),
                        line_number=line_number or None,
                        sample_id=sample_id or None,
                    )
                )

    manifest = build_run_manifest(
        stage="message_baseline_generation",
        mode="validate_only" if validate_only else ("dry_run" if dry_run else "execute"),
        output_root=str(output_root),
        flags={
            "training_executed": False,
            "api_calls_enabled": bool(allow_real_api and str(backend_config.get("provider", "mock")) != "mock" and not dry_run),
            "thresholds_applied_to_pass_fail": False,
        },
        inputs={
            "baseline_spec": baseline_spec_path,
            "plans_jsonl": plans_jsonl,
            "allow_real_api": allow_real_api,
        },
        metadata={
            "baseline_names": baselines,
            "backend_provider": str(backend_config.get("provider", "mock")),
        },
    )
    assert_no_forbidden_training_flags(manifest)

    summary = {
        "schema_version": "mica-message-baseline-generation-v1",
        "validate_only": validate_only,
        "row_count": len(output_rows),
        "sample_count": len(rows),
        "baseline_names": baselines,
        "sample_counts": {
            "total": len(rows) + len(parse_errors),
            "success": len(output_rows),
            "errors": len(error_rows),
        },
        "baseline_counts": baseline_counts,
        "backend_provider": str(backend_config.get("provider", "mock")),
        "real_api_called": bool(allow_real_api and str(backend_config.get("provider", "mock")) != "mock" and not dry_run),
    }
    if not validate_only:
        atomic_write_jsonl(rows_output_path, output_rows, overwrite=overwrite)
        atomic_write_json(manifest_output_path, manifest, overwrite=overwrite)
        atomic_write_json(summary_output_path, summary, overwrite=overwrite)
        if error_jsonl is not None and error_rows:
            atomic_write_jsonl(error_jsonl, error_rows, overwrite=overwrite)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_message_baseline_generation(
        baseline_spec_path=args.baseline_spec,
        plans_jsonl=args.plans_jsonl,
        output_root=args.output_root,
        error_jsonl=args.error_jsonl,
        overwrite=bool(args.overwrite),
        validate_only=bool(args.validate_only),
        strict=not bool(args.lenient),
        dry_run=bool(args.dry_run),
        allow_real_api=bool(args.allow_real_api),
    )
    return 0


def _run_message_baseline(
    baseline_name: str,
    row: dict[str, Any],
    *,
    backend_config: dict[str, Any],
    allow_real_api: bool,
    dry_run: bool,
) -> dict[str, Any]:
    if baseline_name == "llm_prompting":
        return run_llm_prompting_baseline(
            row,
            backend_config=backend_config,
            allow_real_api=allow_real_api,
            dry_run=dry_run,
        )
    if baseline_name in {"pretrained_generation", "pretrained_classifier"}:
        return run_pretrained_generation_baseline(
            row,
            backend_config=backend_config,
            allow_real_api=allow_real_api,
            dry_run=dry_run,
        )
    if baseline_name == "direct_generation":
        plan = coerce_structured_plan(row)
        edit_units = [unit.to_dict() for intent in plan.intents for unit in intent.evidence]
        rendered = run_direct_generation_baseline({"edit_units": edit_units})
        return {
            "sample_id": plan.sample_id,
            "commit_id": plan.commit_id,
            "structured_intent_plan": {"intents": []},
            "evidence_terms": [],
            "plan_source": str(plan.metadata.get("plan_source", "predicted")),
            "proxy_not_human_eval": True,
            "message": str(rendered.get("message", "")),
            "model_name": "direct_generation_local",
            "generator_metadata": dict(rendered.get("metadata", {})),
        }
    raise KeyError(f"Unsupported message baseline: {baseline_name}")


if __name__ == "__main__":
    raise SystemExit(main())
