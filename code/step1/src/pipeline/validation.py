"""
小规模Step1验证脚本

本脚本用于生成审计样本文档，用于人工标注以验证Tier分类质量。

功能：
1. 读取已解析的候选列表
2. 基于校准阈值分配Tier (A/B/C)
3. 生成多样化的采样用于审查
4. 生成Tier-A审计模板用于人工标注
5. 可选：检查审计完成度

输出：
- tier_a_candidates.csv: Tier A候选
- tier_b_candidates.csv: Tier B候选
- tier_c_candidates.csv: Tier C候选
- tier_a_review_sample.csv: Tier A审查样本
- tier_b_review_sample.csv: Tier B审查样本
- tier_a_audit_sample.csv / tier_b_audit_sample.csv: 审计样本模板
- tier_a_audit_protocol.md / tier_b_audit_protocol.md: 审计协议说明
- tier_a_review_packet.md: 审查数据包
- summary.md: 统计摘要
"""

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

from src.pipeline import atomic_mining as miner
import src.data_splitting.annotated_split_protocol as annotated_split_protocol
from src.labeling import label_protocol


TIER_A_TYPES = {"fix", "feat", "refactor", "perf", "test"}  # Tier A类型集合
TIER_A_ROLES = {
    "source",
    "source,test",
    "build,source",
    "config,source",
    "docs,source",
}  # Tier A角色集合
DEFAULT_SAMPLE_PER_TIER = 12  # 默认每层采样数
DEFAULT_RANDOM_SEED = 31  # 默认随机种子
DEFAULT_AUDIT_SIZE = 400  # 默认审计大小
DEFAULT_AUDIT_SAMPLING = "random"  # 默认审计采样方式
DEFAULT_TIER_B_AUDIT_SIZE = 0  # Tier-B辅助审计样本大小（0表示跟随主审计样本大小）
AUDIT_SIZE_MIN = 300  # 审计大小最小值
AUDIT_SIZE_MAX = 500  # 审计大小最大值
TIER_B_SEED_OFFSET = 1  # Tier B种子偏移
TIER_AUDIT_SEED_OFFSET = 97  # Tier A审计种子偏移
DEFAULT_DIFF_EXCERPT_LINES = 36  # 默认diff摘录行数
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制
VALID_AUDIT_LABELS = {"0", "1"}  # 有效的审计标签
VALIDATE_BAND_BY_TIER = {"A": "high", "B": "mid", "C": "low"}
VALIDATE_BAND_LABELS = {
    "high": "Validate High Band",
    "mid": "Validate Mid Band",
    "low": "Validate Low Band",
}

# 传统确定性fallback阈值（仅用于缺少概率先验的旧数据）
LEGACY_TIER_A_SCORE_MIN = 12
LEGACY_TIER_A_UTILITY_MIN = 6
LEGACY_TIER_A_FILE_MIN = 1
LEGACY_TIER_A_FILE_MAX = 4
LEGACY_TIER_A_LINES_MIN = 5
LEGACY_TIER_A_LINES_MAX = 160
LEGACY_TIER_B_SCORE_MIN = 10
LEGACY_TIER_B_UTILITY_MIN = 4
LEGACY_TIER_B_FILE_MIN = 1
LEGACY_TIER_B_FILE_MAX = 6
LEGACY_TIER_B_LINES_MAX = 220


def validate_band_from_tier(tier: str) -> str:
    """将 legacy tier=A/B/C 映射为规范 validate_band=high/mid/low。"""
    return VALIDATE_BAND_BY_TIER.get(str(tier).strip().upper(), "")


def validate_band_label(validate_band: str) -> str:
    """返回 validate band 的展示名称。"""
    return VALIDATE_BAND_LABELS.get(
        str(validate_band).strip().lower(), "Validate Unknown Band"
    )


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates",
        default="outputs/enriched/resolved_candidates.csv",
    )
    parser.add_argument(
        "--pilot",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    parser.add_argument("--output-dir", default="outputs/validation")
    parser.add_argument("--sample-per-tier", type=int, default=DEFAULT_SAMPLE_PER_TIER)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--tau-a", type=float, default=miner.DEFAULT_TAU_A)
    parser.add_argument("--tau-b", type=float, default=miner.DEFAULT_TAU_B)
    parser.add_argument(
        "--primary-calibration-json",
        default="",
        help="Full-diff primary calibration artifact used for the default validate path.",
    )
    parser.add_argument(
        "--proxy-calibration-json",
        default="",
        help="Message-only proxy calibration artifact used only for proxy diagnostic validate runs.",
    )
    parser.add_argument(
        "--calibration-json",
        default="",
        help="Deprecated alias. Interpreted according to --threshold-mode.",
    )
    parser.add_argument("--audit-size", type=int, default=DEFAULT_AUDIT_SIZE)
    parser.add_argument(
        "--tier-b-audit-size",
        type=int,
        default=DEFAULT_TIER_B_AUDIT_SIZE,
        help="辅助 Tier-B 审计样本大小；0 表示跟随主审计样本大小，并自动截断到实际可用样本数。",
    )
    parser.add_argument(
        "--audit-tier",
        choices=["A", "B"],
        default="A",
        help="选择主审计对象；当前默认使用 Tier-A 以独立验证高置信 precision claim。",
    )
    parser.add_argument(
        "--audit-sampling",
        choices=["random", "diverse"],
        default=DEFAULT_AUDIT_SAMPLING,
        help="审计采样策略：random为无偏推荐用于噪声边界估计",
    )
    parser.add_argument(
        "--audit-labeled-csv",
        default="",
        help="Deprecated alias of --tier-a-audit-labeled-csv.",
    )
    parser.add_argument("--annotated-split-plan-json", default="")
    parser.add_argument(
        "--tier-a-audit-labeled-csv",
        default="",
        help="可选的 Tier-A 审计标注CSV路径，用于完成度检查与 precision 汇总。",
    )
    parser.add_argument(
        "--tier-b-audit-labeled-csv",
        default="",
        help="可选的 Tier-B 审计标注CSV路径，用于辅助 precision 汇总。",
    )
    parser.add_argument(
        "--require-audit-completion",
        action="store_true",
        help="当标注审计CSV缺失/不完整/无效时失败",
    )
    parser.add_argument(
        "--diff-required",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用时，仅验证具有解析diff特征的行",
    )
    parser.add_argument(
        "--threshold-mode",
        choices=["message_only", "full_diff"],
        default="full_diff",
        help="决定分Tier时使用 message-only 还是 full-diff 概率链。",
    )
    parser.add_argument(
        "--export-audit-samples",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否导出 review/audit sample 及对应 protocol 文档。",
    )
    return parser.parse_args()


def load_csv(path: Path) -> list[dict]:
    """
    加载CSV文件

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表（每行是一个字典）
    """
    # 设置CSV字段大小限制，避免大字段导致解析错误
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并使用DictReader解析为字典列表
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _legacy_assign_tier(row: dict) -> str:
    """
    传统方式分配Tier（基于固定阈值）

    仅用于缺少原子性先验列的旧流水线输出。
    当没有校准文件（无可信概率阈值）时使用。

    规则：
    - Tier A: score≥12 AND utility≥6 AND 类型是fix/feat/refactor/perf/test
              AND 角色在白名单 AND 1≤文件数≤4 AND 5≤变更行≤160
    - Tier B: score≥10 AND utility≥4 AND 1≤文件数≤6 AND 变更行≤220
    - Tier C: 其他

    参数:
        row: CSV行字典

    返回:
        str: Tier等级 ("A", "B", 或 "C")
    """
    # 提取各项指标
    score = int(row["score"])
    utility = int(row["utility"])
    file_count = int(row["file_count"])
    changed_lines = int(row["changed_lines"])
    role = row["roles"]
    commit_type = row["type"]

    # Tier A检查：需要同时满足多个条件才为高置信度单意图
    if (
        score >= LEGACY_TIER_A_SCORE_MIN  # score >= 12
        and utility >= LEGACY_TIER_A_UTILITY_MIN  # utility >= 6
        and commit_type in TIER_A_TYPES  # 类型是fix/feat/refactor/perf/test
        and role in TIER_A_ROLES  # 角色在白名单中
        and LEGACY_TIER_A_FILE_MIN
        <= file_count
        <= LEGACY_TIER_A_FILE_MAX  # 1 <= file_count <= 4
        and LEGACY_TIER_A_LINES_MIN
        <= changed_lines
        <= LEGACY_TIER_A_LINES_MAX  # 5 <= lines <= 160
    ):
        return "A"

    # Tier B检查：条件比A更宽松
    if (
        score >= LEGACY_TIER_B_SCORE_MIN  # score >= 10
        and utility >= LEGACY_TIER_B_UTILITY_MIN  # utility >= 4
        and LEGACY_TIER_B_FILE_MIN
        <= file_count
        <= LEGACY_TIER_B_FILE_MAX  # 1 <= file_count <= 6
        and changed_lines <= LEGACY_TIER_B_LINES_MAX  # lines <= 220
    ):
        return "B"

    # 不满足A或B条件的为Tier C
    return "C"


def assign_tier(
    row: dict, tau_a: float, tau_b: float, prefer_message_only: bool = False
) -> str:
    """
    分配Tier等级

    优先使用概率分层（基于原子性先验概率）：
    - Tier A: probability > tau_a（高置信度单意图）
    - Tier B: tau_b < probability <= tau_a（中等置信度）
    - Tier C: probability <= tau_b（低置信度）

    仅对缺少原子性先验列的旧行保留传统确定性fallback。

    参数:
        row: CSV行字典
        tau_a: Tier A阈值（必须大于tau_b）
        tau_b: Tier B阈值

    返回:
        str: Tier等级 ("A", "B", 或 "C")
    """
    # 尝试从行中获取原子性先验值
    prior_value = row_atomic_probability(row, prefer_message_only=prefer_message_only)
    if prior_value is not None:
        try:
            return miner.assign_atomic_tier(prior_value, tau_a=tau_a, tau_b=tau_b)
        except ValueError:
            # 概率分层失败时使用fallback
            return _legacy_assign_tier(row)
    # 无先验值时使用fallback
    return _legacy_assign_tier(row)


def row_atomic_probability(
    row: dict, prefer_message_only: bool = False
) -> float | None:
    """
    提取行内原子性概率，按场景优先选择message-only或full-diff字段。
    """
    if prefer_message_only:
        keys = [
            "atomic_prior_message_only_calibrated",
            "atomic_prior_message_only",
            "p_atomic_message_only",
            "p_raw_message_only",
        ]
    else:
        keys = [
            "atomic_prior_calibrated",
            "atomic_prior",
            "p_atomic",
            "p_raw",
        ]
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def is_message_only_calibration_artifact(calibration: dict | None) -> bool:
    """判断校准工件是否为 message-only 路径。"""
    return miner.is_message_only_calibration(calibration)


def resolve_validate_thresholds(
    *,
    candidates: list[dict],
    calibration: dict | None,
    tau_a: float | None,
    tau_b: float | None,
    threshold_mode: str,
) -> tuple[float, float, str]:
    """
    解析validate阶段阈值来源，避免message-only与full-diff尺度混用。
    """
    prefer_message_only = str(threshold_mode) == "message_only"
    probabilities: list[float] = []
    for row in candidates:
        probability = row_atomic_probability(
            row, prefer_message_only=prefer_message_only
        )
        if probability is not None:
            probabilities.append(probability)
    if str(threshold_mode) == "message_only":
        threshold_calibration = (
            miner.require_calibration_mode(
                calibration,
                expected_mode="message_only",
                context="validate message-only proxy diagnostic path",
            )
            if calibration is not None
            else None
        )
    else:
        threshold_calibration = (
            miner.require_calibration_mode(
                calibration,
                expected_mode="full_diff",
                context="validate full-diff primary path",
            )
            if calibration is not None
            else None
        )
    tau_a_value, tau_b_value, source = miner.derive_thresholds(
        probabilities=probabilities,
        calibration=threshold_calibration,
        tau_a=tau_a,
        tau_b=tau_b,
    )
    return float(tau_a_value), float(tau_b_value), f"{threshold_mode}:{source}"


def has_diff_features(row: dict) -> bool:
    """
    检查行是否具有diff特征

    用于diff-required模式下的过滤，确保只处理有完整diff的行。

    参数:
        row: CSV行字典

    返回:
        bool: 是否具有所有必需的diff特征
    """
    required_keys = ["score", "file_count", "hunk_count", "changed_lines"]
    for key in required_keys:
        value = row.get(key)
        if value in {None, ""}:
            return False
    return True


def sample_diverse(rows: list[dict], sample_size: int, seed: int) -> list[dict]:
    """
    多样性采样

    三阶段cap受限采样，确保采样覆盖多样性：
    1. 阶段1：repo_cap=1, type_cap=3（最多1个repo，3个相同type）
    2. 阶段2：repo_cap=2, type_cap=4（如样本不足，放宽限制）
    3. 阶段3：填充剩余（如仍不足，随机补充）

    最后按原子性先验、score、utility降序排列。

    参数:
        rows: 候选行列表
        sample_size: 采样数量
        seed: 随机种子

    返回:
        list[dict]: 多样化采样的行列表
    """
    rng = random.Random(seed)
    shuffled = list(rows)
    rng.shuffle(shuffled)

    picked: list[dict] = []
    repo_counter: Counter = Counter()
    type_counter: Counter = Counter()

    def repo_name(row: dict) -> str:
        return row.get("repo") or row.get("resolved_repo") or ""

    def prior_value(row: dict) -> float:
        raw = row.get("atomic_prior_calibrated")
        if raw in {None, ""}:
            raw = row.get("atomic_prior")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def int_value(row: dict, key: str) -> int:
        raw = row.get(key)
        try:
            if raw in {None, ""}:
                return 0
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def try_pick(repo_cap: int, type_cap: int) -> None:
        # 两轮采样：首先提高多样性，然后填充剩余配额
        for row in shuffled:
            if row in picked:
                continue
            repo = repo_name(row)
            if repo_counter[repo] >= repo_cap:
                continue
            if type_counter[row["type"]] >= type_cap:
                continue
            picked.append(row)
            repo_counter[repo] += 1
            type_counter[row["type"]] += 1
            if len(picked) >= sample_size:
                return

    # 阶段1：严格限制
    try_pick(repo_cap=1, type_cap=3)
    # 阶段2：放宽限制
    if len(picked) < sample_size:
        try_pick(repo_cap=2, type_cap=4)
    # 阶段3：填充剩余
    if len(picked) < sample_size:
        for row in shuffled:
            if row in picked:
                continue
            picked.append(row)
            if len(picked) >= sample_size:
                break

    # 排序：先按先验，再按score，再按utility
    picked.sort(
        key=lambda item: (
            -prior_value(item),
            -int_value(item, "score"),
            -int_value(item, "utility"),
            item.get("repo") or item.get("resolved_repo") or "",
            item["subject"],
        )
    )
    return picked


def sample_random(rows: list[dict], sample_size: int, seed: int) -> list[dict]:
    """
    随机采样

    纯随机抽样，用于无偏噪声边界估计。

    参数:
        rows: 候选行列表
        sample_size: 采样数量
        seed: 随机种子

    返回:
        list[dict]: 随机采样的行列表
    """
    rng = random.Random(seed)
    candidates = list(rows)
    if not candidates:
        return []
    rng.shuffle(candidates)
    return candidates[:sample_size]


def compact_diff(diff: str, max_lines: int = DEFAULT_DIFF_EXCERPT_LINES) -> str:
    """
    压缩diff文本

    截取diff的前N行，并在末尾添加省略标记。

    参数:
        diff: 原始diff文本
        max_lines: 最大保留行数

    返回:
        str: 压缩后的diff文本
    """
    lines = diff.splitlines()
    selected = lines[:max_lines]
    text = "\n".join(selected)
    if len(lines) > max_lines:
        text += "\n... [truncated]"
    return text


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1.0 + z * z / total
    center = (phat + z * z / (2.0 * total)) / denom
    margin = (
        z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * total)) / total) / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def independent_split_stats(candidates: list[dict], pilot_rows: list[dict]) -> dict:
    candidate_shas = {
        str(row.get("sha", "")).strip()
        for row in candidates
        if str(row.get("sha", "")).strip()
    }
    pilot_shas = {
        str(row.get("sha", "")).strip()
        for row in pilot_rows
        if str(row.get("sha", "")).strip()
    }
    overlap = sorted(candidate_shas & pilot_shas)
    return {
        "candidate_rows": len(candidate_shas),
        "pilot_rows": len(pilot_shas),
        "overlap_sha_count": len(overlap),
        "overlap_sha_examples": overlap[:10],
        "is_disjoint": len(overlap) == 0,
    }


def build_audit_samples(
    *,
    tier_a_rows: list[dict],
    tier_b_rows: list[dict],
    audit_size: int,
    audit_sampling: str,
    seed: int,
    primary_audit_tier: str,
    tier_b_audit_size: int = DEFAULT_TIER_B_AUDIT_SIZE,
) -> dict:
    primary_upper = str(primary_audit_tier).upper()
    primary_rows = tier_a_rows if primary_upper == "A" else tier_b_rows
    secondary_rows = tier_b_rows if primary_upper == "A" else tier_a_rows
    sampler = sample_random if audit_sampling == "random" else sample_diverse
    effective_tier_b_audit_size = (
        int(audit_size) if int(tier_b_audit_size) <= 0 else int(tier_b_audit_size)
    )
    primary_sample = sampler(
        primary_rows,
        sample_size=min(int(audit_size), len(primary_rows)),
        seed=seed + TIER_AUDIT_SEED_OFFSET,
    )
    secondary_sample = sampler(
        secondary_rows,
        sample_size=min(effective_tier_b_audit_size, len(secondary_rows)),
        seed=seed + TIER_AUDIT_SEED_OFFSET + TIER_B_SEED_OFFSET,
    )
    return {
        "primary_audit_tier": primary_upper,
        "primary_audit_sample": primary_sample,
        "secondary_audit_sample": secondary_sample,
        "tier_a_audit_sample": primary_sample
        if primary_upper == "A"
        else secondary_sample,
        "tier_b_audit_sample": secondary_sample
        if primary_upper == "A"
        else primary_sample,
    }


def misclassification_pattern_tags(row: dict) -> list[str]:
    tags: list[str] = []
    note = str(row.get("audit_notes", "")).strip().lower()
    if note:
        tags.extend(
            token.strip()
            for token in note.replace(";", ",").split(",")
            if token.strip()
        )
    subject = (
        str(row.get("subject") or row.get("commit_message") or "")
        .splitlines()[0]
        .lower()
    )
    message = str(row.get("commit_message", "")).lower()
    if any(
        line.lstrip().startswith(("- ", "* "))
        for line in str(row.get("commit_message", "")).splitlines()
    ):
        tags.append("markdown_body_bullet")
    if " and " in subject:
        tags.append("conjoined_actions")
    if ";" in subject:
        tags.append("semicolon_subject")
    if len(subject) >= 72:
        tags.append("long_subject")
    if " also " in message or " additionally " in message or " meanwhile " in message:
        tags.append("connective_multi_marker")
    if not tags:
        tags.append("other")
    return sorted(set(tags))


def summarize_misclassification_patterns(rows: list[dict]) -> list[dict]:
    negatives = [
        row
        for row in rows
        if label_protocol.resolve_label_record(row, label_col="audit_is_single_intent")[
            "selected_label"
        ]
        == "0"
    ]
    counts: Counter = Counter()
    for row in negatives:
        for tag in misclassification_pattern_tags(row):
            counts[tag] += 1
    total_negatives = len(negatives)
    return [
        {
            "pattern": pattern,
            "count": count,
            "negative_rows": total_negatives,
            "share_of_negative_rows": f"{(count / total_negatives) if total_negatives else 0.0:.6f}",
        }
        for pattern, count in counts.most_common()
    ]


def build_precision_metrics(labeled_rows: list[dict], pattern_csv_path: str) -> dict:
    valid_rows = [
        (
            row,
            label_protocol.resolve_label_record(
                row, label_col="audit_is_single_intent"
            ),
        )
        for row in labeled_rows
        if label_protocol.resolve_label_record(row, label_col="audit_is_single_intent")[
            "selected_label"
        ]
        in VALID_AUDIT_LABELS
    ]
    sample_count = len(valid_rows)
    positive_count = sum(
        1
        for _, resolved in valid_rows
        if str(resolved["selected_label"]).strip() == "1"
    )
    precision = (positive_count / sample_count) if sample_count else None
    wilson_low, wilson_high = wilson_interval(positive_count, sample_count)
    return {
        "sample_count": sample_count,
        "positive_count": positive_count,
        "precision": precision,
        "wilson95_low": wilson_low,
        "wilson95_high": wilson_high,
        "misclassification_pattern_summary_csv": pattern_csv_path,
        "label_usage_summary": label_protocol.build_label_usage_summary(
            labeled_rows, label_col="audit_is_single_intent"
        ),
    }


def build_precision_report(
    *,
    tier_a_labeled_rows: list[dict],
    tier_b_labeled_rows: list[dict],
    independent_split_stats: dict,
    tier_a_pattern_csv: str,
    tier_b_pattern_csv: str,
) -> dict:
    return {
        "independent_evaluation_split": independent_split_stats,
        "tier_a": build_precision_metrics(
            tier_a_labeled_rows, pattern_csv_path=tier_a_pattern_csv
        ),
        "tier_b": build_precision_metrics(
            tier_b_labeled_rows, pattern_csv_path=tier_b_pattern_csv
        ),
    }


def write_precision_report(path: Path, report: dict) -> None:
    lines = [
        "# Audit Precision Report",
        "",
        f"- Independent evaluation split disjoint: `{report['independent_evaluation_split']['is_disjoint']}`",
        f"- Overlap SHA count: `{report['independent_evaluation_split']['overlap_sha_count']}`",
        "",
        "## Tier-A Precision",
        "",
        f"- Sample count: `{report['tier_a']['sample_count']}`",
        f"- Positive count: `{report['tier_a']['positive_count']}`",
        f"- Precision: `{report['tier_a']['precision']}`",
        f"- Wilson 95% CI: `[{report['tier_a']['wilson95_low']:.6f}, {report['tier_a']['wilson95_high']:.6f}]`",
        f"- Misclassification patterns: `{report['tier_a']['misclassification_pattern_summary_csv']}`",
        "",
        "## Tier-B Precision",
        "",
        f"- Sample count: `{report['tier_b']['sample_count']}`",
        f"- Positive count: `{report['tier_b']['positive_count']}`",
        f"- Precision: `{report['tier_b']['precision']}`",
        f"- Wilson 95% CI: `[{report['tier_b']['wilson95_low']:.6f}, {report['tier_b']['wilson95_high']:.6f}]`",
        f"- Misclassification patterns: `{report['tier_b']['misclassification_pattern_summary_csv']}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def attach_pilot_fields(rows: list[dict], pilot_rows: list[dict]) -> list[dict]:
    """
    附加pilot数据集字段

    将pilot数据集中的git_diff附加到候选行。

    参数:
        rows: 候选行列表
        pilot_rows: pilot数据行列表

    返回:
        list[dict]: 附加了pilot字段的行列表
    """
    # 构建SHA到pilot行的映射
    by_sha = {row["sha"]: row for row in pilot_rows}
    enriched = []
    for row in rows:
        copied = dict(row)
        pilot = by_sha.get(row["sha"], {})
        # 仅在候选行缺失时才从pilot补齐，避免覆写enrich阶段已解析的字段
        copied["git_diff"] = copied.get("git_diff") or pilot.get("git_diff", "")
        copied["masked_commit_message"] = copied.get(
            "masked_commit_message"
        ) or pilot.get("masked_commit_message", "")
        copied["annotated_type"] = copied.get("annotated_type") or pilot.get(
            "annotated_type", ""
        )
        enriched.append(copied)
    return enriched


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    写入CSV文件

    参数:
        path: 输出文件路径
        rows: 行字典列表
    """
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(
    tier_a: list[dict],
    tier_b: list[dict],
    tier_c: list[dict],
    path: Path,
    args: argparse.Namespace,
    precision_report: dict | None = None,
) -> None:
    """
    生成统计摘要

    参数:
        tier_a: Tier A候选列表
        tier_b: Tier B候选列表
        tier_c: Tier C候选列表
        path: 输出文件路径
        args: 命令行参数
    """
    audit_target = max(AUDIT_SIZE_MIN, min(AUDIT_SIZE_MAX, int(args.audit_size)))
    audit_band = validate_band_from_tier(str(args.audit_tier))
    audit_band_label = (
        validate_band_label(audit_band)
        if audit_band
        else f"Legacy Tier-{args.audit_tier}"
    )
    threshold_source = str(getattr(args, "threshold_source", "unknown"))
    threshold_explainer = "- These validate bands reuse the calibration artifact's precision-constrained thresholds."
    if "fixed_from_args" in threshold_source:
        threshold_explainer = "- These validate bands use explicit threshold overrides from CLI arguments."
    elif "calibration_precision" not in threshold_source:
        threshold_explainer = "- These validate bands are dynamically re-derived from the current candidate pool."
    lines = [
        "# Step1 Small-Scale Validation Summary",
        "",
        f"- Candidate pool: `{args.candidates}`",
        f"- Pilot source: `{args.pilot}`",
        f"- Primary calibration file: `{getattr(args, 'primary_calibration_json', '') or 'none'}`",
        f"- Proxy calibration file: `{getattr(args, 'proxy_calibration_json', '') or 'none'}`",
        f"- Diff-required validation: `{args.diff_required}`",
        f"- Validate band thresholds: `tau_high={args.tau_a}`, `tau_mid={args.tau_b}`",
        f"- Validate band threshold source: `{threshold_source}`",
        "- Canonical validate bands: `high / mid / low`; legacy `tier=A/B/C` filenames are retained for compatibility.",
        threshold_explainer,
        f"- Audit target band: `{audit_band_label}` (legacy `Tier-{args.audit_tier}`)",
        f"- Validate High Band count (legacy `Tier-A`): `{len(tier_a)}`",
        f"- Validate Mid Band count (legacy `Tier-B`): `{len(tier_b)}`",
        f"- Validate Low Band count (legacy `Tier-C`): `{len(tier_c)}`",
        f"- {audit_band_label} audit target size (clamped to [300, 500]): `{audit_target}`",
        "",
        "## Independent Audit Precision",
        "",
    ]
    if precision_report is None:
        lines.extend(
            [
                "- Tier-A precision: `pending_labeled_audit`",
                "- Tier-B precision: `pending_labeled_audit`",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- Tier-A precision: `{precision_report['tier_a']['precision']}`",
                f"- Tier-A sample count: `{precision_report['tier_a']['sample_count']}`",
                f"- Tier-B precision: `{precision_report['tier_b']['precision']}`",
                f"- Tier-B sample count: `{precision_report['tier_b']['sample_count']}`",
                "",
            ]
        )
    lines.extend(["## Validate High Band Type Distribution", ""])
    for key, value in Counter(row["type"] for row in tier_a).most_common():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Validate Mid Band Type Distribution", ""])
    for key, value in Counter(row["type"] for row in tier_b).most_common():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Validate High Band Role Distribution", ""])
    for key, value in Counter(row.get("roles", "") for row in tier_a).most_common():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Validate Mid Band Role Distribution", ""])
    for key, value in Counter(row.get("roles", "") for row in tier_b).most_common():
        lines.append(f"- `{key}`: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_review_packet(path: Path, tier_name: str, rows: list[dict]) -> None:
    """
    写入审查数据包

    参数:
        path: 输出文件路径
        tier_name: Tier名称（A或B）
        rows: 候选行列表
    """
    lines = [f"# Tier-{tier_name} Review Packet", ""]
    for idx, row in enumerate(rows, start=1):
        repo = row.get("repo") or row.get("resolved_repo") or ""
        atomic_prior = (
            row.get("atomic_prior_calibrated") or row.get("atomic_prior") or ""
        )
        score = row.get("score", "")
        utility = row.get("utility", "")
        lines.extend(
            [
                f"## Sample {idx}",
                "",
                f"- Repo: `{repo}`",
                f"- Raw Repo: `{row.get('repo_raw', repo)}`",
                f"- SHA: `{row['sha']}`",
                f"- Type: `{row['type']}`",
                f"- Atomic Prior: `{atomic_prior}`",
                f"- Score: `{score}`",
                f"- Utility: `{utility}`",
                f"- Files: `{row.get('file_count', '')}`",
                f"- Hunks: `{row.get('hunk_count', '')}`",
                f"- Changed Lines: `{row.get('changed_lines', '')}`",
                f"- Roles: `{row.get('roles', '')}`",
                f"- Modules: `{row.get('modules', '')}`",
                f"- Reasons: `{row.get('reasons', row.get('full_reasons', ''))}`",
                f"- Utility Reasons: `{row.get('utility_reasons', '')}`",
                f"- Commit URL: {row.get('commit_url', '')}",
                "",
                "### Message",
                "",
                "```text",
                row.get("message", row.get("commit_message", "")),
                "```",
                "",
                "### Diff Excerpt",
                "",
                "```diff",
                compact_diff(row.get("git_diff", "")),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_audit_template_rows(rows: list[dict]) -> list[dict]:
    """
    构建审计模板行

    为每行添加审计字段：is_single_intent, confidence, reviewer, notes

    参数:
        rows: 候选行列表

    返回:
        list[dict]: 添加了审计字段的行列表
    """
    template_rows = []
    for row in rows:
        copied = dict(row)
        copied["audit_is_single_intent"] = ""
        copied["audit_confidence"] = ""
        copied["audit_reviewer"] = ""
        copied["audit_notes"] = ""
        template_rows.append(copied)
    return template_rows


def write_audit_protocol(
    path: Path, audit_rows: list[dict], args: argparse.Namespace
) -> None:
    """
    写入审计协议说明

    参数:
        path: 输出文件路径
        audit_rows: 审计行列表
        args: 命令行参数
    """
    sampling_descriptor = (
        "random" if args.audit_sampling == "random" else args.audit_sampling
    )
    lines = [
        f"# Tier-{args.audit_tier} Audit Template (300-500)",
        "",
        "## Goal",
        "",
        "Estimate Tier-A precision as the primary high-confidence claim, with Tier-B precision as auxiliary evidence.",
        "",
        "## Sampling Setup",
        "",
        f"- Candidate source: `{args.candidates}`",
        f"- Primary calibration file: `{getattr(args, 'primary_calibration_json', '') or 'none'}`",
        f"- Proxy calibration file: `{getattr(args, 'proxy_calibration_json', '') or 'none'}`",
        f"- Tier thresholds in this run: `tau_a={args.tau_a}`, `tau_b={args.tau_b}`",
        f"- Audit sampling policy: `{args.audit_sampling}`",
        f"- Audit sampling seed: `{args.seed + TIER_AUDIT_SEED_OFFSET}`",
        f"- Audit sample size: `{len(audit_rows)}`",
        "",
        "## How To Label",
        "",
        "- Fill `audit_is_single_intent` with `1` (single-intent) or `0` (not single-intent).",
        "- Fill `audit_confidence` with a reviewer confidence score in `[0,1]`.",
        "- Optional: fill `audit_reviewer` and `audit_notes`.",
        "",
        "## Reported Metric",
        "",
        "- `tier_a_precision = mean(tier_a_audit_is_single_intent)`",
        "- `tier_b_precision = mean(tier_b_audit_is_single_intent)`",
        "",
        "## Suggested Report Snippet",
        "",
        f"- We manually audited a {sampling_descriptor} Tier-A sample and report its precision as the primary high-confidence claim; Tier-B is reported as auxiliary evidence for the broader candidate layer.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_audit_completion(rows: list[dict]) -> dict:
    """
    评估审计完成度

    检查审计标注是否完整（标签和置信度是否有效）

    参数:
        rows: 审计行列表

    返回:
        dict: 包含完成度统计的字典
    """
    total = len(rows)
    valid_label_count = 0
    valid_confidence_count = 0
    for row in rows:
        label = label_protocol.resolve_label_record(
            row, label_col="audit_is_single_intent"
        )["selected_label"]
        if label in VALID_AUDIT_LABELS:
            valid_label_count += 1
        confidence_raw = str(row.get("audit_confidence", "")).strip()
        try:
            confidence = float(confidence_raw)
            if 0.0 <= confidence <= 1.0:
                valid_confidence_count += 1
        except ValueError:
            continue
    return {
        "total": total,
        "valid_label_count": valid_label_count,
        "valid_confidence_count": valid_confidence_count,
        "label_completion_ratio": (valid_label_count / total) if total else 0.0,
        "confidence_completion_ratio": (valid_confidence_count / total)
        if total
        else 0.0,
        "is_complete": total > 0
        and valid_label_count == total
        and valid_confidence_count == total,
    }


def evaluate_audit_sample_alignment(
    expected_rows: list[dict], labeled_rows: list[dict]
) -> dict:
    """
    检查审计模板与标注文件的 SHA 是否逐行一致。
    """
    expected_shas = [str(row.get("sha", "")).strip() for row in expected_rows]
    labeled_shas = [str(row.get("sha", "")).strip() for row in labeled_rows]
    prefix = 0
    for expected_sha, labeled_sha in zip(expected_shas, labeled_shas):
        if expected_sha != labeled_sha:
            break
        prefix += 1
    return {
        "expected_rows": len(expected_shas),
        "labeled_rows": len(labeled_shas),
        "matching_sha_prefix": prefix,
        "same_length": len(expected_shas) == len(labeled_shas),
        "same_sha_order": expected_shas == labeled_shas,
        "same_sha_set": set(expected_shas) == set(labeled_shas),
        "is_aligned": expected_shas == labeled_shas,
    }


def write_audit_completion_report(path: Path, audit_path: Path, stats: dict) -> None:
    """
    写入审计完成度报告

    参数:
        path: 输出文件路径
        audit_path: 审计CSV文件路径
        stats: 审计完成度统计
    """
    lines = [
        "# Audit Completion Check",
        "",
        f"- Audit csv: `{audit_path.as_posix()}`",
        f"- Total rows: `{stats['total']}`",
        f"- Valid labels (`0/1`): `{stats['valid_label_count']}`",
        f"- Valid confidence (`[0,1]`): `{stats['valid_confidence_count']}`",
        f"- Label completion ratio: `{stats['label_completion_ratio']:.4f}`",
        f"- Confidence completion ratio: `{stats['confidence_completion_ratio']:.4f}`",
        f"- Same length as generated audit sample: `{stats.get('same_length', False)}`",
        f"- Same SHA set as generated audit sample: `{stats.get('same_sha_set', False)}`",
        f"- Same SHA order as generated audit sample: `{stats.get('same_sha_order', False)}`",
        f"- Matching SHA prefix length: `{stats.get('matching_sha_prefix', 0)}`",
        f"- Is complete: `{stats['is_complete']}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """
    主函数：执行Step1小规模验证

    流程：
    1. 加载候选和pilot数据
    2. 分配Tier等级
    3. 采样生成审查和审计样本
    4. 写入输出文件
    """
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_calibration_path = args.primary_calibration_json
    proxy_calibration_path = args.proxy_calibration_json
    if args.calibration_json:
        print(
            "[deprecation] --calibration-json is deprecated; use --primary-calibration-json or --proxy-calibration-json",
            flush=True,
        )
        if args.threshold_mode == "message_only" and not proxy_calibration_path:
            proxy_calibration_path = args.calibration_json
        elif args.threshold_mode == "full_diff" and not primary_calibration_path:
            primary_calibration_path = args.calibration_json

    calibration_path = (
        proxy_calibration_path
        if args.threshold_mode == "message_only"
        else primary_calibration_path
    )
    if not calibration_path:
        required_flag = (
            "--proxy-calibration-json"
            if args.threshold_mode == "message_only"
            else "--primary-calibration-json"
        )
        raise RuntimeError(
            f"validate {args.threshold_mode} path requires {required_flag}"
        )
    calibration = miner.load_calibration(calibration_path)
    miner.require_calibration_mode(
        calibration,
        expected_mode=(
            "message_only" if args.threshold_mode == "message_only" else "full_diff"
        ),
        context=(
            "validate message-only proxy diagnostic path"
            if args.threshold_mode == "message_only"
            else "validate full-diff primary path"
        ),
    )
    args.primary_calibration_json = primary_calibration_path
    args.proxy_calibration_json = proxy_calibration_path

    audit_size = max(AUDIT_SIZE_MIN, min(AUDIT_SIZE_MAX, int(args.audit_size)))

    candidates = load_csv(Path(args.candidates))
    if not candidates:
        raise RuntimeError("validate input candidates is empty")
    if args.diff_required:
        candidates = [row for row in candidates if has_diff_features(row)]
        if not candidates:
            raise RuntimeError(
                "validate input has no diff-derived rows after diff-required filtering"
            )

    prefer_message_only = args.threshold_mode == "message_only"
    tau_a, tau_b, threshold_source = resolve_validate_thresholds(
        candidates=candidates,
        calibration=calibration,
        tau_a=args.tau_a,
        tau_b=args.tau_b,
        threshold_mode=args.threshold_mode,
    )
    args.tau_a = tau_a
    args.tau_b = tau_b
    args.threshold_source = threshold_source
    pilot_rows = load_csv(Path(args.pilot))
    if args.annotated_split_plan_json:
        split_summary = json.loads(
            Path(args.annotated_split_plan_json).read_text(encoding="utf-8")
        )
        annotated_split_protocol.assert_rows_match_split(
            rows=pilot_rows,
            split_sha_set=annotated_split_protocol.split_sha_set(
                split_summary, "evaluation"
            ),
            split_name="evaluation",
            context="validate evaluation reference",
        )
    split_stats = independent_split_stats(candidates, pilot_rows)
    if not split_stats["is_disjoint"]:
        raise RuntimeError(
            "validate requires an independent evaluation split; "
            f"candidate/pilot overlap detected: {split_stats['overlap_sha_examples']}"
        )

    tier_a = []
    tier_b = []
    tier_c = []
    for row in candidates:
        tier = assign_tier(
            row,
            tau_a=args.tau_a,
            tau_b=args.tau_b,
            prefer_message_only=prefer_message_only,
        )
        copied = dict(row)
        copied["tier"] = tier
        copied["validate_band"] = validate_band_from_tier(tier)
        if tier == "A":
            tier_a.append(copied)
        elif tier == "B":
            tier_b.append(copied)
        else:
            tier_c.append(copied)

    tier_a = attach_pilot_fields(tier_a, pilot_rows)
    tier_b = attach_pilot_fields(tier_b, pilot_rows)

    tier_a_sample = sample_diverse(
        tier_a, sample_size=args.sample_per_tier, seed=args.seed
    )
    tier_b_sample = sample_diverse(
        tier_b, sample_size=args.sample_per_tier, seed=args.seed + TIER_B_SEED_OFFSET
    )
    tier_a_audit_template: list[dict] = []
    tier_b_audit_template: list[dict] = []
    if args.export_audit_samples:
        audit_bundle = build_audit_samples(
            tier_a_rows=tier_a,
            tier_b_rows=tier_b,
            audit_size=audit_size,
            audit_sampling=args.audit_sampling,
            seed=args.seed,
            primary_audit_tier=str(args.audit_tier),
            tier_b_audit_size=args.tier_b_audit_size,
        )
        tier_a_audit_template = build_audit_template_rows(
            audit_bundle["tier_a_audit_sample"]
        )
        tier_b_audit_template = build_audit_template_rows(
            audit_bundle["tier_b_audit_sample"]
        )

    write_csv(output_dir / "tier_a_candidates.csv", tier_a)
    write_csv(output_dir / "tier_b_candidates.csv", tier_b)
    write_csv(output_dir / "tier_c_candidates.csv", tier_c)
    if args.export_audit_samples:
        write_csv(output_dir / "tier_a_review_sample.csv", tier_a_sample)
        write_csv(output_dir / "tier_b_review_sample.csv", tier_b_sample)
        write_csv(output_dir / "tier_a_audit_sample.csv", tier_a_audit_template)
        write_csv(output_dir / "tier_b_audit_sample.csv", tier_b_audit_template)
        write_review_packet(output_dir / "tier_a_review_packet.md", "A", tier_a_sample)
        write_review_packet(output_dir / "tier_b_review_packet.md", "B", tier_b_sample)
        write_audit_protocol(
            output_dir / "tier_a_audit_protocol.md", tier_a_audit_template, args=args
        )
        write_audit_protocol(
            output_dir / "tier_b_audit_protocol.md", tier_b_audit_template, args=args
        )

    tier_a_labeled_path = (
        Path(args.tier_a_audit_labeled_csv)
        if args.tier_a_audit_labeled_csv
        else (
            Path(args.audit_labeled_csv)
            if args.audit_labeled_csv
            else output_dir / "tier_a_audit_sample.csv"
        )
    )
    tier_b_labeled_path = (
        Path(args.tier_b_audit_labeled_csv)
        if args.tier_b_audit_labeled_csv
        else output_dir / "tier_b_audit_sample.csv"
    )

    precision_report = None
    if (
        tier_a_labeled_path.exists()
        or tier_b_labeled_path.exists()
        or args.require_audit_completion
    ):
        if args.require_audit_completion and not args.export_audit_samples:
            raise RuntimeError(
                "require-audit-completion=true requires --export-audit-samples"
            )
        if args.require_audit_completion and not tier_a_labeled_path.exists():
            raise RuntimeError(
                f"tier-a audit csv for completion check not found: {tier_a_labeled_path.as_posix()}"
            )

        tier_a_labeled_rows = (
            load_csv(tier_a_labeled_path) if tier_a_labeled_path.exists() else []
        )
        tier_b_labeled_rows = (
            load_csv(tier_b_labeled_path) if tier_b_labeled_path.exists() else []
        )

        tier_a_completion = evaluate_audit_completion(tier_a_labeled_rows)
        tier_a_completion.update(
            evaluate_audit_sample_alignment(tier_a_audit_template, tier_a_labeled_rows)
        )
        tier_a_completion["is_complete"] = bool(
            tier_a_completion["is_complete"] and tier_a_completion["is_aligned"]
        )
        write_audit_completion_report(
            path=output_dir / "tier_a_audit_completion.md",
            audit_path=tier_a_labeled_path,
            stats=tier_a_completion,
        )

        tier_b_completion = evaluate_audit_completion(tier_b_labeled_rows)
        tier_b_completion.update(
            evaluate_audit_sample_alignment(tier_b_audit_template, tier_b_labeled_rows)
        )
        tier_b_completion["is_complete"] = bool(
            tier_b_completion["is_complete"] and tier_b_completion["is_aligned"]
        )
        write_audit_completion_report(
            path=output_dir / "tier_b_audit_completion.md",
            audit_path=tier_b_labeled_path,
            stats=tier_b_completion,
        )

        if args.require_audit_completion and not tier_a_completion["is_complete"]:
            raise RuntimeError(
                "tier-a audit completion check failed: labeled audit csv is incomplete or invalid"
            )

        tier_a_patterns = summarize_misclassification_patterns(tier_a_labeled_rows)
        tier_b_patterns = summarize_misclassification_patterns(tier_b_labeled_rows)
        tier_a_pattern_csv = output_dir / "tier_a_misclassification_patterns.csv"
        tier_b_pattern_csv = output_dir / "tier_b_misclassification_patterns.csv"
        write_csv(
            tier_a_pattern_csv,
            tier_a_patterns
            or [
                {
                    "pattern": "other",
                    "count": 0,
                    "negative_rows": 0,
                    "share_of_negative_rows": "0.000000",
                }
            ],
        )
        write_csv(
            tier_b_pattern_csv,
            tier_b_patterns
            or [
                {
                    "pattern": "other",
                    "count": 0,
                    "negative_rows": 0,
                    "share_of_negative_rows": "0.000000",
                }
            ],
        )

        precision_report = build_precision_report(
            tier_a_labeled_rows=tier_a_labeled_rows,
            tier_b_labeled_rows=tier_b_labeled_rows,
            independent_split_stats=split_stats,
            tier_a_pattern_csv=tier_a_pattern_csv.as_posix(),
            tier_b_pattern_csv=tier_b_pattern_csv.as_posix(),
        )
        write_json(output_dir / "audit_precision_report.json", precision_report)
        write_precision_report(
            output_dir / "audit_precision_report.md", precision_report
        )

    summarize(
        tier_a,
        tier_b,
        tier_c,
        output_dir / "summary.md",
        args=args,
        precision_report=precision_report,
    )

    print(f"tier_a={len(tier_a)}")
    print(f"tier_b={len(tier_b)}")
    print(f"tier_c={len(tier_c)}")
    print(f"tier_a_sample={len(tier_a_sample)}")
    print(f"tier_b_sample={len(tier_b_sample)}")
    print(f"tier_a_audit_sample={len(tier_a_audit_template)}")
    print(f"tier_b_audit_sample={len(tier_b_audit_template)}")


if __name__ == "__main__":
    main()
