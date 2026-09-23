from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.asset_registry import load_asset_registry, resolve_asset_path
from code.mica.io_utils import write_json
from code.mica.runners.registry import get_runner_policy
from code.mica.runners.stage1_runtime import STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME, STAGE1_VALIDATION_ASSET_NAME
from code.mica.stages.stage1_decision_packets import build_kmax_decision_packet, build_threshold_approval_packet
from code.mica.stages.stage1_split_exposure import audit_stage1_split_exposure


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate pending human-approval packets for Stage 1 thresholds and Kmax.")
    parser.add_argument("--asset-registry", required=True)
    parser.add_argument("--threshold-spec", required=True)
    parser.add_argument("--threshold-report", required=True)
    parser.add_argument("--kmax-report", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--proposed-tau", required=True, type=float)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def run_stage1_generate_approval_packets(
    *,
    asset_registry_path: str | Path,
    threshold_spec_path: str | Path,
    threshold_report_path: str | Path,
    kmax_report_path: str | Path,
    output_root: str | Path,
    proposed_tau: float,
    overwrite: bool = False,
) -> dict[str, str]:
    output_root_path = Path(output_root)
    if output_root_path.exists():
        if any(output_root_path.iterdir()) and not overwrite:
            raise FileExistsError(f"Output directory is not empty: {output_root_path}")
    else:
        output_root_path.mkdir(parents=True, exist_ok=True)

    asset_registry = load_asset_registry(asset_registry_path)
    split_audit = audit_stage1_split_exposure(
        candidate_manifest_path=resolve_asset_path(asset_registry, "stage1_official_validation_dev"),
        current_official_manifest_path=resolve_asset_path(asset_registry, STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME),
        proposed_final_test_manifest_paths=[
            path
            for path in (
                resolve_asset_path(asset_registry, STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME),
                resolve_asset_path(asset_registry, "step1_high_conf_single_test"),
                resolve_asset_path(asset_registry, "strict_synthetic_test"),
            )
            if path
        ],
    )
    threshold_packet = build_threshold_approval_packet(
        threshold_spec_path=threshold_spec_path,
        threshold_report_path=threshold_report_path,
        split_exposure_audit=split_audit,
    )
    kmax_packet = build_kmax_decision_packet(
        kmax_report_path=kmax_report_path,
        proposed_tau=proposed_tau,
    )
    split_audit_path = output_root_path / "stage1_split_exposure_audit.json"
    threshold_packet_path = output_root_path / "stage1_threshold_approval_packet.json"
    kmax_packet_path = output_root_path / "stage1_kmax_decision_packet.json"
    write_json(split_audit_path, split_audit)
    write_json(threshold_packet_path, threshold_packet)
    write_json(kmax_packet_path, kmax_packet)
    return {
        "split_audit": str(split_audit_path),
        "threshold_packet": str(threshold_packet_path),
        "kmax_packet": str(kmax_packet_path),
        "runner_policy": get_runner_policy("run_stage1_generate_approval_packets")["name"],
        "candidate_manifest_asset": STAGE1_VALIDATION_ASSET_NAME,
        "official_final_test_asset": STAGE1_OFFICIAL_FINAL_TEST_ASSET_NAME,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_generate_approval_packets(
        asset_registry_path=args.asset_registry,
        threshold_spec_path=args.threshold_spec,
        threshold_report_path=args.threshold_report,
        kmax_report_path=args.kmax_report,
        output_root=args.output_root,
        proposed_tau=float(args.proposed_tau),
        overwrite=bool(args.overwrite),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
