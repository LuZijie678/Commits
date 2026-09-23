from __future__ import annotations

import re

from code.mica.data.schema import EditUnit
from code.mica.features.file_role import infer_file_role, infer_language
from code.mica.features.identifiers import extract_identifier_tokens


DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def parse_unified_diff_to_edit_units(
    diff_text: str,
    *,
    repo: str,
    sample_id: str,
    gold_intent_ids: list[int] | None = None,
) -> list[EditUnit]:
    del repo  # reserved for future evidence features
    lines = (diff_text or "").splitlines()
    edit_units: list[EditUnit] = []
    current_file: str | None = None
    current_hunk_header: str | None = None
    current_hunk_lines: list[str] = []
    current_file_hunk_index = 0

    def flush_hunk() -> None:
        nonlocal current_hunk_header, current_hunk_lines, current_file_hunk_index
        if current_file is None or current_hunk_header is None:
            current_hunk_lines = []
            return
        added_lines = [line[1:] for line in current_hunk_lines if line.startswith("+") and not line.startswith("+++")]
        deleted_lines = [line[1:] for line in current_hunk_lines if line.startswith("-") and not line.startswith("---")]
        context_lines = [
            line[1:] if line.startswith(" ") else line
            for line in current_hunk_lines
            if line.startswith(" ") and not line.startswith("+++")
        ]
        patch_text = "\n".join([current_hunk_header, *current_hunk_lines]).strip()
        identifiers = extract_identifier_tokens(f"{current_file}\n{patch_text}")
        unit_index = len(edit_units)
        edit_units.append(
            EditUnit(
                unit_id=f"{sample_id}::u{unit_index:04d}",
                hunk_id=f"{current_file}::hunk_{current_file_hunk_index:04d}",
                file_path=current_file,
                patch_text=patch_text,
                added_lines=added_lines,
                deleted_lines=deleted_lines,
                context_lines=context_lines,
                file_role=infer_file_role(current_file),
                language=infer_language(current_file),
                identifiers=identifiers,
                gold_intent_id=None,
                enclosing_symbol_resolution_status="hunk_only",
            )
        )
        current_file_hunk_index += 1
        current_hunk_header = None
        current_hunk_lines = []

    for line in lines:
        diff_match = DIFF_GIT_RE.match(line)
        if diff_match:
            flush_hunk()
            current_file = diff_match.group(2)
            current_file_hunk_index = 0
            continue
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate.startswith("b/"):
                current_file = candidate[2:]
            elif candidate != "/dev/null":
                current_file = candidate
            continue
        if line.startswith("@@"):
            flush_hunk()
            current_hunk_header = line
            current_hunk_lines = []
            continue
        if current_hunk_header is not None:
            current_hunk_lines.append(line)

    flush_hunk()
    if gold_intent_ids is not None:
        if len(gold_intent_ids) != len(edit_units):
            raise ValueError(
                f"gold_intent_ids length mismatch for sample {sample_id}: {len(gold_intent_ids)} vs {len(edit_units)}"
            )
        for unit, gold_intent_id in zip(edit_units, gold_intent_ids):
            unit.gold_intent_id = int(gold_intent_id)
    return edit_units
