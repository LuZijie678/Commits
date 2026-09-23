import unittest
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

# 导入仅消息校准模块和原子挖掘模块
from src.pipeline import message_only_calibration as message_only_calibration
from src.pipeline import atomic_mining as miner


class MessageOnlyCalibrationTest(unittest.TestCase):
    def _base_primary_artifact(self) -> dict:
        # 构建基础主校准工件，用于测试仅消息校准
        return {
            "model_mode": "full_diff",
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            },
            "message_protocol": {"subject_len_min": 0},
            "scope_protocol": {"file_scope_small_max": 0},
            "type_protocol": {"values": {}},
            "epistemic_reference": {"center": 0.0, "scale": 1.0},
        }

    def _message_only_split_rows(
        self, repos: list[str], labels: list[str]
    ) -> list[dict]:
        # 生成仅消息校准的分割测试数据
        rows = []
        for idx, (repo, label) in enumerate(zip(repos, labels), start=1):
            commit_type = "fix" if label == "1" else "feat"
            subject = (
                f"fix: stabilize parser {idx}"
                if label == "1"
                else f"feat: add parser and logger {idx}"
            )
            rows.append(
                {
                    "sha": f"{repo.replace('/', '_')}-{idx}",
                    "repo": repo,
                    "type": commit_type,
                    "commit_message": subject,
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": label,
                }
            )
        return rows

    def test_build_labeled_examples_prefers_adjudicated_label(self) -> None:
        # 测试：当存在裁决标签时，优先使用裁决标签
        # is_single_intent=0, raw_label=0, 但adjudicated_label=1
        rows = [
            {
                "sha": "s1",
                "type": "fix",
                "commit_message": "fix: stabilize parser",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "0",
                "raw_label": "0",
                "adjudicated_label": "1",
            }
        ]
        calibration = {
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            }
        }
        examples = message_only_calibration.build_message_only_labeled_examples(
            rows=rows,
            base_calibration=calibration,
            label_col="is_single_intent",
        )
        self.assertEqual(examples[0]["label"], 1)  # 使用裁决标签

    def test_build_labeled_examples_rejects_missing_diff(self) -> None:
        # 测试：当git_diff为空时应抛出异常，仅消息校准需要差异信息
        rows = [
            {
                "sha": "s1",
                "type": "fix",
                "commit_message": "fix: stabilize parser",
                "git_diff": "",
                "is_single_intent": "1",
            }
        ]
        calibration = {
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            }
        }
        with self.assertRaises(ValueError):
            message_only_calibration.build_message_only_labeled_examples(
                rows=rows,
                base_calibration=calibration,
                label_col="is_single_intent",
            )

    def test_build_labeled_examples_returns_message_only_probs(self) -> None:
        # 测试：构建的示例应该包含仅消息模型的原始概率
        rows = [
            {
                "sha": "s1",
                "type": "fix",
                "commit_message": "fix: stabilize parser",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "1",
            },
            {
                "sha": "s2",
                "type": "feat",
                "commit_message": "feat: add parser and logger",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "0",
            },
        ]
        calibration = {
            "model_mode": "full_diff",
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            }
        }
        examples = message_only_calibration.build_message_only_labeled_examples(
            rows=rows,
            base_calibration=calibration,
            label_col="is_single_intent",
        )
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0]["label"], 1)
        self.assertEqual(examples[1]["label"], 0)
        # 验证原始概率在(0,1)区间内
        self.assertTrue(all(0.0 < row["raw_probability"] < 1.0 for row in examples))

    def test_fit_message_only_calibration_supports_platt_mode(self) -> None:
        # 测试：仅消息校准支持Platt缩放模式
        # 准备测试数据：5个fix正例，5个perf正例，5个feat负例，5个chore负例
        rows = []
        for idx in range(5):
            rows.append(
                {
                    "sha": f"pf{idx}",
                    "type": "fix",
                    "commit_message": f"fix: stabilize parser path {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "1",
                }
            )
        for idx in range(5):
            rows.append(
                {
                    "sha": f"pp{idx}",
                    "type": "perf",
                    "commit_message": f"perf: avoid double reference {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "1",
                }
            )
        for idx in range(5):
            rows.append(
                {
                    "sha": f"nf{idx}",
                    "type": "feat",
                    "commit_message": f"feat: add parser and logger {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "0",
                }
            )
        for idx in range(5):
            rows.append(
                {
                    "sha": f"nc{idx}",
                    "type": "chore",
                    "commit_message": f"chore(release): {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "0",
                }
            )
        calibration = {
            "model_mode": "full_diff",
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            },
            "message_protocol": {"subject_len_min": 0},
            "scope_protocol": {"file_scope_small_max": 0},
            "type_protocol": {"values": {}},
            "epistemic_reference": {"center": 0.0, "scale": 1.0},
        }
        with patch.object(
            message_only_calibration.base_fit,
            "apply_threshold_fallback_policy",
            return_value=None,
        ), patch.object(
            message_only_calibration.base_fit.miner,
            "derive_threshold_seed_from_distribution",
            return_value=(0.8, 0.6),
        ):
            artifact = message_only_calibration.fit_message_only_calibration(
                rows=rows,
                base_calibration=calibration,
                label_col="is_single_intent",
                scheme="holdout",  # 使用留出法
                holdout_ratio=0.2,
                cv_folds=5,
                tau_a_precision=0.9,
                tau_b_precision=0.7,
                random_state=42,
                threshold_fallback_policy="error",
                calibration_mode="platt",  # 采用Platt缩放
            )
        self.assertEqual(artifact["model_mode"], "message_only")
        self.assertEqual(artifact["model_role"], "proxy")  # 仅消息作为代理模型
        self.assertEqual(
            artifact["fit_config"]["base_primary_artifact_version"],
            "step1_atomic_gbdt_isotonic_v1",
        )
        self.assertEqual(artifact["fit_config"]["mode"], "message_only_platt")
        self.assertIn("platt_slope", artifact)
        self.assertGreater(artifact["thresholds"]["tau_a"], artifact["thresholds"]["tau_b"])
        self.assertIn("label_usage_summary", artifact["fit_config"])

    def test_explicit_split_repo_disjoint_eval_true_when_repos_are_disjoint(
        self,
    ) -> None:
        calibration_rows = self._message_only_split_rows(
            repos=["owner/a", "owner/b"],
            labels=["1", "0"],
        )
        evaluation_rows = self._message_only_split_rows(
            repos=["owner/c", "owner/d"],
            labels=["1", "0"],
        )
        with (
            patch.object(
                message_only_calibration.base_fit,
                "apply_threshold_fallback_policy",
                return_value=None,
            ),
            patch.object(
                message_only_calibration.base_fit.miner,
                "derive_threshold_seed_from_distribution",
                return_value=(0.8, 0.6),
            ),
        ):
            artifact = message_only_calibration.fit_message_only_calibration(
                rows=[],
                base_calibration=self._base_primary_artifact(),
                label_col="is_single_intent",
                scheme="cv",
                holdout_ratio=0.2,
                cv_folds=5,
                tau_a_precision=0.9,
                tau_b_precision=0.7,
                random_state=42,
                threshold_fallback_policy="error",
                calibration_mode="platt",
                calibration_rows=calibration_rows,
                evaluation_rows=evaluation_rows,
                split_roles={"calibration": {}, "evaluation": {}},
            )
        self.assertTrue(artifact["metrics"]["repo_disjoint_eval"])
        self.assertEqual(artifact["metrics"]["repo_overlap_count"], 0)
        self.assertEqual(artifact["metrics"]["repo_overlap_examples"], [])
        self.assertEqual(
            artifact["metrics"]["repo_set_calibration"], ["owner/a", "owner/b"]
        )
        self.assertEqual(
            artifact["metrics"]["repo_set_evaluation"], ["owner/c", "owner/d"]
        )

    def test_explicit_split_repo_disjoint_eval_false_when_repos_overlap(self) -> None:
        calibration_rows = self._message_only_split_rows(
            repos=["owner/a", "owner/b"],
            labels=["1", "0"],
        )
        evaluation_rows = self._message_only_split_rows(
            repos=["owner/b", "owner/c"],
            labels=["1", "0"],
        )
        with (
            patch.object(
                message_only_calibration.base_fit,
                "apply_threshold_fallback_policy",
                return_value=None,
            ),
            patch.object(
                message_only_calibration.base_fit.miner,
                "derive_threshold_seed_from_distribution",
                return_value=(0.8, 0.6),
            ),
        ):
            artifact = message_only_calibration.fit_message_only_calibration(
                rows=[],
                base_calibration=self._base_primary_artifact(),
                label_col="is_single_intent",
                scheme="cv",
                holdout_ratio=0.2,
                cv_folds=5,
                tau_a_precision=0.9,
                tau_b_precision=0.7,
                random_state=42,
                threshold_fallback_policy="error",
                calibration_mode="platt",
                calibration_rows=calibration_rows,
                evaluation_rows=evaluation_rows,
                split_roles={"calibration": {}, "evaluation": {}},
                require_repo_disjoint_eval=False,
            )
        self.assertFalse(artifact["metrics"]["repo_disjoint_eval"])
        self.assertEqual(artifact["metrics"]["repo_overlap_count"], 1)
        self.assertEqual(artifact["metrics"]["repo_overlap_examples"], ["owner/b"])
        self.assertFalse(artifact["metrics"]["protocol_violation"])

    def test_explicit_split_repo_overlap_raises_when_disjoint_required(self) -> None:
        calibration_rows = self._message_only_split_rows(
            repos=["owner/a", "owner/b"],
            labels=["1", "0"],
        )
        evaluation_rows = self._message_only_split_rows(
            repos=["owner/b", "owner/c"],
            labels=["1", "0"],
        )
        with (
            patch.object(
                message_only_calibration.base_fit,
                "apply_threshold_fallback_policy",
                return_value=None,
            ),
            patch.object(
                message_only_calibration.base_fit.miner,
                "derive_threshold_seed_from_distribution",
                return_value=(0.8, 0.6),
            ),
        ):
            with self.assertRaises(ValueError):
                message_only_calibration.fit_message_only_calibration(
                    rows=[],
                    base_calibration=self._base_primary_artifact(),
                    label_col="is_single_intent",
                    scheme="cv",
                    holdout_ratio=0.2,
                    cv_folds=5,
                    tau_a_precision=0.9,
                    tau_b_precision=0.7,
                    random_state=42,
                    threshold_fallback_policy="error",
                    calibration_mode="platt",
                    calibration_rows=calibration_rows,
                    evaluation_rows=evaluation_rows,
                    split_roles={"calibration": {}, "evaluation": {}},
                )

    def test_explicit_split_artifact_records_repo_sets_and_counts(self) -> None:
        calibration_rows = self._message_only_split_rows(
            repos=["owner/a", "owner/b"],
            labels=["1", "0"],
        )
        evaluation_rows = self._message_only_split_rows(
            repos=["owner/c", "owner/d"],
            labels=["1", "0"],
        )
        with (
            patch.object(
                message_only_calibration.base_fit,
                "apply_threshold_fallback_policy",
                return_value=None,
            ),
            patch.object(
                message_only_calibration.base_fit.miner,
                "derive_threshold_seed_from_distribution",
                return_value=(0.8, 0.6),
            ),
        ):
            artifact = message_only_calibration.fit_message_only_calibration(
                rows=[],
                base_calibration=self._base_primary_artifact(),
                label_col="is_single_intent",
                scheme="cv",
                holdout_ratio=0.2,
                cv_folds=5,
                tau_a_precision=0.9,
                tau_b_precision=0.7,
                random_state=42,
                threshold_fallback_policy="error",
                calibration_mode="platt",
                calibration_rows=calibration_rows,
                evaluation_rows=evaluation_rows,
                split_roles={"calibration": {}, "evaluation": {}},
            )
        self.assertEqual(artifact["metrics"]["calibration_train_repo_count"], 2)
        self.assertEqual(artifact["metrics"]["threshold_eval_repo_count"], 2)
        self.assertTrue(artifact["fit_config"]["require_repo_disjoint_eval"])

    def test_resolve_message_only_split_rows_rejects_split_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            calibration_csv = base / "calibration.csv"
            evaluation_csv = base / "evaluation.csv"
            fieldnames = [
                "sha",
                "repo",
                "type",
                "commit_message",
                "git_diff",
                "is_single_intent",
            ]
            row = {
                "sha": "wrong-sha",
                "repo": "owner/repo",
                "type": "fix",
                "commit_message": "fix: wrong row",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "1",
            }
            for path in [calibration_csv, evaluation_csv]:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(row)
            plan_json = base / "annotated_split_plan.json"
            plan_json.write_text(
                json.dumps(
                    {
                        "splits": {
                            "protocol": {"shas": ["protocol-sha"]},
                            "gbdt_train": {"shas": ["train-sha"]},
                            "calibration": {"shas": ["calibration-sha"]},
                            "evaluation": {"shas": ["evaluation-sha"]},
                            "proxy_gap": {"shas": ["proxy-gap-sha"]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "calibration_input": calibration_csv.as_posix(),
                    "evaluation_input": evaluation_csv.as_posix(),
                    "annotated_split_plan_json": plan_json.as_posix(),
                },
            )()
            with self.assertRaises(RuntimeError):
                message_only_calibration.resolve_message_only_split_rows(
                    args, fallback_rows=[]
                )


if __name__ == "__main__":
    unittest.main()
