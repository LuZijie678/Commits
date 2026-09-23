"""Utilities for strict annotated-data splitting protocols."""

# 本模块提供严格的标注数据集分割协议工具
# 主要功能包括：
# - 按仓库级别的数据分组，保证数据隔离性
# - 多约束条件下的分割计划构建（最小样本数、正负样本比例、仓库数等）
# - 分割结果验证和数据落盘
