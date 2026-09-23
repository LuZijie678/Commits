"""
为 message-only 审计样本生成确定性标注。

用途：
- 对 `tier_b_audit_sample.csv` 进行协议化打标
- 对 message-only 扩充审计候选进行协议化打标

说明：
- 这是单代理协议化审计，不替代独立多人审阅
- 规则旨在复现当前稳定路线使用的同一口径
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


# CSV 字段大小限制，使用系统最大值避免字段截断
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
# 默认审核者名称，用于单代理协议化审计
DEFAULT_REVIEWER = "codex_single_agent_protocol_v2"
# 负面主题模式列表，用于识别多目标 commit（这些模式通常表示多个改进目标）
NEGATIVE_SUBJECT_PATTERNS = [
    "corrections and improvements",
    "cosmetic things",
    "improve plugin and add support to modify babel",
    "more btreemap->vec, opts and subcmds",
]
# 动词正则表达式，用于识别 commit message 中的动作词（辅助判断目标数量）
VERB_RE = re.compile(
    r"\b(add|update|remove|rename|move|switch|implement|support|fix|improve|introduce|enable|disable|migrate|validate)\b"
)


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    参数:
        --input: 输入的审计样本 CSV 文件路径
        --output: 输出的标注结果 CSV 文件路径
        --reviewer: 审核者名称，默认为 DEFAULT_REVIEWER

    返回:
        解析后的命名空间对象
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reviewer", default=DEFAULT_REVIEWER)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    """
    从 CSV 文件加载行数据。

    参数:
        path: CSV 文件路径

    返回:
        行字典列表
    """
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def label_audit_row(row: dict, reviewer: str = DEFAULT_REVIEWER) -> dict:
    """
    对单行审计数据进行确定性标注。

    基于 commit message 内容、文件数量、变更行数等特征，
    按照预设规则判断是否为单一目标（single intent）。

    参数:
        row: 包含 commit 信息的字典
        reviewer: 审核者名称

    返回:
        添加了标注字段的字典
    """
    # 标准化 commit message：合并空白字符以便处理
    message = " ".join(str(row.get("commit_message", "")).split())
    lower = message.lower()
    # 获取文件数量和变更行数（处理可能为空的字段）
    file_count = int(float(row.get("file_count") or row.get("diff_file_count") or 0))
    changed_lines = int(
        float(row.get("changed_lines") or row.get("diff_changed_lines") or 0)
    )
    # 解析 roles 字段并去重，计算不同角色的数量
    roles = [item for item in str(row.get("roles", "")).split(",") if item]
    role_n = len(set(roles))
    # 统计 commit message 中的动词数量（用于辅助判断目标数量）
    verb_count = len(VERB_RE.findall(lower))

    # 默认标签为单目标，高置信度
    label = "1"
    confidence = "0.86"
    note = "single_goal_default"

    # 规则1: 消息中包含 "* " 开头的列表项，表示多目标
    if "* " in str(row.get("commit_message", "")):
        label = "0"
        confidence = "0.94"
        note = "multi_goal_bullet_list"
    # 规则2: 消息包含负面主题模式，表示多目标
    elif any(pattern in lower for pattern in NEGATIVE_SUBJECT_PATTERNS):
        label = "0"
        confidence = "0.84"
        note = "multi_goal_subject_marker"
    # 规则3: 消息包含 "and" 且动词数量>=3，表示多目标
    elif " and " in lower and verb_count >= 3:
        label = "0"
        confidence = "0.76"
        note = "multi_goal_conjoined_actions"
    # 规则4: 文件数<=3 且 角色数<=2 且 变更行数<=80，表示紧凑的单一变更
    elif file_count <= 3 and role_n <= 2 and changed_lines <= 80:
        label = "1"
        confidence = "0.95"
        note = "single_goal_compact_change"
    # 规则5: 文件数<=8 且 角色数<=2，表示内聚的单一变更
    elif file_count <= 8 and role_n <= 2:
        label = "1"
        confidence = "0.90"
        note = "single_goal_cohesive_change"
    # 规则6: 文件数<=20 且 角色数<=3，表示中等范围的单一变更
    elif file_count <= 20 and role_n <= 3:
        label = "1"
        confidence = "0.80"
        note = "single_goal_moderate_scope"
    # 规则7: 其他情况默认为宽泛的单一变更
    else:
        label = "1"
        confidence = "0.68"
        note = "single_goal_broad_scope"

    # 复制原始数据并添加标注字段
    copied = dict(row)
    copied["audit_is_single_intent"] = label
    copied["audit_confidence"] = confidence
    copied["audit_reviewer"] = reviewer
    copied["audit_notes"] = note
    return copied


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    将行数据写入 CSV 文件。

    参数:
        path: 输出文件路径
        rows: 行数据列表
    """
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """
    主函数：对审计样本进行协议化标注。

    流程：
    1. 加载输入的审计样本 CSV 文件
    2. 对每行应用确定性标注规则
    3. 写入标注结果到输出文件
    """
    args = parse_args()
    rows = load_rows(Path(args.input))
    # 对每行进行标注
    labeled_rows = [label_audit_row(row, reviewer=args.reviewer) for row in rows]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, labeled_rows)
    print(f"labeled_rows={len(labeled_rows)}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
