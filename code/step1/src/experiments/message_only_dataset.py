"""
从基础标注集与已标注的 message-only 审计集组装扩充标注集。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from src.pipeline import atomic_mining as miner


CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制，避免大字段导致解析错误
DEFAULT_LABEL_SOURCE = "diff_audit_v1_message_only_expansion_codex"  # 默认标签来源标识


def parse_args() -> argparse.Namespace:
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotated", required=True)  # 基础标注集文件路径
    parser.add_argument(
        "--audit-labeled", required=True
    )  # 审计标签集文件路径（message-only审计结果）
    parser.add_argument("--output", required=True)  # 输出文件路径
    parser.add_argument("--report-json", default="")  # 可选的JSON报告输出路径
    parser.add_argument("--label-source", default=DEFAULT_LABEL_SOURCE)  # 标签来源标识
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    # 设置CSV字段大小限制
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并读取为字典列表
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def merge_expanded_dataset(
    *,
    annotated_rows: list[dict],
    audit_rows: list[dict],
    label_source: str,
) -> list[dict]:
    # 构建已有SHA集合用于去重
    existing = {str(row.get("sha", "")).strip() for row in annotated_rows}
    # 从基础标注集开始
    merged = list(annotated_rows)
    # 遍历审计行，合并新行
    for row in audit_rows:
        sha = str(row.get("sha", "")).strip()
        # 跳过空SHA或已存在的SHA
        if not sha or sha in existing:
            continue
        # 检查git_diff是否存在
        git_diff = str(row.get("git_diff", "")).strip()
        if not git_diff:
            continue
        # 解析diff特征，确保文件数和变更行数有效
        diff_features = miner.parse_diff(git_diff)
        if (
            float(diff_features.get("file_count", 0.0)) <= 0
            or float(diff_features.get("changed_lines", 0.0)) <= 0
        ):
            continue
        # 添加审计行到合并结果
        merged.append(
            {
                "sha": sha,
                "repo": row.get("repo", ""),
                "resolved_repo": row.get("resolved_repo", row.get("repo", "")),
                "commit_url": row.get("commit_url", ""),
                "type": row.get("type", ""),
                "annotated_type": row.get("type", ""),
                "commit_message": row.get("commit_message", ""),
                "masked_commit_message": row.get(
                    "masked_commit_message", row.get("commit_message", "")
                ),
                "git_diff": git_diff,
                "resolution_status": row.get("resolution_status", "resolved_local"),
                "repo_candidate_count": row.get("repo_candidate_count", ""),
                "candidate_repos": row.get("candidate_repos", ""),
                "diff_line_count": row.get(
                    "diff_line_count", row.get("diff_changed_lines", "")
                ),
                "diff_char_count": row.get("diff_char_count", str(len(git_diff))),
                "diff_error": row.get("diff_error", ""),
                "is_single_intent": row.get("audit_is_single_intent", ""),
                "raw_label": row.get("audit_is_single_intent", ""),
                "adjudicated_label": row.get("adjudicated_label", ""),
                "label_conflict_flag": row.get("label_conflict_flag", "0"),
                "annotator_id": row.get("annotator_id", row.get("audit_reviewer", "")),
                "audit_confidence": row.get("audit_confidence", ""),
                "audit_reviewer": row.get("audit_reviewer", ""),
                "audit_notes": row.get("audit_notes", ""),
                "label_source": label_source,
            }
        )
        existing.add(sha)
    return merged


def write_csv(path: Path, rows: list[dict]) -> None:
    # 空行时写入空文件
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # 写入CSV文件（使用第一行的键作为字段顺序）
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    # 解析命令行参数
    args = parse_args()
    # 加载基础标注集
    annotated_rows = load_rows(Path(args.annotated))
    # 加载审计标签集
    audit_rows = load_rows(Path(args.audit_labeled))
    # 合并两个数据集
    merged_rows = merge_expanded_dataset(
        annotated_rows=annotated_rows,
        audit_rows=audit_rows,
        label_source=args.label_source,
    )
    # 创建输出目录并写入文件
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, merged_rows)
    # 如果指定了报告JSON路径，写入统计信息
    if args.report_json:
        report_path = Path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "annotated_rows": len(annotated_rows),
                    "audit_rows": len(audit_rows),
                    "merged_rows": len(merged_rows),
                    "appended_rows": len(merged_rows) - len(annotated_rows),
                    "label_source": args.label_source,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    # 打印摘要信息
    print(f"merged_rows={len(merged_rows)}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
