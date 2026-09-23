from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_sanity_manifest import build_stage1_sanity_manifest


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
    for index in range(4):
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
    rows = [
        {
            "sample_id": "syn_good",
            "repo": "acme/demo",
            "intent_count": 2,
            "intent_types": ["fix", "test"],
            "intent_subjects": ["fix: guard", "test: cover guard"],
            "synthetic_diff": """diff --git a/src/main.py b/src/main.py
index 1..2 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def run():
+    if value is None:
     return 1
diff --git a/tests/test_main.py b/tests/test_main.py
index 3..4 100644
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -0,0 +1,3 @@
+def test_run():
+    assert run() == 1
+""",
            "edit_units": [
                {"file_path": "src/main.py", "hunk_index_in_file": 1, "header": "@@ -1,2 +1,3 @@", "intent_id": 0},
                {"file_path": "tests/test_main.py", "hunk_index_in_file": 1, "header": "@@ -0,0 +1,3 @@", "intent_id": 1},
            ],
            "edit_to_intent": [0, 1],
            "final_sample_weight": 1.0,
        },
        {
            "sample_id": "syn_missing_alignment",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": "diff --git a/src/a.py b/src/a.py\n",
            "edit_units": [],
        },
        {
            "sample_id": "syn_empty_units",
            "repo": "acme/demo",
            "intent_count": 2,
            "synthetic_diff": "",
            "edit_units": [],
            "edit_to_intent": [0, 1],
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_build_stage1_sanity_manifest_writes_runtime_manifest_and_lightweight_reports(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_root = tmp_path / "outputs" / "mica_stage1_sanity_20260614T000000Z"
    reports_root = tmp_path / "reports"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    result = build_stage1_sanity_manifest(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=output_root,
        reports_root=reports_root,
        max_train_samples=10,
        max_dev_samples=10,
        split_seed=42,
    )

    assert result["manifest_path"] == str(output_root / "stage1_sanity_manifest.json")
    assert result["audit"]["atomic_loaded"] == 4
    assert result["audit"]["synthetic_loaded"] == 1
    assert result["audit"]["synthetic_skipped_missing_alignment"] == 1
    assert result["audit"]["synthetic_skipped_empty_units"] == 1
    assert result["audit"]["source_path_is_local_runtime_only"] is True
    assert result["audit"]["sanity_only"] is True
    assert result["audit"]["train_count"] + result["audit"]["dev_count"] <= 5

    manifest_payload = json.loads((output_root / "stage1_sanity_manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["audit"]["k1_train"] + manifest_payload["audit"]["k1_dev"] >= 1
    assert manifest_payload["audit"]["k2_train"] + manifest_payload["audit"]["k2_dev"] >= 1

    audit_json = (reports_root / "mica_stage1_sanity_data_audit.json").read_text(encoding="utf-8")
    audit_md = (reports_root / "mica_stage1_sanity_data_audit.md").read_text(encoding="utf-8")
    assert "diff --git" not in audit_json
    assert "diff --git" not in audit_md
