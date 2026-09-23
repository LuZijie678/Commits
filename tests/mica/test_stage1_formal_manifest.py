from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_formal_manifest import build_stage1_formal_manifest


def _write_atomic_csv(path: Path, *, rows: int = 24) -> None:
    fieldnames = ["repo", "sha", "type", "subject", "message", "git_diff", "source_confidence"]
    payload = []
    for index in range(rows):
        payload.append(
            {
                "repo": f"acme/repo-{index % 3}",
                "sha": f"a{index:04d}",
                "type": "fix",
                "subject": f"guard value {index}",
                "message": f"fix: guard value {index}",
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


def _medium_diff(index: int) -> str:
    return f"""diff --git a/src/main_{index}.py b/src/main_{index}.py
index 1..2 100644
--- a/src/main_{index}.py
+++ b/src/main_{index}.py
@@ -1,2 +1,3 @@
 def alpha():
+    alpha_{index} = normalize(alpha_{index})
     return alpha
@@ -4,2 +5,3 @@
 def beta():
+    beta_{index} = normalize(beta_{index})
     return beta
@@ -8,2 +10,3 @@
 def alpha_extra():
+    alpha_{index} = clamp(alpha_{index})
     return alpha
@@ -12,2 +15,3 @@
 def beta_extra():
+    beta_{index} = clamp(beta_{index})
     return beta
"""


def _write_synthetic_jsonl(path: Path, *, rows: int = 24) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(rows):
            row = {
                "sample_id": f"synthetic_medium_{index:04d}",
                "repo": f"acme/repo-{index % 3}",
                "intent_count": 2,
                "source_sha": f"s{index:04d}",
                "intent_subjects": [f"alpha {index}", f"beta {index}"],
                "synthetic_diff": _medium_diff(index),
                "edit_to_intent": [0, 1, 0, 1],
                "final_sample_weight": 1.0,
            }
            handle.write(json.dumps(row) + "\n")


def test_formal_manifest_builder_generates_train_dev_test_and_summary(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_root = tmp_path / "outputs" / "mica_stage1_formal_manifest_20260615T000000Z"
    reports_root = tmp_path / "reports"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    payload = build_stage1_formal_manifest(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=output_root,
        reports_root=reports_root,
        seed=42,
        train_k1=4,
        train_k2=4,
        dev_k1=2,
        dev_k2=2,
        test_k1=2,
        test_k2=2,
    )

    assert payload["formal_manifest_status"] == "frozen_runtime_manifest_created"
    assert payload["schedule_candidate"] == "naive_balanced_mixed_large_scale"
    assert payload["stage2_allowed"] is False
    assert payload["runtime_manifest_not_committed"] is True
    assert payload["counts"]["train"]["atomic_k1"] == 4
    assert payload["counts"]["train"]["synthetic_k2"] == 4
    assert payload["counts"]["dev"]["atomic_k1"] == 2
    assert payload["counts"]["test"]["synthetic_k2"] == 2
    assert payload["leakage_checks"]["sample_id_overlap_count"] == 0
    assert "sha_overlap_checks" in payload["leakage_checks"]
    assert payload["forbidden_data_sources"]["stage2_loss"] is False
    assert payload["forbidden_data_sources"]["hard_b"] is False

    full_manifest = json.loads((output_root / "stage1_formal_manifest.json").read_text(encoding="utf-8"))
    assert {"train", "dev", "test"} == set(full_manifest["splits"])
    assert all(row["medium_candidate"] for row in full_manifest["splits"]["train"] if row["source_kind"] == "synthetic_k2")
    assert not any("diff --git" in json.dumps(row) for split in full_manifest["splits"].values() for row in split)

    summary_json = (reports_root / "mica_stage1_formal_manifest_summary.json").read_text(encoding="utf-8")
    summary_md = (reports_root / "mica_stage1_formal_manifest_summary.md").read_text(encoding="utf-8")
    assert "diff --git" not in summary_json
    assert "diff --git" not in summary_md


def test_formal_manifest_records_downgrade_when_counts_are_unavailable(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    _write_atomic_csv(atomic_csv, rows=5)
    _write_synthetic_jsonl(synthetic_jsonl, rows=5)

    payload = build_stage1_formal_manifest(
        atomic_csv=atomic_csv,
        synthetic_jsonl=synthetic_jsonl,
        output_root=tmp_path / "outputs" / "manifest",
        reports_root=tmp_path / "reports",
        seed=42,
        train_k1=20,
        train_k2=20,
        dev_k1=10,
        dev_k2=10,
        test_k1=10,
        test_k2=10,
    )

    assert payload["formal_manifest_downgraded"] is True
    assert payload["downgrade_reason"]
    assert payload["fallback_applied"] is True
