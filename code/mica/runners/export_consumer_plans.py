from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.adapters.stage1_prediction_adapter import normalize_stage1_prediction_row
from code.mica.consumers.plan_schema import adapt_from_legacy_plan
from code.mica.plan_builder import build_plan_from_dict
from code.mica.runners.consumer_runner_utils import (
    atomic_write_jsonl,
    build_runner_error,
    ensure_writable_output,
    load_sample_indexed_rows,
    read_jsonl_records_with_errors,
)
from code.mica.schema_validation import validate_attribution_prediction_contract


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export canonical consumer StructuredIntentPlan JSONL.")
    parser.add_argument("--prediction-jsonl", "--plans", dest="prediction_jsonl", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--error-jsonl")
    parser.add_argument("--edit-units-jsonl-or-manifest")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--lenient", action="store_true")
    parser.add_argument("--review-ready", action="store_true")
    return parser


def export_consumer_plans(
    *,
    prediction_jsonl: str | Path,
    output_jsonl: str | Path,
    error_jsonl: str | Path | None = None,
    edit_units_jsonl_or_manifest: str | Path | None = None,
    overwrite: bool = False,
    validate_only: bool = False,
    strict: bool = True,
    review_ready: bool = False,
) -> dict[str, Any]:
    if not validate_only:
        ensure_writable_output(output_jsonl, overwrite=overwrite)
        if error_jsonl is not None:
            ensure_writable_output(error_jsonl, overwrite=overwrite)

    rows, parse_errors = read_jsonl_records_with_errors(prediction_jsonl, strict=strict)
    external_edit_units_index = (
        load_sample_indexed_rows(edit_units_jsonl_or_manifest)
        if edit_units_jsonl_or_manifest is not None
        else {}
    )
    exported_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = list(parse_errors)
    decision_distribution: dict[str, int] = {}
    predicted_k_distribution: dict[str, int] = {}
    review_ready_exported_count = 0
    missing_release_decision_count = 0
    missing_edit_units_count = 0
    missing_assignment_scores_count = 0
    background_contract_complete_count = 0
    background_contract_incomplete_count = 0
    degraded_plan_count = 0
    unsupported_k_experimental_count = 0
    joined_from_external_edit_units_count = 0
    embedded_edit_units_count = 0
    source_join_mode_counts: dict[str, int] = {}
    review_ready_blocker_counts: dict[str, int] = {}
    blocked_samples_preview: list[dict[str, Any]] = []
    ready_samples_preview: list[str] = []
    blocked_sample_count = 0

    for index, row in enumerate(rows, 1):
        sample_id = str(row.get("sample_id") or f"__row_{index}__")
        external_edit_units = external_edit_units_index.get(sample_id)
        try:
            normalized = normalize_stage1_prediction_row(row)
            validation = validate_attribution_prediction_contract(
                normalized,
                mode="review_ready" if review_ready else "minimal",
                external_edit_units_available=external_edit_units is not None,
            )
            if "missing_release_decision" in validation["errors"]:
                missing_release_decision_count += 1
            if "missing_edit_units" in validation["errors"]:
                missing_edit_units_count += 1
            if "missing_assignment_scores" in validation["errors"] or "limited_prediction_format" in validation["warnings"]:
                missing_assignment_scores_count += 1
            blockers = list(validation["errors"])
            if review_ready and not validation["valid"]:
                blocked_sample_count += 1
                _record_blockers(
                    blocker_counts=review_ready_blocker_counts,
                    blocked_samples_preview=blocked_samples_preview,
                    sample_id=sample_id,
                    blockers=blockers,
                )
                error_rows.append(
                    build_runner_error(
                        error_type="schema_validation_error",
                        message="; ".join(validation["errors"]),
                        sample_id=sample_id,
                        record_index=index,
                    )
                )
                continue
            legacy_plan = build_plan_from_dict(normalized, external_edit_units)
            consumer_plan = adapt_from_legacy_plan(legacy_plan)
            source_metadata = dict(normalized.get("metadata", {}))
            source_metadata.pop("commit_message", None)
            had_embedded_edit_units = bool(normalized.get("edit_units"))
            source_join_mode = "missing_edit_units"
            if had_embedded_edit_units:
                embedded_edit_units_count += 1
                source_join_mode = "embedded_edit_units"
            elif external_edit_units is not None:
                joined_from_external_edit_units_count += 1
                source_join_mode = "external_edit_units"
            source_join_mode_counts[source_join_mode] = source_join_mode_counts.get(source_join_mode, 0) + 1
            background_contract = consumer_plan.background_contract
            exported = consumer_plan.to_dict()
            exported["commit_id"] = consumer_plan.commit_id or source_metadata.get("commit_id") or sample_id
            exported["background_contract"] = background_contract
            exported["source_metadata"] = source_metadata
            exported["metadata"] = {
                **dict(exported.get("metadata", {})),
                "plan_source": "predicted",
            }
            exported_rows.append(exported)
            decision_distribution[consumer_plan.decision] = decision_distribution.get(consumer_plan.decision, 0) + 1
            predicted_k_key = str(consumer_plan.predicted_k)
            predicted_k_distribution[predicted_k_key] = predicted_k_distribution.get(predicted_k_key, 0) + 1
            if background_contract["evidence_complete"]:
                background_contract_complete_count += 1
            else:
                background_contract_incomplete_count += 1
            if legacy_plan.degraded:
                degraded_plan_count += 1
            if any(item.code == "unsupported_k_experimental" for item in legacy_plan.diagnostics):
                unsupported_k_experimental_count += 1
            if review_ready:
                if background_contract["evidence_complete"]:
                    review_ready_exported_count += 1
                    if len(ready_samples_preview) < 20:
                        ready_samples_preview.append(sample_id)
                else:
                    blocked_sample_count += 1
                    _record_blockers(
                        blocker_counts=review_ready_blocker_counts,
                        blocked_samples_preview=blocked_samples_preview,
                        sample_id=sample_id,
                        blockers=["background_evidence_incomplete"],
                    )
        except Exception as exc:  # noqa: BLE001 - keep exporting remaining rows.
            error_rows.append(
                build_runner_error(
                    error_type="schema_validation_error",
                    message=str(exc),
                    sample_id=sample_id,
                    record_index=index,
                )
            )

    summary = {
        "schema_version": "mica-consumer-plan-export-v1",
        "validate_only": validate_only,
        "sample_counts": {
            "total": len(rows) + len(parse_errors),
            "exported": len(exported_rows),
            "errors": len(error_rows),
        },
        "review_ready": review_ready,
        "review_ready_exported_count": review_ready_exported_count,
        "missing_release_decision_count": missing_release_decision_count,
        "missing_edit_units_count": missing_edit_units_count,
        "missing_assignment_scores_count": missing_assignment_scores_count,
        "background_contract_complete_count": background_contract_complete_count,
        "background_contract_incomplete_count": background_contract_incomplete_count,
        "decision_distribution": decision_distribution,
        "predicted_k_distribution": predicted_k_distribution,
        "degraded_plan_count": degraded_plan_count,
        "unsupported_k_experimental_count": unsupported_k_experimental_count,
        "joined_from_external_edit_units_count": joined_from_external_edit_units_count,
        "embedded_edit_units_count": embedded_edit_units_count,
        "source_join_mode_counts": source_join_mode_counts,
        "review_ready_blocker_counts": review_ready_blocker_counts,
        "blocked_sample_count": blocked_sample_count,
        "ready_samples_preview": ready_samples_preview,
        "blocked_samples_preview": blocked_samples_preview,
    }
    if not validate_only:
        atomic_write_jsonl(output_jsonl, exported_rows, overwrite=overwrite)
        if error_jsonl is not None and error_rows:
            atomic_write_jsonl(error_jsonl, error_rows, overwrite=overwrite)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        export_consumer_plans(
            prediction_jsonl=args.prediction_jsonl,
            output_jsonl=args.output_jsonl,
            error_jsonl=args.error_jsonl,
            edit_units_jsonl_or_manifest=args.edit_units_jsonl_or_manifest,
            overwrite=args.overwrite,
            validate_only=args.validate_only,
            strict=not args.lenient,
            review_ready=args.review_ready,
        )
    except (FileNotFoundError, FileExistsError, ValueError):
        return 2
    except Exception:
        return 3
    return 0


def _record_blockers(
    *,
    blocker_counts: dict[str, int],
    blocked_samples_preview: list[dict[str, Any]],
    sample_id: str,
    blockers: list[str],
) -> None:
    normalized_blockers = sorted({str(item) for item in blockers if item})
    if not normalized_blockers:
        return
    for blocker in normalized_blockers:
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    if len(blocked_samples_preview) < 20:
        blocked_samples_preview.append(
            {
                "sample_id": sample_id,
                "blockers": normalized_blockers,
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
