"""
阈值选择模块

本模块提供基于精确率约束和分布的阈值选择功能，包括：
1. Tier阈值派生（tau_a, tau_b）
2. 基于精确率报告的阈值选择
3. 基于不确定性预算的门控阈值选择

Tier阈值用于将候选分为三个等级：
- Tier A: 高置信度单意图候选
- Tier B: 中等置信度
- Tier C: 低置信度
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .distribution_utils import (
    clip01,
    derive_three_cluster_boundaries,
    mean,
    median,
    safe_sorted,
)
from .uncertainty_utils import normalized_entropy

# 最小聚类样本数，少于此值无法进行3簇聚类
MIN_CLUSTER_SAMPLES = 3
# 最小阈值边距，防止tau_a和tau_b过于接近导致分层不明显
MIN_THRESHOLD_MARGIN = 1e-6
# 最小回退gap，确保tau_a > tau_b以保证有效分层
MIN_FALLBACK_GAP = 0.05


@dataclass(frozen=True)
class TierThresholds:
    """
    Tier阈值数据结构

    包含Tier A和Tier B的阈值以及来源说明
    """

    tau_a: float  # Tier A阈值（大于此值为Tier A）
    tau_b: float  # Tier B阈值（大于此值为Tier B，小于等于tau_a为Tier B）
    source: str  # 来源说明


@dataclass(frozen=True)
class ThresholdSelectionReport:
    """
    阈值选择报告

    记录阈值选择的过程和结果
    """

    threshold: float  # 选择的阈值
    achieved_precision: float | None  # 达到的精确率
    source: str  # 来源说明
    used_fallback: bool  # 是否使用了回退
    support: int  # 支持样本数


def select_threshold_by_precision_report(
    probs: Sequence[float],
    labels: Sequence[int],
    target_precision: float,
    fallback: float,
    upper_bound: float | None = None,
) -> ThresholdSelectionReport:
    """
    基于精确率报告选择阈值

    扫描候选阈值（从高到低），找到满足目标精确率的阈值。
    如果找不到，则使用回退值。

    参数:
        probs: 概率列表
        labels: 标签列表（1为正例，0为负例）
        target_precision: 目标精确率（如0.9表示90%精确率）
        fallback: 回退阈值
        upper_bound: 可选的上界（确保tau_b < tau_a）

    返回:
        ThresholdSelectionReport: 阈值选择报告
    """
    # 将概率-标签配对，便于一起处理
    pairs = list(zip(probs, labels))
    # 获取所有唯一的概率值作为候选阈值（按从高到低排序）
    candidates = sorted({round(float(prob), 6) for prob, _ in pairs}, reverse=True)
    # 记录最佳支持样本数（用于回退时返回）
    best_support = 0

    # 遍历每个候选阈值，从高到低扫描
    for threshold in candidates:
        # 如果设置了上界，跳过超过上界的阈值（确保tau_b < tau_a）
        if upper_bound is not None and threshold >= upper_bound:
            continue

        # 初始化计数，用于统计该阈值下的精确率
        tp = 0  # 真阳性数：预测为正且实际为正
        fp = 0  # 假阳性数：预测为正但实际为负
        # 统计高于阈值的样本
        for prob, label in pairs:
            # 低于阈值，跳过该样本
            if prob <= threshold:
                continue
            # 实际为正例，计数真阳性
            if int(label) == 1:
                tp += 1
            # 实际为负例，计数假阳性
            else:
                fp += 1

        # 高于阈值的样本总数
        support = tp + fp
        # 无支持样本，继续下一个阈值
        if support == 0:
            continue

        # 更新最佳支持数
        best_support = max(best_support, support)
        # 计算精确率 = TP / (TP + FP)
        precision = tp / support

        # 如果精确率满足目标，返回该阈值
        if precision >= target_precision:
            return ThresholdSelectionReport(
                threshold=clip01(threshold),  # 裁剪到有效范围[0,1]
                achieved_precision=float(precision),  # 记录实际达到的精确率
                source="constraint_met",  # 成功满足约束
                used_fallback=False,
                support=support,
            )

    # 未找到满足目标的阈值，使用回退值
    return ThresholdSelectionReport(
        threshold=clip01(fallback),
        achieved_precision=None,  # 无法达到目标精确率
        source="fallback_target_precision_unmet",  # 回退原因：目标精确率未满足
        used_fallback=True,
        support=best_support,  # 返回最佳支持数供参考
    )


def select_threshold_by_precision(
    probs: Sequence[float],
    labels: Sequence[int],
    target_precision: float,
    fallback: float,
    upper_bound: float | None = None,
) -> tuple[float, float | None]:
    """
    基于精确率选择阈值（简化版）

    参数:
        probs: 概率列表
        labels: 标签列表
        target_precision: 目标精确率
        fallback: 回退阈值
        upper_bound: 可选的上界

    返回:
        tuple[float, float | None]: (阈值, 达到的精确率)
    """
    # 调用完整版函数并提取结果
    report = select_threshold_by_precision_report(
        probs=probs,
        labels=labels,
        target_precision=target_precision,
        fallback=fallback,
        upper_bound=upper_bound,
    )
    return report.threshold, report.achieved_precision


def derive_tier_thresholds_from_distribution(
    scores: Sequence[float],
    fallback_tau_a: float,
    fallback_tau_b: float,
) -> TierThresholds:
    """
    从分布派生Tier阈值

    使用三簇边界派生阈值；如果失败则使用稳健统计量。

    参数:
        scores: 分数序列（概率值）
        fallback_tau_a: tau_a回退值
        fallback_tau_b: tau_b回退值

    返回:
        TierThresholds: Tier阈值
    """
    # 将所有分数裁剪到有效范围[0,1]
    values = [clip01(item) for item in scores]
    # 样本数不足，无法进行有效的3簇聚类，使用回退值
    if len(values) < MIN_CLUSTER_SAMPLES:
        return TierThresholds(
            tau_a=clip01(fallback_tau_a),
            tau_b=clip01(fallback_tau_b),
            source="fallback_too_few_samples",
        )

    # 使用三簇聚类派生边界（tau_b对应低边界，tau_a对应高边界）
    tau_b, tau_a, source = derive_three_cluster_boundaries(
        values=values,
        fallback_low=fallback_tau_b,
        fallback_high=fallback_tau_a,
    )

    # 聚类失败时，使用回退值
    if source != "kmeans_3cluster":
        return TierThresholds(tau_a=clip01(tau_a), tau_b=clip01(tau_b), source=source)

    # 检查tau_a是否大于tau_b（确保有效分层），如果过于接近则使用稳健统计量
    if tau_a <= tau_b + MIN_THRESHOLD_MARGIN:
        # 使用中位数和均值作为替代方案
        ordered = safe_sorted(values)
        tau_b = median(ordered, default=fallback_tau_b)  # 中位数作为tau_b
        tau_a = mean(ordered, default=fallback_tau_a)  # 均值作为tau_a

        # 仍不满足要求，强制调整间距保证有效分层
        if tau_a <= tau_b + MIN_THRESHOLD_MARGIN:
            tau_a = clip01(max(fallback_tau_a, tau_b + MIN_FALLBACK_GAP))
            tau_b = clip01(min(fallback_tau_b, tau_a - MIN_FALLBACK_GAP))
            return TierThresholds(
                tau_a=tau_a, tau_b=tau_b, source="fallback_median_mean_adjusted"
            )

        return TierThresholds(
            tau_a=clip01(tau_a), tau_b=clip01(tau_b), source="fallback_median_mean"
        )

    # 成功派生有效阈值
    return TierThresholds(tau_a=clip01(tau_a), tau_b=clip01(tau_b), source=source)


def derive_gate_threshold_by_uncertainty(
    scores: Sequence[float],
    fixed_gate: float | None = None,
) -> tuple[float, str]:
    """
    基于不确定性预算派生门控阈值

    选择使得选中项的平均熵低于中位数熵预算的最低分数阈值。

    参数:
        scores: 分数序列
        fixed_gate: 固定的门控值（可选）

    返回:
        tuple[float, str]: (门控阈值, 来源说明)
    """
    # 用户指定了固定门控值，直接使用
    if fixed_gate is not None and fixed_gate > 0.0:
        return clip01(fixed_gate), "fixed_from_args"

    # 裁剪到有效范围
    values = [clip01(item) for item in scores]
    # 空输入返回默认值
    if not values:
        return 0.0, "fallback_empty_scores"

    # 计算每个分数的归一化熵（不确定性度量，值越高表示越不确定）
    entropies = [normalized_entropy(item) for item in values]
    # 熵预算 = 中位数熵（典型不确定性水平）
    entropy_budget = median(entropies, default=1.0)

    # 获取唯一分数并排序（从低到高）
    candidates = sorted(set(values))
    # 默认选择最低的作为最佳阈值
    best = candidates[0]

    # 从低到高扫描，选择使得选中样本平均熵不高于预算的阈值
    for threshold in candidates:
        # 筛选高于阈值的样本
        selected = [
            entropy for prob, entropy in zip(values, entropies) if prob >= threshold
        ]
        # 没有样本满足条件，继续下一个阈值
        if not selected:
            continue
        # 如果选中样本的平均熵低于预算，记录该阈值并退出
        if mean(selected, default=1.0) <= entropy_budget:
            best = threshold
            break  # 找到满足条件的最低阈值

    return clip01(best), "uncertainty_budget_median_entropy"
