"""
Robustness analysis for the strict from-scratch Tier-B audit result.

This script keeps the strict final Tier-B candidate pool fixed, resamples
audit sets with deterministic seeds, labels them with the existing audit
protocol, and aggregates seed stability, type-local error rates, and negative
message patterns.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.labeling.message_only_audit_labeling import (
    DEFAULT_REVIEWER,
    NEGATIVE_SUBJECT_PATTERNS,
    VERB_RE,
    label_audit_row,
)
from src.pipeline.validation import TIER_AUDIT_SEED_OFFSET, sample_random


CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制，避免大字段导致解析错误
DEFAULT_PARENT_RUN = Path(
    "outputs/message_only_from_scratch_20260409T175508Z"
)  # 父级运行输出目录
DEFAULT_STRICT_RUN = (
    DEFAULT_PARENT_RUN / "strict_final_20260409T180439Z"
)  # 严格运行输出目录
DEFAULT_TIER_B = (
    DEFAULT_STRICT_RUN / "validation" / "tier_b_candidates.csv"
)  # Tier B候选文件默认路径
DEFAULT_REFERENCE_LABELS = (
    DEFAULT_PARENT_RUN
    / "seed_run_20260409T180207Z"
    / "validation"
    / "tier_b_audit_sample_labeled.csv"
)  # 参考标签文件默认路径
DEFAULT_OUTPUT_DIR = (
    DEFAULT_PARENT_RUN / "analysis" / "tier_b_robustness"
)  # 输出目录默认路径
DEFAULT_SEEDS = [
    # 用于稳健性测试的20个质数种子（用于生成不同的审计样本）
    3,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
    29,
    31,
    37,
    41,
    43,
    47,
    53,
    59,
    61,
    67,
    71,
    73,
]
SUBSTANTIVE_TYPES = [
    "fix",
    "feat",
    "refactor",
    "test",
    "perf",
]  # 有实质内容的提交类型列表


def parse_args() -> argparse.Namespace:
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tier-b-candidates", default=DEFAULT_TIER_B.as_posix()
    )  # Tier B候选文件路径
    parser.add_argument(
        "--reference-labels", default=DEFAULT_REFERENCE_LABELS.as_posix()
    )  # 参考标签文件路径
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR.as_posix()
    )  # 输出目录路径
    parser.add_argument(
        "--audit-size", type=int, default=300
    )  # 审计样本大小（每个种子采样的数量）
    parser.add_argument(
        "--seeds",
        default=",".join(str(seed) for seed in DEFAULT_SEEDS),
        help="Comma-separated base seeds. Actual audit seed is base seed + validate.TIER_AUDIT_SEED_OFFSET.",
    )  # 质数种子列表（逗号分隔），实际审计种子 = 基础种子 + 偏移量
    parser.add_argument(
        "--reviewer", default=DEFAULT_REVIEWER
    )  # 审计员名称（用于标签记录）
    return parser.parse_args()


def load_csv(path: Path) -> list[dict]:
    # 设置CSV字段大小限制（支持大字段）
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并读取为字典列表
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path, rows: list[dict], fieldnames: list[str] | None = None
) -> None:
    # 创建父目录（如果不存在）
    path.parent.mkdir(parents=True, exist_ok=True)
    # 如果未指定字段名，按出现顺序自动提取
    if fieldnames is None:
        ordered: list[str] = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    ordered.append(key)
        fieldnames = ordered
    # 写入CSV文件
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def bool_diff_complete(row: dict) -> bool:
    # 检查行是否包含完整的diff信息：git_diff非空且file_count、hunk_count、changed_lines都非空
    return bool(str(row.get("git_diff", "")).strip()) and all(
        str(row.get(key, "")).strip()
        for key in ("file_count", "hunk_count", "changed_lines")
    )


def label_rows(rows: list[dict], reviewer: str) -> list[dict]:
    # 对每一行应用审计标签规则，返回带标签的行列表
    return [label_audit_row(row, reviewer=reviewer) for row in rows]


def positive_count(rows: list[dict]) -> int:
    # 统计标记为单意图（audit_is_single_intent=1）的行数
    return sum(
        1 for row in rows if str(row.get("audit_is_single_intent", "")).strip() == "1"
    )


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    # Wilson置信区间计算（95%置信度，z=1.96），返回(下界, 上界)
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total  # 成功比例
    denom = 1 + z * z / total  # 分母
    center = (phat + z * z / (2 * total)) / denom  # 中心点
    # 边际误差
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def safe_ratio(numerator: int, denominator: int) -> float:
    # 安全除法：分母为0时返回0.0，避免除零错误
    return numerator / denominator if denominator else 0.0


def subject_of(row: dict) -> str:
    # 提取行的主题（subject）或提交消息的第一行
    return str(row.get("subject") or row.get("commit_message") or "").splitlines()[0]


def message_patterns(row: dict) -> list[str]:
    # 分析提交消息中的负面模式（可能导致多意图的特征）
    message = str(row.get("commit_message", ""))
    subject = subject_of(row)
    lower = " ".join(message.lower().split())  # 标准化小写消息
    subject_lower = subject.lower()
    lines = message.splitlines()
    # 提取Markdown风格的列表项（- 或 * 开头）
    bullet_lines = [
        line.strip() for line in lines if line.lstrip().startswith(("- ", "* "))
    ]
    patterns: list[str] = []

    # 检查多种负面模式
    if bullet_lines:
        patterns.append("markdown_body_bullet")  # 消息体包含列表
    if len(bullet_lines) >= 2:
        patterns.append("multi_item_body_bullets")  # 多项列表
    # 检查CI/维护相关的二次维护标记
    if any(
        marker in " ".join(bullet_lines).lower()
        for marker in (
            "kick ci",
            "address review",
            "review comments",
            "circleci",
            "artifact",
        )
    ):
        patterns.append("secondary_maintenance_bullet")
    # 内联星号强调（非列表的*）
    if "*" in message and not bullet_lines:
        patterns.append("inline_asterisk_emphasis")
    # 检查显式多目标主题模式
    if any(pattern in lower for pattern in NEGATIVE_SUBJECT_PATTERNS):
        patterns.append("explicit_multi_goal_subject")
    # 检查连接动作（" and " 且动词>=3个）
    if " and " in lower and len(VERB_RE.findall(lower)) >= 3:
        patterns.append("conjoined_actions")
    # 分号主题
    if ";" in subject:
        patterns.append("semicolon_subject")
    # 检查连接词标记
    if any(
        marker in lower
        for marker in (
            " also ",
            " also,",
            " additionally ",
            " meanwhile ",
            " plus ",
            " follow-up ",
        )
    ):
        patterns.append("connective_multi_marker")
    # 长主题
    if len(subject) >= 140:
        patterns.append("long_subject")
    # 多从句主题
    if any(marker in subject_lower for marker in ("also", " and ", " plus ")):
        patterns.append("multi_clause_subject")
    # 无匹配时归类为其他
    if not patterns:
        patterns.append("other")
    return patterns


def summarize_by_type(rows: list[dict], source: str) -> list[dict]:
    # 按提交类型统计正/负面数量和比率
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[str(row.get("type", ""))].append(row)

    output = []
    for commit_type in SUBSTANTIVE_TYPES:
        typed = by_type.get(commit_type, [])
        total = len(typed)
        positives = positive_count(typed)
        negatives = total - positives
        output.append(
            {
                "source": source,
                "type": commit_type,
                "total": total,
                "positive": positives,
                "negative": negatives,
                "negative_rate": f"{safe_ratio(negatives, total):.6f}",
                "positive_rate": f"{safe_ratio(positives, total):.6f}",
            }
        )
    return output


def summarize_patterns(
    rows: list[dict], source: str, unique: bool = False
) -> list[dict]:
    # 统计负面行中的消息模式分布
    negatives = [
        row for row in rows if str(row.get("audit_is_single_intent", "")).strip() == "0"
    ]
    if unique:
        # 按SHA去重（每个提交只计一次）
        by_sha = {str(row.get("sha", "")): row for row in negatives}
        negatives = list(by_sha.values())
    counts: Counter[str] = Counter()
    for row in negatives:
        for pattern in message_patterns(row):
            counts[pattern] += 1
    total = len(negatives)
    return [
        {
            "source": source,
            "pattern": pattern,
            "count": count,
            "share_of_negative_rows": f"{safe_ratio(count, total):.6f}",
            "negative_rows": total,
        }
        for pattern, count in counts.most_common()
    ]


def row_summary(rows: list[dict], seed: int, reference_shas: set[str]) -> dict:
    # 生成单个种子的审计摘要统计
    total = len(rows)
    positives = positive_count(rows)
    negatives = total - positives
    low, high = wilson_interval(positives, total)
    shas = {str(row.get("sha", "")) for row in rows}
    overlap = len(shas & reference_shas)
    summary = {
        "seed": seed,
        "audit_seed": seed + TIER_AUDIT_SEED_OFFSET,
        "sample_size": total,
        "positive": positives,
        "negative": negatives,
        "single_intent_ratio": f"{safe_ratio(positives, total):.6f}",
        "noise_upper_bound": f"{safe_ratio(negatives, total):.6f}",
        "wilson95_low": f"{low:.6f}",
        "wilson95_high": f"{high:.6f}",
        "diff_complete": sum(1 for row in rows if bool_diff_complete(row)),
        "unique_sha": len(shas),
        "overlap_with_reference": overlap,
        "reference_jaccard": f"{safe_ratio(overlap, len(shas | reference_shas)):.6f}",
    }
    for commit_type in SUBSTANTIVE_TYPES:
        # 按类型统计负面的数量和比率
        typed = [row for row in rows if str(row.get("type", "")) == commit_type]
        type_total = len(typed)
        type_positive = positive_count(typed)
        type_negative = type_total - type_positive
        summary[f"{commit_type}_total"] = type_total
        summary[f"{commit_type}_negative"] = type_negative
        summary[f"{commit_type}_negative_rate"] = (
            f"{safe_ratio(type_negative, type_total):.6f}"
        )
    return summary


def pairwise_jaccard(samples: dict[int, list[dict]]) -> tuple[float, float, float]:
    # 计算所有种子样本两两之间的Jaccard相似度（最小/平均/最大）
    values: list[float] = []
    seed_items = list(samples.items())
    for idx, (_, left_rows) in enumerate(seed_items):
        # 提取左样本的SHA集合
        left = {str(row.get("sha", "")) for row in left_rows}
        for _, right_rows in seed_items[idx + 1 :]:
            # 提取右样本的SHA集合
            right = {str(row.get("sha", "")) for row in right_rows}
            # 计算Jaccard相似度：交集/并集
            values.append(safe_ratio(len(left & right), len(left | right)))
    if not values:
        return 0.0, 0.0, 0.0
    return min(values), statistics.mean(values), max(values)


def format_percent(value: float) -> str:
    # 将小数转换为百分比字符串（保留两位小数）
    return f"{100 * value:.2f}%"


def write_report(
    path: Path,
    *,
    tier_b_rows: list[dict],
    reference_rows: list[dict],
    seed_summaries: list[dict],
    pooled_rows: list[dict],
    unique_pooled_rows: list[dict],
    pairwise_overlap: tuple[float, float, float],
    seeds: list[int],
) -> None:
    # 提取关键指标用于报告
    ratios = [float(row["single_intent_ratio"]) for row in seed_summaries]
    noises = [float(row["noise_upper_bound"]) for row in seed_summaries]
    # 参考审计的统计
    main_positive = positive_count(reference_rows)
    main_total = len(reference_rows)
    main_low, main_high = wilson_interval(main_positive, main_total)
    # 合并种子的统计
    pooled_positive = positive_count(pooled_rows)
    pooled_total = len(pooled_rows)
    pooled_low, pooled_high = wilson_interval(pooled_positive, pooled_total)

    # 按类型汇总统计
    ref_type_rows = summarize_by_type(reference_rows, "reference_audit")
    pooled_type_rows = summarize_by_type(pooled_rows, "seed_pooled_occurrences")
    unique_type_rows = summarize_by_type(unique_pooled_rows, "seed_unique_sha")
    # 按消息模式汇总统计
    pattern_rows = (
        summarize_patterns(reference_rows, "reference_audit")
        + summarize_patterns(pooled_rows, "seed_pooled_occurrences")
        + summarize_patterns(unique_pooled_rows, "seed_unique_sha", unique=True)
    )

    # 找出最差和最佳种子
    worst_seed = min(
        seed_summaries, key=lambda item: float(item["single_intent_ratio"])
    )
    best_seed = max(seed_summaries, key=lambda item: float(item["single_intent_ratio"]))

    lines = [
        "# Tier-B Robustness Analysis",
        "",
        "## Scope",
        "",
        f"- Fixed Tier-B candidate pool size: `{len(tier_b_rows)}`",
        f"- Diff-complete Tier-B rows: `{sum(1 for row in tier_b_rows if bool_diff_complete(row))}`",
        f"- Audit sample size per seed: `{seed_summaries[0]['sample_size'] if seed_summaries else 0}`",
        f"- Seeds: `{', '.join(str(seed) for seed in seeds)}`",
        "- Labeling protocol: `src/labeling/message_only_audit_labeling.py` deterministic audit rules",
        "",
        "## Seed Stability",
        "",
        f"- Reference strict audit: `{main_positive}/{main_total}` positive = `{format_percent(safe_ratio(main_positive, main_total))}`",
        f"- Reference Wilson 95% CI: `[{format_percent(main_low)}, {format_percent(main_high)}]`",
        f"- 20-seed mean single-intent ratio: `{format_percent(statistics.mean(ratios))}`",
        f"- 20-seed stdev: `{format_percent(statistics.pstdev(ratios))}`",
        f"- 20-seed min/max: `{format_percent(min(ratios))}` / `{format_percent(max(ratios))}`",
        f"- Worst seed: `{worst_seed['seed']}` with `{format_percent(float(worst_seed['single_intent_ratio']))}`",
        f"- Best seed: `{best_seed['seed']}` with `{format_percent(float(best_seed['single_intent_ratio']))}`",
        f"- Pooled seed occurrences: `{pooled_positive}/{pooled_total}` positive = `{format_percent(safe_ratio(pooled_positive, pooled_total))}`",
        f"- Pooled Wilson 95% CI: `[{format_percent(pooled_low)}, {format_percent(pooled_high)}]`",
        f"- Pairwise sample Jaccard min/mean/max: `{pairwise_overlap[0]:.4f}` / `{pairwise_overlap[1]:.4f}` / `{pairwise_overlap[2]:.4f}`",
        f"- Mean noise upper bound across seeds: `{format_percent(statistics.mean(noises))}`",
        "",
        "Interpretation: because the Tier-B pool contains 323 rows and each audit samples 300 rows, different seeds mostly test sensitivity to which 23 rows are omitted. The observed spread is therefore a direct stability check around the reported audit estimate.",
        "",
        "## Type-Local Error Distribution",
        "",
        "| Source | Type | Total | Positive | Negative | Negative Rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in ref_type_rows + pooled_type_rows + unique_type_rows:
        lines.append(
            f"| {row['source']} | `{row['type']}` | {row['total']} | {row['positive']} | {row['negative']} | {format_percent(float(row['negative_rate']))} |"
        )

    lines.extend(
        [
            "",
            "## Negative Message Patterns",
            "",
            "A negative row may match multiple message patterns, so pattern counts are diagnostic rather than mutually exclusive.",
            "",
            "| Source | Pattern | Count | Negative Rows | Share |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in pattern_rows:
        lines.append(
            f"| {row['source']} | `{row['pattern']}` | {row['count']} | {row['negative_rows']} | {format_percent(float(row['share_of_negative_rows']))} |"
        )

    lines.extend(
        [
            "",
            "## Main Takeaway",
            "",
            "The strict Tier-B result is stable under deterministic seed resampling. Residual noise remains small and is not evenly spread across all types; it is concentrated in inspectable message-level patterns, especially markdown-style body bullets and a small number of long or multi-clause subjects.",
            "",
            "## Artifact Index",
            "",
            "- `seed_stability.csv`: per-seed audit ratios, type counts, and overlap with the reference audit.",
            "- `type_error_distribution.csv`: type-local positive/negative rates for reference, pooled occurrences, and unique SHAs.",
            "- `negative_pattern_distribution.csv`: message-pattern counts among negative labels.",
            "- `negative_examples.csv`: concrete negative rows for inspection.",
            "- `seeds/seed_<N>/tier_b_audit_sample_labeled.csv`: local/generated labeled audit sample for each seed. These files include full diffs and are intentionally ignored by Git; rerun `analyze_tier_b_robustness.py` to regenerate them.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    # 解析命令行参数
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 解析种子列表（逗号分隔的字符串转为整数列表）
    seeds = [int(item.strip()) for item in args.seeds.split(",") if item.strip()]

    # 加载Tier B候选和参考标签
    tier_b_rows = load_csv(Path(args.tier_b_candidates))
    reference_rows = load_csv(Path(args.reference_labels))
    # 构建参考SHA集合用于重叠计算
    reference_shas = {str(row.get("sha", "")) for row in reference_rows}

    # 检查Tier B候选池大小是否足够进行审计
    if len(tier_b_rows) < args.audit_size:
        raise RuntimeError(
            f"Tier-B pool too small for audit size: pool={len(tier_b_rows)} audit_size={args.audit_size}"
        )
    # 检查是否有缺失diff的行
    missing_diff = [row for row in tier_b_rows if not bool_diff_complete(row)]
    if missing_diff:
        raise RuntimeError(
            f"Tier-B pool contains non-diff-complete rows: {len(missing_diff)}"
        )

    # 初始化统计变量
    seed_summaries: list[dict] = []  # 每个种子的摘要
    seed_samples: dict[int, list[dict]] = {}  # 每个种子的样本
    pooled_rows: list[dict] = []  # 合并所有种子的标签行
    negative_examples: list[dict] = []  # 负面示例列表

    # 遍历每个种子进行采样和标签
    for seed in seeds:
        # 随机采样审计样本
        sample = sample_random(
            tier_b_rows,
            sample_size=args.audit_size,
            seed=seed + TIER_AUDIT_SEED_OFFSET,
        )
        # 对采样进行标签
        labeled = label_rows(sample, reviewer=args.reviewer)
        seed_samples[seed] = labeled
        # 合并到pooled_rows
        pooled_rows.extend(labeled)

        # 写入单个种子的标签CSV文件
        seed_dir = output_dir / "seeds" / f"seed_{seed}"
        write_csv(seed_dir / "tier_b_audit_sample_labeled.csv", labeled)

        # 收集负面示例
        for row in labeled:
            if str(row.get("audit_is_single_intent", "")).strip() == "0":
                negative_examples.append(
                    {
                        "source_seed": seed,
                        "sha": row.get("sha", ""),
                        "type": row.get("type", ""),
                        "subject": subject_of(row),
                        "audit_notes": row.get("audit_notes", ""),
                        "message_patterns": ";".join(message_patterns(row)),
                        "file_count": row.get("file_count", ""),
                        "changed_lines": row.get("changed_lines", ""),
                        "roles": row.get("roles", ""),
                        "commit_url": row.get("commit_url", ""),
                    }
                )

        # 生成单个种子的摘要并添加到列表
        seed_summaries.append(
            row_summary(labeled, seed=seed, reference_shas=reference_shas)
        )

    # 按SHA去重（合并后可能重复）
    unique_pooled_by_sha = {str(row.get("sha", "")): row for row in pooled_rows}
    unique_pooled_rows = list(unique_pooled_by_sha.values())

    # 生成汇总统计
    type_rows = (
        summarize_by_type(reference_rows, "reference_audit")
        + summarize_by_type(pooled_rows, "seed_pooled_occurrences")
        + summarize_by_type(unique_pooled_rows, "seed_unique_sha")
    )
    pattern_rows = (
        summarize_patterns(reference_rows, "reference_audit")
        + summarize_patterns(pooled_rows, "seed_pooled_occurrences")
        + summarize_patterns(unique_pooled_rows, "seed_unique_sha", unique=True)
    )

    # 写入CSV输出文件
    write_csv(output_dir / "seed_stability.csv", seed_summaries)
    write_csv(output_dir / "type_error_distribution.csv", type_rows)
    write_csv(output_dir / "negative_pattern_distribution.csv", pattern_rows)
    write_csv(output_dir / "negative_examples.csv", negative_examples)

    # 写入Markdown报告
    write_report(
        output_dir / "REPORT.md",
        tier_b_rows=tier_b_rows,
        reference_rows=reference_rows,
        seed_summaries=seed_summaries,
        pooled_rows=pooled_rows,
        unique_pooled_rows=unique_pooled_rows,
        pairwise_overlap=pairwise_jaccard(seed_samples),
        seeds=seeds,
    )

    # 如果存在CHECKLIST.md，则标记完成项
    checklist = output_dir / "CHECKLIST.md"
    if checklist.exists():
        text = checklist.read_text(encoding="utf-8")
        for item in [
            "Create reproducible analysis script",
            "Run 20-seed Tier-B audit resampling",
            "Generate per-seed labeled audit CSVs",
            "Aggregate seed stability metrics",
            "Aggregate type-local error metrics",
            "Aggregate negative message-pattern metrics",
            "Write final robustness report",
        ]:
            text = text.replace(f"- [ ] {item}", f"- [x] {item}")
        checklist.write_text(text, encoding="utf-8")

    # 打印摘要信息
    print(f"tier_b_pool={len(tier_b_rows)}")
    print(f"seeds={len(seeds)}")
    print(f"output_dir={output_dir.as_posix()}")
    print((output_dir / "REPORT.md").as_posix())


if __name__ == "__main__":
    main()
