from __future__ import annotations

import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn


FEATURE_NAMES = [
    "edit_unit_count",
    "hunk_count",
    "file_count",
    "added_line_count",
    "deleted_line_count",
    "path_diversity",
    "identifier_count",
    "source_role_count",
    "test_role_count",
    "doc_role_count",
    "config_role_count",
    "avg_hunk_size",
    "source_ratio",
    "test_ratio",
    "doc_ratio",
]


def extract_flat_classifier_features(row: dict[str, Any]) -> dict[str, float]:
    edit_units = list(row.get("edit_units", []))
    file_paths = [str(unit.get("file_path", "")) for unit in edit_units]
    file_roles = Counter(str(unit.get("file_role", "unknown")).lower() for unit in edit_units)
    added_line_count = sum(len(unit.get("added_lines", []) or []) for unit in edit_units)
    deleted_line_count = sum(len(unit.get("deleted_lines", []) or []) for unit in edit_units)
    identifier_count = sum(len(unit.get("changed_identifiers", []) or []) for unit in edit_units)
    parents = {PurePosixPath(path).parent.as_posix() for path in file_paths if path}
    hunk_ids = {str(unit.get("hunk_id")) for unit in edit_units if unit.get("hunk_id") is not None}
    role_total = max(len(edit_units), 1)
    avg_hunk_size = (added_line_count + deleted_line_count) / max(len(hunk_ids) or len(edit_units), 1)
    return {
        "edit_unit_count": float(len(edit_units)),
        "hunk_count": float(len(hunk_ids) or len(edit_units)),
        "file_count": float(len(set(file_paths))),
        "added_line_count": float(added_line_count),
        "deleted_line_count": float(deleted_line_count),
        "path_diversity": float(len(parents)),
        "identifier_count": float(identifier_count),
        "source_role_count": float(file_roles.get("source", 0)),
        "test_role_count": float(file_roles.get("test", 0)),
        "doc_role_count": float(file_roles.get("doc", 0) + file_roles.get("docs", 0)),
        "config_role_count": float(file_roles.get("config", 0) + file_roles.get("build", 0)),
        "avg_hunk_size": float(avg_hunk_size),
        "source_ratio": float(file_roles.get("source", 0) / role_total),
        "test_ratio": float(file_roles.get("test", 0) / role_total),
        "doc_ratio": float((file_roles.get("doc", 0) + file_roles.get("docs", 0)) / role_total),
    }


class FlatCountClassifier(nn.Module):
    def __init__(self, *, max_count: int = 4, learning_rate: float = 0.05, epochs: int = 80) -> None:
        super().__init__()
        self.max_count = max_count
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.feature_names = list(FEATURE_NAMES)
        self.linear = nn.Linear(len(self.feature_names), max_count)
        self._mean = torch.zeros(len(self.feature_names), dtype=torch.float32)
        self._std = torch.ones(len(self.feature_names), dtype=torch.float32)
        self._fitted = False

    def fit(self, rows: list[dict[str, Any]]) -> FlatCountClassifier:
        if not rows:
            raise ValueError("FlatCountClassifier.fit requires at least one row.")
        features = torch.stack([self._row_to_tensor(row) for row in rows])
        labels = torch.tensor([max(min(int(row.get("gold_count", 1) or 1), self.max_count), 1) - 1 for row in rows], dtype=torch.long)
        self._mean = features.mean(dim=0)
        self._std = features.std(dim=0).clamp_min(1e-6)
        x = self._normalize(features)
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        self.train(True)
        for _ in range(self.epochs):
            optimizer.zero_grad()
            logits = self.linear(x)
            loss = F.cross_entropy(logits, labels)
            loss.backward()
            optimizer.step()
        self._fitted = True
        return self

    def predict_proba(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        x = self._normalize(torch.stack([self._row_to_tensor(row) for row in rows]))
        self.train(False)
        with torch.no_grad():
            probs = F.softmax(self.linear(x), dim=-1)
        results: list[dict[str, Any]] = []
        for row_probs in probs:
            count_probs = {str(index + 1): float(value.item()) for index, value in enumerate(row_probs)}
            results.append(
                {
                    "count_probs": count_probs,
                    "p_multi": float(row_probs[1:].sum().item()),
                    "predicted_count": int(torch.argmax(row_probs).item()) + 1,
                }
            )
        return results

    def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outputs = []
        for row, proba in zip(rows, self.predict_proba(rows)):
            outputs.append(
                {
                    "sample_id": row.get("sample_id"),
                    "predicted_count": proba["predicted_count"],
                    "is_multi_intent": proba["predicted_count"] >= 2,
                    "unit_to_slot": None,
                    "metadata": {
                        "baseline": "flat_classifier",
                        "produces_attribution": False,
                        "fitted_model": self._fitted,
                        "count_probs": proba["count_probs"],
                        "p_multi": proba["p_multi"],
                    },
                }
            )
        return outputs

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "max_count": self.max_count,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "feature_names": self.feature_names,
            "state_dict": {key: value.detach().cpu().tolist() for key, value in self.state_dict().items()},
            "mean": self._mean.detach().cpu().tolist(),
            "std": self._std.detach().cpu().tolist(),
            "fitted": self._fitted,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> FlatCountClassifier:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        model = cls(max_count=int(payload["max_count"]), learning_rate=float(payload["learning_rate"]), epochs=int(payload["epochs"]))
        state_dict = {key: torch.tensor(value, dtype=torch.float32) for key, value in payload["state_dict"].items()}
        model.load_state_dict(state_dict)
        model._mean = torch.tensor(payload["mean"], dtype=torch.float32)
        model._std = torch.tensor(payload["std"], dtype=torch.float32)
        model._fitted = bool(payload["fitted"])
        return model

    def _row_to_tensor(self, row: dict[str, Any]) -> torch.Tensor:
        features = extract_flat_classifier_features(row)
        return torch.tensor([float(features[name]) for name in self.feature_names], dtype=torch.float32)

    def _normalize(self, features: torch.Tensor) -> torch.Tensor:
        return (features - self._mean) / self._std


def fit_flat_classifier(rows: list[dict[str, Any]], *, max_count: int = 4, learning_rate: float = 0.05, epochs: int = 80) -> FlatCountClassifier:
    return FlatCountClassifier(max_count=max_count, learning_rate=learning_rate, epochs=epochs).fit(rows)


def run_flat_classifier_baseline(
    row: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
    model: FlatCountClassifier | None = None,
) -> dict[str, Any]:
    if model is not None:
        return model.predict([row])[0]

    features = extract_flat_classifier_features(row)
    runtime = {
        "score_multi_threshold": 3.5,
        "path_diversity_weight": 0.5,
        "doc_mix_bonus": 0.5,
        "test_mix_bonus": 0.3,
        **(thresholds or {}),
    }
    score = (
        0.5 * features["file_count"]
        + runtime["path_diversity_weight"] * features["path_diversity"]
        + 0.15 * features["edit_unit_count"]
        + (runtime["doc_mix_bonus"] if features["doc_role_count"] > 0 and features["source_role_count"] > 0 else 0.0)
        + (runtime["test_mix_bonus"] if features["test_role_count"] > 0 and features["source_role_count"] > 0 else 0.0)
    )
    predicted_count = 2 if score >= float(runtime["score_multi_threshold"]) else 1
    return {
        "predicted_count": predicted_count,
        "is_multi_intent": predicted_count >= 2,
        "unit_to_slot": None,
        "metadata": {
            "baseline": "flat_classifier",
            "produces_attribution": False,
            "features": features,
            "thresholds_are_not_final": True,
            "fitted_model": False,
        },
    }
