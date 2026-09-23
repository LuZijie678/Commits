from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import write_json
from code.mica.stage1_v2.family_split import load_candidate_rows
from code.mica.stage1_v2.real_count import build_real_count_annotation_queue, summarize_real_count_queue


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage1-v2 RealCount annotation queue.")
    parser.add_argument("--candidate-path", action="append", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--guideline-version", required=True)
    parser.add_argument("--annotation-version", required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def run_stage1_v2_real_count_queue(
    *,
    candidate_paths: list[str | Path],
    output_json: str | Path,
    guideline_version: str,
    annotation_version: str,
    validate_only: bool = False,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for candidate_path in candidate_paths:
        candidates.extend(load_candidate_rows(candidate_path))
    queue = build_real_count_annotation_queue(
        candidates,
        guideline_version=guideline_version,
        annotation_version=annotation_version,
    )
    summary = summarize_real_count_queue(queue["rows"])
    if validate_only:
        return {"validate_only": True, "summary": summary}
    write_json(output_json, queue)
    write_json(Path(output_json).with_name(Path(output_json).stem + "_summary.json"), summary)
    return {"output_json": str(output_json), "summary": summary}


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_real_count_queue(
        candidate_paths=args.candidate_path,
        output_json=args.output_json,
        guideline_version=args.guideline_version,
        annotation_version=args.annotation_version,
        validate_only=bool(args.validate_only),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
