from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.train.ablate_stage1_slot_competition import (
    build_stage1_slot_competition_settings,
    epoch_phase_for_setting,
    rank_ablation_results,
    run_stage1_slot_competition_ablation,
    select_train_samples_for_phase,
)
from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests


class _Sample:
    def __init__(self, source_kind: str) -> None:
        self.source_kind = source_kind


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


def test_ablation_runner_builds_required_settings() -> None:
    settings = {item["setting_name"]: item for item in build_stage1_slot_competition_settings()}

    assert "S0_current_normal_medium" in settings
    assert "S3_align_only_warmup_then_full" in settings
    assert "S5_disable_deterministic_coupling" in settings


def test_align_only_warmup_switches_loss_weights_and_coupling() -> None:
    setting = next(
        item for item in build_stage1_slot_competition_settings() if item["setting_name"] == "S3_align_only_warmup_then_full"
    )

    warmup = epoch_phase_for_setting(setting, epoch_index=0)
    full = epoch_phase_for_setting(setting, epoch_index=7)

    assert warmup["lambda_align"] == 1.0
    assert warmup["lambda_count"] == 0.0
    assert warmup["lambda_exist"] == 0.0
    assert warmup["enable_existence_mass_coupling"] is False
    assert warmup["enable_count_pb_coupling"] is False

    assert full["lambda_align"] == 1.0
    assert full["lambda_count"] == 0.5
    assert full["lambda_exist"] == 0.5
    assert full["enable_existence_mass_coupling"] is True
    assert full["enable_count_pb_coupling"] is True


def test_k2_focused_warmup_excludes_k1_samples_early() -> None:
    setting = next(
        item for item in build_stage1_slot_competition_settings() if item["setting_name"] == "S4_k2_focused_warmup_then_mixed"
    )
    samples = [_Sample("atomic_k1"), _Sample("synthetic_k2"), _Sample("atomic_k1"), _Sample("synthetic_k2")]

    warmup_samples = select_train_samples_for_phase(samples, epoch_phase_for_setting(setting, epoch_index=0))
    full_samples = select_train_samples_for_phase(samples, epoch_phase_for_setting(setting, epoch_index=7))

    assert all(sample.source_kind == "synthetic_k2" for sample in warmup_samples)
    assert any(sample.source_kind == "atomic_k1" for sample in full_samples)


def test_disable_coupling_setting_turns_off_both_couplings() -> None:
    setting = next(
        item
        for item in build_stage1_slot_competition_settings()
        if item["setting_name"] == "S5_disable_deterministic_coupling"
    )

    phase = epoch_phase_for_setting(setting, epoch_index=3)

    assert phase["enable_existence_mass_coupling"] is False
    assert phase["enable_count_pb_coupling"] is False


def test_report_ranking_fields_exist() -> None:
    ranking = rank_ablation_results(
        [
            {
                "setting_name": "S0_current_normal_medium",
                "k2_split_recall": 0.0,
                "second_slot_gold_recall": 0.0,
                "unit_accuracy_gain_over_all_one": 0.0,
                "slot_collapse_rate": 0.56,
                "count_accuracy": 0.70,
            },
            {
                "setting_name": "S3_align_only_warmup_then_full",
                "k2_split_recall": 0.55,
                "second_slot_gold_recall": 0.42,
                "unit_accuracy_gain_over_all_one": 0.08,
                "slot_collapse_rate": 0.38,
                "count_accuracy": 0.62,
            },
        ]
    )

    assert ranking["best_by_k2_split_recall"] == "S3_align_only_warmup_then_full"
    assert ranking["best_by_second_slot_gold_recall"] == "S3_align_only_warmup_then_full"
    assert ranking["best_by_unit_accuracy_gain"] == "S3_align_only_warmup_then_full"
    assert ranking["best_by_lowest_slot_collapse"] == "S3_align_only_warmup_then_full"
    assert ranking["best_balanced_setting"] == "S3_align_only_warmup_then_full"


def test_ablation_settings_stay_within_stage1_sources() -> None:
    settings = build_stage1_slot_competition_settings()

    for setting in settings:
        assert setting["uses_only_stage1_sources"] is True
        assert setting["uses_hard_b_or_m"] is False


def test_ablation_runner_writes_reports_and_rankings_without_hard_b_or_m(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    curriculum_root = tmp_path / "curriculum_outputs"
    reports_root = tmp_path / "reports"
    output_root = tmp_path / "ablation_outputs"
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
    base_setting = dict(build_stage1_slot_competition_settings()[0])
    base_setting["epochs"] = 1
    base_setting["phases"] = [dict(base_setting["phases"][0], epoch_count=1)]

    payload = run_stage1_slot_competition_ablation(
        curriculum_manifest=manifests["medium"]["manifest_path"],
        synthetic_jsonl=str(synthetic_jsonl),
        atomic_csv=str(atomic_csv),
        output_root=str(output_root),
        reports_root=str(reports_root),
        settings=[base_setting],
    )

    assert payload["uses_only_stage1_sources"] is True
    assert payload["uses_hard_b_or_m"] is False
    assert "best_balanced_setting" in payload["ranking"]
    assert (reports_root / "mica_stage1_slot_competition_ablation_result.json").exists()
    assert (reports_root / "mica_stage1_slot_competition_ablation_result.md").exists()
