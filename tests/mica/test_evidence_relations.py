from __future__ import annotations

from code.mica.evidence.relations import compute_edit_unit_relations


def test_evidence_relations_cover_observable_signals_without_gold_leakage() -> None:
    left = {
        "unit_id": "u1",
        "file_path": "src/auth/token.py",
        "hunk_id": "h1",
        "file_role": "source",
        "language": "python",
        "changed_identifiers": ["AuthToken", "validate_token"],
    }
    right = {
        "unit_id": "u2",
        "file_path": "tests/test_token.py",
        "hunk_id": "h2",
        "file_role": "test",
        "language": "python",
        "changed_identifiers": ["validate_token"],
    }

    features = compute_edit_unit_relations(left, right, {})

    assert features["same_file"] is False
    assert features["same_hunk"] is False
    assert features["same_language"] is True
    assert features["same_identifier"] is True
    assert features["test_target"] is True
    assert "gold_same_intent" not in features

