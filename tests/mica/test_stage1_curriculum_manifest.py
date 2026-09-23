from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests


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
    rows = []
    for index in range(6):
        rows.append(
            {
                "sample_id": f"syn_easy_{index}",
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
        )
    rows.append(
        {
            "sample_id": "syn_medium_good",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": """diff --git a/src/main.py b/src/main.py
index 1..2 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def run():
+    value = normalize(value)
     return value
@@ -4,2 +5,3 @@
 def run():
+    return clamp(value)
     return value
@@ -8,2 +9,3 @@
 def run():
+    logger.info(value)
     return value
@@ -12,2 +13,3 @@
 def run():
+    value = format(value)
     return value
""",
            "edit_to_intent": [0, 1, 0, 1],
        }
    )
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_build_stage1_curriculum_manifests_constructs_easy_manifest_and_records_medium_fallback(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_root = tmp_path / "outputs" / "mica_stage1_curriculum_20260614T000000Z"
    reports_root = tmp_path / "reports"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    result = build_stage1_curriculum_manifests(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=output_root,
        reports_root=reports_root,
        k1_train_count=2,
        k2_train_count=2,
        k1_dev_count=1,
        k2_dev_count=1,
        split_seed=42,
    )

    easy = result["easy"]["summary"]
    medium = result["medium"]["summary"]

    assert easy["train_count"] == 4
    assert easy["dev_count"] == 2
    assert easy["fallback_applied"] is False
    assert medium["fallback_applied"] is True
    assert medium["fallback_reason"]
    assert (output_root / "manifest_easy.json").exists()
    assert (output_root / "manifest_medium.json").exists()
    assert (output_root / "manifest_hard.json").exists()

    summary_json = (reports_root / "mica_stage1_curriculum_manifest_summary.json").read_text(encoding="utf-8")
    summary_md = (reports_root / "mica_stage1_curriculum_manifest_summary.md").read_text(encoding="utf-8")
    assert "diff --git" not in summary_json
    assert "diff --git" not in summary_md

