from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import write_json
from code.mica.stage1_v2.family_split import build_family_safe_synthetic_split, load_candidate_rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage1-v2 atomic-family-safe synthetic split manifests.")
    parser.add_argument("--synthetic-candidates", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--dev-ratio", type=float, default=0.1)
    parser.add_argument("--control-ratio", type=float, default=0.1)
    parser.add_argument("--split-seed", type=int, default=42)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def run_stage1_v2_family_split(
    *,
    synthetic_candidates_path: str | Path,
    output_root: str | Path,
    split_ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
    split_seed: int = 42,
    validate_only: bool = False,
) -> dict[str, Any]:
    rows = load_candidate_rows(synthetic_candidates_path)
    result = build_family_safe_synthetic_split(rows, split_ratios=split_ratios, split_seed=split_seed)
    if validate_only:
        return {
            "schema_version": result["schema_version"],
            "validate_only": True,
            "row_count": sum(len(rows) for rows in result["rows_by_split"].values()),
            "split_summary": result["split_summary"],
            "leakage_clean": result["leakage_report"]["leakage_clean"],
        }
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    for split_name, split_rows in result["rows_by_split"].items():
        write_json(
            output_root_path / f"{split_name}.json",
            {
                "schema_version": result["schema_version"],
                "split": split_name,
                "formal_ready": result["leakage_report"]["leakage_clean"],
                "summary": result["split_summary"][split_name],
                "rows": split_rows,
            },
        )
    write_json(output_root_path / "family_map.json", {"schema_version": result["schema_version"], "rows": result["family_map"]})
    write_json(output_root_path / "leakage_report.json", result["leakage_report"])
    write_json(output_root_path / "split_summary.json", result["split_summary"])
    return {
        "output_root": str(output_root_path),
        "split_summary": result["split_summary"],
        "leakage_clean": result["leakage_report"]["leakage_clean"],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_stage1_v2_family_split(
        synthetic_candidates_path=args.synthetic_candidates,
        output_root=args.output_root,
        split_ratios=(args.train_ratio, args.dev_ratio, args.control_ratio),
        split_seed=args.split_seed,
        validate_only=bool(args.validate_only),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
