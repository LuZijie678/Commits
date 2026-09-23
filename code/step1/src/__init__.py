"""
研究工具包根模块

本包提供原子性校准和参数派生的核心功能。
"""

from .param_derivation import (
    ThresholdSelectionReport,
    TierThresholds,
    derive_atomic_weight,
    derive_atomic_weights,
    derive_epistemic_reference,
    derive_gate_threshold_by_uncertainty,
    derive_small_cluster_upper_bound,
    derive_three_cluster_boundaries,
    derive_two_cluster_boundary,
    derive_tier_thresholds_from_distribution,
    select_threshold_by_precision,
    select_threshold_by_precision_report,
)
