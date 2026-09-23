import csv
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

# 导入各种实验和分析模块用于测试
from src.experiments import message_only_dataset as expanded_dataset
from src.analysis import diagnostics as analysis_diagnostics
from src.analysis import main_results as analysis_main_results
from src.analysis import proxy_gap_report
from src.analysis import proxy_gap_schema
from src.labeling import audit_dataset as message_only_audit
from src.pipeline import enrichment as enrich
from src.pipeline import full_diff_calibration as calibration
from src.labeling import message_only_audit_labeling as audit_labeler
from src.pipeline import atomic_mining as miner
from src.pipeline import prefilter as prefilter
from src.analysis import proxy_gap
from src.pipeline import run_step1 as runner
from src.pipeline import selection as selector
import src.data_splitting.annotated_split_protocol as split_protocol
import src.param_derivation.threshold_selection as threshold_selection
import src.param_derivation.weight_calibration as weight_calibration
from src.pipeline import validation as validator
from unittest.mock import patch


class StrictPipelineUtilsTest(unittest.TestCase):
    def test_run_step1_parse_args_defaults_use_datasets_layout(self) -> None:
        argv_backup = sys.argv[:]
        try:
            sys.argv = ["prog"]
            args = runner.parse_args()
        finally:
            sys.argv = argv_backup
        self.assertEqual(
            args.allcommits,
            "../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
        )
        self.assertEqual(
            args.annotated,
            "../../datasets/step1/canonical/annotated_dataset.csv",
        )
        self.assertEqual(
            args.repo_list,
            "../../datasets/step1/runtime_support/resolved_metadata.csv",
        )
        self.assertEqual(
            args.annotation_overlap_a_csv,
            "../../datasets/step1/review/annotated_overlap_annotator_a.csv",
        )
        self.assertEqual(
            args.annotation_overlap_b_csv,
            "../../datasets/step1/review/annotated_overlap_annotator_b.csv",
        )

    def test_clamp_audit_size(self) -> None:
        # 测试：审计规模限制在[300, 500]范围内
        # 100 < 300 应返回300，300在范围内，500在范围内，600 > 500应返回500
        self.assertEqual(runner.clamp_audit_size(100), 300)
        self.assertEqual(runner.clamp_audit_size(300), 300)
        self.assertEqual(runner.clamp_audit_size(500), 500)
        self.assertEqual(runner.clamp_audit_size(600), 500)

    def test_derive_per_type_auto_mode(self) -> None:
        # 测试：自动推导每类型采样数
        # audit_target=300, effective_yield=0.5 => required=600 => per_type=150（四类硬均衡）
        per_type = runner.derive_per_type(
            per_type_arg=0,
            audit_target=300,
            observed_tier_a_ratio=0.5,
        )
        self.assertEqual(per_type, 150)

    def test_derive_min_resolved_ratio_constraint_mode(self) -> None:
        # 测试：从审计覆盖率约束推导最小解析比例
        # audit_target=300, expected_total=500 => ratio=300/500=0.6
        ratio, source = runner.derive_min_resolved_ratio(
            min_resolved_ratio_arg=0.0,
            audit_target=300,
            expected_total=500,
        )
        self.assertAlmostEqual(ratio, 0.6)
        self.assertEqual(source, "constraint_audit_coverage")

    def test_subject_similarity(self) -> None:
        # 测试：提交主题的相似度计算
        # 相似主题应有>0.5的相似度，不相似主题应返回0
        self.assertGreater(
            enrich.subject_similarity(
                "fix(parser): improve unicode token handling",
                "fix: improve unicode parser token handling",
            ),
            0.5,
        )
        self.assertEqual(
            enrich.subject_similarity(
                "docs: update readme", "perf: optimize render loop"
            ),
            0.0,
        )
        self.assertEqual(per_type, 120)

    def test_derive_min_resolved_ratio_constraint_mode(self) -> None:
        ratio, source = runner.derive_min_resolved_ratio(
            min_resolved_ratio_arg=0.0,
            audit_target=300,
            expected_total=500,
        )
        self.assertAlmostEqual(ratio, 0.6)
        self.assertEqual(source, "constraint_audit_coverage")

    def test_subject_similarity(self) -> None:
        self.assertGreater(
            enrich.subject_similarity(
                "fix(parser): improve unicode token handling",
                "fix: improve unicode parser token handling",
            ),
            0.5,
        )
        self.assertEqual(
            enrich.subject_similarity(
                "docs: update readme", "perf: optimize render loop"
            ),
            0.0,
        )

    def test_audit_completion_evaluator(self) -> None:
        # 测试：审计完成评估器，检查所有行都有有效标签和置信度
        rows = [
            {"audit_is_single_intent": "1", "audit_confidence": "0.9"},
            {"audit_is_single_intent": "0", "audit_confidence": "0.2"},
        ]
        stats = validator.evaluate_audit_completion(rows)
        self.assertTrue(stats["is_complete"])
        self.assertEqual(stats["valid_label_count"], 2)
        self.assertEqual(stats["valid_confidence_count"], 2)

    def test_audit_completion_incomplete(self) -> None:
        # 测试：空字符串表示未完成，标记为不完整
        rows = [
            {"audit_is_single_intent": "1", "audit_confidence": "0.9"},
            {"audit_is_single_intent": "", "audit_confidence": ""},
        ]
        stats = validator.evaluate_audit_completion(rows)
        self.assertFalse(stats["is_complete"])
        self.assertEqual(stats["valid_label_count"], 1)
        self.assertEqual(stats["valid_confidence_count"], 1)

    def test_audit_sample_sha_alignment(self) -> None:
        # 测试：审计样本SHA对齐检查，验证顺序一致
        expected_rows = [{"sha": "a"}, {"sha": "b"}]
        labeled_rows = [{"sha": "a"}, {"sha": "b"}]
        stats = validator.evaluate_audit_sample_alignment(expected_rows, labeled_rows)
        self.assertTrue(stats["is_aligned"])
        self.assertEqual(stats["expected_rows"], 2)
        self.assertEqual(stats["labeled_rows"], 2)

    def test_audit_sample_sha_alignment_detects_order_mismatch(self) -> None:
        # 测试：检测SHA顺序不匹配，matching_sha_prefix应为0
        expected_rows = [{"sha": "a"}, {"sha": "b"}]
        labeled_rows = [{"sha": "b"}, {"sha": "a"}]
        stats = validator.evaluate_audit_sample_alignment(expected_rows, labeled_rows)
        self.assertFalse(stats["is_aligned"])
        self.assertEqual(stats["matching_sha_prefix"], 0)

    def test_random_audit_sampling_is_reproducible(self) -> None:
        # 测试：随机审计采样使用相同种子应产生相同结果
        rows = [{"sha": f"s{i}"} for i in range(20)]
        sampled_a = validator.sample_random(rows, sample_size=8, seed=13)
        sampled_b = validator.sample_random(rows, sample_size=8, seed=13)
        self.assertEqual([item["sha"] for item in sampled_a], [item["sha"] for item in sampled_b])
        self.assertEqual(len(sampled_a), 8)

    def test_threshold_selection_report_fallback_flag(self) -> None:
        # 测试：精度不满足时使用回退值，标记used_fallback=True
        report = threshold_selection.select_threshold_by_precision_report(
            probs=[0.9, 0.9, 0.8, 0.8],
            labels=[1, 0, 1, 0],
            target_precision=0.8,
            fallback=0.8,
        )
        self.assertTrue(report.used_fallback)
        self.assertEqual(report.source, "fallback_target_precision_unmet")

    def test_stratified_selector_is_seed_reproducible(self) -> None:
    # 测试：分层选择器使用相同种子应产生相同结果
        rows = []
        for commit_type in selector.SUBSTANTIVE_TYPES:
            for idx in range(20):
                rows.append({"type": commit_type, "subject": f"{commit_type}: x{idx}", "sha": f"{commit_type}-{idx}"})
        first = selector.select_rows(rows, per_type=5, exclude_breaking=False, offset_per_type=0, seed=17)
        second = selector.select_rows(rows, per_type=5, exclude_breaking=False, offset_per_type=0, seed=17)
        self.assertEqual([item["sha"] for item in first], [item["sha"] for item in second])
        self.assertEqual(len(first), 5 * len(selector.HARD_BALANCE_TYPES))

    def test_stratified_selector_can_prioritize_high_tier(self) -> None:
    # 测试：prefer_high_tier参数优先选择高层级(B>C)的记录
        rows = []
        for idx in range(5):
            rows.append(
                {
                    "type": "fix",
                    "subject": f"fix: b{idx}",
                    "sha": f"fix-b-{idx}",
                    "prefilter_tier": "B",
                }
            )
        for idx in range(5):
            rows.append(
                {
                    "type": "fix",
                    "subject": f"fix: c{idx}",
                    "sha": f"fix-c-{idx}",
                    "prefilter_tier": "C",
                }
            )
        for commit_type in ["feat", "refactor", "test", "perf"]:
            for idx in range(5):
                rows.append(
                    {
                        "type": commit_type,
                        "subject": f"{commit_type}: c{idx}",
                        "sha": f"{commit_type}-{idx}",
                        "prefilter_tier": "C",
                    }
                )
        selected = selector.select_rows(
            rows,
            per_type=3,
            exclude_breaking=False,
            offset_per_type=0,
            seed=17,
            prefer_high_tier=True,
        )
        fix_rows = [row for row in selected if row["type"] == "fix"]
        self.assertEqual(len(fix_rows), 3)
        self.assertTrue(all(row["prefilter_tier"] == "B" for row in fix_rows))

    def test_combined_selection_stage_defaults_to_batch_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            input_csv = base / "prefilter_allcommits.csv"
            output_csv = base / "prefilter_stratified_batch.csv"
            fieldnames = [
                "sha",
                "type",
                "commit_message",
                "resolution_status",
                "resolved_repo",
            ]
            rows = []
            for commit_type in selector.SUBSTANTIVE_TYPES:
                for idx in range(2):
                    rows.append(
                        {
                            "sha": f"{commit_type}-{idx}",
                            "type": commit_type,
                            "commit_message": f"{commit_type}: subject {idx}\n\nbody {idx}",
                            "resolution_status": "prefilter_only",
                            "resolved_repo": "",
                        }
                    )
            rows.append(
                {
                    "sha": "docs-0",
                    "type": "docs",
                    "commit_message": "docs: ignored",
                    "resolution_status": "prefilter_only",
                    "resolved_repo": "",
                }
            )
            with input_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            metrics = selector.run_selection_stage(
                input_path=input_csv,
                output_path=output_csv,
                per_type=1,
                audit_target=300,
                seed=17,
                calibration_json="",
                min_prefilter_prob=0.0,
                dump_debug_artifacts=False,
                compute_message_only_prior=False,
            )

            self.assertEqual(metrics["selected"], len(selector.HARD_BALANCE_TYPES))
            self.assertEqual(metrics["all_candidates"], 10)
            self.assertTrue(output_csv.exists())
            with output_csv.open("r", encoding="utf-8", newline="") as handle:
                selected_rows = list(csv.DictReader(handle))
            self.assertEqual(len(selected_rows), len(selector.HARD_BALANCE_TYPES))
            self.assertTrue(
                all(row["subject"].startswith(row["type"]) for row in selected_rows)
            )
            self.assertFalse((base / "all_prefilter_candidates.csv").exists())
            self.assertFalse((base / "prefilter_top_candidates.csv").exists())

    def test_combined_selection_stage_can_dump_debug_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            input_csv = base / "prefilter_allcommits.csv"
            output_csv = base / "prefilter_stratified_batch.csv"
            metrics_json = base / "selection_metrics.json"
            fieldnames = [
                "sha",
                "type",
                "commit_message",
                "resolution_status",
                "resolved_repo",
            ]
            rows = []
            for commit_type in selector.SUBSTANTIVE_TYPES:
                for idx in range(3):
                    rows.append(
                        {
                            "sha": f"{commit_type}-{idx}",
                            "type": commit_type,
                            "commit_message": f"{commit_type}: subject {idx}",
                            "resolution_status": "prefilter_only",
                            "resolved_repo": "",
                        }
                    )
            with input_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            metrics = selector.run_selection_stage(
                input_path=input_csv,
                output_path=output_csv,
                per_type=1,
                audit_target=300,
                seed=17,
                calibration_json="",
                min_prefilter_prob=0.0,
                dump_debug_artifacts=True,
                debug_top_count=4,
                metrics_json_path=metrics_json,
                compute_message_only_prior=False,
            )

            self.assertTrue(metrics["debug_artifacts_written"])
            self.assertTrue(metrics_json.exists())
            persisted = json.loads(metrics_json.read_text(encoding="utf-8"))
            self.assertEqual(persisted["all_candidates"], 15)
            all_csv = base / "all_prefilter_candidates.csv"
            top_csv = base / "prefilter_top_candidates.csv"
            self.assertTrue(all_csv.exists())
            self.assertTrue(top_csv.exists())
            with all_csv.open("r", encoding="utf-8", newline="") as handle:
                all_rows = list(csv.DictReader(handle))
            with top_csv.open("r", encoding="utf-8", newline="") as handle:
                top_rows = list(csv.DictReader(handle))
            self.assertEqual(len(all_rows), 15)
            self.assertEqual(len(top_rows), 4)

    def test_load_selection_metrics_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "selection_metrics.json"
            payload = {
                "all_candidates": 52424,
                "selected": 1050,
                "per_type": 210,
                "substantive_type_counts": {"fix": 100},
                "observed_tier_a_ratio": 0.1,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            metrics = runner.load_selection_metrics(path)
        self.assertEqual(metrics["all_candidates"], 52424)
        self.assertEqual(metrics["per_type"], 210)

    def test_write_manifest_preserves_selection_artifact_keys_for_early_stop(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run_manifest.json"
            payload = {
                "run_root": "/tmp/run",
                "stopped_after": "select_batch",
                "derived": {"per_type": 210},
                "artifacts": {
                    "selection_dir": "/tmp/run/selection",
                    "selection_batch_csv": "/tmp/run/selection/selection_batch.csv",
                },
                "stage_checks": [
                    {"stage": "select_batch", "metrics": {"selected": 1050}}
                ],
                "args": {},
            }
            runner.write_manifest(path, payload)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["artifacts"]["selection_dir"], "/tmp/run/selection")
            self.assertEqual(
                loaded["artifacts"]["selection_batch_csv"],
                "/tmp/run/selection/selection_batch.csv",
            )

    def test_build_annotated_split_constraints_returns_all_roles(self) -> None:
        args = Namespace(
            seed=31,
            protocol_min_total=20,
            protocol_min_positive=10,
            protocol_min_negative=10,
            protocol_min_repos=3,
            gbdt_train_min_total=40,
            gbdt_train_min_positive=20,
            gbdt_train_min_negative=20,
            gbdt_train_min_repos=4,
            calibration_min_total=20,
            calibration_min_positive=10,
            calibration_min_negative=10,
            calibration_min_repos=3,
            evaluation_min_total=20,
            evaluation_min_positive=10,
            evaluation_min_negative=10,
            evaluation_min_repos=3,
            proxy_gap_min_total=20,
            proxy_gap_min_positive=10,
            proxy_gap_min_negative=10,
            proxy_gap_min_repos=3,
        )
        constraints = runner.build_annotated_split_constraints(args)
        self.assertEqual(
            set(constraints["min_total_by_split"].keys()),
            set(split_protocol.ANNOTATED_SPLIT_ORDER),
        )
        self.assertEqual(constraints["min_total_by_split"]["protocol"], 20)
        self.assertEqual(constraints["min_repo_by_split"]["proxy_gap"], 3)

    def test_runner_persisted_split_artifacts_are_recorded_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "run_root": "/tmp/run",
                "artifacts": {
                    "annotation_agreement_json": "/tmp/run/annotation_agreement.json",
                    "annotation_agreement_md": "/tmp/run/annotation_agreement.md",
                    "annotated_split_plan_json": "/tmp/run/annotated_splits/annotated_split_plan.json",
                    "annotated_split_csvs": {
                        "protocol": "/tmp/run/annotated_splits/protocol.csv",
                        "gbdt_train": "/tmp/run/annotated_splits/gbdt_train.csv",
                    },
                    "annotated_split_sha_csvs": {
                        "protocol": "/tmp/run/annotated_splits/protocol_shas.csv",
                        "gbdt_train": "/tmp/run/annotated_splits/gbdt_train_shas.csv",
                    },
                    "calibration_diagnostics_json": "/tmp/run/calibration/calibration_diagnostics.json",
                    "calibration_diagnostics_md": "/tmp/run/calibration/calibration_diagnostics.md",
                    "main_results_json": "/tmp/run/main_results/main_results.json",
                    "main_results_md": "/tmp/run/main_results/main_results.md",
                },
                "stage_checks": [],
                "args": {},
            }
            path = Path(tmpdir) / "run_manifest.json"
            runner.write_manifest(path, payload)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("annotation_agreement_json", loaded["artifacts"])
            self.assertIn("annotated_split_plan_json", loaded["artifacts"])
            self.assertIn("protocol", loaded["artifacts"]["annotated_split_csvs"])
            self.assertIn("calibration_diagnostics_json", loaded["artifacts"])
            self.assertIn("main_results_json", loaded["artifacts"])

    def test_build_annotation_agreement_payload_unavailable_when_inputs_missing(
        self,
    ) -> None:
        payload = runner.build_annotation_agreement_payload(
            annotator_a_rows=[],
            annotator_b_rows=[],
        )
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["shared_sha_count"], 0)

    def test_require_annotation_agreement_available_raises_when_missing(self) -> None:
        with self.assertRaises(RuntimeError):
            runner.require_annotation_agreement_available(
                {
                    "status": "unavailable",
                    "reason": "annotator overlap csv files are missing or empty",
                }
            )

    def test_build_annotation_agreement_payload_reports_kappa(self) -> None:
        payload = runner.build_annotation_agreement_payload(
            annotator_a_rows=[
                {"sha": "a1", "label": "1", "adjudicated_label": "1"},
                {"sha": "a2", "label": "0"},
            ],
            annotator_b_rows=[
                {"sha": "a1", "label": "1", "adjudicated_label": "1"},
                {"sha": "a2", "label": "1"},
            ],
        )
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["shared_sha_count"], 2)
        self.assertIn("cohen_kappa", payload)
        self.assertIn("adjudication_coverage", payload)

    def test_build_calibration_diagnostics_payload_includes_primary_and_proxy_sections(
        self,
    ) -> None:
        primary = {
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "fit_config": {
                "weak_label_source": "independent_rule_protocol_v1",
                "annotated_split_roles": {"protocol": {"source_csv": "protocol.csv"}},
            },
            "metrics": {
                "coverage_metrics": {"tier_a_positive_recall": 0.4},
                "reliability_report": {"ece": 0.07},
                "rule_only_vs_model": {
                    "rule_positive_recall": 0.3,
                    "model_positive_recall": 0.6,
                },
                "raw_brier_eval": 0.11,
                "calibrated_brier_eval": 0.08,
                "raw_logloss_eval": 0.31,
                "calibrated_logloss_eval": 0.24,
            },
            "thresholds": {"tau_a": 0.9, "tau_b": 0.7, "source": "constraint"},
        }
        proxy = {
            "artifact_version": "step1_message_only_platt_v1",
            "fit_config": {
                "annotated_split_roles": {
                    "calibration": {"source_csv": "calibration.csv"}
                }
            },
            "metrics": {
                "raw_brier_eval": 0.19,
                "calibrated_brier_eval": 0.14,
                "raw_logloss_eval": 0.52,
                "calibrated_logloss_eval": 0.41,
            },
            "thresholds": {"tau_a": 0.95, "tau_b": 0.85, "source": "constraint"},
        }
        payload = analysis_diagnostics.build_calibration_diagnostics_payload(
            primary_artifact=primary,
            proxy_artifact=proxy,
            annotation_agreement={
                "status": "available",
                "shared_sha_count": 18,
                "raw_agreement": 0.83,
                "cohen_kappa": 0.66,
                "adjudication_coverage": 0.5,
                "confusion_summary": {"1->1": 8, "0->0": 7, "1->0": 2, "0->1": 1},
            },
        )
        self.assertIn("primary_model", payload)
        self.assertIn("proxy_model", payload)
        self.assertIn("annotation_agreement_summary", payload)
        self.assertIn("appendix_claims", payload)
        self.assertIn("side_by_side_delta_summary", payload)
        self.assertIn("coverage_metrics", payload["primary_model"])
        self.assertIn("reliability_report", payload["primary_model"])
        self.assertIn("rule_only_vs_model", payload["primary_model"])
        self.assertIn(
            "brier_delta_primary_minus_proxy", payload["side_by_side_delta_summary"]
        )
        self.assertEqual(payload["annotation_agreement_summary"]["status"], "available")

    def test_write_calibration_diagnostics_persists_json_and_markdown(self) -> None:
        payload = {
            "primary_model": {
                "artifact_version": "a",
                "coverage_metrics": {
                    "tier_a_positive_recall": 0.5,
                    "tier_b_or_higher_positive_recall": 0.8,
                    "tier_a_predicted_count": 12,
                    "tier_b_or_higher_predicted_count": 21,
                },
                "rule_only_vs_model": {
                    "rule_positive_recall": 0.3,
                    "model_positive_recall": 0.6,
                },
                "reliability_report": {
                    "ece": 0.07,
                    "mce": 0.11,
                    "bins": [
                        {
                            "bin_index": 0,
                            "lower": 0.0,
                            "upper": 0.5,
                            "count": 3,
                            "avg_confidence": 0.2,
                            "empirical_accuracy": 0.0,
                            "absolute_gap": 0.2,
                        },
                        {
                            "bin_index": 1,
                            "lower": 0.5,
                            "upper": 1.0,
                            "count": 2,
                            "avg_confidence": 0.8,
                            "empirical_accuracy": 1.0,
                            "absolute_gap": 0.2,
                        },
                    ],
                },
            },
            "proxy_model": {"artifact_version": "b"},
            "annotation_agreement_summary": {
                "status": "available",
                "shared_sha_count": 18,
                "raw_agreement": 0.83,
                "cohen_kappa": 0.66,
                "adjudication_coverage": 0.5,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = analysis_diagnostics.write_calibration_diagnostics(
                output_dir=Path(tmpdir),
                payload=payload,
            )
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["markdown"]).exists())
            content = Path(paths["markdown"]).read_text(encoding="utf-8")
            self.assertIn("Per-threshold Coverage", content)
            self.assertIn("Rule-only vs Model", content)
            self.assertIn("ECE Bin Table", content)
            self.assertIn("Annotation Agreement", content)

    def test_build_main_results_payload_includes_rule_only_and_model_groups(
        self,
    ) -> None:
        primary = {
            "artifact_version": "step1_atomic_gbdt_isotonic_v1",
            "metrics": {
                "calibrated_brier_eval": 0.08,
                "calibrated_logloss_eval": 0.24,
                "coverage_metrics": {"positive_support": 40},
                "reliability_report": {"ece": 0.07, "mce": 0.11},
                "rule_only_vs_model": {
                    "rule_positive_count": 12,
                    "model_positive_count": 18,
                    "gold_positive_count": 40,
                    "rule_positive_precision": 0.92,
                    "rule_positive_recall": 0.275,
                    "model_positive_precision": 0.94,
                    "model_positive_recall": 0.425,
                    "rule_abstain_rate": 0.5,
                },
                "feature_reduced_model_ablation": {
                    "removed_features": ["file_count", "has_single_prefix"],
                    "retained_feature_count": 8,
                    "calibrated_brier_eval": 0.11,
                    "calibrated_logloss_eval": 0.29,
                    "reliability_report": {"ece": 0.09, "mce": 0.13},
                    "rule_only_vs_model": {
                        "model_positive_count": 15,
                        "gold_positive_count": 40,
                        "model_positive_precision": 0.93,
                        "model_positive_recall": 0.35,
                    },
                },
            },
        }
        validate_report = {
            "tier_a": {"precision": 0.95, "sample_count": 300},
            "tier_b": {"precision": 0.71, "sample_count": 120},
        }
        payload = analysis_main_results.build_main_results_payload(
            primary_artifact=primary,
            validate_precision_report=validate_report,
        )
        self.assertIn("rule_model_comparison", payload)
        self.assertIn("rule_only", payload["rule_model_comparison"])
        self.assertIn("model_on_rule_labels", payload["rule_model_comparison"])
        self.assertIn("feature_reduced_model", payload["rule_model_comparison"])
        self.assertIn("gain_summary", payload["rule_model_comparison"])
        self.assertIn("independent_audit_precision", payload)

    def test_build_main_results_payload_requires_rule_model_metrics(self) -> None:
        with self.assertRaises(ValueError):
            analysis_main_results.build_main_results_payload(
                primary_artifact={"metrics": {}},
                validate_precision_report={},
            )

    def test_write_main_results_persists_rule_model_comparison_markdown(self) -> None:
        payload = {
            "rule_model_comparison": {
                "rule_only": {
                    "tier_a_precision": 0.92,
                    "tier_a_recall": 0.27,
                    "tier_a_yield": 12,
                    "brier": None,
                    "ece": None,
                },
                "model_on_rule_labels": {
                    "tier_a_precision": 0.94,
                    "tier_a_recall": 0.42,
                    "tier_a_yield": 18,
                    "brier": 0.08,
                    "ece": 0.07,
                },
                "feature_reduced_model": {
                    "tier_a_precision": 0.93,
                    "tier_a_recall": 0.35,
                    "tier_a_yield": 15,
                    "brier": 0.11,
                    "ece": 0.09,
                },
                "gain_summary": {
                    "tier_a_precision_gain_model_minus_rule": 0.02,
                    "tier_a_recall_gain_model_minus_rule": 0.15,
                    "tier_a_yield_gain_model_minus_rule": 6,
                    "tier_a_recall_delta_full_minus_reduced": 0.07,
                },
            },
            "independent_audit_precision": {"tier_a_precision": 0.95},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = analysis_main_results.write_main_results(
                output_dir=Path(tmpdir),
                payload=payload,
            )
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["markdown"]).exists())
            content = Path(paths["markdown"]).read_text(encoding="utf-8")
            self.assertIn("Rule-only vs Model", content)
            self.assertIn("Feature-reduced Model", content)
            self.assertIn("Gain Summary", content)

    def test_check_calibration_rejects_message_only_repo_overlap_violation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "message_only_calibration.json"
            payload = {
                "artifact_version": "step1_message_only_platt_v1",
                "model_mode": "message_only",
                "model_role": "proxy",
                "signal_context": {"weights": {"subject_len": 1.0}},
                "message_protocol": {"subject_len_min": 0},
                "scope_protocol": {"file_scope_small_max": 0},
                "type_protocol": {"values": {}},
                "epistemic_reference": {"center": 0.0, "scale": 1.0},
                "thresholds": {
                    "tau_a": 0.9,
                    "tau_b": 0.7,
                    "source": "constraint",
                    "selection_reports": {
                        "tau_a": {"used_fallback": False},
                        "tau_b": {"used_fallback": False},
                    },
                },
                "metrics": {
                    "repo_disjoint_eval": False,
                    "protocol_violation": True,
                },
                "fit_config": {"mode": "message_only_platt"},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                runner.check_calibration(
                    path,
                    strict=True,
                    expected_artifact="message_only",
                )

    def test_build_enrich_command_uses_dual_calibration_paths(self) -> None:
        cmd = runner.build_enrich_command(
            python_executable="python",
            candidates_csv=Path("/tmp/selection/selection_batch.csv"),
            repo_list="/tmp/repos.csv",
            repo_cache=Path("/tmp/repo_cache.json"),
            output_dir=Path("/tmp/enriched"),
            max_candidates=100,
            min_atomic_prior=0.0,
            primary_calibration_json=Path("/tmp/full_diff.json"),
            proxy_calibration_json=Path("/tmp/message_only.json"),
            search_sleep_seconds=1.0,
            retry_on_429=3,
            progress_every=5,
            checkpoint_interval=10,
            reference_time_utc="2026-04-11T00:00:00Z",
            fetch_diff=True,
            reset_output=True,
            require_complete=True,
        )
        self.assertIn("--primary-calibration-json", cmd)
        self.assertIn("/tmp/full_diff.json", cmd)
        self.assertIn("--proxy-calibration-json", cmd)
        self.assertIn("/tmp/message_only.json", cmd)

    def test_build_proxy_gap_command_uses_primary_and_proxy_calibration_paths(
        self,
    ) -> None:
        cmd = runner.build_proxy_gap_command(
            python_executable="python",
            selection_batch_csv=Path("/tmp/selection/selection_batch.csv"),
            resolved_candidates_csv=Path("/tmp/enriched/resolved_candidates.csv"),
            validation_dir=Path("/tmp/validation"),
            annotated_csv=Path("/tmp/annotated.csv"),
            proxy_calibration_json=Path("/tmp/message_only.json"),
            primary_calibration_json=Path("/tmp/full_diff.json"),
            output_dir=Path("/tmp/analysis"),
            audit_target=300,
            annotated_split_plan_json="/tmp/annotated_splits/annotated_split_plan.json",
        )
        self.assertIn("--proxy-calibration-json", cmd)
        self.assertIn("/tmp/message_only.json", cmd)
        self.assertIn("--primary-calibration-json", cmd)
        self.assertIn("/tmp/full_diff.json", cmd)
        self.assertIn("--annotated-split-plan-json", cmd)

    def test_resolve_calibration_artifacts_infers_sibling_full_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            message_only = base / "message_only_calibration.json"
            full_diff = base / "atomic_calibration_full_diff.json"
            message_only.write_text("{}", encoding="utf-8")
            full_diff.write_text("{}", encoding="utf-8")
            resolved_full, resolved_message = runner.resolve_calibration_artifacts(
                message_only_calibration_json=Path(
                    "/unused/message_only_calibration.json"
                ),
                reuse_message_only_json=message_only.as_posix(),
                reuse_full_diff_json="",
                fetch_diff=True,
            )
            self.assertEqual(resolved_message, message_only)
            self.assertEqual(resolved_full, full_diff)

    def test_assign_probability_bin_uses_descending_lower_bounds(self) -> None:
        bins = [
            (0.75, "[0.75,1.00]"),
            (0.50, "[0.50,0.75)"),
            (0.25, "[0.25,0.50)"),
            (0.0, "[0.00,0.25)"),
        ]
        self.assertEqual(proxy_gap.assign_probability_bin(0.9, bins), "[0.75,1.00]")
        self.assertEqual(proxy_gap.assign_probability_bin(0.6, bins), "[0.50,0.75)")
        self.assertEqual(proxy_gap.assign_probability_bin(0.1, bins), "[0.00,0.25)")

    def test_estimate_feasibility_falls_back_to_band_then_overall(self) -> None:
        selection_rows = [
            {"sha": "s1", "type": "fix", "p_atomic": "0.8"},
            {"sha": "s2", "type": "feat", "p_atomic": "0.8"},
        ]
        probability_bins = [(0.75, "[0.75,1.00]"), (0.0, "[0.00,0.75)")]
        reference_table = {
            "bucket_counts": {"fix::[0.75,1.00]": {"B": 2, "A": 1}},
            "band_counts": {"[0.75,1.00]": {"B": 1, "C": 1}},
            "type_counts": {"fix": {"B": 2, "A": 1}},
            "overall_counts": {"B": 3, "A": 2, "C": 1},
        }
        result = proxy_gap.estimate_feasibility(
            selection_rows=selection_rows,
            reference_table=reference_table,
            probability_bins=probability_bins,
            target_tier="B",
        )
        self.assertEqual(result["selected_count"], 2)
        self.assertIn("fix::[0.75,1.00]", result["bucket_expectations"])
        self.assertIn("feat::[0.75,1.00]", result["bucket_expectations"])
        self.assertEqual(
            result["bucket_expectations"]["fix::[0.75,1.00]"]["source"], "bucket"
        )
        self.assertEqual(
            result["bucket_expectations"]["feat::[0.75,1.00]"]["source"], "band"
        )

    def test_combine_feasibility_prefers_cached_full_diff_precheck(self) -> None:
        reference = {
            "target_tier": "B",
            "selected_count": 10,
            "expected_target_tier_yield": 6.5,
            "conservative_target_tier_lower_bound": 2.7,
            "bucket_expectations": {},
            "fallback_usage": {},
        }
        cached = {
            "covered_selection_count": 8,
            "missing_selection_count": 2,
            "observed_tier_counts": {"A": 4, "B": 3, "C": 1},
            "observed_target_tier_yield": 3,
            "coverage_ratio": 0.8,
        }
        combined = proxy_gap.combine_feasibility_sources(
            reference_feasibility=reference,
            cached_precheck=cached,
            target_tier="B",
        )
        self.assertEqual(combined["source"], "cached_plus_reference_tail")
        self.assertEqual(combined["cached_observed_target_tier_yield"], 3)
        self.assertGreater(combined["expected_target_tier_yield"], 3.0)

    def test_diff_required_filter(self) -> None:
        self.assertTrue(
            validator.has_diff_features(
                {
                    "score": "1",
                    "file_count": "2",
                    "hunk_count": "3",
                    "changed_lines": "4",
                }
            )
        )
        self.assertFalse(
            validator.has_diff_features(
                {
                    "score": "",
                    "file_count": "2",
                    "hunk_count": "3",
                    "changed_lines": "4",
                }
            )
        )

    def test_validate_band_from_tier(self) -> None:
        self.assertEqual(validator.validate_band_from_tier("A"), "high")
        self.assertEqual(validator.validate_band_from_tier("B"), "mid")
        self.assertEqual(validator.validate_band_from_tier("C"), "low")
        self.assertEqual(validator.validate_band_from_tier(""), "")

    def test_validation_summary_uses_validate_band_language(self) -> None:
        tier_a = [{"type": "fix", "roles": "source", "validate_band": "high"}]
        tier_b = [{"type": "feat", "roles": "source", "validate_band": "mid"}]
        tier_c = [{"type": "test", "roles": "test", "validate_band": "low"}]
        args = Namespace(
            audit_size=300,
            candidates="/tmp/candidates.csv",
            pilot="/tmp/pilot.csv",
            calibration_json="/tmp/calibration.json",
            diff_required=True,
            tau_a=0.75,
            tau_b=0.42,
            audit_tier="B",
            threshold_source="message_only:constraint_from_calibration_precision",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.md"
            validator.summarize(tier_a, tier_b, tier_c, summary_path, args=args)
            content = summary_path.read_text(encoding="utf-8")
        self.assertIn("Validate High Band count", content)
        self.assertIn("Validate Mid Band count", content)
        self.assertIn("Validate Low Band count", content)
        self.assertIn(
            "reuse the calibration artifact's precision-constrained thresholds",
            content,
        )

    def test_epistemic_reference(self) -> None:
        ref = weight_calibration.derive_epistemic_reference([0.1, 0.2, 0.3, 0.4])
        self.assertIn("center", ref)
        self.assertIn("scale", ref)
        self.assertGreater(ref["scale"], 0.0)

    def test_check_validate_rejects_audit_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            validation_dir = Path(tmpdir)
            fieldnames = [
                "sha",
                "type",
                "prefilter_tier",
                "audit_is_single_intent",
                "audit_confidence",
            ]
            tier_a_rows = [
                {"sha": "a1", "type": "fix", "prefilter_tier": "A"} for _ in range(300)
            ]
            tier_b_rows = [
                {"sha": f"b{i}", "type": "feat", "prefilter_tier": "B"}
                for i in range(300)
            ]
            audit_rows = [
                {
                    "sha": f"b{i}",
                    "type": "feat",
                    "prefilter_tier": "B",
                    "audit_is_single_intent": "",
                    "audit_confidence": "",
                }
                for i in range(300)
            ]
            labeled_rows = [
                {
                    "sha": f"b{299 - i}",
                    "type": "feat",
                    "prefilter_tier": "B",
                    "audit_is_single_intent": "1",
                    "audit_confidence": "0.9",
                }
                for i in range(300)
            ]
            for name, rows in [
                ("tier_a_candidates.csv", tier_a_rows),
                ("tier_b_candidates.csv", tier_b_rows),
                ("tier_b_audit_sample.csv", audit_rows),
                ("labeled.csv", labeled_rows),
            ]:
                with (validation_dir / name).open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            with self.assertRaises(RuntimeError):
                runner.check_validate(
                    validation_dir=validation_dir,
                    audit_target=300,
                    require_audit_completion=True,
                    audit_labeled_csv=(validation_dir / "labeled.csv").as_posix(),
                    audit_tier="B",
                    expect_audit_samples=True,
                    strict=True,
                )

    def test_check_validate_surfaces_tier_a_precision_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            validation_dir = Path(tmpdir)
            fieldnames = ["sha", "type", "prefilter_tier"]
            tier_a_rows = [
                {"sha": f"a{i}", "type": "fix", "prefilter_tier": "A"}
                for i in range(300)
            ]
            tier_b_rows = [
                {"sha": f"b{i}", "type": "feat", "prefilter_tier": "B"}
                for i in range(10)
            ]
            audit_rows = [
                {"sha": f"a{i}", "type": "fix", "prefilter_tier": "A"}
                for i in range(300)
            ]
            for name, rows in [
                ("tier_a_candidates.csv", tier_a_rows),
                ("tier_b_candidates.csv", tier_b_rows),
                ("tier_a_audit_sample.csv", audit_rows),
            ]:
                with (validation_dir / name).open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            (validation_dir / "audit_precision_report.json").write_text(
                json.dumps(
                    {
                        "tier_a": {"precision": 0.97, "sample_count": 300},
                        "tier_b": {"precision": 0.81, "sample_count": 10},
                    }
                ),
                encoding="utf-8",
            )
            metrics = runner.check_validate(
                validation_dir=validation_dir,
                audit_target=300,
                require_audit_completion=False,
                audit_labeled_csv="",
                audit_tier="A",
                expect_audit_samples=True,
                strict=True,
            )
            self.assertEqual(metrics["tier_a_precision"], 0.97)
            self.assertEqual(metrics["tier_b_precision"], 0.81)

    def test_build_validate_command_respects_diff_flag(self) -> None:
        kwargs = dict(
            python_executable="python",
            candidates_csv=Path("/tmp/candidates.csv"),
            pilot_csv="/tmp/pilot.csv",
            output_dir=Path("/tmp/out"),
            sample_per_tier=30,
            seed=31,
            primary_calibration_json=Path("/tmp/full_diff.json"),
            audit_size=300,
            tier_a_audit_labeled_csv="",
            tier_b_audit_labeled_csv="",
            require_audit_completion=False,
            export_audit_samples=True,
            audit_tier="A",
            threshold_mode="full_diff",
            annotated_split_plan_json="/tmp/annotated_splits/annotated_split_plan.json",
        )
        cmd_no_diff = runner.build_validate_command(diff_required=False, **kwargs)
        self.assertIn("--no-diff-required", cmd_no_diff)
        self.assertNotIn("--diff-required", cmd_no_diff)
        self.assertIn("--audit-tier", cmd_no_diff)
        self.assertIn("A", cmd_no_diff)
        self.assertIn("--threshold-mode", cmd_no_diff)
        self.assertIn("full_diff", cmd_no_diff)
        self.assertIn("--tier-a-audit-labeled-csv", cmd_no_diff)
        self.assertIn("--tier-b-audit-labeled-csv", cmd_no_diff)
        self.assertIn("--primary-calibration-json", cmd_no_diff)
        self.assertIn("/tmp/full_diff.json", cmd_no_diff)
        self.assertIn("--annotated-split-plan-json", cmd_no_diff)

        cmd_with_diff = runner.build_validate_command(diff_required=True, **kwargs)
        self.assertIn("--diff-required", cmd_with_diff)
        self.assertNotIn("--no-diff-required", cmd_with_diff)

    def test_attach_pilot_fields_keeps_existing_diff(self) -> None:
        rows = [
            {
                "sha": "abc",
                "git_diff": "existing-diff",
                "masked_commit_message": "existing-msg",
                "annotated_type": "existing-type",
            }
        ]
        pilot_rows = [
            {
                "sha": "abc",
                "git_diff": "pilot-diff",
                "masked_commit_message": "pilot-msg",
                "annotated_type": "pilot-type",
            }
        ]
        enriched_rows = validator.attach_pilot_fields(rows, pilot_rows)
        self.assertEqual(enriched_rows[0]["git_diff"], "existing-diff")
        self.assertEqual(enriched_rows[0]["masked_commit_message"], "existing-msg")
        self.assertEqual(enriched_rows[0]["annotated_type"], "existing-type")

    def test_atomic_signal_map_message_only_has_all_keys(self) -> None:
        message_features = miner.parse_message("fix: stabilize message-only prior path")
        signals = miner.atomic_signal_map(
            message_features=message_features,
            candidate_type="fix",
            diff_features=None,
        )
        for key in miner.ATOMIC_SIGNAL_KEYS:
            self.assertIn(key, signals)

    def test_atomic_feature_order_excludes_zero_placeholder_features(self) -> None:
        self.assertNotIn("time_isolation", miner.ATOMIC_FEATURE_ORDER)
        self.assertNotIn("author_commit_frequency", miner.ATOMIC_FEATURE_ORDER)
        self.assertNotIn("branch_type", miner.ATOMIC_FEATURE_ORDER)

    def test_build_atomic_feature_map_omits_zero_placeholder_features(self) -> None:
        message_features = miner.parse_message("fix(parser): tighten unicode path")
        diff_features = miner.parse_diff(
            """diff --git a/src/parser.py b/src/parser.py
index 1111111..2222222 100644
--- a/src/parser.py
+++ b/src/parser.py
@@ -1,2 +1,3 @@ def parse():
-value = old_call()
+value = new_call()
+return value
"""
        )
        feature_map = miner.build_atomic_feature_map(
            message_features=message_features,
            candidate_type="fix",
            diff_features=diff_features,
        )
        self.assertNotIn("time_isolation", feature_map)
        self.assertNotIn("author_commit_frequency", feature_map)
        self.assertNotIn("branch_type", feature_map)

    def test_resolve_thresholds_explicit_overrides_calibration(self) -> None:
        calibration = {"thresholds": {"tau_a": 0.8, "tau_b": 0.4}}
        tau_a, tau_b = miner.resolve_thresholds(
            calibration=calibration,
            tau_a=0.9,
            tau_b=0.2,
        )
        self.assertEqual(tau_a, 0.9)
        self.assertEqual(tau_b, 0.2)

    def test_derive_thresholds_explicit_pair_bypasses_distribution(self) -> None:
        tau_a, tau_b, source = miner.derive_thresholds(
            probabilities=[0.5, 0.5, 0.5],
            calibration={"thresholds": {"tau_a": 0.8, "tau_b": 0.4}},
            tau_a=0.9,
            tau_b=0.2,
        )
        self.assertEqual((tau_a, tau_b), (0.9, 0.2))
        self.assertEqual(source, "fixed_from_args")

    def test_prefilter_threshold_derivation_ignores_calibration_thresholds(
        self,
    ) -> None:
        rows = [
            {"sha": "s1", "type": "fix", "commit_message": "fix: keep parser stable"},
            {"sha": "s2", "type": "feat", "commit_message": "feat: add smoke guard"},
        ]
        calibration = {
            "model_mode": "message_only",
            "thresholds": {"tau_a": 0.95, "tau_b": 0.90},
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            },
        }
        with patch.object(
            prefilter.miner,
            "derive_thresholds",
            return_value=(0.6, 0.3, "mock_distribution"),
        ) as mocked:
            candidates = prefilter.build_candidates(
                rows=rows,
                min_prefilter_prob=1e-6,
                tau_a=None,
                tau_b=None,
                calibration=calibration,
            )
        self.assertTrue(len(candidates) >= 1)
        self.assertTrue(mocked.called)
        _, kwargs = mocked.call_args
        self.assertIsNone(kwargs["calibration"])

    def test_prefilter_message_only_path_applies_isotonic_calibration(self) -> None:
        rows = [
            {"sha": "s1", "type": "fix", "commit_message": "fix: keep parser stable"},
            {"sha": "s2", "type": "fix", "commit_message": "fix: tighten parser guard"},
        ]
        calibration = {
            "fit_config": {"mode": "message_only_isotonic"},
            "isotonic": {"x": [0.0, 0.25, 0.5], "y": [0.05, 0.4, 0.95]},
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            },
        }
        with patch.object(
            prefilter.miner,
            "derive_thresholds",
            return_value=(0.8, 0.5, "mock_distribution"),
        ):
            candidates = prefilter.build_candidates(
                rows=rows,
                min_prefilter_prob=1e-6,
                tau_a=None,
                tau_b=None,
                calibration=calibration,
            )
        self.assertGreaterEqual(len(candidates), 1)
        self.assertGreater(
            float(candidates[0]["p_atomic"]),
            float(candidates[0]["atomic_prior"]),
        )

    def test_prefilter_only_accepts_message_only_thresholds_from_matching_artifact(
        self,
    ) -> None:
        full_diff_calibration = {
            "model_mode": "full_diff",
            "fit_config": {"mode": "gbdt_isotonic"},
            "thresholds": {"tau_a": 0.95, "tau_b": 0.863636},
        }
        with self.assertRaises(ValueError):
            prefilter.resolve_prefilter_thresholds(
                calibration=full_diff_calibration,
                tau_a=None,
                tau_b=None,
            )

        message_only_calibration = {
            "model_mode": "message_only",
            "fit_config": {"mode": "message_only_isotonic"},
            "thresholds": {"tau_a": 0.42, "tau_b": 0.31},
        }
        tau_a, tau_b = prefilter.resolve_prefilter_thresholds(
            calibration=message_only_calibration,
            tau_a=None,
            tau_b=None,
        )
        self.assertEqual((tau_a, tau_b), (0.42, 0.31))

    def test_prefilter_removes_score_gate_for_message_only_calibration(self) -> None:
        rows = [
            {"sha": "s1", "type": "fix", "commit_message": "fix: keep parser stable"},
            {"sha": "s2", "type": "feat", "commit_message": "feat: add parser guard"},
        ]
        calibration = {
            "fit_config": {"mode": "message_only_platt"},
            "platt_slope": 1.2,
            "platt_intercept": 0.1,
            "signal_context": {
                "weights": {
                    key: 1.0 / len(miner.ATOMIC_SIGNAL_KEYS)
                    for key in miner.ATOMIC_SIGNAL_KEYS
                }
            },
        }
        with patch.object(
            prefilter.miner,
            "derive_thresholds",
            return_value=(0.8, 0.5, "mock_distribution"),
        ):
            candidates = prefilter.build_candidates(
                rows=rows,
                min_prefilter_prob=1e-6,
                tau_a=None,
                tau_b=None,
                calibration=calibration,
            )
        self.assertTrue(candidates)
        self.assertNotIn("prefilter_score_gate", candidates[0])
        self.assertNotIn("prefilter_score_gate_source", candidates[0])

    def test_message_only_audit_shortfalls_are_computed_per_type_and_label(
        self,
    ) -> None:
        rows = [
            {"type": "fix", "is_single_intent": "1"},
            {"type": "fix", "is_single_intent": "1"},
            {"type": "fix", "is_single_intent": "0"},
            {"type": "feat", "is_single_intent": "0"},
            {"type": "refactor", "is_single_intent": "1"},
        ]
        coverage = message_only_audit.compute_type_label_coverage(rows)
        self.assertEqual(coverage["fix"][1], 2)
        self.assertEqual(coverage["fix"][0], 1)
        self.assertEqual(coverage["feat"][1], 0)
        shortfalls = message_only_audit.compute_label_shortfalls(
            coverage,
            min_per_type_label=2,
            substantive_types=("fix", "feat", "refactor"),
        )
        self.assertEqual(shortfalls["fix"][1], 0)
        self.assertEqual(shortfalls["fix"][0], 1)
        self.assertEqual(shortfalls["feat"][1], 2)
        self.assertEqual(shortfalls["feat"][0], 1)
        self.assertEqual(shortfalls["refactor"][0], 2)

    def test_label_message_only_audit_sample_applies_deterministic_labels(self) -> None:
        row = {
            "sha": "s1",
            "type": "feat",
            "commit_message": "feat(docz-core): improve plugin and add support to modify babel",
            "subject": "feat(docz-core): improve plugin and add support to modify babel",
            "file_count": "11",
            "changed_lines": "201",
            "roles": "source",
        }
        labeled = audit_labeler.label_audit_row(row)
        self.assertEqual(labeled["audit_is_single_intent"], "0")
        self.assertEqual(labeled["audit_notes"], "multi_goal_subject_marker")

    def test_assemble_message_only_expanded_dataset_appends_labeled_rows(self) -> None:
        base_rows = [
            {
                "sha": "a",
                "repo": "owner/repo",
                "resolved_repo": "owner/repo",
                "commit_url": "",
                "type": "fix",
                "annotated_type": "fix",
                "commit_message": "fix: base row",
                "masked_commit_message": "fix: base row",
                "git_diff": "diff --git a/a b/a",
                "resolution_status": "resolved_local",
                "repo_candidate_count": "",
                "candidate_repos": "",
                "diff_line_count": "1",
                "diff_char_count": "20",
                "diff_error": "",
                "is_single_intent": "1",
                "audit_confidence": "0.9",
                "audit_reviewer": "r",
                "audit_notes": "",
                "label_source": "base",
            }
        ]
        audit_rows = [
            {
                "sha": "b",
                "repo": "owner/repo",
                "type": "feat",
                "commit_message": "feat: new row",
                "git_diff": "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n",
                "diff_changed_lines": "2",
                "audit_is_single_intent": "0",
                "audit_confidence": "0.8",
                "audit_reviewer": "r2",
                "audit_notes": "n",
            }
        ]
        merged = expanded_dataset.merge_expanded_dataset(
            annotated_rows=base_rows,
            audit_rows=audit_rows,
            label_source="message_only_rebuild_test",
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[-1]["sha"], "b")
        self.assertEqual(merged[-1]["is_single_intent"], "0")

    def test_assemble_message_only_expanded_dataset_skips_invalid_diff_features(
        self,
    ) -> None:
        base_rows = []
        audit_rows = [
            {
                "sha": "rename-only",
                "repo": "owner/repo",
                "type": "refactor",
                "commit_message": "refactor: rename file",
                "git_diff": "diff --git a/a b/b\nsimilarity index 100%\nrename from a\nrename to b\n",
                "diff_changed_lines": "0",
                "audit_is_single_intent": "1",
                "audit_confidence": "0.9",
                "audit_reviewer": "r",
                "audit_notes": "n",
            }
        ]
        merged = expanded_dataset.merge_expanded_dataset(
            annotated_rows=base_rows,
            audit_rows=audit_rows,
            label_source="message_only_rebuild_test",
        )
        self.assertEqual(merged, [])

    def test_check_calibration_accepts_message_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            calibration_path = Path(tmpdir) / "message_only_calibration.json"
            calibration_path.write_text(
                """
{
  "artifact_version": "step1_message_only_platt_v1",
  "platt_slope": 1.0,
  "platt_intercept": 0.0,
  "signal_context": {"weights": {"has_single_prefix": 1.0}},
  "message_protocol": {"subject_len_min": 0},
  "scope_protocol": {"file_scope_small_max": 0},
  "type_protocol": {"values": {}},
  "epistemic_reference": {"center": 0.0, "scale": 1.0},
  "thresholds": {
    "tau_a": 0.9,
    "tau_b": 0.7,
    "source": "constraint_from_labeled_precision_message_only_platt_cv",
    "selection_reports": {
      "tau_a": {"used_fallback": false},
      "tau_b": {"used_fallback": false}
    }
  },
  "fit_config": {"mode": "message_only_platt"}
}
                """.strip(),
                encoding="utf-8",
            )
            metrics = runner.check_calibration(calibration_path, strict=True)
        self.assertEqual(metrics["calibration_mode"], "message_only_platt")
        self.assertTrue(metrics["is_message_only"])
        self.assertEqual(metrics["model_mode"], "message_only")
        self.assertEqual(metrics["model_role"], "proxy")

    def test_check_calibration_rejects_non_message_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            calibration_path = Path(tmpdir) / "atomic_calibration.json"
            calibration_path.write_text(
                """
{
  "artifact_version": "step1_atomic_gbdt_isotonic_v1",
  "model_pickle_b64": "AA==",
  "feature_order": ["x"],
  "signal_context": {"weights": {"has_single_prefix": 1.0}},
  "message_protocol": {"subject_len_min": 0},
  "scope_protocol": {"file_scope_small_max": 0},
  "type_protocol": {"values": {}},
  "feature_norm_stats": {"global": {"changed_lines": {}, "module_count": {}}},
  "epistemic_reference": {"center": 0.0, "scale": 1.0},
  "thresholds": {
    "tau_a": 0.9,
    "tau_b": 0.7,
    "source": "constraint_from_labeled_precision_holdout",
    "selection_reports": {
      "tau_a": {"used_fallback": false},
      "tau_b": {"used_fallback": false}
    }
  },
  "fit_config": {"mode": "gbdt_isotonic"}
}
                """.strip(),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                runner.check_calibration(calibration_path, strict=True)

    def test_derive_per_type_from_message_only_prefilter_pool(self) -> None:
        per_type = runner.derive_per_type_from_pool(
            per_type_arg=0,
            audit_target=300,
            substantive_type_counts={
                "fix": 23339,
                "feat": 15022,
                "refactor": 8403,
                "test": 5252,
                "perf": 387,
            },
            observed_tier_a_ratio=0.0,
        )
        self.assertEqual(per_type, 300)

    def test_derive_per_type_uses_four_type_hard_balance_not_perf_floor(self) -> None:
        per_type = runner.derive_per_type_from_pool(
            per_type_arg=0,
            audit_target=300,
            substantive_type_counts={
                "fix": 22847,
                "feat": 14306,
                "refactor": 8020,
                "test": 5038,
                "perf": 8,
            },
            observed_tier_a_ratio=0.0,
        )
        self.assertEqual(per_type, 300)

    def test_resolve_validate_audit_tier(self) -> None:
        self.assertEqual(runner.resolve_validate_audit_tier(), "A")

    def test_resolve_validate_threshold_mode(self) -> None:
        self.assertEqual(runner.resolve_validate_threshold_mode(), "full_diff")

    def test_build_audit_samples_defaults_to_tier_a_primary(self) -> None:
        tier_a = [
            {"sha": f"a{i}", "type": "fix", "subject": f"fix: {i}"} for i in range(5)
        ]
        tier_b = [
            {"sha": f"b{i}", "type": "feat", "subject": f"feat: {i}"} for i in range(4)
        ]
        bundle = validator.build_audit_samples(
            tier_a_rows=tier_a,
            tier_b_rows=tier_b,
            audit_size=3,
            audit_sampling="random",
            seed=31,
            primary_audit_tier="A",
        )
        self.assertEqual(bundle["primary_audit_tier"], "A")
        self.assertEqual(len(bundle["tier_a_audit_sample"]), 3)
        self.assertEqual(len(bundle["tier_b_audit_sample"]), 3)
        self.assertTrue(
            all(row["sha"].startswith("a") for row in bundle["primary_audit_sample"])
        )

    def test_build_precision_report_contains_tier_a_and_tier_b_precision(self) -> None:
        tier_a_labeled = [
            {
                "sha": "a1",
                "audit_is_single_intent": "1",
                "audit_confidence": "0.9",
                "commit_message": "fix: a",
            },
            {
                "sha": "a2",
                "audit_is_single_intent": "0",
                "audit_confidence": "0.8",
                "commit_message": "fix: b",
            },
        ]
        tier_b_labeled = [
            {
                "sha": "b1",
                "audit_is_single_intent": "1",
                "audit_confidence": "0.9",
                "commit_message": "feat: a",
            },
        ]
        report = validator.build_precision_report(
            tier_a_labeled_rows=tier_a_labeled,
            tier_b_labeled_rows=tier_b_labeled,
            independent_split_stats={
                "overlap_sha_count": 0,
                "candidate_rows": 3,
                "pilot_rows": 10,
            },
            tier_a_pattern_csv="tier_a_patterns.csv",
            tier_b_pattern_csv="tier_b_patterns.csv",
        )
        self.assertIn("tier_a", report)
        self.assertIn("tier_b", report)
        self.assertEqual(report["tier_a"]["sample_count"], 2)
        self.assertEqual(report["tier_b"]["sample_count"], 1)
        self.assertIn("precision", report["tier_a"])
        self.assertIn("wilson95_low", report["tier_a"])
        self.assertIn("misclassification_pattern_summary_csv", report["tier_a"])

    def test_minimal_e2e_prefilter_to_select_pipeline(self) -> None:
        rows = []
        sha = 0
        for commit_type in selector.SUBSTANTIVE_TYPES:
            for idx in range(3):
                sha += 1
                rows.append(
                    {
                        "sha": f"s{sha}",
                        "type": commit_type,
                        "commit_message": f"{commit_type}: e2e smoke message {idx}",
                    }
                )
        candidates = prefilter.build_candidates(
            rows=rows,
            min_prefilter_prob=1e-6,
            tau_a=0.8,
            tau_b=0.2,
            calibration=None,
        )
        selected = selector.select_rows(
            rows=candidates,
            per_type=1,
            exclude_breaking=False,
            offset_per_type=0,
            seed=19,
        )
        self.assertEqual(len(selected), len(selector.HARD_BALANCE_TYPES))

    def test_select_rows_does_not_require_perf_for_hard_balance(self) -> None:
        rows = []
        sha = 0
        for commit_type in selector.HARD_BALANCE_TYPES:
            for idx in range(3):
                sha += 1
                rows.append(
                    {
                        "sha": f"s{sha}",
                        "type": commit_type,
                        "subject": f"{commit_type}: message {idx}",
                        "prefilter_tier": "A",
                    }
                )
        selected = selector.select_rows(
            rows=rows,
            per_type=2,
            exclude_breaking=False,
            offset_per_type=0,
            seed=7,
        )
        self.assertEqual(len(selected), 2 * len(selector.HARD_BALANCE_TYPES))
        self.assertNotIn("perf", {row["type"] for row in selected})
        type_counter = {item["type"] for item in selected}
        self.assertEqual(type_counter, set(selector.HARD_BALANCE_TYPES))

    def test_resolve_enrich_tier_thresholds_fetch_diff_prefers_full_diff_source(
        self,
    ) -> None:
        tau_a, tau_b, source = enrich.resolve_enrich_tier_thresholds(
            message_only_probabilities=[0.1, 0.9],
            calibration={"thresholds": {"tau_a": 0.8, "tau_b": 0.4}},
            tau_a=None,
            tau_b=None,
            fetch_diff=True,
        )
        self.assertEqual((tau_a, tau_b), (0.8, 0.4))
        self.assertEqual(source, "full_diff:constraint_from_calibration_precision")

    def test_resolve_enrich_tier_thresholds_message_only_ignores_calibration(
        self,
    ) -> None:
        with patch.object(
            enrich.miner,
            "derive_thresholds",
            return_value=(0.6, 0.3, "distribution"),
        ) as mocked:
            tau_a, tau_b, source = enrich.resolve_enrich_tier_thresholds(
                message_only_probabilities=[0.2, 0.4, 0.6],
                calibration={"thresholds": {"tau_a": 0.9, "tau_b": 0.8}},
                tau_a=None,
                tau_b=None,
                fetch_diff=False,
            )
        self.assertEqual((tau_a, tau_b), (0.6, 0.3))
        self.assertEqual(source, "message_only:distribution")
        _, kwargs = mocked.call_args
        self.assertIsNone(kwargs["calibration"])

    def test_enrich_prefers_local_commit_texts_payload(self) -> None:
        row = {"sha": "abc"}
        local_payload = {
            "abc": {
                "repo": "owner/repo",
                "commit_message": "fix: local payload",
                "git_diff": "diff --git a/a b/a\n@@ -1 +1 @@\n-a\n+b\n",
            }
        }
        resolved = enrich.resolve_local_candidate_payload(row, local_payload)
        self.assertEqual(resolved["resolved_repo"], "owner/repo")
        self.assertIn("diff --git", resolved["git_diff"])

    def test_resolve_enrich_tier_thresholds_fetch_diff_requires_full_diff_source(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            enrich.resolve_enrich_tier_thresholds(
                message_only_probabilities=[0.1, 0.2, 0.3],
                calibration=None,
                tau_a=None,
                tau_b=None,
                fetch_diff=True,
            )

    def test_validate_row_atomic_probability_prefers_message_only(self) -> None:
        row = {
            "atomic_prior_calibrated": "0.9",
            "atomic_prior_message_only_calibrated": "0.4",
        }
        self.assertAlmostEqual(
            validator.row_atomic_probability(row, prefer_message_only=True), 0.4
        )
        self.assertAlmostEqual(
            validator.row_atomic_probability(row, prefer_message_only=False), 0.9
        )

    def test_validate_row_atomic_probability_message_only_does_not_fallback_to_full_diff(
        self,
    ) -> None:
        row = {
            "atomic_prior_calibrated": "0.9",
            "atomic_prior": "0.8",
        }
        self.assertIsNone(
            validator.row_atomic_probability(row, prefer_message_only=True)
        )

    def test_validate_row_atomic_probability_full_diff_does_not_fallback_to_message_only(
        self,
    ) -> None:
        row = {
            "atomic_prior_message_only_calibrated": "0.4",
            "atomic_prior_message_only": "0.3",
        }
        self.assertIsNone(
            validator.row_atomic_probability(row, prefer_message_only=False)
        )

    def test_resolve_validate_thresholds_full_diff_uses_calibration(self) -> None:
        candidates = [
            {"atomic_prior_calibrated": "0.2"},
            {"atomic_prior_calibrated": "0.8"},
        ]
        with patch.object(
            validator.miner,
            "derive_thresholds",
            return_value=(0.9, 0.7, "constraint_from_calibration_precision"),
        ) as mocked:
            tau_a, tau_b, source = validator.resolve_validate_thresholds(
                candidates=candidates,
                calibration={
                    "model_mode": "full_diff",
                    "artifact_version": "step1_atomic_gbdt_isotonic_v1",
                    "fit_config": {"mode": "gbdt_isotonic"},
                    "thresholds": {"tau_a": 0.9, "tau_b": 0.7},
                },
                tau_a=None,
                tau_b=None,
                threshold_mode="full_diff",
            )
        self.assertEqual((tau_a, tau_b), (0.9, 0.7))
        self.assertEqual(source, "full_diff:constraint_from_calibration_precision")
        _, kwargs = mocked.call_args
        self.assertIsNotNone(kwargs["calibration"])

    def test_resolve_validate_thresholds_full_diff_rejects_proxy_artifact(self) -> None:
        candidates = [
            {"atomic_prior_calibrated": "0.2"},
            {"atomic_prior_calibrated": "0.8"},
        ]
        with self.assertRaises(ValueError):
            validator.resolve_validate_thresholds(
                candidates=candidates,
                calibration={
                    "model_mode": "message_only",
                    "artifact_version": "step1_message_only_platt_v1",
                    "fit_config": {"mode": "message_only_platt"},
                    "thresholds": {"tau_a": 0.95, "tau_b": 0.85},
                },
                tau_a=None,
                tau_b=None,
                threshold_mode="full_diff",
            )

    def test_resolve_validate_thresholds_message_only_uses_calibration(self) -> None:
        candidates = [
            {"atomic_prior_message_only_calibrated": "0.2"},
            {"atomic_prior_message_only_calibrated": "0.8"},
        ]
        with patch.object(
            validator.miner,
            "derive_thresholds",
            return_value=(0.95, 0.85, "constraint_from_calibration_precision"),
        ) as mocked:
            tau_a, tau_b, source = validator.resolve_validate_thresholds(
                candidates=candidates,
                calibration={
                    "model_mode": "message_only",
                    "artifact_version": "step1_message_only_platt_v1",
                    "fit_config": {"mode": "message_only_platt"},
                    "thresholds": {"tau_a": 0.95, "tau_b": 0.85},
                },
                tau_a=None,
                tau_b=None,
                threshold_mode="message_only",
            )
        self.assertEqual((tau_a, tau_b), (0.95, 0.85))
        self.assertEqual(source, "message_only:constraint_from_calibration_precision")
        _, kwargs = mocked.call_args
        self.assertIsNotNone(kwargs["calibration"])

    def test_resolve_validate_thresholds_message_only_rejects_primary_artifact(
        self,
    ) -> None:
        candidates = [
            {"atomic_prior_message_only_calibrated": "0.2"},
            {"atomic_prior_message_only_calibrated": "0.8"},
        ]
        with self.assertRaises(ValueError):
            validator.resolve_validate_thresholds(
                candidates=candidates,
                calibration={
                    "model_mode": "full_diff",
                    "artifact_version": "step1_atomic_gbdt_isotonic_v1",
                    "fit_config": {"mode": "gbdt_isotonic"},
                    "thresholds": {"tau_a": 0.9, "tau_b": 0.7},
                },
                tau_a=None,
                tau_b=None,
                threshold_mode="message_only",
            )

    def test_check_calibration_accepts_full_diff_artifact_when_expected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            calibration_path = Path(tmpdir) / "atomic_calibration_full_diff.json"
            calibration_path.write_text(
                """
{
  "artifact_version": "step1_atomic_gbdt_isotonic_v1",
  "model_pickle_b64": "AA==",
  "feature_order": ["x"],
  "signal_context": {"weights": {"has_single_prefix": 1.0}},
  "message_protocol": {"subject_len_min": 0},
  "scope_protocol": {"file_scope_small_max": 0},
  "type_protocol": {"values": {}},
  "feature_norm_stats": {"global": {"changed_lines": {}, "module_count": {}}},
  "epistemic_reference": {"center": 0.0, "scale": 1.0},
  "thresholds": {
    "tau_a": 0.9,
    "tau_b": 0.7,
    "source": "constraint_from_labeled_precision_holdout",
    "selection_reports": {
      "tau_a": {"used_fallback": false},
      "tau_b": {"used_fallback": false}
    }
  },
  "fit_config": {"mode": "gbdt_isotonic"}
}
                """.strip(),
                encoding="utf-8",
            )
            metrics = runner.check_calibration(
                calibration_path, strict=True, expected_artifact="full_diff"
            )
        self.assertEqual(metrics["calibration_mode"], "gbdt_isotonic")
        self.assertFalse(metrics["is_message_only"])
        self.assertEqual(metrics["model_mode"], "full_diff")
        self.assertEqual(metrics["model_role"], "primary")

    def test_analyze_proxy_gap_reports_conversion_matrix_and_downgrade_rate(
        self,
    ) -> None:
        probability_bins = [(0.75, "[0.75,1.00]"), (0.0, "[0.00,0.75)")]
        selection_rows = [
            {
                "sha": "s1",
                "type": "fix",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.95",
            },
            {
                "sha": "s2",
                "type": "feat",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.82",
            },
            {
                "sha": "s3",
                "type": "test",
                "prefilter_tier": "B",
                "p_atomic_message_only": "0.40",
            },
        ]
        resolved_rows = [
            {"sha": "s1", "type": "fix"},
            {"sha": "s2", "type": "feat"},
            {"sha": "s3", "type": "test"},
        ]
        tier_a_rows = [{"sha": "s2"}]
        tier_b_rows = [{"sha": "s3"}]
        tier_c_rows = []
        result = proxy_gap.analyze_proxy_gap(
            selection_rows=selection_rows,
            resolved_rows=resolved_rows,
            tier_a_rows=tier_a_rows,
            tier_b_rows=tier_b_rows,
            tier_c_rows=tier_c_rows,
            probability_bins=probability_bins,
        )
        self.assertEqual(result["missing_tier_policy"], "missing_as_unknown")
        self.assertEqual(result["proxy_to_primary_tier_matrix"]["A->UNKNOWN"], 1)
        self.assertEqual(result["proxy_to_primary_tier_matrix"]["A->A"], 1)
        self.assertEqual(result["proxy_to_primary_tier_matrix"]["B->B"], 1)
        self.assertEqual(
            result["tier_consistency_denominator_policy"],
            "known_primary_tier_only",
        )
        self.assertEqual(
            result["downgrade_denominator_policy"],
            "proxy_a_with_known_primary_tier_only",
        )
        self.assertAlmostEqual(
            result["downgrade_rate_message_only_a_to_full_diff_c"], 0.0
        )
        self.assertAlmostEqual(result["message_only_tier_a_unknown_rate"], 0.5)
        self.assertAlmostEqual(result["tier_consistency"], 1.0)

    def test_analyze_proxy_gap_can_record_true_tier_c_explicitly(self) -> None:
        probability_bins = [(0.75, "[0.75,1.00]"), (0.0, "[0.00,0.75)")]
        selection_rows = [
            {
                "sha": "s1",
                "type": "fix",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.95",
            },
            {
                "sha": "s2",
                "type": "feat",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.82",
            },
        ]
        resolved_rows = [
            {"sha": "s1", "type": "fix"},
            {"sha": "s2", "type": "feat"},
        ]
        result = proxy_gap.analyze_proxy_gap(
            selection_rows=selection_rows,
            resolved_rows=resolved_rows,
            tier_a_rows=[{"sha": "s2"}],
            tier_b_rows=[],
            tier_c_rows=[{"sha": "s1"}],
            probability_bins=probability_bins,
        )
        self.assertEqual(result["proxy_to_primary_tier_matrix"]["A->C"], 1)
        self.assertEqual(result["proxy_to_primary_tier_matrix"]["A->A"], 1)
        self.assertAlmostEqual(
            result["downgrade_rate_message_only_a_to_full_diff_c"], 0.5
        )

    def test_analyze_proxy_gap_missing_as_c_is_only_sensitivity_mode(self) -> None:
        probability_bins = [(0.75, "[0.75,1.00]"), (0.0, "[0.00,0.75)")]
        selection_rows = [
            {
                "sha": "s1",
                "type": "fix",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.95",
            },
            {
                "sha": "s2",
                "type": "feat",
                "prefilter_tier": "A",
                "p_atomic_message_only": "0.82",
            },
        ]
        resolved_rows = [
            {"sha": "s1", "type": "fix"},
            {"sha": "s2", "type": "feat"},
        ]
        default_result = proxy_gap.analyze_proxy_gap(
            selection_rows=selection_rows,
            resolved_rows=resolved_rows,
            tier_a_rows=[{"sha": "s2"}],
            tier_b_rows=[],
            tier_c_rows=[],
            probability_bins=probability_bins,
        )
        sensitivity_result = proxy_gap.analyze_proxy_gap(
            selection_rows=selection_rows,
            resolved_rows=resolved_rows,
            tier_a_rows=[{"sha": "s2"}],
            tier_b_rows=[],
            tier_c_rows=[],
            probability_bins=probability_bins,
            missing_tier_policy="missing_as_c",
        )
        self.assertEqual(default_result["missing_tier_policy"], "missing_as_unknown")
        self.assertEqual(sensitivity_result["missing_tier_policy"], "missing_as_c")
        self.assertEqual(
            default_result["proxy_to_primary_tier_matrix"]["A->UNKNOWN"], 1
        )
        self.assertEqual(sensitivity_result["proxy_to_primary_tier_matrix"]["A->C"], 1)
        self.assertTrue(sensitivity_result["is_sensitivity_analysis"])

    def test_proxy_gap_payload_records_missing_policy_and_sensitivity_analysis(
        self,
    ) -> None:
        payload = proxy_gap_schema.build_proxy_quality_payload(
            selection_count=10,
            resolved_count=10,
            proxy_probability_gap={
                "message_only_auc": 0.9,
                "full_diff_auc": 0.95,
                "message_only_brier": 0.11,
                "full_diff_brier": 0.08,
                "message_only_logloss": 0.31,
                "full_diff_logloss": 0.22,
            },
            conversion_metrics={
                "missing_tier_policy": "missing_as_unknown",
                "tier_consistency": 0.8,
                "downgrade_rate_message_only_a_to_full_diff_c": 0.05,
                "proxy_to_primary_tier_matrix": {"A->A": 5, "A->UNKNOWN": 1},
            },
            sensitivity_analysis={
                "missing_as_c": {
                    "missing_tier_policy": "missing_as_c",
                    "is_sensitivity_analysis": True,
                }
            },
        )
        self.assertEqual(
            payload["conversion_metrics"]["missing_tier_policy"], "missing_as_unknown"
        )
        self.assertIn("sensitivity_analysis", payload)
        self.assertIn("missing_as_c", payload["sensitivity_analysis"])

    def test_proxy_gap_probability_metrics_include_logloss(self) -> None:
        metrics = proxy_gap.build_probability_gap_metrics_from_arrays(
            labels=[1, 0, 1, 0],
            message_only_probs=[0.9, 0.4, 0.7, 0.3],
            full_diff_probs=[0.95, 0.2, 0.8, 0.1],
            proxy_tiers=["A", "B", "A", "C"],
            primary_tiers=["A", "C", "B", "C"],
        )
        self.assertIn("message_only_logloss", metrics)
        self.assertIn("full_diff_logloss", metrics)
        self.assertIn("logloss_gap_proxy_minus_primary", metrics)
        self.assertGreater(metrics["message_only_logloss"], 0.0)

    def test_proxy_gap_probability_metrics_prefer_adjudicated_label(self) -> None:
        annotated_rows = [
            {
                "type": "fix",
                "annotated_type": "fix",
                "commit_message": "fix: a",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "0",
                "raw_label": "0",
                "adjudicated_label": "1",
            },
            {
                "type": "feat",
                "annotated_type": "feat",
                "commit_message": "feat: b",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
                "is_single_intent": "1",
                "raw_label": "1",
                "adjudicated_label": "0",
            },
        ]
        with (
            patch.object(
                proxy_gap, "_message_only_probability", side_effect=[0.9, 0.1]
            ),
            patch.object(
                proxy_gap,
                "_full_diff_probability_and_tier",
                side_effect=[(0.95, "A"), (0.05, "C")],
            ),
        ):
            metrics = proxy_gap.build_probability_gap_metrics(
                annotated_rows=annotated_rows,
                message_only_calibration={"thresholds": {"tau_a": 0.8, "tau_b": 0.5}},
                full_diff_calibration={"thresholds": {"tau_a": 0.8, "tau_b": 0.5}},
            )
        self.assertEqual(metrics["annotated_metric_sample_count"], 2)
        self.assertAlmostEqual(metrics["message_only_auc"], 1.0)

    def test_derive_proxy_conclusion_reliable_prefilter(self) -> None:
        payload = {
            "proxy_probability_gap": {
                "message_only_auc": 0.91,
                "full_diff_auc": 0.95,
                "message_only_brier": 0.10,
                "full_diff_brier": 0.07,
            },
            "conversion_metrics": {
                "tier_consistency": 0.87,
                "downgrade_rate_message_only_a_to_full_diff_c": 0.03,
            },
        }
        conclusion = proxy_gap_schema.derive_proxy_conclusion(payload)
        self.assertEqual(conclusion["classification"], "reliable_prefilter")
        self.assertIn("suitable as a broad prefilter", conclusion["paper_sentence"])

    def test_derive_proxy_conclusion_not_reliable_for_atomic_decision(self) -> None:
        payload = {
            "proxy_probability_gap": {
                "message_only_auc": 0.72,
                "full_diff_auc": 0.95,
                "message_only_brier": 0.22,
                "full_diff_brier": 0.06,
            },
            "conversion_metrics": {
                "tier_consistency": 0.51,
                "downgrade_rate_message_only_a_to_full_diff_c": 0.24,
            },
        }
        conclusion = proxy_gap_schema.derive_proxy_conclusion(payload)
        self.assertEqual(
            conclusion["classification"], "not_reliable_for_atomic_filtering"
        )
        self.assertIn("not reliable", conclusion["paper_sentence"])

    def test_proxy_gap_payload_schema_contains_conclusion_and_sections(self) -> None:
        payload = proxy_gap_schema.build_proxy_quality_payload(
            selection_count=10,
            resolved_count=10,
            proxy_probability_gap={
                "message_only_auc": 0.9,
                "full_diff_auc": 0.95,
                "message_only_brier": 0.11,
                "full_diff_brier": 0.08,
                "message_only_logloss": 0.31,
                "full_diff_logloss": 0.22,
            },
            conversion_metrics={
                "tier_consistency": 0.8,
                "downgrade_rate_message_only_a_to_full_diff_c": 0.05,
                "proxy_to_primary_tier_matrix": {"A->A": 5, "A->C": 1},
            },
        )
        self.assertIn("proxy_probability_gap", payload)
        self.assertIn("conversion_metrics", payload)
        self.assertIn("conclusion", payload)
        self.assertIn("paper_sentence", payload["conclusion"])

    def test_proxy_gap_report_markdown_mentions_missing_policy(self) -> None:
        payload = {
            "selection_count": 10,
            "resolved_count": 8,
            "audit_target": 300,
            "proxy_probability_gap": {
                "message_only_auc": 0.9,
                "full_diff_auc": 0.95,
                "message_only_brier": 0.11,
                "full_diff_brier": 0.08,
                "message_only_logloss": 0.31,
                "full_diff_logloss": 0.22,
            },
            "conversion_metrics": {
                "missing_tier_policy": "missing_as_unknown",
                "unknown_rate": 0.25,
                "tier_consistency": 0.8,
                "downgrade_rate_message_only_a_to_full_diff_c": 0.05,
                "observed_full_diff_tier_counts": {"A": 3, "B": 2, "UNKNOWN": 3},
            },
            "feasibility": {
                "expected_target_tier_yield": 120.0,
                "conservative_target_tier_lower_bound": 100.0,
            },
            "conclusion": {
                "classification": "usable_with_risk",
                "reason": "x",
                "paper_sentence": "y",
                "policy_note": "Primary proxy-gap statistics use missing_as_unknown.",
            },
        }
        markdown = proxy_gap_report.build_proxy_gap_markdown(
            payload=payload,
            observed_tier_b=2,
        )
        self.assertIn("Missing-tier policy", markdown)
        self.assertIn("missing_as_unknown", markdown)

    def test_check_input_split_rejects_sha_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            annotated = Path(tmpdir) / "annotated.csv"
            allcommits = Path(tmpdir) / "allcommits.csv"
            fieldnames = ["sha", "commit_message", "type"]
            with annotated.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {"sha": "same", "commit_message": "fix: a", "type": "fix"}
                )
            with allcommits.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {"sha": "same", "commit_message": "fix: b", "type": "fix"}
                )
            with self.assertRaises(RuntimeError):
                runner.check_input_split_disjoint(annotated, allcommits)

    def test_collect_input_split_metadata_reports_repo_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            annotated = Path(tmpdir) / "annotated.csv"
            allcommits = Path(tmpdir) / "allcommits.csv"
            fieldnames = ["sha", "commit_message", "type", "resolved_repo"]
            for path, rows in [
                (
                    annotated,
                    [
                        {
                            "sha": "a1",
                            "commit_message": "fix: a",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
                (
                    allcommits,
                    [
                        {
                            "sha": "b1",
                            "commit_message": "fix: b",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
            ]:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            metadata = runner.collect_input_split_metadata(annotated, allcommits)
            self.assertEqual(metadata["overlap_sha_count"], 0)
            self.assertEqual(metadata["overlap_repo_count"], 1)
            self.assertIn("owner/repo", metadata["overlap_repo_examples"])

    def test_check_input_split_rejects_repo_overlap_under_error_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            annotated = Path(tmpdir) / "annotated.csv"
            allcommits = Path(tmpdir) / "allcommits.csv"
            fieldnames = ["sha", "commit_message", "type", "resolved_repo"]
            for path, rows in [
                (
                    annotated,
                    [
                        {
                            "sha": "a1",
                            "commit_message": "fix: a",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
                (
                    allcommits,
                    [
                        {
                            "sha": "b1",
                            "commit_message": "fix: b",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
            ]:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            with self.assertRaises(RuntimeError):
                runner.check_input_split_disjoint(
                    annotated,
                    allcommits,
                    repo_overlap_policy="error",
                )

    def test_check_input_split_allows_repo_overlap_under_frozen_stats_policy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            annotated = Path(tmpdir) / "annotated.csv"
            allcommits = Path(tmpdir) / "allcommits.csv"
            fieldnames = ["sha", "commit_message", "type", "resolved_repo"]
            for path, rows in [
                (
                    annotated,
                    [
                        {
                            "sha": "a1",
                            "commit_message": "fix: a",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
                (
                    allcommits,
                    [
                        {
                            "sha": "b1",
                            "commit_message": "fix: b",
                            "type": "fix",
                            "resolved_repo": "owner/repo",
                        }
                    ],
                ),
            ]:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            metadata = runner.check_input_split_disjoint(
                annotated,
                allcommits,
                repo_overlap_policy="allow_frozen_stats",
            )
            self.assertEqual(metadata["overlap_repo_count"], 1)
            self.assertEqual(metadata["repo_overlap_policy"], "allow_frozen_stats")

    def test_repo_aware_holdout_indices_are_repo_disjoint(self) -> None:
        labels = [1, 1, 0, 0]
        groups = ["repo_a", "repo_a", "repo_b", "repo_b"]
        split = calibration.stratified_holdout_indices(labels, 0.5, 42)
        self.assertIsNotNone(split)
        repo_split = calibration.repo_aware_holdout_indices(
            labels=labels,
            groups=groups,
            holdout_ratio=0.5,
            random_state=42,
        )
        self.assertIsNotNone(repo_split)
        train_idx, val_idx = repo_split
        train_repos = {groups[i] for i in train_idx}
        val_repos = {groups[i] for i in val_idx}
        self.assertTrue(train_repos.isdisjoint(val_repos))

    def test_repo_aware_cv_splits_are_repo_disjoint(self) -> None:
        labels = [1, 1, 0, 0, 1, 0]
        groups = ["repo_a", "repo_a", "repo_b", "repo_b", "repo_c", "repo_c"]
        split_bundle = calibration.repo_aware_cv_splits(
            labels=labels,
            groups=groups,
            cv_folds=3,
            random_state=42,
        )
        self.assertIsNotNone(split_bundle)
        splits, _ = split_bundle
        for train_idx, val_idx in splits:
            train_repos = {groups[i] for i in train_idx}
            val_repos = {groups[i] for i in val_idx}
            self.assertTrue(train_repos.isdisjoint(val_repos))


if __name__ == "__main__":
    unittest.main()
