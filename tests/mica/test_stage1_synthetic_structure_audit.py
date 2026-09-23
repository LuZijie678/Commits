from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.audit_stage1_synthetic_structure import audit_stage1_synthetic_structure


def _write_atomic_csv(path: Path, *, rows: int = 4) -> None:
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
    rows = [
        {
            "sample_id": "syn_path_dominated",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": """diff --git a/src/main.py b/src/main.py
index 1..2 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def run():
+    if left is None:
     return 1
@@ -4,2 +5,3 @@
 def build():
+    if right is None:
     return 2
diff --git a/tests/test_main.py b/tests/test_main.py
index 3..4 100644
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -0,0 +1,3 @@
+def test_run():
+    assert run() == 1
@@ -4,0 +5,3 @@
+def test_build():
+    assert build() == 2
""",
            "edit_to_intent": [0, 0, 1, 1],
            "intent_types": ["fix", "test"],
            "intent_subjects": ["fix: guard", "test: cover guard"],
        },
        {
            "sample_id": "syn_nondegenerate",
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
            "intent_types": ["logic", "logging"],
            "intent_subjects": ["refine logic", "refine logging"],
        },
        {
            "sample_id": "syn_singleton_dominated",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": """diff --git a/src/app.py b/src/app.py
index 1..2 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 def run():
+    value = normalize(value)
     return value
@@ -4,2 +5,3 @@
 def run():
+    return clamp(value)
     return value
diff --git a/docs/app.md b/docs/app.md
index 3..4 100644
--- a/docs/app.md
+++ b/docs/app.md
@@ -0,0 +1,3 @@
+Document run behavior.
""",
            "edit_to_intent": [0, 0, 1],
            "intent_types": ["logic", "docs"],
            "intent_subjects": ["refine logic", "document behavior"],
        },
        {
            "sample_id": "syn_missing_alignment",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": "diff --git a/src/a.py b/src/a.py\n",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_stage1_synthetic_structure_audit_detects_degenerate_and_nondegenerate_samples(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_root = tmp_path / "outputs" / "mica_stage1_structure_audit_20260614T000000Z"
    reports_root = tmp_path / "reports"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    result = audit_stage1_synthetic_structure(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=output_root,
        reports_root=reports_root,
    )

    assert result["summary"]["synthetic_total"] == 4
    assert result["summary"]["synthetic_loaded"] == 3
    assert result["summary"]["synthetic_skipped_missing_alignment"] == 1
    assert result["summary"]["singleton_dominated_candidate_count"] == 1
    assert result["summary"]["path_dominated_candidate_count"] == 1
    assert result["summary"]["nondegenerate_candidate_count"] == 1
    assert result["summary"]["same_file_k2_fraction"] > 0.0
    assert result["summary"]["cross_file_k2_fraction"] > 0.0
    assert (output_root / "synthetic_structure_details.jsonl").exists()

    audit_json = (reports_root / "mica_stage1_synthetic_structure_audit.json").read_text(encoding="utf-8")
    audit_md = (reports_root / "mica_stage1_synthetic_structure_audit.md").read_text(encoding="utf-8")
    assert "diff --git" not in audit_json
    assert "diff --git" not in audit_md

