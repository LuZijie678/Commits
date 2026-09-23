"""
分布工具函数模块

本模块提供基于数据分布自动派生参数的工具函数，主要用于：
1. 使用K-Means聚类派生阈值边界
2. 从数据分布中自适应选择分割点
3. 计算统计量（中位数、平均值等）

这些函数替代了手工设置的固定阈值，使参数选择更加鲁棒。
"""

from __future__ import annotations

from typing import Sequence

from sklearn.cluster import KMeans

# 可复现性随机种子，确保多次运行聚类结果一致
REPRODUCIBILITY_SEED = 42
# K-Means初始化方式，"auto"让sklearn自动选择合适的初始化方法
KMEANS_N_INIT = "auto"
# 最小两簇样本数，低于此值无法进行2簇聚类
MIN_TWO_CLUSTER_SAMPLES = 2
# 最小三簇样本数，低于此值无法进行3簇聚类
MIN_THREE_CLUSTER_SAMPLES = 3


def safe_sorted(values: Sequence[float]) -> list[float]:
    """
    安全排序：将值转换为浮点数并排序

    参数:
        values: 输入值序列

    返回:
        list[float]: 排序后的浮点数列表
    """
    # 将所有值转换为浮点数，确保类型一致
    cleaned = [float(item) for item in values]
    # 原地排序
    cleaned.sort()
    return cleaned


def median(values: Sequence[float], default: float = 0.5) -> float:
    """
    计算中位数

    参数:
        values: 值序列
        default: 空序列时的默认值

    返回:
        float: 中位数值
    """
    # 先排序
    ordered = safe_sorted(values)
    # 空序列检查
    if not ordered:
        return default
    n = len(ordered)
    middle = n // 2
    # 奇数个数，返回中间元素
    if n % 2 == 1:
        return ordered[middle]
    # 偶数个数，返回中间两个数的平均值
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def mean(values: Sequence[float], default: float = 0.0) -> float:
    """
    计算平均值

    参数:
        values: 值序列
        default: 空序列时的默认值

    返回:
        float: 平均值
    """
    # 空序列检查
    if not values:
        return default
    # 总和除以个数
    return float(sum(values) / len(values))


def clip01(value: float) -> float:
    """
    裁剪值到[0, 1]范围

    参数:
        value: 输入值

    返回:
        float: 裁剪后的值
    """
    # 先取上限再取下限，确保在[0,1]范围内
    return max(0.0, min(1.0, float(value)))


def _cluster_centers(values: Sequence[float], n_clusters: int) -> list[float] | None:
    """
    使用1D K-Means推断分布断点

    参数:
        values: 值序列
        n_clusters: 聚类数量

    返回:
        list[float] | None: 聚类中心列表或None（如果无法聚类）
    """
    # 转换为浮点数列表
    cleaned = [float(item) for item in values]
    # 检查样本数是否足够进行指定数量的聚类
    if n_clusters == 2 and len(cleaned) < MIN_TWO_CLUSTER_SAMPLES:
        return None
    if n_clusters == 3 and len(cleaned) < MIN_THREE_CLUSTER_SAMPLES:
        return None
    if len(cleaned) < n_clusters:
        return None
    # 创建KMeans模型，使用固定随机种子保证可复现性
    model = KMeans(
        n_clusters=n_clusters,
        random_state=REPRODUCIBILITY_SEED,
        n_init=KMEANS_N_INIT,
    )
    # 将1D数据转换为2D数组（sklearn要求每个样本一个特征向量）
    model.fit([[item] for item in cleaned])
    # 提取聚类中心并排序返回（排序确保结果可预测）
    return sorted(float(center[0]) for center in model.cluster_centers_)


def _fit_two_cluster(
    values: Sequence[float],
) -> tuple[list[float], list[int], list[float]] | None:
    """
    拟合两簇模型，返回中心、标签和原始值

    参数:
        values: 值序列

    返回:
        tuple[list[float], list[int], list[float]] | None: (中心, 标签, 清洗后的值)
    """
    # 转换为浮点数
    cleaned = [float(item) for item in values]
    # 样本不足，无法聚类
    if len(cleaned) < MIN_TWO_CLUSTER_SAMPLES:
        return None
    # 创建两簇KMeans模型
    model = KMeans(
        n_clusters=2,
        random_state=REPRODUCIBILITY_SEED,
        n_init=KMEANS_N_INIT,
    )
    # 获取每个样本的簇标签（0或1）
    labels = model.fit_predict([[item] for item in cleaned])
    # 提取聚类中心
    centers = [float(center[0]) for center in model.cluster_centers_]
    return centers, [int(label) for label in labels], cleaned


def derive_two_cluster_boundary(
    values: Sequence[float], fallback: float
) -> tuple[float, str]:
    """
    派生两簇边界

    使用两簇聚类，中点作为分割阈值

    参数:
        values: 值序列
        fallback: 失败时的回退值

    返回:
        tuple[float, str]: (边界值, 来源说明)
    """
    # 使用2簇聚类，中点作为分割阈值
    centers = _cluster_centers(values, n_clusters=2)
    # 聚类失败，使用回退值
    if not centers or len(centers) < 2:
        return float(fallback), "fallback_two_cluster"
    # 计算两个中心的中点作为边界
    boundary = 0.5 * (centers[0] + centers[1])
    return float(boundary), "kmeans_2cluster"


def derive_three_cluster_boundaries(
    values: Sequence[float],
    fallback_low: float,
    fallback_high: float,
) -> tuple[float, float, str]:
    """
    派生三簇边界

    使用三簇聚类，得到低边界和高边界

    参数:
        values: 值序列
        fallback_low: 低边界回退值
        fallback_high: 高边界回退值

    返回:
        tuple[float, float, str]: (低边界, 高边界, 来源说明)
    """
    # 使用3簇聚类
    centers = _cluster_centers(values, n_clusters=3)
    # 聚类失败，使用回退值
    if not centers or len(centers) < 3:
        return float(fallback_low), float(fallback_high), "fallback_three_cluster"
    # 第一和第二中心之间为低边界，第二和第三中心之间为高边界
    low_boundary = 0.5 * (centers[0] + centers[1])
    high_boundary = 0.5 * (centers[1] + centers[2])
    return float(low_boundary), float(high_boundary), "kmeans_3cluster"


def derive_small_cluster_upper_bound(
    values: Sequence[float], fallback: float
) -> tuple[float, str]:
    """
    派生小簇上界

    用于识别"小"或"聚焦"的值的上边界
    例如：小文件数、小模块数

    参数:
        values: 值序列
        fallback: 失败时的回退值

    返回:
        tuple[float, str]: (上界值, 来源说明)
    """
    # 执行两簇聚类
    result = _fit_two_cluster(values)
    # 聚类失败，返回回退值
    if result is None:
        return float(fallback), "fallback_two_cluster_low_upper"
    centers, labels, cleaned = result
    # 确定哪个簇是较小的（中心值较小的那个）
    low_label = 0 if centers[0] <= centers[1] else 1
    # 提取小簇的所有值
    low_values = [value for value, label in zip(cleaned, labels) if label == low_label]
    # 小簇为空，返回回退值
    if not low_values:
        return float(fallback), "fallback_two_cluster_low_upper_empty"
    # 返回小簇的最大值作为��界
    return float(max(low_values)), "kmeans_2cluster_low_cluster_max"


def derive_high_cluster_lower_bound(
    values: Sequence[float], fallback: float
) -> tuple[float, str]:
    """
    派生大簇下界

    用于识别"大"或"分散"的值的下边界
    例如：多角色冲突、多模块

    参数:
        values: 值序列
        fallback: 失败时的回退值

    返回:
        tuple[float, str]: (下界值, 来源说明)
    """
    # 执行两簇聚类
    result = _fit_two_cluster(values)
    # 聚类失败，返回回退值
    if result is None:
        return float(fallback), "fallback_two_cluster_high_lower"
    centers, labels, cleaned = result
    # 确定哪个簇是较大的（中心值较大的那个）
    high_label = 0 if centers[0] >= centers[1] else 1
    # 提取大簇的所有值
    high_values = [
        value for value, label in zip(cleaned, labels) if label == high_label
    ]
    # 大簇为空，返回回退值
    if not high_values:
        return float(fallback), "fallback_two_cluster_high_lower_empty"
    # 返回大簇的最小值作为下界
    return float(min(high_values)), "kmeans_2cluster_high_cluster_min"
