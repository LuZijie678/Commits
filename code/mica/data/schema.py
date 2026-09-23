from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EditUnit:
    unit_id: str
    hunk_id: str
    file_path: str
    patch_text: str
    added_lines: list[str]
    deleted_lines: list[str]
    context_lines: list[str]
    file_role: str
    language: str | None
    identifiers: list[str]
    gold_intent_id: int | None
    enclosing_symbol_type: str | None = None
    enclosing_symbol_name: str | None = None
    enclosing_symbol_signature: str | None = None
    enclosing_symbol_old_span: tuple[int, int] | None = None
    enclosing_symbol_new_span: tuple[int, int] | None = None
    enclosing_symbol_old_text: str | None = None
    enclosing_symbol_new_text: str | None = None
    enclosing_symbol_resolution_status: str = "hunk_only"
    context_clipped: bool = False
    provenance_status: str = "unknown"
    source_atomic_commit_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MicaSample:
    sample_id: str
    repo: str
    split: str
    k: int
    is_multi_intent: bool
    diff_text: str
    edit_units: list[EditUnit]
    gold_count: int
    gold_intent_ids: list[str]
    gold_unit_to_intent: dict[str, int]
    intent_types: list[str] | None
    intent_subjects: list[str] | None
    sample_weight: float
    source_kind: str


@dataclass(slots=True)
class Stage1SplitBundle:
    train: list[MicaSample] = field(default_factory=list)
    dev: list[MicaSample] = field(default_factory=list)
    test: list[MicaSample] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    source_stats: dict[str, object] = field(default_factory=dict)
