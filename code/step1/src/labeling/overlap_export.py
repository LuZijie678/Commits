from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

from src.labeling import label_protocol


# CSV 字段大小限制，使用系统最大值避免字段截断
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
# 默认采样比例：从数据集中抽取 15% 用于双标注
DEFAULT_SAMPLE_RATIO = 0.15
# 默认最小样本数量：确保双标注至少有 50 条样本
DEFAULT_MIN_SAMPLE_SIZE = 50
# 随机种子：确保分层抽样结果可复现
DEFAULT_RANDOM_SEED = 31


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    参数:
        --input: 输入的标注数据集 CSV 文件路径
        --output: 输出的重叠样本 CSV 文件路径
        --sample-ratio: 采样比例，默认为 0.15 (15%)
        --min-sample-size: 最小样本数量，默认为 50
        --seed: 随机种子，默认为 31

    返回:
        解析后的命名空间对象
    """
    parser = argparse.ArgumentParser(
        description="Export a stratified overlap subset for double annotation."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-ratio", type=float, default=DEFAULT_SAMPLE_RATIO)
    parser.add_argument("--min-sample-size", type=int, default=DEFAULT_MIN_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
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


def sample_overlap_rows(
    *,
    rows: list[dict],
    sample_ratio: float,
    min_sample_size: int,
    seed: int,
) -> list[dict]:
    """
    分层抽样生成重叠样本集。

    按 (type, is_single_intent) 分层，在每层内按比例抽取样本。
    如果某层样本不足，从剩余未抽取的样本中补充。

    参数:
        rows: 原始行数据列表
        sample_ratio: 采样比例
        min_sample_size: 最小样本数量
        seed: 随机种子

    返回:
        抽样后的行数据列表
    """
    # 计算目标样本数量（取最大值）
    target_size = max(
        int(min_sample_size), int(math.ceil(len(rows) * float(sample_ratio)))
    )
    # 按分层键 (type, label) 分组
    by_stratum: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("annotated_type") or row.get("type") or "").strip(),
            str(row.get("is_single_intent", "")).strip(),
        )
        by_stratum[key].append(dict(row))
    rng = random.Random(int(seed))
    sampled: list[dict] = []
    # 按分层键排序，确保结果可复现
    for key in sorted(by_stratum):
        bucket = list(by_stratum[key])
        rng.shuffle(bucket)
        # 计算该层的配额：按该层占比分配目标数量
        quota = max(1, int(math.floor(target_size * (len(bucket) / max(1, len(rows))))))
        sampled.extend(bucket[: min(quota, len(bucket))])
    # 如果样本不足，从剩余数据中补充
    if len(sampled) < target_size:
        seen = {str(row.get("sha", "")).strip() for row in sampled}
        remainder = [
            dict(row) for row in rows if str(row.get("sha", "")).strip() not in seen
        ]
        rng.shuffle(remainder)
        sampled.extend(remainder[: max(0, target_size - len(sampled))])
    return sampled[:target_size]


def build_overlap_template_rows(rows: list[dict]) -> list[dict]:
    """
    构建双标注模板行数据。

    为每行添加双标注所需的字段，并清空需要标注的字段。

    参数:
        rows: 行数据列表

    返回:
        模板化后的行数据列表
    """
    templated: list[dict] = []
    for row in rows:
        copied = dict(row)
        # 添加标注者相关字段
        copied["annotator_id"] = ""
        copied["raw_label"] = (
            str(row.get("raw_label", "")).strip()
            or str(row.get("is_single_intent", "")).strip()
        )
        copied["label"] = ""
        copied["rationale"] = ""
        # 保留已有信息，清空待仲裁字段
        copied["adjudicated_label"] = ""
        copied["label_source"] = str(row.get("label_source", "")).strip()
        copied["label_conflict_flag"] = (
            "1"
            if label_protocol.parse_conflict_flag(row.get("label_conflict_flag"))
            else "0"
        )
        copied["adjudicator_id"] = ""
        copied["adjudication_note"] = ""
        templated.append(copied)
    return templated


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    将行数据写入 CSV 文件。

    参数:
        path: 输出文件路径
        rows: 行数据列表
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """
    主函数：导出分层重叠样本用于双标注。

    流程：
    1. 加载标注数据集
    2. 分层抽样生成重叠样本
    3. 构建双标注模板
    4. 写入输出文件
    """
    args = parse_args()
    # 加载标注数据集
    rows = load_rows(Path(args.input))
    # 分层抽样：确保各类型和标签组合都有代表性的样本
    sampled = sample_overlap_rows(
        rows=rows,
        sample_ratio=args.sample_ratio,
        min_sample_size=args.min_sample_size,
        seed=args.seed,
    )
    # 构建模板：添加双标注所需的空字段
    templated = build_overlap_template_rows(sampled)
    output_path = Path(args.output)
    write_csv(output_path, templated)
    # 打印输出信息
    print(f"overlap_rows={len(templated)}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
