from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.eval.stage1_unit_accuracy_supplement import (
    build_stage1_official_status_revision,
    load_and_compute_stage1_unit_accuracy_supplement,
)
from code.mica.io_utils import write_json


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover the Stage 1 unit-accuracy gain metric from frozen official artifacts.")
    parser.add_argument("--official-result", required=True)
    parser.add_argument("--official-manifest", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--aggregate-metrics", required=True)
    parser.add_argument("--final-test-manifest", required=True)
    parser.add_argument("--threshold-spec", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--computation-git-sha", required=True)
    parser.add_argument("--observability-audit-output", required=True)
    parser.add_argument("--supplement-output", required=True)
    parser.add_argument("--status-revision-output")
    return parser


def run_stage1_unit_accuracy_supplement(
    *,
    official_result_path: str | Path,
    official_manifest_path: str | Path,
    predictions_path: str | Path,
    aggregate_metrics_path: str | Path,
    final_test_manifest_path: str | Path,
    threshold_spec_path: str | Path,
    checkpoint_sha256: str,
    computation_git_sha: str,
    observability_audit_output_path: str | Path,
    supplement_output_path: str | Path,
    status_revision_output_path: str | Path | None = None,
) -> dict:
    computed = load_and_compute_stage1_unit_accuracy_supplement(
        official_result_path=official_result_path,
        official_manifest_path=official_manifest_path,
        predictions_path=predictions_path,
        aggregate_metrics_path=aggregate_metrics_path,
        final_test_manifest_path=final_test_manifest_path,
        threshold_spec_path=threshold_spec_path,
        checkpoint_sha256=checkpoint_sha256,
        computation_git_sha=computation_git_sha,
    )
    write_json(observability_audit_output_path, computed["observability_audit"])
    write_json(supplement_output_path, computed["supplement_record"])
    status_revision = None
    if status_revision_output_path is not None:
        status_revision = build_stage1_official_status_revision(
            official_result=computed["official_result"],
            supplement_record=computed["supplement_record"],
            supplement_record_path=str(supplement_output_path),
            computation_git_sha=computation_git_sha,
        )
        write_json(status_revision_output_path, status_revision)
    return {
        "observability_audit": computed["observability_audit"],
        "supplement_record": computed["supplement_record"],
        "status_revision": status_revision,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage1_unit_accuracy_supplement(
        official_result_path=args.official_result,
        official_manifest_path=args.official_manifest,
        predictions_path=args.predictions,
        aggregate_metrics_path=args.aggregate_metrics,
        final_test_manifest_path=args.final_test_manifest,
        threshold_spec_path=args.threshold_spec,
        checkpoint_sha256=args.checkpoint_sha256,
        computation_git_sha=args.computation_git_sha,
        observability_audit_output_path=args.observability_audit_output,
        supplement_output_path=args.supplement_output,
        status_revision_output_path=args.status_revision_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
