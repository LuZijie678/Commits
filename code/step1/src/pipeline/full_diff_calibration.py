"""
原子性校准拟合脚本

本脚本用于拟合Step1原子性分类器的校准参数，包括：
1. 训练GBDT模型（基于弱标签）
2. 使用等渗回归进行概率校准
3. 基于标注数据选择阈值（tau_a, tau_b）

支持的校准模式：
- gbdt_isotonic: GBDT模型 + 等渗回归校准（默认）
- platt: 简单的Platt缩放

输出包含：
- 序列化模型（Base64编码）
- 阈值（tau_a: Tier A下限, tau_b: Tier B下限）
- 协议（消息协议、范围协议、类型协议）
- 认知不确定性参考
"""

import argparse
import base64
import csv
import json
import math
import pickle
import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

from src.pipeline import atomic_mining as miner
import src.data_splitting.annotated_split_protocol as annotated_split_protocol
from src.labeling import label_protocol
from src.param_derivation.distribution_utils import (
    derive_three_cluster_boundaries,
    derive_high_cluster_lower_bound,
    derive_small_cluster_upper_bound,
)
from src.param_derivation.threshold_selection import (
    ThresholdSelectionReport,
    select_threshold_by_precision_report,
)
from src.param_derivation.weight_calibration import derive_epistemic_reference


DEFAULT_MODE = "gbdt_isotonic"  # 默认模式：GBDT+等渗回归
DEFAULT_PLATT_ITERATIONS = 0  # 默认Platt迭代次数（0表示自动派生）
DEFAULT_PLATT_LEARNING_RATE = 0.0  # 默认Platt学习率（0表示自动派生）
DEFAULT_PLATT_L2 = 0.0  # 默认Platt L2正则化（0表示自动派生）
DEFAULT_TARGET_PRECISION_A = 0.90  # Tier A目标精确率：90%
DEFAULT_TARGET_PRECISION_B = 0.70  # Tier B目标精确率：70%
DEFAULT_GBDT_ESTIMATORS = 0  # 默认GBDT树数量（0表示自动派生）
DEFAULT_GBDT_MAX_DEPTH = 0  # 默认GBDT深度（0表示自动派生）
DEFAULT_GBDT_LEARNING_RATE = 0.0  # 默认GBDT学习率（0表示自动派生）
DEFAULT_RANDOM_STATE = 42  # 默认随机种子
DEFAULT_HARD_NEGATIVE_UPSAMPLE = 0.0  # 默认硬负例上采样比例（0表示自动派生）
DEFAULT_MIN_LABELED = 20  # 最少标注样本数
DEFAULT_LABELED_CALIBRATION_SCHEME = "holdout"  # 默认标注校准方案
CALIBRATION_SCHEME_CHOICES = ("holdout", "cv")
DEFAULT_LABELED_HOLDOUT_RATIO = 0.20  # 默认留出比例
DEFAULT_LABELED_CV_FOLDS = 5  # 默认交叉验证折数
DEFAULT_THRESHOLD_FALLBACK_POLICY = "error"  # 默认阈值回退策略
THRESHOLD_FALLBACK_POLICIES = ("error",)
CLIP_EPS = 1e-8  # 概率裁剪epsilon
MIN_WEAK_POOL_SIZE = 100  # 最小弱标签池大小
MIN_WEAK_CLASS_COUNT = 20  # 最小弱标签类别数
NEGATIVE_TYPE_SET = {"chore", "ci"}  # 负面类型集合（这些类型通常不是单意图）
SUBSTANTIVE_TYPE_SET = {"fix", "feat", "refactor", "test", "perf"}
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制


@dataclass(frozen=True)
class WeakLabelProtocol:
    """
    弱标签协议

    定义去循环化弱标签协议。

    该协议只基于可解释的消息/结构规则，不依赖 `atomic_prior()` 或其任何变体。
    目标是高精度优先，宁可 abstain，也不追求高召回。
    """

    version: str  # 协议版本
    positive_file_count_max: float  # 阳性最大文件数（归一化空间）
    positive_module_count_max: float  # 阳性最大模块数（归一化空间）
    positive_patch_size_max: float  # 阳性最大 patch 大小（归一化空间）
    positive_role_count_max: int  # 阳性最大角色数
    negative_file_count_min: float  # 阴性最小文件数（归一化空间）
    negative_module_count_min: float  # 阴性最小模块数（归一化空间）
    negative_patch_size_min: float  # 阴性最小 patch 大小（归一化空间）
    negative_role_count_min: int  # 阴性最小角色数
    positive_issue_ref_max: int  # 阳性最大 issue / PR 引用数
    negative_issue_ref_min: int  # 阴性最小 issue / PR 引用数
    positive_subject_action_max: int  # 阳性最大 subject action 数
    negative_subject_action_min: int  # 阴性最小 subject action 数
    negative_structural_rule_min_fires: int  # 触发结构负样本所需最少规则数
    source: str  # 来源说明


def estimate_subject_action_count(subject_line: str) -> int:
    """
    粗粒度估计 subject 中包含的动作数量。

    该计数仅用于弱标签规则，不参与模型打分；它故意保持可解释但粗糙。
    """
    # 添加首尾空格便于单词边界匹配
    subject = f" {str(subject_line or '').strip().lower()} "
    # 空subject返回0
    if not subject.strip():
        return 0
    # 统计连接词数量（表示多个动作）
    connector_count = 0
    for token in [
        " and ",  # and连接 - 表示两个动作
        " also ",  # also - 表示额外动作
        " plus ",  # plus - 表示附加
        " then ",  # then - 表示顺序
        " additionally ",  # additionally - 表示额外
        " meanwhile ",  # meanwhile - 表示并行
        " follow-up ",  # follow-up - 表示后续
        ";",  # 分号 - 表示并列
        " / ",  # 斜杠 - 表示choice
        " & ",  # & - 表示and
    ]:
        connector_count += subject.count(token)
    # 至少1个动作 + 连接词数量 = 估计的动作数
    return max(1, 1 + connector_count)


def summarize_rule_reports(rule_reports: list[dict]) -> dict:
    """聚合弱标签规则触发情况，供 artifact 审计。"""
    label_counts: Counter = Counter()
    decision_kind_counts: Counter = Counter()
    positive_rule_counts: Counter = Counter()
    negative_rule_counts: Counter = Counter()
    abstain_reason_counts: Counter = Counter()

    for report in rule_reports:
        label_name = str(report.get("label_name", "abstain"))
        decision_kind = str(report.get("decision_kind", "abstain"))
        label_counts[label_name] += 1
        decision_kind_counts[decision_kind] += 1
        for rule_name in report.get("positive_rules_fired", []):
            positive_rule_counts[str(rule_name)] += 1
        for rule_name in report.get("negative_rules_fired", []):
            negative_rule_counts[str(rule_name)] += 1
        if label_name == "abstain":
            abstain_reason_counts[decision_kind] += 1

    return {
        "protocol_version": "independent_rule_protocol_v1",
        "label_counts": dict(label_counts),
        "decision_kind_counts": dict(decision_kind_counts),
        "positive_rule_counts": dict(positive_rule_counts),
        "negative_rule_counts": dict(negative_rule_counts),
        "abstain_reason_counts": dict(abstain_reason_counts),
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    # 必需参数：输入CSV文件路径
    parser.add_argument(
        "--input",
        default="",
        help="CSV数据集路径，推荐使用annotated_dataset或包含commit_message/type/git_diff的enriched候选",
    )
    parser.add_argument("--protocol-input", default="")
    parser.add_argument("--gbdt-train-input", default="")
    parser.add_argument("--calibration-input", default="")
    parser.add_argument("--evaluation-input", default="")
    parser.add_argument(
        "--allow-legacy-single-split",
        action="store_true",
        help="Explicitly allow reusing a single annotated input for all roles. Not recommended.",
    )
    parser.add_argument(
        "--annotated-split-plan-json",
        default="",
        help="Optional annotated split plan json used to validate split isolation.",
    )
    # 输出路径，默认输出到step1校准目录
    parser.add_argument(
        "--output", default="outputs/calibration/atomic_calibration.json"
    )
    # 校准模式选择：gbdt_isotonic或platt
    parser.add_argument(
        "--mode", choices=["gbdt_isotonic", "platt"], default=DEFAULT_MODE
    )

    # legacy platt模式参数
    parser.add_argument("--logit-col", default="atomic_logit")  # logit列名
    parser.add_argument(
        "--iterations", type=int, default=DEFAULT_PLATT_ITERATIONS
    )  # Platt迭代次数
    parser.add_argument(
        "--platt-learning-rate",
        type=float,
        default=DEFAULT_PLATT_LEARNING_RATE,  # Platt学习率
    )
    parser.add_argument("--l2", type=float, default=DEFAULT_PLATT_L2)  # L2正则化

    # 标签和阈值参数
    parser.add_argument("--label-col", default="is_single_intent")  # 标签列名
    parser.add_argument(
        "--tau-a-precision",
        type=float,
        default=DEFAULT_TARGET_PRECISION_A,  # Tier A目标精确率90%
    )
    parser.add_argument(
        "--tau-b-precision",
        type=float,
        default=DEFAULT_TARGET_PRECISION_B,  # Tier B目标精确率70%
    )

    # GBDT模型参数
    parser.add_argument(
        "--n-estimators", type=int, default=DEFAULT_GBDT_ESTIMATORS
    )  # 树数量
    parser.add_argument(
        "--max-depth", type=int, default=DEFAULT_GBDT_MAX_DEPTH
    )  # 最大深度
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=DEFAULT_GBDT_LEARNING_RATE,  # 学习率
    )
    parser.add_argument(
        "--random-state", type=int, default=DEFAULT_RANDOM_STATE
    )  # 随机种子
    parser.add_argument(
        "--hard-negative-upsample",
        type=float,
        default=DEFAULT_HARD_NEGATIVE_UPSAMPLE,  # 硬负例上采样比例
    )
    parser.add_argument(
        "--min-labeled", type=int, default=DEFAULT_MIN_LABELED
    )  # 最少标注样本数
    # 标注校准方案：holdout或cv
    parser.add_argument(
        "--labeled-calibration-scheme",
        choices=list(CALIBRATION_SCHEME_CHOICES),
        default=DEFAULT_LABELED_CALIBRATION_SCHEME,
        help="使用holdout切分或CV-OOF进行标注等渗校准/阈值选择",
    )
    parser.add_argument(
        "--labeled-holdout-ratio",
        type=float,
        default=DEFAULT_LABELED_HOLDOUT_RATIO,  # holdout验证比例
        help="holdout校准方案的验证比例",
    )
    parser.add_argument(
        "--labeled-cv-folds",
        type=int,
        default=DEFAULT_LABELED_CV_FOLDS,  # 交叉验证折数
        help="交叉验证的分层折数",
    )
    # 阈值回退策略
    parser.add_argument(
        "--threshold-fallback-policy",
        choices=list(THRESHOLD_FALLBACK_POLICIES),
        default=DEFAULT_THRESHOLD_FALLBACK_POLICY,
        help="精确率约束的阈值选择回退时的策略",
    )
    return parser.parse_args()


def sigmoid(value: float) -> float:
    """
    Sigmoid函数：将任意值映射到(0,1)区间

    公式: sigmoid(x) = 1 / (1 + exp(-x))

    参数:
        value: 输入的logit值

    返回:
        float: 映射后的概率值，范围(0,1)
    """
    if value >= 0:
        exp_val = math.exp(-value)
        return 1.0 / (1.0 + exp_val)
    exp_val = math.exp(value)
    return exp_val / (1.0 + exp_val)


def clip_prob(value: float) -> float:
    """
    裁剪概率值到有效范围

    将概率裁剪到(epsilon, 1-epsilon)，避免数值溢出问题。
    例如：log(0)或log(1)会导致-inf或inf。

    参数:
        value: 原始概率值

    返回:
        float: 裁剪后的概率值
    """
    return min(1.0 - CLIP_EPS, max(CLIP_EPS, value))


def safe_float(value: object, default: float = 0.0) -> float:
    """
    安全转换为浮点数

    处理空值、None等特殊情况，避免转换错误。

    参数:
        value: 待转换的值
        default: 转换失败时的默认值

    返回:
        float: 转换后的浮点数
    """
    try:
        if value in {"", None}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def quantile_value(values: list[float], q: float, default: float) -> float:
    """
    计算分位数

    例如：q=0.5返回中位数，q=0.25返回第一四分位数。

    参数:
        values: 值列表
        q: 分位数，范围[0,1]
        default: 空列表时的默认值

    返回:
        float: 分位数值
    """
    if not values:
        return float(default)
    ordered = sorted(float(item) for item in values)
    q_clip = max(0.0, min(1.0, float(q)))
    index = int(round((len(ordered) - 1) * q_clip))
    index = max(0, min(len(ordered) - 1, index))
    return float(ordered[index])


def _normalized_diff_feature(
    *,
    repo: str,
    feature_name: str,
    raw_value: float,
    repo_stats: dict[str, dict[str, dict[str, float]]],
    global_stats: dict[str, dict[str, float]],
) -> float:
    """
    计算diff特征的仓库级归一化值（缺失时回退到全局统计）
    """
    feature_stats = (repo_stats.get(repo) or {}).get(feature_name)
    if feature_stats is None:
        feature_stats = (global_stats or {}).get(feature_name)
    return float(miner.normalize_feature(float(raw_value), feature_stats))


def parse_label(raw: object) -> int | None:
    """
    解析标注标签

    支持多种标签格式的解析：
    - 阳性: "1", "true", "yes", "y", "single", "atomic"
    - 阴性: "0", "false", "no", "n", "multi", "non-atomic"
    - 无效: None, "", 其他

    参数:
        raw: 原始标签值

    返回:
        int | None: 解析后的标签（1=阳性, 0=阴性, None=无效）
    """
    if raw in {None, ""}:
        return None
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "single", "atomic"}:
        return 1
    if value in {"0", "false", "no", "n", "multi", "non-atomic"}:
        return 0
    return None


def resolve_training_label(row: dict, *, label_col: str) -> int | None:
    resolved = label_protocol.resolve_label_record(row, label_col=label_col)
    return resolved["selected_label_int"]


def stratified_holdout_indices(
    labels: list[int],
    holdout_ratio: float,
    random_state: int,
) -> tuple[list[int], list[int]] | None:
    """
    分层留出索引

    按标签分层切分数据，确保训练集和验证集都包含所有类别。
    这对于类别不平衡的数据集尤为重要。

    参数:
        labels: 标签列表（元素为0或1）
        holdout_ratio: 留出比例（0-1之间）
        random_state: 随机种子（保证可复现性）

    返回:
        tuple[list[int], list[int]] | None: (训练索引列表, 验证索引列表)
        - 如果无法满足分层条件，返回None
    """
    # 裁剪比例到有效范围，确保在(0,1)之间
    ratio = max(0.0, min(1.0, float(holdout_ratio)))
    # 比例必须大于0且小于1才能进行有效切分
    if ratio <= 0.0 or ratio >= 1.0:
        return None

    # 按标签分组，便于分层切分
    by_label: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(int(label), []).append(index)

    # 每类至少需要2个样本才能保持训练/验证集都有该类，否则无法进行分层
    if any(len(indices) < 2 for indices in by_label.values()):
        return None

    # 分层切分：对每个类别分别进行切分
    rng = random.Random(random_state)  # 使用随机种子保证可复现性
    train_indices: list[int] = []  # 训练集索引
    val_indices: list[int] = []  # 验证集索引
    for label in sorted(by_label):
        indices = list(by_label[label])
        rng.shuffle(indices)  # 随机打乱该类别的索引
        # 计算留出数量：根据比例计算该类别应留出的样本数
        holdout_n = int(round(len(indices) * ratio))
        holdout_n = max(1, holdout_n)  # 至少1个
        holdout_n = min(len(indices) - 1, holdout_n)  # 最多len-1个（保证训练集有样本）
        if holdout_n <= 0:
            return None
        # 前holdout_n个作为验证集，剩余作为训练集
        val_indices.extend(indices[:holdout_n])
        train_indices.extend(indices[holdout_n:])

    # 检查有效性：确保训练集和验证集都不为空
    if not train_indices or not val_indices:
        return None
    # 确保训练集和验证集都包含两个类别
    train_labels = {labels[index] for index in train_indices}
    val_labels = {labels[index] for index in val_indices}
    if len(train_labels) < 2 or len(val_labels) < 2:
        return None
    return train_indices, val_indices


def repo_group_values(items: list[dict]) -> list[str]:
    """为 split 提取 repo 级 group key；缺失 repo 时退化为唯一 sha。"""
    groups: list[str] = []
    for item in items:
        row = item.get("row", item)
        repo = (
            str(item.get("repo", "")).strip()
            or str(row.get("repo", "")).strip()
            or str(row.get("resolved_repo", "")).strip()
            or miner.extract_repo(str(row.get("commit_url", "")))
        )
        sha = str(row.get("sha", "")).strip()
        groups.append(repo or f"sha::{sha}")
    return groups


def repo_aware_holdout_indices(
    labels: list[int],
    groups: list[str],
    holdout_ratio: float,
    random_state: int,
) -> tuple[list[int], list[int]] | None:
    ratio = max(0.0, min(1.0, float(holdout_ratio)))
    if ratio <= 0.0 or ratio >= 1.0 or len(labels) != len(groups):
        return None
    unique_groups = {str(group) for group in groups if str(group)}
    if len(unique_groups) < 2:
        return None
    n_splits = max(2, int(round(1.0 / ratio)))
    n_splits = min(n_splits, len(unique_groups))
    if n_splits < 2:
        return None
    splitter = StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=random_state
    )
    try:
        train_idx, val_idx = next(
            splitter.split(list(range(len(labels))), labels, groups)
        )
    except ValueError:
        return None
    return list(train_idx), list(val_idx)


def repo_aware_cv_splits(
    labels: list[int],
    groups: list[str],
    cv_folds: int,
    random_state: int,
) -> tuple[list[tuple[list[int], list[int]]], int] | None:
    if len(labels) != len(groups):
        return None
    unique_groups = {str(group) for group in groups if str(group)}
    if len(unique_groups) < 2:
        return None
    class_counts = Counter(labels)
    min_class = min(class_counts.values()) if class_counts else 0
    n_splits = min(max(2, int(cv_folds)), int(min_class), len(unique_groups))
    if n_splits < 2:
        return None
    splitter = StratifiedGroupKFold(
        n_splits=n_splits, shuffle=True, random_state=random_state
    )
    try:
        splits = [
            (list(train_idx), list(val_idx))
            for train_idx, val_idx in splitter.split(
                list(range(len(labels))), labels, groups
            )
        ]
    except ValueError:
        return None
    return splits, n_splits


def subset(values: list[float], indices: list[int]) -> list[float]:
    """
    从列表中按索引提取子集

    参数:
        values: 原始列表
        indices: 索引列表

    返回:
        list[float]: 提取的子列表
    """
    return [values[index] for index in indices]


def subset_int(values: list[int], indices: list[int]) -> list[int]:
    """
    从整数列表中按索引提取子集

    参数:
        values: 原始整数列表
        indices: 索引列表

    返回:
        list[int]: 提取的子列表
    """
    return [values[index] for index in indices]


def threshold_report_to_dict(report) -> dict:
    """
    将阈值选择报告转换为字典

    参数:
        report: ThresholdSelectionReport对象

    返回:
        dict: 包含threshold, achieved_precision, source, used_fallback, support的字典
    """
    return {
        "threshold": float(report.threshold),
        "achieved_precision": (
            float(report.achieved_precision)
            if report.achieved_precision is not None
            else None
        ),
        "source": str(report.source),
        "used_fallback": bool(report.used_fallback),
        "support": int(report.support),
    }


def apply_threshold_fallback_policy(
    reports: dict[str, dict],
    policy: str,
) -> None:
    """
    应用阈值回退策略

    当阈值选择使用了fallback时，直接抛出异常终止程序。

    参数:
        reports: 阈值报告字典（键为tau_a/tau_b）
        policy: 策略选项（当前仅支持error）

    异常:
        RuntimeError: 当policy="error"且有fallback时
    """
    fallback_items = [
        name for name, report in reports.items() if bool(report.get("used_fallback"))
    ]
    if not fallback_items:
        return
    message = (
        "precision-constrained threshold selection used fallback for "
        + ", ".join(fallback_items)
        + f" (policy={policy})"
    )
    raise RuntimeError(message)


def derive_gbdt_hyperparams(
    n_samples: int,
    n_features: int,
    n_estimators_arg: int,
    max_depth_arg: int,
    learning_rate_arg: float,
) -> dict[str, float | int]:
    """
    派生GBDT超参数

    根据样本数和特征数自动推导GBDT模型的超参数。
    如果参数>0则使用用户指定值，否则自动推导。

    超参数推导公式：
    - n_estimators: max(32, sqrt(n_samples * n_features))
    - max_depth: max(2, log2(n_features + 1))
    - learning_rate: 1 / sqrt(n_estimators)

    参数:
        n_samples: 样本数量
        n_features: 特征数量
        n_estimators_arg: 用户指定的树数量（0=自动）
        max_depth_arg: 用户指定的最大深度（0=自动）
        learning_rate_arg: 用户指定的学习率（0=自动）

    返回:
        dict: 超参数字典，包含值和来源说明
    """
    # 推导n_estimators：如果用户指定则使用指定值，否则自动推导
    if n_estimators_arg > 0:
        n_estimators = int(n_estimators_arg)
        estimators_source = "fixed_from_args"
    else:
        # 自动推导：sqrt(n_samples * n_features)，至少32棵树
        n_estimators = max(
            32, int(round(math.sqrt(max(1, n_samples) * max(1, n_features))))
        )
        estimators_source = "distribution_sqrt_nxf"

    # 推导max_depth：如果用户指定则使用指定值，否则自动推导
    if max_depth_arg > 0:
        max_depth = int(max_depth_arg)
        depth_source = "fixed_from_args"
    else:
        # 自动推导：log2(n_features + 1)，至少2层
        max_depth = max(2, int(round(math.log2(max(2, n_features + 1)))))
        depth_source = "constraint_log2_feature_dim"

    # 推导learning_rate：如果用户指定则使用指定值，否则自动推导
    if learning_rate_arg > 0:
        learning_rate = float(learning_rate_arg)
        lr_source = "fixed_from_args"
    else:
        # 自动推导：1 / sqrt(n_estimators)，树越多学习率越小
        learning_rate = 1.0 / max(1.0, math.sqrt(float(n_estimators)))
        lr_source = "constraint_inverse_sqrt_estimators"

    return {
        "n_estimators": n_estimators,  # GBDT树的数量
        "max_depth": max_depth,  # 树的最大深度
        "learning_rate": learning_rate,  # 学习率
        "n_estimators_source": estimators_source,  # n_estimators来源
        "max_depth_source": depth_source,  # max_depth来源
        "learning_rate_source": lr_source,  # learning_rate来源
    }


def derive_platt_hyperparams(
    n_samples: int,
    iterations_arg: int,
    learning_rate_arg: float,
    l2_arg: float,
) -> dict[str, float | int | str]:
    """
    派生Platt Scaling超参数

    根据样本数量自动推导Platt scaling的超参数。

    超参数推导公式：
    - iterations: max(1, sqrt(n_samples) * 100)
    - learning_rate: 1 / sqrt(n_samples)
    - l2: 1 / n_samples

    参数:
        n_samples: 样本数量
        iterations_arg: 用户指定的迭代次数（0=自动）
        learning_rate_arg: 用户指定的学习率（0=自动）
        l2_arg: 用户指定的L2正则化（0=自动）

    返回:
        dict: 超参数字典
    """
    # 推导iterations：如果用户指定则使用指定值，否则自动推导
    if iterations_arg > 0:
        iterations = int(iterations_arg)
        iterations_source = "fixed_from_args"
    else:
        # 自动推导：sqrt(n_samples) * 100，样本越多迭代越多
        iterations = max(1, int(round(math.sqrt(max(1, n_samples)) * 100.0)))
        iterations_source = "constraint_sqrt_sample_scale"

    # 推导learning_rate：如果用户指定则使用指定值，否则自动推导
    if learning_rate_arg > 0:
        learning_rate = float(learning_rate_arg)
        lr_source = "fixed_from_args"
    else:
        # 自动推导：1 / sqrt(n_samples)，样本越多学习率越小
        learning_rate = 1.0 / max(1.0, math.sqrt(float(max(1, n_samples))))
        lr_source = "constraint_inverse_sqrt_samples"

    # 推导l2：如果用户指定则使用指定值，否则自动推导
    if l2_arg > 0:
        l2 = float(l2_arg)
        l2_source = "fixed_from_args"
    else:
        # 自动推导：1 / n_samples，样本越多正则化越弱
        l2 = 1.0 / max(1.0, float(max(1, n_samples)))
        l2_source = "constraint_inverse_samples"

    return {
        "iterations": iterations,  # 梯度下降迭代次数
        "learning_rate": learning_rate,  # 学习率
        "l2": l2,  # L2正则化系数
        "iterations_source": iterations_source,  # iterations来源
        "learning_rate_source": lr_source,  # learning_rate来源
        "l2_source": l2_source,  # l2来源
    }


def load_rows(path: Path) -> list[dict]:
    """
    加载CSV文件

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表（每行是一个字典）
    """
    # 设置CSV字段大小限制，避免大字段导致解析错误
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件，使用DictReader解析为字典列表（每行是一个字典）
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def resolve_atomic_calibration_split_rows(
    args: argparse.Namespace,
    fallback_rows: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    """
    解析 full-diff calibration 的互斥 split 输入。

    在 strict runner 路径下，必须显式提供 protocol/train/calibration/evaluation 四类 split。
    """
    protocol_input = str(getattr(args, "protocol_input", "") or "").strip()
    train_input = str(getattr(args, "gbdt_train_input", "") or "").strip()
    calibration_input = str(getattr(args, "calibration_input", "") or "").strip()
    evaluation_input = str(getattr(args, "evaluation_input", "") or "").strip()
    split_plan_json = str(getattr(args, "annotated_split_plan_json", "") or "").strip()
    split_inputs = [protocol_input, train_input, calibration_input, evaluation_input]
    if any(split_inputs):
        if not all(split_inputs):
            raise ValueError(
                "full-diff calibration requires protocol/train/calibration/evaluation split inputs together"
            )
        protocol_rows = load_rows(Path(protocol_input))
        train_rows = load_rows(Path(train_input))
        calibration_rows = load_rows(Path(calibration_input))
        evaluation_rows = load_rows(Path(evaluation_input))
        split_summary = (
            json.loads(Path(split_plan_json).read_text(encoding="utf-8"))
            if split_plan_json
            else {}
        )
        if split_summary:
            annotated_split_protocol.assert_rows_match_split(
                rows=protocol_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "protocol"
                ),
                split_name="protocol",
                context="full-diff protocol derivation",
            )
            annotated_split_protocol.assert_rows_match_split(
                rows=train_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "gbdt_train"
                ),
                split_name="gbdt_train",
                context="full-diff gbdt training",
            )
            annotated_split_protocol.assert_rows_match_split(
                rows=calibration_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "calibration"
                ),
                split_name="calibration",
                context="full-diff calibration fitting",
            )
            annotated_split_protocol.assert_rows_match_split(
                rows=evaluation_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "evaluation"
                ),
                split_name="evaluation",
                context="full-diff threshold selection",
            )
        split_roles = {
            "protocol": {
                "source_csv": protocol_input,
                "summary": (split_summary.get("splits") or {}).get("protocol", {}),
            },
            "gbdt_train": {
                "source_csv": train_input,
                "summary": (split_summary.get("splits") or {}).get("gbdt_train", {}),
            },
            "calibration": {
                "source_csv": calibration_input,
                "summary": (split_summary.get("splits") or {}).get("calibration", {}),
            },
            "evaluation": {
                "source_csv": evaluation_input,
                "summary": (split_summary.get("splits") or {}).get("evaluation", {}),
            },
            "split_plan_json": split_plan_json,
        }
        return protocol_rows, train_rows, calibration_rows, evaluation_rows, split_roles
    if not fallback_rows:
        raise ValueError(
            "full-diff calibration requires either split inputs or a non-empty --input"
        )
    return fallback_rows, fallback_rows, fallback_rows, fallback_rows, {}


def brier_score(probs: list[float], labels: list[int]) -> float:
    """
    计算Brier Score

    Brier Score是概率预测质量的度量，公式：
    BS = (1/N) * sum((probability - label)^2)

    值越小表示预测越准确，范围[0, 1]。

    参数:
        probs: 预测概率列表
        labels: 真实标签列表（0或1）

    返回:
        float: Brier Score
    """
    # 累加每个样本的预测误差平方 (probability - label)^2
    total = 0.0
    for p, y in zip(probs, labels):
        total += (p - y) ** 2
    # 除以样本数得到平均值（0/1分类问题中N至少为1）
    return total / max(len(labels), 1)


def log_loss(probs: list[float], labels: list[int]) -> float:
    """
    计算对数损失（Log Loss）

    公式：LL = -(1/N) * sum(y*log(p) + (1-y)*log(1-p))

    值越小表示预测越准确，范围[0, +∞)。

    参数:
        probs: 预测概率列表
        labels: 真实标签列表（0或1）

    返回:
        float: Log Loss
    """
    # 累加交叉熵损失
    total = 0.0
    for p, y in zip(probs, labels):
        # 裁剪概率到(epsilon, 1-epsilon)避免log(0)或log(负数)
        p_clip = clip_prob(p)
        # 交叉熵公式：y*log(p) + (1-y)*log(1-p)
        # 当y=1时，项为log(p)；当y=0时，项为log(1-p)
        total += -(y * math.log(p_clip) + (1 - y) * math.log(1 - p_clip))
    # 除以样本数得到平均值
    return total / max(len(labels), 1)


def compute_threshold_coverage_metrics(
    *,
    probs: list[float],
    labels: list[int],
    tau_a: float,
    tau_b: float,
) -> dict:
    positive_support = sum(1 for label in labels if int(label) == 1)
    tier_a_positive = sum(
        1
        for prob, label in zip(probs, labels)
        if int(label) == 1 and float(prob) > float(tau_a)
    )
    tier_b_or_higher_positive = sum(
        1
        for prob, label in zip(probs, labels)
        if int(label) == 1 and float(prob) > float(tau_b)
    )
    tier_a_predicted = sum(1 for prob in probs if float(prob) > float(tau_a))
    tier_b_predicted = sum(1 for prob in probs if float(prob) > float(tau_b))
    return {
        "positive_support": positive_support,
        "tier_a_predicted_count": tier_a_predicted,
        "tier_b_or_higher_predicted_count": tier_b_predicted,
        "tier_a_positive_recall": (
            tier_a_positive / positive_support if positive_support else None
        ),
        "tier_b_or_higher_positive_recall": (
            tier_b_or_higher_positive / positive_support if positive_support else None
        ),
    }


def compare_rule_only_vs_model_metrics(
    *,
    rule_labels: list[int | None],
    model_probs: list[float],
    gold_labels: list[int],
    tau_a: float,
) -> dict:
    rule_positive_indices = [
        index for index, label in enumerate(rule_labels) if label == 1
    ]
    model_positive_indices = [
        index for index, prob in enumerate(model_probs) if float(prob) > float(tau_a)
    ]
    gold_positive_indices = [
        index for index, label in enumerate(gold_labels) if int(label) == 1
    ]
    rule_true_positive = sum(
        1 for index in rule_positive_indices if int(gold_labels[index]) == 1
    )
    model_true_positive = sum(
        1 for index in model_positive_indices if int(gold_labels[index]) == 1
    )
    gold_positive_count = len(gold_positive_indices)
    return {
        "rule_positive_count": len(rule_positive_indices),
        "model_positive_count": len(model_positive_indices),
        "gold_positive_count": gold_positive_count,
        "rule_positive_precision": (
            rule_true_positive / len(rule_positive_indices)
            if rule_positive_indices
            else None
        ),
        "rule_positive_recall": (
            rule_true_positive / gold_positive_count if gold_positive_count else None
        ),
        "model_positive_precision": (
            model_true_positive / len(model_positive_indices)
            if model_positive_indices
            else None
        ),
        "model_positive_recall": (
            model_true_positive / gold_positive_count if gold_positive_count else None
        ),
        "rule_abstain_rate": (
            sum(1 for label in rule_labels if label is None) / len(rule_labels)
            if rule_labels
            else None
        ),
    }


RULE_ADJACENT_FEATURES = {
    "file_count",
    "module_count",
    "file_role_purity",
    "has_single_prefix",
    "multi_intent_markers",
    "single_issue_link",
    "doc_or_test_only",
    "repo_norm_size",
    "repo_norm_module_span",
}


def derive_feature_reduced_order(feature_order: list[str]) -> list[str]:
    reduced_order = [
        name for name in feature_order if str(name) not in RULE_ADJACENT_FEATURES
    ]
    if not reduced_order:
        raise ValueError("feature-reduced ablation removed every feature")
    return reduced_order


def _project_feature_rows(
    feature_rows: list[list[float]],
    *,
    source_feature_order: list[str],
    target_feature_order: list[str],
) -> list[list[float]]:
    index_by_name = {str(name): idx for idx, name in enumerate(source_feature_order)}
    target_indices = [index_by_name[str(name)] for name in target_feature_order]
    return [[float(row[idx]) for idx in target_indices] for row in feature_rows]


def build_feature_reduced_model_ablation(
    *,
    feature_order: list[str],
    weak_feature_rows: list[list[float]],
    weak_labels: list[int],
    weak_sample_weights: list[float],
    calibration_feature_rows: list[list[float]],
    calibration_labels: list[int],
    evaluation_feature_rows: list[list[float]],
    evaluation_labels: list[int],
    evaluation_rule_labels: list[int | None],
    n_estimators: int,
    max_depth: int,
    learning_rate: float,
    random_state: int,
    tau_a_precision: float,
    tau_b_precision: float,
    threshold_fallback_policy: str,
) -> dict:
    reduced_feature_order = derive_feature_reduced_order(feature_order)
    removed_features = [
        name for name in feature_order if name not in reduced_feature_order
    ]
    reduced_weak_rows = _project_feature_rows(
        weak_feature_rows,
        source_feature_order=feature_order,
        target_feature_order=reduced_feature_order,
    )
    reduced_calibration_rows = _project_feature_rows(
        calibration_feature_rows,
        source_feature_order=feature_order,
        target_feature_order=reduced_feature_order,
    )
    reduced_evaluation_rows = _project_feature_rows(
        evaluation_feature_rows,
        source_feature_order=feature_order,
        target_feature_order=reduced_feature_order,
    )
    reduced_model = GradientBoostingClassifier(
        n_estimators=int(n_estimators),
        max_depth=int(max_depth),
        learning_rate=float(learning_rate),
        random_state=random_state,
    )
    reduced_model.fit(
        reduced_weak_rows,
        weak_labels,
        sample_weight=weak_sample_weights,
    )
    reduced_raw_probs_labeled = [
        float(item[1]) for item in reduced_model.predict_proba(reduced_calibration_rows)
    ]
    reduced_evaluation_raw_probs = [
        float(item[1]) for item in reduced_model.predict_proba(reduced_evaluation_rows)
    ]
    isotonic = IsotonicRegression(out_of_bounds="clip")
    isotonic.fit(reduced_raw_probs_labeled, calibration_labels)
    reduced_eval_probs = [
        float(value) for value in isotonic.predict(reduced_evaluation_raw_probs)
    ]
    fallback_tau_a, fallback_tau_b = miner.derive_threshold_seed_from_distribution(
        reduced_eval_probs
    )
    tau_a_report = select_threshold_by_precision_report(
        reduced_eval_probs,
        evaluation_labels,
        target_precision=tau_a_precision,
        fallback=fallback_tau_a,
    )
    tau_b_report = select_threshold_by_precision_report(
        reduced_eval_probs,
        evaluation_labels,
        target_precision=tau_b_precision,
        fallback=fallback_tau_b,
        upper_bound=tau_a_report.threshold,
    )
    selection_reports = {
        "tau_a": threshold_report_to_dict(tau_a_report),
        "tau_b": threshold_report_to_dict(tau_b_report),
    }
    apply_threshold_fallback_policy(selection_reports, policy=threshold_fallback_policy)
    tau_a = tau_a_report.threshold
    tau_b = tau_b_report.threshold
    adjusted_for_gap = False
    if tau_b >= tau_a:
        tau_a = max(tau_a, fallback_tau_a)
        tau_b = min(tau_b, fallback_tau_b)
        if tau_b >= tau_a:
            raise ValueError(
                "feature-reduced threshold selection failed: tau_b >= tau_a after repair"
            )
        adjusted_for_gap = True
    return {
        "removed_features": removed_features,
        "feature_order": reduced_feature_order,
        "removed_feature_count": len(removed_features),
        "retained_feature_count": len(reduced_feature_order),
        "thresholds": {
            "tau_a": tau_a,
            "tau_b": tau_b,
            "target_precision_a": tau_a_precision,
            "target_precision_b": tau_b_precision,
            "achieved_precision_a": tau_a_report.achieved_precision,
            "achieved_precision_b": tau_b_report.achieved_precision,
            "selection_reports": selection_reports,
            "fallback_policy": threshold_fallback_policy,
            "adjusted_for_gap": adjusted_for_gap,
        },
        "raw_brier_eval": brier_score(reduced_evaluation_raw_probs, evaluation_labels),
        "calibrated_brier_eval": brier_score(reduced_eval_probs, evaluation_labels),
        "raw_logloss_eval": log_loss(reduced_evaluation_raw_probs, evaluation_labels),
        "calibrated_logloss_eval": log_loss(reduced_eval_probs, evaluation_labels),
        "coverage_metrics": compute_threshold_coverage_metrics(
            probs=reduced_eval_probs,
            labels=evaluation_labels,
            tau_a=tau_a,
            tau_b=tau_b,
        ),
        "reliability_report": build_reliability_report(
            probs=reduced_eval_probs,
            labels=evaluation_labels,
            bins=10,
        ),
        "rule_only_vs_model": compare_rule_only_vs_model_metrics(
            rule_labels=evaluation_rule_labels,
            model_probs=reduced_eval_probs,
            gold_labels=evaluation_labels,
            tau_a=tau_a,
        ),
    }


def build_reliability_report(
    *,
    probs: list[float],
    labels: list[int],
    bins: int = 10,
) -> dict:
    if not probs or len(probs) != len(labels):
        return {"ece": None, "mce": None, "bins": []}
    clipped = [clip_prob(float(prob)) for prob in probs]
    n_bins = max(1, int(bins))
    bucket_rows: list[dict] = []
    ece = 0.0
    mce = 0.0
    total = len(clipped)
    for bucket_index in range(n_bins):
        lower = bucket_index / n_bins
        upper = (bucket_index + 1) / n_bins
        bucket_items = [
            (prob, int(label))
            for prob, label in zip(clipped, labels)
            if (prob >= lower and prob < upper)
            or (bucket_index == n_bins - 1 and prob <= upper)
        ]
        if not bucket_items:
            bucket_rows.append(
                {
                    "bin_index": bucket_index,
                    "lower": round(lower, 6),
                    "upper": round(upper, 6),
                    "count": 0,
                    "avg_confidence": None,
                    "empirical_accuracy": None,
                    "absolute_gap": None,
                }
            )
            continue
        avg_conf = sum(item[0] for item in bucket_items) / len(bucket_items)
        emp_acc = sum(item[1] for item in bucket_items) / len(bucket_items)
        gap = abs(avg_conf - emp_acc)
        ece += (len(bucket_items) / total) * gap
        mce = max(mce, gap)
        bucket_rows.append(
            {
                "bin_index": bucket_index,
                "lower": round(lower, 6),
                "upper": round(upper, 6),
                "count": len(bucket_items),
                "avg_confidence": round(avg_conf, 6),
                "empirical_accuracy": round(emp_acc, 6),
                "absolute_gap": round(gap, 6),
            }
        )
    return {
        "ece": round(ece, 6),
        "mce": round(mce, 6),
        "bins": bucket_rows,
    }


def fit_platt_scaler(
    logits: list[float],
    labels: list[int],
    iterations: int,
    learning_rate: float,
    l2: float,
) -> tuple[float, float]:
    """
    拟合Platt Scaling参数

    使用梯度下降优化Platt scaling的参数：
    p = sigmoid(slope * logit + intercept)

    参数:
        logits: logit值列表
        labels: 标签列表（0或1）
        iterations: 迭代次数
        learning_rate: 学习率
        l2: L2正则化系数

    返回:
        tuple[float, float]: (slope, intercept)
    """
    # 初始化Platt参数：slope=1.0, intercept=0.0
    slope = 1.0
    intercept = 0.0
    n = len(logits)  # 样本数量

    # 迭代优化Platt参数
    for _ in range(iterations):
        grad_slope = 0.0  # slope的梯度
        grad_intercept = 0.0  # intercept的梯度

        # 遍历所有样本，计算梯度
        for logit, label in zip(logits, labels):
            # 计算预测概率：sigmoid(slope * logit + intercept)
            prob = sigmoid(slope * logit + intercept)
            # 计算预测误差
            error = prob - label
            # 累加slope的梯度（误差 * logit）
            grad_slope += error * logit
            # 累加intercept的梯度（误差 * 1）
            grad_intercept += error

        # 计算平均梯度并加上L2正则化
        grad_slope = grad_slope / n + l2 * slope
        grad_intercept = grad_intercept / n

        # 梯度下降更新参数
        slope -= learning_rate * grad_slope
        intercept -= learning_rate * grad_intercept

    return slope, intercept


def derive_weak_label_protocol(
    parsed_rows: list[dict],
    message_protocol: dict | None = None,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> WeakLabelProtocol:
    """
    从原始消息/结构统计量派生独立规则弱标签协议。

    该协议完全不依赖 `atomic_prior()`、`atomic_logit()` 或其任何变体。
    只使用可解释的消息与结构量，优先保证高精度，允许大量 abstain。

    参数:
        parsed_rows: 解析后的数据行（包含message_features, diff_features, type, repo）
        message_protocol: 消息协议字典（可选）
        scope_protocol: 范围协议字典（可选）
        type_protocol: 类型协议字典（可选）

    返回:
        WeakLabelProtocol: 弱标签协议数据类
    """
    # === 步骤1: 收集结构统计量 ===
    normalized_file_counts: list[float] = []  # 归一化文件数
    normalized_module_counts: list[float] = []  # 归一化模块数
    role_cardinality: list[float] = []  # 角色基数（角色数量）
    normalized_patch_sizes: list[float] = []  # 归一化patch大小（changed_lines）

    repo_stats = miner.compute_repo_feature_stats(parsed_rows)
    global_stats = miner.compute_global_feature_stats(parsed_rows)

    for item in parsed_rows:
        diff_features = item["diff_features"]
        file_count = float(diff_features.get("file_count", 0))
        module_count = float(diff_features.get("module_count", 0))
        patch_size = float(diff_features.get("changed_lines", 0))
        role_cardinality.append(float(len(diff_features.get("roles", []))))  # 角色数量
        repo_name = item.get("repo", "")
        normalized_file_counts.append(
            _normalized_diff_feature(
                repo=repo_name,
                feature_name="file_count",
                raw_value=file_count,
                repo_stats=repo_stats,
                global_stats=global_stats,
            )
        )
        normalized_module_counts.append(
            _normalized_diff_feature(
                repo=repo_name,
                feature_name="module_count",
                raw_value=module_count,
                repo_stats=repo_stats,
                global_stats=global_stats,
            )
        )
        normalized_patch_sizes.append(
            _normalized_diff_feature(
                repo=repo_name,
                feature_name="changed_lines",
                raw_value=patch_size,
                repo_stats=repo_stats,
                global_stats=global_stats,
            )
        )

    # === 步骤2: 派生保守阳性结构阈值 ===
    file_focus_norm_cutoff, file_norm_source = derive_small_cluster_upper_bound(
        values=normalized_file_counts,
        fallback=quantile_value(
            normalized_file_counts,
            q=0.35,
            default=max(normalized_file_counts) if normalized_file_counts else 0.0,
        ),
    )
    module_focus_norm_cutoff, module_norm_source = derive_small_cluster_upper_bound(
        values=normalized_module_counts,
        fallback=quantile_value(
            normalized_module_counts,
            q=0.35,
            default=max(normalized_module_counts) if normalized_module_counts else 0.0,
        ),
    )
    patch_focus_norm_cutoff, patch_norm_source = derive_small_cluster_upper_bound(
        values=normalized_patch_sizes,
        fallback=quantile_value(
            normalized_patch_sizes,
            q=0.35,
            default=max(normalized_patch_sizes) if normalized_patch_sizes else 0.0,
        ),
    )
    role_pure_cutoff, role_pure_source = derive_small_cluster_upper_bound(
        values=role_cardinality,
        fallback=quantile_value(
            role_cardinality,
            q=0.40,
            default=max(role_cardinality) if role_cardinality else 1.0,
        ),
    )

    # === 步骤3: 派生明确阴性结构阈值 ===
    wide_file_norm_cutoff, wide_file_norm_source = derive_high_cluster_lower_bound(
        values=normalized_file_counts,
        fallback=quantile_value(
            normalized_file_counts,
            q=0.75,
            default=max(normalized_file_counts) if normalized_file_counts else 0.0,
        ),
    )
    wide_patch_norm_cutoff, wide_patch_norm_source = derive_high_cluster_lower_bound(
        values=normalized_patch_sizes,
        fallback=quantile_value(
            normalized_patch_sizes,
            q=0.75,
            default=max(normalized_patch_sizes) if normalized_patch_sizes else 0.0,
        ),
    )
    role_conflict_cutoff, role_source = derive_high_cluster_lower_bound(
        values=role_cardinality,
        fallback=quantile_value(
            role_cardinality,
            q=0.70,
            default=max(role_cardinality) if role_cardinality else 0.0,
        ),
    )
    module_conflict_norm_cutoff, module_conflict_norm_source = (
        derive_high_cluster_lower_bound(
            values=normalized_module_counts,
            fallback=quantile_value(
                normalized_module_counts,
                q=0.75,
                default=max(normalized_module_counts)
                if normalized_module_counts
                else 0.0,
            ),
        )
    )

    return WeakLabelProtocol(
        version="independent_rule_protocol_v1",
        positive_file_count_max=float(file_focus_norm_cutoff),  # 阳性最大文件数
        positive_module_count_max=float(module_focus_norm_cutoff),  # 阳性最大模块数
        positive_patch_size_max=float(patch_focus_norm_cutoff),  # 阳性最大 patch
        positive_role_count_max=max(
            1, int(math.ceil(role_pure_cutoff))
        ),  # 阳性最大角色数
        negative_file_count_min=float(wide_file_norm_cutoff),  # 阴性最小文件数
        negative_module_count_min=float(module_conflict_norm_cutoff),  # 阴性最小模块数
        negative_patch_size_min=float(wide_patch_norm_cutoff),  # 阴性最小 patch
        negative_role_count_min=max(
            1, int(math.ceil(role_conflict_cutoff))
        ),  # 阴性最小角色数
        positive_issue_ref_max=1,
        negative_issue_ref_min=2,
        positive_subject_action_max=1,
        negative_subject_action_min=2,
        negative_structural_rule_min_fires=2,
        source=";".join(
            [
                "weak_label_source=independent_rule_protocol_v1",
                f"positive_file_focus={file_norm_source}",
                f"positive_module_focus={module_norm_source}",
                f"positive_patch_focus={patch_norm_source}",
                f"positive_role_focus={role_pure_source}",
                f"negative_wide_file={wide_file_norm_source}",
                f"negative_wide_patch={wide_patch_norm_source}",
                f"role_conflict={role_source}",
                f"module_conflict={module_conflict_norm_source}",
            ]
        ),
    )


def negative_structural_conflict(
    message_features: dict,
    diff_features: dict,
    protocol: WeakLabelProtocol,
    normalized_file_count: float,
    normalized_patch_size: float,
    normalized_module_count: float,
) -> bool:
    """
    判断是否命中结构负样本规则。
    """
    issue_ref_count = int(message_features.get("issue_ref_count", 0))
    subject_action_count = estimate_subject_action_count(
        str(message_features.get("subject_line", ""))
    )
    role_count = len(set(diff_features.get("roles", [])))
    structural_rule_fires = 0
    if normalized_file_count >= protocol.negative_file_count_min:
        structural_rule_fires += 1
    if normalized_module_count >= protocol.negative_module_count_min:
        structural_rule_fires += 1
    if normalized_patch_size >= protocol.negative_patch_size_min:
        structural_rule_fires += 1
    if role_count >= protocol.negative_role_count_min:
        structural_rule_fires += 1
    if issue_ref_count >= protocol.negative_issue_ref_min:
        structural_rule_fires += 1
    if subject_action_count >= protocol.negative_subject_action_min:
        structural_rule_fires += 1
    return structural_rule_fires >= protocol.negative_structural_rule_min_fires


def weak_label_and_weight(
    message_features: dict,
    diff_features: dict,
    candidate_type: str,
    protocol: WeakLabelProtocol,
    normalized_file_count: float,
    normalized_module_count: float,
    normalized_patch_size: float,
) -> tuple[int | None, str, dict]:
    """
    按独立规则协议生成三值弱标签和可审计规则报告。
    """
    issue_ref_count = int(message_features.get("issue_ref_count", 0))
    subject_action_count = estimate_subject_action_count(
        str(message_features.get("subject_line", ""))
    )
    role_count = len(set(diff_features.get("roles", [])))

    positive_rules = {
        "substantive_type": candidate_type in SUBSTANTIVE_TYPE_SET,
        "conventional_prefix": bool(message_features.get("prefix_match")),
        "no_multi_intent_markers": not bool(message_features.get("has_multi_markers")),
        "no_noisy_markers": not bool(message_features.get("has_noisy_markers")),
        "not_release_like": not bool(message_features.get("release_like")),
        "single_subject_action": subject_action_count
        <= protocol.positive_subject_action_max,
        "issue_linkage_simple": issue_ref_count <= protocol.positive_issue_ref_max,
        "compact_file_scope": normalized_file_count <= protocol.positive_file_count_max,
        "compact_module_scope": normalized_module_count
        <= protocol.positive_module_count_max,
        "compact_patch_scope": normalized_patch_size
        <= protocol.positive_patch_size_max,
        "role_purity": role_count <= protocol.positive_role_count_max,
    }
    positive_rules_fired = [name for name, enabled in positive_rules.items() if enabled]

    negative_explicit_rules = {
        "negative_type": candidate_type in NEGATIVE_TYPE_SET,
        "multi_intent_markers": bool(message_features.get("has_multi_markers")),
        "noisy_markers": bool(message_features.get("has_noisy_markers")),
        "release_like": bool(message_features.get("release_like")),
    }
    negative_structural_rules = {
        "multi_subject_actions": subject_action_count
        >= protocol.negative_subject_action_min,
        "multiple_issue_refs": issue_ref_count >= protocol.negative_issue_ref_min,
        "wide_file_scope": normalized_file_count >= protocol.negative_file_count_min,
        "wide_module_scope": normalized_module_count
        >= protocol.negative_module_count_min,
        "wide_patch_scope": normalized_patch_size >= protocol.negative_patch_size_min,
        "role_conflict": role_count >= protocol.negative_role_count_min,
    }
    explicit_negative_fires = [
        name for name, enabled in negative_explicit_rules.items() if enabled
    ]
    structural_negative_fires = [
        name for name, enabled in negative_structural_rules.items() if enabled
    ]
    negative_rules_fired = explicit_negative_fires + structural_negative_fires

    if all(positive_rules.values()):
        label = 1
        kind = "positive"
        label_name = "positive"
    elif explicit_negative_fires:
        label = 0
        kind = "negative_explicit"
        label_name = "negative"
    elif len(structural_negative_fires) >= protocol.negative_structural_rule_min_fires:
        label = 0
        kind = "negative_structural"
        label_name = "negative"
    else:
        label = None
        kind = "abstain"
        label_name = "abstain"

    report = {
        "protocol_version": protocol.version,
        "label_name": label_name,
        "decision_kind": kind,
        "positive_rules_fired": positive_rules_fired,
        "negative_rules_fired": negative_rules_fired,
        "subject_action_count": subject_action_count,
        "issue_ref_count": issue_ref_count,
        "role_count": role_count,
        "normalized_file_count": float(normalized_file_count),
        "normalized_module_count": float(normalized_module_count),
        "normalized_patch_size": float(normalized_patch_size),
    }
    return label, kind, report


def build_rule_labeled_examples(
    *,
    parsed_rows: list[dict],
    protocol: WeakLabelProtocol,
    repo_stats: dict[str, dict[str, dict[str, float]]] | None = None,
    global_stats: dict[str, dict[str, float]] | None = None,
) -> tuple[list[dict], dict]:
    """批量运行规则协议，生成训练前的弱标签记录和聚合报告。"""
    effective_repo_stats = (
        repo_stats
        if repo_stats is not None
        else miner.compute_repo_feature_stats(parsed_rows)
    )
    effective_global_stats = (
        global_stats
        if global_stats is not None
        else miner.compute_global_feature_stats(parsed_rows)
    )
    examples: list[dict] = []
    rule_reports: list[dict] = []

    for item in parsed_rows:
        repo_name = item.get("repo", "")
        normalized_file_count = _normalized_diff_feature(
            repo=repo_name,
            feature_name="file_count",
            raw_value=float(item["diff_features"].get("file_count", 0.0)),
            repo_stats=effective_repo_stats,
            global_stats=effective_global_stats,
        )
        normalized_module_count = _normalized_diff_feature(
            repo=repo_name,
            feature_name="module_count",
            raw_value=float(item["diff_features"].get("module_count", 0.0)),
            repo_stats=effective_repo_stats,
            global_stats=effective_global_stats,
        )
        normalized_patch_size = _normalized_diff_feature(
            repo=repo_name,
            feature_name="changed_lines",
            raw_value=float(item["diff_features"].get("changed_lines", 0.0)),
            repo_stats=effective_repo_stats,
            global_stats=effective_global_stats,
        )
        label, decision_kind, rule_report = weak_label_and_weight(
            item["message_features"],
            item["diff_features"],
            candidate_type=item["type"],
            protocol=protocol,
            normalized_file_count=normalized_file_count,
            normalized_module_count=normalized_module_count,
            normalized_patch_size=normalized_patch_size,
        )
        examples.append(
            {
                "row": item["row"],
                "label": label,
                "label_name": rule_report["label_name"],
                "decision_kind": decision_kind,
                "sample_weight": 1.0,
                "positive_rules_fired": list(rule_report["positive_rules_fired"]),
                "negative_rules_fired": list(rule_report["negative_rules_fired"]),
                "rule_report": rule_report,
            }
        )
        rule_reports.append(rule_report)

    return examples, summarize_rule_reports(rule_reports)


def run_platt_mode(args: argparse.Namespace, rows: list[dict]) -> dict:
    """
    运行Platt校准模式

    简单的Platt Scaling校准：
    1. 从标注数据提取logit和标签
    2. 使用梯度下降拟合Platt参数
    3. 生成校准JSON（包含platt_slope, platt_intercept）

    参数:
        args: 命令行参数
        rows: 数据行列表

    返回:
        dict: 校准结果字典
    """
    # 提取logit和标签数据
    logits: list[float] = []
    labels: list[int] = []
    for row in rows:
        # 跳过空logit值
        if row.get(args.logit_col, "") == "":
            continue
        # 解析标签，跳过无效标签
        label = resolve_training_label(row, label_col=args.label_col)
        if label is None:
            continue
        # 收集有效的logit和标签
        logits.append(safe_float(row.get(args.logit_col)))
        labels.append(label)

    # 检查是否有足够的标注数据
    if len(logits) < args.min_labeled:
        raise ValueError(
            f"not enough labeled rows for calibration (need at least {args.min_labeled})"
        )

    # 派生Platt超参数
    platt_hparams = derive_platt_hyperparams(
        n_samples=len(logits),
        iterations_arg=args.iterations,
        learning_rate_arg=args.platt_learning_rate,
        l2_arg=args.l2,
    )

    # 计算原始概率（sigmoid变换）
    raw_probs = [sigmoid(item) for item in logits]

    # 拟合Platt Scaling参数
    slope, intercept = fit_platt_scaler(
        logits,
        labels,
        iterations=int(platt_hparams["iterations"]),
        learning_rate=float(platt_hparams["learning_rate"]),
        l2=float(platt_hparams["l2"]),
    )

    # 应用Platt校准得到校准概率
    calibrated_probs = [sigmoid(slope * item + intercept) for item in logits]

    # 从校准概率分布派生初始阈值
    fallback_tau_a, fallback_tau_b = miner.derive_threshold_seed_from_distribution(
        calibrated_probs
    )

    # 根据目标精确率选择Tier A阈值
    tau_a_report = select_threshold_by_precision_report(
        calibrated_probs,
        labels,
        target_precision=args.tau_a_precision,
        fallback=fallback_tau_a,
    )
    # 根据目标精确率选择Tier B阈值（不能超过tau_a）
    tau_b_report = select_threshold_by_precision_report(
        calibrated_probs,
        labels,
        target_precision=args.tau_b_precision,
        fallback=fallback_tau_b,
        upper_bound=tau_a_report.threshold,
    )

    # 收集阈值报告
    threshold_reports = {
        "tau_a": threshold_report_to_dict(tau_a_report),
        "tau_b": threshold_report_to_dict(tau_b_report),
    }
    # 应用阈值回退策略
    apply_threshold_fallback_policy(
        threshold_reports, policy=args.threshold_fallback_policy
    )

    # 提取阈值和精确率
    tau_a = tau_a_report.threshold
    tau_b = tau_b_report.threshold
    tau_a_prec = tau_a_report.achieved_precision
    tau_b_prec = tau_b_report.achieved_precision

    # 检查并修复tau_b >= tau_a的情况
    adjusted_for_gap = False
    if tau_b >= tau_a:
        # 使用fallback值进行修复
        tau_a = max(tau_a, fallback_tau_a)
        tau_b = min(tau_b, fallback_tau_b)
        # 如果修复后仍然无效，抛出错误
        if tau_b >= tau_a:
            raise ValueError(
                "threshold selection failed: tau_b >= tau_a after distribution-seed repair"
            )
        adjusted_for_gap = True

    return {
        "artifact_version": "step1_platt_v1",  # 工件版本标识
        "model_mode": "full_diff",
        "model_role": "primary",
        "platt_slope": slope,  # Platt缩放斜率
        "platt_intercept": intercept,  # Platt缩放截距
        "thresholds": {
            "tau_a": tau_a,  # Tier A阈值
            "tau_b": tau_b,  # Tier B阈值
            "source": "constraint_from_labeled_precision_platt",  # 阈值来源
            "target_precision_a": args.tau_a_precision,  # Tier A目标精确率
            "target_precision_b": args.tau_b_precision,  # Tier B目标精确率
            "achieved_precision_a": tau_a_prec,  # Tier A实际精确率
            "achieved_precision_b": tau_b_prec,  # Tier B实际精确率
            "selection_reports": threshold_reports,  # 阈值选择报告
            "fallback_policy": args.threshold_fallback_policy,  # 回退策略
            "adjusted_for_gap": adjusted_for_gap,  # 是否调整过
        },
        "metrics": {
            "n": len(logits),  # 样本数量
            "positive_rate": sum(labels) / len(labels),  # 阳性比例
            "raw_brier": brier_score(raw_probs, labels),  # 原始Brier Score
            "calibrated_brier": brier_score(
                calibrated_probs, labels
            ),  # 校准后Brier Score
            "raw_logloss": log_loss(raw_probs, labels),  # 原始Log Loss
            "calibrated_logloss": log_loss(calibrated_probs, labels),  # 校准后Log Loss
        },
        "fit_config": {
            "mode": "platt",  # 校准模式
            "iterations": int(platt_hparams["iterations"]),  # 迭代次数
            "learning_rate": float(platt_hparams["learning_rate"]),  # 学习率
            "l2": float(platt_hparams["l2"]),  # L2正则化
            "iterations_source": str(platt_hparams["iterations_source"]),  # 来源
            "learning_rate_source": str(platt_hparams["learning_rate_source"]),  # 来源
            "l2_source": str(platt_hparams["l2_source"]),  # 来源
            "logit_col": args.logit_col,  # logit列名
            "label_col": args.label_col,  # 标签列名
            "source": args.input,  # 数据来源
            "threshold_fallback_policy": args.threshold_fallback_policy,  # 回退策略
        },
    }


def run_gbdt_isotonic_mode(args: argparse.Namespace, rows: list[dict]) -> dict:
    """
    运行GBDT+等渗回归校准模式

    解析行，生成弱标签，训练GBDT模型，使用等渗回归校准概率。

    参数:
        args: 命令行参数
        rows: 输入行列表

    返回:
        dict: 校准结果，包含模型、阈值、协议等
    """
    protocol_rows, train_rows, calibration_rows, evaluation_rows, split_roles = (
        resolve_atomic_calibration_split_rows(args, rows)
    )

    def parse_rows_for_stage(stage_rows: list[dict], stage_name: str) -> list[dict]:
        parsed_stage_rows = []
        for row in stage_rows:
            message = (
                row.get("commit_message")
                or row.get("message")
                or row.get("masked_commit_message")
                or ""
            )
            if not message:
                continue
            message_features = miner.parse_message(message)
            diff_features = miner.parse_diff(row.get("git_diff", ""))
            parsed_stage_rows.append(
                {
                    "row": row,
                    "message_features": message_features,
                    "diff_features": diff_features,
                    "type": row.get("annotated_type") or row.get("type", ""),
                    "repo": row.get("repo")
                    or row.get("resolved_repo")
                    or miner.extract_repo(row.get("commit_url", "")),
                }
            )
        if not parsed_stage_rows:
            raise ValueError(f"no usable rows for {stage_name}")
        invalid_diff_rows = [
            item
            for item in parsed_stage_rows
            if float(item["diff_features"].get("file_count", 0.0)) <= 0.0
            or float(item["diff_features"].get("changed_lines", 0.0)) <= 0.0
        ]
        if invalid_diff_rows:
            preview = [
                item["row"].get("sha", "")
                for item in invalid_diff_rows[:10]
                if item["row"].get("sha")
            ]
            raise ValueError(
                f"{stage_name} contains rows with invalid diff features "
                f"(count={len(invalid_diff_rows)}; examples={preview})"
            )
        return parsed_stage_rows

    protocol_parsed_rows = parse_rows_for_stage(protocol_rows, "protocol split")
    train_parsed_rows = parse_rows_for_stage(train_rows, "gbdt_train split")
    calibration_parsed_rows = parse_rows_for_stage(
        calibration_rows, "calibration split"
    )
    evaluation_parsed_rows = parse_rows_for_stage(evaluation_rows, "evaluation split")

    # === 步骤2: 计算特征统计量 ===
    protocol_repo_stats = miner.compute_repo_feature_stats(protocol_parsed_rows)
    protocol_global_feature_stats = miner.compute_global_feature_stats(
        protocol_parsed_rows
    )
    train_repo_stats = miner.compute_repo_feature_stats(train_parsed_rows)
    train_global_feature_stats = miner.compute_global_feature_stats(train_parsed_rows)

    # === 步骤3: 派生协议 ===
    message_protocol = miner.derive_message_protocol(
        [item["message_features"] for item in protocol_parsed_rows]
    )
    scope_protocol = miner.derive_scope_protocol(
        [item["diff_features"] for item in protocol_parsed_rows]
    )
    type_protocol = miner.derive_type_protocol(
        [item["type"] for item in protocol_parsed_rows]
    )

    # === 步骤4: 派生信号上下文 ===
    feature_order = list(miner.ATOMIC_FEATURE_ORDER)  # 特征顺序
    signal_context = miner.derive_atomic_signal_context(
        [
            miner.atomic_signal_map(
                message_features=item["message_features"],
                candidate_type=item["type"],
                diff_features=item["diff_features"],
                message_protocol=message_protocol,
                scope_protocol=scope_protocol,
                type_protocol=type_protocol,
            )
            for item in protocol_parsed_rows
        ]
    )

    # === 步骤5: 派生独立规则弱标签协议 ===
    weak_label_protocol = derive_weak_label_protocol(
        protocol_parsed_rows,
        message_protocol=message_protocol,
        scope_protocol=scope_protocol,
        type_protocol=type_protocol,
    )

    # === 步骤6: 生成规则弱标签训练数据 ===
    weak_label_examples, weak_label_rule_report = build_rule_labeled_examples(
        parsed_rows=train_parsed_rows,
        protocol=weak_label_protocol,
        repo_stats=protocol_repo_stats,
        global_stats=protocol_global_feature_stats,
    )
    X_weak: list[list[float]] = []  # 特征矩阵
    y_weak: list[int] = []  # 标签向量
    weak_label_kinds: list[str] = []  # 标签类型记录

    for item, weak_example in zip(train_parsed_rows, weak_label_examples):
        weak_label = weak_example["label"]
        weak_kind = str(weak_example["decision_kind"])
        if weak_label is None:
            continue
        feature_map = miner.build_atomic_feature_map(
            message_features=item["message_features"],
            candidate_type=item["type"],
            diff_features=item["diff_features"],
            repo_stats=train_repo_stats.get(item["repo"]),
            global_stats=train_global_feature_stats,
        )
        # 按特征顺序转换为向量
        vector = [float(feature_map.get(name, 0.0)) for name in feature_order]
        X_weak.append(vector)
        y_weak.append(int(weak_label))
        weak_label_kinds.append(weak_kind)

    # === 步骤7: 检查弱标签池大小 ===
    positives = sum(y_weak)  # 阳性样本数
    negatives = len(y_weak) - positives  # 阴性样本数
    if (
        len(X_weak) < MIN_WEAK_POOL_SIZE
        or positives < MIN_WEAK_CLASS_COUNT
        or negatives < MIN_WEAK_CLASS_COUNT
    ):
        raise ValueError(
            "weak label pool too small or imbalanced: "
            f"n={len(X_weak)}, pos={positives}, neg={negatives}; "
            "expand annotated dataset and rerun calibration"
        )

    # === 步骤8: 计算结构负样本上采样比例 ===
    structural_negative_count = sum(
        1 for kind in weak_label_kinds if kind == "negative_structural"
    )
    positive_count = sum(
        1
        for kind, label in zip(weak_label_kinds, y_weak)
        if kind == "positive" and label == 1
    )
    if args.hard_negative_upsample > 0:
        resolved_structural_negative_upsample = float(args.hard_negative_upsample)
        upsample_source = "fixed_from_args"
    else:
        # 自动推导：阳性样本数/结构负样本数，保证困难负样本不被淹没。
        resolved_structural_negative_upsample = max(
            1.0, positive_count / max(1, structural_negative_count)
        )
        upsample_source = "constraint_balance_positive_vs_structural_negative"

    # 构建样本权重：结构负样本上采样，其他权重为1
    w_weak: list[float] = []
    for weak_kind in weak_label_kinds:
        if weak_kind == "negative_structural":
            w_weak.append(resolved_structural_negative_upsample)
        else:
            w_weak.append(1.0)

    # === 步骤9: 派生GBDT超参数 ===
    derived_hparams = derive_gbdt_hyperparams(
        n_samples=len(X_weak),
        n_features=len(feature_order),
        n_estimators_arg=args.n_estimators,
        max_depth_arg=args.max_depth,
        learning_rate_arg=args.learning_rate,
    )

    # === 步骤10: 训练GBDT模型 ===
    model = GradientBoostingClassifier(
        n_estimators=int(derived_hparams["n_estimators"]),
        max_depth=int(derived_hparams["max_depth"]),
        learning_rate=float(derived_hparams["learning_rate"]),
        random_state=args.random_state,
    )
    # 使用样本权重训练，硬负例权重更高
    model.fit(X_weak, y_weak, sample_weight=w_weak)

    # === 步骤11: 计算认知不确定性参考 ===
    # 从弱标签数据中估计模型的认知不确定性分布
    weak_raw_probs = [float(item[1]) for item in model.predict_proba(X_weak)]
    weak_epistemic_values = [
        miner.estimate_model_epistemic_uncertainty(model, feature_vector=vector)
        for vector in X_weak
    ]
    epistemic_reference = derive_epistemic_reference(weak_epistemic_values)

    # === 步骤12: 收集标注数据 ===
    # 从parsed_rows中提取有标注的样本
    X_labeled: list[list[float]] = []  # 标注数据特征矩阵
    y_labeled: list[int] = []  # 标注数据标签
    raw_probs_labeled: list[float] = []  # 原始预测概率
    labeled_groups: list[str] = []  # 标注样本 repo group

    for item in calibration_parsed_rows:
        # 解析标注标签，跳过无效标签
        label = resolve_training_label(item["row"], label_col=args.label_col)
        if label is None:
            continue
        # 构建特征向量
        feature_map = miner.build_atomic_feature_map(
            message_features=item["message_features"],
            candidate_type=item["type"],
            diff_features=item["diff_features"],
            repo_stats=train_repo_stats.get(item["repo"]),
            global_stats=train_global_feature_stats,
        )
        vector = [float(feature_map.get(name, 0.0)) for name in feature_order]
        # 获取模型的原始预测概率
        raw_prob = float(model.predict_proba([vector])[0][1])
        X_labeled.append(vector)
        y_labeled.append(label)
        raw_probs_labeled.append(raw_prob)
        labeled_groups.append(
            item.get("repo", "") or f"sha::{item['row'].get('sha', '')}"
        )

    # === 步骤13: 初始化阈值和校准参数 ===
    isotonic_info: dict | None = None
    # 从弱标签概率分布派生初始阈值
    tau_a, tau_b = miner.derive_threshold_seed_from_distribution(weak_raw_probs)
    tau_a_prec = None  # Tier A实际精确率
    tau_b_prec = None  # Tier B实际精确率
    threshold_source = "distribution_from_weak_pool"  # 阈值来源
    threshold_reports: dict[str, dict] = {}  # 阈值选择报告
    adjusted_for_gap = False  # 是否调整过阈值间隙
    labeled_metrics: dict[str, object] = {
        "labeled_n": len(y_labeled),  # 标注样本数量
        "labeled_positive_rate": (sum(y_labeled) / len(y_labeled))
        if y_labeled
        else None,  # 标注阳性比例
    }
    calibration_protocol: dict[str, object] = {
        "requested_scheme": args.labeled_calibration_scheme,  # 请求的校准方案
        "used_scheme": "distribution_fallback",  # 实际使用的校准方案
        "threshold_fallback_policy": args.threshold_fallback_policy,  # 阈值回退策略
    }

    # === 步骤14: 基于标注数据进行概率校准和阈值选择 ===
    # 检查是否有足够的标注数据
    evaluation_feature_rows: list[list[float]] = []
    evaluation_labels: list[int] = []
    evaluation_raw_probs: list[float] = []
    evaluation_groups: list[str] = []
    evaluation_rule_examples, _ = build_rule_labeled_examples(
        parsed_rows=evaluation_parsed_rows,
        protocol=weak_label_protocol,
        repo_stats=protocol_repo_stats,
        global_stats=protocol_global_feature_stats,
    )
    for item in evaluation_parsed_rows:
        label = resolve_training_label(item["row"], label_col=args.label_col)
        if label is None:
            continue
        feature_map = miner.build_atomic_feature_map(
            message_features=item["message_features"],
            candidate_type=item["type"],
            diff_features=item["diff_features"],
            repo_stats=train_repo_stats.get(item["repo"]),
            global_stats=train_global_feature_stats,
        )
        vector = [float(feature_map.get(name, 0.0)) for name in feature_order]
        raw_prob = float(model.predict_proba([vector])[0][1])
        evaluation_feature_rows.append(vector)
        evaluation_labels.append(label)
        evaluation_raw_probs.append(raw_prob)
        evaluation_groups.append(
            item.get("repo", "") or f"sha::{item['row'].get('sha', '')}"
        )

    calibration_ready = len(y_labeled) >= args.min_labeled and len(set(y_labeled)) > 1
    evaluation_ready = (
        len(evaluation_labels) >= args.min_labeled and len(set(evaluation_labels)) > 1
    )
    if calibration_ready and evaluation_ready:
        isotonic = IsotonicRegression(out_of_bounds="clip")
        isotonic.fit(raw_probs_labeled, y_labeled)
        eval_probs = [float(value) for value in isotonic.predict(evaluation_raw_probs)]
        eval_labels = list(evaluation_labels)
        isotonic_info = {
            "x": [float(value) for value in isotonic.X_thresholds_],
            "y": [float(value) for value in isotonic.y_thresholds_],
            "n": len(y_labeled),
            "scheme": "explicit_calibration_split_then_evaluation_split",
        }
        calibration_repos = set(labeled_groups)
        evaluation_repos = set(evaluation_groups)
        evaluation_rule_labels = [
            example["label"]
            for example, item in zip(evaluation_rule_examples, evaluation_parsed_rows)
            if resolve_training_label(item["row"], label_col=args.label_col) is not None
        ]
        labeled_metrics.update(
            {
                "raw_brier_eval": brier_score(evaluation_raw_probs, evaluation_labels),
                "calibrated_brier_eval": brier_score(eval_probs, evaluation_labels),
                "raw_logloss_eval": log_loss(evaluation_raw_probs, evaluation_labels),
                "calibrated_logloss_eval": log_loss(eval_probs, evaluation_labels),
                "calibration_train_n": len(y_labeled),
                "threshold_eval_n": len(eval_labels),
                "repo_disjoint_eval": calibration_repos.isdisjoint(evaluation_repos),
                "calibration_train_repo_count": len(calibration_repos),
                "threshold_eval_repo_count": len(evaluation_repos),
            }
        )
        calibration_protocol.update(
            {
                "used_scheme": "explicit_annotated_split_protocol",
                "calibration_train_n": len(y_labeled),
                "threshold_eval_n": len(eval_labels),
                "repo_disjoint_eval": calibration_repos.isdisjoint(evaluation_repos),
                "calibration_train_repo_count": len(calibration_repos),
                "threshold_eval_repo_count": len(evaluation_repos),
            }
        )
        if eval_probs and len(set(eval_labels)) > 1:
            # 从校准概率分布派生初始阈值
            eval_fallback_tau_a, eval_fallback_tau_b = (
                miner.derive_threshold_seed_from_distribution(eval_probs)
            )
            # 根据目标精确率选择Tier A阈值
            tau_a_report = select_threshold_by_precision_report(
                eval_probs,
                eval_labels,
                target_precision=args.tau_a_precision,
                fallback=eval_fallback_tau_a,
            )
            # 根据目标精确率选择Tier B阈值
            tau_b_report = select_threshold_by_precision_report(
                eval_probs,
                eval_labels,
                target_precision=args.tau_b_precision,
                fallback=eval_fallback_tau_b,
                upper_bound=tau_a_report.threshold,
            )
            # 收集阈值报告
            threshold_reports = {
                "tau_a": threshold_report_to_dict(tau_a_report),
                "tau_b": threshold_report_to_dict(tau_b_report),
            }
            # 应用阈值回退策略
            apply_threshold_fallback_policy(
                threshold_reports, policy=args.threshold_fallback_policy
            )
            # 提取阈值和精确率
            tau_a = tau_a_report.threshold
            tau_b = tau_b_report.threshold
            tau_a_prec = tau_a_report.achieved_precision
            tau_b_prec = tau_b_report.achieved_precision
            threshold_source = f"constraint_from_labeled_precision_{calibration_protocol.get('used_scheme')}"
            # 检查并修复tau_b >= tau_a的情况
            if tau_b >= tau_a:
                tau_a = max(tau_a, eval_fallback_tau_a)
                tau_b = min(tau_b, eval_fallback_tau_b)
                if tau_b >= tau_a:
                    raise ValueError(
                        "threshold selection failed: tau_b >= tau_a after distribution-seed repair"
                    )
                adjusted_for_gap = True
            labeled_metrics["coverage_metrics"] = compute_threshold_coverage_metrics(
                probs=eval_probs,
                labels=eval_labels,
                tau_a=tau_a,
                tau_b=tau_b,
            )
            labeled_metrics["reliability_report"] = build_reliability_report(
                probs=eval_probs,
                labels=eval_labels,
                bins=10,
            )
            labeled_metrics["rule_only_vs_model"] = compare_rule_only_vs_model_metrics(
                rule_labels=evaluation_rule_labels,
                model_probs=eval_probs,
                gold_labels=eval_labels,
                tau_a=tau_a,
            )
            labeled_metrics["feature_reduced_model_ablation"] = (
                build_feature_reduced_model_ablation(
                    feature_order=feature_order,
                    weak_feature_rows=X_weak,
                    weak_labels=y_weak,
                    weak_sample_weights=w_weak,
                    calibration_feature_rows=X_labeled,
                    calibration_labels=y_labeled,
                    evaluation_feature_rows=evaluation_feature_rows,
                    evaluation_labels=eval_labels,
                    evaluation_rule_labels=evaluation_rule_labels,
                    n_estimators=int(derived_hparams["n_estimators"]),
                    max_depth=int(derived_hparams["max_depth"]),
                    learning_rate=float(derived_hparams["learning_rate"]),
                    random_state=args.random_state,
                    tau_a_precision=args.tau_a_precision,
                    tau_b_precision=args.tau_b_precision,
                    threshold_fallback_policy=args.threshold_fallback_policy,
                )
            )
        else:
            raise ValueError(
                "no valid evaluation split probabilities for threshold selection"
            )
    else:
        raise ValueError(
            "full-diff calibration requires separate calibration/evaluation splits with both classes"
        )
    if threshold_source == "distribution_from_weak_pool":
        raise ValueError(
            "strict calibration forbids distribution_from_weak_pool threshold source; "
            "provide enough labeled data/eval split for precision-constrained thresholds"
        )

    # === 步骤17: 序列化模型并返回结果 ===
    # 将GBDT模型序列化为Base64编码的pickle
    model_pickle_b64 = base64.b64encode(pickle.dumps(model)).decode("utf-8")

    return {
        "artifact_version": "step1_atomic_gbdt_isotonic_v1",  # 工件版本
        "model_mode": "full_diff",
        "model_role": "primary",
        "feature_order": feature_order,  # 特征顺序
        "signal_context": signal_context,  # 信号上下文
        "message_protocol": message_protocol,  # 消息协议
        "scope_protocol": scope_protocol,  # 范围协议
        "type_protocol": type_protocol,  # 类型协议
        "epistemic_reference": epistemic_reference,  # 认知不确定性参考
        "feature_norm_stats": {
            "global": train_global_feature_stats,  # 全局特征统计（仅来自 gbdt_train split）
        },
        "model_pickle_b64": model_pickle_b64,  # 序列化的模型
        "isotonic": isotonic_info,  # 等渗回归信息
        "thresholds": {
            "tau_a": tau_a,  # Tier A阈值
            "tau_b": tau_b,  # Tier B阈值
            "source": threshold_source,  # 阈值来源
            "target_precision_a": args.tau_a_precision,  # Tier A目标精确率
            "target_precision_b": args.tau_b_precision,  # Tier B目标精确率
            "achieved_precision_a": tau_a_prec,  # Tier A实际精确率
            "achieved_precision_b": tau_b_prec,  # Tier B实际精确率
            "selection_reports": threshold_reports,  # 阈值选择报告
            "fallback_policy": args.threshold_fallback_policy,  # 回退策略
            "adjusted_for_gap": adjusted_for_gap,  # 是否调整过间隙
        },
        "metrics": {
            "weak_train_n": len(X_weak),  # 弱标签训练样本数
            "weak_positive_rate": positives / len(X_weak),  # 弱标签阳性比例
            "weak_avg_raw_prob": sum(weak_raw_probs)
            / len(weak_raw_probs),  # 弱标签平均原始概率
            **labeled_metrics,  # 合并标注指标
        },
        "fit_config": {
            "mode": "gbdt_isotonic",  # 校准模式
            "source": args.input,  # 数据来源
            "label_col": args.label_col,  # 标签列名
            "label_usage_summary": {
                "gbdt_train": label_protocol.build_label_usage_summary(
                    [item["row"] for item in train_parsed_rows],
                    label_col=args.label_col,
                ),
                "calibration": label_protocol.build_label_usage_summary(
                    [item["row"] for item in calibration_parsed_rows],
                    label_col=args.label_col,
                ),
                "evaluation": label_protocol.build_label_usage_summary(
                    [item["row"] for item in evaluation_parsed_rows],
                    label_col=args.label_col,
                ),
            },
            "weak_label_source": weak_label_protocol.version,
            "weak_label_protocol_version": weak_label_protocol.version,
            "n_estimators": int(derived_hparams["n_estimators"]),  # 树数量
            "max_depth": int(derived_hparams["max_depth"]),  # 最大深度
            "learning_rate": float(derived_hparams["learning_rate"]),  # 学习率
            "n_estimators_source": derived_hparams["n_estimators_source"],  # 来源
            "max_depth_source": derived_hparams["max_depth_source"],  # 来源
            "learning_rate_source": derived_hparams["learning_rate_source"],  # 来源
            "random_state": args.random_state,  # 随机种子
            "negative_upsample": resolved_structural_negative_upsample,  # 结构负样本上采样比例
            "negative_upsample_source": upsample_source,  # 来源
            "structural_negative_count": structural_negative_count,  # 结构负样本数量
            "positive_count_for_upsample": positive_count,  # 用于上采样的阳性数
            "labeled_calibration_scheme": args.labeled_calibration_scheme,  # 标注校准方案
            "labeled_holdout_ratio": args.labeled_holdout_ratio,  # 留出比例
            "labeled_cv_folds": args.labeled_cv_folds,  # CV折数
            "threshold_fallback_policy": args.threshold_fallback_policy,  # 阈值回退策略
            "calibration_protocol": calibration_protocol,  # 校准协议详情
            "weak_label_rule_report": weak_label_rule_report,
            "weak_label_protocol": {  # 弱标签协议详情
                "version": weak_label_protocol.version,
                "positive_file_count_max": weak_label_protocol.positive_file_count_max,
                "positive_module_count_max": weak_label_protocol.positive_module_count_max,
                "positive_patch_size_max": weak_label_protocol.positive_patch_size_max,
                "positive_role_count_max": weak_label_protocol.positive_role_count_max,
                "negative_file_count_min": weak_label_protocol.negative_file_count_min,
                "negative_module_count_min": weak_label_protocol.negative_module_count_min,
                "negative_patch_size_min": weak_label_protocol.negative_patch_size_min,
                "negative_role_count_min": weak_label_protocol.negative_role_count_min,
                "positive_issue_ref_max": weak_label_protocol.positive_issue_ref_max,
                "negative_issue_ref_min": weak_label_protocol.negative_issue_ref_min,
                "positive_subject_action_max": weak_label_protocol.positive_subject_action_max,
                "negative_subject_action_min": weak_label_protocol.negative_subject_action_min,
                "negative_structural_rule_min_fires": weak_label_protocol.negative_structural_rule_min_fires,
                "source": weak_label_protocol.source,
            },
            "annotated_split_roles": split_roles,
        },
    }


def main() -> None:
    """
    主函数：执行原子性校准拟合

    流程：
    1. 加载输入数据
    2. 根据模式运行校准（platt或gbdt_isotonic）
    3. 写入校准结果（模型、阈值、协议）
    """
    # 解析命令行参数
    args = parse_args()
    # 加载CSV数据
    if (
        args.mode == "gbdt_isotonic"
        and not args.allow_legacy_single_split
        and not (
            args.protocol_input
            and args.gbdt_train_input
            and args.calibration_input
            and args.evaluation_input
        )
    ):
        raise ValueError(
            "full-diff calibration now requires explicit protocol/train/calibration/evaluation split inputs; "
            "pass --allow-legacy-single-split to bypass this guard"
        )
    rows = load_rows(Path(args.input)) if args.input else []

    # 根据模式选择并运行校准
    if args.mode == "platt":
        result = run_platt_mode(args, rows)
    else:
        result = run_gbdt_isotonic_mode(args, rows)

    # 确保输出目录存在
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 写入校准结果JSON
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 打印摘要信息
    print(f"mode={args.mode}")
    print(
        f"samples={result.get('metrics', {}).get('weak_train_n', result.get('metrics', {}).get('n', 0))}"
    )
    fit_config = result.get("fit_config", {})
    if isinstance(fit_config, dict) and fit_config.get("weak_label_source"):
        print(f"weak_label_source={fit_config.get('weak_label_source')}")
        print(
            f"weak_label_protocol_version={fit_config.get('weak_label_protocol_version')}"
        )
    tau_a_value = float(result.get("thresholds", {}).get("tau_a", float("nan")))
    tau_b_value = float(result.get("thresholds", {}).get("tau_b", float("nan")))
    print(f"tau_a={tau_a_value:.6f}")
    print(f"tau_b={tau_b_value:.6f}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
