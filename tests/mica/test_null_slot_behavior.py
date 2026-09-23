from __future__ import annotations

from code.mica.model.null_slot import (
    append_null_slot_to_assignment_scores,
    build_null_slot_mask,
    is_background_eligible_unit,
    split_foreground_and_null_assignments,
)


def test_generated_and_lockfile_units_are_background_eligible() -> None:
    generated = {"unit_id": "u1", "file_path": "dist/bundle.js", "file_role": "generated", "patch_text": "x\n" * 10}
    lockfile = {"unit_id": "u2", "file_path": "package-lock.json", "file_role": "lockfile"}
    source = {"unit_id": "u3", "file_path": "src/app.py", "file_role": "source", "changed_identifiers": ["token"]}

    assert is_background_eligible_unit(generated, {}) is True
    assert is_background_eligible_unit(lockfile, {}) is True
    assert is_background_eligible_unit(source, {}) is False


def test_build_null_slot_mask_is_conservative_for_normal_test_and_doc_units() -> None:
    rows = [
        {"unit_id": "u1", "file_path": "tests/test_auth.py", "file_role": "test", "changed_identifiers": ["token"]},
        {"unit_id": "u2", "file_path": "docs/auth.md", "file_role": "doc", "changed_identifiers": ["token"]},
        {"unit_id": "u3", "file_path": "pnpm-lock.yaml", "file_role": "lockfile"},
    ]

    mask = build_null_slot_mask(rows, {})

    assert mask["eligible_by_unit_id"]["u1"] is False
    assert mask["eligible_by_unit_id"]["u2"] is False
    assert mask["eligible_by_unit_id"]["u3"] is True
    assert mask["eligible_count"] == 1


def test_append_null_slot_and_split_assignments_track_foreground_separately() -> None:
    scores = {
        "u1": {"slot_1": 0.8, "slot_2": 0.2},
        "u2": {"slot_1": 0.1, "slot_2": 0.9},
    }

    augmented = append_null_slot_to_assignment_scores(scores, {"null_slot": {"null_slot_id": "slot_null", "default_score": 0.05}})
    split = split_foreground_and_null_assignments({"u1": "slot_1", "u2": "slot_null"})

    assert "slot_null" in augmented["u1"]
    assert split["foreground_assignments"] == {"u1": "slot_1"}
    assert split["null_unit_ids"] == ["u2"]
    assert split["foreground_count"] == 1

