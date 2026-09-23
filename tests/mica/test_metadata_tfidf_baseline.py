from __future__ import annotations

from code.mica.baselines.metadata_tfidf_classifier import MetadataTfidfClassifier


def _row(sample_id: str, file_path: str, gold_count: int) -> dict:
    return {
        "sample_id": sample_id,
        "gold_count": gold_count,
        "edit_units": [
            {
                "file_path": file_path,
                "file_role": "source",
                "changed_identifiers": ["auth", "token"] if gold_count > 1 else ["docs"],
                "added_lines": ["line1", "line2"],
                "deleted_lines": ["line3"],
            }
        ],
    }


def test_metadata_tfidf_classifier_fit_predict_and_reload(tmp_path) -> None:
    model = MetadataTfidfClassifier(epochs=20, learning_rate=0.1)
    train_rows = [_row("s1", "src/auth.py", 2), _row("s2", "docs/readme.md", 1)]
    model.fit(train_rows)
    preds = model.predict(train_rows)
    path = tmp_path / "tfidf.json"
    model.save(path)
    loaded = MetadataTfidfClassifier.load(path)

    assert len(preds) == 2
    assert loaded.predict_proba(train_rows)[0]["predicted_count"] >= 1
