#!/usr/bin/env python3
"""
Formal Step2 few-shot 检索命令行封装。

本脚本是 construct_simple_two_intent.py 中 retrieve_fewshot_examples() 函数的
独立 CLI 入口，用于从 SQLite few-shot pool 中按 type signature 检索示例。

用法示例：
python code/retrieve_fewshot.py \
  --db data/fewshot_pool.db \
  --type-pair "fix+test" \
  --repo "owner/repo" \
  --k 2 \
  --seed 42

返回 JSON 格式的检索结果，包含：
- examples: 检索到的 few-shot 示例列表
- few_shot_source: 检索来源（exact_kway / type_overlap / generic_fallback 等）
- retrieval_status: 检索状态（exact / partial / generic / failed）
- retrieval_log: 详细的检索日志（各级候选数、排除原因等）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path


# 动态加载 construct_simple_two_intent 模块，复用其中的 retrieve_fewshot_examples 等函数
MODULE_PATH = Path(__file__).resolve().with_name("construct_simple_two_intent.py")
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    必需参数：
        --db: SQLite 数据库路径
        --type-pair: 规范化的类型签名（如 fix+test）
        --repo: 仓库标识（如 owner/repo）

    可选参数：
        --table: few-shot 表名（默认 fewshot_examples）
        --k: 检索示例数（默认 2）
        --seed: 随机种子（默认 42）
        --query-version: 查询版本元数据标签（已弃用，不影响检索行为）

    Returns:
        解析后的参数命名空间
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite database path.")
    parser.add_argument("--table", default="fewshot_examples")
    parser.add_argument("--type-pair", required=True, help="Canonical type signature, e.g. fix+test or fix+refactor+test.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--k", type=int, default=2, help="Number of few-shot examples to retrieve.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--query-version",
        default="sqlite_formal_kway_v2",
        help="Deprecated metadata-only flag; retrieval behavior is unchanged.",
    )
    args = parser.parse_args()
    if args.k <= 0:
        parser.error("`--k` must be a positive integer.")
    db_path = Path(args.db)
    if not db_path.exists() or not db_path.is_file():
        parser.error(f"Invalid --db path: {db_path}")
    if args.seed < 0:
        parser.error("`--seed` must be >= 0.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.table):
        parser.error(f"Unsafe table name: {args.table}")
    return args


def main() -> None:
    """执行 few-shot 检索并将结果输出为 JSON。

    流程：
    1. 解析命令行参数
    2. 调用 construct_simple_two_intent.retrieve_fewshot_examples() 执行检索
    3. 在返回的 payload 中附加 query_version 和 retrieval_params 元数据
    4. 以 JSON 格式输出到标准输出
    """
    args = parse_args()
    # 调用核心检索函数（k-aware fallback 策略：exact_kway → type_overlap → pairwise_overlap → single_type_overlap → generic_fallback）
    payload = MOD.retrieve_fewshot_examples(
        db_path=str(Path(args.db)),
        table=args.table,
        type_signature_canonical=args.type_pair,
        current_repo=args.repo,
        k=args.k,
        seed=args.seed,
    )
    # 附加查询版本元数据（不影响实际检索逻辑）
    payload["query_version"] = args.query_version
    payload["query_version_effective"] = False
    payload["retrieval_params"] = {
        "db": str(Path(args.db)),
        "table": args.table,
        "type_signature_canonical": args.type_pair,
        "repo": args.repo,
        "k": args.k,
        "seed": args.seed,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
