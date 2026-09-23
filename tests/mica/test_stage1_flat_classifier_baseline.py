from __future__ import annotations

from code.mica.baselines.flat_classifier import FlatCountClassifier, extract_flat_classifier_features, run_flat_classifier_baseline


def test_flat_classifier_baseline_returns_count_prediction_without_attribution() -> None:
    row = {
        "sample_id": "s1",
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/a.py", "added_lines": ["a"], "deleted_lines": [], "changed_identifiers": ["token"], "file_role": "source"},
            {"unit_id": "u2", "file_path": "docs/api.md", "added_lines": ["b"], "deleted_lines": [], "changed_identifiers": [], "file_role": "doc"},
        ],
    }

    features = extract_flat_classifier_features(row)
    result = run_flat_classifier_baseline(row)

    assert features["edit_unit_count"] == 2
    assert result["metadata"]["baseline"] == "flat_classifier"
    assert result["metadata"]["produces_attribution"] is False
    assert result["unit_to_slot"] is None
    assert result["predicted_count"] in {1, 2}


def test_flat_classifier_can_fit_predict_and_reload(tmp_path) -> None:
    train_rows = [
        {
            "sample_id": "k1",
            "gold_count": 1,
            "edit_units": [{"unit_id": "u1", "file_path": "src/a.py", "added_lines": ["a"], "deleted_lines": [], "changed_identifiers": ["a"], "file_role": "source"}],
        },
        {
            "sample_id": "k2",
            "gold_count": 2,
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/a.py", "added_lines": ["a"], "deleted_lines": [], "changed_identifiers": ["a"], "file_role": "source"},
                {"unit_id": "u2", "file_path": "tests/a_test.py", "added_lines": ["b"], "deleted_lines": [], "changed_identifiers": ["a"], "file_role": "test"},
            ],
        },
    ]
    model = FlatCountClassifier(max_count=3, epochs=40).fit(train_rows)
    probs = model.predict_proba(train_rows)
    saved = tmp_path / "flat_classifier.json"
    model.save(saved)
    reloaded = FlatCountClassifier.load(saved)

    assert len(probs) == 2
    assert abs(sum(probs[0]["count_probs"].values()) - 1.0) < 1e-6
    assert reloaded.predict(train_rows)[0]["metadata"]["fitted_model"] is True
