"""
预过滤批次选择脚本

本脚本将 message-only prefilter 与 select_batch 合并为单一阶段，
直接从原始 `prefilter_allcommits.csv` 中解析消息、可选计算
message-only prior/tier，并按类型选择分层批次。

功能：
- 从 raw allcommits 数据直接构建候选池
- 按类型分层抽样
- 可选计算 message-only prior/tier
- 可选的breaking变更排除
- 可选导出调试产物
- 随机打乱确保多样性
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

from src.pipeline import atomic_mining as miner
from src.pipeline import prefilter as prefilter


SUBSTANTIVE_TYPES = ["fix", "feat", "refactor", "test", "perf"]  # 实质性提交类型
HARD_BALANCE_TYPES = ["fix", "feat", "refactor", "test"]  # 硬均衡类型；perf 保留但不占硬配额
DEFAULT_PER_TYPE = 10  # 默认每类型数量
DEFAULT_AUDIT_TARGET = 300  # 默认审计目标大小（用于自动派生 per_type）
DEFAULT_SEED = 31  # 默认随机种子
DEFAULT_DEBUG_TOP_COUNT = 20000  # 默认调试 Top 候选数
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制
TIER_PRIORITY = {"A": 0, "B": 1, "C": 2, "": 3}
RATIO_EPS = 1e-9


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    # 输入文件路径参数
    parser.add_argument(
        "--input",
        default="../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
    )
    # 输出文件路径参数
    parser.add_argument(
        "--output",
        default="outputs/selection/selection_batch.csv",
    )
    # 每类型选择的数量参数
    parser.add_argument("--per-type", type=int, default=DEFAULT_PER_TYPE)
    parser.add_argument(
        "--audit-target",
        type=int,
        default=DEFAULT_AUDIT_TARGET,
        help="Audit target used when per-type=0 and the script derives a balanced count automatically.",
    )
    # 是否排除breaking变更参数
    parser.add_argument(
        "--exclude-breaking", action="store_true", help="排除breaking变更"
    )
    # 每类型偏移量参数（用于分页/跳过前面的样本）
    parser.add_argument("--offset-per-type", type=int, default=0, help="每类型偏移量")
    # 随机种子参数
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--prefer-high-tier",
        action="store_true",
        help="Select higher-tier rows first within each type before randomizing ties.",
    )
    parser.add_argument(
        "--proxy-calibration-json",
        default="",
        help="Optional message-only proxy calibration artifact used to compute prior/tier in-memory.",
    )
    parser.add_argument(
        "--calibration-json",
        default="",
        help="Deprecated alias of --proxy-calibration-json.",
    )
    parser.add_argument(
        "--min-prefilter-prob",
        type=float,
        default=0.0,
        help="Optional message-only gate threshold; 0 means derive automatically when prior computation is enabled.",
    )
    parser.add_argument("--tau-a", type=float, default=miner.DEFAULT_TAU_A)
    parser.add_argument("--tau-b", type=float, default=miner.DEFAULT_TAU_B)
    parser.add_argument(
        "--compute-message-only-prior",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When enabled, compute message-only prior/tier in memory before selection.",
    )
    parser.add_argument(
        "--dump-debug-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Optionally dump all_prefilter_candidates.csv and prefilter_top_candidates.csv for debugging.",
    )
    parser.add_argument(
        "--debug-top-count",
        type=int,
        default=DEFAULT_DEBUG_TOP_COUNT,
        help="Top-N size used when --dump-debug-artifacts is enabled.",
    )
    parser.add_argument(
        "--metrics-json",
        default="",
        help="Optional path to persist full selection metrics as JSON for the runner/analysis.",
    )
    return parser.parse_args()


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
    # 打开文件并使用DictReader解析为字典列表
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def derive_per_type_from_pool(
    *,
    per_type_arg: int,
    audit_target: int,
    substantive_type_counts: dict[str, int],
    observed_tier_a_ratio: float,
) -> int:
    """
    从当前候选池稳定派生每类型候选数。

    当 observed_tier_a_ratio 很低时，优先保证类型覆盖，退化为
    `min(audit_target, min_substantive_pool)`。
    """
    # 如果用户指定了per_type参数，直接返回
    if per_type_arg > 0:
        return per_type_arg
    # 计算所有实质性类型中的最小池大小
    min_pool = min(
        int(substantive_type_counts.get(commit_type, 0))
        for commit_type in HARD_BALANCE_TYPES
    )
    # 如果Tier A比例太低（几乎无高质量候选），优先保证类型覆盖
    if float(observed_tier_a_ratio) <= RATIO_EPS:
        return max(1, min(int(audit_target), min_pool))
    # 根据Tier A比例推导每类型需要的数量（高质量候选越多，每类型配额越少）
    required_candidates = int(
        (float(audit_target) / max(RATIO_EPS, float(observed_tier_a_ratio))) + 0.999999
    )
    # 向上取整分配到每类型
    return max(
        1, (required_candidates + len(HARD_BALANCE_TYPES) - 1) // len(HARD_BALANCE_TYPES)
    )


def build_subject_only_candidates(rows: list[dict]) -> list[dict]:
    """从 raw allcommits 行构建最小选择候选，不计算 prior/tier。"""
    candidates: list[dict] = []
    for row in rows:
        commit_type = str(row.get("type", "")).strip()
        if commit_type not in SUBSTANTIVE_TYPES:
            continue
        message_features = miner.parse_message(str(row.get("commit_message", "")))
        copied = dict(row)
        copied["subject"] = message_features["subject_line"]
        copied.setdefault("prefilter_tier", "")
        copied.setdefault("prefilter_score", "")
        copied.setdefault("p_raw", "")
        copied.setdefault("p_atomic", "")
        copied.setdefault("atomic_prior", "")
        copied.setdefault("atomic_prior_calibrated", "")
        copied.setdefault("prefilter_reasons", "")
        copied.setdefault("prefilter_gate_prob", "")
        copied.setdefault("prefilter_gate_source", "")
        copied.setdefault("prefilter_tau_a", "")
        copied.setdefault("prefilter_tau_b", "")
        candidates.append(copied)
    return candidates


def prepare_selection_pool(
    *,
    rows: list[dict],
    calibration: dict | None,
    min_prefilter_prob: float,
    tau_a: float | None,
    tau_b: float | None,
    compute_message_only_prior: bool,
) -> tuple[list[dict], dict[str, object]]:
    """构建用于类型均衡抽样的 substantive 候选池及其统计。"""
    if compute_message_only_prior:
        resolved_tau_a, resolved_tau_b = prefilter.resolve_prefilter_thresholds(
            calibration=calibration,
            tau_a=tau_a,
            tau_b=tau_b,
        )
        candidates = prefilter.build_candidates(
            rows=rows,
            min_prefilter_prob=min_prefilter_prob,
            tau_a=resolved_tau_a,
            tau_b=resolved_tau_b,
            calibration=calibration,
        )
        candidates = [
            row
            for row in candidates
            if str(row.get("type", "")).strip() in SUBSTANTIVE_TYPES
        ]
    else:
        candidates = build_subject_only_candidates(rows)

    substantive_type_counts = {
        commit_type: sum(
            1 for row in candidates if str(row.get("type", "")).strip() == commit_type
        )
        for commit_type in SUBSTANTIVE_TYPES
    }
    tier_a_count = sum(
        1 for row in candidates if str(row.get("prefilter_tier", "")).strip() == "A"
    )
    observed_tier_a_ratio = tier_a_count / len(candidates) if candidates else 0.0
    metrics: dict[str, object] = {
        "all_candidates": len(candidates),
        "substantive_type_counts": substantive_type_counts,
        "min_substantive_pool": min(substantive_type_counts.values())
        if substantive_type_counts
        else 0,
        "tier_a_count": tier_a_count,
        "observed_tier_a_ratio": round(observed_tier_a_ratio, 6),
        "compute_message_only_prior": bool(compute_message_only_prior),
    }
    return candidates, metrics


def is_breaking(subject: str) -> bool:
    """
    判断subject是否为breaking变更

    Breaking变更的标识：
    - 格式: type!: 或 type(scope)!:
    - 具体类型: feat!:, fix!:, refactor!:, perf!:, test!:

    参数:
        subject: 提交消息的subject行

    返回:
        bool: 是否为breaking变更
    """
    # 提取subject的第一个单词（到第一个空格为止）
    # 例如 "feat!: add login" -> "feat!:"
    first_word = subject.split(" ", 1)[0]
    # 检查是否包含 "!:"（Conventional Commit的breaking变更标记）
    if "!:" in first_word:
        return True
    # 检查常见breaking类型前缀（更严格的检查）
    return (
        subject.startswith("feat!:")
        or subject.startswith("fix!:")
        or subject.startswith("refactor!:")
        or subject.startswith("perf!:")
        or subject.startswith("test!:")
    )


def select_rows(
    rows: list[dict],
    per_type: int,
    exclude_breaking: bool,
    offset_per_type: int,
    seed: int,
    prefer_high_tier: bool = False,
) -> list[dict]:
    """
    选择分层批次

    从预过滤候选中选择分层批次，确保每种实质性类型都有相同样本数。
    流程：
    1. 按提交类型分组
    2. 可选排除breaking变更
    3. 可选应用偏移量（用于分页）
    4. 随机打乱
    5. 每类型选取per_type个

    参数:
        rows: 输入的候选行列表
        per_type: 每类型选择的数量
        exclude_breaking: 是否排除breaking变更
        offset_per_type: 每类型的偏移量（用于分页/跳过前面的样本）
        seed: 随机种子（保证可复现性）

    返回:
        list[dict]: 选中的行列表
    """
    # 步骤1: 按类型分组，创建类型到行列表的映射
    by_type: dict[str, list[dict]] = {
        commit_type: [] for commit_type in HARD_BALANCE_TYPES
    }
    # 遍历所有行，按类型分组
    for row in rows:
        commit_type = row["type"]
        # 跳过非实质性类型
        if commit_type not in HARD_BALANCE_TYPES:
            continue
        # 如果需要排除breaking变更，跳过
        if exclude_breaking and is_breaking(row["subject"]):
            continue
        # 将行添加到对应类型的列表
        by_type[commit_type].append(row)

    # 步骤2: 为每个类型创建随机选择器
    rng = random.Random(seed)
    picked: list[dict] = []  # 选中的行列表

    # 遍历每种实质性类型
    for index, commit_type in enumerate(HARD_BALANCE_TYPES):
        # 获取该类型的行列表
        bucket = list(by_type.get(commit_type, []))
        # 为每种类型创建独立的随机器（使用不同种子保证多样性）
        rng_type = random.Random(seed + index)
        if prefer_high_tier:
            tier_groups: dict[str, list[dict]] = {"A": [], "B": [], "C": [], "": []}
            for item in bucket:
                tier_groups.setdefault(
                    str(item.get("prefilter_tier", "")).strip(), []
                ).append(item)
            bucket = []
            for tier_name in ["A", "B", "C", ""]:
                tier_bucket = list(tier_groups.get(tier_name, []))
                rng_type.shuffle(tier_bucket)
                bucket.extend(tier_bucket)
        else:
            rng_type.shuffle(bucket)
        # 计算需要的数量：偏移量 + 每类型数量
        required = offset_per_type + per_type
        # 如果该类型的行数不足要求的数量，跳过
        if len(bucket) < required:
            continue
        # 选取从offset开始的per_type个样本
        selected_slice = bucket[offset_per_type : offset_per_type + per_type]
        picked.extend(selected_slice)

    # 步骤3: 最终打乱所有选中的行
    rng.shuffle(picked)
    return picked


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
    # 打开文件并写入CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        # 使用第一行的键作为列名
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()  # 写入表头
        writer.writerows(rows)  # 写入数据行


def write_json(path: Path, payload: dict[str, object]) -> None:
    """写入JSON文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_selection_stage(
    *,
    input_path: Path,
    output_path: Path,
    per_type: int,
    audit_target: int,
    seed: int,
    calibration_json: str = "",
    min_prefilter_prob: float = 0.0,
    tau_a: float | None = None,
    tau_b: float | None = None,
    compute_message_only_prior: bool = True,
    dump_debug_artifacts: bool = False,
    debug_top_count: int = DEFAULT_DEBUG_TOP_COUNT,
    metrics_json_path: Path | None = None,
    exclude_breaking: bool = False,
    offset_per_type: int = 0,
    prefer_high_tier: bool = False,
) -> dict[str, object]:
    """合并 prefilter + select_batch 的主执行入口。"""
    rows = load_rows(input_path)
    calibration = miner.load_calibration(calibration_json) if calibration_json else None
    candidates, pool_metrics = prepare_selection_pool(
        rows=rows,
        calibration=calibration,
        min_prefilter_prob=min_prefilter_prob,
        tau_a=tau_a,
        tau_b=tau_b,
        compute_message_only_prior=compute_message_only_prior,
    )
    if not candidates:
        raise RuntimeError(
            "combined selection stage produced zero substantive candidates"
        )

    effective_per_type = derive_per_type_from_pool(
        per_type_arg=per_type,
        audit_target=audit_target,
        substantive_type_counts=dict(pool_metrics.get("substantive_type_counts", {})),
        observed_tier_a_ratio=float(pool_metrics.get("observed_tier_a_ratio", 0.0)),
    )
    selected = select_rows(
        candidates,
        per_type=effective_per_type,
        exclude_breaking=exclude_breaking,
        offset_per_type=offset_per_type,
        seed=seed,
        prefer_high_tier=prefer_high_tier and compute_message_only_prior,
    )
    expected_total = effective_per_type * len(HARD_BALANCE_TYPES)
    if len(selected) < expected_total:
        raise RuntimeError(
            f"insufficient stratified rows: expected {expected_total}, got {len(selected)}; "
            "increase candidate pool or reduce per-type target"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, selected)

    debug_top_candidates = 0
    if dump_debug_artifacts:
        write_csv(output_path.parent / "all_prefilter_candidates.csv", candidates)
        top_rows = candidates[: min(int(debug_top_count), len(candidates))]
        write_csv(output_path.parent / "prefilter_top_candidates.csv", top_rows)
        debug_top_candidates = len(top_rows)

    type_counter = dict(Counter(row.get("type", "") for row in selected))
    metrics = {
        **pool_metrics,
        "selection_model_mode": "message_only" if compute_message_only_prior else "",
        "selection_model_role": "proxy" if compute_message_only_prior else "",
        "selected": len(selected),
        "per_type": effective_per_type,
        "type_distribution": type_counter,
        "debug_artifacts_written": bool(dump_debug_artifacts),
        "debug_top_candidates": debug_top_candidates,
        "output_csv": output_path.as_posix(),
    }
    if metrics_json_path is not None:
        write_json(metrics_json_path, metrics)
    return metrics


def main() -> None:
    """
    主函数：执行预过滤批次选择

    流程：
    1. 解析命令行参数
    2. 加载预过滤候选数据
    3. 执行分层选择
    4. 验证并写入输出
    """
    args = parse_args()
    proxy_calibration_json = args.proxy_calibration_json or args.calibration_json
    if args.calibration_json:
        print(
            "[deprecation] --calibration-json is deprecated; use --proxy-calibration-json",
            flush=True,
        )
    metrics = run_selection_stage(
        input_path=Path(args.input),
        output_path=Path(args.output),
        per_type=args.per_type,
        audit_target=args.audit_target,
        seed=args.seed,
        calibration_json=proxy_calibration_json,
        min_prefilter_prob=args.min_prefilter_prob,
        tau_a=args.tau_a,
        tau_b=args.tau_b,
        compute_message_only_prior=bool(args.compute_message_only_prior),
        dump_debug_artifacts=bool(args.dump_debug_artifacts),
        debug_top_count=args.debug_top_count,
        metrics_json_path=Path(args.metrics_json) if args.metrics_json else None,
        exclude_breaking=bool(args.exclude_breaking),
        offset_per_type=args.offset_per_type,
        prefer_high_tier=bool(args.prefer_high_tier),
    )
    print(f"all_candidates={metrics['all_candidates']}")
    print(f"selected={metrics['selected']}")
    print(f"per_type={metrics['per_type']}")
    print(Path(args.output).as_posix())


if __name__ == "__main__":
    main()
