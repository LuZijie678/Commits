from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.eval.anti_shortcut_audit import (
    audit_shortcut_readiness,
    build_anti_shortcut_experiment_plan,
    build_masked_dataset_rows,
    build_model_rerun_request,
)
from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Anti-shortcut audit masking harness.")
    parser.add_argument("--audit-spec", required=True)
    parser.add_argument("--edit-units-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute-model", action="store_true")
    parser.add_argument("--advisor-approved", action="store_true")
    return parser


def run_anti_shortcut_audit_dryrun(
    *,
    audit_spec_path: str | Path,
    edit_units_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    execute_model: bool = False,
    advisor_approved: bool = False,
) -> dict[str, object]:
    if not dry_run:
        raise ValueError("Anti-shortcut audit harness requires explicit --dry-run.")
    if execute_model and not advisor_approved:
        raise ValueError("Anti-shortcut model rerun requires explicit advisor approval.")

    spec = read_json(audit_spec_path)
    rows = read_jsonl(edit_units_jsonl)
    experiment_plan = build_anti_shortcut_experiment_plan(spec, rows)
    masking_modes = list(experiment_plan["masking_modes"])

    output_root_path = Path(output_root)
    masked_variants = []
    for mode in masking_modes:
        masked_rows = build_masked_dataset_rows(rows, mode)
        filename = _masked_filename(mode)
        write_jsonl(output_root_path / filename, masked_rows)
        masked_variants.append(
            {
                "masking_mode": mode,
                "filename": filename,
                "sample_count": len(masked_rows),
                "edit_unit_count": sum(len(row.get("edit_units", [])) for row in masked_rows),
            }
        )
    if "marker_masked" in masking_modes:
        marker_rows = build_masked_dataset_rows(rows, "marker_masked")
        write_jsonl(output_root_path / "diff_marker_masked_edit_units.jsonl", marker_rows)
    readiness = audit_shortcut_readiness(rows)
    readiness["masking_modes_materialized"] = masking_modes
    readiness["masked_variant_count"] = len(masked_variants)
    write_json(output_root_path / "anti_shortcut_readiness_summary.json", readiness)
    write_json(output_root_path / "anti_shortcut_masked_variant_manifest.json", {"variants": masked_variants})
    rerun_request = {
        **build_model_rerun_request(
            str(output_root_path / masked_variants[0]["filename"]) if masked_variants else "",
            list(spec.get("model_command", [])),
            spec,
        ),
        "rerun_ready": True,
        "execute_requested": bool(execute_model),
        "advisor_approved": bool(advisor_approved),
        "masked_variants": [variant["filename"] for variant in masked_variants],
        "masked_variant_manifest": "anti_shortcut_masked_variant_manifest.json",
        "experiment_plan": experiment_plan,
    }
    write_json(output_root_path / "anti_shortcut_rerun_request.json", rerun_request)
    manifest = {
        "run_id": f"anti_shortcut_audit_dryrun_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "stage": "anti_shortcut_audit_dryrun",
        "dry_run": True,
        "model_executed": False,
        "training_executed": False,
        "shortcut_conclusion_made": False,
        "thresholds_tuned": False,
        "rerun_ready": True,
        "masking_modes_materialized": masking_modes,
        "masked_variant_count": len(masked_variants),
    }
    write_json(output_root_path / "anti_shortcut_audit_dryrun_manifest.json", manifest)
    return manifest


def _masked_filename(masking_mode: str) -> str:
    return f"{masking_mode}_edit_units.jsonl"


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_anti_shortcut_audit_dryrun(
        audit_spec_path=args.audit_spec,
        edit_units_jsonl=args.edit_units_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        execute_model=bool(args.execute_model),
        advisor_approved=bool(args.advisor_approved),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
