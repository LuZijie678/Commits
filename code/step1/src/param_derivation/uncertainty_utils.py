"""
不确定性工具模块

本模块提供不确定性量化和权重计算的工具函数，包括：
1. 伯努利熵计算
2. 归一化熵
3. 认知不确定性（epistemic）标准化
4. 组合置信权重（结合 aleatoric 和 epistemic 不确定性）

这些工具用于：
- 基于熵的权重计算
- 模型不确定性估计
- 组合置信度评估
"""

from __future__ import annotations

import math

# 数值稳定性epsilon，防止除零和log(0)
EPS = 1e-8
# 熵归一化常数（以比特为单位），用于将自然对数熵转换为以比特为单位的熵
LOG2 = math.log(2.0)


def clip_prob(probability: float) -> float:
    """
    裁剪概率到有效范围

    参数:
        probability: 输入概率

    返回:
        float: 裁剪后的概率
    """
    # 将概率裁剪到(EPS, 1-EPS)范围，避免log(0)或log(1)导致的问题
    return min(1.0 - EPS, max(EPS, float(probability)))


def bernoulli_entropy(probability: float) -> float:
    """
    计算伯努利分布的熵

    H(p) = -p*log(p) - (1-p)*log(1-p)

    参数:
        probability: 概率值

    返回:
        float: 熵值（自然对数）
    """
    # 先裁剪到有效范围，避免数值问题
    p = clip_prob(probability)
    # 伯努利熵公式：-p*log(p) - (1-p)*log(1-p)
    return -(p * math.log(p) + (1.0 - p) * math.log(1.0 - p))


def normalized_entropy(probability: float) -> float:
    """
    归一化熵（以比特为单位）

    参数:
        probability: 概率值

    返回:
        float: 归一化熵 [0, 1]
    """
    # 除以log(2)将自然对数熵转换为以比特为单位的熵
    # 当p=0或p=1时熵为0（确定），当p=0.5时熵为1（最不确定）
    return bernoulli_entropy(probability) / LOG2


def entropy_confidence_weight(probability: float) -> float:
    """
    基于熵的置信权重 [0, 1]

    熵越高（不确定性越大）权重越低
    熵越低（确定性越大）权重越高

    参数:
        probability: 概率值

    返回:
        float: 置信权重 [0, 1]
    """
    # 1 - 归一化熵 = 置信度
    # p=0.5时熵最大(1)，置信度最低(0)
    # p=0或p=1时熵最小(0)，置信度最高(1)
    return 1.0 - normalized_entropy(probability)


def normalized_epistemic(epistemic_std: float, center: float, scale: float) -> float:
    """
    归一化认知不确定性

    使用缩放的tanh变换将标准差映射到[0, 1]

    参数:
        epistemic_std: 认知不确定性标准差
        center: 参考中心值（认知不确定性的典型值）
        scale: 参考缩放因子（认知不确定性的典型范围）

    返回:
        float: 归一化的认知不确定性 [0, 1]
    """
    # 缩放因子无效时返回0
    if scale <= EPS:
        return 0.0
    # 计算z-score：标准化到center周围
    z = max(0.0, (float(epistemic_std) - float(center)) / (float(scale) + EPS))
    # 使用z/(1+z)将正值映射到[0,1]，类似tanh的平滑性质
    return z / (1.0 + z)


def combined_confidence_weight(
    probability: float,
    epistemic_std: float = 0.0,
    epistemic_center: float = 0.0,
    epistemic_scale: float = 1.0,
) -> float:
    """
    组合置信权重

    结合 aleatoric（随机）不确定性和 epistemic（认知）不确定性
    得到综合的置信度权重

    公式: uncertainty = 1 - (1 - aleatoric) * (1 - epistemic)
          weight = 1 - uncertainty

    参数:
        probability: 概率值（用于计算 aleatoric 不确定性）
        epistemic_std: 认知不确定性标准差
        epistemic_center: 认知不确定性参考中心
        epistemic_scale: 认知不确定性参考缩放

    返回:
        float: 组合置信权重 [0, 1]
    """
    # 计算 aleatoric 不确定性（数据本身的随机性，由概率决定）
    aleatoric = normalized_entropy(probability)
    # 计算 epistemic 不确定性（模型认知的不足，由模型不确定性决定）
    epistemic = normalized_epistemic(
        epistemic_std=epistemic_std,
        center=epistemic_center,
        scale=epistemic_scale,
    )
    # 组合两种不确定性：两者都高时，总不确定性更高
    # 公式：1 - (1 - aleatoric) * (1 - epistemic) = aleatoric + epistemic - aleatoric * epistemic
    uncertainty = 1.0 - (1.0 - aleatoric) * (1.0 - epistemic)
    # 置信度 = 1 - 不确定性
    return 1.0 - uncertainty
