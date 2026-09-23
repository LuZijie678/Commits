import unittest
from argparse import Namespace
import json
import csv
import tempfile
from pathlib import Path
from unittest.mock import patch

# 导入完整差异校准模块，用于原子性分类器的训练和评估
from src.pipeline import full_diff_calibration as calibration


class WeakLabelProtocolDecircularizationTest(unittest.TestCase):
    def test_resolve_training_label_prefers_adjudicated_label(self) -> None:
        # 测试：当存在裁决标签时，优先使用裁决标签作为训练标签
        # is_single_intent=0, raw_label=0, 但adjudicated_label=1
        label = calibration.resolve_training_label(
            {
                "is_single_intent": "0",
                "raw_label": "0",
                "adjudicated_label": "1",
            },
            label_col="is_single_intent",
        )
        self.assertEqual(label, 1)

    def _parsed_rows(self) -> list[dict]:
        # 构建测试数据：5个不同仓库和类型的提交记录，包含消息和差异特征
        messages = [
            (
                "repo_a",
                "fix",
                "fix(parser): stabilize unicode token path",
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
            (
                "repo_a",
                "feat",
                "feat(api): add parser and logger",
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
            (
                "repo_b",
                "refactor",
                "refactor(core): simplify parser flow",
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
            (
                "repo_b",
                "chore",
                "chore(release): 1.2.3",
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
            (
                "repo_c",
                "docs",
                "docs: refresh parser overview",
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
            ),
        ]
        parsed_rows: list[dict] = []
        for repo, commit_type, message, diff in messages:
            parsed_rows.append(
                {
                    "repo": repo,
                    "type": commit_type,
                    "message_features": calibration.miner.parse_message(message),
                    "diff_features": calibration.miner.parse_diff(diff),
                    "row": {
                        "sha": f"{repo}-{commit_type}",
                        "commit_message": message,
                        "git_diff": diff,
                        "type": commit_type,
                        # chore类型标记为负样本，其他为正样本
                        "is_single_intent": "1" if commit_type != "chore" else "0",
                    },
                }
            )
        return parsed_rows

    def test_derive_weak_label_protocol_does_not_call_atomic_prior(self) -> None:
        # 测试：推导弱标签协议时不应调用atomic_prior，确保解耦
        parsed_rows = self._parsed_rows()
        with patch.object(
            calibration.miner,
            "atomic_prior",
            side_effect=AssertionError("atomic_prior should not be used for weak label protocol derivation"),
        ):
            protocol = calibration.derive_weak_label_protocol(parsed_rows=parsed_rows)
        self.assertEqual(protocol.version, "independent_rule_protocol_v1")
        self.assertGreaterEqual(protocol.positive_subject_action_max, 1)
        self.assertGreaterEqual(protocol.negative_structural_rule_min_fires, 2)

    def test_weak_label_generation_runs_without_atomic_prior(self) -> None:
        # 测试：使用预定义协议生成弱标签时不应调用atomic_prior
        protocol = calibration.WeakLabelProtocol(
            version="independent_rule_protocol_v1",
            positive_file_count_max=0.0,
            positive_module_count_max=0.0,
            positive_patch_size_max=0.0,
            positive_role_count_max=1,
            negative_file_count_min=1.0,
            negative_module_count_min=1.0,
            negative_patch_size_min=1.0,
            negative_role_count_min=3,
            positive_issue_ref_max=1,
            negative_issue_ref_min=2,
            positive_subject_action_max=1,
            negative_subject_action_min=2,
            negative_structural_rule_min_fires=2,
            source="unit_test",
        )
        message_features = calibration.miner.parse_message(
            "fix(parser): stabilize unicode token path"
        )
        diff_features = calibration.miner.parse_diff(
            "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        )
        with patch.object(
            calibration.miner,
            "atomic_prior",
            side_effect=AssertionError("atomic_prior should not be used for weak label generation"),
        ):
            label, kind, report = calibration.weak_label_and_weight(
                message_features=message_features,
                diff_features=diff_features,
                candidate_type="fix",
                protocol=protocol,
                normalized_file_count=0.0,
                normalized_module_count=0.0,
                normalized_patch_size=0.0,
            )
        self.assertEqual(label, 1)  # fix前缀匹配正向规则
        self.assertEqual(kind, "positive")
        self.assertEqual(report["label_name"], "positive")
        self.assertIn("conventional_prefix", report["positive_rules_fired"])

    def test_rule_labeled_examples_produce_auditable_report(self) -> None:
        # 测试：构建规则标签示例时生成可审计的报告
        parsed_rows = self._parsed_rows()
        protocol = calibration.derive_weak_label_protocol(parsed_rows=parsed_rows)
        examples, summary = calibration.build_rule_labeled_examples(
            parsed_rows=parsed_rows,
            protocol=protocol,
        )
        self.assertEqual(len(examples), len(parsed_rows))
        self.assertEqual(summary["protocol_version"], "independent_rule_protocol_v1")
        self.assertIn("positive_rule_counts", summary)
        self.assertIn("negative_rule_counts", summary)
        self.assertIn("label_counts", summary)
        self.assertTrue(any(example["label_name"] == "positive" for example in examples))
        self.assertTrue(any(example["label_name"] == "negative" for example in examples))

    def test_weak_label_protocol_supports_abstain(self) -> None:
        # 测试：当弱标签协议规则都不触发时，支持弃权(abstain)
        protocol = calibration.WeakLabelProtocol(
            version="independent_rule_protocol_v1",
            positive_file_count_max=-0.5,
            positive_module_count_max=-0.5,
            positive_patch_size_max=-0.5,
            positive_role_count_max=0,
            negative_file_count_min=10.0,
            negative_module_count_min=10.0,
            negative_patch_size_min=10.0,
            negative_role_count_min=10,
            positive_issue_ref_max=1,
            negative_issue_ref_min=3,
            positive_subject_action_max=1,
            negative_subject_action_min=3,
            negative_structural_rule_min_fires=3,
            source="unit_test",
        )
        # docs类型的提交不匹配任何规则，应返回弃权
        label, kind, report = calibration.weak_label_and_weight(
            message_features=calibration.miner.parse_message("docs: refresh overview"),
            diff_features=calibration.miner.parse_diff(
                "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
            ),
            candidate_type="docs",
            protocol=protocol,
            normalized_file_count=0.0,
            normalized_module_count=0.0,
            normalized_patch_size=0.0,
        )
        self.assertIsNone(label)
        self.assertEqual(kind, "abstain")
        self.assertEqual(report["label_name"], "abstain")

    def test_run_gbdt_isotonic_mode_uses_rule_labeled_targets(self) -> None:
        # 测试：GBDT+保序回归模式下使用规则标签作为目标进行训练
        # 4个正样本（fix类型）和4个负样本（feat类型）
        rows = []
        for idx in range(4):
            rows.append(
                {
                    "sha": f"p{idx}",
                    "type": "fix",
                    "commit_message": f"fix(parser): stabilize path {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "1",
                }
            )
        for idx in range(4):
            rows.append(
                {
                    "sha": f"n{idx}",
                    "type": "feat",
                    "commit_message": f"feat(api): add parser and logger {idx}",
                    "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                    "is_single_intent": "0",
                }
            )

        # 模拟的梯度提升树分类器，用于测试
        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.fit_y = None
                self.predict_call_count = 0

            def fit(self, X, y, sample_weight=None):
                self.fit_y = list(y)

            def predict_proba(self, X):
                if len(X) == 1:
                    self.predict_call_count += 1
                    positive_prob = 0.65 if (self.predict_call_count % 2 == 0) else 0.55
                    return [[1.0 - positive_prob, positive_prob]]
                return [
                    [0.35 if (idx % 2 == 0) else 0.45, 0.65 if (idx % 2 == 0) else 0.55]
                    for idx, _ in enumerate(X)
                ]

        fake_model = FakeModel()

        class FakeIsotonic:
            X_thresholds_ = [0.1, 0.9]
            y_thresholds_ = [0.2, 0.8]

            def fit(self, X, y):
                return None

            def predict(self, values):
                return list(values)

        def fake_build_rule_labeled_examples(
            *, parsed_rows, protocol, repo_stats=None, global_stats=None
        ):
            examples = []
            labels = [1, 0, 1, 0]
            for idx, item in enumerate(parsed_rows[:4]):
                examples.append(
                    {
                        "row": item["row"],
                        "label": labels[idx],
                        "label_name": "positive" if labels[idx] == 1 else "negative",
                        "decision_kind": "positive"
                        if labels[idx] == 1
                        else "negative_explicit",
                        "sample_weight": 1.0,
                        "positive_rules_fired": ["stub_positive"]
                        if labels[idx] == 1
                        else [],
                        "negative_rules_fired": ["stub_negative"]
                        if labels[idx] == 0
                        else [],
                        "rule_report": {
                            "label_name": "positive" if labels[idx] == 1 else "negative"
                        },
                        "feature_vector": [0.1, 0.2, 0.3],
                    }
                )
            return examples, {
                "protocol_version": "independent_rule_protocol_v1",
                "label_counts": {"positive": 2, "negative": 2, "abstain": 0},
                "decision_kind_counts": {"positive": 2, "negative_explicit": 2},
                "positive_rule_counts": {"stub_positive": 2},
                "negative_rule_counts": {"stub_negative": 2},
            }

        args = Namespace(
            input="annotated.csv",
            label_col="is_single_intent",
            tau_a_precision=0.9,
            tau_b_precision=0.7,
            n_estimators=2,
            max_depth=2,
            learning_rate=0.1,
            random_state=42,
            hard_negative_upsample=0.0,
            min_labeled=2,
            labeled_calibration_scheme="holdout",
            labeled_holdout_ratio=0.5,
            labeled_cv_folds=2,
            threshold_fallback_policy="error",
        )
        # 定义GBDT超参数和其他配置，用于完整差异校准训练

        with (
            patch.object(
                calibration.miner,
                "build_atomic_feature_map",
                return_value={"f0": 0.1, "f1": 0.2, "f2": 0.3},
            ),
            patch.object(calibration.miner, "ATOMIC_FEATURE_ORDER", ["f0", "f1", "f2"]),
            patch.object(calibration, "MIN_WEAK_POOL_SIZE", 1),
            patch.object(calibration, "MIN_WEAK_CLASS_COUNT", 1),
            patch.object(
                calibration,
                "build_rule_labeled_examples",
                side_effect=fake_build_rule_labeled_examples,
            ),
            patch.object(
                calibration,
                "derive_gbdt_hyperparams",
                return_value={
                    "n_estimators": 2,
                    "max_depth": 2,
                    "learning_rate": 0.1,
                    "n_estimators_source": "test",
                    "max_depth_source": "test",
                    "learning_rate_source": "test",
                },
            ),
            patch.object(
                calibration, "GradientBoostingClassifier", return_value=fake_model
            ),
            patch.object(
                calibration.miner,
                "estimate_model_epistemic_uncertainty",
                return_value=0.0,
            ),
            patch.object(
                calibration,
                "derive_epistemic_reference",
                return_value={"center": 0.0, "scale": 1.0},
            ),
            patch.object(
                calibration,
                "repo_aware_holdout_indices",
                return_value=([0, 4, 1, 5], [2, 6, 3, 7]),
            ),
            patch.object(
                calibration,
                "subset",
                side_effect=lambda values, indices: [values[i] for i in indices],
            ),
            patch.object(
                calibration,
                "subset_int",
                side_effect=lambda values, indices: [values[i] for i in indices],
            ),
            patch.object(
                calibration, "IsotonicRegression", return_value=FakeIsotonic()
            ),
            patch.object(
                calibration,
                "select_threshold_by_precision_report",
                side_effect=[
                    calibration.ThresholdSelectionReport(0.9, 0.95, "mock", False, 4),
                    calibration.ThresholdSelectionReport(0.7, 0.80, "mock", False, 4),
                    calibration.ThresholdSelectionReport(0.88, 0.93, "mock", False, 4),
                    calibration.ThresholdSelectionReport(0.68, 0.79, "mock", False, 4),
                ],
            ),
            patch.object(
                calibration, "apply_threshold_fallback_policy", return_value=None
            ),
            patch.object(calibration.pickle, "dumps", return_value=b"fake-model"),
        ):
            artifact = calibration.run_gbdt_isotonic_mode(args, rows)

        self.assertEqual(fake_model.fit_y, [1, 0, 1, 0])
        self.assertEqual(
            artifact["fit_config"]["weak_label_source"],
            "independent_rule_protocol_v1",
        )
        self.assertEqual(
            artifact["fit_config"]["weak_label_protocol_version"],
            "independent_rule_protocol_v1",
        )
        self.assertIn("label_usage_summary", artifact["fit_config"])

    def test_resolve_atomic_calibration_split_rows_rejects_split_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            protocol_csv = base / "protocol.csv"
            train_csv = base / "gbdt_train.csv"
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
            for path in [protocol_csv, train_csv, calibration_csv, evaluation_csv]:
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
            args = Namespace(
                protocol_input=protocol_csv.as_posix(),
                gbdt_train_input=train_csv.as_posix(),
                calibration_input=calibration_csv.as_posix(),
                evaluation_input=evaluation_csv.as_posix(),
                annotated_split_plan_json=plan_json.as_posix(),
            )
            with self.assertRaises(RuntimeError):
                calibration.resolve_atomic_calibration_split_rows(
                    args, fallback_rows=[]
                )

    def test_compute_threshold_coverage_metrics_reports_positive_recall(self) -> None:
        # 测试：计算阈值覆盖指标，报告每个tier的正例召回率
        metrics = calibration.compute_threshold_coverage_metrics(
            probs=[0.95, 0.82, 0.51, 0.21],
            labels=[1, 1, 0, 0],
            tau_a=0.9,
            tau_b=0.5,
        )
        self.assertEqual(metrics["positive_support"], 2)
        self.assertAlmostEqual(metrics["tier_a_positive_recall"], 0.5)
        self.assertAlmostEqual(metrics["tier_b_or_higher_positive_recall"], 1.0)

    def test_compare_rule_only_vs_model_metrics_exposes_rule_recall_gap(self) -> None:
    # 测试：对比纯规则模型和GBDT模型的性能差距，验证模型召回率优势
        metrics = calibration.compare_rule_only_vs_model_metrics(
            rule_labels=[1, None, 0, None],
            model_probs=[0.92, 0.91, 0.20, 0.12],
            gold_labels=[1, 1, 0, 0],
            tau_a=0.9,
        )
        self.assertIn("rule_positive_precision", metrics)
        self.assertIn("model_positive_recall", metrics)
        self.assertLess(
            metrics["rule_positive_recall"], metrics["model_positive_recall"]
        )

    def test_derive_feature_reduced_order_removes_rule_adjacent_features(self) -> None:
        reduced = calibration.derive_feature_reduced_order(
            [
                "file_count",
                "module_count",
                "semantic_cluster_tightness",
                "identifier_focus",
                "has_single_prefix",
                "repo_norm_module_span",
            ]
        )
        self.assertEqual(reduced, ["semantic_cluster_tightness", "identifier_focus"])

    def test_build_reliability_report_contains_ece(self) -> None:
        report = calibration.build_reliability_report(
            probs=[0.9, 0.8, 0.3, 0.2],
            labels=[1, 1, 0, 0],
            bins=4,
        )
        self.assertIn("ece", report)
        self.assertIn("mce", report)
        self.assertIn("bins", report)
        self.assertGreaterEqual(report["ece"], 0.0)


if __name__ == "__main__":
    unittest.main()
