from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any


DEFAULT_SCALAR_KEYS = {
    "sample_id": "sample_overlap",
    "sha": "commit_overlap",
    "normalized_diff_hash": "normalized_diff_overlap",
    "edit_unit_fingerprint": "edit_unit_fingerprint_overlap",
    "atomic_family_id": "atomic_family_overlap",
    "construction_group": "construction_group_overlap",
    "pr_id": "pr_overlap",
    "repository_mirror_id": "repository_mirror_overlap",
    "cherry_pick_fingerprint": "cherry_pick_overlap",
    "backport_fingerprint": "backport_overlap",
    "revert_fingerprint": "revert_overlap",
}
DEFAULT_LIST_KEYS = {
    "source_atomic_commit_ids": "atomic_source_overlap",
}
NEAR_DUPLICATE_ALGORITHM_VERSION = "sequence_matcher_v1"


def audit_stage1_v2_leakage(
    rows_by_split: dict[str, list[dict[str, Any]]],
    *,
    near_duplicate_threshold: float = 0.98,
    near_duplicate_limit: int = 5000,
) -> dict[str, Any]:
    split_names = sorted(rows_by_split)
    scalar_report = {
        name: _cross_split_scalar_overlap(rows_by_split, field)
        for field, name in DEFAULT_SCALAR_KEYS.items()
    }
    list_report = {
        name: _cross_split_list_overlap(rows_by_split, field)
        for field, name in DEFAULT_LIST_KEYS.items()
    }
    near_duplicate = _near_duplicate_report(
        rows_by_split,
        threshold=near_duplicate_threshold,
        comparison_limit=near_duplicate_limit,
    )
    violations = [
        name
        for name, payload in {**scalar_report, **list_report}.items()
        if int(payload["overlap_count"]) > 0
    ]
    if near_duplicate["available"] and int(near_duplicate["overlap_count"]) > 0:
        violations.append("near_duplicate_overlap")
    ready = (
        not violations
        and near_duplicate["available"]
        and near_duplicate["skipped_due_to_size"] is False
    )
    return {
        "schema_version": "mica-stage1-v2-leakage-report-v1",
        "split_names": split_names,
        "required_zero_overlap_keys": sorted(list(DEFAULT_SCALAR_KEYS.values()) + list(DEFAULT_LIST_KEYS.values())),
        "scalar_overlap": scalar_report,
        "list_overlap": list_report,
        "near_duplicate": near_duplicate,
        "violations": violations,
        "leakage_clean": ready,
    }


def fingerprint_text(value: Any) -> str:
    text = str(value or "").strip()
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text else ""


def _cross_split_scalar_overlap(rows_by_split: dict[str, list[dict[str, Any]]], field: str) -> dict[str, Any]:
    values_by_split = {
        split: {str(row.get(field) or "") for row in rows if str(row.get(field) or "")}
        for split, rows in rows_by_split.items()
    }
    overlap_count = 0
    overlap_pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(sorted(values_by_split)):
        for right in sorted(values_by_split)[left_index + 1 :]:
            overlap = sorted(values_by_split[left] & values_by_split[right])
            overlap_count += len(overlap)
            if overlap:
                overlap_pairs.append(
                    {
                        "left_split": left,
                        "right_split": right,
                        "count": len(overlap),
                        "examples": overlap[:5],
                    }
                )
    return {"overlap_count": overlap_count, "pairs": overlap_pairs}


def _cross_split_list_overlap(rows_by_split: dict[str, list[dict[str, Any]]], field: str) -> dict[str, Any]:
    values_by_split = {
        split: {
            str(item)
            for row in rows
            for item in _normalize_string_list(row.get(field))
            if str(item)
        }
        for split, rows in rows_by_split.items()
    }
    overlap_count = 0
    overlap_pairs: list[dict[str, Any]] = []
    ordered_splits = sorted(values_by_split)
    for left_index, left in enumerate(ordered_splits):
        for right in ordered_splits[left_index + 1 :]:
            overlap = sorted(values_by_split[left] & values_by_split[right])
            overlap_count += len(overlap)
            if overlap:
                overlap_pairs.append(
                    {
                        "left_split": left,
                        "right_split": right,
                        "count": len(overlap),
                        "examples": overlap[:5],
                    }
                )
    return {"overlap_count": overlap_count, "pairs": overlap_pairs}


def _near_duplicate_report(
    rows_by_split: dict[str, list[dict[str, Any]]],
    *,
    threshold: float,
    comparison_limit: int,
) -> dict[str, Any]:
    rows = [
        dict(row, split=split)
        for split, split_rows in rows_by_split.items()
        for row in split_rows
    ]
    candidate_pairs = 0
    overlap_count = 0
    examples: list[dict[str, Any]] = []
    exact_signature_pairs = _cross_split_scalar_overlap(rows_by_split, "edit_unit_fingerprint")
    if int(exact_signature_pairs["overlap_count"]) > 0:
        overlap_count += int(exact_signature_pairs["overlap_count"])
    text_rows = [
        row
        for row in rows
        if _near_duplicate_text(row)
    ]
    available = bool(text_rows) or int(exact_signature_pairs["overlap_count"]) >= 0
    comparisons_skipped = False
    if len(text_rows) >= 2:
        grouped_by_split: dict[str, list[dict[str, Any]]] = {}
        for row in text_rows:
            grouped_by_split.setdefault(str(row["split"]), []).append(row)
        split_names = sorted(grouped_by_split)
        for left_index, left_split in enumerate(split_names):
            for right_split in split_names[left_index + 1 :]:
                for left_row in grouped_by_split[left_split]:
                    for right_row in grouped_by_split[right_split]:
                        candidate_pairs += 1
                        if candidate_pairs > comparison_limit:
                            comparisons_skipped = True
                            break
                        similarity = SequenceMatcher(
                            None,
                            _near_duplicate_text(left_row),
                            _near_duplicate_text(right_row),
                        ).ratio()
                        if similarity >= threshold:
                            overlap_count += 1
                            if len(examples) < 5:
                                examples.append(
                                    {
                                        "left_sample_id": left_row.get("sample_id"),
                                        "right_sample_id": right_row.get("sample_id"),
                                        "left_split": left_split,
                                        "right_split": right_split,
                                        "similarity": round(float(similarity), 6),
                                    }
                                )
                    if comparisons_skipped:
                        break
                if comparisons_skipped:
                    break
            if comparisons_skipped:
                break
    return {
        "available": available,
        "algorithm": NEAR_DUPLICATE_ALGORITHM_VERSION,
        "threshold": threshold,
        "comparison_limit": comparison_limit,
        "candidate_pair_count": candidate_pairs,
        "skipped_due_to_size": comparisons_skipped,
        "overlap_count": overlap_count,
        "examples": examples,
    }


def _near_duplicate_text(row: dict[str, Any]) -> str:
    explicit = str(row.get("near_duplicate_text") or "").strip()
    if explicit:
        return explicit
    fingerprint = str(row.get("edit_unit_fingerprint") or row.get("normalized_diff_hash") or "").strip()
    if fingerprint:
        return fingerprint
    unit_tokens = []
    for unit in list(row.get("edit_units", []) or []):
        unit_tokens.append(str(unit.get("file_path") or ""))
        unit_tokens.extend(str(item) for item in list(unit.get("changed_identifiers", []) or []))
    return " ".join(token for token in unit_tokens if token)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if value in (None, ""):
        return []
    text = str(value)
    if "|" in text:
        return [item for item in text.split("|") if item]
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return [text]
