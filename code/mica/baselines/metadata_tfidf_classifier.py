from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
NUMERIC_FEATURES = ["edit_unit_count", "file_count", "identifier_count", "added_line_count", "deleted_line_count", "path_diversity"]


class MetadataTfidfClassifier(nn.Module):
    def __init__(self, *, max_count: int = 4, learning_rate: float = 0.05, epochs: int = 40) -> None:
        super().__init__()
        self.max_count = max_count
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.vocab: dict[str, int] = {}
        self.linear: nn.Linear | None = None
        self._fitted = False

    def fit(self, rows: list[dict[str, Any]]) -> MetadataTfidfClassifier:
        if not rows:
            raise ValueError("MetadataTfidfClassifier.fit requires rows.")
        self.vocab = _build_vocab(rows)
        features = torch.stack([self._row_to_tensor(row) for row in rows])
        labels = torch.tensor([max(1, min(int(row.get("gold_count", 1) or 1), self.max_count)) - 1 for row in rows], dtype=torch.long)
        self.linear = nn.Linear(features.size(1), self.max_count)
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        self.train(True)
        for _ in range(self.epochs):
            optimizer.zero_grad()
            logits = self.linear(features)
            loss = F.cross_entropy(logits, labels)
            loss.backward()
            optimizer.step()
        self._fitted = True
        return self

    def predict_proba(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.linear is None:
            raise ValueError("MetadataTfidfClassifier must be fitted before prediction.")
        features = torch.stack([self._row_to_tensor(row) for row in rows])
        self.train(False)
        with torch.no_grad():
            probs = F.softmax(self.linear(features), dim=-1)
        results = []
        for row_probs in probs:
            count_probs = {str(index + 1): float(value.item()) for index, value in enumerate(row_probs)}
            results.append(
                {
                    "predicted_count": int(torch.argmax(row_probs).item()) + 1,
                    "count_probs": count_probs,
                    "p_multi": float(row_probs[1:].sum().item()),
                }
            )
        return results

    def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        predictions = []
        for row, payload in zip(rows, self.predict_proba(rows)):
            predictions.append(
                {
                    "sample_id": row.get("sample_id"),
                    "predicted_count": payload["predicted_count"],
                    "is_multi_intent": payload["predicted_count"] >= 2,
                    "unit_to_slot": None,
                    "metadata": {
                        "baseline": "metadata_tfidf_classifier",
                        "produces_attribution": False,
                        "count_probs": payload["count_probs"],
                        "p_multi": payload["p_multi"],
                    },
                }
            )
        return predictions

    def save(self, path: str | Path) -> None:
        if self.linear is None:
            raise ValueError("Cannot save unfitted MetadataTfidfClassifier.")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "max_count": self.max_count,
                    "learning_rate": self.learning_rate,
                    "epochs": self.epochs,
                    "vocab": self.vocab,
                    "state_dict": {key: value.detach().cpu().tolist() for key, value in self.state_dict().items()},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> MetadataTfidfClassifier:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        model = cls(max_count=int(payload["max_count"]), learning_rate=float(payload["learning_rate"]), epochs=int(payload["epochs"]))
        model.vocab = {str(key): int(value) for key, value in dict(payload["vocab"]).items()}
        feature_size = len(model.vocab) + len(NUMERIC_FEATURES)
        model.linear = nn.Linear(feature_size, model.max_count)
        state_dict = {key: torch.tensor(value, dtype=torch.float32) for key, value in payload["state_dict"].items()}
        model.load_state_dict(state_dict)
        model._fitted = True
        return model

    def _row_to_tensor(self, row: dict[str, Any]) -> torch.Tensor:
        token_counts = Counter(_extract_tokens(row))
        vector = torch.zeros(len(self.vocab) + len(NUMERIC_FEATURES), dtype=torch.float32)
        for token, count in token_counts.items():
            if token in self.vocab:
                vector[self.vocab[token]] = float(count)
        numeric = _extract_numeric_features(row)
        for index, key in enumerate(NUMERIC_FEATURES, start=len(self.vocab)):
            vector[index] = float(numeric[key])
        return vector


def _build_vocab(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(_extract_tokens(row))
    return {token: index for index, (token, _) in enumerate(sorted(counter.items()))}


def _extract_tokens(row: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for unit in row.get("edit_units", []):
        file_path = str(unit.get("file_path", ""))
        tokens.extend(token.lower() for token in TOKEN_RE.findall(file_path))
        tokens.extend(str(token).lower() for token in unit.get("changed_identifiers", []) if token)
        role = str(unit.get("file_role", "unknown")).lower()
        tokens.append(f"role:{role}")
    return tokens


def _extract_numeric_features(row: dict[str, Any]) -> dict[str, float]:
    edit_units = list(row.get("edit_units", []))
    file_paths = {str(unit.get("file_path", "")) for unit in edit_units if unit.get("file_path")}
    identifiers = sum(len(unit.get("changed_identifiers", []) or []) for unit in edit_units)
    added = sum(len(unit.get("added_lines", []) or []) for unit in edit_units)
    deleted = sum(len(unit.get("deleted_lines", []) or []) for unit in edit_units)
    parents = {Path(path).parent.as_posix() for path in file_paths}
    return {
        "edit_unit_count": float(len(edit_units)),
        "file_count": float(len(file_paths)),
        "identifier_count": float(identifiers),
        "added_line_count": float(added),
        "deleted_line_count": float(deleted),
        "path_diversity": float(len(parents)),
    }
