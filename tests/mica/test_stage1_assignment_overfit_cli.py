from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.train.overfit_stage1_assignment import run_stage1_assignment_overfit


def _write_atomic_csv(path: Path, *, rows: int = 10) -> None:
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


def _write_synthetic_jsonl(path: Path, *, rows: int = 12) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(rows):
            row = {
                "sample_id": f"syn_medium_{index:03d}",
                "repo": "acme/demo",
                "intent_count": 2,
                "synthetic_diff": f"""diff --git a/src/main_{index}.py b/src/main_{index}.py
index 1..2 100644
--- a/src/main_{index}.py
+++ b/src/main_{index}.py
@@ -1,2 +1,3 @@
 def run():
+    value = normalize(value_{index})
     return 1
@@ -4,2 +5,3 @@
 def run():
+    value = clamp(value_{index})
     return 1
@@ -8,2 +9,3 @@
 def test_run():
+    assert run() == 1
     return None
@@ -12,2 +13,3 @@
 def test_run():
+    assert helper() == 1
     return None
""",
                "edit_to_intent": [0, 0, 1, 1],
            }
            handle.write(json.dumps(row) + "\n")


def test_overfit_cli_runs_on_medium_manifest_without_hard_b_or_m(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    curriculum_root = tmp_path / "curriculum_outputs"
    reports_root = tmp_path / "reports"
    output_root = tmp_path / "overfit_outputs"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    manifests = build_stage1_curriculum_manifests(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=curriculum_root,
        reports_root=reports_root,
        k1_train_count=4,
        k2_train_count=4,
        k1_dev_count=2,
        k2_dev_count=2,
        split_seed=42,
    )

    result = run_stage1_assignment_overfit(
        manifest_json=manifests["medium"]["manifest_path"],
        atomic_csv=str(atomic_csv),
        synthetic_jsonl=str(synthetic_jsonl),
        output_root=str(output_root),
        reports_root=str(reports_root),
        settings=[
            {
                "setting_name": "tiny_k2_only",
                "k2_count": 4,
                "k1_count": 0,
                "epochs": 2,
                "batch_size": 2,
                "learning_rate": 1e-3,
                "device": "cpu",
                "seed": 42,
                "align_only": False,
            }
        ],
    )

    assert result["training_run"] is True
    assert result["uses_only_stage1_sources"] is True
    assert result["uses_hard_b_or_m"] is False
    assert result["settings"][0]["setting_name"] == "tiny_k2_only"
