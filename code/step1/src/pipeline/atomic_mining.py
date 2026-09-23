"""
单意图（Single-Intent）候选挖掘模块

本模块实现了从Git提交中挖掘具有单一意图的候选提交的核心逻辑。
主要功能包括：
1. 解析提交消息和diff特征
2. 计算原子性先验概率（atomic prior）
3. 构建原子性信号映射
4. 分配Tier等级（A/B/C）
5. 应用校准和权重计算

核心概念：
- 单意图提交：只包含一个逻辑变更的提交
- Tier A: 高置信度的单意图候选
- Tier B: 中等置信度
- Tier C: 低置信度或非单意图
"""

import argparse
import base64
import csv
import json
import math
import pickle
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from src.param_derivation.threshold_selection import (
    TierThresholds,
    derive_gate_threshold_by_uncertainty,
    derive_tier_thresholds_from_distribution,
)
from src.param_derivation.weight_calibration import (
    derive_atomic_weight,
    derive_epistemic_reference,
)


# 传统提交格式正则：type(scope)!: subject
PREFIX_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\([^)]+\))?(?P<breaking>!)?: (?P<subject>.+)$"
)
# Git diff文件路径解析正则
FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")

# 多意图标记：用于检测提交是否包含多个意图
MULTI_MARKERS = [
    ";",  # 分号分隔多个操作
    " also ",  # "also" 表示额外操作
    " additionally ",  # "additionally" 表示额外操作
    " meanwhile ",  # "meanwhile" 表示并行操作
    " plus ",  # "plus" 表示附加操作
    " follow-up ",  # "follow-up" 表示后续操作
    " follow up ",  # follow up变体
]

# 噪声标记：表示提交可能不完整或处于草稿状态
NOISY_MARKERS = [
    "wip",  # Work In Progress
    "save",  # 暂存
    "fixup",  # 修正
    "tmp",  # 临时
    "todo",  # 待办
    "qs",  # 快速保存
]

# 发布类标记：表示与版本发布相关的提交
RELEASE_MARKERS = [
    "release",
    "version bump",
    "bump version",
]

# 停用词：路径解析时忽略的目录名
STOPWORDS = {
    "",
    ".",
    "..",
    "__pycache__",
    "src",
    "lib",
    "app",
    "apps",
    "packages",
    "pkg",
    "core",
    "internal",
    "tests",
    "test",
    "docs",
}

# 实质性提交类型：包含实际代码变更的类型
SUBSTANTIVE_TYPES = {"fix", "feat", "refactor", "perf", "test"}
# 弱实质性类型：文档和样式变更
WEAK_TYPES = {"docs", "style"}
# 基础设施类型：构建和CI相关
INFRA_TYPES = {"build", "ci", "chore"}

# Step1概率先验（distribution-derived weak prior when no trained model is loaded）。
# 原子性信号键：用于计算提交原子性（单意图）概率的特征信号
ATOMIC_SIGNAL_KEYS = [
    "prefix_valid",  # 是否符合传统提交格式
    "subject_compact",  # subject是否简洁
    "body_compact",  # body是否简洁
    "single_focus_message",  # 消息是否单一焦点
    "clean_message",  # 消息是否清晰（无噪声标记）
    "not_release_like",  # 是否非发布类
    "commit_type_signal",  # 提交类型信号
    "file_scope_signal",  # 文件范围信号
    "patch_scope_signal",  # patch范围信号
    "hunk_scope_signal",  # hunk范围信号
    "role_focus_signal",  # 角色聚焦信号
    "module_focus_signal",  # 模块聚焦信号
]
# 统一原子性权重：各信号等权重
UNIFORM_ATOMIC_WEIGHT = 1.0 / len(ATOMIC_SIGNAL_KEYS)
# 默认原子性权重字典
DEFAULT_ATOMIC_WEIGHTS = {key: UNIFORM_ATOMIC_WEIGHT for key in ATOMIC_SIGNAL_KEYS}
# 默认原子性偏置
DEFAULT_ATOMIC_BIAS = 0.0
# 信号分散度epsilon：用于防止除零
SIGNAL_DISPERSION_EPS = 1e-6
# Logit缩放epsilon：用于防止除零
LOGIT_SCALE_EPS = 1e-6

# 默认Tier阈值（从校准文件或分布派生）
DEFAULT_TAU_A: float | None = None
DEFAULT_TAU_B: float | None = None
# 默认最小分数
DEFAULT_MIN_SCORE = 0
# 默认最小原子性先验
DEFAULT_MIN_ATOMIC_PRIOR = 0.0
# 默认目标候选数量
DEFAULT_TARGET_COUNT = 100
# CSV字段大小限制
CSV_FIELD_SIZE_LIMIT = 2**31 - 1
# 摘要中显示的top仓库数量
SUMMARY_TOP_REPO_COUNT = 15
# 摘要中显示的top示例数量
SUMMARY_TOP_EXAMPLE_COUNT = 10
# 概率分箱数量
PROBABILITY_BIN_COUNT = 4
# 范围协议分位数配置
SCOPE_PROTOCOL_QUANTILE_LOW = 1.0 / 3.0
SCOPE_PROTOCOL_QUANTILE_MID = 2.0 / 3.0
SCOPE_PROTOCOL_QUANTILE_HIGH = 0.90
# epsilon常量
EPS = 1e-9
# 概率裁剪epsilon
PROB_CLIP_EPS = 1e-8

# 支持角色集合（测试、文档、配置、构建）
SUPPORT_ROLE_SET = {"test", "docs", "config", "build"}
# 包含source的支持角色集合（source + test/docs/config/build的任意组合）
SOURCE_WITH_SUPPORT_ROLE_SET = {"source"} | SUPPORT_ROLE_SET

# 原子性特征接口（Step1 -> Step2传播）。
# 原子性特征顺序：用于GBDT模型训练和推理的特征列表
ATOMIC_FEATURE_ORDER = [
    "file_count",  # 文件数量
    "hunk_count",  # diff hunk数量
    "file_gini",  # 文件分布基尼系数
    "method_count",  # 方法数量
    "module_count",  # 模块数量
    "ast_edit_entropy",  # AST编辑熵
    "dominant_edit_ratio",  # 主导编辑比例
    "file_role_purity",  # 文件角色纯度
    "has_single_prefix",  # 是否有单一前缀
    "multi_intent_markers",  # 多意图标记
    "semantic_cluster_tightness",  # 语义聚类紧密度
    "identifier_focus",  # 标识符聚焦度
    "single_issue_link",  # 单issue链接
    "issue_type_consistency",  # issue类型一致性
    "doc_or_test_only",  # 仅文档或测试
    "repo_norm_size",  # 仓库标准化大小
    "repo_norm_module_span",  # 仓库标准化模块跨度
]

# Issue引用正则：匹配 #数字 或 issue/fixes/close + 数字
ISSUE_REF_RE = re.compile(
    r"(?:#\d+|(?:issue|fixe?[sd]?|close[sd]?)\s*#?\d+)", re.IGNORECASE
)
# 标识符正则：匹配编程语言标识符（字母或下划线开头，后续可以是字母数字）
TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,}")
# Hunk方法名正则：提取diff hunk中变更的函数/方法名
HUNK_METHOD_RE = re.compile(r"@@.*@@\s*(.+)$")


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数

    返回:
        argparse.Namespace: 解析后的命令行参数
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
        help="输入CSV数据集路径",
    )
    parser.add_argument("--output-dir", default="outputs/single_intent_trial")
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument(
        "--min-atomic-prior", type=float, default=DEFAULT_MIN_ATOMIC_PRIOR
    )
    parser.add_argument("--tau-a", type=float, default=DEFAULT_TAU_A)
    parser.add_argument("--tau-b", type=float, default=DEFAULT_TAU_B)
    parser.add_argument("--calibration-json", default="")
    return parser.parse_args()


def clean_lines(text: str) -> list[str]:
    """
    清理文本行：去除每行末尾的换行符

    参数:
        text: 输入文本

    返回:
        list[str]: 清理后的行列表
    """
    # 遍历输入文本的每一行，去除末尾换行符后返回列表
    return [line.rstrip() for line in text.splitlines()]


def sigmoid(value: float) -> float:
    """
    Sigmoid函数：将任意值映射到(0,1)区间

    公式: sigmoid(x) = 1 / (1 + exp(-x))
    用于将logit转换为概率

    参数:
        value: 输入值（任意实数）

    返回:
        float: sigmoid变换后的概率值，范围(0,1)
    """
    # 当value >= 0时，使用exp(-value)避免数值溢出
    if value >= 0:
        exp_val = math.exp(-value)
        return 1.0 / (1.0 + exp_val)
    # 当value < 0时，使用exp(value)避免数值溢出
    exp_val = math.exp(value)
    return exp_val / (1.0 + exp_val)


def clip_prob(value: float) -> float:
    """
    裁剪概率值：避免概率为0或1导致的数值问题

    概率接近0或1时，logit计算会溢出。
    此函数将概率裁剪到(epsilon, 1-epsilon)区间

    参数:
        value: 原始概率值

    返回:
        float: 裁剪后的概率值，范围(PROB_CLIP_EPS, 1-PROB_CLIP_EPS)
    """
    # 使用max确保不小于PROB_CLIP_EPS，使用min确保不大于1-PROB_CLIP_EPS
    return min(1.0 - PROB_CLIP_EPS, max(PROB_CLIP_EPS, value))


def safe_logit(prob: float) -> float:
    """
    安全计算logit：先裁剪概率再计算

    logit(p) = log(p / (1-p))
    当p接近0或1时会导致数值溢出，所以先裁剪

    参数:
        prob: 概率值，范围[0,1]

    返回:
        float: logit值
    """
    # 先裁剪概率到安全范围，避免log(0)或log(负数)
    clipped = clip_prob(prob)
    # 计算logit: log(p/(1-p))
    return math.log(clipped / (1.0 - clipped))


def entropy_from_counts(counter: Counter[str]) -> float:
    """
    从计数器计算熵：衡量分布的随机性

    熵越高表示分布越均匀，越低表示越集中
    公式: H = -sum(p * log(p))

    参数:
        counter: 字符计数（如词频统计）

    返回:
        float: 熵值，范围[0, log(n)]，其中n是类别数
    """
    # 计算总计数
    total = sum(counter.values())
    # 空计数器返回0熵
    if total <= 0:
        return 0.0
    value = 0.0
    # 遍历每个类别，计算其概率并累加熵
    for count in counter.values():
        p = count / total
        if p > 0:
            # 累加 -p*log(p)，加EPS防止log(0)
            value -= p * math.log(p + EPS)
    return value


def gini_from_counts(counter: Counter[str]) -> float:
    """
    从计数器计算基尼系数：衡量分布的不均匀程度

    基尼系数越高表示分布越不均匀（集中）
    公式: Gini = 1 - sum(p^2)

    参数:
        counter: 字符计数

    返回:
        float: 基尼系数，范围[0,1]，0=完全均匀，1=完全不均匀
    """
    # 计算总计数
    total = sum(counter.values())
    # 空计数器返回0
    if total <= 0:
        return 0.0
    squared = 0.0
    # 遍历每个类别，计算其概率并累加概率平方
    for count in counter.values():
        p = count / total
        squared += p * p
    # 基尼系数 = 1 - sum(p^2)，使用max确保非负
    return max(0.0, 1.0 - squared)


def _lexical_focus_ratio(text: str) -> float:
    """
    计算词汇聚焦度：文本中最常见词占总词数的比例

    用于衡量文本是否聚焦于少数词汇
    例如：文本全是"bug"相关词 -> 高聚焦度

    参数:
        text: 输入文本

    返回:
        float: 聚焦度，范围[0,1]，越高表示词汇越集中
    """
    # 使用TOKEN_RE提取所有标识符（单词），并转为小写以便统一统计
    tokens = [token.lower() for token in TOKEN_RE.findall(text)]
    # 无Token返回0
    if not tokens:
        return 0.0
    # 统计词频
    counts = Counter(tokens)
    # 返回最常见词的占比 = 最常见词的数量 / 总词数
    return counts.most_common(1)[0][1] / len(tokens)


def _semantic_cluster_tightness(message: str) -> float:
    """
    计算语义聚类紧密度：每行词汇聚焦度的平均值

    用于判断提交消息是否聚焦于单一主题
    每行都聚焦 -> 高紧密度

    参数:
        message: 提交消息

    返回:
        float: 紧密度，范围[0,1]
    """
    # 提取所有非空行（去除首尾空白）
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    # 无有效行返回0
    if not lines:
        return 0.0
    # 计算每行的词汇聚焦度，然后取平均得到紧密度
    per_line_focus = [_lexical_focus_ratio(line) for line in lines]
    return sum(per_line_focus) / len(per_line_focus)


def _identifier_focus(identifiers: list[str]) -> float:
    """
    计算标识符聚焦度：前3个最常见标识符占总标识符数的比例

    用于衡量diff中修改的标识符是否集中

    参数:
        identifiers: 标识符列表（如函数名、变量名）

    返回:
        float: 聚焦度，范围[0,1]
    """
    # 空列表返回0
    if not identifiers:
        return 0.0
    # 统计标识符词频（忽略大小写以便统一统计）
    counts = Counter(token.lower() for token in identifiers)
    # 计算总标识符数
    total = sum(counts.values())
    # 取前3个最常见标识符的数量累加
    top = sum(count for _, count in counts.most_common(3))
    # 前3个占比作为聚焦度
    return top / max(total, 1)


def _isotonic_predict(
    probability: float, x_values: list[float], y_values: list[float]
) -> float:
    """
    等渗回归预测：使用已拟合的等渗回归模型对概率进行校准

    等渗回归是保序回归，保持原始排序的同时进行非线性变换
    使用分段线性插值进行预测

    参数:
        probability: 原始概率（待校准）
        x_values: 等渗模型的输入阈值（已排序）
        y_values: 等渗模型的输出阈值（已排序）

    返回:
        float: 校准后的概率
    """
    # 空模型直接返回原值
    if not x_values or not y_values:
        return probability
    # 裁剪到有效概率范围
    p = clip_prob(probability)
    # 边界处理：低于最小阈值返回最小映射值
    if p <= x_values[0]:
        return y_values[0]
    # 边界处理：高于最大阈值返回最大映射值
    if p >= x_values[-1]:
        return y_values[-1]
    # 二分查找找到p所在的区间
    left = 0
    right = len(x_values) - 1
    while left + 1 < right:
        middle = (left + right) // 2
        if x_values[middle] <= p:
            left = middle  # p在右半边
        else:
            right = middle  # p在左半边
    # 获取区间边界
    x0, x1 = x_values[left], x_values[right]
    y0, y1 = y_values[left], y_values[right]
    # 线性插值计算校准后的值
    if abs(x1 - x0) < EPS:
        return y1  # 避免除零
    ratio = (p - x0) / (x1 - x0)  # 插值比例
    return y0 + ratio * (y1 - y0)  # 线性插值


def parse_message(message: str) -> dict:
    """
    解析提交消息，提取特征用于原子性判断

    本函数从提交消息中提取多个维度的特征，用于后续判断该提交是否为单意图：
    1. 结构特征：subject长度、body行数、段落数
    2. 格式特征：是否符合Conventional Commit格式
    3. 语义特征：是否含多意图标记、噪声标记、发布类标记
    4. 关联特征：issue引用数量

    参数:
        message: 提交消息文本（包含subject和body）

    返回:
        dict: 消息特征字典，包含字段:
        - subject_line: 标题行
        - subject_len: 标题长度（字符数）
        - body_line_count: 正文行数（不含标题）
        - paragraph_count: 段落数（空行分隔）
        - prefix_match: 是否符合Conventional Commit格式（布尔值）
        - prefix_type: 匹配到的提交类型（如feat, fix等）
        - has_multi_markers: 是否含有多意图标记（如";", "also"等）
        - has_noisy_markers: 是否含有噪声标记（如wip, todo等）
        - release_like: 是否类似发布类提交
        - issue_ref_count: issue引用数量
        - single_issue_link: 是否只链接一个issue（布尔值）
        - semantic_cluster_tightness: 语义聚类紧密度（0-1）
    """
    # 步骤1: 清理文本行，去除末尾换行符
    lines = clean_lines(message)
    # 步骤2: 分离subject和body
    # 找到第一行非空行作为subject，其余作为body
    subject_line = ""
    body_lines: list[str] = []
    for index, line in enumerate(lines):
        if line.strip():  # 找到第一行非空行
            subject_line = line.strip()
            # body是该行之后的所有非空行
            body_lines = [item.strip() for item in lines[index + 1 :] if item.strip()]
            break

    # 步骤3: 检查是否符合Conventional Commit格式
    # 格式: type(scope)!: subject 或 type: subject
    match = PREFIX_RE.match(subject_line)

    # 步骤4: 转为小写并添加空格（方便单词边界匹配）
    lower = f" {message.lower()} "

    # 步骤5: 计算段落数（空行分隔的文本块）
    paragraphs = [
        chunk.strip() for chunk in re.split(r"\n\s*\n", message) if chunk.strip()
    ]

    # 步骤6: 检测多意图标记
    # 检查是否有列表符号（* 或 - 开头）或多意图连接词
    has_bullets = any(line.lstrip().startswith(("* ", "- ")) for line in lines)
    # 多意图标记包括: ";", "also", "additionally", "meanwhile", "plus", "follow-up"
    has_multi_markers = has_bullets or any(marker in lower for marker in MULTI_MARKERS)

    # 步骤7: 检测噪声标记（使用单词边界匹配，避免误匹配）
    has_noisy_markers = any(
        re.search(rf"\b{re.escape(marker)}\b", lower) for marker in NOISY_MARKERS
    )

    # 步骤8: 检测发布类标记
    release_like = any(marker in lower for marker in RELEASE_MARKERS)

    # 步骤9: 提取issue引用
    issue_refs = ISSUE_REF_RE.findall(message)

    # 步骤10: 计算语义聚类紧密度（每行词汇聚焦度的平均值）
    semantic_tightness = _semantic_cluster_tightness(message)

    # 返回完整的特征字典
    return {
        "subject_line": subject_line,
        "subject_len": len(subject_line),
        "body_line_count": len(body_lines),
        "paragraph_count": len(paragraphs),
        "prefix_match": bool(match),  # 转换为布尔值
        "prefix_type": match.group("type") if match else "",  # 提取type部分
        "has_multi_markers": has_multi_markers,
        "has_noisy_markers": has_noisy_markers,
        "release_like": release_like,
        "issue_ref_count": len(issue_refs),
        "single_issue_link": len(issue_refs) == 1,
        "semantic_cluster_tightness": semantic_tightness,
    }


def derive_message_protocol(message_feature_rows: list[dict]) -> dict[str, float]:
    """
    从消息特征分布派生出消息协议/边界

    消息协议定义了消息的正常范围，用于判断消息是否"简洁"或"紧凑"。
    这些边界从数据分布的分位数自动派生，而非人工设定。

    协议包含:
    - subject长度边界：太小或太大都不好
    - body行数边界：超过某阈值表示"碎片化"
    - 段落数边界：超过某阈值表示"碎片化"

    参数:
        message_feature_rows: 消息特征行列表（每个元素包含subject_len, body_line_count等）

    返回:
        dict: 消息协议字典，包含:
        - subject_len_min: subject最小长度（10分位）
        - subject_len_max: subject最大长度（90分位）
        - body_compact_max_lines: body紧凑最大行数（50分位）
        - body_fragmented_min_lines: body碎片化最小行数（85分位）
        - paragraph_compact_max: 段落紧凑最大数量（50分位）
        - paragraph_fragmented_min: 段落碎片化最小数量（85分位）
        - source: 来源说明
    """
    # 步骤1: 收集所有subject长度（过滤掉0值）
    subject_lengths = [
        float(item.get("subject_len", 0.0))
        for item in message_feature_rows
        if float(item.get("subject_len", 0.0)) > 0.0
    ]
    # 步骤2: 收集所有body行数和段落数
    body_lines = [
        float(item.get("body_line_count", 0.0)) for item in message_feature_rows
    ]
    paragraphs = [
        float(item.get("paragraph_count", 0.0)) for item in message_feature_rows
    ]
    # 步骤3: 空值处理（设置默认值避免后续计算错误）
    if not subject_lengths:
        subject_lengths = [1.0]
    if not body_lines:
        body_lines = [0.0]
    if not paragraphs:
        paragraphs = [0.0]

    # 步骤4: 计算分位数边界
    # subject长度：10分位为最小，90分位为最大
    subject_len_min = quantile(subject_lengths, 0.10, default=min(subject_lengths))
    subject_len_max = quantile(subject_lengths, 0.90, default=max(subject_lengths))
    # 确保min <= max（可能因数据分布反转）
    if subject_len_max < subject_len_min:
        subject_len_min, subject_len_max = subject_len_max, subject_len_min

    # 返回协议字典，包含分位数边界
    return {
        "subject_len_min": max(1.0, subject_len_min),
        "subject_len_max": max(1.0, subject_len_max),
        # body行数：50分位以下是"紧凑"，85分以上是"碎片化"
        "body_compact_max_lines": quantile(
            body_lines, 0.50, default=statistics.median(body_lines)
        ),
        "body_fragmented_min_lines": quantile(
            body_lines, 0.85, default=max(body_lines)
        ),
        # 段落数：同理
        "paragraph_compact_max": quantile(
            paragraphs, 0.50, default=statistics.median(paragraphs)
        ),
        "paragraph_fragmented_min": quantile(paragraphs, 0.85, default=max(paragraphs)),
        "source": "distribution_quantiles_message_protocol",
    }


def quantile(values: list[float], q: float, default: float) -> float:
    """
    计算分位数

    例如：q=0.5返回中位数，q=0.25返回第一四分位数

    参数:
        values: 值列表（将按大小排序）
        q: 分位数，范围[0,1]，如0.5表示中位数
        default: 默认值（当列表为空时返回）

    返回:
        float: 分位数值
    """
    if not values:
        return default  # 空列表返回默认值
    # 排序以便计算分位数
    ordered = sorted(float(item) for item in values)
    # 裁剪q到有效范围[0,1]
    q_clip = max(0.0, min(1.0, float(q)))
    # 计算索引：例如长度为10，q=0.5，索引=4.5->4
    index = int(round((len(ordered) - 1) * q_clip))
    # 确保索引在有效范围内
    index = max(0, min(len(ordered) - 1, index))
    return float(ordered[index])


def _derive_scope_bounds(values: list[float]) -> dict[str, float]:
    """
    从值分布派生出范围边界（小/中/大）

    使用三个分位数将数据分为三个区间：
    - 小于等于small_max: 聚焦/紧凑
    - 大于small_max且小于large_min: 中等
    - 大于等于large_min: 分散/大规模

    参数:
        values: 数值列表（如文件数、变更行数等）

    返回:
        dict: 范围边界字典，包含:
        - small_max: 小值上界（1/3分位）
        - medium_max: 中值上界（2/3分位）
        - large_min: 大值下界（90分位）
    """
    # 过滤None值并转为float
    cleaned = [float(item) for item in values if item is not None]
    # 空值处理
    if not cleaned:
        return {
            "small_max": 0.0,
            "medium_max": 0.0,
            "large_min": 0.0,
        }
    # 计算三个分位数的边界
    small_max = quantile(cleaned, SCOPE_PROTOCOL_QUANTILE_LOW, default=min(cleaned))
    medium_max = quantile(
        cleaned, SCOPE_PROTOCOL_QUANTILE_MID, default=statistics.median(cleaned)
    )
    large_min = quantile(cleaned, SCOPE_PROTOCOL_QUANTILE_HIGH, default=max(cleaned))
    # 确保顺序正确（可能因数据分布反转）
    ordered = sorted([small_max, medium_max, large_min])
    return {
        "small_max": ordered[0],  # 最小的作为小值上界
        "medium_max": ordered[1],  # 中间的作为中值上界
        "large_min": ordered[2],  # 最大的作为大值下界
    }


def derive_scope_protocol(diff_feature_rows: list[dict]) -> dict[str, float]:
    """
    从diff特征分布派生出范围协议

    范围协议定义了文件数、patch大小、hunk数、模块数的正常范围。
    这些边界用于判断提交的变更是否"聚焦"（小范围）还是"分散"（大范围）。

    参数:
        diff_feature_rows: diff特征行列表（每个元素包含file_count, changed_lines等）

    返回:
        dict: 范围协议字典，包含多组边界:
        - file_scope_*: 文件数边界
        - patch_scope_*: 变更行数边界
        - hunk_scope_*: hunk数边界
        - module_scope_*: 模块数边界
        - source: 来源说明
    """
    # 收集各维度特征
    file_counts = [float(item.get("file_count", 0.0)) for item in diff_feature_rows]
    patch_sizes = [float(item.get("changed_lines", 0.0)) for item in diff_feature_rows]
    hunk_counts = [float(item.get("hunk_count", 0.0)) for item in diff_feature_rows]
    module_counts = [float(item.get("module_count", 0.0)) for item in diff_feature_rows]

    # 为每个维度派生边界
    file_bounds = _derive_scope_bounds(file_counts)
    patch_bounds = _derive_scope_bounds(patch_sizes)
    hunk_bounds = _derive_scope_bounds(hunk_counts)
    module_bounds = _derive_scope_bounds(module_counts)

    # 返回完整的范围协议
    return {
        # 文件数边界
        "file_scope_small_max": file_bounds["small_max"],
        "file_scope_medium_max": file_bounds["medium_max"],
        "file_scope_large_min": file_bounds["large_min"],
        # 变更行数边界
        "patch_scope_small_max": patch_bounds["small_max"],
        "patch_scope_medium_max": patch_bounds["medium_max"],
        "patch_scope_large_min": patch_bounds["large_min"],
        # hunk数边界
        "hunk_scope_few_max": hunk_bounds["small_max"],
        "hunk_scope_mid_max": hunk_bounds["medium_max"],
        "hunk_scope_many_min": hunk_bounds["large_min"],
        # 模块数边界
        "module_scope_focused_max": module_bounds["small_max"],
        "module_scope_mid_max": module_bounds["medium_max"],
        "module_scope_scattered_min": module_bounds["large_min"],
        "source": "distribution_quantiles_scope_protocol",
    }


def derive_type_protocol(candidate_types: list[str]) -> dict:
    """
    从候选提交类型分布派生出类型协议

    类型协议计算每种类型的z-score标准化流行度。
    越常见的类型（如fix, feat）有更高的z-score，
    越稀有的类型有负的z-score。

    参数:
        candidate_types: 候选类型列表（如["fix", "feat", "fix", "refactor"]）

    返回:
        dict: 类型协议字典，包含:
        - values: 类型名到z-score的映射
        - default: 默认值（中性，0.0）
        - source: 来源说明
    """
    # 统计各类型出现次数
    counts = Counter(item for item in candidate_types if item)
    if not counts:
        return {
            "values": {},
            "default": 0.0,
            "source": "fallback_empty_type_protocol",
        }

    total = float(sum(counts.values()))  # 总数
    # 计算每种类型的流行度（占比）
    prevalences = [count / total for count in counts.values()]

    # 计算均值和标准差用于z-score标准化
    center = statistics.mean(prevalences)  # 均值
    spread = (
        statistics.pstdev(prevalences)  # 标准差
        if len(prevalences) > 1
        else abs(prevalences[0] - center)  # 只有一个类别时用偏差
    )
    spread = max(spread, EPS)  # 避免除零

    # 计算每种类型的z-score
    values = {
        commit_type: (count / total - center) / spread
        for commit_type, count in counts.items()
    }
    # 默认值为中位数
    default = statistics.median(values.values()) if values else 0.0

    return {
        "values": values,
        "default": default,
        "source": "distribution_type_prevalence_zscore",
    }


def probability_bins_from_distribution(
    probabilities: list[float], bin_count: int = PROBABILITY_BIN_COUNT
) -> list[tuple[float, str]]:
    """
    从概率分布创建概率分箱

    用于统计分析和可视化

    参数:
        probabilities: 概率列表
        bin_count: 分箱数量

    返回:
        list[tuple[float, str]]: (下界, 分箱标签)列表
    """
    if not probabilities:
        return [(0.0, "[0.00,1.00]")]
    bins = max(1, int(bin_count))
    clipped = [clip_prob(item) for item in probabilities]
    boundaries: list[float] = []
    for idx in range(bins):
        q = float(idx) / float(bins)
        boundaries.append(quantile(clipped, q, default=min(clipped)))
    boundaries.append(max(clipped))
    labels: list[tuple[float, str]] = []
    for idx in range(bins - 1, -1, -1):
        lower = boundaries[idx]
        upper = boundaries[idx + 1]
        bracket = "]" if idx == bins - 1 else ")"
        labels.append((lower, f"[{lower:.2f},{upper:.2f}{bracket}"))
    return labels


def classify_role(path: str) -> str:
    """
    根据文件路径分类角色/类型

    将文件路径映射到预定义的角色类别，用于判断提交变更的文件类型分布。
    例如：修改了多个文件，但都是docs类型，说明是文档类提交。

    角色分类规则（按优先级）:
    1. docs: 文档相关（docs/目录、.md文件等）
    2. ci: CI/CD配置（.github/workflows/、.circleci/等）
    3. test: 测试文件（/test/、/tests/、*_test.py等）
    4. build: 构建配置（package.json、Makefile等）
    5. config: 配置文件（.json、.yaml、/config/等）
    6. source: 源代码（默认）

    参数:
        path: 文件路径（如 "src/components/Button.tsx"）

    返回:
        str: 角色类型 (docs/ci/test/build/config/source)
    """
    # 转换为小写方便匹配
    lower = path.lower()
    # 提取文件名（不含目录）
    name = lower.rsplit("/", 1)[-1]

    # 步骤1: 检查是否为文档文件
    if (
        lower.startswith("docs/")  # docs目录
        or "/docs/" in lower  # 路径中含docs
        or name
        in {"readme.md", "readme.rst", "changelog.md", "changes.md"}  # 特定文档名
        or lower.endswith((".md", ".rst", ".adoc"))  # 文档格式后缀
    ):
        return "docs"

    # 步骤2: 检查是否为CI配置文件
    if (
        lower.startswith(".github/workflows/")  # GitHub Actions
        or lower.startswith(".circleci/")  # CircleCI
        or lower == ".travis.yml"  # Travis CI
        or lower.endswith(".github/workflows.yml")  # GitHub Actions yml
    ):
        return "ci"

    # 步骤3: 检查是否为测试文件
    if (
        "/test/" in lower  # test目录
        or "/tests/" in lower  # tests目录
        or "/spec/" in lower  # spec目录（Ruby/JS）
        or "/__tests__/" in lower  # __tests__目录
        or name.startswith("test_")  # test_前缀
        or name.endswith(  # 测试文件后缀
            ("_test.py", "_test.go", ".spec.ts", ".spec.js", ".test.ts", ".test.js")
        )
    ):
        return "test"

    # 步骤4: 检查是否为构建文件
    if name in {  # 常见的构建/包管理文件
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "pom.xml",
        "build.gradle",
        "gradle.properties",
        "requirements.txt",
        "makefile",
        "dockerfile",
    }:
        return "build"

    # 步骤5: 检查是否为配置文件
    if (
        lower.endswith(
            (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")
        )  # 配置文件后缀
        or "/config/" in lower  # config目录
        or name.startswith(".editorconfig")  # 编辑器配置
        or name.startswith("tsconfig")  # TS配置
        or name.startswith("eslint")  # ESLint配置
    ):
        return "config"

    # 步骤6: 默认归类为源代码
    return "source"


def primary_module(path: str) -> str:
    """
    从文件路径提取主模块名

    将文件路径的第一段（排除停用词）作为模块名。
    例如："src/components/Button.tsx" -> "components"
         "lib/utils/helper.py" -> "utils"

    参数:
        path: 文件路径

    返回:
        str: 模块名（停用词过滤后的第一段路径），空字符串表示无有效模块
    """
    # 按/分割路径，去除空段
    pieces = [piece for piece in path.split("/") if piece]
    if not pieces:
        return ""  # 空路径返回空字符串
    # 遍历各段，跳过停用词，返回第一个非停用词
    for piece in pieces:
        if piece.lower() not in STOPWORDS:
            return piece.lower()
    # 如果全是停用词，返回第一段
    return pieces[0].lower()


def parse_diff(diff: str) -> dict:
    """
    解析Git diff，提取变更特征

    本函数从Git diff文本中提取多个维度的特征，用于判断提交是否为单意图：
    1. 结构特征：文件数、hunk数、变更行数
    2. 分布特征：文件分布基尼系数（变更是否集中在少数文件）
    3. 内容特征：方法数量、标识符聚焦度
    4. 编辑特征：AST编辑熵、主导编辑类型比例
    5. 角色特征：文件角色分布、模块数、角色纯度

    参数:
        diff: Git diff文本（包含@@、+++、---等行）

    返回:
        dict: diff特征字典，包含:
        - file_paths: 文件路径列表
        - file_count: 文件数量
        - hunk_count: diff hunk数量（每个@@标记一个hunk）
        - changed_lines: 变更行数（新增+删除）
        - role_counts: 各角色文件数（Counter）
        - roles: 角色列表（去重排序）
        - module_counts: 各模块文件数（Counter）
        - module_count: 模块数量
        - file_gini: 文件分布基尼系数（0=均匀，1=集中）
        - method_count: 方法/函数数量（从hunk header提取）
        - ast_edit_entropy: AST编辑熵（编辑类型多样性）
        - dominant_edit_ratio: 主导编辑类型比例
        - file_role_purity: 文件角色纯度
        - identifier_focus: 标识符聚焦度
    """
    # === 步骤1: 初始化累加器 ===
    file_paths: list[str] = []  # 收集所有文件路径
    hunks = 0  # 累计hunk数量
    changed_lines = 0  # 累计变更行数
    file_line_counts: Counter[str] = Counter()  # 每个文件的变更行数
    edit_type_counts: Counter[str] = Counter()  # 编辑类型统计
    method_names: set[str] = set()  # 方法名集合（去重）
    identifiers: list[str] = []  # 标识符列表
    active_file = ""  # 当前正在处理的文件

    # === 步骤2: 逐行解析diff ===
    for raw_line in diff.splitlines():
        # 去除每行末尾的换行符
        line = raw_line.rstrip("\n")

        # 2.1 检测文件路径行: "diff --git a/path b/path"
        match = FILE_RE.match(line)
        if match:
            # 提取目标文件路径（b/后面部分）
            active_file = match.group(2)
            file_paths.append(active_file)
            continue

        # 2.2 检测hunk开始行: "@@ -行,行 +行,行 @@ 函数名"
        if line.startswith("@@"):
            hunks += 1  # 累计hunk数
            # 尝试从hunk header提取函数/方法名
            method_match = HUNK_METHOD_RE.match(line)
            if method_match:
                method_hint = method_match.group(1).strip()
                if method_hint:
                    method_names.add(method_hint)  # 添加到方法集合（去重）
            continue

        # 2.3 跳过元数据行（+++、---、index等）
        if line.startswith(
            ("+++", "---", "index ", "new file mode", "deleted file mode")
        ):
            continue

        # 2.4 处理实际变更行（+或-开头的行）
        if line.startswith("+") or line.startswith("-"):
            changed_lines += 1  # 累计变更行数
            if active_file:
                # 累加该文件的变更行数
                file_line_counts[active_file] += 1
            # 提取变更内容（去掉+或-前缀）
            content = line[1:].strip()

            # 2.5 分类编辑类型
            if content.startswith(("import ", "from ")):
                # 导入语句
                edit_type_counts["import"] += 1
            elif re.match(r"(class|def|function|interface|type)\s+", content):
                # 声明语句（类、函数、接口等）
                edit_type_counts["declaration"] += 1
            elif content.startswith(("#", "//", "/*", "*")):
                # 注释行
                edit_type_counts["comment"] += 1
            elif "(" in content and ")" in content:
                # 函数调用或签名
                edit_type_counts["call_or_sig"] += 1
            elif "=" in content or ":" in content:
                # 赋值或配置
                edit_type_counts["assignment_or_config"] += 1
            else:
                # 其他类型
                edit_type_counts["other"] += 1

            # 2.6 提取标识符（用于计算标识符聚焦度）
            identifiers.extend(TOKEN_RE.findall(content))

    # === 步骤3: 计算角色和模块分布 ===
    # 统计每个文件的角色类型
    roles = Counter(classify_role(path) for path in file_paths)
    # 统计source文件的模块分布（忽略docs/ci/test/build/config）
    modules = Counter(
        primary_module(path) for path in file_paths if classify_role(path) == "source"
    )

    # === 步骤4: 计算分布特征 ===
    # 文件分布基尼系数：如果大部分变更集中在少数文件，gini高
    file_gini = gini_from_counts(
        file_line_counts if file_line_counts else Counter(file_paths)
    )

    # AST编辑熵：编辑类型的多样性（高熵=多种类型混合，低熵=单一类型）
    ast_edit_entropy = entropy_from_counts(edit_type_counts)

    # 主导编辑类型比例：最常见编辑类型占总编辑的比例
    dominant_edit_ratio = 0.0
    if edit_type_counts:
        dominant_edit_ratio = edit_type_counts.most_common(1)[0][1] / max(
            sum(edit_type_counts.values()), 1
        )

    # 文件角色纯度：最常见角色占总文件的比例
    file_role_purity = 0.0
    if roles:
        file_role_purity = roles.most_common(1)[0][1] / max(len(file_paths), 1)

    # 标识符聚焦度
    identifier_focus = _identifier_focus(identifiers)

    # === 步骤5: 返回完整的特征字典 ===
    return {
        "file_paths": file_paths,
        "file_count": len(file_paths),
        "hunk_count": hunks,
        "changed_lines": changed_lines,
        "role_counts": dict(roles),
        "roles": sorted(roles),
        "module_counts": dict(modules),
        "module_count": len(modules),
        "file_gini": file_gini,
        "method_count": len(method_names),
        "ast_edit_entropy": ast_edit_entropy,
        "dominant_edit_ratio": dominant_edit_ratio,
        "file_role_purity": file_role_purity,
        "identifier_focus": identifier_focus,
    }


def compute_repo_feature_stats(
    parsed_rows: list[dict],
) -> dict[str, dict[str, dict[str, float]]]:
    """
    计算每个仓库的特征统计（均值和标准差）

    用于仓库级别的特征归一化。不同仓库的代码规模差异很大：
    - 大仓库可能一次变更多达50个文件
    - 小仓库可能只有1-2个文件

    如果不做归一化，大仓库的提交很容易被误判为"非单意图"。
    通过仓库级别的均值/标准差归一化，可以消除仓库规模差异的影响。

    参数:
        parsed_rows: 解析后的行列表，每行需包含:
        - repo: 仓库名
        - diff_features: diff特征字典

    返回:
        dict: 仓库级别的特征统计，结构为:
        {
            "facebook/react": {
                "file_count": {"mean": 5.2, "std": 3.1},
                "changed_lines": {"mean": 45.0, "std": 30.0},
                ...
            },
            "microsoft/vscode": {...},
            ...
        }
    """
    # 步骤1: 按仓库分组收集特征值
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in parsed_rows:
        repo = row.get("repo", "")
        diff_features = row.get("diff_features")
        if not repo or not diff_features:
            continue
        # 为每个仓库初始化特征列表
        repo_bucket = grouped.setdefault(
            repo,
            {
                "file_count": [],
                "hunk_count": [],
                "changed_lines": [],
                "module_count": [],
                "method_count": [],
                "ast_edit_entropy": [],
            },
        )
        # 收集每个特征的值
        for key in repo_bucket:
            repo_bucket[key].append(float(diff_features.get(key, 0.0)))

    # 步骤2: 计算每个仓库各特征的均值和标准差
    stats: dict[str, dict[str, dict[str, float]]] = {}
    for repo, bucket in grouped.items():
        stats[repo] = {}
        for key, values in bucket.items():
            if not values:
                # 空值设置默认值（避免除零）
                stats[repo][key] = {"mean": 0.0, "std": 1.0}
                continue
            # 计算均值
            mean = sum(values) / len(values)
            # 计算方差
            variance = sum((item - mean) ** 2 for item in values) / max(len(values), 1)
            # 计算标准差
            std = math.sqrt(variance)
            stats[repo][key] = {"mean": mean, "std": std}
    return stats


def compute_global_feature_stats(
    parsed_rows: list[dict],
) -> dict[str, dict[str, float]]:
    """
    计算全局特征统计（跨所有仓库）

    用于全局级别的特征归一化。当没有校准文件时，使用全局统计进行归一化。
    全局统计代表所有仓库的总体分布特征。

    参数:
        parsed_rows: 解析后的行列表，每行需包含diff_features

    返回:
        dict: 全局特征统计，结构为:
        {
            "file_count": {"mean": 3.5, "std": 2.8},
            "changed_lines": {"mean": 40.0, "std": 35.0},
            ...
        }
    """
    # 定义需要统计的特征键
    keys = [
        "file_count",
        "hunk_count",
        "changed_lines",
        "module_count",
        "method_count",
        "ast_edit_entropy",
    ]
    # 初始化各特征的列表
    bucket: dict[str, list[float]] = {key: [] for key in keys}
    # 收集所有特征值
    for row in parsed_rows:
        diff_features = row.get("diff_features")
        if not diff_features:
            continue
        for key in keys:
            bucket[key].append(float(diff_features.get(key, 0.0)))

    # 计算全局统计
    stats: dict[str, dict[str, float]] = {}
    for key in keys:
        values = bucket.get(key, [])
        if not values:
            stats[key] = {"mean": 0.0, "std": 1.0}
            continue
        mean = sum(values) / len(values)
        variance = sum((item - mean) ** 2 for item in values) / max(len(values), 1)
        std = math.sqrt(variance)
        stats[key] = {"mean": float(mean), "std": float(std)}
    return stats


def normalize_feature(value: float, stats: dict[str, float] | None) -> float:
    """
    归一化特征值：z-score标准化

    将原始值转换为z-score：
    z = (x - mean) / std

    这样可以将不同尺度的特征标准化到相似范围，
    避免某些特征因数值过大而主导模型。

    参数:
        value: 原始特征值
        stats: 统计信息字典，包含:
        - mean: 均值
        - std: 标准差

    返回:
        float: 标准化后的z-score值
    """
    # 无统计信息返回0（表示无法归一化）
    if not stats:
        return 0.0
    # 提取均值和标准差
    mean = float(stats.get("mean", 0.0))
    std = float(stats.get("std", 0.0))
    # z-score标准化，加EPS防止除零
    return (value - mean) / (std + EPS)


def build_atomic_feature_map(
    message_features: dict,
    candidate_type: str,
    diff_features: dict | None = None,
    repo_stats: dict[str, dict[str, float]] | None = None,
    global_stats: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    """
    构建原子性特征映射

    将消息特征、diff特征和类型组合成用于GBDT训练的固定顺序特征向量。
    特征顺序由ATOMIC_FEATURE_ORDER定义，包含17维特征：

    结构特征（5维）:
    - file_count: 文件数量
    - hunk_count: diff hunk数量
    - file_gini: 文件分布基尼系数
    - method_count: 方法数量
    - module_count: 模块数量

    编辑特征（3维）:
    - ast_edit_entropy: AST编辑熵
    - dominant_edit_ratio: 主导编辑类型比例
    - file_role_purity: 文件角色纯度

    语义特征（4维）:
    - has_single_prefix: 是否有单一Conventional Commit前缀
    - multi_intent_markers: 多意图标记
    - semantic_cluster_tightness: 语义聚类紧密度
    - identifier_focus: 标识符聚焦度

    上下文特征（5维）:
    - single_issue_link: 单issue链接
    - issue_type_consistency: issue类型一致性
    - doc_or_test_only: 仅文档或测试
    - repo_norm_size: 仓库标准化大小
    - repo_norm_module_span: 仓库标准化模块跨度

    参数:
        message_features: 消息特征字典（来自parse_message）
        candidate_type: 提交类型（如fix, feat, refactor等）
        diff_features: diff特征字典（来自parse_diff，可选）
        repo_stats: 仓库级别特征统计（可选，用于归一化）
        global_stats: 全局特征统计（可选，用于归一化）

    返回:
        dict[str, float]: 特征名到特征值的映射，键顺序由ATOMIC_FEATURE_ORDER定义
    """
    # 获取diff特征（空字典作为默认值）
    diff = diff_features or {}

    # === 步骤1: 计算派生特征 ===
    # 角色集合
    roles = set(diff.get("roles", []))
    has_source_role = "source" in roles
    support_roles = {"test", "docs", "config", "build", "ci"}

    # issue类型一致性：commit type与prefix type是否一致
    issue_type_consistency = (
        1.0
        if (message_features.get("prefix_type") == candidate_type and candidate_type)
        else 0.0
    )

    # 仅文档/测试标记：是否只修改了docs/test/config/build文件（不含source）
    doc_or_test_only = (
        1.0
        if roles
        and not has_source_role
        and roles.issubset({"docs", "test", "config", "build"})
        else 0.0
    )

    # === 步骤2: 获取归一化统计 ===
    # 优先使用仓库级别统计，其次使用全局统计
    changed_stats = (repo_stats or {}).get("changed_lines")
    module_stats = (repo_stats or {}).get("module_count")
    if changed_stats is None:
        changed_stats = (global_stats or {}).get("changed_lines")
    if module_stats is None:
        module_stats = (global_stats or {}).get("module_count")

    # === 步骤3: 构建特征字典 ===
    features = {
        # 3.1 结构特征（来自diff）
        "file_count": float(diff.get("file_count", 0.0)),
        "hunk_count": float(diff.get("hunk_count", 0.0)),
        "file_gini": float(diff.get("file_gini", 0.0)),
        "method_count": float(diff.get("method_count", 0.0)),
        "module_count": float(diff.get("module_count", 0.0)),
        # 3.2 编辑特征（来自diff）
        "ast_edit_entropy": float(diff.get("ast_edit_entropy", 0.0)),
        "dominant_edit_ratio": float(diff.get("dominant_edit_ratio", 0.0)),
        "file_role_purity": float(diff.get("file_role_purity", 0.0)),
        # 3.3 语义特征（来自message）
        "has_single_prefix": 1.0 if message_features.get("prefix_match") else 0.0,
        "multi_intent_markers": 1.0
        if message_features.get("has_multi_markers")
        else 0.0,
        "semantic_cluster_tightness": float(
            message_features.get("semantic_cluster_tightness", 0.0)
        ),
        # identifier_focus优先使用diff中的，其次使用subject的
        "identifier_focus": float(
            diff.get(
                "identifier_focus",
                _lexical_focus_ratio(message_features.get("subject_line", "")),
            )
        ),
        # 3.4 上下文特征
        "single_issue_link": 1.0 if message_features.get("single_issue_link") else 0.0,
        "issue_type_consistency": issue_type_consistency,
        "doc_or_test_only": doc_or_test_only,
        # 3.5 归一化特征
        "repo_norm_size": normalize_feature(
            float(diff.get("changed_lines", 0.0)), changed_stats
        ),
        "repo_norm_module_span": normalize_feature(
            float(diff.get("module_count", 0.0)), module_stats
        ),
    }

    # === 步骤4: 增强file_role_purity ===
    # 当source角色和支持角色以聚焦方式混合时，鼓励一致性
    # 例如：source+test 是可接受的（聚焦），但 source+test+docs+ci 不可接受
    if roles and has_source_role and roles.issubset({"source"} | support_roles):
        role_space = max(1.0, float(len({"source"} | support_roles)))
        inferred_floor = max(0.0, 1.0 - float(len(roles) - 1) / role_space)
        features["file_role_purity"] = max(features["file_role_purity"], inferred_floor)

    # === 步骤5: 确保所有特征都有值 ===
    for name in ATOMIC_FEATURE_ORDER:
        features.setdefault(name, 0.0)
    return features


def _commit_type_signal(
    candidate_type: str, type_protocol: dict | None = None
) -> float:
    """
    计算提交类型信号

    根据类型协议返回该类型的z-score标准化流行度。
    常见类型（如fix, feat）返回正值，冷门类型返回负值。
    这反映了不同类型的提交在数据集中的分布差异。

    参数:
        candidate_type: 提交类型（如fix, feat, refactor等）
        type_protocol: 类型协议字典，包含:
        - values: 类型名到z-score的映射
        - default: 默认值

    返回:
        float: 类型信号值，范围约[-2, 2]，正=流行，负=冷门
    """
    protocol = type_protocol or {}
    values = protocol.get("values")
    if isinstance(values, dict) and candidate_type in values:
        return float(values[candidate_type])
    default = protocol.get("default")
    if default is not None:
        return float(default)
    return 0.0  # 无协议时返回中性值


def _continuous_scope_signal(
    value: float, compact_anchor: float, wide_anchor: float
) -> float:
    """
    计算连续范围信号：将值映射到[-1, 1]

    这是一个通用的信号计算函数，用于衡量"聚焦"程度：
    - 值接近compact_anchor（紧凑）-> 返回接近1.0
    - 值接近wide_anchor（宽松）-> 返回接近-1.0
    - 值在两者之间 -> 线性插值

    例如：文件数3（紧凑）-> 1.0，文件数20（宽松）-> -1.0

    参数:
        value: 实际值（如文件数、变更行数等）
        compact_anchor: 紧凑锚点（边界值，小于此值表示聚焦）
        wide_anchor: 宽松锚点（边界值，大于此值表示分散）

    返回:
        float: 范围信号，1.0=聚焦，-1.0=分散，0.0=中间
    """
    # 转为float确保计算精度
    compact = float(compact_anchor)
    wide = float(wide_anchor)
    # 锚点反转（异常情况）返回0
    if wide <= compact:
        return 0.0
    # 裁剪value到[compact, wide]范围
    clipped = max(compact, min(wide, float(value)))
    # 计算比例：0=compact，1=wide
    ratio = (clipped - compact) / (wide - compact)
    # 映射到[1, -1]：compact->1, wide->-1
    return 1.0 - 2.0 * ratio


def _file_scope_signal(file_count: int, scope_protocol: dict | None = None) -> float:
    """
    计算文件范围信号：文件数量是否聚焦

    使用范围协议中的边界值判断文件数是否"聚焦"：
    - 小于file_scope_small_max -> 聚焦（返回1.0）
    - 大于file_scope_large_min -> 分散（返回-1.0）

    参数:
        file_count: 文件数量
        scope_protocol: 范围协议字典

    返回:
        float: 文件范围信号 [-1, 1]
    """
    protocol = scope_protocol or {}
    # 从协议获取边界值，如果无协议则用实际值作为默认值
    compact = float(protocol.get("file_scope_small_max", float(file_count)))
    wide = float(protocol.get("file_scope_large_min", float(file_count)))
    return _continuous_scope_signal(
        file_count, compact_anchor=compact, wide_anchor=wide
    )


def _patch_scope_signal(
    changed_lines: int, scope_protocol: dict | None = None
) -> float:
    """
    计算patch范围信号：变更行数是否聚焦

    使用范围协议中的边界值判断变更行数是否"聚焦"。

    参数:
        changed_lines: 变更行数（新增+删除）
        scope_protocol: 范围协议字典

    返回:
        float: patch范围信号 [-1, 1]
    """
    protocol = scope_protocol or {}
    compact = float(protocol.get("patch_scope_small_max", float(changed_lines)))
    wide = float(protocol.get("patch_scope_large_min", float(changed_lines)))
    return _continuous_scope_signal(
        changed_lines, compact_anchor=compact, wide_anchor=wide
    )


def _hunk_scope_signal(hunk_count: int, scope_protocol: dict | None = None) -> float:
    """
    计算hunk范围信号：hunk数量是否聚焦

    参数:
        hunk_count: diff中@@块的数量
        scope_protocol: 范围协议字典

    返回:
        float: hunk范围信号 [-1, 1]
    """
    protocol = scope_protocol or {}
    compact = float(protocol.get("hunk_scope_few_max", float(hunk_count)))
    wide = float(protocol.get("hunk_scope_many_min", float(hunk_count)))
    return _continuous_scope_signal(
        hunk_count, compact_anchor=compact, wide_anchor=wide
    )


def _role_focus_signal(roles: set[str]) -> float:
    """
    计算角色聚焦信号：文件角色是否聚焦

    规则：
    - 无角色 -> 0.0
    - 单角色 -> 1.0（最聚焦）
    - source + 支持角色混合 -> 线性衰减（可接受）
    - 其他混合 -> -1.0（分散）

    参数:
        roles: 文件角色集合（如{"source", "test"}）

    返回:
        float: 角色聚焦信号 [-1, 1]
    """
    if not roles:
        return 0.0
    if len(roles) == 1:
        return 1.0
    # source + 支持角色混合是可接受的
    if "source" in roles and roles.issubset(SOURCE_WITH_SUPPORT_ROLE_SET):
        max_span = max(1.0, float(len(SOURCE_WITH_SUPPORT_ROLE_SET)))
        return 1.0 - float(len(roles) - 1) / max_span
    return -1.0


def _module_focus_signal(
    module_count: int, scope_protocol: dict | None = None
) -> float:
    """
    计算模块聚焦信号：模块数量是否聚焦

    参数:
        module_count: 模块数量（source文件的路径首段）
        scope_protocol: 范围协议字典

    返回:
        float: 模块聚焦信号 [-1, 1]
    """
    protocol = scope_protocol or {}
    if module_count == 0:
        return 1.0  # 无模块=无分散，认为聚焦
    compact = float(protocol.get("module_scope_focused_max", float(module_count)))
    wide = float(protocol.get("module_scope_scattered_min", float(module_count)))
    return _continuous_scope_signal(
        module_count, compact_anchor=compact, wide_anchor=wide
    )


def atomic_signal_map(
    message_features: dict,
    candidate_type: str,
    diff_features: dict | None = None,
    message_protocol: dict | None = None,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> dict[str, float]:
    """
    构建原子性信号映射

    将消息特征、diff特征和协议组合成多个原子性信号。
    每个信号的取值范围为[-1, 1]：
    - 1.0 = 完全有利于单意图
    - 0.0 = 中性
    - -1.0 = 完全不利于单意图

    信号分为两类：
    1. 消息信号（6个）：仅使用消息特征即可计算
    2. Diff信号（6个）：需要diff特征

    消息相关信号（始终计算）：
    - prefix_valid: 是否符合Conventional Commit格式
    - subject_compact: subject长度是否在合理范围
    - body_compact: body是否简洁（行数和段落数适中）
    - single_focus_message: 是否含多意图标记
    - clean_message: 是否含噪声标记
    - not_release_like: 是否非发布类

    Diff相关信号（需要diff_features）：
    - file_scope_signal: 文件数量是否聚焦
    - patch_scope_signal: 变更行数是否聚焦
    - hunk_scope_signal: hunk数量是否聚焦
    - role_focus_signal: 文件角色是否聚焦
    - module_focus_signal: 模块数量是否聚焦
    - commit_type_signal: 类型流行度

    参数:
        message_features: 消息特征字典（来自parse_message）
        candidate_type: 提交类型（如fix, feat等）
        diff_features: diff特征字典（来自parse_diff，可选）
        message_protocol: 消息协议字典（可选）
        scope_protocol: 范围协议字典（可选）
        type_protocol: 类型协议字典（可选）

    返回:
        dict[str, float]: 信号名到信号值的映射
    """
    # === 步骤1: 从协议中提取边界值 ===
    protocol = message_protocol or {}
    subject_len = int(message_features.get("subject_len", 0))
    body_line_count = int(message_features.get("body_line_count", 0))
    paragraph_count = int(message_features.get("paragraph_count", 0))

    # subject长度边界
    subject_len_min = int(
        round(float(protocol.get("subject_len_min", max(1, subject_len))))
    )
    subject_len_max = int(
        round(float(protocol.get("subject_len_max", max(subject_len_min, subject_len))))
    )

    # body行数边界
    body_compact_max_lines = int(
        round(float(protocol.get("body_compact_max_lines", max(0, body_line_count))))
    )
    body_fragmented_min_lines = int(
        round(
            float(
                protocol.get(
                    "body_fragmented_min_lines",
                    max(body_compact_max_lines, body_line_count),
                )
            )
        )
    )

    # 段落数边界
    paragraph_compact_max = int(
        round(float(protocol.get("paragraph_compact_max", max(0, paragraph_count))))
    )
    paragraph_fragmented_min = int(
        round(
            float(
                protocol.get(
                    "paragraph_fragmented_min",
                    max(paragraph_compact_max, paragraph_count),
                )
            )
        )
    )

    # === 步骤2: 计算消息信号（6个）===
    signals = {
        # 2.1 prefix_valid: 是否符合Conventional Commit格式
        "prefix_valid": 1.0 if message_features["prefix_match"] else -1.0,
        # 2.2 subject_compact: subject长度是否在合理范围
        "subject_compact": 1.0
        if subject_len_min <= message_features["subject_len"] <= subject_len_max
        else -1.0,
        # 2.3 body_compact: body是否简洁
        # 条件：行数<=compact_max AND 段落数<=compact_max
        # 否则如果行数>=fragmented_min OR 段落数>=fragmented_min -> -1
        # 否则 -> 0（中间状态）
        "body_compact": 1.0
        if message_features["body_line_count"] <= body_compact_max_lines
        and message_features["paragraph_count"] <= paragraph_compact_max
        else (
            -1.0
            if message_features["body_line_count"] >= body_fragmented_min_lines
            or message_features["paragraph_count"] >= paragraph_fragmented_min
            else 0.0
        ),
        # 2.4 single_focus_message: 是否含多意图标记
        "single_focus_message": -1.0 if message_features["has_multi_markers"] else 1.0,
        # 2.5 clean_message: 是否含噪声标记
        "clean_message": -1.0 if message_features["has_noisy_markers"] else 1.0,
        # 2.6 not_release_like: 是否非发布类
        "not_release_like": -1.0 if message_features["release_like"] else 1.0,
    }

    # === 步骤3: 计算Diff信号（需要diff特征）===
    if diff_features:
        # 3.1 file_scope_signal: 文件数是否聚焦
        signals["file_scope_signal"] = _file_scope_signal(
            int(diff_features.get("file_count", 0)), scope_protocol
        )

        # 3.2 patch_scope_signal: 变更行数是否聚焦
        signals["patch_scope_signal"] = _patch_scope_signal(
            int(diff_features.get("changed_lines", 0)), scope_protocol
        )

        # 3.3 hunk_scope_signal: hunk数是否聚焦
        signals["hunk_scope_signal"] = _hunk_scope_signal(
            int(diff_features.get("hunk_count", 0)), scope_protocol
        )

        # 3.4 role_focus_signal: 文件角色是否聚焦
        signals["role_focus_signal"] = _role_focus_signal(
            set(diff_features.get("roles", []))
        )

        # 3.5 module_focus_signal: 模块数是否聚焦
        signals["module_focus_signal"] = _module_focus_signal(
            int(diff_features.get("module_count", 0)), scope_protocol
        )

    # commit_type_signal在message-only和full-diff路径都应可用
    signals["commit_type_signal"] = _commit_type_signal(candidate_type, type_protocol)

    # 确保所有原子性信号键都存在（message-only路径下diff信号补0）
    for key in ATOMIC_SIGNAL_KEYS:
        signals.setdefault(key, 0.0)

    # === 步骤4: 返回信号映射 ===
    return signals


def summarize_signal_reasons(signals: dict[str, float], top_k: int = 6) -> list[str]:
    """
    总结信号原因

    按信号绝对强度排序，取top-k个非零信号，生成原因列表。
    用于人类可读的结果展示。

    参数:
        signals: 信号字典（键为信号名，值为-1到1）
        top_k: 返回的原因数量上限

    返回:
        list[str]: 原因列表，格式为"极性:信号名"
        - "pos:prefix_valid" 表示正向信号
        - "neg:has_multi_markers" 表示负向信号
    """
    # 按绝对值降序排列（最强的信号在前）
    ranked = sorted(signals.items(), key=lambda item: abs(float(item[1])), reverse=True)
    reasons: list[str] = []
    for key, value in ranked:
        # 跳过零值信号
        if abs(float(value)) <= 0.0:
            continue
        # 确定极性
        polarity = "pos" if float(value) > 0 else "neg"
        reasons.append(f"{polarity}:{key}")
        # 达到top_k后停止
        if len(reasons) >= top_k:
            break
    return reasons


def derive_atomic_signal_context(signal_maps: list[dict[str, float]]) -> dict:
    """
    派生原子性信号上下文

    基于信号分布的分散度自适应计算权重，替代手工设置固定权重。
    核心思想：分散度高的信号被认为是更具有信息量的。

    推导步骤：
    1. 计算每个信号的分散度（标准差）
    2. 将分散度归一化为权重
    3. 计算加权组合后的中位数作为偏置
    4. 计算缩放因子使组合分数的标准差为1

    参数:
        signal_maps: 信号映射列表（每个元素是一个信号的字典）

    返回:
        dict: 信号上下文，包含:
        - weights: 信号权重字典（各权重之和为1）
        - bias: 偏置（负的中位数，使大部分分数为正）
        - scale: 缩放因子（使组合分数的标准差为1）
        - source: 来源说明
    """
    # 空输入返回默认值
    if not signal_maps:
        return {
            "weights": DEFAULT_ATOMIC_WEIGHTS,
            "bias": DEFAULT_ATOMIC_BIAS,
            "scale": 1.0,
            "source": "fallback_empty_signal_pool",
        }

    # === 步骤1: 计算每个信号的分散度（作为信息量代理）===
    # 分散度高 = 信号在不同样本间变化大 = 更有区分力
    dispersion: dict[str, float] = {}
    for key in ATOMIC_SIGNAL_KEYS:
        values = [float(item.get(key, 0.0)) for item in signal_maps]
        if len(values) > 1:
            spread = statistics.pstdev(values)  # 标准差
        else:
            spread = abs(values[0]) if values else 0.0
        # 加EPS避免零值
        dispersion[key] = max(spread, SIGNAL_DISPERSION_EPS)

    # === 步骤2: 归一化分散度为权重 ===
    dispersion_sum = sum(dispersion.values())
    if dispersion_sum <= SIGNAL_DISPERSION_EPS:
        # 分散度之和过小，退化为均匀权重
        weights = dict(DEFAULT_ATOMIC_WEIGHTS)
        source = "fallback_uniform_weight"
    else:
        # 分散度归一化为权重
        weights = {key: value / dispersion_sum for key, value in dispersion.items()}
        source = "distribution_signal_dispersion"

    # === 步骤3: 计算加权组合分数的统计量 ===
    pooled_scores = []
    for signals in signal_maps:
        # 计算每个样本的加权组合分数
        pooled_scores.append(
            sum(
                weights[key] * float(signals.get(key, 0.0))
                for key in ATOMIC_SIGNAL_KEYS
            )
        )

    # === 步骤4: 计算偏置和缩放因子 ===
    if pooled_scores:
        center = statistics.median(pooled_scores)  # 中位数
        spread = (
            statistics.pstdev(pooled_scores)  # 标准差
            if len(pooled_scores) > 1
            else abs(pooled_scores[0])
        )
    else:
        center = 0.0
        spread = 1.0
    # 缩放因子：使组合分数的标准差为1，便于后续sigmoid处理
    scale = 1.0 / max(spread, LOGIT_SCALE_EPS)

    return {
        "weights": weights,
        "bias": -center,  # 偏置为负的中位数，使大部分分数为正
        "scale": scale,
        "source": source,
    }


def atomic_logit(
    message_features: dict,
    candidate_type: str,
    diff_features: dict | None = None,
    signal_context: dict | None = None,
    message_protocol: dict | None = None,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> float:
    """
    计算原子性logit值

    将多个信号组合成单个logit值：
    logit = scale * (bias + sum(weight_i * signal_i))

    这是启发式先验路径的核心计算函数。

    参数:
        message_features: 消息特征字典
        candidate_type: 提交类型（如fix, feat等）
        diff_features: diff特征字典（可选）
        signal_context: 信号上下文（权重、偏置、缩放因子）
        message_protocol: 消息协议（可选）
        scope_protocol: 范围协议（可选）
        type_protocol: 类型协议（可选）

    返回:
        float: logit值，可以是任意实数
    """
    # 步骤1: 计算信号映射
    signals = atomic_signal_map(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=diff_features,
        message_protocol=message_protocol,
        scope_protocol=scope_protocol,
        type_protocol=type_protocol,
    )

    # 步骤2: 获取权重和参数
    # 优先使用signal_context中的权重，否则使用默认均匀权重
    if signal_context and isinstance(signal_context.get("weights"), dict):
        raw_weights = signal_context["weights"]
        weights = {key: float(raw_weights.get(key, 0.0)) for key in ATOMIC_SIGNAL_KEYS}
        bias = float(signal_context.get("bias", DEFAULT_ATOMIC_BIAS))
        scale = float(signal_context.get("scale", 1.0))
    else:
        weights = dict(DEFAULT_ATOMIC_WEIGHTS)
        bias = DEFAULT_ATOMIC_BIAS
        scale = 1.0

    # 步骤3: 计算加权和
    value = bias + sum(weights[key] * signals[key] for key in ATOMIC_SIGNAL_KEYS)

    # 步骤4: 缩放后返回
    return scale * value


def apply_platt_calibration(logit: float, slope: float, intercept: float) -> float:
    """
    应用Platt校准

    将logit值通过Platt scaling转换为概率：
    p = sigmoid(slope * logit + intercept)

    参数:
        logit: 原始logit值
        slope: 缩放参数
        intercept: 偏移参数

    返回:
        float: 校准后的概率值
    """
    return sigmoid(slope * logit + intercept)


def apply_calibration_to_raw_prob(
    raw_probability: float, raw_logit: float, calibration: dict | None
) -> float:
    """
    将原始概率通过校准器转换为校准后概率

    支持两种校准方式：
    1. Isotonic Regression（等渗回归）：保序回归，适合非线性校准
    2. Platt Scaling：线性变换，适合二分类校准

    参数:
        raw_probability: 原始概率值
        raw_logit: 原始logit值（用于Platt校准）
        calibration: 校准参数字典，包含:
        - isotonic: 等渗回归参数 {x: [...], y: [...]}
        - platt_slope, platt_intercept: Platt参数

    返回:
        float: 校准后的概率值
    """
    # 无校准参数直接返回原始值
    if calibration is None:
        return raw_probability

    # 尝试等渗回归校准
    isotonic = calibration.get("isotonic")
    if isotonic and isinstance(isotonic, dict):
        x_values = isotonic.get("x", [])
        y_values = isotonic.get("y", [])
        if (
            isinstance(x_values, list)
            and isinstance(y_values, list)
            and x_values
            and y_values
        ):
            # 使用等渗回归预测
            return clip_prob(_isotonic_predict(raw_probability, x_values, y_values))

    # 尝试Platt校准
    if "platt_slope" in calibration and "platt_intercept" in calibration:
        slope = float(calibration.get("platt_slope", 1.0))
        intercept = float(calibration.get("platt_intercept", 0.0))
        return clip_prob(
            apply_platt_calibration(raw_logit, slope=slope, intercept=intercept)
        )

    # 无有效校准方式返回原始值
    return raw_probability


def estimate_model_epistemic_uncertainty(model, feature_vector: list[float]) -> float:
    """
    估计模型的认知不确定性

    使用GBDT的staged_predict_proba计算认知不确定性：
    - 在每棵树上运行预测，得到一系列概率
    - 计算这些概率的标准差

    标准差越大，表示模型对预测的不确定性越高。

    参数:
        model: 训练好的GBDT模型
        feature_vector: 特征向量

    返回:
        float: 认知不确定性（标准差），范围[0, 0.5]
    """
    staged_probs = []
    # 获取staged预测方法
    staged_fn = getattr(model, "staged_predict_proba", None)
    if staged_fn is None:
        return 0.0  # 模型不支持staged预测
    try:
        # 遍历每棵树，收集预测概率
        for stage_probs in staged_fn([feature_vector]):
            if len(stage_probs) == 0 or len(stage_probs[0]) < 2:
                continue
            staged_probs.append(float(stage_probs[0][1]))
    except Exception:
        return 0.0  # 预测失败返回0
    # 至少需要2个stage才能计算标准差
    if len(staged_probs) < 2:
        return 0.0
    return float(statistics.pstdev(staged_probs))


def atomic_prior(
    message_features: dict,
    candidate_type: str,
    diff_features: dict | None = None,
    calibration: dict | None = None,
    repo_stats: dict[str, dict[str, float]] | None = None,
    global_stats: dict[str, dict[str, float]] | None = None,
    signal_context: dict | None = None,
    epistemic_reference: dict[str, float] | None = None,
    message_protocol: dict | None = None,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> dict:
    """
    计算原子性先验

    这是计算单意图概率的核心函数，包含两条路径：

    模型路径（精确）：
    - 条件：有校准文件 + 有GBDT模型 + 有非空diff特征
    - 流程：GBDT预测 -> Isotonic校准 -> 认知不确定性估计

    启发式路径（快速）：
    - 条件：无模型，但有非空diff特征
    - 流程：信号加权 -> sigmoid映射 -> 无校准

    参数:
        message_features: 消息特征字典（来自parse_message）
        candidate_type: 提交类型（如fix, feat等）
        diff_features: diff特征字典（来自parse_diff，可选）
        calibration: 校准参数字典（可选，包含模型、协议等）
        repo_stats: 仓库级别统计（可选，用于归一化）
        global_stats: 全局级别统计（可选，用于归一化）
        signal_context: 信号上下文（权重、偏置、缩放）
        epistemic_reference: 认知不确定性参考（center, scale）
        message_protocol: 消息协议
        scope_protocol: 范围协议
        type_protocol: 类型协议

    返回:
        dict: 原子性先验信息，包含:
        - atomic_logit: 原始logit值
        - atomic_prior: 原始概率（裁剪后）
        - atomic_prior_calibrated: 校准后概率
        - p_raw: 同atomic_prior（兼容字段）
        - p_atomic: 同atomic_prior_calibrated（兼容字段）
        - omega_atomic: 不确定性权重
        - epistemic_std: 认知不确定性
        - x_atom: 特征向量（JSON字符串）
        - signal_context_source: 信号上下文来源
    """
    # === 步骤1: 从校准文件提取协议（如果未传入）===
    # 优先级：显式传入的参数 > 校准文件中的值
    if (
        epistemic_reference is None
        and isinstance(calibration, dict)
        and isinstance(calibration.get("epistemic_reference"), dict)
    ):
        epistemic_reference = calibration.get("epistemic_reference")
    if (
        message_protocol is None
        and isinstance(calibration, dict)
        and isinstance(calibration.get("message_protocol"), dict)
    ):
        message_protocol = calibration.get("message_protocol")
    if (
        scope_protocol is None
        and isinstance(calibration, dict)
        and isinstance(calibration.get("scope_protocol"), dict)
    ):
        scope_protocol = calibration.get("scope_protocol")
    if (
        type_protocol is None
        and isinstance(calibration, dict)
        and isinstance(calibration.get("type_protocol"), dict)
    ):
        type_protocol = calibration.get("type_protocol")

    # === 步骤2: 校验diff特征并构建特征向量 ===
    has_diff = (
        diff_features is not None
        and float(diff_features.get("file_count", 0.0)) > 0
        and float(diff_features.get("changed_lines", 0.0)) > 0
    )
    if not has_diff:
        raise ValueError(
            "atomic_prior requires non-empty diff features; "
            "no-diff heuristic fallback has been removed"
        )

    feature_map = build_atomic_feature_map(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=diff_features,
        repo_stats=repo_stats,
        global_stats=global_stats,
    )

    # === 步骤3: 选择计算路径 ===
    prior = 0.0
    epistemic_std = 0.0

    # 判断是否使用模型路径
    use_model = (
        calibration is not None
        and calibration.get("_runtime_model") is not None  # 有GBDT模型
        and has_diff  # 有非空diff特征
    )

    if use_model:
        # === 模型路径 ===
        # 3.1 提取特征向量（按模型要求的顺序）
        feature_order = calibration.get("feature_order", ATOMIC_FEATURE_ORDER)
        feature_vector = [float(feature_map.get(name, 0.0)) for name in feature_order]

        # 3.2 GBDT预测
        probabilities = calibration["_runtime_model"].predict_proba([feature_vector])
        if len(probabilities) == 0 or len(probabilities[0]) < 2:
            prior = 0.5  # 预测失败使用0.5
        else:
            prior = clip_prob(float(probabilities[0][1]))

        # 3.3 估计认知不确定性
        epistemic_std = estimate_model_epistemic_uncertainty(
            calibration["_runtime_model"],
            feature_vector=feature_vector,
        )

        # 3.4 计算原始logit（用于后续Platt校准）
        raw_logit = safe_logit(prior)
    else:
        # === 启发式路径 ===
        # 使用信号加权计算logit，然后sigmoid映射
        raw_logit = atomic_logit(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=diff_features,
            signal_context=signal_context,
            message_protocol=message_protocol,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )
        prior = sigmoid(raw_logit)  # 直接sigmoid，无校准

    # === 步骤4: 应用校准 ===
    calibration_for_apply = calibration
    if (
        calibration is not None
        and calibration.get("_runtime_model") is not None
        and not use_model
    ):
        calibration_for_apply = None
    calibrated = apply_calibration_to_raw_prob(
        prior, raw_logit, calibration=calibration_for_apply
    )

    # === 步骤5: 计算不确定性权重 ===
    epistemic_center = float((epistemic_reference or {}).get("center", 0.0))
    epistemic_scale = float((epistemic_reference or {}).get("scale", 1.0))
    omega = derive_atomic_weight(
        calibrated,
        epistemic_std=epistemic_std,
        epistemic_center=epistemic_center,
        epistemic_scale=epistemic_scale,
    )

    # === 步骤6: 返回完整结果 ===
    return {
        "atomic_logit": raw_logit,
        "atomic_prior": clip_prob(prior),
        "atomic_prior_calibrated": clip_prob(calibrated),
        "p_raw": clip_prob(prior),
        "p_atomic": clip_prob(calibrated),
        "omega_atomic": clip_prob(omega),
        "epistemic_std": float(epistemic_std),
        "x_atom": json.dumps(feature_map, ensure_ascii=False, sort_keys=True),
        "signal_context_source": (signal_context or {}).get(
            "source", "default_uniform_fallback"
        ),
    }


def assign_atomic_tier(probability: float, tau_a: float, tau_b: float) -> str:
    """
    分配原子性Tier等级

    基于校准后的概率将提交分为三个置信度等级：
    - Tier A: 高置信度单意图（probability > tau_a）
    - Tier B: 中等置信度（tau_b < probability <= tau_a）
    - Tier C: 低置信度或非单意图（probability <= tau_b）

    参数:
        probability: 校准后的原子性概率
        tau_a: Tier A阈值（必须大于tau_b）
        tau_b: Tier B阈值

    返回:
        str: Tier等级 ("A", "B", 或 "C")

    异常:
        ValueError: 当tau_a <= tau_b时抛出
    """
    if tau_a <= tau_b:
        raise ValueError("tau_a must be greater than tau_b")
    if probability > tau_a:
        return "A"
    if probability > tau_b:
        return "B"
    return "C"


def resolve_thresholds(
    calibration: dict | None, tau_a: float | None, tau_b: float | None
) -> tuple[float | None, float | None]:
    """
    解析阈值

    从校准文件中提取阈值（如果存在），或使用命令行传入的值。

    参数:
        calibration: 校准参数字典（包含thresholds字段）
        tau_a: 命令行传入的tau_a值（可选）
        tau_b: 命令行传入的tau_b值（可选）

    返回:
        tuple[float | None, float | None]: (resolved_tau_a, resolved_tau_b)
        - 如果校准文件中有有效阈值，使用校准文件的值
        - 否则使用命令行传入的值
    """
    # 先读取校准文件阈值（若有效）
    calibrated_a: float | None = None
    calibrated_b: float | None = None
    if calibration and isinstance(calibration.get("thresholds"), dict):
        thresholds = calibration["thresholds"]
        threshold_a = thresholds.get("tau_a")
        threshold_b = thresholds.get("tau_b")
        if threshold_a is not None and threshold_b is not None:
            candidate_a = float(threshold_a)
            candidate_b = float(threshold_b)
            if candidate_a > candidate_b:
                calibrated_a = candidate_a
                calibrated_b = candidate_b

    # 显式命令行参数优先覆盖对应维度
    resolved_a = calibrated_a
    resolved_b = calibrated_b
    if tau_a is not None:
        resolved_a = float(tau_a)
    if tau_b is not None:
        resolved_b = float(tau_b)
    return resolved_a, resolved_b


def derive_threshold_seed_from_distribution(
    probabilities: list[float],
) -> tuple[float, float]:
    """
    从概率分布派生阈值种子

    使用分位数作为初始阈值：
    - tau_a = 2/3分位数（较高中位数）
    - tau_b = 1/3分位数（较低中位数）

    这是分布驱动阈值推导的fallback方法。

    参数:
        probabilities: 概率列表（通常为校准后的概率）

    返回:
        tuple[float, float]: (tau_a, tau_b)

    异常:
        ValueError: 当概率列表为空或分布退化时抛出
    """
    if not probabilities:
        raise ValueError("cannot derive thresholds from empty probability pool")
    # 裁剪到有效范围
    clipped = [clip_prob(item) for item in probabilities]
    # 计算分位数
    lower = quantile(clipped, 1.0 / 3.0, default=min(clipped))
    upper = quantile(clipped, 2.0 / 3.0, default=max(clipped))
    # 处理退化情况
    if upper <= lower:
        lower = min(clipped)
        upper = max(clipped)
    if upper <= lower:
        raise ValueError(
            "probability distribution is degenerate; unable to derive tau_a/tau_b"
        )
    return upper, lower  # tau_a > tau_b


def derive_thresholds(
    probabilities: list[float],
    calibration: dict | None,
    tau_a: float | None,
    tau_b: float | None,
) -> tuple[float, float, str]:
    """
    派生Tier阈值

    确定Tier A和Tier B的边界阈值，优先级：
    1. 如果校准文件中有阈值约束（精确率约束），使用校准文件的值
    2. 否则使用分布推导（3-cluster边界）

    参数:
        probabilities: 概率列表（用于分布推导）
        calibration: 校准参数字典
        tau_a: 命令行传入的tau_a（可选）
        tau_b: 命令行传入的tau_b（可选）

    返回:
        tuple[float, float, str]: (tau_a, tau_b, source)
        - source: 阈值来源说明
    """
    # 步骤1: 解析候选阈值（显式参数优先）
    resolved_a, resolved_b = resolve_thresholds(
        calibration=calibration, tau_a=tau_a, tau_b=tau_b
    )
    has_explicit_a = tau_a is not None
    has_explicit_b = tau_b is not None
    if resolved_a is not None and resolved_b is not None:
        if float(resolved_a) <= float(resolved_b):
            raise ValueError("resolved thresholds invalid: tau_a <= tau_b")
        if has_explicit_a and has_explicit_b:
            return float(resolved_a), float(resolved_b), "fixed_from_args"
        if has_explicit_a or has_explicit_b:
            return float(resolved_a), float(resolved_b), "mixed_calibration_and_args"
        if calibration and isinstance(calibration.get("thresholds"), dict):
            return (
                float(resolved_a),
                float(resolved_b),
                "constraint_from_calibration_precision",
            )

    # 步骤2: 分布推导
    # 使用分位数作为种子
    seed_a, seed_b = derive_threshold_seed_from_distribution(probabilities)
    # 命令行参数可以覆盖种子值
    fallback_a = float(resolved_a) if resolved_a is not None else seed_a
    fallback_b = float(resolved_b) if resolved_b is not None else seed_b

    # 步骤3: 使用3-cluster边界精细化
    derived: TierThresholds = derive_tier_thresholds_from_distribution(
        scores=probabilities,
        fallback_tau_a=fallback_a,
        fallback_tau_b=fallback_b,
    )
    if derived.tau_a <= derived.tau_b:
        raise ValueError("derived thresholds invalid: tau_a <= tau_b")
    return derived.tau_a, derived.tau_b, derived.source


def derive_gate_threshold(
    probabilities: list[float], configured_min_prior: float
) -> tuple[float, str]:
    """
    派生门控阈值

    门控阈值用于过滤低置信度候选。
    支持两种模式：
    1. 固定模式：直接使用配置值
    2. 自动模式：基于熵预算约束推导

    参数:
        probabilities: 概率列表
        configured_min_prior: 配置的最小先验值

    返回:
        tuple[float, str]: (gate_threshold, source)
    """
    return derive_gate_threshold_by_uncertainty(
        scores=probabilities, fixed_gate=configured_min_prior
    )


def calibration_model_mode(calibration: dict | None) -> str:
    """
    解析校准工件的模型模式。

    返回：
    - ``full_diff``: 使用完整 diff 特征的主模型
    - ``message_only``: 仅使用 message/type 特征的低成本 proxy
    - ``""``: 无法识别
    """
    if not isinstance(calibration, dict):
        return ""
    explicit_mode = str(calibration.get("model_mode", "")).strip().lower()
    if explicit_mode in {"full_diff", "message_only"}:
        return explicit_mode
    fit_config = calibration.get("fit_config")
    if isinstance(fit_config, dict):
        fit_mode = str(fit_config.get("mode", "")).strip().lower()
        if fit_mode in {"message_only_isotonic", "message_only_platt"}:
            return "message_only"
        if fit_mode in {"gbdt_isotonic", "platt"}:
            return "full_diff"
    artifact_version = str(calibration.get("artifact_version", "")).strip().lower()
    if "message_only" in artifact_version:
        return "message_only"
    if (
        artifact_version.startswith("step1_atomic_")
        or artifact_version == "step1_platt_v1"
    ):
        return "full_diff"
    return ""


def calibration_model_role(calibration: dict | None) -> str:
    """
    解析校准工件的语义角色。

    ``full_diff`` 工件是 ``primary``，``message_only`` 工件是 ``proxy``。
    """
    if not isinstance(calibration, dict):
        return ""
    explicit_role = str(calibration.get("model_role", "")).strip().lower()
    if explicit_role in {"primary", "proxy"}:
        return explicit_role
    inferred_mode = calibration_model_mode(calibration)
    if inferred_mode == "full_diff":
        return "primary"
    if inferred_mode == "message_only":
        return "proxy"
    return ""


def is_message_only_calibration(calibration: dict | None) -> bool:
    """返回工件是否为 message-only proxy calibration。"""
    return calibration_model_mode(calibration) == "message_only"


def is_full_diff_calibration(calibration: dict | None) -> bool:
    """返回工件是否为 full-diff primary calibration。"""
    return calibration_model_mode(calibration) == "full_diff"


def require_calibration_mode(
    calibration: dict | None,
    *,
    expected_mode: str,
    context: str,
) -> dict:
    """
    强制校准工件与当前路径的模型语义匹配。

    不允许静默把 proxy 当 primary，或把 primary 当 proxy。
    """
    if not isinstance(calibration, dict):
        raise ValueError(f"{context} requires a `{expected_mode}` calibration artifact")
    actual_mode = calibration_model_mode(calibration)
    if actual_mode != expected_mode:
        raise ValueError(
            f"{context} requires a `{expected_mode}` calibration artifact, got `{actual_mode or 'unknown'}`"
        )
    return calibration


def load_calibration(path: str) -> dict | None:
    """
    加载校准文件

    读取校准JSON文件，支持两种格式：
    1. 完整格式：包含GBDT模型（Base64编码）+ Isotonic参数 + 协议
    2. 简单格式：仅包含Platt参数或Isotonic映射

    参数:
        path: 校准JSON文件路径

    返回:
        dict | None: 校准参数字典，包含:
        - _runtime_model: 反序列化的GBDT模型（如果有）
        - feature_order: 特征顺序
        - isotonic: 等渗回归参数
        - thresholds: 阈值
        - 协议字典等

    异常:
        FileNotFoundError: 文件不存在
        ValueError: 文件格式无效
    """
    # 空路径返回None
    if not path:
        return None
    # 检查文件是否存在
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"calibration file not found: {path}")

    # 读取JSON
    data = json.loads(file_path.read_text(encoding="utf-8"))

    # 检查是否包含模型（完整格式）
    if "model_pickle_b64" in data:
        # Base64解码 -> 反序列化
        raw_bytes = base64.b64decode(data["model_pickle_b64"].encode("utf-8"))
        data["_runtime_model"] = pickle.loads(raw_bytes)
        # 确保有特征顺序
        if "feature_order" not in data:
            data["feature_order"] = ATOMIC_FEATURE_ORDER
        return data

    # 简单格式：检查是否有有效的校准参数
    has_platt = "platt_slope" in data and "platt_intercept" in data
    has_isotonic = isinstance(data.get("isotonic"), dict)
    if not has_platt and not has_isotonic:
        raise ValueError(
            "calibration file must contain either platt params or isotonic mapping"
        )
    return data


def score_message_only(
    message_features: dict,
    candidate_type: str,
    signal_context: dict | None = None,
    message_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> tuple[float, list[str]]:
    """
    仅基于消息计算分数（用于预过滤阶段）

    不使用diff特征，仅根据消息特征计算原子性分数。
    这是预过滤阶段的简化版本。

    参数:
        message_features: 消息特征字典
        candidate_type: 提交类型
        signal_context: 信号上下文
        message_protocol: 消息协议
        type_protocol: 类型协议

    返回:
        tuple[float, list[str]]: (score, reasons)
        - score: 原子性分数 [0, 100]
        - reasons: 信号原因列表
    """
    # 计算信号映射（diff_features=None）
    signals = atomic_signal_map(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=None,  # 无diff
        message_protocol=message_protocol,
        type_protocol=type_protocol,
    )
    context = (
        signal_context
        if isinstance((signal_context or {}).get("weights"), dict)
        else derive_atomic_signal_context([signals])
    )
    logit = atomic_logit(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=None,
        signal_context=context,
        message_protocol=message_protocol,
        type_protocol=type_protocol,
    )
    score = 100.0 * clip_prob(sigmoid(logit))
    return round(score, 6), summarize_signal_reasons(signals)


def score_commit(
    message_features: dict,
    diff_features: dict,
    candidate_type: str,
    signal_context: dict | None = None,
    message_protocol: dict | None = None,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> tuple[float, list[str]]:
    """
    基于消息和diff计算分数（用于增强阶段）

    与score_message_only不同，这里使用完整的diff特征。
    计算流程：
    1. 构建完整信号映射（消息+diff）
    2. 计算或使用signal_context
    3. 计算logit -> sigmoid -> 100

    参数:
        message_features: 消息特征字典
        diff_features: diff特征字典
        candidate_type: 提交类型
        signal_context: 信号上下文
        message_protocol: 消息协议
        scope_protocol: 范围协议
        type_protocol: 类型协议

    返回:
        tuple[float, list[str]]: (score, reasons)
    """
    # 计算完整信号映射（包含diff信号）
    signals = atomic_signal_map(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=diff_features,  # 有diff
        message_protocol=message_protocol,
        scope_protocol=scope_protocol,
        type_protocol=type_protocol,
    )
    # 获取或派生signal_context
    context = (
        signal_context
        if isinstance((signal_context or {}).get("weights"), dict)
        else derive_atomic_signal_context([signals])
    )
    # 计算logit
    logit = atomic_logit(
        message_features=message_features,
        candidate_type=candidate_type,
        diff_features=diff_features,
        signal_context=context,
        message_protocol=message_protocol,
        scope_protocol=scope_protocol,
        type_protocol=type_protocol,
    )
    # 转换为0-100分数
    score = 100.0 * clip_prob(sigmoid(logit))
    return round(score, 6), summarize_signal_reasons(signals)


def utility_score(
    candidate_type: str,
    diff_features: dict,
    scope_protocol: dict | None = None,
    type_protocol: dict | None = None,
) -> tuple[float, list[str]]:
    """
    计算结构化价值分数（Utility Score）

    与原子性概率不同，utility衡量提交的结构化价值：
    - 文件范围是否聚焦
    - Patch大小是否合理
    - 角色分布是否纯净
    - 等等

    这个分数用于：
    1. 排序辅助（当原子性概率相同时，优先选择utility高的）
    2. 质量过滤（utility过低可能表示结构过于分散）

    参数:
        candidate_type: 提交类型
        diff_features: diff特征字典
        scope_protocol: 范围协议
        type_protocol: 类型协议

    返回:
        tuple[float, list[str]]: (utility, reasons)
        - utility: 结构化价值 [0, 100]
    """
    # 提取角色集合
    roles = set(diff_features["roles"])
    # 计算6个结构化信号
    structural_signals = {
        "file_scope_signal": _file_scope_signal(
            diff_features["file_count"], scope_protocol=scope_protocol
        ),
        "patch_scope_signal": _patch_scope_signal(
            diff_features["changed_lines"], scope_protocol=scope_protocol
        ),
        "hunk_scope_signal": _hunk_scope_signal(
            diff_features["hunk_count"], scope_protocol=scope_protocol
        ),
        "role_focus_signal": _role_focus_signal(roles),
        "module_focus_signal": _module_focus_signal(
            diff_features["module_count"], scope_protocol=scope_protocol
        ),
        "commit_type_signal": _commit_type_signal(
            candidate_type, type_protocol=type_protocol
        ),
    }
    # 平均后映射到[0, 100]
    mean_signal = sum(structural_signals.values()) / max(1, len(structural_signals))
    utility = 100.0 * clip_prob((mean_signal + 1.0) / 2.0)  # [-1,1] -> [0,100]
    return round(utility, 6), summarize_signal_reasons(structural_signals)


def extract_repo(commit_url: str) -> str:
    """
    从commit URL提取仓库名

    从GitHub commit URL中提取owner/repo部分：
    https://github.com/facebook/react/commit/abc123 -> facebook/react

    参数:
        commit_url: GitHub commit URL

    返回:
        str: 仓库名（如"facebook/react"），无法提取时返回空字符串
    """
    match = re.search(r"github\.com/([^/]+/[^/]+)/commit/", commit_url)
    return match.group(1) if match else ""


def mine_rows(
    rows: list[dict],
    min_score: int,
    min_atomic_prior: float,
    tau_a: float,
    tau_b: float,
    calibration: dict | None = None,
) -> list[dict]:
    """
    挖掘候选行

    解析每行，提取消息和diff特征，计算原子性先验和Tier分类。

    参数:
        rows: 输入行列表
        min_score: 最小分数阈值
        min_atomic_prior: 最小原子性先验
        tau_a: Tier A阈值
        tau_b: Tier B阈值
        calibration: 校准参数字典

    返回:
        list[dict]: 候选行列表
    """
    candidates = []
    parsed_rows = []
    for row in rows:
        message_text = (
            row.get("commit_message")
            or row.get("message")
            or row.get("masked_commit_message")
            or ""
        )
        message_features = parse_message(message_text)
        diff_text = row.get("git_diff", "")
        diff_features = parse_diff(diff_text)
        parsed_rows.append(
            {
                "row": row,
                "message_features": message_features,
                "diff_features": diff_features,
                "repo": extract_repo(row.get("commit_url", "")),
                "message_text": message_text,
            }
        )

    calibration_global_stats = (
        (calibration or {}).get("feature_norm_stats", {}).get("global")
        if isinstance((calibration or {}).get("feature_norm_stats"), dict)
        else None
    )
    use_batch_repo_stats = calibration_global_stats is None
    # If calibration artifact contains normalization stats, use them to avoid
    # batch-transductive feature drift across runs.
    repo_stats = compute_repo_feature_stats(parsed_rows) if use_batch_repo_stats else {}
    global_stats = (
        calibration_global_stats
        if calibration_global_stats is not None
        else compute_global_feature_stats(parsed_rows)
    )
    calibration_message_protocol = (calibration or {}).get("message_protocol")
    if isinstance(calibration_message_protocol, dict):
        message_protocol = calibration_message_protocol
    else:
        message_protocol = derive_message_protocol(
            [item["message_features"] for item in parsed_rows]
        )
    calibration_scope_protocol = (calibration or {}).get("scope_protocol")
    if isinstance(calibration_scope_protocol, dict):
        scope_protocol = calibration_scope_protocol
    else:
        scope_protocol = derive_scope_protocol(
            [item["diff_features"] for item in parsed_rows]
        )
    calibration_type_protocol = (calibration or {}).get("type_protocol")
    if isinstance(calibration_type_protocol, dict):
        type_protocol = calibration_type_protocol
    else:
        type_protocol = derive_type_protocol(
            [
                item["row"].get("annotated_type") or item["row"].get("type", "")
                for item in parsed_rows
            ]
        )
    signal_maps = [
        atomic_signal_map(
            message_features=parsed["message_features"],
            candidate_type=parsed["row"].get("annotated_type")
            or parsed["row"].get("type", ""),
            diff_features=parsed["diff_features"],
            message_protocol=message_protocol,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )
        for parsed in parsed_rows
    ]
    calibration_signal_context = (calibration or {}).get("signal_context")
    if isinstance(calibration_signal_context, dict) and isinstance(
        calibration_signal_context.get("weights"), dict
    ):
        signal_context = calibration_signal_context
    else:
        signal_context = derive_atomic_signal_context(signal_maps)

    epistemic_pool: list[float] = []
    probability_pool: list[float] = []
    for parsed in parsed_rows:
        row = parsed["row"]
        message_features = parsed["message_features"]
        diff_features = parsed["diff_features"]
        repo = parsed["repo"]
        candidate_type = row.get("annotated_type") or row.get("type", "")
        prior_info = atomic_prior(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=diff_features,
            calibration=calibration,
            repo_stats=repo_stats.get(repo) if use_batch_repo_stats else None,
            global_stats=global_stats,
            signal_context=signal_context,
            message_protocol=message_protocol,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )
        epistemic_pool.append(float(prior_info.get("epistemic_std", 0.0)))
        probability_pool.append(prior_info["p_atomic"])

    calibration_epistemic_reference = (calibration or {}).get("epistemic_reference")
    if isinstance(calibration_epistemic_reference, dict):
        epistemic_reference = calibration_epistemic_reference
    else:
        epistemic_reference = derive_epistemic_reference(epistemic_pool)
    for parsed in parsed_rows:
        row = parsed["row"]
        message_features = parsed["message_features"]
        diff_features = parsed["diff_features"]
        repo = parsed["repo"]
        candidate_type = row.get("annotated_type") or row.get("type", "")
        parsed["prior_info"] = atomic_prior(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=diff_features,
            calibration=calibration,
            repo_stats=repo_stats.get(repo) if use_batch_repo_stats else None,
            global_stats=global_stats,
            signal_context=signal_context,
            epistemic_reference=epistemic_reference,
            message_protocol=message_protocol,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )

    tau_a, tau_b, tau_source = derive_thresholds(
        probabilities=probability_pool,
        calibration=calibration,
        tau_a=tau_a,
        tau_b=tau_b,
    )
    gate_prior, gate_source = derive_gate_threshold(
        probabilities=probability_pool,
        configured_min_prior=min_atomic_prior,
    )
    score_pool = [
        100.0 * float(parsed["prior_info"]["p_atomic"]) for parsed in parsed_rows
    ]
    # Auto gate defaults to score median; explicit CLI value overrides it.
    score_gate = (
        float(min_score)
        if min_score > 0
        else float(statistics.median(score_pool))
        if score_pool
        else 0.0
    )
    score_gate_source = (
        "fixed_from_args" if min_score > 0 else "distribution_median_score"
    )

    for parsed in parsed_rows:
        row = parsed["row"]
        message_features = parsed["message_features"]
        diff_features = parsed["diff_features"]
        repo = parsed["repo"]
        candidate_type = row.get("annotated_type") or row.get("type", "")
        signals = atomic_signal_map(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=diff_features,
            message_protocol=message_protocol,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )
        reasons = summarize_signal_reasons(signals)
        prior_info = parsed["prior_info"]
        score = 100.0 * float(prior_info["p_atomic"])
        if score < score_gate:
            continue

        p_atomic = prior_info["atomic_prior_calibrated"]
        if p_atomic < gate_prior:
            continue

        utility, utility_reasons = utility_score(
            candidate_type,
            diff_features,
            scope_protocol=scope_protocol,
            type_protocol=type_protocol,
        )
        tier = assign_atomic_tier(p_atomic, tau_a=tau_a, tau_b=tau_b)
        candidate = {
            "score": round(score, 6),
            "utility": utility,
            "atomic_logit": round(prior_info["atomic_logit"], 6),
            "atomic_prior": round(prior_info["atomic_prior"], 6),
            "atomic_prior_calibrated": round(prior_info["atomic_prior_calibrated"], 6),
            "atomic_weight": round(prior_info["omega_atomic"], 6),
            "epistemic_std": round(float(prior_info.get("epistemic_std", 0.0)), 6),
            "x_atom": prior_info["x_atom"],
            "p_raw": round(prior_info["p_raw"], 6),
            "p_atomic": round(prior_info["p_atomic"], 6),
            "omega_atomic": round(prior_info["omega_atomic"], 6),
            "signal_context_source": prior_info.get("signal_context_source", ""),
            "tier": tier,
            "tier_source": tau_source,
            "tau_a": round(tau_a, 6),
            "tau_b": round(tau_b, 6),
            "score_gate": score_gate,
            "score_gate_source": score_gate_source,
            "gate_atomic_prior": round(gate_prior, 6),
            "gate_source": gate_source,
            "repo": repo,
            "sha": row["sha"],
            "commit_url": row.get("commit_url", ""),
            "type": row["type"],
            "annotated_type": row.get("annotated_type", ""),
            "subject": message_features["subject_line"],
            "body_line_count": message_features["body_line_count"],
            "paragraph_count": message_features["paragraph_count"],
            "file_count": diff_features["file_count"],
            "hunk_count": diff_features["hunk_count"],
            "changed_lines": diff_features["changed_lines"],
            "roles": ",".join(diff_features["roles"]),
            "modules": ",".join(sorted(diff_features["module_counts"])),
            "reasons": ",".join(reasons),
            "utility_reasons": ",".join(utility_reasons),
            "message": parsed["message_text"].replace("\r\n", "\n"),
        }
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            -item["atomic_prior_calibrated"],
            -item["score"],
            -item["utility"],
            item["file_count"],
            -item["changed_lines"],
            item["body_line_count"],
            item["subject"],
        )
    )
    return candidates


def load_rows(path: Path) -> list[dict]:
    """
    加载CSV文件

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表
    """
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    写入CSV文件

    参数:
        path: 输出文件路径
        rows: 行字典列表
    """
    fieldnames = [
        "score",
        "utility",
        "x_atom",
        "p_raw",
        "p_atomic",
        "omega_atomic",
        "signal_context_source",
        "atomic_logit",
        "atomic_prior",
        "atomic_prior_calibrated",
        "atomic_weight",
        "epistemic_std",
        "tier",
        "tier_source",
        "tau_a",
        "tau_b",
        "score_gate",
        "score_gate_source",
        "gate_atomic_prior",
        "gate_source",
        "repo",
        "repo_raw",
        "sha",
        "commit_url",
        "type",
        "annotated_type",
        "subject",
        "body_line_count",
        "paragraph_count",
        "file_count",
        "hunk_count",
        "changed_lines",
        "roles",
        "modules",
        "reasons",
        "utility_reasons",
        "message",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    path: Path,
    rows: list[dict],
    all_rows: list[dict],
    mined_count: int,
    min_score: int,
    min_atomic_prior: float,
    tau_a: float,
    tau_b: float,
    input_path: Path,
) -> None:
    """
    写入统计摘要

    参数:
        path: 输出文件路径
        rows: 候选行列表
        all_rows: 全部行列表
        mined_count: 挖掘的候选数量
        min_score: 最小分数阈值
        min_atomic_prior: 最小原子性先验
        tau_a: Tier A阈值
        tau_b: Tier B阈值
        input_path: 输入文件路径
    """
    by_type = Counter(row["type"] for row in rows)
    by_repo = Counter(row["repo"] for row in rows)
    score_counter = Counter(int(round(float(row["score"]))) for row in rows)
    utility_counter = Counter(row["utility"] for row in rows)
    tier_counter = Counter(row["tier"] for row in rows)
    pool_file_buckets = Counter()
    for row in all_rows:
        file_count = int(row["file_count"])
        if file_count == 1:
            pool_file_buckets["1"] += 1
        elif 2 <= file_count <= 4:
            pool_file_buckets["2-4"] += 1
        else:
            pool_file_buckets["5+"] += 1
    pool_roles = Counter(row["roles"] for row in all_rows)
    gate_prior = min_atomic_prior
    gate_source = (
        "fixed_from_args"
        if min_atomic_prior > 0
        else "uncertainty_budget_median_entropy"
    )
    tier_source = "distribution_or_calibration_runtime"
    score_gate = min_score
    score_gate_source = (
        "fixed_from_args" if min_score > 0 else "distribution_median_score"
    )
    effective_tau_a = tau_a
    effective_tau_b = tau_b
    if rows:
        gate_prior = float(rows[0].get("gate_atomic_prior", gate_prior))
        gate_source = str(rows[0].get("gate_source", gate_source))
        tier_source = str(rows[0].get("tier_source", tier_source))
        score_gate = int(rows[0].get("score_gate", score_gate))
        score_gate_source = str(rows[0].get("score_gate_source", score_gate_source))
        effective_tau_a = float(
            rows[0].get(
                "tau_a", effective_tau_a if effective_tau_a is not None else 0.0
            )
        )
        effective_tau_b = float(
            rows[0].get(
                "tau_b", effective_tau_b if effective_tau_b is not None else 0.0
            )
        )

    lines = [
        "# Single-Intent Candidate Mining Summary",
        "",
        f"- Input dataset: `{input_path.as_posix()}`",
        f"- Minimum score gate: `{score_gate}` (`{score_gate_source}`)",
        f"- Minimum atomic prior gate: `{gate_prior}` (`{gate_source}`)",
        f"- Tier thresholds: `tau_a={effective_tau_a}`, `tau_b={effective_tau_b}`",
        f"- Tier derivation source: `{tier_source}`",
        f"- Selected candidates: `{len(rows)}`",
        f"- Passing candidates before top-k cutoff: `{mined_count}`",
        "",
        "## Tier Distribution",
        "",
    ]
    for tier_name, count in sorted(tier_counter.items()):
        lines.append(f"- `{tier_name}`: {count}")

    lines.extend(["", "## Type Distribution", ""])
    for type_name, count in by_type.most_common():
        lines.append(f"- `{type_name}`: {count}")

    lines.extend(["", "## Repo Distribution", ""])
    for repo, count in by_repo.most_common(SUMMARY_TOP_REPO_COUNT):
        lines.append(f"- `{repo}`: {count}")

    lines.extend(["", "## Score Distribution", ""])
    for score, count in sorted(score_counter.items(), reverse=True):
        lines.append(f"- `{score}`: {count}")

    lines.extend(["", "## Utility Distribution", ""])
    for utility, count in sorted(utility_counter.items(), reverse=True):
        lines.append(f"- `{utility}`: {count}")

    lines.extend(["", "## Passing Pool Snapshot", ""])
    for bucket, count in pool_file_buckets.items():
        lines.append(f"- files `{bucket}`: {count}")
    for role_name, count in pool_roles.most_common(10):
        lines.append(f"- roles `{role_name}`: {count}")

    lines.extend(["", "## Top Examples", ""])
    for row in rows[:SUMMARY_TOP_EXAMPLE_COUNT]:
        lines.append(
            f"- prior `{row['atomic_prior_calibrated']}` | tier `{row['tier']}` | score `{row['score']}` utility `{row['utility']}` | `{row['type']}` | `{row['repo']}` | {row['subject']} | files `{row['file_count']}` | lines `{row['changed_lines']}`"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """
    主函数：执行单意图候选挖掘

    流程：
    1. 加载输入CSV
    2. 解析每行，计算原子性先验和Tier分类
    3. 写入候选CSV和摘要
    """
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration = load_calibration(args.calibration_json)
    tau_a, tau_b = resolve_thresholds(
        calibration=calibration, tau_a=args.tau_a, tau_b=args.tau_b
    )

    rows = load_rows(input_path)
    all_candidates = mine_rows(
        rows,
        min_score=args.min_score,
        min_atomic_prior=args.min_atomic_prior,
        tau_a=tau_a,
        tau_b=tau_b,
        calibration=calibration,
    )
    selected = all_candidates[: args.target_count]

    write_csv(output_dir / "all_passing_candidates.csv", all_candidates)
    write_csv(output_dir / "single_intent_candidates.csv", selected)
    write_summary(
        output_dir / "summary.md",
        selected,
        all_candidates,
        mined_count=len(all_candidates),
        min_score=args.min_score,
        min_atomic_prior=args.min_atomic_prior,
        tau_a=tau_a,
        tau_b=tau_b,
        input_path=input_path,
    )
    print(f"selected={len(selected)}")
    print(f"passing_before_cutoff={len(all_candidates)}")
    print((output_dir / "single_intent_candidates.csv").as_posix())


if __name__ == "__main__":
    main()
