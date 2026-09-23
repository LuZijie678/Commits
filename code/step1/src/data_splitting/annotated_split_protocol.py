from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path


# 定义标注数据集的分割顺序，用于计划构建和验证
# 包含: 协议数据、GBDT训练数据、校准数据、评估数据、代理gap数据
ANNOTATED_SPLIT_ORDER = (
    "protocol",
    "gbdt_train",
    "calibration",
    "evaluation",
    "proxy_gap",
)

# 定义分割分配的优先级顺序，优先级高的分割会先被满足约束
# 评估和代理gap优先，其次是协议和校准，最后是GBDT训练
SPLIT_ASSIGNMENT_PRIORITY = (
    "evaluation",
    "proxy_gap",
    "protocol",
    "calibration",
    "gbdt_train",
)


def _row_sha(row: dict) -> str:
    """从行数据中提取sha值，用于唯一标识每条数据记录"""
    return str(row.get("sha", "")).strip()


def _row_repo(row: dict) -> str:
    """
    从行数据中提取仓库标识，优先使用repo字段，
    其次尝试resolved_repo字段，最后使用sha作为备选
    """
    return (
        str(row.get("repo", "")).strip()
        or str(row.get("resolved_repo", "")).strip()
        or f"sha::{_row_sha(row)}"
    )


def _row_label(row: dict) -> int | None:
    """
    从行数据中提取标签值，只接受0或1的整数
    其他值或空值都返回None
    """
    raw = row.get("is_single_intent")
    # 处理空值情况
    if raw in {None, ""}:
        return None
    try:
        label = int(raw)
    except (TypeError, ValueError):
        return None
    # 只接受0或1这两个有效标签值
    return label if label in {0, 1} else None


def _normalize_constraints(
    constraint: dict[str, int] | None,
) -> dict[str, int]:
    """
    标准化约束条件，将None或空约束转换为全零字典
    确保每个分割名称都有一个对应的约束值（非负整数）
    """
    # 初始化所有分割的约束为0
    normalized = {name: 0 for name in ANNOTATED_SPLIT_ORDER}
    # 遍历所有分割名称，填充有效的约束值
    for name in ANNOTATED_SPLIT_ORDER:
        if constraint and name in constraint:
            # 确保约束值为非负整数
            normalized[name] = max(0, int(constraint[name]))
    return normalized


def _group_rows_by_repo(rows: list[dict]) -> list[dict]:
    """
    按仓库对行数据进行分组，每个仓库作为一个独立的分组单元
    同一仓库的所有记录会被分配到同一个分割中，保证数据隔离性
    """
    # 使用字典按仓库名聚合行数据
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sha = _row_sha(row)
        # 过滤掉没有sha的无效行
        if not sha:
            continue
        grouped[_row_repo(row)].append(row)

    # 转换为列表格式，计算每个仓库的统计信息
    groups: list[dict] = []
    for repo, repo_rows in grouped.items():
        # 提取该仓库的所有sha和标签
        shas = [_row_sha(row) for row in repo_rows if _row_sha(row)]
        labels = [_row_label(row) for row in repo_rows]
        # 统计正负样本数量
        positive_count = sum(1 for label in labels if label == 1)
        negative_count = sum(1 for label in labels if label == 0)
        groups.append(
            {
                "repo": repo,
                "rows": list(repo_rows),
                "shas": shas,
                "row_count": len(repo_rows),
                "positive_count": positive_count,
                "negative_count": negative_count,
            }
        )
    return groups


def _empty_split_state() -> dict:
    """
    创建空的分割状态字典，用于初始化各分割的统计数据
    包含仓库列表、行数据、sha列表及各类计数
    """
    return {
        "repos": [],
        "rows": [],
        "shas": [],
        "row_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "repo_count": 0,
    }


def _split_deficits(
    split_state: dict,
    split_name: str,
    *,
    min_total_by_split: dict[str, int],
    min_positive_by_split: dict[str, int],
    min_negative_by_split: dict[str, int],
    min_repo_by_split: dict[str, int],
) -> dict[str, int]:
    """
    计算当前分割与目标约束之间的差距（不足量）
    返回各指标的缺少数量，用于指导分组分配决策
    """
    return {
        # 缺少的总行数 = 目标最小值 - 当前已分配数量
        "total": max(
            0, int(min_total_by_split[split_name]) - int(split_state["row_count"])
        ),
        # 缺少的正样本数
        "positive": max(
            0,
            int(min_positive_by_split[split_name]) - int(split_state["positive_count"]),
        ),
        # 缺少的负样本数
        "negative": max(
            0,
            int(min_negative_by_split[split_name]) - int(split_state["negative_count"]),
        ),
        # 缺少的仓库数
        "repo": max(
            0, int(min_repo_by_split[split_name]) - int(split_state["repo_count"])
        ),
    }


def _split_satisfied(deficits: dict[str, int]) -> bool:
    """
    检查分割是否已满足所有约束条件
    当所有不足量都 <= 0 时表示已满足
    """
    return all(int(value) <= 0 for value in deficits.values())


def _assign_group(split_state: dict, group: dict) -> None:
    """
    将一个仓库分组分配到指定分割中
    同时更新该分割的所有统计计数
    """
    split_state["repos"].append(str(group["repo"]))
    split_state["rows"].extend(group["rows"])
    split_state["shas"].extend(group["shas"])
    split_state["row_count"] += int(group["row_count"])
    split_state["positive_count"] += int(group["positive_count"])
    split_state["negative_count"] += int(group["negative_count"])
    # 仓库数量等于仓库列表长度
    split_state["repo_count"] = len(split_state["repos"])


def _group_score(group: dict, deficits: dict[str, int]) -> tuple[int, int, int]:
    """
    计算分组对当前分割的优先级评分
    评分规则：优先满足仓库数需求，其次正样本、负样本，最后总行数
    评分越高表示该分组越适合当前分割的约束需求
    """
    # 如果当前还需要仓库，则分配仓库有额外加分
    repo_gain = 1 if deficits["repo"] > 0 else 0
    # 计算该分组能提供的正样本增益（不超过缺少量）
    pos_gain = min(int(group["positive_count"]), int(deficits["positive"]))
    # 计算该分组能提供的负样本增益
    neg_gain = min(int(group["negative_count"]), int(deficits["negative"]))
    # 计算该分组能提供的总行数增益
    total_gain = min(int(group["row_count"]), int(deficits["total"]))
    # 综合评分：仓库*1000 + 正样本*100 + 负样本*100 + 总行数
    score = repo_gain * 1000 + pos_gain * 100 + neg_gain * 100 + total_gain
    # 溢出量（分配超过需求的部分），用于次要排序
    overflow = max(0, int(group["row_count"]) - int(deficits["total"]))
    # 返回评分和溢出量的负值（评分高、溢出少、原始行数少优先）
    return score, -overflow, -int(group["row_count"])


def _validate_plan_constraints(
    plan: dict,
    *,
    min_total_by_split: dict[str, int],
    min_positive_by_split: dict[str, int],
    min_negative_by_split: dict[str, int],
    min_repo_by_split: dict[str, int],
) -> None:
    """
    验证最终分割计划是否满足所有约束条件
    如果任何约束不满足，抛出运行时错误
    """
    for split_name in ANNOTATED_SPLIT_ORDER:
        split_state = plan["splits"][split_name]
        # 检查总行数约束
        if split_state["row_count"] < min_total_by_split[split_name]:
            raise RuntimeError(
                f"annotated split `{split_name}` row_count too small: {split_state['row_count']} < {min_total_by_split[split_name]}"
            )
        # 检查正样本数约束
        if split_state["positive_count"] < min_positive_by_split[split_name]:
            raise RuntimeError(
                f"annotated split `{split_name}` positive_count too small: {split_state['positive_count']} < {min_positive_by_split[split_name]}"
            )
        # 检查负样本数约束
        if split_state["negative_count"] < min_negative_by_split[split_name]:
            raise RuntimeError(
                f"annotated split `{split_name}` negative_count too small: {split_state['negative_count']} < {min_negative_by_split[split_name]}"
            )
        # 检查仓库数约束
        if split_state["repo_count"] < min_repo_by_split[split_name]:
            raise RuntimeError(
                f"annotated split `{split_name}` repo_count too small: {split_state['repo_count']} < {min_repo_by_split[split_name]}"
            )


def build_annotated_split_plan(
    *,
    rows: list[dict],
    seed: int,
    min_total_by_split: dict[str, int] | None,
    min_positive_by_split: dict[str, int] | None,
    min_negative_by_split: dict[str, int] | None,
    min_repo_by_split: dict[str, int] | None,
) -> dict:
    """
    构建标注数据集的分割计划，核心算法逻辑：
    1. 标准化约束条件
    2. 按仓库分组数据
    3. 按优先级顺序为各分割分配分组
    4. 验证约束满足情况
    """
    # 标准化所有约束条件，将None转为全零字典
    min_total = _normalize_constraints(min_total_by_split)
    min_positive = _normalize_constraints(min_positive_by_split)
    min_negative = _normalize_constraints(min_negative_by_split)
    min_repo = _normalize_constraints(min_repo_by_split)

    # 按仓库对数据进行分组
    groups = _group_rows_by_repo(rows)

    # 验证：每个分割至少需要一个仓库分组
    if len(groups) < len(ANNOTATED_SPLIT_ORDER):
        raise RuntimeError(
            "annotated split planning requires at least one repo group per split"
        )
    # 验证：仓库分组数必须满足所有min_repo约束的总和
    if len(groups) < sum(1 for name in ANNOTATED_SPLIT_ORDER if min_repo[name] > 0):
        raise RuntimeError(
            "insufficient repo groups for requested min_repo constraints"
        )

    # 使用随机种子创建随机数生成器，确保结果可复现
    rng = random.Random(int(seed))
    indexed_groups = list(groups)
    # 首先随机打乱分组顺序
    rng.shuffle(indexed_groups)
    # 然后按样本数量降序排序（正负样本总数多的在前）
    indexed_groups.sort(
        key=lambda group: (
            -(int(group["positive_count"]) + int(group["negative_count"])),
            -int(group["row_count"]),
            str(group["repo"]),
        )
    )

    # 初始化分割计划结构
    plan = {
        "seed": int(seed),
        "split_order": list(ANNOTATED_SPLIT_ORDER),
        "constraints": {
            "min_total_by_split": dict(min_total),
            "min_positive_by_split": dict(min_positive),
            "min_negative_by_split": dict(min_negative),
            "min_repo_by_split": dict(min_repo),
        },
        "splits": {name: _empty_split_state() for name in ANNOTATED_SPLIT_ORDER},
    }
    # 初始时所有分组都未分配
    unassigned_groups = list(indexed_groups)

    # 按优先级顺序为每个分割分配分组
    for split_name in SPLIT_ASSIGNMENT_PRIORITY:
        split_state = plan["splits"][split_name]
        # 循环分配直到当前分割满足约束
        while True:
            # 计算当前分割的不足量
            deficits = _split_deficits(
                split_state,
                split_name,
                min_total_by_split=min_total,
                min_positive_by_split=min_positive,
                min_negative_by_split=min_negative,
                min_repo_by_split=min_repo,
            )
            # 如果约束已满足，退出循环
            if _split_satisfied(deficits):
                break

            # 计算每个未分配分组的评分
            scored_groups = [
                (_group_score(group, deficits), index, group)
                for index, group in enumerate(unassigned_groups)
            ]
            # 过滤掉评分为0的分组（对当前分割无贡献）
            scored_groups = [
                (score, index, group)
                for score, index, group in scored_groups
                if score[0] > 0
            ]
            # 如果没有可用的分组，抛出错误
            if not scored_groups:
                raise RuntimeError(
                    f"unable to satisfy annotated split constraints for `{split_name}`"
                )
            # 按评分降序排序，选择最优分组
            scored_groups.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            _, _, best_group = scored_groups[0]
            # 将最优分组分配给当前分割
            _assign_group(split_state, best_group)
            # 从未分配列表中移除已分配的分组
            unassigned_groups = [
                group
                for group in unassigned_groups
                if str(group["repo"]) != str(best_group["repo"])
            ]

    # 将剩余未分配的分组放入默认分割（优先选择gbdt_train）
    remainder_split = (
        "gbdt_train"
        if "gbdt_train" in ANNOTATED_SPLIT_ORDER
        else ANNOTATED_SPLIT_ORDER[0]
    )
    for group in unassigned_groups:
        _assign_group(plan["splits"][remainder_split], group)

    # 验证所有约束是否真正满足
    _validate_plan_constraints(
        plan,
        min_total_by_split=min_total,
        min_positive_by_split=min_positive,
        min_negative_by_split=min_negative,
        min_repo_by_split=min_repo,
    )
    # 验证所有分割的SHA是否互不重叠
    if not all_splits_sha_disjoint(plan):
        raise RuntimeError("annotated split planner produced overlapping SHAs")
    return plan


def all_splits_sha_disjoint(plan: dict) -> bool:
    """
    检查所有分割的SHA集合是否互不重叠
    用于确保数据分割的隔离性，避免数据泄露
    """
    seen: set[str] = set()
    for split_name in ANNOTATED_SPLIT_ORDER:
        split_state = (plan.get("splits") or {}).get(split_name) or {}
        # 获取当前分割的SHA集合
        current = {str(sha) for sha in split_state.get("shas", []) if str(sha)}
        # 检查是否与已见过的SHA有交集
        if seen & current:
            return False
        # 合并到已见集合中
        seen |= current
    return True


def summarize_split_plan(plan: dict) -> dict:
    """
    生成分割计划的摘要信息，包含各分割的详细统计
    用于日志记录和调试
    """
    return {
        "seed": int(plan.get("seed", 0)),
        "split_order": list(plan.get("split_order", [])),
        "constraints": dict(plan.get("constraints", {})),
        "is_sha_disjoint": all_splits_sha_disjoint(plan),
        "splits": {
            split_name: {
                "row_count": int(
                    (plan.get("splits") or {}).get(split_name, {}).get("row_count", 0)
                ),
                "positive_count": int(
                    (plan.get("splits") or {})
                    .get(split_name, {})
                    .get("positive_count", 0)
                ),
                "negative_count": int(
                    (plan.get("splits") or {})
                    .get(split_name, {})
                    .get("negative_count", 0)
                ),
                "repo_count": int(
                    (plan.get("splits") or {}).get(split_name, {}).get("repo_count", 0)
                ),
                "repos": list(
                    (plan.get("splits") or {}).get(split_name, {}).get("repos", [])
                ),
                "shas": list(
                    (plan.get("splits") or {}).get(split_name, {}).get("shas", [])
                ),
            }
            for split_name in ANNOTATED_SPLIT_ORDER
        },
    }


def split_sha_set(plan: dict, split_name: str) -> set[str]:
    """
    获取指定分割的SHA集合
    用于快速判断某条记录属于哪个分割
    """
    split_state = (plan.get("splits") or {}).get(split_name) or {}
    return {str(sha) for sha in split_state.get("shas", []) if str(sha)}


def materialize_split_rows(
    *,
    rows: list[dict],
    plan: dict,
    split_name: str,
) -> list[dict]:
    """
    根据分割计划提取指定分割的所有行数据
    返回符合指定分割SHA集合的所有原始记录
    """
    wanted = split_sha_set(plan, split_name)
    return [dict(row) for row in rows if _row_sha(row) in wanted]


def assert_rows_match_split(
    *,
    rows: list[dict],
    split_sha_set: set[str],
    split_name: str,
    context: str,
) -> None:
    """
    断言给定的行数据集合与预期分割的SHA集合匹配
    用于验证数据一致性，如果有不匹配的SHA则抛出错误
    """
    # 提取所有行的SHA
    row_shas = {_row_sha(row) for row in rows if _row_sha(row)}
    # 计算不在预期分割中的SHA
    unexpected = sorted(row_shas - set(split_sha_set))
    if unexpected:
        raise RuntimeError(
            f"{context} received rows outside `{split_name}` split: {unexpected[:10]}"
        )


def _write_csv(path: Path, rows: list[dict]) -> None:
    """
    将行数据写入CSV文件
    自动创建父目录，处理空数据情况
    """
    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)
    # 空数据时写入空文件
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # 收集所有可能的字段名
    fieldnames = sorted({key for row in rows for key in row.keys()})
    # 使用DictWriter写入CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_split_artifacts(
    *,
    base_dir: Path,
    rows: list[dict],
    plan: dict,
) -> dict:
    """
    将分割计划和分割后的数据写入文件系统
    生成JSON计划文件和CSV数据文件
    """
    # 创建基础目录
    base_dir.mkdir(parents=True, exist_ok=True)
    # 生成计划摘要
    summary = summarize_split_plan(plan)
    # 写入JSON计划文件
    plan_json = base_dir / "annotated_split_plan.json"
    plan_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 初始化各类输出文件的路径字典
    split_csvs: dict[str, str] = {}
    split_sha_csvs: dict[str, str] = {}
    split_repo_summary_jsons: dict[str, str] = {}

    # 遍历所有分割，生成对应的输出文件
    for split_name in ANNOTATED_SPLIT_ORDER:
        # 提取该分割的行数据
        split_rows = materialize_split_rows(rows=rows, plan=plan, split_name=split_name)

        # 写入分割的完整CSV文件（包含所有字段）
        split_csv_path = base_dir / f"{split_name}.csv"
        _write_csv(split_csv_path, split_rows)
        split_csvs[split_name] = split_csv_path.as_posix()

        # 写入该分割的SHA列表CSV
        split_sha_csv_path = base_dir / f"{split_name}_shas.csv"
        _write_csv(
            split_sha_csv_path,
            [{"sha": sha} for sha in summary["splits"][split_name]["shas"]],
        )
        split_sha_csvs[split_name] = split_sha_csv_path.as_posix()

        # 写入该分割的仓库摘要JSON
        split_repo_summary_path = base_dir / f"{split_name}_repo_summary.json"
        split_repo_summary_path.write_text(
            json.dumps(summary["splits"][split_name], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        split_repo_summary_jsons[split_name] = split_repo_summary_path.as_posix()

    # 返回所有生成文件的路径映射
    return {
        "plan_json": plan_json.as_posix(),
        "split_csvs": split_csvs,
        "split_sha_csvs": split_sha_csvs,
        "split_repo_summary_jsons": split_repo_summary_jsons,
    }
