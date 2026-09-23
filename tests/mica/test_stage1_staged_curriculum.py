from __future__ import annotations

import csv
import json
from pathlib import Path

from code.mica.data.build_stage1_curriculum_manifest import build_stage1_curriculum_manifests
from code.mica.train.run_stage1_staged_curriculum import (
    build_stage1_staged_curriculum_settings,
    epoch_phase_for_setting,
    rank_staged_curriculum_results,
    run_stage1_staged_curriculum,
    select_train_samples_for_phase,
)


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


def test_staged_runner_builds_required_settings() -> None:
    settings = {item["setting_name"]: item for item in build_stage1_staged_curriculum_settings()}

    assert "T0_k2_only_reference" in settings
    assert "T1_long_k2_specialization_then_gentle_k1_reintroduction" in settings
    assert "T2_k2_specialization_with_replay_protected_mixed_training" in settings
    assert "T3_align_preserving_mixed_training" in settings
    assert "T5_disable_deterministic_coupling_during_reintroduction" in settings


def test_align_preserving_schedule_switches_loss_weights() -> None:
    setting = next(
        item for item in build_stage1_staged_curriculum_settings() if item["setting_name"] == "T3_align_preserving_mixed_training"
    )

    warmup = epoch_phase_for_setting(setting, epoch_index=0)
    later = epoch_phase_for_setting(setting, epoch_index=10)

    assert warmup["resolved_lambda_align"] == 1.0
    assert warmup["resolved_lambda_count"] == 0.0
    assert warmup["resolved_lambda_exist"] == 0.0
    assert warmup["enable_existence_mass_coupling"] is False
    assert warmup["enable_count_pb_coupling"] is False

    assert later["resolved_lambda_align"] == 1.0
    assert 0.2 <= later["resolved_lambda_count"] <= 0.5
    assert 0.2 <= later["resolved_lambda_exist"] <= 0.5


def test_k2_only_phase_excludes_k1() -> None:
    setting = next(
        item
        for item in build_stage1_staged_curriculum_settings()
        if item["setting_name"] == "T1_long_k2_specialization_then_gentle_k1_reintroduction"
    )
    samples = [_Sample("atomic_k1"), _Sample("synthetic_k2"), _Sample("atomic_k1"), _Sample("synthetic_k2")]

    warmup_samples = select_train_samples_for_phase(samples, epoch_phase_for_setting(setting, epoch_index=0))
    mixed_samples = select_train_samples_for_phase(samples, epoch_phase_for_setting(setting, epoch_index=12))

    assert all(sample.source_kind == "synthetic_k2" for sample in warmup_samples)
    assert any(sample.source_kind == "atomic_k1" for sample in mixed_samples)


def test_gradual_k1_reintroduction_ratio_is_encoded() -> None:
    setting = next(
        item
        for item in build_stage1_staged_curriculum_settings()
        if item["setting_name"] == "T1_long_k2_specialization_then_gentle_k1_reintroduction"
    )
    phase_mid = epoch_phase_for_setting(setting, epoch_index=8)
    phase_late = epoch_phase_for_setting(setting, epoch_index=13)

    assert phase_mid["k2_to_k1_ratio"] == [3, 1]
    assert phase_late["k2_to_k1_ratio"] == [1, 1]


def test_disable_coupling_schedule_turns_off_both_couplings() -> None:
    setting = next(
        item
        for item in build_stage1_staged_curriculum_settings()
        if item["setting_name"] == "T5_disable_deterministic_coupling_during_reintroduction"
    )

    phase = epoch_phase_for_setting(setting, epoch_index=10)

    assert phase["enable_existence_mass_coupling"] is False
    assert phase["enable_count_pb_coupling"] is False


def test_report_ranking_fields_exist() -> None:
    ranking = rank_staged_curriculum_results(
        [
            {
                "setting_name": "T0_k2_only_reference",
                "k2_split_recall_mixed": 0.20,
                "second_slot_gold_recall_mixed": 0.10,
                "unit_accuracy_gain_over_all_one_mixed": 0.01,
                "slot_collapse_rate_mixed": 0.55,
                "count_accuracy_mixed": 0.70,
                "over_split_rate_on_k1_mixed": 0.50,
            },
            {
                "setting_name": "T3_align_preserving_mixed_training",
                "k2_split_recall_mixed": 0.60,
                "second_slot_gold_recall_mixed": 0.45,
                "unit_accuracy_gain_over_all_one_mixed": 0.08,
                "slot_collapse_rate_mixed": 0.35,
                "count_accuracy_mixed": 0.62,
                "over_split_rate_on_k1_mixed": 0.30,
            },
        ]
    )

    assert ranking["best_by_mixed_second_slot_gold_recall"] == "T3_align_preserving_mixed_training"
    assert ranking["best_by_mixed_k2_split_recall"] == "T3_align_preserving_mixed_training"
    assert ranking["best_by_mixed_unit_accuracy_gain"] == "T3_align_preserving_mixed_training"
    assert ranking["best_by_lowest_mixed_slot_collapse"] == "T3_align_preserving_mixed_training"
    assert ranking["best_balanced_stage1_schedule"] == "T3_align_preserving_mixed_training"


def test_staged_settings_stay_within_stage1_sources() -> None:
    settings = build_stage1_staged_curriculum_settings()

    for setting in settings:
        assert setting["uses_only_stage1_sources"] is True
        assert setting["uses_hard_b_or_m"] is False


def test_runner_evaluates_mixed_and_k2_only_without_hard_b_or_m(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    curriculum_root = tmp_path / "curriculum_outputs"
    reports_root = tmp_path / "reports"
    output_root = tmp_path / "staged_outputs"
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
    base_setting = dict(build_stage1_staged_curriculum_settings()[0])
    base_setting["epochs"] = 1
    base_setting["phases"] = [dict(base_setting["phases"][0], epoch_count=1)]

    payload = run_stage1_staged_curriculum(
        curriculum_manifest=manifests["medium"]["manifest_path"],
        synthetic_jsonl=str(synthetic_jsonl),
        atomic_csv=str(atomic_csv),
        output_root=str(output_root),
        reports_root=str(reports_root),
        settings=[base_setting],
    )

    assert payload["uses_only_stage1_sources"] is True
    assert payload["uses_hard_b_or_m"] is False
    setting_payload = payload["settings"][0]
    assert "count_accuracy_mixed" in setting_payload
    assert "count_accuracy_k2_only" in setting_payload
    assert "best_balanced_stage1_schedule" in payload["ranking"]
    assert (reports_root / "mica_stage1_staged_curriculum_result.json").exists()
    assert (reports_root / "mica_stage1_staged_curriculum_result.md").exists()
