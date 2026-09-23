from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


# CSV 字段大小限制，使用系统最大值
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
# 有效的标签集合，仅包含 "0" 和 "1"
VALID_LABELS = {"0", "1"}


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    参数:
        --annotator-a-csv: 标注者 A 的 CSV 文件路径
        --annotator-b-csv: 标注者 B 的 CSV 文件路径
        --output-json: 输出 JSON 报告的路径
        --output-md: 输出 Markdown 报告的路径

    返回:
        解析后的命名空间对象
    """
    parser = argparse.ArgumentParser(
        description="Compute raw agreement, Cohen's kappa, and confusion summary for two annotators."
    )
    parser.add_argument("--annotator-a-csv", required=True)
    parser.add_argument("--annotator-b-csv", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
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


def aligned_labels(
    rows_a: list[dict], rows_b: list[dict]
) -> tuple[list[str], list[str], list[str]]:
    """
    对齐两个标注者对同一批 commit 的标注结果。

    基于 sha 字段匹配，筛选出两个标注者都有标注的共同 commit，
    并提取对应的标签值。

    参数:
        rows_a: 标注者 A 的行数据
        rows_b: 标注者 B 的行数据

    返回:
        (aligned_shas, labels_a, labels_b) 元组
    """
    # 构建按 sha 索引的字典，用于快速查找
    by_sha_a = {
        str(row.get("sha", "")).strip(): row
        for row in rows_a
        if str(row.get("sha", "")).strip()
    }
    by_sha_b = {
        str(row.get("sha", "")).strip(): row
        for row in rows_b
        if str(row.get("sha", "")).strip()
    }
    # 找出两个标注者都标注了的 commit
    shared = sorted(set(by_sha_a) & set(by_sha_b))
    labels_a: list[str] = []
    labels_b: list[str] = []
    aligned_shas: list[str] = []
    for sha in shared:
        # 尝试从 label 或 audit_is_single_intent 字段获取标签
        label_a = str(
            by_sha_a[sha].get("label")
            or by_sha_a[sha].get("audit_is_single_intent")
            or ""
        ).strip()
        label_b = str(
            by_sha_b[sha].get("label")
            or by_sha_b[sha].get("audit_is_single_intent")
            or ""
        ).strip()
        # 只保留有效标签的记录
        if label_a in VALID_LABELS and label_b in VALID_LABELS:
            labels_a.append(label_a)
            labels_b.append(label_b)
            aligned_shas.append(sha)
    return aligned_shas, labels_a, labels_b


def raw_agreement(labels_a: list[str], labels_b: list[str]) -> float | None:
    """
    计算两个标注者之间的原始一致率。

    原始一致率 = 一致的标注数 / 总标注数

    参数:
        labels_a: 标注者 A 的标签列表
        labels_b: 标注者 B 的标签列表

    返回:
        原始一致率（0-1 之间的浮点数），如果输入无效则返回 None
    """
    if not labels_a or len(labels_a) != len(labels_b):
        return None
    same = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    return same / len(labels_a)


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """
    计算 Cohen's Kappa 系数，用于衡量两个标注者之间的一致性。

    Cohen's Kappa 考虑了随机一致的影响，比原始一致率更可靠。
    公式: κ = (Po - Pe) / (1 - Pe)
    其中 Po 是观察一致率，Pe 是期望随机一致率。

    参数:
        labels_a: 标注者 A 的标签列表
        labels_b: 标注者 B 的标签列表

    返回:
        Kappa 系数（-1 到 1 之间的浮点数），如果输入无效则返回 None
    """
    if not labels_a or len(labels_a) != len(labels_b):
        return None
    observed = raw_agreement(labels_a, labels_b)
    if observed is None:
        return None
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    total = len(labels_a)
    expected = 0.0
    # 计算期望随机一致率（各标签类别的边际概率乘积之和）
    for label in VALID_LABELS:
        expected += (counts_a[label] / total) * (counts_b[label] / total)
    # 如果期望一致率为 1（所有标注完全一致），返回 1.0
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def confusion_summary(labels_a: list[str], labels_b: list[str]) -> dict[str, int]:
    """
    生成混淆矩阵汇总，表示两个标注者标注结果的对应关系。

    混淆矩阵格式: "A->B" 表示标注者 A 标为 A，标注者 B 标为 B

    参数:
        labels_a: 标注者 A 的标签列表
        labels_b: 标注者 B 的标签列表

    返回:
        混淆矩阵字典，键为 "A->B" 格式，值为计数
    """
    matrix = Counter()
    for a, b in zip(labels_a, labels_b):
        matrix[f"{a}->{b}"] += 1
    return dict(matrix)


def build_agreement_report(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """
    构建完整的标注一致性报告。

    报告包含：
    - 共同标注的 commit 数量
    - 原始一致率
    - Cohen's Kappa 系数
    - 混淆矩阵汇总
    - 仲裁覆盖率（有多少 commit 已有仲裁标签）

    参数:
        rows_a: 标注者 A 的行数据
        rows_b: 标注者 B 的行数据

    返回:
        包含各项指标的字典
    """
    shas, labels_a, labels_b = aligned_labels(rows_a, rows_b)
    shared_by_sha = {
        str(row.get("sha", "")).strip(): row
        for row in rows_a + rows_b
        if str(row.get("sha", "")).strip()
    }
    # 统计已有仲裁标签的 commit 数量
    adjudicated = sum(
        1
        for sha in shas
        if str(shared_by_sha.get(sha, {}).get("adjudicated_label", "")).strip()
        in VALID_LABELS
    )
    return {
        "shared_sha_count": len(shas),
        "raw_agreement": raw_agreement(labels_a, labels_b),
        "cohen_kappa": cohen_kappa(labels_a, labels_b),
        "confusion_summary": confusion_summary(labels_a, labels_b),
        "adjudication_coverage": (adjudicated / len(shas)) if shas else None,
    }


def write_json(path: Path, payload: dict) -> None:
    """
    将报告数据写入 JSON 文件。

    参数:
        path: 输出文件路径
        payload: 要写入的字典数据
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, payload: dict) -> None:
    """
    将报告数据写入 Markdown 格式文件。

    参数:
        path: 输出文件路径
        payload: 包含报告数据的字典
    """
    lines = [
        "# Annotation Agreement Report",
        "",
        f"- Shared labeled rows: `{payload['shared_sha_count']}`",
        f"- Raw agreement: `{payload['raw_agreement']}`",
        f"- Cohen's kappa: `{payload['cohen_kappa']}`",
        f"- Adjudication coverage: `{payload['adjudication_coverage']}`",
        "",
        "## Confusion Summary",
        "",
    ]
    for key, value in sorted((payload.get("confusion_summary") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """
    主函数：计算并输出两个标注者之间的一致性报告。

    流程：
    1. 加载两个标注者的 CSV 文件
    2. 计算一致性指标
    3. 输出 JSON 和 Markdown 格式的报告
    """
    args = parse_args()
    rows_a = load_rows(Path(args.annotator_a_csv))
    rows_b = load_rows(Path(args.annotator_b_csv))
    payload = build_agreement_report(rows_a, rows_b)
    write_json(Path(args.output_json), payload)
    write_markdown(Path(args.output_md), payload)
    print(f"shared_sha_count={payload['shared_sha_count']}")
    print(f"cohen_kappa={payload['cohen_kappa']}")


if __name__ == "__main__":
    main()
