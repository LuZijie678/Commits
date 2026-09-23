from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

from src.labeling import label_protocol


# CSV 字段大小限制，使用系统最大值避免字段截断
CSV_FIELD_SIZE_LIMIT = 2**31 - 1


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    参数:
        --input: 输入的标注数据集 CSV 文件路径
        --output: 输出的具化数据集 CSV 文件路径
        --report-json: 输出报告的 JSON 文件路径
        --label-col: 标签列名，默认为 "is_single_intent"

    返回:
        解析后的命名空间对象
    """
    parser = argparse.ArgumentParser(
        description="Materialize an annotated dataset into a main adjudicated label view."
    )
    parser.add_argument(
        "--input",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    parser.add_argument(
        "--output",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    parser.add_argument(
        "--report-json",
        default="../../datasets/step1/manifest/annotated_dataset_materialization_report.json",
    )
    parser.add_argument("--label-col", default="is_single_intent")
    return parser.parse_args()


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    """
    从 CSV 文件加载字段名和行数据。

    参数:
        path: CSV 文件路径

    返回:
        (字段名列表, 行字典列表) 元组
    """
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def build_output_fieldnames(input_fieldnames: list[str]) -> list[str]:
    """
    构建输出 CSV 的字段名列表。

    确保所有必要的标签相关字段都存在于输出中。

    参数:
        input_fieldnames: 输入 CSV 的字段名列表

    返回:
        包含所有必要字段的列表
    """
    ordered = list(input_fieldnames)
    # 添加具化所需的标签字段
    for field in label_protocol.MATERIALIZED_LABEL_FIELDS:
        if field not in ordered:
            ordered.append(field)
    # 添加 label_source 字段
    if "label_source" not in ordered:
        ordered.append("label_source")
    return ordered


def write_rows(path: Path, *, fieldnames: list[str], rows: list[dict]) -> None:
    """
    将行数据写入 CSV 文件。

    参数:
        path: 输出文件路径
        fieldnames: 字段名列表
        rows: 行数据列表
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_rows_atomic(path: Path, *, fieldnames: list[str], rows: list[dict]) -> None:
    """
    以原子操作方式写入 CSV 文件（先写临时文件再重命名）。

    避免在写入过程中因异常导致文件损坏。

    参数:
        path: 输出文件路径
        fieldnames: 字段名列表
        rows: 行数据列表
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent.as_posix()
    ) as tmp:
        temp_path = Path(tmp.name)
    try:
        write_rows(temp_path, fieldnames=fieldnames, rows=rows)
        # 原子替换：使用 os.replace 确保重命名是原子的
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def build_materialization_report(
    *,
    source_csv: Path,
    output_csv: Path,
    original_rows: list[dict],
    materialized_rows: list[dict],
    label_col: str,
) -> dict:
    """
    构建数据具化报告。

    报告包含：
    - 输入输出文件路径
    - 行数统计
    - 标签使用情况汇总
    - 具化前的标签来源统计

    参数:
        source_csv: 源 CSV 文件路径
        output_csv: 输出 CSV 文件路径
        original_rows: 原始行数据
        materialized_rows: 具化后的行数据
        label_col: 标签列名

    返回:
        包含报告信息的字典
    """
    original_sources = []
    for row in original_rows:
        resolved = label_protocol.resolve_label_record(row, label_col=label_col)
        original_sources.append(str(resolved["selected_source"] or ""))
    return {
        "source_csv": source_csv.as_posix(),
        "output_csv": output_csv.as_posix(),
        "row_count": len(materialized_rows),
        "label_col": label_col,
        "label_usage_summary": label_protocol.build_label_usage_summary(
            materialized_rows, label_col=label_col
        ),
        "pre_materialization_source_counts": {
            source: original_sources.count(source)
            for source in sorted(set(original_sources))
            if source
        },
    }


def main() -> None:
    """
    主函数：具化标注数据集。

    流程：
    1. 加载原始标注数据
    2. 具化为标准化的视图格式
    3. 写入输出文件
    4. 生成并保存报告
    """
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report_json)
    # 加载数据：读取 CSV 文件并获取字段名和行数据
    fieldnames, rows = load_rows(input_path)
    # 具化标签视图：将标注数据转换为标准化格式
    materialized_rows = label_protocol.materialize_label_view_rows(
        rows, label_col=args.label_col
    )
    # 构建输出字段名：确保包含所有必要的标签字段
    output_fieldnames = build_output_fieldnames(fieldnames)
    # 原子写入输出文件：先写临时文件再重命名，避免文件损坏
    write_rows_atomic(output_path, fieldnames=output_fieldnames, rows=materialized_rows)
    # 生成报告：收集具化前后的统计信息
    report = build_materialization_report(
        source_csv=input_path,
        output_csv=output_path,
        original_rows=rows,
        materialized_rows=materialized_rows,
        label_col=args.label_col,
    )
    # 写入报告：创建父目录并保存 JSON 报告
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 打印统计信息
    print(f"materialized_rows={report['row_count']}")
    print(f"adjudicated_ratio={report['label_usage_summary'].get('adjudicated_ratio')}")


if __name__ == "__main__":
    main()
