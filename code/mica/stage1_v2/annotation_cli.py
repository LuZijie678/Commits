from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.stage1_v2.audit_log import append_annotation_audit_event, compute_record_hash


ANNOTATION_DRAFT_SCHEMA_VERSION = "mica-stage1-v2-annotation-draft-v1"
ANNOTATION_SUBMISSION_SCHEMA_VERSION = "mica-stage1-v2-annotation-submission-v1"
TOOL_VERSION = "stage1-v2-annotation-cli-v1"
PUBLIC_SAMPLE_FIELDS = {
    "schema_version",
    "sample_id",
    "commit_id",
    "repository",
    "guideline_version",
    "annotation_version",
    "normalized_diff",
    "git_diff",
    "edit_units",
    "allowed_context",
    "repository_language",
    "package",
    "diff_reference",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Stage1-v2 annotation CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show-sample", help="Show one sanitized sample from a queue.")
    show.add_argument("--queue", required=True)
    show.add_argument("--sample-id", required=True)

    init = subparsers.add_parser("init-draft", help="Create a local annotation draft template.")
    init.add_argument("--queue", required=True)
    init.add_argument("--sample-id", required=True)
    init.add_argument("--annotator-id", required=True)
    init.add_argument("--actor-role", required=True)
    init.add_argument("--campaign-id", required=True)
    init.add_argument("--batch-id", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--audit-log", required=True)

    validate = subparsers.add_parser("validate-draft", help="Validate a draft payload.")
    validate.add_argument("--draft", required=True)

    submit = subparsers.add_parser("submit-draft", help="Submit a draft as an immutable revision.")
    submit.add_argument("--draft", required=True)
    submit.add_argument("--submission-root", required=True)
    submit.add_argument("--audit-log", required=True)

    return parser


def sanitize_annotation_sample(row: dict[str, Any]) -> dict[str, Any]:
    task_type = "real_count" if "annotator_a_exact_k" in row or "adjudicated_exact_k" in row else "real_alignment"
    sanitized = {key: value for key, value in row.items() if key in PUBLIC_SAMPLE_FIELDS}
    sanitized["task_type"] = task_type
    return sanitized


def initialize_annotation_draft(
    *,
    queue_path: str | Path,
    sample_id: str,
    annotator_id: str,
    actor_role: str,
    campaign_id: str,
    batch_id: str,
    output_path: str | Path,
    audit_log_path: str | Path,
) -> dict[str, Any]:
    row = _load_sample(queue_path, sample_id)
    public_sample = sanitize_annotation_sample(row)
    draft = {
        "schema_version": ANNOTATION_DRAFT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "sample_id": sample_id,
        "annotator_id": annotator_id,
        "actor_role": actor_role,
        "task_type": public_sample["task_type"],
        "guideline_version": str(row.get("guideline_version") or ""),
        "annotation_version": str(row.get("annotation_version") or ""),
        "source_queue_path": str(queue_path),
        "sample_snapshot_hash": compute_record_hash(public_sample),
        "public_sample": public_sample,
        "draft_status": "draft",
        "response": _empty_response_template(public_sample["task_type"]),
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, draft)
    append_annotation_audit_event(
        log_path=audit_log_path,
        campaign_id=campaign_id,
        batch_id=batch_id,
        sample_id=sample_id,
        actor_id=annotator_id,
        actor_role=actor_role,
        event_type="opened",
        guideline_version=draft["guideline_version"],
        tool_version=TOOL_VERSION,
        new_record_hash=compute_record_hash(draft),
        details={"draft_path": str(target)},
    )
    return draft


def validate_annotation_draft(draft: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    required = (
        "schema_version",
        "campaign_id",
        "batch_id",
        "sample_id",
        "annotator_id",
        "actor_role",
        "task_type",
        "guideline_version",
        "annotation_version",
        "sample_snapshot_hash",
        "public_sample",
        "response",
    )
    for field_name in required:
        if draft.get(field_name) in (None, "", []):
            errors.append(f"missing_{field_name}")
    if str(draft.get("schema_version") or "") != ANNOTATION_DRAFT_SCHEMA_VERSION:
        errors.append("invalid_schema_version")
    task_type = str(draft.get("task_type") or "")
    response = dict(draft.get("response") or {})
    if task_type == "real_count":
        if response.get("exact_k") is None:
            errors.append("missing_exact_k")
    elif task_type == "real_alignment":
        annotation = dict(response.get("annotation") or {})
        if annotation.get("exact_k") is None:
            errors.append("missing_annotation_exact_k")
        if not isinstance(annotation.get("unit_labels"), dict):
            errors.append("missing_unit_labels")
        if not isinstance(annotation.get("intents"), list):
            errors.append("missing_intents")
    else:
        errors.append("invalid_task_type")
    return {"valid": not errors, "errors": errors}


def submit_annotation_draft(
    *,
    draft_path: str | Path,
    submission_root: str | Path,
    audit_log_path: str | Path,
) -> dict[str, Any]:
    draft = read_json(draft_path)
    validation = validate_annotation_draft(draft)
    if not validation["valid"]:
        append_annotation_audit_event(
            log_path=audit_log_path,
            campaign_id=str(draft.get("campaign_id") or ""),
            batch_id=str(draft.get("batch_id") or ""),
            sample_id=str(draft.get("sample_id") or ""),
            actor_id=str(draft.get("annotator_id") or ""),
            actor_role=str(draft.get("actor_role") or ""),
            event_type="validation_failed",
            guideline_version=str(draft.get("guideline_version") or ""),
            tool_version=TOOL_VERSION,
            new_record_hash=compute_record_hash(draft),
            details={"errors": list(validation["errors"])},
        )
        raise ValueError(f"Invalid annotation draft: {validation['errors']}")

    submission_dir = (
        Path(submission_root)
        / str(draft["actor_role"])
        / str(draft["annotator_id"])
        / str(draft["sample_id"])
    )
    submission_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(submission_dir.glob("submission_r*.json"))
    previous_hash = None
    if existing:
        previous_payload = read_json(existing[-1])
        previous_hash = compute_record_hash(previous_payload)
    revision_index = len(existing) + 1
    submission = {
        "schema_version": ANNOTATION_SUBMISSION_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "campaign_id": draft["campaign_id"],
        "batch_id": draft["batch_id"],
        "sample_id": draft["sample_id"],
        "annotator_id": draft["annotator_id"],
        "actor_role": draft["actor_role"],
        "task_type": draft["task_type"],
        "guideline_version": draft["guideline_version"],
        "annotation_version": draft["annotation_version"],
        "sample_snapshot_hash": draft["sample_snapshot_hash"],
        "public_sample": draft["public_sample"],
        "response": draft["response"],
        "revision_index": revision_index,
        "supersedes_submission_hash": previous_hash,
    }
    submission_path = submission_dir / f"submission_r{revision_index:04d}.json"
    write_json(submission_path, submission)
    new_hash = compute_record_hash(submission)
    if previous_hash is not None:
        append_annotation_audit_event(
            log_path=audit_log_path,
            campaign_id=str(draft["campaign_id"]),
            batch_id=str(draft["batch_id"]),
            sample_id=str(draft["sample_id"]),
            actor_id=str(draft["annotator_id"]),
            actor_role=str(draft["actor_role"]),
            event_type="superseded",
            guideline_version=str(draft["guideline_version"]),
            tool_version=TOOL_VERSION,
            old_record_hash=previous_hash,
            new_record_hash=new_hash,
            details={"submission_path": str(submission_path)},
        )
    append_annotation_audit_event(
        log_path=audit_log_path,
        campaign_id=str(draft["campaign_id"]),
        batch_id=str(draft["batch_id"]),
        sample_id=str(draft["sample_id"]),
        actor_id=str(draft["annotator_id"]),
        actor_role=str(draft["actor_role"]),
        event_type="submitted",
        guideline_version=str(draft["guideline_version"]),
        tool_version=TOOL_VERSION,
        old_record_hash=previous_hash,
        new_record_hash=new_hash,
        details={"submission_path": str(submission_path)},
    )
    return {
        "submission_path": str(submission_path),
        "submission_hash": new_hash,
        "revision_index": revision_index,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "show-sample":
        row = _load_sample(args.queue, args.sample_id)
        print(json.dumps(sanitize_annotation_sample(row), ensure_ascii=False, indent=2))
        return 0
    if args.command == "init-draft":
        draft = initialize_annotation_draft(
            queue_path=args.queue,
            sample_id=args.sample_id,
            annotator_id=args.annotator_id,
            actor_role=args.actor_role,
            campaign_id=args.campaign_id,
            batch_id=args.batch_id,
            output_path=args.output,
            audit_log_path=args.audit_log,
        )
        print(json.dumps({"draft_path": args.output, "sample_id": draft["sample_id"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate-draft":
        draft = read_json(args.draft)
        print(json.dumps(validate_annotation_draft(draft), ensure_ascii=False, indent=2))
        return 0
    if args.command == "submit-draft":
        result = submit_annotation_draft(
            draft_path=args.draft,
            submission_root=args.submission_root,
            audit_log_path=args.audit_log,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    raise ValueError(f"Unknown command: {args.command}")


def _load_sample(queue_path: str | Path, sample_id: str) -> dict[str, Any]:
    for row in read_jsonl(queue_path):
        if str(row.get("sample_id") or "") == sample_id:
            return row
    raise ValueError(f"sample_id not found in queue: {sample_id}")


def _empty_response_template(task_type: str) -> dict[str, Any]:
    if task_type == "real_count":
        return {"exact_k": None, "notes": None}
    return {
        "annotation": {
            "exact_k": None,
            "unit_labels": {},
            "intents": [],
        },
        "notes": None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
