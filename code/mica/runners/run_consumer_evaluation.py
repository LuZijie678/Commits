from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from code.mica.consumers.pipeline import ConsumerPipeline
from code.mica.consumers.plan_schema import StructuredIntentPlan as ConsumerStructuredIntentPlan
from code.mica.consumers.plan_schema import adapt_from_legacy_plan
from code.mica.eval.consumer_metrics import aggregate_consumer_records
from code.mica.eval.consumer_records import ConsumerAggregateRecord, ConsumerEvaluationRecord
from code.mica.eval.consumer_stratification import stratify_consumer_records
from code.mica.runners.consumer_runner_utils import (
    atomic_write_json,
    atomic_write_jsonl,
    build_runner_error,
    ensure_writable_output,
    read_jsonl_records_with_errors,
)


VALID_PLAN_SOURCES = {"predicted", "oracle"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic consumer evaluation over structured-plan JSONL.")
    parser.add_argument("--plans", "--predicted-plan-jsonl", dest="plans", required=True)
    parser.add_argument("--per-sample-output", "--per-sample-output-jsonl", dest="per_sample_output", required=True)
    parser.add_argument("--aggregate-output", "--aggregate-output-json", dest="aggregate_output", required=True)
    parser.add_argument("--mode", default="deterministic")
    parser.add_argument("--plan-source", choices=sorted(VALID_PLAN_SOURCES), default="predicted")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--lenient", action="store_true", help="Continue past malformed JSONL lines and record structured row errors.")
    return parser


def run_consumer_evaluation(
    *,
    predicted_plan_jsonl: str | Path,
    per_sample_output_jsonl: str | Path,
    aggregate_output_json: str | Path,
    mode: str = "deterministic",
    plan_source: str = "predicted",
    overwrite: bool = False,
    validate_only: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    if plan_source not in VALID_PLAN_SOURCES:
        raise ValueError(f"plan_source must be one of {sorted(VALID_PLAN_SOURCES)}, got {plan_source!r}")
    if not validate_only:
        ensure_writable_output(per_sample_output_jsonl, overwrite=overwrite)
        ensure_writable_output(aggregate_output_json, overwrite=overwrite)

    rows, parse_errors = read_jsonl_records_with_errors(predicted_plan_jsonl, strict=strict)
    pipeline = ConsumerPipeline()
    if validate_only:
        return ConsumerAggregateRecord(
            mode=mode,
            plan_source=plan_source,
            validate_only=True,
            sample_counts={
                "total": len(rows) + len(parse_errors),
                "success": 0,
                "rejected": 0,
                "invalid_plan": 0,
                "verification_eligible": 0,
                "excluded_non_decompose": 0,
                "errors": len(parse_errors),
            },
            aggregate_metrics={},
            micro={},
            macro={},
            denominators={},
            excluded_samples={},
            stratified={},
        ).to_dict()

    per_sample_rows: list[tuple[int, dict[str, Any]]] = []
    for error in parse_errors:
        line_number = int(error.get("line_number") or 0)
        sample_id = str(error.get("sample_id") or f"__line_{line_number}__")
        per_sample_rows.append(
            (
                line_number,
                ConsumerEvaluationRecord(
                    sample_id=sample_id,
                    commit_id=None,
                    status="invalid_plan",
                    decision=None,
                    plan_source=plan_source,
                    predicted_k=None,
                    gold_k=None,
                    message=None,
                    verification={},
                    fallback={},
                    errors=[error],
                    background_contract={},
                    verification_eligible=False,
                    excluded_reason="invalid_input",
                    strata={"plan_source": plan_source},
                    input_contract={
                        "plan_shape": "unknown",
                        "used_raw_commit_message": False,
                        "used_raw_diff_direct_generation": False,
                    },
                ).to_dict(),
            )
        )

    for row in rows:
        line_number = int(row.pop("__line_number__", 0))
        sample_id = str(row.get("sample_id", ""))
        plan, plan_shape, coerce_error = _coerce_plan(row)
        if coerce_error is not None or plan is None:
            per_sample_rows.append(
                (
                    line_number,
                    ConsumerEvaluationRecord(
                        sample_id=sample_id or "__invalid_plan__",
                        commit_id=str(row.get("commit_id")) if row.get("commit_id") is not None else None,
                        status="invalid_plan",
                        decision=row.get("decision"),
                        plan_source=plan_source,
                        predicted_k=int(row["predicted_k"]) if row.get("predicted_k") is not None else None,
                        gold_k=int(row["gold_k"]) if row.get("gold_k") is not None else None,
                        message=None,
                        verification={},
                        fallback={},
                        errors=[
                            build_runner_error(
                                error_type="schema_validation_error",
                                message=coerce_error or "plan coercion failed",
                                sample_id=sample_id or None,
                            )
                        ],
                        background_contract={},
                        verification_eligible=False,
                        excluded_reason="invalid_plan",
                        strata={"plan_source": plan_source},
                        input_contract={
                            "plan_shape": plan_shape,
                            "used_raw_commit_message": False,
                            "used_raw_diff_direct_generation": False,
                        },
                    ).to_dict(),
                )
            )
            continue

        result = pipeline.generate(structured_plan=plan, mode=mode, verify=True)
        coverage = dict(result.verification.get("slot_coverage", {}))
        background_contract = plan.background_contract
        strata = _build_strata(plan, plan_source=plan_source, fallback_level=result.fallback.get("fallback_level"))
        per_sample_rows.append(
            (
                line_number,
                ConsumerEvaluationRecord(
                    sample_id=sample_id or plan.sample_id,
                    commit_id=plan.commit_id,
                    status=result.status,
                    decision=plan.decision,
                    plan_source=plan_source,
                    predicted_k=plan.predicted_k,
                    gold_k=int(plan.metadata["gold_k"]) if plan.metadata.get("gold_k") is not None else None,
                    message=result.message.to_dict() if result.message else None,
                    verification=dict(result.verification),
                    fallback=dict(result.fallback),
                    errors=list(result.errors),
                    background_contract=background_contract,
                    verification_eligible=plan.decision == "decompose",
                    excluded_reason=None if plan.decision == "decompose" else f"decision={plan.decision}",
                    strata=strata,
                    input_contract={
                        "plan_shape": plan_shape,
                        "used_raw_commit_message": False,
                        "used_raw_diff_direct_generation": False,
                        "declared_intent_coverage": coverage.get("intent_coverage_rate"),
                    },
                ).to_dict(),
            )
        )

    ordered_rows = [row for _, row in sorted(per_sample_rows, key=lambda item: item[0])]
    metrics = aggregate_consumer_records(ordered_rows, macro_group_by="predicted_k")
    summary = ConsumerAggregateRecord(
        mode=mode,
        plan_source=plan_source,
        validate_only=False,
        sample_counts={
            "total": len(ordered_rows),
            "success": sum(1 for row in ordered_rows if row["status"] == "success"),
            "rejected": sum(1 for row in ordered_rows if row["status"] == "rejected"),
            "invalid_plan": sum(1 for row in ordered_rows if row["status"] == "invalid_plan"),
            "verification_eligible": sum(1 for row in ordered_rows if row["verification_eligible"]),
            "excluded_non_decompose": sum(
                1 for row in ordered_rows if str(row.get("excluded_reason", "")).startswith("decision=")
            ),
            "errors": sum(1 for row in ordered_rows if row["status"] == "invalid_plan"),
        },
        aggregate_metrics=metrics["aggregate_metrics"],
        micro=metrics["micro"],
        macro=metrics["macro"],
        denominators=metrics["denominators"],
        excluded_samples={
            "non_decompose_or_invalid": [row["sample_id"] for row in ordered_rows if not row["verification_eligible"]],
            "excluded_reasons": metrics["excluded_reasons"],
        },
        stratified={
            "predicted_k": stratify_consumer_records(ordered_rows, group_by="predicted_k"),
            "plan_source": stratify_consumer_records(ordered_rows, group_by="plan_source"),
        },
    ).to_dict()
    atomic_write_jsonl(per_sample_output_jsonl, ordered_rows, overwrite=overwrite)
    atomic_write_json(aggregate_output_json, summary, overwrite=overwrite)
    return summary


def _coerce_plan(
    row: dict[str, Any],
) -> tuple[ConsumerStructuredIntentPlan | None, str, str | None]:
    try:
        if "decision" in row:
            return ConsumerStructuredIntentPlan.from_dict(row), "consumer", None
        return adapt_from_legacy_plan(row), "legacy", None
    except Exception:
        try:
            if "sample_id" in row and ("assignments" in row or "unit_to_slot" in row or "active_slots" in row):
                from code.mica.adapters.stage1_prediction_adapter import normalize_stage1_prediction_row
                from code.mica.plan_builder import build_plan_from_dict

                legacy_plan = build_plan_from_dict(normalize_stage1_prediction_row(row))
                return adapt_from_legacy_plan(legacy_plan), "prediction", None
        except Exception as inner_exc:  # noqa: BLE001 - return structured error to caller.
            return None, "prediction", str(inner_exc)
        plan_shape = "consumer" if "decision" in row else "legacy"
        return None, plan_shape, "unable to coerce plan"


def _build_strata(
    plan: ConsumerStructuredIntentPlan,
    *,
    plan_source: str,
    fallback_level: int | None,
) -> dict[str, Any]:
    file_roles = sorted({role for intent in plan.intents for role in intent.file_roles})
    background_types = sorted({record.background_assignment_type for record in plan.background_unit_records})
    gold_k = int(plan.metadata["gold_k"]) if plan.metadata.get("gold_k") is not None else None
    return {
        "predicted_k": plan.predicted_k,
        "gold_k": gold_k,
        "decision": plan.decision,
        "plan_source": plan_source,
        "background_contract.evidence_complete": plan.background_contract["evidence_complete"],
        "fallback_level": fallback_level,
        "file_role_composition": "+".join(file_roles) if file_roles else None,
        "source_type": plan.metadata.get("prediction_source") or plan.metadata.get("annotation_source"),
        "hard_b_flag": bool(plan.metadata.get("hard_b", False)),
        "multi_intent": bool((gold_k or plan.predicted_k) > 1),
        "background_assignment_type": "+".join(background_types) if background_types else None,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        run_consumer_evaluation(
            predicted_plan_jsonl=args.plans,
            per_sample_output_jsonl=args.per_sample_output,
            aggregate_output_json=args.aggregate_output,
            mode=args.mode,
            plan_source=args.plan_source,
            overwrite=args.overwrite,
            validate_only=args.validate_only,
            strict=not args.lenient,
        )
    except (FileNotFoundError, FileExistsError, ValueError):
        return 2
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
