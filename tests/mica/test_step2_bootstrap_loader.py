from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.load_step2_bootstrap import load_stage1_strict_bootstrap


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
    rows = [
        {
            "repo": "acme/demo",
            "sha": "aaa111",
            "type": "fix",
            "subject": "fix: correct null guard",
            "message": "fix: correct null guard",
            "git_diff": """diff --git a/src/main.py b/src/main.py
index 1..2 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,3 @@
 def run():
+    if value is None:
     return 1
""",
            "source_confidence": "1.0",
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_synthetic_jsonl(path: Path) -> None:
    rows = [
        {
            "sample_id": "syn_001",
            "repo": "acme/demo",
            "intent_count": 2,
            "intent_types": ["fix", "test"],
            "intent_subjects": ["fix: correct null guard", "test: add guard coverage"],
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
            "final_sample_weight": 0.9,
        },
        {
            "sample_id": "syn_bad",
            "repo": "acme/demo",
            "intent_count": 2,
            "intent_types": ["fix", "test"],
            "intent_subjects": ["fix: correct null guard", "test: add guard coverage"],
            "synthetic_diff": "diff --git a/a b/a\n",
            "edit_units": [],
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_load_stage1_strict_bootstrap_builds_atomic_and_synthetic_samples(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=atomic_csv,
        synthetic_jsonl_path=synthetic_jsonl,
        max_atomic_samples=1,
        max_synthetic_samples=2,
        split_ratios=(0.5, 0.5, 0.0),
        split_seed=7,
    )

    samples = bundle.train + bundle.dev + bundle.test
    assert len(samples) == 2
    atomic_sample = next(sample for sample in samples if sample.source_kind == "atomic_k1")
    synthetic_sample = next(sample for sample in samples if sample.source_kind == "synthetic_k2")

    assert atomic_sample.gold_count == 1
    assert atomic_sample.is_multi_intent is False
    assert {unit.gold_intent_id for unit in atomic_sample.edit_units} == {0}

    assert synthetic_sample.gold_count == 2
    assert synthetic_sample.is_multi_intent is True
    assert synthetic_sample.gold_unit_to_intent == {
        "syn_001::u0000": 0,
        "syn_001::u0001": 1,
    }
    assert bundle.skipped == [{"sample_id": "syn_bad", "reason": "missing_edit_to_intent"}]


def test_load_stage1_strict_bootstrap_accepts_large_atomic_diff_field(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic_large.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    _write_synthetic_jsonl(synthetic_jsonl)

    large_diff = (
        "diff --git a/src/big.py b/src/big.py\n"
        "index 1..2 100644\n"
        "--- a/src/big.py\n"
        "+++ b/src/big.py\n"
        "@@ -1,1 +1,70001 @@\n"
        " def run():\n"
        + ("+x\n" * 70000)
    )
    with atomic_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "repo",
                "sha",
                "type",
                "subject",
                "message",
                "git_diff",
                "source_confidence",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "repo": "acme/demo",
                "sha": "big111",
                "type": "fix",
                "subject": "fix: big diff",
                "message": "fix: big diff",
                "git_diff": large_diff,
                "source_confidence": "1.0",
            }
        )

    bundle = load_stage1_strict_bootstrap(
        atomic_csv_path=atomic_csv,
        synthetic_jsonl_path=synthetic_jsonl,
        max_atomic_samples=1,
        max_synthetic_samples=1,
    )

    samples = bundle.train + bundle.dev + bundle.test
    assert any(sample.source_kind == "atomic_k1" for sample in samples)
