from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.train.train_stage1_sanity import run_stage1_sanity


def _write_atomic_csv(path: Path) -> None:
    fieldnames = [
        "repo",
        "sha",
        "type",
        "subject",
        "message",
        "git_diff",
        "source_confidence",
    ]
    rows = []
    for index in range(6):
        rows.append(
            {
                "repo": "acme/demo",
                "sha": f"a{index:03d}",
                "type": "fix",
                "subject": f"fix: guard case {index}",
                "message": f"fix: guard case {index}",
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
        writer.writerows(rows)


def _write_synthetic_jsonl(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(8):
            row = {
                "sample_id": f"syn_{index:03d}",
                "repo": "acme/demo",
                "intent_count": 2,
                "intent_types": ["fix", "test"],
                "intent_subjects": [f"fix: guard {index}", f"test: cover guard {index}"],
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
+""",
                "edit_units": [
                    {"file_path": f"src/main_{index}.py", "hunk_index_in_file": 1, "header": "@@ -1,2 +1,3 @@", "intent_id": 0},
                    {"file_path": f"tests/test_main_{index}.py", "hunk_index_in_file": 1, "header": "@@ -0,0 +1,3 @@", "intent_id": 1},
                ],
                "edit_to_intent": [0, 1],
                "final_sample_weight": 1.0,
            }
            handle.write(json.dumps(row) + "\n")


def test_stage1_sanity_smoke_runs_on_tiny_cpu_fixture(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_dir = tmp_path / "mica_outputs"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    result = run_stage1_sanity(
        {
            "atomic_csv": str(atomic_csv),
            "synthetic_jsonl": str(synthetic_jsonl),
            "max_train_samples": 8,
            "max_dev_samples": 4,
            "batch_size": 4,
            "epochs": 2,
            "Kmax": 4,
            "learning_rate": 1e-3,
            "seed": 42,
            "device": "cpu",
            "output_root": str(output_dir),
        }
    )

    assert result["training_not_run"] is False
    assert result["train_sample_count"] > 0
    assert result["dev_sample_count"] > 0
    assert 0.0 <= result["count_accuracy"] <= 1.0
    assert "oracle_k_alignment_pairwise_f1" in result
    assert "predicted_k_alignment_pairwise_f1" in result
    assert "train_loss_first_epoch" in result
    assert "train_loss_last_epoch" in result
    assert set(result["source_kind_distribution"]) == {"atomic_k1", "synthetic_k2"}
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "training_log.jsonl").exists()
    assert (output_dir / "dev_predictions_sample.jsonl").exists()
    assert (output_dir / "reports" / "mica_stage1_sanity_result.json").exists()
    assert (output_dir / "reports" / "mica_stage1_sanity_result.md").exists()
