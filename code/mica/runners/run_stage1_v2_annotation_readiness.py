from __future__ import annotations

import argparse
import json
from pathlib import Path

from code.mica.io_utils import read_json, write_json
from code.mica.stage1_v2.materialization import build_annotation_readiness_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Stage1-v2 annotation readiness report.")
    parser.add_argument("--protocol-spec", default="configs/mica/stage1_v2_protocol_spec.json")
    parser.add_argument("--asset-registry", default="configs/mica/stage1_v2_asset_registry.json")
    parser.add_argument("--real-count-pilot-queue")
    parser.add_argument("--real-adjudicated-pilot")
    parser.add_argument("--background-queue")
    parser.add_argument("--blind-review-asset")
    parser.add_argument("--output-json", required=True)
    return parser


def run_stage1_v2_annotation_readiness(
    *,
    protocol_spec_path: str | Path,
    asset_registry_path: str | Path,
    output_json: str | Path,
    real_count_pilot_queue_path: str | Path | None = None,
    real_adjudicated_pilot_path: str | Path | None = None,
    background_queue_path: str | Path | None = None,
    blind_review_asset_path: str | Path | None = None,
) -> dict[str, object]:
    protocol_spec = read_json(protocol_spec_path)
    asset_registry = read_json(asset_registry_path)
    payload = build_annotation_readiness_report(
        protocol_spec=protocol_spec,
        asset_registry=asset_registry,
        real_count_queue_path=real_count_pilot_queue_path,
        real_adjudicated_pilot_path=real_adjudicated_pilot_path,
        background_queue_path=background_queue_path,
        blind_review_asset_path=blind_review_asset_path,
    )
    write_json(output_json, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_annotation_readiness(
        protocol_spec_path=args.protocol_spec,
        asset_registry_path=args.asset_registry,
        output_json=args.output_json,
        real_count_pilot_queue_path=args.real_count_pilot_queue,
        real_adjudicated_pilot_path=args.real_adjudicated_pilot,
        background_queue_path=args.background_queue,
        blind_review_asset_path=args.blind_review_asset,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
