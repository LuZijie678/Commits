import unittest

from src.analysis import strategy_compare


class StrategyCompareTest(unittest.TestCase):
    def test_model_rule_refilter_selection_logic(self) -> None:
        scored_rows = [
            {
                "sha": "a",
                "model_prob": 0.95,
                "tau_a": 0.90,
                "tau_b": 0.80,
                "model_tier": "A",
                "rule_label": 1,
                "rule_weight": 1.0,
            },
            {
                "sha": "b",
                "model_prob": 0.94,
                "tau_a": 0.90,
                "tau_b": 0.80,
                "model_tier": "A",
                "rule_label": 0,
                "rule_weight": 0.0,
            },
            {
                "sha": "c",
                "model_prob": 0.30,
                "tau_a": 0.90,
                "tau_b": 0.80,
                "model_tier": "C",
                "rule_label": 1,
                "rule_weight": 1.0,
            },
        ]
        selected = strategy_compare.apply_selection_strategy(
            scored_rows=scored_rows,
            strategy="model_rule_refilter",
            target_count=0,
        )
        by_sha = {row["sha"]: row for row in selected}
        self.assertEqual(by_sha["a"]["is_selected"], "1")
        self.assertEqual(by_sha["a"]["passed_rule_refilter"], "true")
        self.assertEqual(by_sha["a"]["conservative_tier"], "A")
        self.assertEqual(by_sha["b"]["is_selected"], "0")
        self.assertEqual(by_sha["b"]["passed_rule_refilter"], "false")
        self.assertEqual(
            by_sha["b"]["selection_reason"],
            "model_tier_a_but_rule_not_positive",
        )
        self.assertEqual(by_sha["c"]["is_selected"], "0")
        self.assertEqual(by_sha["c"]["conservative_tier"], "")

    def test_source_confidence_uses_rule_weight_when_available(self) -> None:
        self.assertAlmostEqual(
            strategy_compare.compute_source_confidence(0.9, 0.8), 0.72
        )
        self.assertAlmostEqual(
            strategy_compare.compute_source_confidence(0.9, None), 0.9
        )

    def test_strategy_metrics(self) -> None:
        label_by_sha = {
            "a": 1,
            "b": 0,
            "c": 1,
            "d": 0,
        }
        metrics = strategy_compare.compute_strategy_metrics(
            selected_shas={"a", "b"},
            label_by_sha=label_by_sha,
        )
        self.assertEqual(metrics["selected_count"], 2)
        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 0.5)
        self.assertAlmostEqual(metrics["f1"], 0.5)
        self.assertAlmostEqual(metrics["estimated_noise_rate"], 0.5)
        self.assertEqual(metrics["evaluation_metric_status"], "computed_from_overlap")

    def test_strategy_metrics_reports_strict_disjoint_not_computable(self) -> None:
        label_by_sha = {
            "a": 1,
            "b": 0,
        }
        metrics = strategy_compare.compute_strategy_metrics(
            selected_shas={"x", "y"},
            label_by_sha=label_by_sha,
        )
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])
        self.assertEqual(
            metrics["evaluation_metric_status"],
            "not_directly_computable_strict_disjoint",
        )
        self.assertIn("SHA-disjoint", metrics["evaluation_metric_note"])

    def test_conservative_source_rows_have_required_fields(self) -> None:
        rows = [
            {
                "sha": "a",
                "resolved_repo": "owner/repo",
                "commit_url": "https://example/a",
                "type": "fix",
                "subject": "fix: test",
                "commit_message": "fix: test",
                "git_diff": "diff --git ...",
                "model_prob": 0.91,
                "model_tier": "A",
                "tau_a": 0.90,
                "tau_b": 0.80,
                "rule_label": 1,
                "rule_weight": 1.0,
                "passed_rule_refilter": "true",
                "conservative_tier": "A",
                "selection_strategy": "model_rule_refilter",
                "selection_reason": "model_tier_a_and_rule_positive",
                "is_selected": "1",
            }
        ]
        exported = strategy_compare.build_conservative_source_rows(rows)
        self.assertEqual(len(exported), 1)
        required = {
            "sha",
            "repo",
            "commit_url",
            "type",
            "subject",
            "message",
            "git_diff",
            "model_prob",
            "model_tier",
            "tau_a",
            "tau_b",
            "rule_label",
            "rule_weight",
            "passed_rule_refilter",
            "conservative_tier",
            "selection_strategy",
            "selection_reason",
            "source_confidence",
        }
        self.assertTrue(required.issubset(set(exported[0].keys())))

    def test_proxy_role_summary_missing_file(self) -> None:
        payload = strategy_compare.build_proxy_role_summary(None)
        self.assertEqual(payload["proxy_role"], "recall_prefilter_only")
        self.assertTrue(payload["proxy_metrics_missing"])
        self.assertFalse(payload["proxy_high_confidence_warning"])

    def test_proxy_role_summary_reads_conversion_metrics(self) -> None:
        payload = strategy_compare.build_proxy_role_summary(
            {
                "conversion_metrics": {
                    "tier_consistency": 0.62,
                    "downgrade_rate_message_only_a_to_full_diff_c": 0.49,
                }
            }
        )
        self.assertAlmostEqual(payload["proxy_to_full_diff_agreement"], 0.62)
        self.assertAlmostEqual(payload["proxy_a_to_full_diff_c_rate"], 0.49)
        self.assertTrue(payload["proxy_high_confidence_warning"])


if __name__ == "__main__":
    unittest.main()
