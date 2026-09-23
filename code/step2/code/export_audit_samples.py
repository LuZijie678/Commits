#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from experiment_tooling_common import diff_excerpt, read_csv_rows, read_jsonl_rows, safe_strip, stratified_sample


MESSAGE_FIELDS = [
    "sample_id",
    "repo",
    "type_pair",
    "intent_subjects",
    "synthetic_subject",
    "synthetic_diff_excerpt",
    "covers_all_required_intents",
    "faithful_to_sources",
    "no_artifact",
    "subject_naturalness",
    "length_ok",
    "final_decision",
    "annotator_confidence",
    "notes",
]

STRUCTURAL_FIELDS = [
    "sample_id",
    "repo",
    "type_pair",
    "construction_route",
    "logical_intent_count",
    "intent_cardinality",
    "structure_pattern",
    "difficulty_level",
    "difficulty_name",
    "training_focus",
    "realism_score",
    "rho",
    "identifier_overlap_score",
    "dependency_hint_score",
    "main_topic_coherence",
    "shared_file_count",
    "shared_file_ratio",
    "same_file_hunk_count",
    "module_overlap_score",
    "file_role_mix",
    "patch_conflict_risk",
    "perturbation_plan_summary",
    "perturbation_applied_summary",
    "synthetic_subject",
    "synthetic_diff_excerpt",
    "realistic_diff_structure",
    "difficulty_assignment_reasonable",
    "structure_pattern_reasonable",
    "artificial_boundary_visible",
    "shared_file_behavior_reasonable",
    "identifier_overlap_reasonable",
    "final_realism_label",
    "annotator_confidence",
    "notes",
]

SOURCE_FIELDS = [
    "sha",
    "repo",
    "type",
    "subject",
    "diff_excerpt",
    "is_single_intent",
    "confidence",
    "notes",
]


def _load_rows(input_path: Path) -> list[dict[str, Any]]:
    rows, _warnings = read_jsonl_rows(input_path)
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _compact_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return safe_strip(value)


def _stringify_list(values: Any) -> str:
    if isinstance(values, list):
        return " | ".join(safe_strip(item) for item in values if safe_strip(item))
    return safe_strip(values)


def _feature_value(row: dict[str, Any], name: str) -> str:
    payload = row.get("difficulty_features", {}) or {}
    value = payload.get(name)
    if value is None:
        return ""
    return str(value)


def _message_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id", ""),
        "repo": row.get("repo", ""),
        "type_pair": row.get("type_pair", ""),
        "intent_subjects": " | ".join(row.get("intent_subjects", []) or []),
        "synthetic_subject": row.get("synthetic_subject", ""),
        "synthetic_diff_excerpt": diff_excerpt(safe_strip(row.get("synthetic_diff", ""))),
        "covers_all_required_intents": "",
        "faithful_to_sources": "",
        "no_artifact": "",
        "subject_naturalness": "",
        "length_ok": "",
        "final_decision": "",
        "annotator_confidence": "",
        "notes": "",
    }


def _structural_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id", ""),
        "repo": row.get("repo", ""),
        "type_pair": row.get("type_pair", ""),
        "construction_route": row.get("construction_route", ""),
        "logical_intent_count": row.get("logical_intent_count", row.get("intent_count", "")),
        "intent_cardinality": row.get("intent_cardinality", ""),
        "structure_pattern": row.get("structure_pattern", ""),
        "difficulty_level": row.get("difficulty_level", ""),
        "difficulty_name": row.get("difficulty_name", ""),
        "training_focus": _stringify_list(row.get("training_focus", [])),
        "realism_score": "" if row.get("realism_score") is None else str(row.get("realism_score")),
        "rho": "" if row.get("rho") is None else str(row.get("rho")),
        "identifier_overlap_score": _feature_value(row, "identifier_overlap_score"),
        "dependency_hint_score": _feature_value(row, "dependency_hint_score"),
        "main_topic_coherence": _feature_value(row, "main_topic_coherence"),
        "shared_file_count": _feature_value(row, "shared_file_count"),
        "shared_file_ratio": _feature_value(row, "shared_file_ratio"),
        "same_file_hunk_count": _feature_value(row, "same_file_hunk_count"),
        "module_overlap_score": _feature_value(row, "module_overlap_score"),
        "file_role_mix": _feature_value(row, "file_role_mix"),
        "patch_conflict_risk": _feature_value(row, "patch_conflict_risk"),
        "perturbation_plan_summary": _compact_json(row.get("perturbation_plan")),
        "perturbation_applied_summary": _compact_json(row.get("perturbation_applied")),
        "synthetic_subject": row.get("synthetic_subject", ""),
        "synthetic_diff_excerpt": diff_excerpt(safe_strip(row.get("synthetic_diff", ""))),
        "realistic_diff_structure": "",
        "difficulty_assignment_reasonable": "",
        "structure_pattern_reasonable": "",
        "artificial_boundary_visible": "",
        "shared_file_behavior_reasonable": "",
        "identifier_overlap_reasonable": "",
        "final_realism_label": "",
        "annotator_confidence": "",
        "notes": "",
    }


def export_audit_csv(
    *,
    input_path: Path,
    output_path: Path,
    audit_type: str,
    n: int,
    seed: int,
    stratify_fields: list[str] | None = None,
) -> None:
    rows = _load_rows(input_path)
    sampled = stratified_sample(rows, n, seed, stratify_fields or [])
    if audit_type == "message":
        payload = [_message_audit_row(row) for row in sampled]
        _write_csv(output_path, MESSAGE_FIELDS, payload)
        return
    if audit_type == "structural":
        payload = [_structural_audit_row(row) for row in sampled]
        _write_csv(output_path, STRUCTURAL_FIELDS, payload)
        return
    raise ValueError(f"Unsupported audit_type: {audit_type}")


def export_source_audit_csv(*, source_csv_path: Path, output_path: Path, n: int, seed: int) -> None:
    rows, _warnings = read_csv_rows(source_csv_path)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "sha": row.get("sha", ""),
                "repo": row.get("repo", ""),
                "type": row.get("type", ""),
                "subject": row.get("subject", ""),
                "git_diff": row.get("git_diff", ""),
            }
        )
    sampled = stratified_sample(normalized, n, seed, [])
    payload = [
        {
            "sha": row.get("sha", ""),
            "repo": row.get("repo", ""),
            "type": row.get("type", ""),
            "subject": row.get("subject", ""),
            "diff_excerpt": diff_excerpt(safe_strip(row.get("git_diff", ""))),
            "is_single_intent": "",
            "confidence": "",
            "notes": "",
        }
        for row in sampled
    ]
    _write_csv(output_path, SOURCE_FIELDS, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Step2 audit CSV templates for human review.")
    parser.add_argument("--input", default="")
    parser.add_argument("--source-data", default="")
    parser.add_argument("--audit-type", required=True, choices=["message", "structural", "source"])
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stratify", action="append", default=[])
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.audit_type == "source":
        if not args.source_data:
            raise SystemExit("--source-data is required for source audit export")
        export_source_audit_csv(
            source_csv_path=Path(args.source_data),
            output_path=Path(args.out),
            n=max(0, int(args.n)),
            seed=int(args.seed),
        )
        return
    if not args.input:
        raise SystemExit("--input is required for message/structural audit export")
    export_audit_csv(
        input_path=Path(args.input),
        output_path=Path(args.out),
        audit_type=args.audit_type,
        n=max(0, int(args.n)),
        seed=int(args.seed),
        stratify_fields=list(args.stratify),
    )


if __name__ == "__main__":
    main()
