import tempfile
import unittest
from pathlib import Path

# 导入标注分割协议模块，用于生成分层标注数据的分割计划
import src.data_splitting.annotated_split_protocol as split_protocol


class AnnotatedSplitProtocolTest(unittest.TestCase):
    def _rows(self) -> list[dict]:
        # 生成测试数据：10个仓库，每个仓库2条记录(1正1负)
        rows: list[dict] = []
        for repo_idx in range(1, 11):
            repo = f"owner/repo_{repo_idx}"
            # 正样本：fix类型的单意图提交
            rows.append(
                {
                    "sha": f"{repo_idx:02d}a",
                    "repo": repo,
                    "resolved_repo": repo,
                    "type": "fix",
                    "is_single_intent": "1",
                }
            )
            # 负样本：feat类型的非单意图提交
            rows.append(
                {
                    "sha": f"{repo_idx:02d}b",
                    "repo": repo,
                    "resolved_repo": repo,
                    "type": "feat",
                    "is_single_intent": "0",
                }
            )
        return rows

    def _constraints(self) -> tuple[dict, dict, dict, dict]:
        # 定义分割约束条件：每个split至少需要2条记录、1正1负、1个仓库
        min_total = {name: 2 for name in split_protocol.ANNOTATED_SPLIT_ORDER}
        min_positive = {name: 1 for name in split_protocol.ANNOTATED_SPLIT_ORDER}
        min_negative = {name: 1 for name in split_protocol.ANNOTATED_SPLIT_ORDER}
        min_repo = {name: 1 for name in split_protocol.ANNOTATED_SPLIT_ORDER}
        return min_total, min_positive, min_negative, min_repo

    def test_build_annotated_split_plan_is_sha_disjoint(self) -> None:
        # 测试：构建的分割计划中所有split的SHA应该互不重叠
        rows = self._rows()
        min_total, min_positive, min_negative, min_repo = self._constraints()
        plan = split_protocol.build_annotated_split_plan(
            rows=rows,
            seed=31,  # 使用种子31保证可复现
            min_total_by_split=min_total,
            min_positive_by_split=min_positive,
            min_negative_by_split=min_negative,
            min_repo_by_split=min_repo,
        )
        # 验证所有分割SHA无交集
        self.assertTrue(split_protocol.all_splits_sha_disjoint(plan))
        # 验证所有分割的记录数之和等于输入记录数
        self.assertEqual(
            sum(
                plan["splits"][name]["row_count"]
                for name in split_protocol.ANNOTATED_SPLIT_ORDER
            ),
            len(rows),
        )

    def test_build_annotated_split_plan_records_repo_summary(self) -> None:
        # 测试：分割计划应该记录每个split的仓库统计信息
        rows = self._rows()
        min_total, min_positive, min_negative, min_repo = self._constraints()
        plan = split_protocol.build_annotated_split_plan(
            rows=rows,
            seed=31,
            min_total_by_split=min_total,
            min_positive_by_split=min_positive,
            min_negative_by_split=min_negative,
            min_repo_by_split=min_repo,
        )
        summary = split_protocol.summarize_split_plan(plan)
        self.assertEqual(summary["seed"], 31)
        self.assertIn("protocol", summary["splits"])
        self.assertIn("repo_count", summary["splits"]["protocol"])
        self.assertIn("repos", summary["splits"]["protocol"])
        self.assertTrue(summary["is_sha_disjoint"])

    def test_assert_rows_match_split_raises_on_mismatch(self) -> None:
        # 测试：当行的SHA不在指定的split中时应该抛出异常
        with self.assertRaises(RuntimeError):
            split_protocol.assert_rows_match_split(
                rows=[{"sha": "outside"}],
                split_sha_set={"inside"},
                split_name="protocol",
                context="protocol derivation",
            )

    def test_materialize_split_rows_returns_only_assigned_rows(self) -> None:
        # 测试：根据分割计划返回指定split的所有行
        rows = self._rows()
        min_total, min_positive, min_negative, min_repo = self._constraints()
        plan = split_protocol.build_annotated_split_plan(
            rows=rows,
            seed=31,
            min_total_by_split=min_total,
            min_positive_by_split=min_positive,
            min_negative_by_split=min_negative,
            min_repo_by_split=min_repo,
        )
        evaluation_rows = split_protocol.materialize_split_rows(
            rows=rows,
            plan=plan,
            split_name="evaluation",
        )
        expected = set(plan["splits"]["evaluation"]["shas"])
        self.assertEqual({row["sha"] for row in evaluation_rows}, expected)

    def test_write_split_artifacts_persists_csv_and_sha_lists(self) -> None:
        # 测试：将分割计划写入文件，包括JSON计划和CSV文件
        rows = self._rows()
        min_total, min_positive, min_negative, min_repo = self._constraints()
        plan = split_protocol.build_annotated_split_plan(
            rows=rows,
            seed=31,
            min_total_by_split=min_total,
            min_positive_by_split=min_positive,
            min_negative_by_split=min_negative,
            min_repo_by_split=min_repo,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_paths = split_protocol.write_split_artifacts(
                base_dir=Path(tmpdir),
                rows=rows,
                plan=plan,
            )
            # 验证JSON计划文件存在
            self.assertTrue(Path(artifact_paths["plan_json"]).exists())
            # 验证每个split的CSV文件存在
            self.assertTrue(Path(artifact_paths["split_csvs"]["protocol"]).exists())
            # 验证每个split的SHA列表文件存在
            self.assertTrue(Path(artifact_paths["split_sha_csvs"]["protocol"]).exists())


if __name__ == "__main__":
    unittest.main()
