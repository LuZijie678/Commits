from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from code.mica.stage1_v2.reviewed_diagnostic import write_reviewed_diagnostic_outputs


DEFAULT_REVIEWED_MARKINGS = "datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_markings.jsonl"
DEFAULT_BLINDING_MAP = "datasets/mica/stage1_v2/real_alignment/calibration_round_2_blinding_map.json"
DEFAULT_REPORT = "datasets/mica/stage1_v2/real_alignment/calibration_round_2_reviewed_diagnostic_analysis.json"
DEFAULT_FOLLOWUP = "datasets/mica/stage1_v2/real_alignment/calibration_round_2_review_followup_queue.jsonl"
DEFAULT_DRAFT = "docs/annotation/STAGE1_V2_GUIDELINE_PILOT_V3_REVISION_DRAFT.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze human-reviewed Codex R2 diagnostic markings without promoting them to formal evidence."
    )
    parser.add_argument("--reviewed-markings", default=DEFAULT_REVIEWED_MARKINGS)
    parser.add_argument("--blinding-map", default=DEFAULT_BLINDING_MAP)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--followup-queue", default=DEFAULT_FOLLOWUP)
    parser.add_argument("--guideline-revision-draft", default=DEFAULT_DRAFT)
    parser.add_argument("--protocol-version", default="stage1-v2-protocol")
    parser.add_argument("--kmax", type=int, default=4)
    parser.add_argument("--created-at", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = write_reviewed_diagnostic_outputs(
        reviewed_markings_path=Path(args.reviewed_markings),
        blinding_map_path=Path(args.blinding_map),
        report_path=Path(args.report),
        followup_queue_path=Path(args.followup_queue),
        guideline_revision_draft_path=Path(args.guideline_revision_draft),
        protocol_version=args.protocol_version,
        kmax=args.kmax,
        created_at=args.created_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
