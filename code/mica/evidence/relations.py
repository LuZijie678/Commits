from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from code.mica.features.file_role import infer_file_role, role_flags
from code.mica.features.identifiers import tokenize_path


def compute_edit_unit_relations(unit_i: dict[str, Any], unit_j: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    del spec
    left_path = str(unit_i.get("file_path", ""))
    right_path = str(unit_j.get("file_path", ""))
    left_role = str(unit_i.get("file_role") or infer_file_role(left_path)).lower()
    right_role = str(unit_j.get("file_role") or infer_file_role(right_path)).lower()
    left_ids = {str(item).lower() for item in list(unit_i.get("changed_identifiers", []) or []) if str(item).strip()}
    right_ids = {str(item).lower() for item in list(unit_j.get("changed_identifiers", []) or []) if str(item).strip()}
    left_path_tokens = set(tokenize_path(left_path))
    right_path_tokens = set(tokenize_path(right_path))
    identifier_jaccard = _jaccard(left_ids, right_ids)
    role_pair = f"{left_role}->{right_role}"
    test_target = _is_test_target(left_role, right_role, left_ids, right_ids, left_path_tokens, right_path_tokens)
    doc_refers_to = _is_doc_ref(left_role, right_role, left_ids, right_ids, left_path_tokens, right_path_tokens)
    return {
        "same_file": left_path == right_path and left_path != "",
        "same_hunk": str(unit_i.get("hunk_id", "")) != "" and str(unit_i.get("hunk_id", "")) == str(unit_j.get("hunk_id", "")),
        "path_distance": float(_path_distance(left_path, right_path)),
        "same_symbol": bool(left_ids & right_ids),
        "same_identifier": bool(left_ids & right_ids),
        "same_language": _language(unit_i) == _language(unit_j) and _language(unit_i) is not None,
        "test_target": test_target,
        "doc_refers_to": doc_refers_to,
        "config_build_lockfile": bool({left_role, right_role} & {"config", "build", "lockfile"}),
        "generated_file": bool(_generated_like(unit_i) or _generated_like(unit_j)),
        "identifier_jaccard": identifier_jaccard,
        "same_language_name": _language(unit_i),
        "file_role_pair": role_pair,
    }


def _path_distance(left_path: str, right_path: str) -> int:
    left_parts = [part for part in PurePosixPath(left_path).parts if part]
    right_parts = [part for part in PurePosixPath(right_path).parts if part]
    common = 0
    for left, right in zip(left_parts, right_parts):
        if left == right:
            common += 1
        else:
            break
    return (len(left_parts) - common) + (len(right_parts) - common)


def _is_test_target(left_role: str, right_role: str, left_ids: set[str], right_ids: set[str], left_path_tokens: set[str], right_path_tokens: set[str]) -> bool:
    one_test = (left_role == "test") ^ (right_role == "test")
    return one_test and bool((left_ids & right_ids) or (left_path_tokens & right_path_tokens))


def _is_doc_ref(left_role: str, right_role: str, left_ids: set[str], right_ids: set[str], left_path_tokens: set[str], right_path_tokens: set[str]) -> bool:
    one_doc = (left_role == "doc") ^ (right_role == "doc")
    return one_doc and bool((left_ids & right_ids) or (left_path_tokens & right_path_tokens))


def _generated_like(unit: dict[str, Any]) -> bool:
    metadata = dict(unit.get("metadata", {}))
    file_path = str(unit.get("file_path", ""))
    flags = role_flags(file_path)
    role = str(unit.get("file_role") or infer_file_role(file_path)).lower()
    return bool(metadata.get("generated_file") or metadata.get("large_generated_blob") or flags["is_generated_like"] or role in {"generated", "lockfile"})


def _language(unit: dict[str, Any]) -> str | None:
    value = unit.get("language")
    return str(value).lower() if value else None


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)

