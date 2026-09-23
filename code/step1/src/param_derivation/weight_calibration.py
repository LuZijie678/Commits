"""
权重校准模块

本模块提供原子性权重计算的工具函数，包括：
1. 认知不确定性参考派生（center和scale）
2. 原子性权重计算（结合概率和认知不确定性）
3. 批量权重派生

这些权重用于：
- 对候选进行加权排序
- 反映模型对预测的置信程度
- 在训练时作为样本权重
"""

from __future__ import annotations

import statistics
from typing import Sequence

from .uncertainty_utils import combined_confidence_weight


def derive_epistemic_reference(epistemic_values: Sequence[float]) -> dict[str, float]:
    """
    派生认知不确定性参考（center和scale）

    使用中位数作为中心，中位绝对偏差作为缩放因子。
    这种稳健统计量对异常值不敏感。

    参数:
        epistemic_values: 认知不确定性值序列

    返回:
        dict[str, float]: 包含center和scale的字典
    """
    # 将所有值限制为非负数，避免负值影响统计计算
    values = [max(0.0, float(item)) for item in epistemic_values]
    # 空输入时返回默认值，避免后续计算错误
    if not values:
        return {"center": 0.0, "scale": 1.0}

    # 使用中位数作为中心（稳健统计量，对异常值不敏感）
    center = statistics.median(values)
    # 计算每个值与中位数的绝对偏差，用于衡量离散程度
    deviations = [abs(item - center) for item in values]
    # 使用中位绝对偏差（MAD）作为缩放因子，对异常值更鲁棒
    scale = statistics.median(deviations) if deviations else 0.0

    # 如果MAD为0（所有值相同或只有一个值），使用标准差作为替代
    if scale <= 0.0:
        scale = statistics.pstdev(values) if len(values) > 1 else 1.0

    # 仍然为0，使用默认值1.0避免除零错误
    if scale <= 0.0:
        scale = 1.0

    return {"center": float(center), "scale": float(scale)}


def derive_atomic_weight(
    probability: float,
    epistemic_std: float = 0.0,
    epistemic_center: float = 0.0,
    epistemic_scale: float = 1.0,
) -> float:
    """
    派生原子性权重

    结合概率（aleatoric不确定性）和认知不确定性计算综合权重。

    参数:
        probability: 原子性概率
        epistemic_std: 认知不确定性标准差
        epistemic_center: 认知不确定性中心
        epistemic_scale: 认知不确定性缩放

    返回:
        float: 原子性权重 [0, 1]
    """
    # 调用uncertainty_utils中的组合置信权重函数
    # 结合aleatoric（概率的熵）和epistemic（模型不确定性）
    return combined_confidence_weight(
        probability=probability,
        epistemic_std=epistemic_std,
        epistemic_center=epistemic_center,
        epistemic_scale=epistemic_scale,
    )


def derive_atomic_weights(
    probabilities: Sequence[float],
    epistemic_values: Sequence[float] | None = None,
) -> list[float]:
    """
    派生批量原子性权重

    参数:
        probabilities: 概率序列
        epistemic_values: 认知不确定性序列（可选）

    返回:
        list[float]: 权重列表
    """
    # 初始化认知不确定性列表（默认为0，表示无不确定性）
    epistemic_list = [0.0 for _ in probabilities]
    # 如果提供了认知不确定性值，使用它们；否则保持为0
    if epistemic_values is not None:
        epistemic_list = [float(item) for item in epistemic_values]

    # 从所有认知���确定性值派生参考（center和scale），用于归一化
    reference = derive_epistemic_reference(epistemic_list)

    # 为每个概率计算权重，结合其原子性概率和认知不确定性
    return [
        derive_atomic_weight(
            probability=prob,  # 原子性概率
            epistemic_std=epi,  # 认知不确定性
            epistemic_center=reference["center"],  # 使用派生的中心
            epistemic_scale=reference["scale"],  # 使用派生的缩放
        )
        for prob, epi in zip(probabilities, epistemic_list)
    ]
