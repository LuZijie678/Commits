from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Any

from code.mica.data.schema import EditUnit


EDIT_START = "<EDIT_START>"
EDIT_END = "<EDIT_END>"


@dataclass(slots=True)
class EditUnitContextView:
    unit_id: str
    h_patch: str
    h_symbol: str
    h_metadata: dict[str, Any]
    diagnostics: list[str]
    symbol_context_id: str | None = None


@dataclass(slots=True)
class SharedSymbolContextView:
    symbol_context_id: str
    h_symbol_base: str
    h_metadata: dict[str, Any]
    unit_ids: list[str]
    diagnostics: list[str]


@dataclass(slots=True)
class CommitContextBundle:
    unit_views: list[EditUnitContextView]
    symbol_contexts: dict[str, SharedSymbolContextView]
    diagnostics: dict[str, Any]


def build_edit_unit_context_view(unit: EditUnit) -> EditUnitContextView:
    diagnostics: list[str] = []
    patch = unit.patch_text or "\n".join([*unit.deleted_lines, *unit.added_lines])
    symbol_text = unit.enclosing_symbol_new_text or unit.enclosing_symbol_old_text or ""
    if symbol_text:
        h_symbol = _mark_changed_span(symbol_text, unit.added_lines, unit.deleted_lines)
        if EDIT_START not in h_symbol or EDIT_END not in h_symbol:
            diagnostics.append("changed_span_marker_inserted_as_prefix")
            h_symbol = f"{EDIT_START}\n{patch}\n{EDIT_END}\n{symbol_text}"
    else:
        diagnostics.append("hunk_only_context")
        h_symbol = f"{EDIT_START}\n{patch}\n{EDIT_END}"

    if unit.enclosing_symbol_resolution_status not in {"ast_resolved", "lexical_fallback", "hunk_only", "unresolved"}:
        diagnostics.append("unknown_resolution_status")
    if unit.context_clipped:
        diagnostics.append("context_clipped")

    return EditUnitContextView(
        unit_id=unit.unit_id,
        h_patch=patch,
        h_symbol=h_symbol,
        h_metadata=_metadata_for_unit(unit),
        diagnostics=diagnostics,
    )


def build_commit_context_bundle(units: list[EditUnit]) -> CommitContextBundle:
    """Build per-unit patch views plus de-duplicated enclosing-symbol contexts.

    The protocol keeps the edit-unit assignment target at hunk/edit-unit level,
    but lets multiple hunks in the same enclosing symbol share one symbol context
    representation. Each unit still carries its own patch span and marked view.
    """
    unit_views: list[EditUnitContextView] = []
    symbol_contexts: dict[str, SharedSymbolContextView] = {}
    symbol_key_to_id: dict[str, str] = {}
    for unit in units:
        unit_view = build_edit_unit_context_view(unit)
        symbol_key = _symbol_context_key(unit)
        symbol_context_id = symbol_key_to_id.get(symbol_key)
        if symbol_context_id is None:
            symbol_context_id = _stable_symbol_context_id(symbol_key)
            symbol_key_to_id[symbol_key] = symbol_context_id
            symbol_contexts[symbol_context_id] = SharedSymbolContextView(
                symbol_context_id=symbol_context_id,
                h_symbol_base=_symbol_base_text(unit, unit_view.h_symbol),
                h_metadata=_metadata_for_unit(unit),
                unit_ids=[],
                diagnostics=_shared_symbol_diagnostics(unit),
            )
        symbol_contexts[symbol_context_id].unit_ids.append(unit.unit_id)
        unit_views.append(
            EditUnitContextView(
                unit_id=unit_view.unit_id,
                h_patch=unit_view.h_patch,
                h_symbol=unit_view.h_symbol,
                h_metadata=unit_view.h_metadata,
                diagnostics=unit_view.diagnostics,
                symbol_context_id=symbol_context_id,
            )
        )
    shared_context_count = sum(1 for context in symbol_contexts.values() if len(context.unit_ids) > 1)
    return CommitContextBundle(
        unit_views=unit_views,
        symbol_contexts=symbol_contexts,
        diagnostics={
            "unit_context_count": len(unit_views),
            "shared_symbol_context_count": len(symbol_contexts),
            "deduplicated_symbol_context_count": shared_context_count,
            "symbol_context_deduplication_active": shared_context_count > 0,
        },
    )


def summarize_context_resolution(units: list[EditUnit]) -> dict[str, Any]:
    counts = Counter(unit.enclosing_symbol_resolution_status for unit in units)
    total = max(len(units), 1)
    by_language: dict[str, Counter[str]] = {}
    for unit in units:
        language = unit.language or "unknown"
        by_language.setdefault(language, Counter())[unit.enclosing_symbol_resolution_status] += 1
    return {
        "unit_count": len(units),
        "ast_resolution_success_rate": counts.get("ast_resolved", 0) / total,
        "lexical_fallback_rate": counts.get("lexical_fallback", 0) / total,
        "hunk_only_fallback_rate": counts.get("hunk_only", 0) / total,
        "unresolved_rate": counts.get("unresolved", 0) / total,
        "clipping_rate": sum(1 for unit in units if unit.context_clipped) / total,
        "resolution_status_counts": dict(counts),
        "resolution_by_language": {language: dict(counter) for language, counter in by_language.items()},
    }


def _mark_changed_span(symbol_text: str, added_lines: list[str], deleted_lines: list[str]) -> str:
    for line in [*added_lines, *deleted_lines]:
        stripped = line.strip()
        if not stripped:
            continue
        index = symbol_text.find(stripped)
        if index >= 0:
            end = index + len(stripped)
            return f"{symbol_text[:index]}{EDIT_START}{symbol_text[index:end]}{EDIT_END}{symbol_text[end:]}"
    return symbol_text


def _metadata_for_unit(unit: EditUnit) -> dict[str, Any]:
    return {
        "file_path": unit.file_path,
        "language": unit.language,
        "file_role": unit.file_role,
        "changed_identifiers": list(unit.identifiers),
        "source_sha": None,
        "enclosing_symbol_type": unit.enclosing_symbol_type,
        "enclosing_symbol_name": unit.enclosing_symbol_name,
        "enclosing_symbol_signature": unit.enclosing_symbol_signature,
        "enclosing_symbol_resolution_status": unit.enclosing_symbol_resolution_status,
    }


def _symbol_context_key(unit: EditUnit) -> str:
    symbol_text = unit.enclosing_symbol_new_text or unit.enclosing_symbol_old_text
    if not symbol_text:
        return f"hunk_only::{unit.file_path}::{unit.hunk_id}::{unit.unit_id}"
    return "::".join(
        [
            unit.file_path,
            str(unit.enclosing_symbol_type),
            str(unit.enclosing_symbol_name),
            str(unit.enclosing_symbol_signature),
            str(unit.enclosing_symbol_old_span),
            str(unit.enclosing_symbol_new_span),
            unit.enclosing_symbol_resolution_status,
            symbol_text,
        ]
    )


def _stable_symbol_context_id(symbol_key: str) -> str:
    digest = hashlib.sha1(symbol_key.encode("utf-8")).hexdigest()[:12]
    return f"symbol_{digest}"


def _symbol_base_text(unit: EditUnit, fallback_marked_symbol: str) -> str:
    return unit.enclosing_symbol_new_text or unit.enclosing_symbol_old_text or fallback_marked_symbol


def _shared_symbol_diagnostics(unit: EditUnit) -> list[str]:
    diagnostics: list[str] = []
    if not (unit.enclosing_symbol_new_text or unit.enclosing_symbol_old_text):
        diagnostics.append("hunk_only_context")
    if unit.context_clipped:
        diagnostics.append("context_clipped")
    return diagnostics
