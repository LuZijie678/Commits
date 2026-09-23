import unittest

# 导入标注一致性协议和重叠导出模块
from src.labeling import agreement
from src.labeling import overlap_export


class AnnotationAgreementTest(unittest.TestCase):
    def test_overlap_subset_export_adds_double_annotation_fields(self) -> None:
        # 测试数据：包含不同标签的多个提交行
        rows = [
            {
                "sha": "a1",
                "type": "fix",
                "annotated_type": "fix",
                "is_single_intent": "1",
            },
            {
                "sha": "a2",
                "type": "fix",
                "annotated_type": "fix",
                "is_single_intent": "0",
            },
            {
                "sha": "b1",
                "type": "feat",
                "annotated_type": "feat",
                "is_single_intent": "1",
            },
            {
                "sha": "b2",
                "type": "feat",
                "annotated_type": "feat",
                "is_single_intent": "0",
            },
        ]
        # 按照50%采样率采样，最小样本量为2，使用种子31保证可复现
        sampled = overlap_export.sample_overlap_rows(
            rows=rows,
            sample_ratio=0.5,
            min_sample_size=2,
            seed=31,
        )
        # 构建双标注模板行，应该包含标注��ID、标签、理由和裁决标签字段
        templated = overlap_export.build_overlap_template_rows(sampled)
        self.assertTrue(templated)
        self.assertIn("annotator_id", templated[0])
        self.assertIn("label", templated[0])
        self.assertIn("rationale", templated[0])
        self.assertIn("adjudicated_label", templated[0])

    def test_agreement_report_computes_raw_agreement_kappa_and_confusion(self) -> None:
        # 标注者A的标注结果：4个提交，两个为正(1)，两个为负(0)
        annotator_a = [
            {"sha": "a1", "label": "1"},
            {"sha": "a2", "label": "0"},
            {"sha": "a3", "label": "1"},
            {"sha": "a4", "label": "0"},
        ]
        # 标注者B的标注结果：a1和a2一致，a3标注相反，a4一致
        annotator_b = [
            {"sha": "a1", "label": "1"},
            {"sha": "a2", "label": "0"},
            {"sha": "a3", "label": "0"},
            {"sha": "a4", "label": "0"},
        ]
        # 构建一致性报告，计算原始一致性、Cohen's Kappa和混淆矩阵
        report = agreement.build_agreement_report(annotator_a, annotator_b)
        self.assertEqual(report["shared_sha_count"], 4)
        self.assertAlmostEqual(report["raw_agreement"], 0.75)  # 3/4=0.75
        self.assertIn("1->0", report["confusion_summary"])  # A标注1但B标注0
        self.assertIn("0->0", report["confusion_summary"])  # 两者都标注0
        self.assertIsNotNone(report["cohen_kappa"])


if __name__ == "__main__":
    unittest.main()
