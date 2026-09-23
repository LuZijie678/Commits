"""
预过滤脚本（仅基于消息）

本脚本对全部提交进行初步筛选，仅使用提交消息特征。
这是整个流水线的第一阶段，用于从大量提交中筛选出可能具有单意图的候选。

预过滤基于：
- 消息格式（是否符合传统提交格式）
- 消息长度和结构
- 原子性先验概率
- Tier分类（A/B/C）

输出：
- all_prefilter_candidates.csv: 所有通过的候选
- prefilter_top_candidates.csv: 排名前N的候选
- summary.md: 统计摘要
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from src.pipeline import atomic_mining as miner


SUBSTANTIVE_TYPES = {"fix", "feat", "refactor", "perf", "test"}  # 实质性提交类型
WEAK_TYPES = {"docs", "style"}  # 弱实质性类型
INFRA_TYPES = {"build", "ci", "chore"}  # 基础设施类型
DEFAULT_TARGET_COUNT = 20000  # 默认目标候选数量
DEFAULT_TOP_EXAMPLE_COUNT = 15  # 默认Top示例数量
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    # 输入CSV文件路径（全部提交数据）
    parser.add_argument(
        "--input",
        default="../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
    )
    # 输出目录路径
    parser.add_argument("--output-dir", default="outputs/prefilter")
    # 最小概率门控（0=自动推导）
    parser.add_argument("--min-prefilter-prob", type=float, default=0.0)
    # Tier A阈值
    parser.add_argument("--tau-a", type=float, default=miner.DEFAULT_TAU_A)
    # Tier B阈值
    parser.add_argument("--tau-b", type=float, default=miner.DEFAULT_TAU_B)
    # 目标候选数量
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    # 校准JSON文件路径（可选）
    parser.add_argument("--calibration-json", default="")
    return parser.parse_args()


def is_message_only_calibration(calibration: dict | None) -> bool:
    """
    判断校准工件是否适用于 message-only 路径

    full-diff calibration 的阈值/等渗映射不能直接用于 message-only 概率。
    仅当工件显式声明 message-only 模式时，才允许在 prefilter 中复用。
    """
    return miner.is_message_only_calibration(calibration)


def resolve_prefilter_thresholds(
    calibration: dict | None,
    tau_a: float | None,
    tau_b: float | None,
) -> tuple[float | None, float | None]:
    """
    解析 prefilter 阈值

    只接受显式的 message-only calibration 阈值，避免把 full-diff 阈值
    静默带入 message-only 预过滤路径。
    """
    calibration_for_thresholds = None
    if calibration is not None:
        calibration_for_thresholds = miner.require_calibration_mode(
            calibration,
            expected_mode="message_only",
            context="prefilter message-only proxy path",
        )
    return miner.resolve_thresholds(
        calibration=calibration_for_thresholds,
        tau_a=tau_a,
        tau_b=tau_b,
    )


def load_rows(path: Path) -> list[dict]:
    """
    加载CSV文件

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表
    """
    # 设置CSV字段大小限制，避免大字段导致解析错误
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并使用DictReader解析为字典列表（每行是一个字典）
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def type_priority(commit_type: str) -> int:
    """
    获取提交类型优先级

    优先级顺序：
    - 0: 实质性类型（fix, feat, refactor, perf, test）
    - 1: 弱实质性类型（docs, style）
    - 2: 基础设施类型（build, ci, chore）

    参数:
        commit_type: 提交类型

    返回:
        int: 优先级（0最高）
    """
    if commit_type in SUBSTANTIVE_TYPES:
        return 0
    if commit_type in WEAK_TYPES:
        return 1
    return 2


def type_priority(commit_type: str) -> int:
    """
    获取提交类型优先级

    优先级顺序：
    - 0: 实质性类型（fix, feat, refactor, perf, test）
    - 1: 弱实质性类型（docs, style）
    - 2: 基础设施类型（build, ci, chore）

    参数:
        commit_type: 提交类型

    返回:
        int: 优先级（0最高）
    """
    # 检查是否为实质性类型：fix, feat, refactor, perf, test（优先级最高=0）
    if commit_type in SUBSTANTIVE_TYPES:
        return 0
    # 检查是否为弱实质性类型：docs, style（优先级次之=1）
    if commit_type in WEAK_TYPES:
        return 1
    # 默认是基础设施类型：build, ci, chore（优先级最低=2）
    return 2


def build_candidates(
    rows: list[dict],
    min_prefilter_prob: float,
    tau_a: float,
    tau_b: float,
    calibration: dict | None = None,
) -> list[dict]:
    """
    构建预过滤候选列表

    预过滤仅使用消息特征（无diff），这是流水线的第一阶段。
    流程：
    1. 解析每条提交的消息特征
    2. 派生信号上下文（权重、偏置、缩放）
    3. 计算原子性先验概率
    4. 应用概率门控过滤
    5. 分配Tier等级（A/B/C）
    6. 收集信号原因

    参数:
        rows: 输入的提交行列表（每行需包含commit_message和type字段）
        min_prefilter_prob: 最小概率门控（0=自动推导）
        tau_a: Tier A阈值（概率大于此为Tier A）
        tau_b: Tier B阈值（概率大于此为Tier B）
        calibration: 校准参数（可选，有校准文件时使用模型路径）

    返回:
        list[dict]: 过滤后的候选列表，每项包含:
        - row: 原始行
        - message_features: 解析后的消息特征
        - prior_info: 原子性先验信息
        - score: 100 * p_atomic
        - tier: A/B/C
        - reasons: 信号原因列表
    """
    # 步骤1: 解析消息特征
    # 遍历所有行，解析每条的commit_message得到消息特征
    scored_rows: list[dict] = []
    for row in rows:
        # 解析消息特征（subject_line, body, prefix_match等）
        message_features = miner.parse_message(row["commit_message"])
        scored_rows.append(
            {
                "row": row,  # 保留原始行
                "message_features": message_features,  # 解析后的消息特征
            }
        )

    # 步骤2: 派生或使用信号上下文
    # 消息-only预过滤仍然派生基于分布的信号上下文，
    # 以保持与完整挖掘路径一致的先验计算
    # 从校准文件中获取消息协议（如果存在）
    message_protocol = (
        (calibration or {}).get("message_protocol")
        if isinstance(calibration, dict)
        else None
    )
    # 从校准文件中获取类型协议
    calibration_type_protocol = (
        (calibration or {}).get("type_protocol")
        if isinstance(calibration, dict)
        else None
    )
    # 如果有校准类型协议则使用，否则从数据派生
    if isinstance(calibration_type_protocol, dict):
        type_protocol = calibration_type_protocol
    else:
        type_protocol = miner.derive_type_protocol(
            candidate_types=[item["row"]["type"] for item in scored_rows]
        )

    # 步骤3: 计算信号映射（无diff特征）
    # 为每个候选计算原子性信号映射
    signal_maps = [
        miner.atomic_signal_map(
            message_features=item["message_features"],
            candidate_type=item["row"]["type"],
            diff_features=None,  # 消息-only，无diff
            message_protocol=message_protocol,
            type_protocol=type_protocol,
        )
        for item in scored_rows
    ]

    # 步骤4: 获取或派生信号上下文
    # 尝试从校准文件获取信号上下文，否则从当前数据派生
    calibration_signal_context = (calibration or {}).get("signal_context")
    if isinstance(calibration_signal_context, dict) and isinstance(
        calibration_signal_context.get("weights"), dict
    ):
        # 使用校准文件中的信号上下文
        signal_context = calibration_signal_context
    else:
        # 从当前信号映射派生信号上下文
        signal_context = miner.derive_atomic_signal_context(signal_maps)

    # 步骤5: 计算消息-only原子性先验
    # 注意：预过滤阶段不使用full-diff模型路径，因此不调用atomic_prior（该函数要求非空diff特征）。
    message_only_calibration = None
    if calibration is not None:
        message_only_calibration = miner.require_calibration_mode(
            calibration,
            expected_mode="message_only",
            context="prefilter message-only proxy path",
        )
    epistemic_ref = (
        (calibration or {}).get("epistemic_reference")
        if isinstance((calibration or {}).get("epistemic_reference"), dict)
        else {}
    )
    epistemic_center = float(epistemic_ref.get("center", 0.0))
    epistemic_scale = float(epistemic_ref.get("scale", 1.0))
    for item in scored_rows:
        message_features = item["message_features"]
        candidate_type = item["row"]["type"]
        logit = miner.atomic_logit(
            message_features=item["message_features"],
            candidate_type=candidate_type,
            diff_features=None,
            signal_context=signal_context,
            message_protocol=message_protocol,
            type_protocol=type_protocol,
        )
        prior = miner.clip_prob(miner.sigmoid(logit))
        calibrated = miner.apply_calibration_to_raw_prob(
            prior,
            logit,
            calibration=message_only_calibration,
        )
        omega = miner.derive_atomic_weight(
            calibrated,
            epistemic_std=0.0,
            epistemic_center=epistemic_center,
            epistemic_scale=epistemic_scale,
        )
        feature_map = miner.build_atomic_feature_map(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=None,
            repo_stats=None,
            global_stats=None,
        )
        item["prior_info"] = {
            "atomic_logit": logit,
            "atomic_prior": prior,
            "atomic_prior_calibrated": calibrated,
            "p_raw": prior,
            "p_atomic": calibrated,
            "omega_atomic": miner.clip_prob(omega),
            "epistemic_std": 0.0,
            "x_atom": json.dumps(feature_map, ensure_ascii=False, sort_keys=True),
            "signal_context_source": (signal_context or {}).get(
                "source", "default_uniform_weight"
            ),
        }

    # 提取所有概率值
    probabilities = [item["prior_info"]["p_atomic"] for item in scored_rows]
    # 预过滤是message-only路径，Tier阈值应与当前message-only概率同尺度派生；
    # 不直接复用full-diff calibration thresholds，避免尺度错位污染后续统计。
    # 派生Tier阈值（基于消息-only概率分布）
    tau_a, tau_b, tau_source = miner.derive_thresholds(
        probabilities=probabilities,
        calibration=None,  # message-only不使用校准
        tau_a=tau_a,
        tau_b=tau_b,
    )
    # 派生概率门控阈值
    gate_prob, gate_source = miner.derive_gate_threshold(
        probabilities=probabilities,
        configured_min_prior=min_prefilter_prob,
    )

    # 步骤6: 应用门控过滤并构建候选
    candidates = []
    for item in scored_rows:
        row = item["row"]
        message_features = item["message_features"]
        prior_info = item["prior_info"]
        # 计算分数：100 * p_atomic
        score = 100.0 * float(prior_info["p_atomic"])
        # 收集信号原因
        reasons = miner.summarize_signal_reasons(
            miner.atomic_signal_map(
                message_features=message_features,
                candidate_type=row["type"],
                diff_features=None,
                message_protocol=message_protocol,
                type_protocol=type_protocol,
            )
        )
        p_atomic = prior_info["p_atomic"]
        # 门控过滤：仅保留概率门控，移除与其冗余的 score gate
        if p_atomic < gate_prob:
            continue
        # 分配Tier等级
        prefilter_tier = miner.assign_atomic_tier(p_atomic, tau_a=tau_a, tau_b=tau_b)
        # 构建候选字典，包含丰富的预过滤信息
        candidates.append(
            {
                "prefilter_score": score,  # 预过滤分数
                "proxy_model_mode": "message_only",
                "proxy_model_role": "proxy",
                "x_atom": prior_info["x_atom"],  # 原始logit
                "x_atom_message_only": prior_info["x_atom"],
                "p_raw": round(prior_info["p_raw"], 6),  # 原始概率
                "p_raw_message_only": round(prior_info["p_raw"], 6),
                "p_atomic": round(prior_info["p_atomic"], 6),  # 原子性概率
                "p_atomic_message_only": round(prior_info["p_atomic"], 6),
                "omega_atomic": round(prior_info["omega_atomic"], 6),  # 原子性权重
                "omega_atomic_message_only": round(prior_info["omega_atomic"], 6),
                "signal_context_source": prior_info.get(
                    "signal_context_source", ""
                ),  # 信号上下文来源
                "signal_context_source_message_only": prior_info.get(
                    "signal_context_source", ""
                ),
                "atomic_logit": round(prior_info["atomic_logit"], 6),  # 原子性logit
                "atomic_logit_message_only": round(prior_info["atomic_logit"], 6),
                "atomic_prior": round(prior_info["atomic_prior"], 6),  # 原子性先验
                "atomic_prior_message_only": round(prior_info["atomic_prior"], 6),
                "atomic_prior_calibrated": round(
                    prior_info["atomic_prior_calibrated"],
                    6,  # 校准后的先验
                ),
                "atomic_prior_message_only_calibrated": round(
                    prior_info["atomic_prior_calibrated"],
                    6,
                ),
                "atomic_weight": round(
                    prior_info["omega_atomic"], 6
                ),  # 原子性权重（重复）
                "prefilter_gate_prob": round(gate_prob, 6),  # 门控概率阈值
                "prefilter_gate_source": gate_source,  # 门控来源
                "prefilter_tier": prefilter_tier,  # Tier等级
                "prefilter_tier_source": tau_source,  # Tier来源
                "prefilter_tau_a": round(tau_a, 6),  # Tier A阈值
                "prefilter_tau_b": round(tau_b, 6),  # Tier B阈值
                "type_priority": type_priority(row["type"]),  # 类型优先级
                "sha": row["sha"],  # 提交SHA
                "type": row["type"],  # 提交类型
                "subject": message_features["subject_line"],  # subject行
                "subject_len": message_features["subject_len"],  # subject长度
                "body_line_count": message_features["body_line_count"],  # body行数
                "paragraph_count": message_features["paragraph_count"],  # 段落数
                "prefix_match": int(message_features["prefix_match"]),  # 前缀匹配
                "has_multi_markers": int(
                    message_features["has_multi_markers"]
                ),  # 多意图标记
                "has_noisy_markers": int(
                    message_features["has_noisy_markers"]
                ),  # 噪声标记
                "release_like": int(message_features["release_like"]),  # 类发布标记
                "prefilter_reasons": ",".join(reasons),  # 信号原因
                "commit_message": row["commit_message"].replace(
                    "\r\n", "\n"
                ),  # 规范化换行符
            }
        )

    # 按多个键排序：概率、分数、优先级、body行数、subject
    candidates.sort(
        key=lambda item: (
            -item.get("p_atomic", item["atomic_prior"]),
            -item["prefilter_score"],
            item["type_priority"],
            item["body_line_count"],
            item["subject"],
        )
    )
    return candidates


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    写入CSV文件

    参数:
        path: 输出文件路径
        rows: 要写入的行列表
    """
    # 如果没有数据，写入空文件
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # 定义输出字段顺序
    fieldnames = [
        "prefilter_score",  # 预过滤分数
        "x_atom",  # 原始logit
        "p_raw",  # 原始概率
        "p_atomic",  # 原子性概率
        "omega_atomic",  # 原子性权重
        "signal_context_source",  # 信号上下文来源
        "atomic_logit",  # 原子性logit
        "atomic_prior",  # 原子性先验
        "atomic_prior_calibrated",  # 校准后先验
        "atomic_weight",  # 原子性权重
        "prefilter_gate_prob",  # 门控概率阈值
        "prefilter_gate_source",  # 门控来源
        "prefilter_tier",  # Tier等级
        "prefilter_tier_source",  # Tier来源
        "prefilter_tau_a",  # Tier A阈值
        "prefilter_tau_b",  # Tier B阈值
        "type_priority",  # 类型优先级
        "sha",  # 提交SHA
        "type",  # 提交类型
        "subject",  # subject行
        "subject_len",  # subject长度
        "body_line_count",  # body行数
        "paragraph_count",  # 段落数
        "prefix_match",  # 前缀匹配
        "has_multi_markers",  # 多意图标记
        "has_noisy_markers",  # 噪声标记
        "release_like",  # 类发布标记
        "prefilter_reasons",  # 信号原因
        "commit_message",  # 提交消息
    ]
    # 打开文件并写入CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        # 使用DictWriter写入
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()  # 写入表头
        writer.writerows(rows)  # 写入数据行


def write_summary(
    path: Path, candidates: list[dict], selected: list[dict], args: argparse.Namespace
) -> None:
    """
    写入统计摘要

    生成Markdown格式的摘要报告，包含Tier分布、概率分布、类型分布等统计信息。

    参数:
        path: 输出文件路径
        candidates: 候选行列表
        selected: 选中的行列表
        args: 命令行参数
    """
    # 统计分数分布
    score_counter = Counter(
        int(round(float(row["prefilter_score"]))) for row in candidates
    )
    # 统计类型分布
    type_counter = Counter(row["type"] for row in candidates)
    # 统计Tier分布
    tier_counter = Counter(row["prefilter_tier"] for row in candidates)
    # 统计概率分箱分布
    prob_bins = Counter()
    probability_values = [
        float(row.get("p_atomic", row["atomic_prior"])) for row in candidates
    ]
    # 从概率分布动态生成分箱边界
    dynamic_bins = miner.probability_bins_from_distribution(probability_values)
    # 统计每个分箱的候选数
    for row in candidates:
        p = float(row.get("p_atomic", row["atomic_prior"]))
        assigned = False
        for lower_bound, bucket_name in dynamic_bins:
            if p >= lower_bound:
                prob_bins[bucket_name] += 1
                assigned = True
                break
        if not assigned:
            # 未分配的分到最后一个分箱
            min_lower = dynamic_bins[-1][0] if dynamic_bins else 0.0
            fallback_bucket = f"[0.00,{min_lower:.2f})"
            prob_bins[fallback_bucket] += 1

    # 确定生效的门控参数
    effective_gate = args.min_prefilter_prob
    gate_source = (
        "fixed_from_args"
        if args.min_prefilter_prob > 0
        else "uncertainty_budget_median_entropy"
    )
    effective_tau_a = args.tau_a
    effective_tau_b = args.tau_b
    tier_source = "constraint_from_calibration_precision_or_input"
    # 如果有候选数据，从第一条候选获取实际生效的门控值
    if candidates:
        effective_gate = float(candidates[0].get("prefilter_gate_prob", effective_gate))
        gate_source = str(candidates[0].get("prefilter_gate_source", gate_source))
        effective_tau_a = float(candidates[0].get("prefilter_tau_a", effective_tau_a))
        effective_tau_b = float(candidates[0].get("prefilter_tau_b", effective_tau_b))
        tier_source = str(candidates[0].get("prefilter_tier_source", tier_source))

    # 构建摘要内容
    lines = [
        "# Full Step1 Message-Only Prefilter Summary",
        "",
        f"- Input dataset: `{args.input}`",
        f"- Minimum prefilter probability: `{effective_gate}` (`{gate_source}`)",
        f"- Tier thresholds: `tau_a={effective_tau_a}`, `tau_b={effective_tau_b}`",
        f"- Tier derivation source: `{tier_source}`",
        f"- Passing candidates: `{len(candidates)}`",
        f"- Top exported candidates: `{len(selected)}`",
        "",
        "## Tier Distribution",
        "",
    ]
    # 添加Tier分布
    for tier_name, count in sorted(tier_counter.items()):
        lines.append(f"- tier `{tier_name}`: {count}")

    # 添加概率分箱分布
    lines.extend(["", "## Atomic Probability Bins", ""])
    for bucket_name, count in prob_bins.items():
        lines.append(f"- `{bucket_name}`: {count}")

    # 添加分数分布
    lines.extend(["", "## Score Distribution", ""])
    for score, count in sorted(score_counter.items(), reverse=True):
        lines.append(f"- score `{score}`: {count}")
    # 添加类型分布
    lines.extend(["", "## Type Distribution", ""])
    for commit_type, count in type_counter.most_common():
        lines.append(f"- `{commit_type}`: {count}")
    # 添加Top示例
    lines.extend(["", "## Top Examples", ""])
    for row in selected[:DEFAULT_TOP_EXAMPLE_COUNT]:
        lines.append(
            f"- p_atomic `{row.get('p_atomic', row['atomic_prior'])}` | tier `{row['prefilter_tier']}` | score `{row['prefilter_score']}` | `{row['type']}` | `{row['subject']}` | `{row['sha']}`"
        )
    # 写入文件
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """
    主函数：执行预过滤

    流程：
    1. 加载全部提交
    2. 解析消息特征
    3. 计算原子性先验和Tier分类
    4. 写入候选CSV和摘要
    """
    # 解析命令行参数
    args = parse_args()
    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载校准文件（如果有）
    calibration = (
        miner.load_calibration(args.calibration_json) if args.calibration_json else None
    )
    # 解析阈值（从校准文件或命令行参数）
    tau_a, tau_b = resolve_prefilter_thresholds(
        calibration=calibration, tau_a=args.tau_a, tau_b=args.tau_b
    )
    # 更新args中的阈值
    args.tau_a = tau_a
    args.tau_b = tau_b

    # 加载输入数据
    rows = load_rows(Path(args.input))
    # 构建预过滤候选列表
    candidates = build_candidates(
        rows,
        min_prefilter_prob=args.min_prefilter_prob,
        tau_a=tau_a,
        tau_b=tau_b,
        calibration=calibration,
    )
    # 检查是否有通过的候选
    if not candidates:
        raise RuntimeError("prefilter produced zero passing candidates")
    # 截取目标数量的Top候选
    selected = candidates[: args.target_count]
    # 检查是否有选中候选
    if not selected:
        raise RuntimeError("prefilter top candidate export is empty")

    # 写入输出文件：所有候选和Top候选
    write_csv(output_dir / "all_prefilter_candidates.csv", candidates)
    write_csv(output_dir / "prefilter_top_candidates.csv", selected)
    # 写入摘要
    write_summary(output_dir / "summary.md", candidates, selected, args=args)

    # 打印摘要信息
    print(f"all_candidates={len(candidates)}")
    print(f"top_candidates={len(selected)}")
    print((output_dir / "all_prefilter_candidates.csv").as_posix())


if __name__ == "__main__":
    main()
