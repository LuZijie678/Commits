from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, write_json
from code.mica.stage1_v2.readiness import (
    build_null_background_preflight,
    build_stage1_v2_baseline_matrix,
    build_stage1_v2_readiness,
    load_optional_json,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Stage1-v2 readiness preflight.")
    parser.add_argument("--protocol-spec", required=True)
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--synthetic-leakage-report")
    parser.add_argument("--real-count-report")
    parser.add_argument("--real-adjudicated-report")
    parser.add_argument("--baseline-matrix-report")
    parser.add_argument("--anti-shortcut-report")
    parser.add_argument("--annotation-campaign-report")
    parser.add_argument("--real-adjudicated-queue")
    parser.add_argument("--official-test-unexposed", action="store_true")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser


def run_stage1_v2_readiness(
    *,
    protocol_spec_path: str | Path,
    asset_registry_path: str | Path,
    output_json: str | Path,
    output_md: str | Path,
    synthetic_leakage_report_path: str | Path | None = None,
    real_count_report_path: str | Path | None = None,
    real_adjudicated_report_path: str | Path | None = None,
    baseline_matrix_report_path: str | Path | None = None,
    anti_shortcut_report_path: str | Path | None = None,
    annotation_campaign_report_path: str | Path | None = None,
    real_adjudicated_queue_path: str | Path | None = None,
    official_test_unexposed: bool = False,
) -> dict[str, Any]:
    protocol_spec = read_json(protocol_spec_path)
    asset_registry = read_json(asset_registry_path)
    synthetic_leakage = load_optional_json(synthetic_leakage_report_path)
    real_count = load_optional_json(real_count_report_path)
    real_adjudicated = load_optional_json(real_adjudicated_report_path)
    baseline_matrix = load_optional_json(baseline_matrix_report_path) or build_stage1_v2_baseline_matrix(protocol_spec)
    anti_shortcut = load_optional_json(anti_shortcut_report_path)
    annotation_campaign = load_optional_json(annotation_campaign_report_path)
    real_adjudicated_rows = []
    if real_adjudicated_queue_path is not None and Path(real_adjudicated_queue_path).exists():
        queue_payload = read_json(real_adjudicated_queue_path)
        if isinstance(queue_payload, dict):
            real_adjudicated_rows = [row for row in list(queue_payload.get("rows") or []) if isinstance(row, dict)]
    null_background = build_null_background_preflight(protocol_spec, real_adjudicated_rows)
    payload = build_stage1_v2_readiness(
        protocol_spec=protocol_spec,
        asset_registry=asset_registry,
        synthetic_leakage_report=synthetic_leakage,
        real_count_report=real_count,
        real_adjudicated_report=real_adjudicated,
        null_background_report=null_background,
        baseline_matrix_report=baseline_matrix,
        anti_shortcut_report=anti_shortcut,
        annotation_campaign_report=annotation_campaign,
        official_test_unexposed=official_test_unexposed,
    )
    write_json(output_json, payload)
    Path(output_md).write_text(_markdown(payload), encoding="utf-8")
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Stage1-v2 Readiness",
        "",
        f"- protocol_frozen: {str(payload['protocol_frozen']).lower()}",
        f"- synthetic_family_split_ready: {str(payload['synthetic_family_split_ready']).lower()}",
        f"- leakage_clean: {str(payload['leakage_clean']).lower()}",
        f"- real_count_asset_ready: {str(payload['real_count_asset_ready']).lower()}",
        f"- Kmax_frozen: {str(payload['Kmax_frozen']).lower()}",
        f"- real_alignment_test_ready: {str(payload['real_alignment_test_ready']).lower()}",
        f"- double_annotation_complete: {str(payload['double_annotation_complete']).lower()}",
        f"- adjudication_complete: {str(payload['adjudication_complete']).lower()}",
        f"- agreement_gates_passed: {str(payload['agreement_gates_passed']).lower()}",
        f"- benchmark_strata_ready: {str(payload['benchmark_strata_ready']).lower()}",
        f"- repository_concentration_passed: {str(payload['repository_concentration_passed']).lower()}",
        f"- null_background_assets_ready: {str(payload['null_background_assets_ready']).lower()}",
        f"- baseline_matrix_ready: {str(payload['baseline_matrix_ready']).lower()}",
        f"- anti_shortcut_ready: {str(payload['anti_shortcut_ready']).lower()}",
        f"- seed_matrix_frozen: {str(payload['seed_matrix_frozen']).lower()}",
        f"- statistical_protocol_frozen: {str(payload['statistical_protocol_frozen']).lower()}",
        f"- synthetic_scale_sufficient: {str(payload['synthetic_scale_sufficient']).lower()}",
        f"- required_atomic_sources_human_verified: {str(payload['required_atomic_sources_human_verified']).lower()}",
        f"- annotation_staffing_complete: {str(payload['annotation_staffing_complete']).lower()}",
        f"- annotators_qualified: {str(payload['annotators_qualified']).lower()}",
        f"- calibration_round_complete: {str(payload['calibration_round_complete']).lower()}",
        f"- calibration_agreement_passed: {str(payload['calibration_agreement_passed']).lower()}",
        f"- pilot_guideline_frozen: {str(payload['pilot_guideline_frozen']).lower()}",
        f"- pilot_double_annotation_complete: {str(payload['pilot_double_annotation_complete']).lower()}",
        f"- pilot_adjudication_complete: {str(payload['pilot_adjudication_complete']).lower()}",
        f"- pilot_quality_gates_passed: {str(payload['pilot_quality_gates_passed']).lower()}",
        f"- official_test_unexposed: {str(payload['official_test_unexposed']).lower()}",
        f"- formal_ready: {str(payload['formal_ready']).lower()}",
        f"- stage2_entry_allowed: {str(payload['stage2_entry_allowed']).lower()}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_readiness(
        protocol_spec_path=args.protocol_spec,
        asset_registry_path=args.asset_registry,
        output_json=args.output_json,
        output_md=args.output_md,
        synthetic_leakage_report_path=args.synthetic_leakage_report,
        real_count_report_path=args.real_count_report,
        real_adjudicated_report_path=args.real_adjudicated_report,
        baseline_matrix_report_path=args.baseline_matrix_report,
        anti_shortcut_report_path=args.anti_shortcut_report,
        annotation_campaign_report_path=args.annotation_campaign_report,
        real_adjudicated_queue_path=args.real_adjudicated_queue,
        official_test_unexposed=bool(args.official_test_unexposed),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
