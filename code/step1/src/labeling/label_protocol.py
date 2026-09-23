from __future__ import annotations

from collections import Counter


# 有效的二元标签集合，仅包含 "0" 和 "1" 两种标签
VALID_BINARY_LABELS = {"0", "1"}
# 数据具化时需要添加的标签相关字段列表
# raw_label: 原始标注结果
# adjudicated_label: 仲裁后的标签
# label_conflict_flag: 标签冲突标志
# annotator_id: 标注者ID
MATERIALIZED_LABEL_FIELDS = (
    "raw_label",
    "adjudicated_label",
    "label_conflict_flag",
    "annotator_id",
)


def normalize_binary_label(raw: object) -> str | None:
    """
    将原始标签值规范化为标准的二进制标签字符串。

    参数:
        raw: 原始标签值，可以是任意对象

    返回:
        规范化的标签字符串 ("0" 或 "1")，如果无法规范化则返回 None
    """
    text = str(raw).strip()
    if text in VALID_BINARY_LABELS:
        return text
    return None


def parse_conflict_flag(raw: object) -> bool:
    """
    解析标签冲突标志值。

    参数:
        raw: 原始冲突标志值

    返回:
        布尔值，表示是否存在标签冲突
    """
    text = str(raw).strip().lower()
    return text in {"1", "true", "yes", "y"}


def resolve_label_record(row: dict, *, label_col: str = "is_single_intent") -> dict:
    """
    解析单行记录的标签信息，根据优先级选择最终使用的标签。

    标签优先级: adjudicated_label > raw_label > label_col

    参数:
        row: 包含标签信息的字典
        label_col: 回退标签列名，默认为 "is_single_intent"

    返回:
        包含解析后标签信息的字典
    """
    if not isinstance(row, dict):
        raise ValueError("label resolution requires a row dict")
    if (
        "adjudicated_label" not in row
        and "raw_label" not in row
        and label_col not in row
    ):
        raise ValueError(
            f"row is missing label fields: expected one of `adjudicated_label`, `raw_label`, `{label_col}`"
        )

    # 尝试从不同字段获取标签值
    adjudicated_label = normalize_binary_label(row.get("adjudicated_label"))
    raw_label = normalize_binary_label(row.get("raw_label"))
    fallback_label = normalize_binary_label(row.get(label_col))

    # 根据优先级选择最终使用的标签及其来源
    selected_label = None
    selected_source = ""
    if adjudicated_label is not None:
        selected_label = adjudicated_label
        selected_source = "adjudicated_label"
    elif raw_label is not None:
        selected_label = raw_label
        selected_source = "raw_label"
    elif fallback_label is not None:
        selected_label = fallback_label
        selected_source = label_col

    # 解析冲突标志，并在存在冲突时自动标记
    label_conflict_flag = parse_conflict_flag(row.get("label_conflict_flag"))
    # 如果同时存在 adjudicated_label 和 raw_label 且不一致，标记冲突
    if (
        adjudicated_label is not None
        and raw_label is not None
        and adjudicated_label != raw_label
    ):
        label_conflict_flag = True

    return {
        "selected_label": selected_label,
        "selected_label_int": int(selected_label)
        if selected_label is not None
        else None,
        "selected_source": selected_source,
        "raw_label": raw_label if raw_label is not None else fallback_label,
        "adjudicated_label": adjudicated_label,
        "label_source": str(row.get("label_source", "")).strip(),
        "annotator_id": str(
            row.get("annotator_id") or row.get("audit_reviewer") or ""
        ).strip(),
        "label_conflict_flag": bool(label_conflict_flag),
    }


def build_label_usage_summary(
    rows: list[dict], *, label_col: str = "is_single_intent"
) -> dict:
    """
    构建标签使用情况汇总统计。

    统计内容包括：
    - 总标注行数、缺失标签行数
    - 各标签来源的计数
    - 仲裁标签占比、回退标签占比
    - 标签冲突行数

    参数:
        rows: 行数据列表
        label_col: 回退标签列名

    返回:
        包含各项统计指标的字典
    """
    source_counts: Counter = Counter()  # 记录各标签来源的计数
    label_source_counts: Counter = Counter()  # 记录 label_source 字段的计数
    labeled_rows = 0  # 有效标注的行数
    conflict_rows = 0  # 存在标签冲突的行数
    missing_rows = 0  # 缺少标签的行数
    for row in rows:
        resolved = resolve_label_record(row, label_col=label_col)
        if resolved["selected_label"] is None:
            missing_rows += 1
            continue
        labeled_rows += 1
        source_counts[str(resolved["selected_source"])] += 1
        if resolved["label_source"]:
            label_source_counts[str(resolved["label_source"])] += 1
        if resolved["label_conflict_flag"]:
            conflict_rows += 1
    # 回退标签数 = 标注行数 - 使用仲裁标签的行数
    fallback_count = labeled_rows - int(source_counts.get("adjudicated_label", 0))
    return {
        "label_col": label_col,
        "labeled_rows": labeled_rows,
        "missing_label_rows": missing_rows,
        "source_counts": dict(source_counts),
        "label_source_counts": dict(label_source_counts),
        "adjudicated_ratio": (
            source_counts.get("adjudicated_label", 0) / labeled_rows
            if labeled_rows
            else None
        ),
        "fallback_ratio": (fallback_count / labeled_rows if labeled_rows else None),
        "conflict_rows": conflict_rows,
    }


def materialize_label_view_rows(
    rows: list[dict], *, label_col: str = "is_single_intent"
) -> list[dict]:
    """
    将标注数据集具化为标准化的视图格式。

    为每行添加统一的标签字段：
    - raw_label: 原始标注结果
    - adjudicated_label: 仲裁后的标签
    - label_conflict_flag: 标签冲突标志
    - annotator_id: 标注者ID
    - label_source: 标签来源说明

    参数:
        rows: 原始行数据列表
        label_col: 回退标签列名

    返回:
        具化后的行数据列表
    """
    materialized_rows: list[dict] = []
    for row in rows:
        copied = dict(row)
        resolved = resolve_label_record(copied, label_col=label_col)
        raw_label = normalize_binary_label(copied.get("raw_label"))
        # 如果 raw_label 为空，尝试从 fallback 列获取
        if raw_label is None:
            raw_label = normalize_binary_label(copied.get(label_col))
        adjudicated_label = normalize_binary_label(copied.get("adjudicated_label"))
        # 填充标准化字段，空值转为空字符串
        copied["raw_label"] = raw_label or ""
        copied["adjudicated_label"] = adjudicated_label or ""
        copied["label_conflict_flag"] = "1" if resolved["label_conflict_flag"] else "0"
        copied["annotator_id"] = resolved["annotator_id"]
        # 确定 label_source：如果未设置则根据现有字段推断来源
        if not str(copied.get("label_source", "")).strip():
            if adjudicated_label is not None:
                copied["label_source"] = "adjudicated_label"
            elif raw_label is not None and "raw_label" in row:
                copied["label_source"] = "raw_label"
            elif raw_label is not None:
                copied["label_source"] = "legacy_single_label"
            else:
                copied["label_source"] = ""
        materialized_rows.append(copied)
    return materialized_rows
