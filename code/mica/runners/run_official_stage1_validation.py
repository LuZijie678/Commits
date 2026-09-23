from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, write_json
from code.mica.plan_builder import build_plans_from_jsonl

CURRENT_CANDIDATE_SCHEDULE = "naive_balanced_mixed_large_scale"


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Stage 1 Official Validation Readiness",
        "",
        f"- `deprecated`: {payload['deprecated']}",
        f"- `runner_role`: {payload['runner_role']}",
        f"- `canonical_formal_runner`: {payload['canonical_formal_runner']}",
        f"- `ready`: {payload['ready']}",
        f"- `dry_run`: {payload['dry_run']}",
        f"- `validate_only`: {payload['validate_only']}",
        f"- `candidate_schedule`: {payload['candidate_schedule']}",
        f"- `stage2_allowed`: {payload['stage2_allowed']}",
        "",
        "## Checks",
        "",
        f"- `training_invoked = {payload['training_invoked']}`",
        f"- `hard_b_checked = {payload['forbidden_sources_checked']['hard_b']}`",
        f"- `M_weak_checked = {payload['forbidden_sources_checked']['M_weak']}`",
        f"- `RealDomainSplit_checked = {payload['forbidden_sources_checked']['RealDomainSplit']}`",
        f"- `RealDomainSelective_checked = {payload['forbidden_sources_checked']['RealDomainSelective']}`",
        "",
        "## Diagnostics",
        "",
    ]
    for item in payload["diagnostics"]:
        lines.append(f"- `{item['code']}`: {item['message']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run readiness checker for frozen Stage 1 official validation.")
    parser.add_argument("--protocol-spec", required=True)
    parser.add_argument("--metric-thresholds", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--prediction-jsonl")
    parser.add_argument("--edit-units-jsonl")
    parser.add_argument("--plan-smoke-check", action="store_true")
    return parser


def run_official_stage1_validation(
    *,
    protocol_spec_path: str | Path,
    metric_thresholds_path: str | Path,
    manifest_path: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    validate_only: bool = False,
    prediction_jsonl: str | Path | None = None,
    edit_units_jsonl: str | Path | None = None,
    plan_smoke_check: bool = False,
) -> dict[str, Any]:
    if not dry_run and not validate_only:
        raise ValueError("Stage 1 official validation requires --dry-run or --validate-only.")
    if plan_smoke_check and prediction_jsonl is None:
        raise ValueError("--plan-smoke-check requires --prediction-jsonl.")

    protocol_spec = read_json(Path(protocol_spec_path))
    metric_thresholds = read_json(Path(metric_thresholds_path))
    manifest = read_json(Path(manifest_path))
    diagnostics: list[dict[str, Any]] = []

    if protocol_spec.get("stage2_allowed") is not False:
        diagnostics.append({"code": "stage2_not_frozen", "severity": "error", "message": "Protocol spec must keep stage2_allowed=false."})
    if manifest.get("stage2_allowed") is not False:
        diagnostics.append({"code": "manifest_stage2_not_frozen", "severity": "error", "message": "Runtime manifest must keep stage2_allowed=false."})
    if protocol_spec.get("candidate_schedule") != CURRENT_CANDIDATE_SCHEDULE:
        diagnostics.append({"code": "unexpected_candidate_schedule", "severity": "error", "message": "Protocol spec candidate schedule does not match current frozen Stage 1 candidate."})
    if manifest.get("schedule_candidate") not in {None, CURRENT_CANDIDATE_SCHEDULE}:
        diagnostics.append({"code": "manifest_schedule_mismatch", "severity": "error", "message": "Manifest schedule candidate does not match frozen Stage 1 candidate."})
    if not metric_thresholds:
        diagnostics.append({"code": "missing_threshold_payload", "severity": "warning", "message": "Metric thresholds payload is empty."})

    ready = not any(item["severity"] == "error" for item in diagnostics)
    result = {
        "run_id": f"stage1_official_validation_readiness_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deprecated": True,
        "runner_role": "readiness_wrapper_only",
        "canonical_formal_runner": "code/mica/runners/run_stage1_official_validation.py",
        "official_execution_supported": False,
        "ready": ready,
        "dry_run": dry_run,
        "validate_only": validate_only,
        "training_invoked": False,
        "training_executed": False,
        "official_validation_executed": False,
        "thresholds_applied_to_pass_fail": False,
        "stage": "stage1",
        "stage2_allowed": False,
        "candidate_schedule": CURRENT_CANDIDATE_SCHEDULE,
        "protocol_status": protocol_spec.get("protocol_status"),
        "manifest_checked": str(Path(manifest_path)),
        "protocol_spec_checked": str(Path(protocol_spec_path)),
        "metric_thresholds_checked": str(Path(metric_thresholds_path)),
        "forbidden_sources_checked": {
            "hard_b": False,
            "M_weak": False,
            "RealDomainSplit": False,
            "RealDomainSelective": False,
            "generation": False,
            "retrieval": False,
            "verifier": False,
        },
        "diagnostics": diagnostics,
        "plan_smoke_check_executed": False,
    }
    output_root_path = Path(output_root)
    if plan_smoke_check and prediction_jsonl is not None:
        plan_summary = build_plans_from_jsonl(
            prediction_jsonl=prediction_jsonl,
            edit_units_jsonl_or_manifest=edit_units_jsonl,
            output_jsonl=output_root_path / "stage1_official_validation_plan_smoke_plans.jsonl",
            summary_json_path=output_root_path / "stage1_official_validation_plan_smoke.json",
            summary_md_path=output_root_path / "stage1_official_validation_plan_smoke.md",
        )
        result["plan_smoke_check_executed"] = True
        result["plan_smoke_summary"] = plan_summary
    write_json(output_root_path / "stage1_official_validation_readiness.json", result)
    _write_markdown(output_root_path / "stage1_official_validation_readiness.md", result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_official_stage1_validation(
        protocol_spec_path=args.protocol_spec,
        metric_thresholds_path=args.metric_thresholds,
        manifest_path=args.manifest,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        validate_only=bool(args.validate_only),
        prediction_jsonl=args.prediction_jsonl,
        edit_units_jsonl=args.edit_units_jsonl,
        plan_smoke_check=bool(args.plan_smoke_check),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
