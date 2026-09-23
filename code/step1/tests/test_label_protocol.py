import unittest

# 导入标签协议模块，用于解析和管理标签记录
from src.labeling import label_protocol


class LabelProtocolTest(unittest.TestCase):
    def test_resolve_label_record_prefers_adjudicated_label(self) -> None:
        # 测试：当存在裁决标签时，优先使用裁决标签而不是原始标签
        # is_single_intent=0, raw_label=0, 但adjudicated_label=1，存在冲突
        resolved = label_protocol.resolve_label_record(
            {
                "is_single_intent": "0",
                "raw_label": "0",
                "adjudicated_label": "1",
                "label_source": "double_annotation",
            }
        )
        self.assertEqual(resolved["selected_label_int"], 1)  # 应选择裁决标签1
        self.assertEqual(resolved["selected_source"], "adjudicated_label")
        self.assertTrue(resolved["label_conflict_flag"])  # 标记存在标签冲突

    def test_resolve_label_record_falls_back_to_raw_then_legacy(self) -> None:
        # 测试标签解析优先级：裁决标签 > raw_label > is_single_intent
        # 场景1：有raw_label字段时使用它
        raw_first = label_protocol.resolve_label_record(
            {"raw_label": "1", "is_single_intent": "0"}
        )
        # 场景2：只有is_single_intent字段时作为后备
        legacy = label_protocol.resolve_label_record({"is_single_intent": "0"})
        self.assertEqual(raw_first["selected_source"], "raw_label")
        self.assertEqual(raw_first["selected_label_int"], 1)
        self.assertEqual(legacy["selected_source"], "is_single_intent")
        self.assertEqual(legacy["selected_label_int"], 0)

    def test_build_label_usage_summary_reports_fallback_ratio(self) -> None:
        # 测试构建标签使用摘要，统计不同来源标签的比例
        # 3条记录：1条有裁决标签，1条有raw_label，1条只有is_single_intent
        summary = label_protocol.build_label_usage_summary(
            [
                {"adjudicated_label": "1", "raw_label": "0"},
                {"raw_label": "1"},
                {"is_single_intent": "0"},
            ]
        )
        self.assertEqual(summary["labeled_rows"], 3)
        self.assertAlmostEqual(summary["adjudicated_ratio"], 1.0 / 3.0)  # 1/3有裁决标签
        self.assertAlmostEqual(summary["fallback_ratio"], 2.0 / 3.0)  # 2/3使用后备

    def test_resolve_label_record_raises_when_no_supported_fields(self) -> None:
        # 测试：当没有支持的标签字段时应抛出异常
        with self.assertRaises(ValueError):
            label_protocol.resolve_label_record({"sha": "x"})

    def test_materialize_label_view_rows_populates_main_view_fields(self) -> None:
        # 测试：填充标签视图的主字段，将旧格式转换为标准视图格式
        rows = [
            {
                "sha": "abc",
                "is_single_intent": "1",
                "audit_reviewer": "ann1",
                "label_source": "",
            }
        ]
        materialized = label_protocol.materialize_label_view_rows(rows)
        self.assertEqual(len(materialized), 1)
        self.assertEqual(materialized[0]["raw_label"], "1")  # 从is_single_intent复制
        self.assertEqual(materialized[0]["adjudicated_label"], "")  # 空值
        self.assertEqual(materialized[0]["label_conflict_flag"], "0")  # 无冲突
        self.assertEqual(materialized[0]["annotator_id"], "ann1")  # 保留审核者
        self.assertEqual(
            materialized[0]["label_source"], "legacy_single_label"
        )  # 标记为旧格式


if __name__ == "__main__":
    unittest.main()
