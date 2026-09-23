"""
Proxy Gap Analysis Module

该模块用于分析 message-only proxy（仅使用提交消息的模型）与 full-diff primary model（使用完整 diff 的模型）
之间的性能差距。主要功能包括：
1. 计算概率性指标（AUC、Brier Score、Log Loss 等）的差距
2. 分析 tier（层级）分类的一致性
3. 生成可行性估计和敏感度分析
4. 输出 JSON 和 Markdown 格式的分析报告
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.labeling import label_protocol
from src.pipeline import atomic_mining as miner
from src.analysis import proxy_gap_report
from src.analysis import proxy_gap_schema
import src.data_splitting.annotated_split_protocol as annotated_split_protocol
from src.pipeline import validation as validator
from sklearn.metrics import roc_auc_score

# CSV 字段大小限制（避免大字段导致解析错误）
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
# 有意义的提交类型（过滤掉非实质性类型如 docs、chore 等）
SUBSTANTIVE_TYPES = ("fix", "feat", "refactor", "test", "perf")
# 默认的缺失 tier 处理策略
DEFAULT_MISSING_TIER_POLICY = proxy_gap_schema.DEFAULT_MISSING_TIER_POLICY
# 有效的缺失 tier 策略列表
VALID_MISSING_TIER_POLICIES = ("missing_as_unknown", "missing_as_c")
# 本地提交文本的默认 JSONL 文件路径（用于回填缺失的提交消息和 diff）
DEFAULT_LOCAL_COMMIT_TEXTS_JSONL = Path(
    "../../datasets/step1/runtime_support/resolved_commit_texts.jsonl"
)


def load_csv_rows(path: Path) -> list[dict]:
    """从 CSV 文件加载所有行并作为字典列表返回"""
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_csv_rows(path: Path) -> list[dict]:
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_local_commit_texts(path: Path, wanted_shas: set[str]) -> dict[str, dict]:
    """从 JSONL 文件加载本地提交文本，仅返回 wanted_shas 中存在的提交
    返回: sha -> 提交数据字典的映射
    """
    if not wanted_shas or not path.exists():
        return {}
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            sha = str(payload.get("sha", "")).strip()
            if sha and sha in wanted_shas:
                rows[sha] = payload
    return rows


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """计算 Wilson 置信区间（默认 95% 置信度）
    参数: successes - 成功次数, total - 总次数, z - z-score（1.96 对应 95%）
    返回: (下界, 上界)
    """
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1.0 + z * z / total
    center = (phat + z * z / (2.0 * total)) / denom
    margin = (
        z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * total)) / total) / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def assign_probability_bin(probability: float, bins: list[tuple[float, str]]) -> str:
    """将概率值分配到对应的概率区间桶
    参数: probability - 概率值, bins - 区间定义列表 [(下界, 标签), ...]
    返回: 匹配的区间标签
    """
    if not bins:
        return "[0.00,1.00]"
    clipped = miner.clip_prob(float(probability))
    for lower, label in bins:
        if clipped >= float(lower):
            return str(label)
    return str(bins[-1][1])


def _message_only_probability(
    row: dict,
    message_only_calibration: dict,
) -> float:
    """仅使用提交消息计算原子性概率（proxy 模型的概率）
    参数: row - 提交记录, message_only_calibration - 仅消息校准配置
    返回: 校准后的原子性概率值
    """
    message_features = miner.parse_message(str(row.get("commit_message", "")))
    candidate_type = str(row.get("type", "")).strip()
    logit = miner.atomic_logit(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=None,
        signal_context=(message_only_calibration or {}).get("signal_context"),
        message_protocol=(message_only_calibration or {}).get("message_protocol"),
        type_protocol=(message_only_calibration or {}).get("type_protocol"),
    )
    raw_prob = miner.clip_prob(miner.sigmoid(logit))
    return float(
        miner.apply_calibration_to_raw_prob(
            raw_prob,
            logit,
            calibration=message_only_calibration,
        )
    )


def _full_diff_probability_and_tier(
    row: dict,
    full_diff_calibration: dict,
) -> tuple[float, str] | None:
    """使用完整 diff 计算原子性概率和 tier 分类（primary 模型的概率和分类）
    参数: row - 提交记录, full_diff_calibration - 完整 diff 校准配置
    返回: (概率, tier分类) 或 None（如果 diff 无效）
    """
    message = str(row.get("commit_message", ""))
    candidate_type = str(row.get("type", "")).strip()
    git_diff = str(row.get("git_diff", "")).strip()
    if not git_diff:
        return None
    diff_features = miner.parse_diff(git_diff)
    # 检查 diff 是否包含有效的文件变更
    if (
        float(diff_features.get("file_count", 0.0)) <= 0.0
        or float(diff_features.get("changed_lines", 0.0)) <= 0.0
    ):
        return None
    prior = miner.atomic_prior(
        message_features=miner.parse_message(message),
        candidate_type=candidate_type,
        diff_features=diff_features,
        calibration=full_diff_calibration,
        global_stats=(
            (full_diff_calibration or {}).get("feature_norm_stats") or {}
        ).get("global"),
    )
    thresholds = (full_diff_calibration or {}).get("thresholds") or {}
    tau_a = float(thresholds.get("tau_a"))
    tau_b = float(thresholds.get("tau_b"))
    probability = float(prior["p_atomic"])
    return probability, miner.assign_atomic_tier(probability, tau_a=tau_a, tau_b=tau_b)


def _full_diff_tier(
    row: dict,
    full_diff_calibration: dict,
) -> str | None:
    """仅获取完整 diff 模型的 tier 分类（不含概率）
    参数: row - 提交记录, full_diff_calibration - 完整 diff 校准配置
    返回: tier 分类或 None
    """
    result = _full_diff_probability_and_tier(row, full_diff_calibration)
    if result is None:
        return None
    _, tier = result
    return tier


def _safe_auc(labels: list[int], probabilities: list[float]) -> float | None:
    """计算 AUC 分数，处理边界情况（至少需要 2 个样本和 2 个不同标签）
    参数: labels - 真实标签列表, probabilities - 预测概率列表
    返回: AUC 分数或 None（如果无法计算）
    """
    if len(labels) < 2 or len(set(labels)) < 2:
        return None
    return float(roc_auc_score(labels, probabilities))


def _brier_score(labels: list[int], probabilities: list[float]) -> float | None:
    """计算 Brier 分数（预测概率与真实标签的均方误差）
    参数: labels - 真实标签列表, probabilities - 预测概率列表
    返回: Brier 分数或 None
    """
    if not labels:
        return None
    total = 0.0
    for label, probability in zip(labels, probabilities):
        total += (float(probability) - int(label)) ** 2
    return total / len(labels)


def _log_loss(labels: list[int], probabilities: list[float]) -> float | None:
    """计算对数损失（交叉熵）
    参数: labels - 真实标签列表, probabilities - 预测概率列表
    返回: 对数损失或 None
    """
    if not labels:
        return None
    total = 0.0
    for label, probability in zip(labels, probabilities):
        clipped = miner.clip_prob(float(probability))
        total += -(
            int(label) * math.log(clipped) + (1 - int(label)) * math.log(1.0 - clipped)
        )
    return total / len(labels)


def build_probability_gap_metrics_from_arrays(
    *,
    labels: list[int],
    message_only_probs: list[float],
    full_diff_probs: list[float],
    proxy_tiers: list[str],
    primary_tiers: list[str],
) -> dict:
    """从数组数据计算概率差距指标（AUC、Brier、LogLoss、tier一致性）
    参数: labels - 真实标签, message_only_probs - proxy模型概率, full_diff_probs - primary模型概率
          proxy_tiers - proxy模型tier分类, primary_tiers - primary模型tier分类
    返回: 包含各指标及差距的字典
    """
    # 过滤并整理可比较的数据（确保类型一致）
    comparable = [
        (
            int(label),
            float(proxy_prob),
            float(primary_prob),
            str(proxy_tier),
            str(primary_tier),
        )
        for label, proxy_prob, primary_prob, proxy_tier, primary_tier in zip(
            labels, message_only_probs, full_diff_probs, proxy_tiers, primary_tiers
        )
    ]
    if not comparable:
        return {
            "annotated_metric_sample_count": 0,
            "message_only_auc": None,
            "full_diff_auc": None,
            "message_only_brier": None,
            "full_diff_brier": None,
            "message_only_logloss": None,
            "full_diff_logloss": None,
            "auc_gap_primary_minus_proxy": None,
            "brier_gap_proxy_minus_primary": None,
            "logloss_gap_proxy_minus_primary": None,
            "annotated_tier_consistency": None,
        }
    # 提取各维度的数据
    metric_labels = [item[0] for item in comparable]
    metric_proxy_probs = [item[1] for item in comparable]
    metric_primary_probs = [item[2] for item in comparable]
    metric_proxy_tiers = [item[3] for item in comparable]
    metric_primary_tiers = [item[4] for item in comparable]
    # 计算 tier 一致性（proxy 和 primary 分类相同的比例）
    matching_tiers = sum(
        1
        for proxy_tier, primary_tier in zip(metric_proxy_tiers, metric_primary_tiers)
        if proxy_tier == primary_tier
    )
    # 计算各项概率指标
    message_only_auc = _safe_auc(metric_labels, metric_proxy_probs)
    full_diff_auc = _safe_auc(metric_labels, metric_primary_probs)
    message_only_brier = _brier_score(metric_labels, metric_proxy_probs)
    full_diff_brier = _brier_score(metric_labels, metric_primary_probs)
    message_only_logloss = _log_loss(metric_labels, metric_proxy_probs)
    full_diff_logloss = _log_loss(metric_labels, metric_primary_probs)
    return {
        "annotated_metric_sample_count": len(metric_labels),
        "message_only_auc": message_only_auc,
        "full_diff_auc": full_diff_auc,
        "message_only_brier": message_only_brier,
        "full_diff_brier": full_diff_brier,
        "message_only_logloss": message_only_logloss,
        "full_diff_logloss": full_diff_logloss,
        "auc_gap_primary_minus_proxy": (
            None
            if message_only_auc is None or full_diff_auc is None
            else full_diff_auc - message_only_auc
        ),
        "brier_gap_proxy_minus_primary": (
            None
            if message_only_brier is None or full_diff_brier is None
            else message_only_brier - full_diff_brier
        ),
        "logloss_gap_proxy_minus_primary": (
            None
            if message_only_logloss is None or full_diff_logloss is None
            else message_only_logloss - full_diff_logloss
        ),
        "annotated_tier_consistency": matching_tiers / len(metric_labels),
    }


def build_explicit_tier_lookup(
    *,
    tier_a_rows: list[dict],
    tier_b_rows: list[dict],
    tier_c_rows: list[dict],
) -> dict[str, str]:
    """构建从 SHA 到 tier 分类的查找表
    参数: tier_a_rows/b_rows/c_rows - 各 tier 的候选提交列表
    返回: sha -> tier分类 的映射字典
    """
    tier_by_sha: dict[str, str] = {}
    for rows, tier in ((tier_a_rows, "A"), (tier_b_rows, "B"), (tier_c_rows, "C")):
        for row in rows:
            sha = str(row.get("sha", "")).strip()
            if sha:
                tier_by_sha[sha] = tier
    return tier_by_sha


def _selection_proxy_probability(row: dict) -> float:
    """从选择阶段的记录中提取 proxy 概率值（按优先级尝试多个字段）
    参数: row - 选择阶段的提交记录
    返回: proxy 概率值，如果都不存在则返回 0.0
    """
    for key in [
        "p_atomic_message_only",
        "atomic_prior_message_only_calibrated",
        "atomic_prior_message_only",
        "p_raw_message_only",
        "p_atomic",
        "atomic_prior_calibrated",
        "atomic_prior",
    ]:
        value = row.get(key)
        if value in {None, ""}:
            continue
        return float(value)
    return 0.0


def build_probability_gap_metrics(
    *,
    annotated_rows: list[dict],
    message_only_calibration: dict,
    full_diff_calibration: dict,
) -> dict:
    """为标注数据计算 proxy 与 primary 之间的概率差距指标
    参数: annotated_rows - 已标注的提交列表, message_only_calibration - proxy 校准配置
          full_diff_calibration - primary 校准配置
    返回: 概率差距指标字典
    """
    labels: list[int] = []
    message_only_probs: list[float] = []
    full_diff_probs: list[float] = []
    proxy_tiers: list[str] = []
    primary_tiers: list[str] = []

    for row in annotated_rows:
        resolved_label = label_protocol.resolve_label_record(
            row, label_col="is_single_intent"
        )
        if resolved_label["selected_label"] is None:
            continue
        label = int(resolved_label["selected_label_int"])
        commit_type = str(row.get("type") or row.get("annotated_type") or "").strip()
        # 过滤非实质性提交类型
        if commit_type not in SUBSTANTIVE_TYPES:
            continue
        if not str(row.get("git_diff", "")).strip():
            continue
        try:
            proxy_probability = _message_only_probability(row, message_only_calibration)
            primary = _full_diff_probability_and_tier(row, full_diff_calibration)
        except Exception:
            continue
        if primary is None:
            continue
        primary_probability, primary_tier = primary
        # 使用 proxy 阈值计算 proxy tier
        proxy_tier = validator.assign_tier(
            {
                "atomic_prior_message_only_calibrated": proxy_probability,
            },
            tau_a=float(
                (message_only_calibration.get("thresholds") or {}).get("tau_a")
            ),
            tau_b=float(
                (message_only_calibration.get("thresholds") or {}).get("tau_b")
            ),
            prefer_message_only=True,
        )
        labels.append(label)
        message_only_probs.append(proxy_probability)
        full_diff_probs.append(primary_probability)
        proxy_tiers.append(proxy_tier)
        primary_tiers.append(primary_tier)

    return build_probability_gap_metrics_from_arrays(
        labels=labels,
        message_only_probs=message_only_probs,
        full_diff_probs=full_diff_probs,
        proxy_tiers=proxy_tiers,
        primary_tiers=primary_tiers,
    )


def _bucket_key(commit_type: str, bin_label: str) -> tuple[str, str]:
    """构建桶的键名（用于分组统计）
    参数: commit_type - 提交类型, bin_label - 概率区间标签
    返回: (提交类型, 区间标签) 元组
    """
    return str(commit_type).strip(), str(bin_label)


def build_reference_conversion_table(
    *,
    annotated_rows: list[dict],
    message_only_calibration: dict,
    full_diff_calibration: dict,
    probability_bins: list[tuple[float, str]],
) -> dict:
    """构建参考转换表，统计 proxy 概率区间到 primary tier 的映射关系
    用于后续可行性估计
    参数: annotated_rows - 已标注数据, 校准配置, 概率区间定义
    返回: 包含各维度计数的字典
    """
    # 按 (提交类型, 概率区间) 分组统计各 tier 数量
    bucket_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    # 按概率区间分组统计
    band_counts: dict[str, Counter] = defaultdict(Counter)
    # 按提交类型分组统计
    type_counts: dict[str, Counter] = defaultdict(Counter)
    overall = Counter()

    for row in annotated_rows:
        commit_type = str(row.get("type") or row.get("annotated_type") or "").strip()
        if commit_type not in SUBSTANTIVE_TYPES:
            continue
        if not str(row.get("git_diff", "")).strip():
            continue
        try:
            message_only_prob = _message_only_probability(row, message_only_calibration)
            full_diff_tier = _full_diff_tier(row, full_diff_calibration)
        except Exception:
            continue
        if full_diff_tier is None:
            continue
        bin_label = assign_probability_bin(message_only_prob, probability_bins)
        bucket_counts[_bucket_key(commit_type, bin_label)][full_diff_tier] += 1
        band_counts[bin_label][full_diff_tier] += 1
        type_counts[commit_type][full_diff_tier] += 1
        overall[full_diff_tier] += 1

    return {
        "bucket_counts": {
            f"{commit_type}::{bin_label}": dict(counter)
            for (commit_type, bin_label), counter in bucket_counts.items()
        },
        "band_counts": {band: dict(counter) for band, counter in band_counts.items()},
        "type_counts": {
            commit_type: dict(counter) for commit_type, counter in type_counts.items()
        },
        "overall_counts": dict(overall),
    }


def _rate_and_bound(
    counter: Counter, tier_name: str = "B"
) -> tuple[int, int, float, float]:
    """计算指定 tier 的比例和 Wilson 置信区间下界
    参数: counter - tier 计数, tier_name - 目标 tier 名称
    返回: (成功数, 总数, 比例, Wilson下界)
    """
    total = sum(counter.values())
    successes = int(counter.get(tier_name, 0))
    if total <= 0:
        return 0, 0, 0.0, 0.0
    low, _ = wilson_interval(successes, total)
    return successes, total, successes / total, low


def _counter_from_mapping(mapping: dict[str, int] | None) -> Counter:
    """将字典映射转换为 Counter 对象
    参数: mapping - 可选的字典映射
    返回: Counter 对象
    """
    counter = Counter()
    if not isinstance(mapping, dict):
        return counter
    for key, value in mapping.items():
        counter[str(key)] = int(value)
    return counter


def estimate_feasibility(
    *,
    selection_rows: list[dict],
    reference_table: dict,
    probability_bins: list[tuple[float, str]],
    target_tier: str = "B",
) -> dict:
    """基于参考转换表估算选择集的目标 tier 产出率
    参数: selection_rows - 选择阶段候选列表, reference_table - 参考转换表
          probability_bins - 概率区间定义, target_tier - 目标 tier (默认 B)
    返回: 包含期望产出数和保守下界的字典
    """
    # 解析参考表中的各项计数
    bucket_counts = {
        tuple(key.split("::", 1)): _counter_from_mapping(value)
        for key, value in (reference_table.get("bucket_counts") or {}).items()
    }
    band_counts = {
        key: _counter_from_mapping(value)
        for key, value in (reference_table.get("band_counts") or {}).items()
    }
    type_counts = {
        key: _counter_from_mapping(value)
        for key, value in (reference_table.get("type_counts") or {}).items()
    }
    overall_counts = _counter_from_mapping(reference_table.get("overall_counts"))

    expected = 0.0
    lower_bound = 0.0
    fallback_usage = Counter()
    selected_bucket_counts = Counter()

    # 统计选择集中各 (类型, 概率区间) 的数量
    for row in selection_rows:
        commit_type = str(row.get("type", "")).strip()
        if commit_type not in SUBSTANTIVE_TYPES:
            continue
        prob = float(
            row.get("p_atomic")
            or row.get("atomic_prior_calibrated")
            or row.get("atomic_prior")
            or 0.0
        )
        bin_label = assign_probability_bin(prob, probability_bins)
        selected_bucket_counts[(commit_type, bin_label)] += 1

    # 计算每个桶的期望产出（使用分层回退策略）
    bucket_expectations: dict[str, dict] = {}
    for (commit_type, bin_label), count in sorted(selected_bucket_counts.items()):
        # 优先使用精确的 (类型, 区间) 匹配
        source = "bucket"
        ref_counter = bucket_counts.get((commit_type, bin_label))
        if not ref_counter or sum(ref_counter.values()) == 0:
            # 回退到按类型匹配
            ref_counter = type_counts.get(commit_type)
            source = "type"
        if not ref_counter or sum(ref_counter.values()) == 0:
            # 回退到按区间匹配
            ref_counter = band_counts.get(bin_label)
            source = "band"
        if not ref_counter or sum(ref_counter.values()) == 0:
            # 最后回退到总体统计
            ref_counter = overall_counts
            source = "overall"
        successes, total, rate, low = _rate_and_bound(
            ref_counter, tier_name=target_tier
        )
        expected += count * rate
        lower_bound += count * low
        fallback_usage[source] += count
        bucket_expectations[f"{commit_type}::{bin_label}"] = {
            "selected_count": count,
            "reference_total": total,
            "reference_target_tier_count": successes,
            "estimated_rate": round(rate, 6),
            "wilson95_lower": round(low, 6),
            "source": source,
        }

    return {
        "target_tier": target_tier,
        "selected_count": int(sum(selected_bucket_counts.values())),
        "expected_target_tier_yield": round(expected, 3),
        "conservative_target_tier_lower_bound": round(lower_bound, 3),
        "bucket_expectations": bucket_expectations,
        "fallback_usage": dict(fallback_usage),
    }


def cached_full_diff_precheck(
    *,
    selection_rows: list[dict],
    full_diff_calibration: dict,
    local_commit_texts: dict[str, dict],
    target_tier: str = "B",
) -> dict:
    """使用本地缓存的完整 diff 数据进行预检查，获取实际 tier 分布
    参数: selection_rows - 选择集, full_diff_calibration - 校准配置
          local_commit_texts - 本地缓存的完整提交数据, target_tier - 目标 tier
    返回: 各 tier 计数和覆盖率统计
    """
    observed = Counter()
    covered = 0
    for row in selection_rows:
        sha = str(row.get("sha", "")).strip()
        payload = local_commit_texts.get(sha)
        if not payload:
            continue
        try:
            tier = _full_diff_tier(
                {
                    "commit_message": payload.get(
                        "commit_message", row.get("commit_message", "")
                    ),
                    "type": row.get("type", ""),
                    "git_diff": payload.get("git_diff", ""),
                },
                full_diff_calibration,
            )
        except Exception:
            continue
        if tier is None:
            continue
        observed[tier] += 1
        covered += 1

    total = len(selection_rows)
    return {
        "covered_selection_count": covered,
        "missing_selection_count": max(0, total - covered),
        "observed_tier_counts": dict(observed),
        "observed_target_tier_yield": int(observed.get(target_tier, 0)),
        "coverage_ratio": round((covered / total) if total else 0.0, 6),
    }


def combine_feasibility_sources(
    *,
    reference_feasibility: dict,
    cached_precheck: dict | None,
    target_tier: str = "B",
) -> dict:
    """合并参考表估算和本地缓存预检查的结果
    参数: reference_feasibility - 参考表估算结果, cached_precheck - 缓存预检查结果
    返回: 合并后的可行性估计
    """
    if not cached_precheck:
        return {
            **reference_feasibility,
            "source": "reference_only",
            "cached_observed_target_tier_yield": None,
            "cached_coverage_ratio": 0.0,
        }
    missing = int(cached_precheck.get("missing_selection_count", 0))
    selected = int(reference_feasibility.get("selected_count", 0))
    cached_observed = float(cached_precheck.get("observed_target_tier_yield", 0))
    cached_coverage_ratio = float(cached_precheck.get("coverage_ratio", 0.0))
    reference_expected = float(
        reference_feasibility.get("expected_target_tier_yield", 0.0)
    )
    reference_lower = float(
        reference_feasibility.get("conservative_target_tier_lower_bound", 0.0)
    )
    # 计算缺失部分占选择集的比例
    tail_ratio = 0.0 if selected <= 0 else max(0.0, min(1.0, missing / selected))
    # 缓存已覆盖的部分使用实际观测值，缺失部分使用参考表估算
    combined_expected = cached_observed + reference_expected * tail_ratio
    combined_lower = cached_observed + reference_lower * tail_ratio
    source = "cached_plus_reference_tail" if missing > 0 else "cached_only"
    return {
        **reference_feasibility,
        "expected_target_tier_yield": round(combined_expected, 3),
        "conservative_target_tier_lower_bound": round(combined_lower, 3),
        "source": source,
        "cached_observed_target_tier_yield": int(cached_observed),
        "cached_coverage_ratio": round(cached_coverage_ratio, 6),
    }


def analyze_proxy_gap(
    *,
    selection_rows: list[dict],
    resolved_rows: list[dict],
    tier_a_rows: list[dict],
    tier_b_rows: list[dict],
    tier_c_rows: list[dict],
    probability_bins: list[tuple[float, str]],
    missing_tier_policy: str = DEFAULT_MISSING_TIER_POLICY,
) -> dict:
    """分析 proxy (message-only) 与 primary (full-diff) 之间的 tier 差距
    参数: selection_rows - 选择集, resolved_rows - 已解决候选集
          tier_a/b/c_rows - 各 tier 的验证候选, probability_bins - 概率区间
          missing_tier_policy - 缺失 tier 处理策略
    返回: 包含 tier 转换矩阵和各项统计的字典
    """
    if missing_tier_policy not in VALID_MISSING_TIER_POLICIES:
        raise ValueError(f"unsupported missing_tier_policy: {missing_tier_policy}")
    # 构建选择集 SHA 索引
    selected_by_sha = {str(row.get("sha", "")).strip(): row for row in selection_rows}
    # 构建验证集 tier 查找表
    tier_by_sha = build_explicit_tier_lookup(
        tier_a_rows=tier_a_rows,
        tier_b_rows=tier_b_rows,
        tier_c_rows=tier_c_rows,
    )
    # 初始化各项计数器
    matrix = Counter()
    by_type = defaultdict(Counter)
    by_bucket = defaultdict(Counter)
    observed_tier_counts = Counter()
    proxy_tier_counts = Counter()
    proxy_tier_a_total = 0
    proxy_tier_a_known_primary_total = 0
    proxy_tier_a_unknown_total = 0
    proxy_tier_a_to_primary_tier_c = 0
    matching_tiers = 0
    comparable_rows = 0
    unknown_total = 0

    for row in resolved_rows:
        sha = str(row.get("sha", "")).strip()
        if not sha or sha not in selected_by_sha:
            continue
        selection_row = selected_by_sha[sha]
        selection_tier = str(selection_row.get("prefilter_tier", "")).strip() or "NA"
        # 确定 full-diff tier（根据策略处理缺失值）
        if sha in tier_by_sha:
            full_diff_tier = tier_by_sha[sha]
        elif missing_tier_policy == "missing_as_c":
            full_diff_tier = "C"
        else:
            full_diff_tier = "UNKNOWN"
        commit_type = str(row.get("type", "")).strip()
        message_only_prob = _selection_proxy_probability(selection_row)
        bin_label = assign_probability_bin(message_only_prob, probability_bins)
        # 更新各维度计数
        matrix[(selection_tier, full_diff_tier)] += 1
        by_type[commit_type][full_diff_tier] += 1
        by_bucket[f"{commit_type}::{bin_label}"][full_diff_tier] += 1
        observed_tier_counts[full_diff_tier] += 1
        proxy_tier_counts[selection_tier] += 1
        # 统计未知 tier
        if full_diff_tier == "UNKNOWN":
            unknown_total += 1
        # 计算 tier 一致性（仅对有明确 tier 的记录）
        if selection_tier in {"A", "B", "C"} and full_diff_tier in {"A", "B", "C"}:
            comparable_rows += 1
            if selection_tier == full_diff_tier:
                matching_tiers += 1
        # 统计 proxy tier A 到 primary tier C 的降级情况
        if selection_tier == "A":
            proxy_tier_a_total += 1
            if full_diff_tier == "UNKNOWN":
                proxy_tier_a_unknown_total += 1
            else:
                proxy_tier_a_known_primary_total += 1
            if full_diff_tier == "C":
                proxy_tier_a_to_primary_tier_c += 1

    return {
        "missing_tier_policy": missing_tier_policy,
        "is_sensitivity_analysis": missing_tier_policy != DEFAULT_MISSING_TIER_POLICY,
        "proxy_to_primary_tier_matrix": {
            f"{src}->{dst}": count for (src, dst), count in sorted(matrix.items())
        },
        "tier_consistency_denominator_policy": "known_primary_tier_only",
        "tier_consistency": (
            None if comparable_rows <= 0 else matching_tiers / comparable_rows
        ),
        "known_primary_tier_count": int(comparable_rows),
        "unknown_count": int(unknown_total),
        "unknown_rate": (
            None
            if not resolved_rows
            else unknown_total
            / len(
                [
                    row
                    for row in resolved_rows
                    if str(row.get("sha", "")).strip() in selected_by_sha
                ]
            )
        ),
        "message_only_tier_counts": dict(proxy_tier_counts),
        "message_only_tier_a_count": int(proxy_tier_a_total),
        "message_only_tier_a_known_primary_count": int(
            proxy_tier_a_known_primary_total
        ),
        "message_only_tier_a_unknown_count": int(proxy_tier_a_unknown_total),
        "message_only_tier_a_unknown_rate": (
            None
            if proxy_tier_a_total <= 0
            else proxy_tier_a_unknown_total / proxy_tier_a_total
        ),
        "message_only_tier_a_to_full_diff_c_count": int(proxy_tier_a_to_primary_tier_c),
        "downgrade_denominator_policy": "proxy_a_with_known_primary_tier_only",
        "downgrade_rate_message_only_a_to_full_diff_c": (
            None
            if proxy_tier_a_known_primary_total <= 0
            else proxy_tier_a_to_primary_tier_c / proxy_tier_a_known_primary_total
        ),
        "selection_to_full_diff_matrix": {
            f"{src}->{dst}": count for (src, dst), count in sorted(matrix.items())
        },
        "full_diff_tier_by_type": {
            key: dict(counter) for key, counter in sorted(by_type.items())
        },
        "full_diff_tier_by_type_and_message_only_band": {
            key: dict(counter) for key, counter in sorted(by_bucket.items())
        },
        "observed_full_diff_tier_counts": dict(observed_tier_counts),
    }


def generate_analysis_artifacts(
    *,
    selection_batch_csv: Path,
    resolved_candidates_csv: Path,
    validation_dir: Path,
    annotated_csv: Path,
    message_only_calibration_json: Path,
    full_diff_calibration_json: Path,
    output_dir: Path,
    audit_target: int,
    local_commit_texts_jsonl: Path = DEFAULT_LOCAL_COMMIT_TEXTS_JSONL,
    annotated_split_plan_json: Path | None = None,
) -> dict:
    """生成 proxy gap 分析的所有输出产物（JSON 和 Markdown 报告）
    参数: 各输入文件路径和配置参数
    返回: 包含输出路径和关键指标的字典
    """
    # 加载输入数据
    selection_rows = load_csv_rows(selection_batch_csv)
    resolved_rows = load_csv_rows(resolved_candidates_csv)
    tier_a_rows = load_csv_rows(validation_dir / "tier_a_candidates.csv")
    tier_b_rows = load_csv_rows(validation_dir / "tier_b_candidates.csv")
    tier_c_path = validation_dir / "tier_c_candidates.csv"
    tier_c_rows = load_csv_rows(tier_c_path) if tier_c_path.exists() else []
    annotated_rows = load_csv_rows(annotated_csv)
    # 验证标注数据分割
    if annotated_split_plan_json is not None and annotated_split_plan_json.exists():
        split_summary = json.loads(
            annotated_split_plan_json.read_text(encoding="utf-8")
        )
        annotated_split_protocol.assert_rows_match_split(
            rows=annotated_rows,
            split_sha_set=annotated_split_protocol.split_sha_set(
                split_summary, "proxy_gap"
            ),
            split_name="proxy_gap",
            context="proxy-gap reference analysis",
        )
    # 加载校准配置
    message_only_calibration = miner.load_calibration(
        message_only_calibration_json.as_posix()
    )
    full_diff_calibration = miner.load_calibration(
        full_diff_calibration_json.as_posix()
    )
    # 验证校准模式匹配
    miner.require_calibration_mode(
        message_only_calibration,
        expected_mode="message_only",
        context="proxy-gap proxy analysis path",
    )
    miner.require_calibration_mode(
        full_diff_calibration,
        expected_mode="full_diff",
        context="proxy-gap full-diff primary analysis path",
    )

    # 基于选择集概率分布生成概率区间
    selection_message_only_probs = [
        float(
            row.get("p_atomic")
            or row.get("atomic_prior_calibrated")
            or row.get("atomic_prior")
            or 0.0
        )
        for row in selection_rows
    ]
    probability_bins = miner.probability_bins_from_distribution(
        selection_message_only_probs
    )
    # 构建参考转换表（用于估算产出率）
    reference_table = build_reference_conversion_table(
        annotated_rows=annotated_rows,
        message_only_calibration=message_only_calibration,
        full_diff_calibration=full_diff_calibration,
        probability_bins=probability_bins,
    )
    # 基于参考表估算可行性
    reference_feasibility = estimate_feasibility(
        selection_rows=selection_rows,
        reference_table=reference_table,
        probability_bins=probability_bins,
        target_tier="B",
    )
    # 加载本地提交文本用于实际验证
    local_commit_texts = load_local_commit_texts(
        local_commit_texts_jsonl,
        {
            str(row.get("sha", "")).strip()
            for row in selection_rows
            if str(row.get("sha", "")).strip()
        },
    )
    # 使用本地数据预检查实际 tier 分布
    cached_precheck = cached_full_diff_precheck(
        selection_rows=selection_rows,
        full_diff_calibration=full_diff_calibration,
        local_commit_texts=local_commit_texts,
        target_tier="B",
    )
    # 合并参考估算和实际预检查结果
    feasibility = combine_feasibility_sources(
        reference_feasibility=reference_feasibility,
        cached_precheck=cached_precheck,
        target_tier="B",
    )
    # 执行主要 proxy gap 分析
    proxy_gap = analyze_proxy_gap(
        selection_rows=selection_rows,
        resolved_rows=resolved_rows,
        tier_a_rows=tier_a_rows,
        tier_b_rows=tier_b_rows,
        tier_c_rows=tier_c_rows,
        probability_bins=probability_bins,
        missing_tier_policy=DEFAULT_MISSING_TIER_POLICY,
    )
    # 执行敏感度分析（将缺失 tier 视为 C）
    sensitivity_missing_as_c = analyze_proxy_gap(
        selection_rows=selection_rows,
        resolved_rows=resolved_rows,
        tier_a_rows=tier_a_rows,
        tier_b_rows=tier_b_rows,
        tier_c_rows=tier_c_rows,
        probability_bins=probability_bins,
        missing_tier_policy="missing_as_c",
    )
    # 计算概率差距指标
    probability_gap_metrics = build_probability_gap_metrics(
        annotated_rows=annotated_rows,
        message_only_calibration=message_only_calibration,
        full_diff_calibration=full_diff_calibration,
    )
    # 统计实际观测到的 tier B 数量
    resolved_tier_counts = Counter(
        proxy_gap.get("observed_full_diff_tier_counts") or {}
    )
    observed_tier_b = int(resolved_tier_counts.get("B", 0))
    # 构建最终输出数据
    payload = proxy_gap_schema.build_proxy_quality_payload(
        selection_count=len(selection_rows),
        resolved_count=len(resolved_rows),
        audit_target=int(audit_target),
        probability_bins=[
            {"lower": float(lower), "label": str(label)}
            for lower, label in probability_bins
        ],
        feasibility={
            **feasibility,
            "audit_target": int(audit_target),
            "expected_gap_vs_target": round(
                float(feasibility["expected_target_tier_yield"]) - float(audit_target),
                3,
            ),
            "conservative_gap_vs_target": round(
                float(feasibility["conservative_target_tier_lower_bound"])
                - float(audit_target),
                3,
            ),
            "cached_precheck": cached_precheck,
        },
        proxy_probability_gap=probability_gap_metrics,
        conversion_metrics={
            **proxy_gap,
            "observed_tier_b_yield": observed_tier_b,
            "observed_tier_b_gap_vs_target": observed_tier_b - int(audit_target),
        },
        sensitivity_analysis={
            "missing_as_c": {
                **sensitivity_missing_as_c,
                "analysis_role": "sensitivity_only",
            }
        },
    )

    # 输出 JSON 和 Markdown 报告
    json_path = output_dir / "proxy_gap_analysis.json"
    md_path = output_dir / "proxy_gap_analysis.md"
    proxy_gap_report.write_json(json_path, payload)
    proxy_gap_report.write_text(
        md_path,
        proxy_gap_report.build_proxy_gap_markdown(
            payload=payload,
            observed_tier_b=observed_tier_b,
        ),
    )
    return {
        "json_path": json_path.as_posix(),
        "markdown_path": md_path.as_posix(),
        "message_only_auc": payload["proxy_probability_gap"]["message_only_auc"],
        "full_diff_auc": payload["proxy_probability_gap"]["full_diff_auc"],
        "message_only_logloss": payload["proxy_probability_gap"][
            "message_only_logloss"
        ],
        "full_diff_logloss": payload["proxy_probability_gap"]["full_diff_logloss"],
        "tier_consistency": payload["conversion_metrics"]["tier_consistency"],
        "downgrade_rate_message_only_a_to_full_diff_c": payload["conversion_metrics"][
            "downgrade_rate_message_only_a_to_full_diff_c"
        ],
        "classification": payload["conclusion"]["classification"],
        "expected_tier_b_yield": payload["feasibility"]["expected_target_tier_yield"],
        "conservative_tier_b_lower_bound": payload["feasibility"][
            "conservative_target_tier_lower_bound"
        ],
        "observed_tier_b_yield": observed_tier_b,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute independent proxy-gap metrics between message-only proxy scores and full-diff primary tiers."
    )
    parser.add_argument("--selection-batch-csv", required=True)
    parser.add_argument("--resolved-candidates-csv", required=True)
    parser.add_argument("--validation-dir", required=True)
    parser.add_argument("--annotated-csv", required=True)
    parser.add_argument("--proxy-calibration-json", required=True)
    parser.add_argument("--primary-calibration-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--audit-target", type=int, required=True)
    parser.add_argument("--annotated-split-plan-json", default="")
    parser.add_argument(
        "--local-commit-texts-jsonl",
        default=DEFAULT_LOCAL_COMMIT_TEXTS_JSONL.as_posix(),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = generate_analysis_artifacts(
        selection_batch_csv=Path(args.selection_batch_csv),
        resolved_candidates_csv=Path(args.resolved_candidates_csv),
        validation_dir=Path(args.validation_dir),
        annotated_csv=Path(args.annotated_csv),
        message_only_calibration_json=Path(args.proxy_calibration_json),
        full_diff_calibration_json=Path(args.primary_calibration_json),
        output_dir=Path(args.output_dir),
        audit_target=int(args.audit_target),
        local_commit_texts_jsonl=Path(args.local_commit_texts_jsonl),
        annotated_split_plan_json=(
            Path(args.annotated_split_plan_json)
            if args.annotated_split_plan_json
            else None
        ),
    )
    print(f"proxy_gap_json={metrics['json_path']}")
    print(f"proxy_gap_markdown={metrics['markdown_path']}")
    print(f"message_only_auc={metrics['message_only_auc']}")
    print(f"full_diff_auc={metrics['full_diff_auc']}")
    print(f"tier_consistency={metrics['tier_consistency']}")
    print(
        "downgrade_rate_message_only_a_to_full_diff_c="
        f"{metrics['downgrade_rate_message_only_a_to_full_diff_c']}"
    )


if __name__ == "__main__":
    main()
