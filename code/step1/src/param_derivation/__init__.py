"""
参数派生工具包

本模块提供从数据分布自动派生实验参数的工具，用于：
1. 基于K-Means聚类的阈值边界派生
2. 基于分位数的范围协议计算
3. 认知不确定性参考值派生
4. 基于精确率约束的阈值选择
5. 组合置信权重计算

这些工具确保实验可复现且对审稿人友好，避免手工设置固定阈值。
"""

# 分布工具：从数据分布中自动派生阈值边界
from .distribution_utils import (
    derive_high_cluster_lower_bound,
    derive_small_cluster_upper_bound,
    derive_three_cluster_boundaries,
    derive_two_cluster_boundary,
)

# 阈值选择工具：基于精确率约束和不确定性预算选择阈值
from .threshold_selection import (
    ThresholdSelectionReport,
    TierThresholds,
    derive_gate_threshold_by_uncertainty,
    derive_tier_thresholds_from_distribution,
    select_threshold_by_precision,
    select_threshold_by_precision_report,
)

# 不确定性工具：计算熵和置信度权重
from .uncertainty_utils import (
    bernoulli_entropy,
    clip_prob,
    combined_confidence_weight,
    entropy_confidence_weight,
    normalized_entropy,
    normalized_epistemic,
)

# 权重校准工具：计算原子性权重
from .weight_calibration import (
    derive_atomic_weight,
    derive_atomic_weights,
    derive_epistemic_reference,
)
