from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.train.train_stage1_sanity import run_stage1_sanity


def _write_atomic_csv(path: Path, *, rows: int = 8) -> None:
    fieldnames = [
        "repo",
        "sha",
        "type",
        "subject",
        "message",
        "git_diff",
        "source_confidence",
    ]
    payload = []
    for index in range(rows):
        payload.append(
            {
                "repo": "acme/demo",
                "sha": f"a{index:03d}",
                "type": "fix",
                "subject": f"fix: guard {index}",
                "message": f"fix: guard {index}",
                "git_diff": f"""diff --git a/src/main_{index}.py b/src/main_{index}.py
index 1..2 100644
--- a/src/main_{index}.py
+++ b/src/main_{index}.py
@@ -1,2 +1,3 @@
 def run():
+    if value_{index} is None:
     return 1
""",
                "source_confidence": "1.0",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload)


def _write_synthetic_jsonl(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(8):
            row = {
                "sample_id": f"syn_{index:03d}",
                "repo": "acme/demo",
                "intent_count": 2,
                "synthetic_diff": f"""diff --git a/src/main_{index}.py b/src/main_{index}.py
index 1..2 100644
--- a/src/main_{index}.py
+++ b/src/main_{index}.py
@@ -1,2 +1,3 @@
 def run():
+    if value_{index} is None:
     return 1
diff --git a/tests/test_main_{index}.py b/tests/test_main_{index}.py
index 3..4 100644
--- a/tests/test_main_{index}.py
+++ b/tests/test_main_{index}.py
@@ -0,0 +1,3 @@
+def test_run_{index}():
+    assert run() == 1
""",
                "edit_to_intent": [0, 1],
            }
            handle.write(json.dumps(row) + "\n")


def test_manifest_json_overrides_random_split_selection(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    curriculum_output_root = tmp_path / "curriculum_outputs"
    reports_root = tmp_path / "reports"
    training_output_root = tmp_path / "train_outputs"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    manifests = build_stage1_curriculum_manifests(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=curriculum_output_root,
        reports_root=reports_root,
        k1_train_count=2,
        k2_train_count=2,
        k1_dev_count=1,
        k2_dev_count=1,
        split_seed=42,
    )
    manifest_path = Path(manifests["easy"]["manifest_path"])
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    result = run_stage1_sanity(
        {
            "atomic_csv": str(atomic_csv),
            "synthetic_jsonl": str(synthetic_jsonl),
            "max_train_samples": 20,
            "max_dev_samples": 20,
            "batch_size": 4,
            "epochs": 2,
            "Kmax": 4,
            "learning_rate": 1e-3,
            "seed": 42,
            "device": "cpu",
            "output_root": str(training_output_root),
        },
        cli_manifest_json=str(manifest_path),
        cli_curriculum_level="easy",
    )

    assert result["curriculum_level"] == "easy"
    assert result["manifest_path_runtime_only"] == str(manifest_path)
    assert result["train_sample_count"] == len(manifest_payload["train_samples"])
    assert result["dev_sample_count"] == len(manifest_payload["dev_samples"])
    assert set(result["source_kind_distribution"]) == {"atomic_k1", "synthetic_k2"}
