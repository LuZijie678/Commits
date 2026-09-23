from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, read_jsonl, write_json, write_jsonl


REVIEWED_DIAGNOSTIC_SCHEMA_VERSION = "mica-stage1-v2-reviewed-diagnostic-analysis-v1"
FOLLOWUP_QUEUE_SCHEMA_VERSION = "mica-stage1-v2-reviewed-diagnostic-followup-v1"
GUIDELINE_DRAFT_SCHEMA_VERSION = "mica-stage1-v2-guideline-revision-draft-v1"
DEFAULT_PROTOCOL_VERSION = "stage1-v2-protocol"
DEFAULT_KMAX = 4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def analyze_reviewed_diagnostic_markings(
    reviewed_rows: list[dict[str, Any]],
    *,
    blinding_map: dict[str, Any] | None = None,
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    kmax: int = DEFAULT_KMAX,
    created_at: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Summarize reviewed LLM markings without promoting them to formal gold."""
    metadata_by_sample = _metadata_by_sample(blinding_map or {})
    exact_k_distribution: Counter[str] = Counter()
    exact_k_status_distribution: Counter[str] = Counter()
    label_distribution: Counter[str] = Counter()
    background_type_distribution: Counter[str] = Counter()
    tag_distribution: Counter[str] = Counter()
    priority_distribution: Counter[str] = Counter()
    rows_with_background = 0
    rows_with_shared_or_uncertain = 0
    rows_with_review_notes = 0
    rows_with_overflow = 0
    rows_with_k_gt_kmax = 0
    followup_rows: list[dict[str, Any]] = []

    for row in sorted(reviewed_rows, key=lambda item: str(item.get("sample_id") or "")):
        sample_id = str(row.get("sample_id") or "")
        marking = _marking_payload(row)
        exact_k = marking.get("exact_k")
        exact_k_key = "None" if exact_k is None else str(exact_k)
        exact_k_distribution[exact_k_key] += 1
        exact_k_status = str(marking.get("exact_k_status") or "unspecified")
        exact_k_status_distribution[exact_k_status] += 1
        metadata = metadata_by_sample.get(sample_id, {})
        provisional_tags = sorted(str(tag) for tag in metadata.get("provisional_tags", []) if str(tag))
        tag_distribution.update(provisional_tags)

        unit_assignments = list(marking.get("unit_assignments") or [])
        labels = [str(item.get("label") or "missing_label") for item in unit_assignments if isinstance(item, dict)]
        label_distribution.update(labels)
        background_types = [
            str(item.get("background_type") or "unspecified")
            for item in unit_assignments
            if isinstance(item, dict) and str(item.get("label") or "") == "background"
        ]
        background_type_distribution.update(background_types)
        if background_types:
            rows_with_background += 1
        if any(label in {"shared_support", "uncertain", "mixed"} for label in labels):
            rows_with_shared_or_uncertain += 1
        review_notes = list(marking.get("review_notes") or [])
        if review_notes:
            rows_with_review_notes += 1
        if exact_k is None or "overflow" in exact_k_status or "ambiguous" in exact_k_status:
            rows_with_overflow += 1
        if isinstance(exact_k, int) and exact_k > kmax:
            rows_with_k_gt_kmax += 1

        priority, reasons = _followup_priority(
            exact_k=exact_k,
            exact_k_status=exact_k_status,
            labels=labels,
            background_types=background_types,
            review_notes=review_notes,
            provisional_tags=provisional_tags,
            kmax=kmax,
        )
        priority_distribution[priority] += 1
        if priority != "p3_low":
            followup_rows.append(
                {
                    "schema_version": FOLLOWUP_QUEUE_SCHEMA_VERSION,
                    "protocol_version": protocol_version,
                    "sample_id": sample_id,
                    "original_sample_id": metadata.get("original_sample_id"),
                    "repository": metadata.get("repository"),
                    "commit_id": metadata.get("commit_id"),
                    "priority": priority,
                    "followup_reasons": reasons,
                    "exact_k": exact_k,
                    "exact_k_status": exact_k_status,
                    "provisional_tags": provisional_tags,
                    "review_notes": review_notes,
                    "formal_human_evidence": False,
                    "allowed_use": "guideline_debug_and_human_followup_only",
                    "blocked_use": [
                        "formal_pre_adjudication_agreement",
                        "adjudicated_gold",
                        "training",
                        "stage2_entry",
                    ],
                    "requested_action": _requested_action(priority, reasons),
                }
            )

    record_count = len(reviewed_rows)
    report = {
        "schema_version": REVIEWED_DIAGNOSTIC_SCHEMA_VERSION,
        "protocol_version": protocol_version,
        "artifact_id": "calibration_round_2_reviewed_diagnostic_analysis",
        "created_at": created_at or utc_now_iso(),
        "input_artifact_id": "human_reviewed_codex_calibration_round_2_markings",
        "round_label": "calibration_round_2",
        "record_count": record_count,
        "formal_human_evidence": False,
        "formal_evidence_blocker": "not_independent_double_annotation_or_adjudication",
        "stage1_v2_training_allowed": False,
        "stage2_entry_allowed": False,
        "kmax_for_diagnostic_triage": kmax,
        "exact_k_distribution": dict(sorted(exact_k_distribution.items())),
        "exact_k_status_distribution": dict(sorted(exact_k_status_distribution.items())),
        "unit_label_distribution": dict(sorted(label_distribution.items())),
        "background_type_distribution": dict(sorted(background_type_distribution.items())),
        "provisional_tag_distribution": dict(sorted(tag_distribution.items())),
        "priority_distribution": dict(sorted(priority_distribution.items())),
        "diagnostic_counts": {
            "rows_with_background": rows_with_background,
            "rows_with_shared_or_uncertain_or_mixed": rows_with_shared_or_uncertain,
            "rows_with_review_notes": rows_with_review_notes,
            "rows_with_overflow_or_ambiguous_status": rows_with_overflow,
            "rows_with_exact_k_gt_kmax": rows_with_k_gt_kmax,
            "followup_queue_count": len(followup_rows),
        },
        "gate_interpretation": {
            "pre_adjudication_agreement_usable": False,
            "adjudicated_gold_usable": False,
            "guideline_status": "diagnostic_revision_input_only",
            "reason": "Reviewed Codex markings are not independent A/B annotations and cannot satisfy formal human gates.",
        },
        "highest_priority_sample_ids": [
            row["sample_id"] for row in followup_rows if row["priority"] == "p0_blocking_review"
        ],
    }
    draft = build_guideline_revision_draft(report, followup_rows)
    return report, followup_rows, draft


def write_reviewed_diagnostic_outputs(
    *,
    reviewed_markings_path: str | Path,
    blinding_map_path: str | Path,
    report_path: str | Path,
    followup_queue_path: str | Path,
    guideline_revision_draft_path: str | Path,
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    kmax: int = DEFAULT_KMAX,
    created_at: str | None = None,
) -> dict[str, Any]:
    reviewed_rows = read_jsonl(reviewed_markings_path)
    blinding_map = read_json(blinding_map_path)
    report, followup_rows, draft = analyze_reviewed_diagnostic_markings(
        reviewed_rows,
        blinding_map=blinding_map,
        protocol_version=protocol_version,
        kmax=kmax,
        created_at=created_at,
    )
    write_json(report_path, report)
    write_jsonl(followup_queue_path, followup_rows)
    Path(guideline_revision_draft_path).parent.mkdir(parents=True, exist_ok=True)
    Path(guideline_revision_draft_path).write_text(draft, encoding="utf-8")
    return {
        "report": report,
        "followup_queue_count": len(followup_rows),
        "report_path": str(report_path),
        "followup_queue_path": str(followup_queue_path),
        "guideline_revision_draft_path": str(guideline_revision_draft_path),
    }


def build_guideline_revision_draft(report: dict[str, Any], followup_rows: list[dict[str, Any]]) -> str:
    priority_counts = report.get("priority_distribution", {})
    diagnostic_counts = report.get("diagnostic_counts", {})
    high_priority = report.get("highest_priority_sample_ids", [])
    lines = [
        "# Stage1-v2 Guideline Pilot V3 Revision Draft",
        "",
        "Status: `revision_draft_only`.",
        "",
        "This draft is derived from user-reviewed Codex R2 diagnostic markings. It is not a final frozen guideline and does not convert the diagnostic sidecar into formal gold.",
        "",
        "## Evidence Scope",
        "",
        f"- Input artifact: `{report.get('input_artifact_id')}`",
        f"- Record count: `{report.get('record_count')}`",
        "- Formal human evidence: `false`",
        "- Formal blocker: `not_independent_double_annotation_or_adjudication`",
        "- Training allowed: `false`",
        "- Stage 2 entry allowed: `false`",
        "",
        "## Diagnostic Triage",
        "",
        f"- Priority counts: `{priority_counts}`",
        f"- Rows with background: `{diagnostic_counts.get('rows_with_background', 0)}`",
        f"- Rows with shared/uncertain/mixed labels: `{diagnostic_counts.get('rows_with_shared_or_uncertain_or_mixed', 0)}`",
        f"- Rows with review notes: `{diagnostic_counts.get('rows_with_review_notes', 0)}`",
        f"- Rows with overflow/ambiguous status: `{diagnostic_counts.get('rows_with_overflow_or_ambiguous_status', 0)}`",
        f"- Rows with exact_k > Kmax: `{diagnostic_counts.get('rows_with_exact_k_gt_kmax', 0)}`",
        f"- P0 samples: `{high_priority}`",
        "",
        "## Proposed Revision Targets",
        "",
        "1. Clarify `k > Kmax` and overflow handling: do not force complex commits into `k<=4`; route them to stress/overflow with explicit rationale.",
        "2. Clarify generated/static previewer output: generated files are background only when the diff evidence shows they are build artifacts tied to a foreground change.",
        "3. Clarify lockfile/dependency changes: lockfiles are background only when mechanically synchronized with a foreground dependency/runtime change.",
        "4. Clarify shared support vs foreground: shared_support must identify which intent(s) it supports and must not hide independent action-object edits.",
        "5. Clarify uncertain/mixed units: evidence-insufficient units should remain uncertain or mixed; do not coerce them into background or a foreground intent.",
        "6. Clarify hard-single boundaries: required tests/docs/config can merge with a main intent, but independent infrastructure or maintenance remains separate.",
        "",
        "## Follow-up Queue Policy",
        "",
        "- P0 rows require direct human review before any guideline decision.",
        "- P1 rows should be sampled in the next calibration discussion.",
        "- P2 rows can be used as secondary examples.",
        "- No row in this queue is eligible for formal training, Kmax, or Stage 2 evidence.",
        "",
        "## P0 Follow-up Samples",
        "",
    ]
    for row in followup_rows:
        if row["priority"] != "p0_blocking_review":
            continue
        lines.append(
            f"- `{row['sample_id']}`: exact_k=`{row.get('exact_k')}`, status=`{row.get('exact_k_status')}`, reasons=`{row.get('followup_reasons')}`"
        )
    lines.append("")
    return "\n".join(lines)


def _metadata_by_sample(blinding_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = blinding_map.get("rows") if isinstance(blinding_map, dict) else []
    if not isinstance(rows, list):
        return {}
    return {str(row.get("sample_id") or ""): row for row in rows if isinstance(row, dict)}


def _marking_payload(row: dict[str, Any]) -> dict[str, Any]:
    marking = row.get("codex_marking")
    if isinstance(marking, dict):
        return marking
    return row


def _followup_priority(
    *,
    exact_k: Any,
    exact_k_status: str,
    labels: list[str],
    background_types: list[str],
    review_notes: list[Any],
    provisional_tags: list[str],
    kmax: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if exact_k is None:
        reasons.append("exact_k_missing_or_overflow")
    if isinstance(exact_k, int) and exact_k > kmax:
        reasons.append("exact_k_exceeds_kmax")
    if "overflow" in exact_k_status or "ambiguous" in exact_k_status:
        reasons.append("overflow_or_ambiguous_status")
    if "needs_close_review" in exact_k_status:
        reasons.append("exact_k_needs_close_review")
    elif "needs_review" in exact_k_status:
        reasons.append("exact_k_needs_review")
    if any(label in {"shared_support", "uncertain", "mixed"} for label in labels):
        reasons.append("shared_uncertain_or_mixed_unit")
    if review_notes:
        reasons.append("review_notes_present")
    if {"ambiguous_boundary", "probable_k4_or_complex"} & set(provisional_tags):
        reasons.append("high_complexity_provisional_stratum")
    if any(item in {"generated", "vendor", "lockfile"} for item in background_types):
        reasons.append("background_type_requires_evidence_check")

    if any(reason in reasons for reason in ("exact_k_missing_or_overflow", "exact_k_exceeds_kmax", "overflow_or_ambiguous_status")):
        return "p0_blocking_review", reasons
    if any(reason in reasons for reason in ("exact_k_needs_close_review", "shared_uncertain_or_mixed_unit", "high_complexity_provisional_stratum")):
        return "p1_guideline_review", reasons
    if reasons:
        return "p2_secondary_review", reasons
    return "p3_low", reasons


def _requested_action(priority: str, reasons: list[str]) -> str:
    if priority == "p0_blocking_review":
        return "Human reviewer must resolve overflow/Kmax/ambiguity before this sample can inform guideline decisions."
    if priority == "p1_guideline_review":
        return "Use in guideline discussion to clarify split/merge/background/shared-support rules."
    if priority == "p2_secondary_review":
        return "Optional secondary review for examples and edge-case documentation."
    return "No immediate action."
