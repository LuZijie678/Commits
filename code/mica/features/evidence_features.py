from __future__ import annotations

from pathlib import PurePosixPath

from code.mica.data.schema import EditUnit
from code.mica.features.file_role import role_flags
from code.mica.features.identifiers import tokenize_path


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def build_edit_unit_features(unit: EditUnit, *, hunk_index: int) -> dict[str, object]:
    path_tokens = tokenize_path(unit.file_path)
    flags = role_flags(unit.file_path)
    added = len(unit.added_lines)
    deleted = len(unit.deleted_lines)
    changed = added + deleted
    return {
        "file_path": unit.file_path,
        "file_role": unit.file_role,
        "language": unit.language,
        "hunk_index": int(hunk_index),
        "changed_line_count": int(changed),
        "added_deleted_ratio": (added + 1.0) / (deleted + 1.0),
        "identifier_tokens": list(unit.identifiers),
        "path_tokens": path_tokens,
        **flags,
    }


def build_pairwise_features(left: EditUnit, right: EditUnit) -> dict[str, object]:
    left_path = PurePosixPath(left.file_path)
    right_path = PurePosixPath(right.file_path)
    left_ids = set(left.identifiers)
    right_ids = set(right.identifiers)
    left_tokens = set(tokenize_path(left.file_path))
    right_tokens = set(tokenize_path(right.file_path))
    left_flags = role_flags(left.file_path)
    right_flags = role_flags(right.file_path)
    identifier_jaccard = _jaccard(left_ids, right_ids)
    path_token_jaccard = _jaccard(left_tokens, right_tokens)
    test_target_hint = (
        (left_flags["is_test"] and not right_flags["is_test"]) or (right_flags["is_test"] and not left_flags["is_test"])
    ) and (identifier_jaccard > 0.0 or path_token_jaccard > 0.0)
    doc_ref_hint = (
        (left_flags["is_doc"] and not right_flags["is_doc"]) or (right_flags["is_doc"] and not left_flags["is_doc"])
    ) and (identifier_jaccard > 0.0 or path_token_jaccard > 0.0)
    return {
        "same_file": left.file_path == right.file_path,
        "same_directory": left_path.parent == right_path.parent,
        "same_file_role": left.file_role == right.file_role,
        "identifier_jaccard": identifier_jaccard,
        "path_token_jaccard": path_token_jaccard,
        "test_target_hint": bool(test_target_hint),
        "doc_ref_hint": bool(doc_ref_hint),
    }
