from __future__ import annotations

from code.mica.data.context_protocol import (
    EDIT_END,
    EDIT_START,
    build_commit_context_bundle,
    build_edit_unit_context_view,
    summarize_context_resolution,
)
from code.mica.data.collate import collate_mica_samples
from code.mica.data.schema import EditUnit, MicaSample


def _unit(**overrides) -> EditUnit:
    payload = {
        "unit_id": "u1",
        "hunk_id": "h1",
        "file_path": "src/auth.py",
        "patch_text": "+    return validate(token)",
        "added_lines": ["    return validate(token)"],
        "deleted_lines": ["    return False"],
        "context_lines": ["def check(token):"],
        "file_role": "source",
        "language": "python",
        "identifiers": ["check", "token"],
        "gold_intent_id": 0,
    }
    payload.update(overrides)
    return EditUnit(**payload)


def _sample(units: list[EditUnit]) -> MicaSample:
    return MicaSample(
        sample_id="sample-context",
        repo="acme/demo",
        split="train",
        k=1,
        is_multi_intent=False,
        diff_text="diff --git a/src/auth.py b/src/auth.py",
        edit_units=units,
        gold_count=1,
        gold_intent_ids=["intent_0"],
        gold_unit_to_intent={unit.unit_id: 0 for unit in units if unit.gold_intent_id == 0},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind="strict_synthetic",
    )


def test_context_view_keeps_patch_and_marks_changed_span_in_symbol_context() -> None:
    unit = _unit(
        enclosing_symbol_type="function",
        enclosing_symbol_name="check",
        enclosing_symbol_signature="def check(token):",
        enclosing_symbol_new_text="def check(token):\n    return validate(token)",
        enclosing_symbol_resolution_status="ast_resolved",
    )

    view = build_edit_unit_context_view(unit)

    assert view.h_patch == unit.patch_text
    assert EDIT_START in view.h_symbol
    assert EDIT_END in view.h_symbol
    assert view.h_metadata["enclosing_symbol_resolution_status"] == "ast_resolved"


def test_context_resolution_summary_reports_fallback_and_clipping_rates() -> None:
    units = [
        _unit(unit_id="u1", enclosing_symbol_resolution_status="ast_resolved"),
        _unit(unit_id="u2", enclosing_symbol_resolution_status="lexical_fallback", context_clipped=True),
        _unit(unit_id="u3", enclosing_symbol_resolution_status="hunk_only"),
    ]

    summary = summarize_context_resolution(units)

    assert summary["ast_resolution_success_rate"] == 1 / 3
    assert summary["lexical_fallback_rate"] == 1 / 3
    assert summary["hunk_only_fallback_rate"] == 1 / 3
    assert summary["clipping_rate"] == 1 / 3


def test_commit_context_bundle_deduplicates_shared_enclosing_symbol_context() -> None:
    shared_symbol = "def check(token):\n    validate(token)\n    log(token)"
    units = [
        _unit(
            unit_id="u1",
            hunk_id="h1",
            patch_text="+    validate(token)",
            added_lines=["    validate(token)"],
            deleted_lines=[],
            enclosing_symbol_type="function",
            enclosing_symbol_name="check",
            enclosing_symbol_signature="def check(token):",
            enclosing_symbol_new_text=shared_symbol,
            enclosing_symbol_resolution_status="ast_resolved",
        ),
        _unit(
            unit_id="u2",
            hunk_id="h2",
            patch_text="+    log(token)",
            added_lines=["    log(token)"],
            deleted_lines=[],
            enclosing_symbol_type="function",
            enclosing_symbol_name="check",
            enclosing_symbol_signature="def check(token):",
            enclosing_symbol_new_text=shared_symbol,
            enclosing_symbol_resolution_status="ast_resolved",
        ),
    ]

    bundle = build_commit_context_bundle(units)

    assert len(bundle.unit_views) == 2
    assert len(bundle.symbol_contexts) == 1
    assert bundle.diagnostics["symbol_context_deduplication_active"] is True
    assert {view.symbol_context_id for view in bundle.unit_views} == set(bundle.symbol_contexts)
    assert [view.h_patch for view in bundle.unit_views] == ["+    validate(token)", "+    log(token)"]
    shared_context = next(iter(bundle.symbol_contexts.values()))
    assert shared_context.unit_ids == ["u1", "u2"]


def test_collate_reports_context_protocol_diagnostics() -> None:
    units = [
        _unit(unit_id="u1", enclosing_symbol_resolution_status="ast_resolved"),
        _unit(
            unit_id="u2",
            enclosing_symbol_resolution_status="lexical_fallback",
            context_clipped=True,
        ),
        _unit(
            unit_id="u3",
            enclosing_symbol_resolution_status="hunk_only",
            enclosing_symbol_new_text=None,
            enclosing_symbol_old_text=None,
        ),
    ]

    batch = collate_mica_samples([_sample(units)])

    assert batch["input_context_protocol"] == "patch_plus_marked_enclosing_symbol_context_hashed_features"
    summary = batch["context_resolution_summary"][0]
    assert summary["unit_count"] == 3
    assert summary["ast_resolution_success_rate"] == 1 / 3
    assert summary["lexical_fallback_rate"] == 1 / 3
    assert summary["hunk_only_fallback_rate"] == 1 / 3
    assert summary["clipping_rate"] == 1 / 3
    assert batch["context_bundle_diagnostics"][0]["unit_context_count"] == 3


def test_collate_deduplicates_shared_symbol_context_in_batch_diagnostics() -> None:
    shared_symbol = "def check(token):\n    validate(token)\n    log(token)"
    units = [
        _unit(
            unit_id="u1",
            hunk_id="h1",
            patch_text="+    validate(token)",
            added_lines=["    validate(token)"],
            deleted_lines=[],
            enclosing_symbol_type="function",
            enclosing_symbol_name="check",
            enclosing_symbol_signature="def check(token):",
            enclosing_symbol_new_text=shared_symbol,
            enclosing_symbol_resolution_status="ast_resolved",
        ),
        _unit(
            unit_id="u2",
            hunk_id="h2",
            patch_text="+    log(token)",
            added_lines=["    log(token)"],
            deleted_lines=[],
            enclosing_symbol_type="function",
            enclosing_symbol_name="check",
            enclosing_symbol_signature="def check(token):",
            enclosing_symbol_new_text=shared_symbol,
            enclosing_symbol_resolution_status="ast_resolved",
        ),
    ]

    batch = collate_mica_samples([_sample(units)])

    diagnostics = batch["context_bundle_diagnostics"][0]
    assert diagnostics["shared_symbol_context_count"] == 1
    assert diagnostics["deduplicated_symbol_context_count"] == 1
    assert diagnostics["symbol_context_deduplication_active"] is True


def test_collate_text_features_include_marked_enclosing_symbol_context() -> None:
    patch = "+    return validate(token)"
    base_kwargs = {
        "patch_text": patch,
        "added_lines": ["    return validate(token)"],
        "deleted_lines": ["    return False"],
        "enclosing_symbol_type": "function",
        "enclosing_symbol_name": "check",
        "enclosing_symbol_signature": "def check(token):",
        "enclosing_symbol_resolution_status": "ast_resolved",
    }
    no_symbol = _unit(unit_id="u1", **base_kwargs)
    auth_symbol = _unit(
        unit_id="u1",
        enclosing_symbol_new_text="def check(token):\n    return validate(token)",
        **base_kwargs,
    )
    billing_symbol = _unit(
        unit_id="u1",
        enclosing_symbol_new_text="def check(invoice):\n    return validate(invoice)",
        identifiers=["check", "invoice"],
        **base_kwargs,
    )

    no_symbol_batch = collate_mica_samples([_sample([no_symbol])])
    auth_batch = collate_mica_samples([_sample([auth_symbol])])
    billing_batch = collate_mica_samples([_sample([billing_symbol])])

    no_symbol_vector = no_symbol_batch["text_features"][0, 0]
    auth_vector = auth_batch["text_features"][0, 0]
    billing_vector = billing_batch["text_features"][0, 0]
    assert not no_symbol_vector.equal(auth_vector)
    assert not auth_vector.equal(billing_vector)
