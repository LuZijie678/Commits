from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.formal_assets import (
    FORMAL_ASSET_MANIFEST_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    build_formal_asset_manifests,
)
from code.mica.io_utils import read_json


def _write_step1_atomic_csv(path: Path, *, rows: int = 18) -> None:
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
                "repo": f"acme/atomic-repo-{index % 6}",
                "sha": f"a{index:04d}",
                "type": "fix",
                "subject": f"fix value {index}",
                "message": f"fix: value {index}",
                "git_diff": f"""diff --git a/src/atomic_{index}.py b/src/atomic_{index}.py
index 1..2 100644
--- a/src/atomic_{index}.py
+++ b/src/atomic_{index}.py
@@ -1,2 +1,3 @@
 def run():
+    value_{index} = normalize(value_{index})
     return 1
""",
                "source_confidence": "1.0",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload)


def _write_strict_synthetic_jsonl(path: Path, *, rows: int = 24) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(rows):
            row = {
                "sample_id": f"synthetic_{index:04d}",
                "repo": f"acme/synth-repo-{index % 6}",
                "intent_count": 2,
                "intent_k": 2,
                "intent_subjects": [f"alpha {index}", f"beta {index}"],
                "intent_types": ["fix", "refactor"],
                "synthetic_diff": f"""diff --git a/src/left_{index}.py b/src/left_{index}.py
index 1..2 100644
--- a/src/left_{index}.py
+++ b/src/left_{index}.py
@@ -1,2 +1,3 @@
 def left():
+    left_{index} = normalize(left_{index})
     return left_{index}
@@ -5,2 +6,3 @@
 def right():
+    right_{index} = clamp(right_{index})
     return right_{index}
""",
                "edit_to_intent": [0, 1],
                "final_sample_weight": 1.0,
                "sources": [
                    {
                        "repo": f"acme/synth-repo-{index % 6}",
                        "sha": f"s{index:04d}",
                        "subject": f"alpha {index}",
                        "type": "fix",
                    },
                    {
                        "repo": f"acme/synth-repo-{index % 6}",
                        "sha": f"t{index:04d}",
                        "subject": f"beta {index}",
                        "type": "refactor",
                    },
                ],
                "construction_type": "same_repo_multi_round_robin_v1",
                "construction_route": "route_2_multi_intent",
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_m_verified_csv(path: Path, *, rows: int = 18) -> None:
    fieldnames = [
        "repo",
        "sha",
        "subject",
        "commit_message",
        "llm_label",
        "llm_intent_count_estimate",
        "git_diff",
        "diff_status",
    ]
    payload = []
    for index in range(rows):
        payload.append(
            {
                "repo": f"acme/m-repo-{index % 6}",
                "sha": f"m{index:04d}",
                "subject": f"feat and docs {index}",
                "commit_message": f"feat and docs {index}",
                "llm_label": "M",
                "llm_intent_count_estimate": "2",
                "git_diff": f"""diff --git a/src/m_{index}.py b/src/m_{index}.py
index 1..2 100644
--- a/src/m_{index}.py
+++ b/src/m_{index}.py
@@ -1,2 +1,3 @@
 def handler():
+    token_{index} = validate(token_{index})
     return token_{index}
""",
                "diff_status": "ok",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload)


def _write_hard_b_csv(path: Path, *, rows: int = 12) -> None:
    fieldnames = [
        "repo",
        "sha",
        "subject",
        "commit_message",
        "git_diff",
        "diff_status",
    ]
    payload = []
    for index in range(rows):
        payload.append(
            {
                "repo": f"acme/hardb-repo-{index % 4}",
                "sha": f"h{index:04d}",
                "subject": f"single intent {index}",
                "commit_message": f"single intent {index}",
                "git_diff": f"""diff --git a/src/hb_{index}.py b/src/hb_{index}.py
index 1..2 100644
--- a/src/hb_{index}.py
+++ b/src/hb_{index}.py
@@ -1,2 +1,3 @@
 def hb():
+    state_{index} = refresh(state_{index})
     return state_{index}
""",
                "diff_status": "ok",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload)


def test_build_formal_asset_manifests_writes_registry_populates_existing_assets_and_marks_missing_manual_assets(
    tmp_path: Path,
) -> None:
    step1_atomic_csv = tmp_path / "step1_atomic.csv"
    strict_synthetic_jsonl = tmp_path / "strict_synthetic.jsonl"
    m_verified_csv = tmp_path / "m_verified.csv"
    hard_b_csv = tmp_path / "hard_b.csv"
    _write_step1_atomic_csv(step1_atomic_csv)
    _write_strict_synthetic_jsonl(strict_synthetic_jsonl)
    _write_m_verified_csv(m_verified_csv)
    _write_hard_b_csv(hard_b_csv)

    result = build_formal_asset_manifests(
        step1_atomic_csv=step1_atomic_csv,
        strict_synthetic_jsonl=strict_synthetic_jsonl,
        m_verified_csv=m_verified_csv,
        hard_b_csv=hard_b_csv,
        output_root=tmp_path / "formal_assets",
        stage1_counts={"train": 4, "dev": 2, "test": 2},
        stage2_split_ratios=(0.5, 0.25, 0.25),
        split_seed=13,
    )

    registry = read_json(result["registry_path"])
    assert registry["schema_version"] == REGISTRY_SCHEMA_VERSION
    assert registry["assets"]["step1_high_conf_single_train"]["status"] == "frozen"
    assert registry["assets"]["strict_synthetic_train"]["status"] == "frozen"
    assert registry["assets"]["hard_b_train"]["status"] == "frozen"
    assert registry["assets"]["m_weak_train"]["status"] == "frozen"
    assert registry["assets"]["m_align_calib"]["status"] == "pending_annotation"
    assert registry["assets"]["real_alignment_dev"]["status"] == "pending_annotation"
    assert registry["assets"]["oracle_plans"]["status"] == "pending_generation"

    stage1_manifest = read_json(Path(registry["assets"]["strict_synthetic_train"]["path"]))
    assert stage1_manifest["schema_version"] == FORMAL_ASSET_MANIFEST_SCHEMA_VERSION
    assert stage1_manifest["formal_ready"] is True
    assert stage1_manifest["summary"]["duplicate_count"] == 0
    assert stage1_manifest["summary"]["leakage_group_overlap_count"] == 0

    m_weak_manifest = read_json(Path(registry["assets"]["m_weak_train"]["path"]))
    assert m_weak_manifest["rows"][0]["cardinality_label_type"] == "censored_k_ge_2"
    assert m_weak_manifest["rows"][0]["weak_label"] == "censored_k_ge_2"

