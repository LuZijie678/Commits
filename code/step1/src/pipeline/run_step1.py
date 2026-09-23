"""
Step1 完整实验流水线运行脚本

本脚本实现了 Step1 实验的端到端流水线，当前真实阶段为：
1. 校准（Calibration）：拟合 full-diff / message-only 两类校准工件
2. 合并筛选（Combined Prefilter + Select）：从 raw allcommits 直接完成 message-only 评分与类型均衡抽样
3. 增强（Enrich）：解析 GitHub 仓库并补齐完整 diff 信息
4. 验证（Validate）：基于候选池生成 review / audit 产物

特性：
- 严格阶段门控：每个阶段输出都经过质量检查
- 可恢复增强：支持断点续传
- 流式日志：实时输出日志到控制台和文件
"""

import argparse
import csv
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.labeling import agreement as annotation_agreement
from src.analysis import diagnostics as analysis_diagnostics
from src.analysis import main_results as analysis_main_results
from src.analysis import strategy_compare as analysis_strategy_compare
from src.pipeline import atomic_mining as miner
import src.data_splitting.annotated_split_protocol as annotated_split_protocol
from src.pipeline.validation import evaluate_audit_sample_alignment


DEFAULT_RUN_NAME = "full_step1_run"  # 默认运行名称
DEFAULT_BASE_OUTPUT_DIR = "outputs"  # 默认输出目录
DEFAULT_PREFILTER_TARGET_COUNT = 20000  # 调试导出的 Top 候选数量
DEFAULT_PER_TYPE = 0  # 每类型候选数（0表示自动派生）
DEFAULT_MAX_CANDIDATES = 0  # 最大候选数（0表示使用完整批次）
DEFAULT_SAMPLE_PER_TIER = 30  # 每层采样数
DEFAULT_AUDIT_SIZE = 300  # 审计样本大小
DEFAULT_RANDOM_SEED = 31  # 随机种子
DEFAULT_STOP_AFTER = "validate"  # 默认运行到验证阶段
# `prefilter` 保留为 legacy alias；当前真实阶段边界对应合并后的 `select_batch`。
VALID_STOP_AFTER = ("calibration", "prefilter", "select_batch", "enrich", "validate")
# 实质性提交类型：包含实际代码变更的类型
SUBSTANTIVE_TYPES = ("fix", "feat", "refactor", "test", "perf")
HARD_BALANCE_TYPES = ("fix", "feat", "refactor", "test")
AUDIT_SIZE_MIN = 300  # 审计大小最小值
AUDIT_SIZE_MAX = 500  # 审计大小最大值
DEFAULT_MIN_RESOLVED_RATIO = 0.0  # 默认最小解析比例
DEFAULT_MIN_DIFF_RATIO = 1.00  # 默认最小diff比例
DEFAULT_ENRICH_MAX_RETRIES = 3  # 默认最大重试次数
DEFAULT_ENRICH_PROGRESS_EVERY = 10  # 默认进度输出间隔
DEFAULT_ENRICH_CHECKPOINT_INTERVAL = 10  # 默认检查点间隔
DEFAULT_ENRICH_SEARCH_SLEEP_SECONDS = 1.0  # 默认搜索休眠秒数
DEFAULT_ENRICH_RETRY_ON_429 = 4  # 默认429重试次数
DEFAULT_CALIBRATION_SCHEME = "holdout"  # 默认校准方案
DEFAULT_CALIBRATION_HOLDOUT_RATIO = 0.20  # 默认校准留出比例
DEFAULT_CALIBRATION_CV_FOLDS = 5  # 默认交叉验证折数
DEFAULT_THRESHOLD_FALLBACK_POLICY = "error"  # 默认阈值回退策略
DEFAULT_SELECTION_STRATEGIES = "rule_only,model_only,model_rule_refilter"
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制
RATIO_EPS = 1e-6  # 比例epsilon
REPO_OVERLAP_POLICIES = ("error", "allow_frozen_stats")


def utc_ts() -> str:
    """
    获取当前UTC时间戳字符串

    格式: YYYYMMDDTHHMMSSZ（例如: 20260407T130500Z）

    返回:
        str: UTC时间戳字符串
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clamp_audit_size(value: int) -> int:
    """
    限制审计大小在有效范围内

    将审计大小裁剪到[300, 500]范围内。

    参数:
        value: 原始审计大小

    返回:
        int: 裁剪后的审计大小
    """
    return max(AUDIT_SIZE_MIN, min(AUDIT_SIZE_MAX, int(value)))


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数

    参数说明：
    --run-name: 运行名称，用于输出目录命名
    --run-ts: 显式指定运行时间戳
    --base-output-dir: 基础输出目录
    --allcommits: 全部提交数据路径
    --annotated: 标注数据集路径
    --repo-list: 仓库列表路径
    --label-col: 标签列名（默认为is_single_intent）
    --min-prefilter-prob: 合并筛选阶段的 message-only 最小概率门控
    --prefilter-target-count: 调试导出的 Top 候选数量
    --per-type: 每类型候选数（0表示自动派生）
    --max-candidates: 最大候选数
    --min-atomic-prior: 最小原子性先验
    --sample-per-tier: 每层采样数
    --audit-size: 审计样本大小
    --seed: 随机种子
    --fetch-diff: 是否获取diff
    --min-resolved-ratio: 最小解析比例
    --min-diff-ratio: 最小diff比例
    --enrich-*: 增强阶段相关参数
    --calibration-*: 校准阶段相关参数
    --strict-gates: 是否启用严格阶段门控
    --require-enrich-complete: 是否要求增强完成
    --require-audit-completion: 是否要求审计完成
    --stop-after: 运行到指定阶段后停止
    """
    # 创建参数解析器
    parser = argparse.ArgumentParser(
        description="Run Step1 full pipeline with strict stage gates, resumable enrich, and streaming logs."
    )
    # 运行名称
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    # 可选的运行时间戳后缀
    parser.add_argument(
        "--run-ts",
        default="",
        help="Optional explicit run timestamp suffix, e.g. 20260407T130500Z",
    )
    # 基础输出目录
    parser.add_argument("--base-output-dir", default=DEFAULT_BASE_OUTPUT_DIR)
    # 全部提交数据路径
    parser.add_argument(
        "--allcommits",
        default="../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv",
    )
    # 标注数据集路径
    parser.add_argument(
        "--annotated",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    # 仓库列表路径
    parser.add_argument(
        "--repo-list",
        default="../../datasets/step1/runtime_support/resolved_metadata.csv",
    )
    # 标签列名
    parser.add_argument("--label-col", default="is_single_intent")
    parser.add_argument(
        "--annotation-overlap-a-csv",
        default="../../datasets/step1/review/annotated_overlap_annotator_a.csv",
    )
    parser.add_argument(
        "--annotation-overlap-b-csv",
        default="../../datasets/step1/review/annotated_overlap_annotator_b.csv",
    )
    parser.add_argument("--annotated-split-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--protocol-min-total", type=int, default=40)
    parser.add_argument("--protocol-min-positive", type=int, default=15)
    parser.add_argument("--protocol-min-negative", type=int, default=15)
    parser.add_argument("--protocol-min-repos", type=int, default=5)
    parser.add_argument("--gbdt-train-min-total", type=int, default=120)
    parser.add_argument("--gbdt-train-min-positive", type=int, default=40)
    parser.add_argument("--gbdt-train-min-negative", type=int, default=40)
    parser.add_argument("--gbdt-train-min-repos", type=int, default=10)
    parser.add_argument("--calibration-min-total", type=int, default=60)
    parser.add_argument("--calibration-min-positive", type=int, default=20)
    parser.add_argument("--calibration-min-negative", type=int, default=20)
    parser.add_argument("--calibration-min-repos", type=int, default=5)
    parser.add_argument("--evaluation-min-total", type=int, default=60)
    parser.add_argument("--evaluation-min-positive", type=int, default=20)
    parser.add_argument("--evaluation-min-negative", type=int, default=20)
    parser.add_argument("--evaluation-min-repos", type=int, default=5)
    parser.add_argument("--proxy-gap-min-total", type=int, default=60)
    parser.add_argument("--proxy-gap-min-positive", type=int, default=20)
    parser.add_argument("--proxy-gap-min-negative", type=int, default=20)
    parser.add_argument("--proxy-gap-min-repos", type=int, default=5)
    # 预过滤最小概率
    parser.add_argument("--min-prefilter-prob", type=float, default=0.0)
    # 调试导出的Top候选数量
    parser.add_argument(
        "--prefilter-target-count", type=int, default=DEFAULT_PREFILTER_TARGET_COUNT
    )
    parser.add_argument(
        "--dump-debug-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Dump optional debug artifacts such as all_prefilter_candidates.csv and prefilter_top_candidates.csv.",
    )
    # 每类型候选数（0表示自动派生）
    parser.add_argument(
        "--per-type",
        type=int,
        default=DEFAULT_PER_TYPE,
        help="Per-type candidate count for the merged prefilter/select stage. Use 0 to derive automatically from audit constraints.",
    )
    # 最大候选数
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help="Max candidates for enrich. Use 0 to consume full stratified batch.",
    )
    # 最小原子性先验
    parser.add_argument("--min-atomic-prior", type=float, default=0.0)
    # 每层采样数
    parser.add_argument("--sample-per-tier", type=int, default=DEFAULT_SAMPLE_PER_TIER)
    # 审计样本大小
    parser.add_argument("--audit-size", type=int, default=DEFAULT_AUDIT_SIZE)
    # 随机种子
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    # 是否获取diff
    parser.add_argument("--fetch-diff", action="store_true")
    # 最小解析比例
    parser.add_argument(
        "--min-resolved-ratio",
        type=float,
        default=DEFAULT_MIN_RESOLVED_RATIO,
        help="Minimum resolved ratio gate. Use 0 to derive from audit coverage constraint (audit_size/max_candidates).",
    )
    # 最小diff比例
    parser.add_argument("--min-diff-ratio", type=float, default=DEFAULT_MIN_DIFF_RATIO)
    # 增强最大重试次数
    parser.add_argument(
        "--enrich-max-retries", type=int, default=DEFAULT_ENRICH_MAX_RETRIES
    )
    # 增强进度输出间隔
    parser.add_argument(
        "--enrich-progress-every", type=int, default=DEFAULT_ENRICH_PROGRESS_EVERY
    )
    # 增强检查点间隔
    parser.add_argument(
        "--enrich-checkpoint-interval",
        type=int,
        default=DEFAULT_ENRICH_CHECKPOINT_INTERVAL,
    )
    # 增强搜索休眠秒数
    parser.add_argument(
        "--enrich-search-sleep-seconds",
        type=float,
        default=DEFAULT_ENRICH_SEARCH_SLEEP_SECONDS,
    )
    # 增强429重试次数
    parser.add_argument(
        "--enrich-retry-on-429", type=int, default=DEFAULT_ENRICH_RETRY_ON_429
    )
    # 校准方案
    parser.add_argument(
        "--calibration-scheme",
        choices=["holdout", "cv"],
        default=DEFAULT_CALIBRATION_SCHEME,
        help="Labeled calibration scheme used by src.pipeline.full_diff_calibration.",
    )
    # 校准留出比例
    parser.add_argument(
        "--calibration-holdout-ratio",
        type=float,
        default=DEFAULT_CALIBRATION_HOLDOUT_RATIO,
    )
    # 交叉验证折数
    parser.add_argument(
        "--calibration-cv-folds",
        type=int,
        default=DEFAULT_CALIBRATION_CV_FOLDS,
    )
    # 阈值回退策略
    parser.add_argument(
        "--threshold-fallback-policy",
        choices=["error"],
        default=DEFAULT_THRESHOLD_FALLBACK_POLICY,
        help="Strict policy: fail when precision-constrained tau selection falls back.",
    )
    # 可复用的校准JSON
    parser.add_argument(
        "--reuse-proxy-calibration-json",
        default="",
        help="Optional existing message-only proxy calibration json path.",
    )
    parser.add_argument(
        "--reuse-primary-calibration-json",
        default="",
        help="Optional existing full-diff primary calibration json path.",
    )
    parser.add_argument(
        "--reuse-calibration-json",
        default="",
        help="Deprecated alias of --reuse-proxy-calibration-json.",
    )
    parser.add_argument(
        "--reuse-full-diff-calibration-json",
        default="",
        help="Deprecated alias of --reuse-primary-calibration-json.",
    )
    # 是否启用严格阶段门控
    parser.add_argument(
        "--strict-gates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable hard stage gates; fail fast when data quality constraints are not satisfied.",
    )
    parser.add_argument(
        "--repo-overlap-policy",
        choices=list(REPO_OVERLAP_POLICIES),
        default="error",
        help="Policy for annotated/allcommits repo overlap. `error` enforces strict repo-disjoint splits; `allow_frozen_stats` records overlap and relies on frozen training-side stats.",
    )
    # 是否要求增强完成
    parser.add_argument(
        "--require-enrich-complete",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require enrich stage to process all requested candidates.",
    )
    # 是否要求审计完成
    parser.add_argument(
        "--require-audit-completion",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require a labeled audit csv to be fully completed after validate.",
    )
    parser.add_argument(
        "--run-audit-sample-export",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether validate stage should export review/audit sample artifacts.",
    )
    parser.add_argument(
        "--run-proxy-gap-analysis",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run proxy-gap analysis stage; disable for fast strategy-only batches.",
    )
    parser.add_argument(
        "--selection-strategies",
        default=DEFAULT_SELECTION_STRATEGIES,
        help="Comma-separated strategies, e.g. rule_only,model_only,model_rule_refilter",
    )
    parser.add_argument(
        "--strategy-target-count",
        type=int,
        default=0,
        help="Optional per-strategy selected-count cap (0 means no cap).",
    )
    # 审计标注CSV路径
    parser.add_argument(
        "--audit-labeled-csv",
        default="",
        help="Optional labeled audit csv path for completion check.",
    )
    # UTC参考时间戳
    parser.add_argument(
        "--reference-time-utc",
        default="",
        help="Optional UTC reference timestamp (ISO8601) for repo activity filtering reproducibility.",
    )
    # 运行到指定阶段后停止
    parser.add_argument(
        "--stop-after",
        choices=list(VALID_STOP_AFTER),
        default=DEFAULT_STOP_AFTER,
        help="Run pipeline up to this stage (inclusive). `prefilter` is kept as a legacy alias for the merged prefilter/select stage.",
    )
    return parser.parse_args()


def run_cmd_stream(command: list[str], cwd: Path, log_path: Path) -> None:
    """
    运行命令并实时输出日志

    使用子进程运行命令，将stdout和stderr重定向到日志文件，
    同时实时输出到控制台。

    参数:
        command: 命令列表
        cwd: 工作目录
        log_path: 日志文件路径

    异常:
        RuntimeError: 命令退出码非0时抛出
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write(f"$ {' '.join(command)}\n\n")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log_handle.write(line)
        process.stdout.close()
        exit_code = process.wait()
        log_handle.write(f"\n## EXIT_CODE={exit_code}\n")
    if exit_code != 0:
        raise RuntimeError(f"command failed (exit {exit_code}): {' '.join(command)}")


def load_json(path: Path) -> dict:
    """
    加载JSON文件

    参数:
        path: JSON文件路径

    返回:
        dict: 解析后的字典
    """
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv_rows(path: Path) -> list[dict]:
    """
    加载CSV文件为字典列表

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表
    """
    # 空文件或不存在则返回空列表
    if not path.exists() or path.stat().st_size == 0:
        return []
    # 设置CSV字段大小限制
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 读取并解析CSV
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def derive_per_type(
    per_type_arg: int,
    audit_target: int,
    observed_tier_a_ratio: float,
) -> int:
    """
    派生每类型候选数量

    基于审计目标大小和观察到的Tier A比例，自动计算每类型应选取的候选数。

    计算公式: per_type = ceil(audit_target / (observed_tier_a_ratio * len(types)))

    参数:
        per_type_arg: 用户指定的每类型候选数（如果>0则直接返回）
        audit_target: 审计目标大小
        observed_tier_a_ratio: 观察到的Tier A比例

    返回:
        int: 派生后的每类型候选数
    """
    # 如果用户指定了值，直接使用
    if per_type_arg > 0:
        return per_type_arg
    # 有效产出率（防止除零）
    effective_yield = max(RATIO_EPS, float(observed_tier_a_ratio))
    # 需要的候选总数
    required_candidates = math.ceil(audit_target / effective_yield)
    # 每类型候选数 = 总候选数 / 类型数
    return max(1, math.ceil(required_candidates / len(HARD_BALANCE_TYPES)))


def is_message_only_calibration_artifact(data: dict | None) -> bool:
    """判断校准工件是否为 message-only 路径。"""
    return miner.is_message_only_calibration(data)


def derive_per_type_from_pool(
    *,
    per_type_arg: int,
    audit_target: int,
    substantive_type_counts: dict[str, int],
    observed_tier_a_ratio: float,
) -> int:
    """
    从合并筛选阶段的 substantive 候选池稳定派生每类型候选数。

    message-only 稳定方案不再依赖 `tier_a_ratio` 自动放大样本数。
    当 calibration 工件是 message-only 且 `Tier A = 0` 时，
    直接按 audit target 与最小实质性类型池大小共同约束 `per_type`。
    """
    if per_type_arg > 0:
        return per_type_arg
    if float(observed_tier_a_ratio) <= RATIO_EPS:
        min_pool = min(int(substantive_type_counts.get(commit_type, 0)) for commit_type in HARD_BALANCE_TYPES)
        return max(1, min(int(audit_target), min_pool))
    return derive_per_type(
        per_type_arg=0,
        audit_target=audit_target,
        observed_tier_a_ratio=observed_tier_a_ratio,
    )


def resolve_validate_audit_tier() -> str:
    """当前官方实验路线固定主审计 Tier-A。"""
    return "A"


def resolve_validate_threshold_mode() -> str:
    """当前官方实验路线固定使用 full-diff 概率链分 Tier。"""
    return "full_diff"


def derive_min_resolved_ratio(
    min_resolved_ratio_arg: float, audit_target: int, expected_total: int
) -> tuple[float, str]:
    """
    派生最小解析比例

    如果用户未指定，则基于审计覆盖率约束自动派生。

    参数:
        min_resolved_ratio_arg: 用户指定的最小解析比例
        audit_target: 审计目标大小
        expected_total: 预期总数

    返回:
        tuple[float, str]: (解析比例, 来源说明)
    """
    # 用户指定则直接使用
    if min_resolved_ratio_arg > 0.0:
        return float(min_resolved_ratio_arg), "fixed_from_args"
    # 预期总数无效时直接报错，避免静默回退。
    if expected_total <= 0:
        raise ValueError(
            f"expected_total must be positive for resolved-ratio derivation, got {expected_total}"
        )
    # 基于审计覆盖率约束派生
    return min(
        1.0, max(0.0, float(audit_target) / float(expected_total))
    ), "constraint_audit_coverage"


def ensure(condition: bool, message: str) -> None:
    """
    确保条件满足，否则抛出异常（严格模式）

    参数:
        condition: 条件
        message: 错误消息
    """
    if not condition:
        raise RuntimeError(message)


def enforce(condition: bool, message: str, strict: bool) -> None:
    """
    强制执行条件检查

    在严格模式下，不满足条件会抛出异常；
    在宽松模式下，只打印警告。

    参数:
        condition: 条件
        message: 错误/警告消息
        strict: 是否严格模式
    """
    if condition:
        return
    if strict:
        raise RuntimeError(message)
    print(f"[gate warn] {message}", flush=True)


def check_calibration(
    calibration_json: Path, strict: bool, expected_artifact: str = "message_only"
) -> dict:
    """
    检查校准输出质量

    验证校准阶段生成的JSON文件是否包含所有必要组件。

    参数:
        calibration_json: 校准JSON文件路径
        strict: 是否严格模式（严格模式下不满足条件会抛出异常）
        expected_artifact: 期望的工件类型：`message_only` 或 `full_diff`

    返回:
        dict: 校准检查结果，包含tau_a, tau_b, feature_count等
    """
    enforce(
        calibration_json.exists(),
        f"missing calibration file: {calibration_json.as_posix()}",
        strict=strict,
    )
    if not calibration_json.exists():
        return {"exists": False}
    data = load_json(calibration_json)
    thresholds = data.get("thresholds") or {}
    tau_a = float(thresholds.get("tau_a", -1.0))
    tau_b = float(thresholds.get("tau_b", -1.0))
    calibration_mode = str(
        ((data.get("fit_config") or {}).get("mode", "")) if isinstance(data.get("fit_config"), dict) else ""
    )
    model_mode = miner.calibration_model_mode(data)
    model_role = miner.calibration_model_role(data)
    is_message_only = model_mode == "message_only"
    has_model = bool(data.get("model_pickle_b64"))
    has_features = (
        isinstance(data.get("feature_order"), list) and len(data["feature_order"]) > 0
    )
    signal_context = data.get("signal_context")
    has_signal_context = isinstance(signal_context, dict) and isinstance(
        signal_context.get("weights"), dict
    )
    message_protocol = data.get("message_protocol")
    has_message_protocol = (
        isinstance(message_protocol, dict) and "subject_len_min" in message_protocol
    )
    scope_protocol = data.get("scope_protocol")
    has_scope_protocol = (
        isinstance(scope_protocol, dict) and "file_scope_small_max" in scope_protocol
    )
    type_protocol = data.get("type_protocol")
    has_type_protocol = isinstance(type_protocol, dict) and isinstance(
        type_protocol.get("values"), dict
    )
    feature_norm_stats = data.get("feature_norm_stats")
    has_feature_norm_stats = (
        isinstance(feature_norm_stats, dict)
        and isinstance(feature_norm_stats.get("global"), dict)
        and "changed_lines" in feature_norm_stats.get("global", {})
        and "module_count" in feature_norm_stats.get("global", {})
    )
    epistemic_reference = data.get("epistemic_reference")
    has_epistemic_reference = (
        isinstance(epistemic_reference, dict)
        and "center" in epistemic_reference
        and "scale" in epistemic_reference
    )
    selection_reports = thresholds.get("selection_reports")
    has_reports = (
        isinstance(selection_reports, dict)
        and "tau_a" in selection_reports
        and "tau_b" in selection_reports
    )
    fallback_used = False
    if has_reports:
        fallback_used = any(
            bool((report or {}).get("used_fallback"))
            for report in selection_reports.values()
        )
    metrics = data.get("metrics") or {}
    protocol_violation = bool(metrics.get("protocol_violation"))
    repo_disjoint_eval = metrics.get("repo_disjoint_eval")
    threshold_source = str(thresholds.get("source", ""))
    enforce(0.0 < tau_b < tau_a < 1.0, "calibration thresholds invalid", strict=strict)
    if expected_artifact == "message_only":
        enforce(
            is_message_only,
            "run_full_step1_experiment requires a message-only calibration artifact",
            strict=strict,
        )
    elif expected_artifact == "full_diff":
        enforce(
            not is_message_only,
            "run_full_step1_experiment requires a full-diff calibration artifact",
            strict=strict,
        )
        enforce(
            has_model,
            "full-diff calibration missing serialized model",
            strict=strict,
        )
        enforce(
            has_features,
            "full-diff calibration missing feature_order",
            strict=strict,
        )
        enforce(
            has_feature_norm_stats,
            "full-diff calibration missing feature_norm_stats",
            strict=strict,
        )
    else:
        raise ValueError(f"unknown expected_artifact: {expected_artifact}")
    enforce(
        has_signal_context,
        "calibration missing signal_context for non-transductive prior",
        strict=strict,
    )
    enforce(
        has_message_protocol,
        "calibration missing message_protocol for dynamic message boundaries",
        strict=strict,
    )
    enforce(
        has_scope_protocol,
        "calibration missing scope_protocol for dynamic structural boundaries",
        strict=strict,
    )
    enforce(
        has_type_protocol,
        "calibration missing type_protocol for dynamic commit-type priors",
        strict=strict,
    )
    enforce(
        has_epistemic_reference,
        "calibration missing epistemic uncertainty reference",
        strict=strict,
    )
    enforce(
        has_reports,
        "calibration thresholds missing explicit selection_reports disclosure",
        strict=strict,
    )
    enforce(not fallback_used, "calibration threshold fallback detected", strict=strict)
    enforce(
        not protocol_violation,
        "calibration artifact reports protocol_violation=true",
        strict=strict,
    )
    if expected_artifact == "message_only" and repo_disjoint_eval is not None:
        enforce(
            bool(repo_disjoint_eval),
            "message-only calibration artifact is not repo-disjoint between calibration/evaluation splits",
            strict=strict,
        )
    return {
        "tau_a": tau_a,
        "tau_b": tau_b,
        "feature_count": len(data.get("feature_order", [])),
        "threshold_source": threshold_source,
        "threshold_fallback_used": fallback_used,
        "calibration_mode": calibration_mode,
        "is_message_only": is_message_only,
        "model_mode": model_mode,
        "model_role": model_role,
        "repo_disjoint_eval": repo_disjoint_eval,
        "protocol_violation": protocol_violation,
    }


def load_sha_set(path: Path) -> set[str]:
    """从CSV加载 SHA 集合。"""
    rows = load_csv_rows(path)
    return {
        sha
        for sha in (str(row.get("sha", "")).strip() for row in rows)
        if sha
    }


def load_repo_set(path: Path) -> set[str]:
    """从CSV加载 repo 集合。"""
    rows = load_csv_rows(path)
    repos: set[str] = set()
    for row in rows:
        repo = (
            str(row.get("repo", "")).strip()
            or str(row.get("resolved_repo", "")).strip()
            or miner.extract_repo(str(row.get("commit_url", "")))
        )
        if repo:
            repos.add(repo)
    return repos


def collect_input_split_metadata(annotated_csv: Path, allcommits_csv: Path) -> dict:
    """收集 annotated / allcommits 的 SHA 与 repo 级 split metadata。"""
    annotated_shas = load_sha_set(annotated_csv)
    allcommits_shas = load_sha_set(allcommits_csv)
    annotated_repos = load_repo_set(annotated_csv)
    allcommits_repos = load_repo_set(allcommits_csv)
    overlap_shas = sorted(annotated_shas & allcommits_shas)
    overlap_repos = sorted(annotated_repos & allcommits_repos)
    return {
        "annotated_csv": annotated_csv.as_posix(),
        "allcommits_csv": allcommits_csv.as_posix(),
        "annotated_sha_count": len(annotated_shas),
        "allcommits_sha_count": len(allcommits_shas),
        "overlap_sha_count": len(overlap_shas),
        "overlap_sha_examples": overlap_shas[:10],
        "annotated_repo_count": len(annotated_repos),
        "allcommits_repo_count": len(allcommits_repos),
        "overlap_repo_count": len(overlap_repos),
        "overlap_repo_examples": overlap_repos[:20],
        "annotated_repos": sorted(annotated_repos),
        "allcommits_repos": sorted(allcommits_repos),
        "is_sha_disjoint": len(overlap_shas) == 0,
        "is_repo_disjoint": len(overlap_repos) == 0,
    }


def check_input_split_disjoint(
    annotated_csv: Path,
    allcommits_csv: Path,
    repo_overlap_policy: str = "error",
) -> dict:
    """
    检查标注集与候选池是否存在 SHA / repo 重叠。

    SHA 重叠始终直接失败。repo 重叠由 `repo_overlap_policy` 决定：
    - error: 作为严格 repo-level leakage 风险直接失败
    - allow_frozen_stats: 允许继续，但必须在下游使用冻结的 training-side stats
    """
    metadata = collect_input_split_metadata(annotated_csv, allcommits_csv)
    overlap_shas = metadata["overlap_sha_examples"]
    if metadata["overlap_sha_count"] > 0:
        preview = ",".join(overlap_shas[:10])
        raise RuntimeError(
            "annotated/allcommits sha overlap detected: "
            f"count={metadata['overlap_sha_count']} examples={preview}"
        )
    if metadata["overlap_repo_count"] > 0 and repo_overlap_policy == "error":
        preview = ",".join(metadata["overlap_repo_examples"][:20])
        raise RuntimeError(
            "annotated/allcommits repo overlap detected under strict repo-disjoint policy: "
            f"count={metadata['overlap_repo_count']} examples={preview}"
        )
    metadata["repo_overlap_policy"] = repo_overlap_policy
    return metadata


def path_as_str_or_empty(path: Path | None) -> str:
    """存在时返回路径字符串，否则返回空串。"""
    if path is None:
        return ""
    return path.as_posix() if path.exists() else ""


def build_annotated_split_constraints(args: argparse.Namespace) -> dict:
    """从 runner 参数构建 annotated 五分区约束。"""
    split_seed = getattr(args, "annotated_split_seed", getattr(args, "seed", DEFAULT_RANDOM_SEED))
    return {
        "seed": int(split_seed),
        "min_total_by_split": {
            "protocol": int(args.protocol_min_total),
            "gbdt_train": int(args.gbdt_train_min_total),
            "calibration": int(args.calibration_min_total),
            "evaluation": int(args.evaluation_min_total),
            "proxy_gap": int(args.proxy_gap_min_total),
        },
        "min_positive_by_split": {
            "protocol": int(args.protocol_min_positive),
            "gbdt_train": int(args.gbdt_train_min_positive),
            "calibration": int(args.calibration_min_positive),
            "evaluation": int(args.evaluation_min_positive),
            "proxy_gap": int(args.proxy_gap_min_positive),
        },
        "min_negative_by_split": {
            "protocol": int(args.protocol_min_negative),
            "gbdt_train": int(args.gbdt_train_min_negative),
            "calibration": int(args.calibration_min_negative),
            "evaluation": int(args.evaluation_min_negative),
            "proxy_gap": int(args.proxy_gap_min_negative),
        },
        "min_repo_by_split": {
            "protocol": int(args.protocol_min_repos),
            "gbdt_train": int(args.gbdt_train_min_repos),
            "calibration": int(args.calibration_min_repos),
            "evaluation": int(args.evaluation_min_repos),
            "proxy_gap": int(args.proxy_gap_min_repos),
        },
    }


def prepare_annotated_split_artifacts(
    *,
    annotated_csv: Path,
    run_root: Path,
    constraints: dict,
) -> dict:
    """为 annotated 数据生成严格互斥五分区并落盘。"""
    annotated_rows = load_csv_rows(annotated_csv)
    plan = annotated_split_protocol.build_annotated_split_plan(
        rows=annotated_rows,
        seed=int(constraints["seed"]),
        min_total_by_split=dict(constraints["min_total_by_split"]),
        min_positive_by_split=dict(constraints["min_positive_by_split"]),
        min_negative_by_split=dict(constraints["min_negative_by_split"]),
        min_repo_by_split=dict(constraints["min_repo_by_split"]),
    )
    artifact_paths = annotated_split_protocol.write_split_artifacts(
        base_dir=run_root / "annotated_splits",
        rows=annotated_rows,
        plan=plan,
    )
    summary = annotated_split_protocol.summarize_split_plan(plan)
    return {
        "plan": plan,
        "summary": summary,
        **artifact_paths,
    }


def check_select(selection_batch_csv: Path, per_type: int, strict: bool) -> dict:
    """
    检查批次选择输出质量

    验证分层批次选择：
    - 输出非空
    - 总数匹配预期
    - 每种类型数量均衡

    参数:
        selection_batch_csv: 分层批次CSV文件
        per_type: 每类型候选数
        strict: 是否严格模式

    返回:
        dict: 选择检查结果
    """
    rows = load_csv_rows(selection_batch_csv)
    enforce(len(rows) > 0, "select_batch produced empty output", strict=strict)
    type_counter: dict[str, int] = {}
    for row in rows:
        commit_type = row.get("type", "")
        type_counter[commit_type] = type_counter.get(commit_type, 0) + 1
    resolved_per_type = int(per_type)
    if resolved_per_type <= 0:
        counts = [type_counter.get(commit_type, 0) for commit_type in HARD_BALANCE_TYPES]
        resolved_per_type = min(counts) if counts else 0
    expected_total = resolved_per_type * len(HARD_BALANCE_TYPES)
    enforce(
        len(rows) == expected_total,
        f"select_batch count mismatch: expected {expected_total}, got {len(rows)}",
        strict=strict,
    )
    for commit_type in HARD_BALANCE_TYPES:
        enforce(
            type_counter.get(commit_type, 0) == resolved_per_type,
            f"select_batch imbalance for {commit_type}: expected {resolved_per_type}, got {type_counter.get(commit_type, 0)}",
            strict=strict,
        )
    return {
        "selected": len(rows),
        "per_type": resolved_per_type,
        "type_distribution": type_counter,
    }


def check_enrich(
    enriched_dir: Path,
    expected_total: int,
    fetch_diff: bool,
    min_resolved_ratio: float,
    min_diff_ratio: float,
    require_complete: bool,
    strict: bool,
) -> dict:
    """
    检查增强输出质量

    验证增强阶段输出：
    - 解析成功比例满足要求
    - 如果fetch_diff，则diff覆盖率满足要求
    - 完成状态检查

    参数:
        enriched_dir: 增强输出目录
        expected_total: 预期候选总数
        fetch_diff: 是否获取diff
        min_resolved_ratio: 最小解析比例
        min_diff_ratio: 最小diff比例
        require_complete: 是否要求完成
        strict: 是否严格模式

    返回:
        dict: 增强检查结果
    """
    resolved_csv = enriched_dir / "resolved_candidates.csv"
    status_json = enriched_dir / "enrich_status.json"
    rows = load_csv_rows(resolved_csv)
    enforce(len(rows) > 0, "enrich output is empty", strict=strict)
    if not rows:
        return {
            "processed_rows": 0,
            "resolved_count": 0,
            "resolved_ratio": 0.0,
            "diff_count": 0,
            "diff_ratio": 0.0,
            "completed": False,
            "status_path": status_json.as_posix(),
        }
    resolved_count = sum(1 for row in rows if row.get("resolved_repo"))
    resolved_ratio = resolved_count / len(rows)
    enforce(
        resolved_ratio >= min_resolved_ratio,
        f"resolved ratio too low: {resolved_ratio:.4f} < {min_resolved_ratio:.4f}",
        strict=strict,
    )
    diff_count = 0
    if fetch_diff:
        diff_count = sum(
            1
            for row in rows
            if str(row.get("git_diff", "")).strip()
            or row.get("score") not in {None, ""}
        )
        diff_ratio = diff_count / len(rows)
        enforce(
            diff_ratio >= min_diff_ratio,
            f"diff coverage too low: {diff_ratio:.4f} < {min_diff_ratio:.4f}",
            strict=strict,
        )
    else:
        diff_ratio = 0.0
    status_payload = {}
    if status_json.exists():
        status_payload = load_json(status_json)
    completed = bool(status_payload.get("completed", len(rows) >= expected_total))
    enforce(
        (not require_complete) or completed,
        "enrich not complete; resume/retry required",
        strict=strict,
    )
    enforce(
        (not require_complete) or len(rows) >= expected_total,
        f"enrich row count too low for complete mode: {len(rows)} < {expected_total}",
        strict=strict,
    )
    return {
        "processed_rows": len(rows),
        "resolved_count": resolved_count,
        "resolved_ratio": round(resolved_ratio, 6),
        "diff_count": diff_count,
        "diff_ratio": round(diff_ratio, 6),
        "completed": completed,
        "status_path": status_json.as_posix(),
    }


def check_validate(
    validation_dir: Path,
    audit_target: int,
    require_audit_completion: bool,
    audit_labeled_csv: str,
    audit_tier: str,
    expect_audit_samples: bool,
    strict: bool,
) -> dict:
    """
    检查验证输出质量

    验证验证阶段输出：
    - Tier A候选数 >= 审计目标
    - 审计样本大小在[300, 500]范围内
    - 如果require_audit_completion，验证标注完成度

    参数:
        validation_dir: 验证输出目录
        audit_target: 审计目标大小
        require_audit_completion: 是否要求审计完成
        audit_labeled_csv: 审计标注CSV路径
        strict: 是否严格模式

    返回:
        dict: 验证检查结果
    """
    tier_a_rows = load_csv_rows(validation_dir / "tier_a_candidates.csv")
    tier_b_rows = load_csv_rows(validation_dir / "tier_b_candidates.csv")
    audit_tier_upper = str(audit_tier).upper()
    audit_rows = tier_a_rows if audit_tier_upper == "A" else tier_b_rows
    audit_sample_name = (
        "tier_a_audit_sample.csv"
        if audit_tier_upper == "A"
        else "tier_b_audit_sample.csv"
    )
    tier_audit_rows = (
        load_csv_rows(validation_dir / audit_sample_name) if expect_audit_samples else []
    )
    enforce(
        len(audit_rows) >= audit_target,
        f"tier_{audit_tier_upper.lower()} too small for audit target: {len(audit_rows)} < {audit_target}",
        strict=strict,
    )
    if expect_audit_samples:
        enforce(
            AUDIT_SIZE_MIN <= len(tier_audit_rows) <= AUDIT_SIZE_MAX,
            "audit sample size is outside [300, 500]",
            strict=strict,
        )
    elif require_audit_completion:
        raise RuntimeError(
            "require_audit_completion=true requires audit sample export to be enabled"
        )
    audit_completion = {}
    if require_audit_completion:
        audit_path = (
            Path(audit_labeled_csv)
            if audit_labeled_csv
            else (validation_dir / audit_sample_name)
        )
        labeled_rows = load_csv_rows(audit_path)
        enforce(
            len(labeled_rows) == len(tier_audit_rows),
            "audit labeled csv size mismatch",
            strict=strict,
        )
        alignment_stats = evaluate_audit_sample_alignment(tier_audit_rows, labeled_rows)
        enforce(
            bool(alignment_stats.get("is_aligned")),
            "audit labeled csv sha order mismatch",
            strict=strict,
        )
        valid_label_count = 0
        valid_conf_count = 0
        for row in labeled_rows:
            label = str(row.get("audit_is_single_intent", "")).strip()
            if label in {"0", "1"}:
                valid_label_count += 1
            confidence_raw = str(row.get("audit_confidence", "")).strip()
            try:
                confidence = float(confidence_raw)
                if 0.0 <= confidence <= 1.0:
                    valid_conf_count += 1
            except ValueError:
                continue
        enforce(
            valid_label_count == len(labeled_rows),
            "audit labels are incomplete or invalid",
            strict=strict,
        )
        enforce(
            valid_conf_count == len(labeled_rows),
            "audit confidence is incomplete or invalid",
            strict=strict,
        )
        audit_completion = {
            "audit_labeled_csv": audit_path.as_posix(),
            "valid_label_count": valid_label_count,
            "valid_confidence_count": valid_conf_count,
            "same_length": bool(alignment_stats.get("same_length")),
            "same_sha_set": bool(alignment_stats.get("same_sha_set")),
            "same_sha_order": bool(alignment_stats.get("same_sha_order")),
        }
    precision_report = {}
    precision_report_path = validation_dir / "audit_precision_report.json"
    if precision_report_path.exists():
        precision_report = load_json(precision_report_path)
    return {
        "tier_a": len(tier_a_rows),
        "tier_b": len(tier_b_rows),
        "audit_tier": audit_tier_upper,
        "audit_sample": len(tier_audit_rows),
        "audit_completion": audit_completion,
        "tier_a_precision": ((precision_report.get("tier_a") or {}).get("precision")),
        "tier_b_precision": ((precision_report.get("tier_b") or {}).get("precision")),
        "tier_a_precision_sample_count": ((precision_report.get("tier_a") or {}).get("sample_count")),
        "tier_b_precision_sample_count": ((precision_report.get("tier_b") or {}).get("sample_count")),
        "audit_precision_report_json": (
            precision_report_path.as_posix() if precision_report_path.exists() else ""
        ),
    }


def write_manifest(path: Path, payload: dict) -> None:
    """
    写入清单JSON文件

    参数:
        path: 输出文件路径
        payload: 清单数据字典
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")




def build_annotation_agreement_payload(
    *,
    annotator_a_rows: list[dict] | None,
    annotator_b_rows: list[dict] | None,
) -> dict:
    if not annotator_a_rows or not annotator_b_rows:
        return {
            "status": "unavailable",
            "reason": "annotator overlap csv files are missing or empty",
            "shared_sha_count": 0,
            "raw_agreement": None,
            "cohen_kappa": None,
            "confusion_summary": {},
            "adjudication_coverage": None,
        }
    payload = annotation_agreement.build_agreement_report(
        annotator_a_rows, annotator_b_rows
    )
    return {"status": "available", **payload}


def require_annotation_agreement_available(payload: dict) -> None:
    if str((payload or {}).get("status", "")).strip().lower() != "available":
        raise RuntimeError(
            "formal Step1 runs now require annotation agreement artifacts; "
            f"current status={payload.get('status')!r}, reason={payload.get('reason', '')!r}"
        )


def write_annotation_agreement(
    *,
    output_dir: Path,
    payload: dict,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "annotation_agreement.json"
    md_path = output_dir / "annotation_agreement.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Annotation Agreement",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Shared labeled rows: `{payload.get('shared_sha_count')}`",
        f"- Raw agreement: `{payload.get('raw_agreement')}`",
        f"- Cohen's kappa: `{payload.get('cohen_kappa')}`",
        f"- Adjudication coverage: `{payload.get('adjudication_coverage')}`",
        "",
        "## Confusion Summary",
        "",
    ]
    for key, value in sorted((payload.get("confusion_summary") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path.as_posix(), "markdown": md_path.as_posix()}


def load_selection_metrics(path: Path) -> dict:
    """加载合并阶段输出的完整 metrics JSON。"""
    ensure(path.exists(), f"selection metrics json missing: {path.as_posix()}")
    return load_json(path)


def build_validate_command(
    *,
    python_executable: str,
    candidates_csv: Path,
    pilot_csv: str,
    output_dir: Path,
    sample_per_tier: int,
    seed: int,
    diff_required: bool,
    primary_calibration_json: Path | None,
    proxy_calibration_json: Path | None = None,
    audit_size: int,
    tier_a_audit_labeled_csv: str,
    tier_b_audit_labeled_csv: str,
    require_audit_completion: bool,
    export_audit_samples: bool,
    audit_tier: str,
    threshold_mode: str,
    annotated_split_plan_json: str = "",
) -> list[str]:
    """
    构建validate阶段命令，确保diff-required与enrich配置一致。
    """
    command = [
        python_executable,
        "-m",
        "src.pipeline.validation",
        "--candidates",
        candidates_csv.as_posix(),
        "--pilot",
        pilot_csv,
        "--output-dir",
        output_dir.as_posix(),
        "--sample-per-tier",
        str(sample_per_tier),
        "--seed",
        str(seed),
        "--audit-size",
        str(audit_size),
        "--audit-tier",
        audit_tier,
        "--threshold-mode",
        threshold_mode,
        "--tier-a-audit-labeled-csv",
        tier_a_audit_labeled_csv,
        "--tier-b-audit-labeled-csv",
        tier_b_audit_labeled_csv,
    ]
    if primary_calibration_json is not None:
        command.extend(
            ["--primary-calibration-json", primary_calibration_json.as_posix()]
        )
    if proxy_calibration_json is not None:
        command.extend(["--proxy-calibration-json", proxy_calibration_json.as_posix()])
    if annotated_split_plan_json:
        command.extend(["--annotated-split-plan-json", annotated_split_plan_json])
    command.append("--diff-required" if diff_required else "--no-diff-required")
    if require_audit_completion:
        command.append("--require-audit-completion")
    command.append(
        "--export-audit-samples" if export_audit_samples else "--no-export-audit-samples"
    )
    return command


def build_enrich_command(
    *,
    python_executable: str,
    candidates_csv: Path,
    repo_list: str,
    repo_cache: Path,
    output_dir: Path,
    max_candidates: int,
    min_atomic_prior: float,
    primary_calibration_json: Path | None,
    proxy_calibration_json: Path | None,
    search_sleep_seconds: float,
    retry_on_429: int,
    progress_every: int,
    checkpoint_interval: int,
    reference_time_utc: str,
    fetch_diff: bool,
    reset_output: bool,
    require_complete: bool,
) -> list[str]:
    """构建 enrich 阶段命令，显式传递 full-diff 与 message-only 两类校准工件。"""
    command = [
        python_executable,
        "-u",
        "-m",
        "src.pipeline.enrichment",
        "--input",
        candidates_csv.as_posix(),
        "--repo-list",
        repo_list,
        "--repo-cache",
        repo_cache.as_posix(),
        "--output-dir",
        output_dir.as_posix(),
        "--max-candidates",
        str(max_candidates),
        "--min-atomic-prior",
        str(min_atomic_prior),
        "--search-sleep-seconds",
        str(search_sleep_seconds),
        "--retry-on-429",
        str(max(1, int(retry_on_429))),
        "--progress-every",
        str(max(1, int(progress_every))),
        "--checkpoint-interval",
        str(max(1, int(checkpoint_interval))),
        "--reference-time-utc",
        reference_time_utc,
    ]
    if primary_calibration_json is not None:
        command.extend(["--primary-calibration-json", primary_calibration_json.as_posix()])
    if proxy_calibration_json is not None:
        command.extend(
            [
                "--proxy-calibration-json",
                proxy_calibration_json.as_posix(),
            ]
        )
    if fetch_diff:
        command.append("--fetch-diff")
    if reset_output:
        command.append("--reset-output")
    if require_complete:
        command.append("--require-complete")
    return command


def build_proxy_gap_command(
    *,
    python_executable: str,
    selection_batch_csv: Path,
    resolved_candidates_csv: Path,
    validation_dir: Path,
    annotated_csv: Path,
    proxy_calibration_json: Path,
    primary_calibration_json: Path,
    output_dir: Path,
    audit_target: int,
    annotated_split_plan_json: str = "",
) -> list[str]:
    """构建独立 proxy-gap CLI 命令。"""
    command = [
        python_executable,
        "-m",
        "src.analysis.proxy_gap",
        "--selection-batch-csv",
        selection_batch_csv.as_posix(),
        "--resolved-candidates-csv",
        resolved_candidates_csv.as_posix(),
        "--validation-dir",
        validation_dir.as_posix(),
        "--annotated-csv",
        annotated_csv.as_posix(),
        "--proxy-calibration-json",
        proxy_calibration_json.as_posix(),
        "--primary-calibration-json",
        primary_calibration_json.as_posix(),
        "--output-dir",
        output_dir.as_posix(),
        "--audit-target",
        str(int(audit_target)),
    ]
    if annotated_split_plan_json:
        return command + ["--annotated-split-plan-json", annotated_split_plan_json]
    return command


def resolve_calibration_artifacts(
    *,
    message_only_calibration_json: Path,
    reuse_message_only_json: str,
    reuse_full_diff_json: str,
    fetch_diff: bool,
) -> tuple[Path | None, Path]:
    """解析复用模式下的 full-diff / message-only 校准工件路径。"""
    message_only_path = Path(reuse_message_only_json) if reuse_message_only_json else message_only_calibration_json
    ensure(
        message_only_path.exists(),
        f"reuse calibration file not found: {message_only_path.as_posix()}",
    )
    full_diff_path: Path | None = None
    if reuse_full_diff_json:
        full_diff_path = Path(reuse_full_diff_json)
        ensure(
            full_diff_path.exists(),
            f"reuse full-diff calibration file not found: {full_diff_path.as_posix()}",
        )
    else:
        sibling = message_only_path.with_name("atomic_calibration_full_diff.json")
        if sibling.exists():
            full_diff_path = sibling
        elif fetch_diff:
            raise RuntimeError(
                "fetch-diff mode requires full-diff calibration; "
                f"could not infer sibling artifact near {message_only_path.as_posix()}"
            )
    return full_diff_path, message_only_path


def main() -> None:
    """
    主函数：执行Step1完整实验流水线

    流程：
    1. 校准阶段：生成 full-diff / message-only 两类校准工件
    2. 合并筛选阶段：从 raw allcommits 直接完成 message-only prior 计算与类型均衡抽样
    3. 增强阶段：解析 GitHub 仓库并获取 diff
    4. 验证阶段：基于候选池生成 review / audit 产物
    """
    args = parse_args()
    selection_strategies = analysis_strategy_compare.parse_selection_strategies(
        args.selection_strategies
    )
    workdir = Path.cwd()
    run_suffix = args.run_ts or utc_ts()
    run_root = Path(args.base_output_dir) / f"{args.run_name}_{run_suffix}"
    run_root.mkdir(parents=True, exist_ok=True)

    calib_dir = run_root / "calibration"
    selection_dir = run_root / "selection"
    enriched_dir = run_root / "enriched"
    validation_dir = run_root / "validation"
    analysis_dir = run_root / "analysis"
    logs_dir = run_root / "logs"
    for item in [calib_dir, selection_dir, enriched_dir, validation_dir, analysis_dir, logs_dir]:
        item.mkdir(parents=True, exist_ok=True)

    audit_target = clamp_audit_size(args.audit_size)
    per_type: int | None = args.per_type if args.per_type > 0 else None
    py = sys.executable
    primary_calibration_json = calib_dir / "atomic_calibration_full_diff.json"
    proxy_calibration_json = calib_dir / "message_only_calibration.json"
    selection_batch_csv = selection_dir / "selection_batch.csv"
    selection_metrics_json = selection_dir / "selection_metrics.json"
    resolved_candidates_csv = enriched_dir / "resolved_candidates.csv"

    stage_checks: list[dict] = []
    reference_time_utc = args.reference_time_utc or datetime.now(
        timezone.utc
    ).isoformat().replace("+00:00", "Z")
    split_metadata = check_input_split_disjoint(
        Path(args.annotated),
        Path(args.allcommits),
        repo_overlap_policy=args.repo_overlap_policy,
    )
    split_metadata_path = run_root / "input_split_metadata.json"
    write_manifest(split_metadata_path, split_metadata)
    annotated_split_constraints = build_annotated_split_constraints(args)
    annotated_split_artifacts = prepare_annotated_split_artifacts(
        annotated_csv=Path(args.annotated),
        run_root=run_root,
        constraints=annotated_split_constraints,
    )
    annotated_split_summary = annotated_split_artifacts["summary"]
    annotated_split_csvs = annotated_split_artifacts["split_csvs"]
    annotated_split_sha_csvs = annotated_split_artifacts["split_sha_csvs"]
    annotated_split_repo_summary_jsons = annotated_split_artifacts["split_repo_summary_jsons"]
    annotator_a_rows = (
        load_csv_rows(Path(args.annotation_overlap_a_csv))
        if Path(args.annotation_overlap_a_csv).exists()
        else []
    )
    annotator_b_rows = (
        load_csv_rows(Path(args.annotation_overlap_b_csv))
        if Path(args.annotation_overlap_b_csv).exists()
        else []
    )
    annotation_agreement_payload = build_annotation_agreement_payload(
        annotator_a_rows=annotator_a_rows,
        annotator_b_rows=annotator_b_rows,
    )
    require_annotation_agreement_available(annotation_agreement_payload)
    annotation_agreement_paths = write_annotation_agreement(
        output_dir=run_root,
        payload=annotation_agreement_payload,
    )
    stage_checks.append(
        {
            "stage": "annotated_split",
            "metrics": {
                "seed": annotated_split_summary["seed"],
                "is_sha_disjoint": annotated_split_summary["is_sha_disjoint"],
                "splits": {
                    split_name: {
                        "row_count": annotated_split_summary["splits"][split_name]["row_count"],
                        "positive_count": annotated_split_summary["splits"][split_name]["positive_count"],
                        "negative_count": annotated_split_summary["splits"][split_name]["negative_count"],
                        "repo_count": annotated_split_summary["splits"][split_name]["repo_count"],
                    }
                    for split_name in annotated_split_protocol.ANNOTATED_SPLIT_ORDER
                },
            },
        }
    )
    stage_checks.append(
        {
            "stage": "annotation_agreement",
            "metrics": {
                "status": annotation_agreement_payload.get("status"),
                "shared_sha_count": annotation_agreement_payload.get("shared_sha_count"),
                "raw_agreement": annotation_agreement_payload.get("raw_agreement"),
                "cohen_kappa": annotation_agreement_payload.get("cohen_kappa"),
                "adjudication_coverage": annotation_agreement_payload.get(
                    "adjudication_coverage"
                ),
                "annotation_agreement_json": annotation_agreement_paths["json"],
            },
        }
    )

    reuse_proxy_calibration_json = (
        args.reuse_proxy_calibration_json or args.reuse_calibration_json
    )
    reuse_primary_calibration_json = (
        args.reuse_primary_calibration_json or args.reuse_full_diff_calibration_json
    )
    if args.reuse_calibration_json:
        print(
            "[deprecation] --reuse-calibration-json is deprecated; use --reuse-proxy-calibration-json",
            flush=True,
        )
    if args.reuse_full_diff_calibration_json:
        print(
            "[deprecation] --reuse-full-diff-calibration-json is deprecated; use --reuse-primary-calibration-json",
            flush=True,
        )

    if reuse_proxy_calibration_json:
        full_diff_reuse, message_only_reuse = resolve_calibration_artifacts(
            message_only_calibration_json=proxy_calibration_json,
            reuse_message_only_json=reuse_proxy_calibration_json,
            reuse_full_diff_json=reuse_primary_calibration_json,
            fetch_diff=bool(args.fetch_diff),
        )
        if full_diff_reuse is not None:
            primary_calibration_json = full_diff_reuse
        proxy_calibration_json = message_only_reuse
    else:
        run_cmd_stream(
            [
                py,
                "-m",
                "src.pipeline.full_diff_calibration",
                "--mode",
                "gbdt_isotonic",
                "--input",
                annotated_split_csvs["gbdt_train"],
                "--protocol-input",
                annotated_split_csvs["protocol"],
                "--gbdt-train-input",
                annotated_split_csvs["gbdt_train"],
                "--calibration-input",
                annotated_split_csvs["calibration"],
                "--evaluation-input",
                annotated_split_csvs["evaluation"],
                "--annotated-split-plan-json",
                annotated_split_artifacts["plan_json"],
                "--label-col",
                args.label_col,
                "--labeled-calibration-scheme",
                "holdout",
                "--labeled-holdout-ratio",
                str(args.calibration_holdout_ratio),
                "--threshold-fallback-policy",
                args.threshold_fallback_policy,
                "--output",
                primary_calibration_json.as_posix(),
            ],
            cwd=workdir,
            log_path=logs_dir / "01_calibration.log",
        )
        run_cmd_stream(
            [
                py,
                "-m",
                "src.pipeline.message_only_calibration",
                "--input",
                annotated_split_csvs["calibration"],
                "--calibration-input",
                annotated_split_csvs["calibration"],
                "--evaluation-input",
                annotated_split_csvs["evaluation"],
                "--annotated-split-plan-json",
                annotated_split_artifacts["plan_json"],
                "--base-calibration",
                primary_calibration_json.as_posix(),
                "--output",
                proxy_calibration_json.as_posix(),
                "--calibration-mode",
                "platt",
                "--labeled-calibration-scheme",
                "cv",
                "--labeled-cv-folds",
                "5",
                "--tau-a-precision",
                "0.9",
                "--tau-b-precision",
                "0.7",
                "--threshold-fallback-policy",
                args.threshold_fallback_policy,
            ],
            cwd=workdir,
            log_path=logs_dir / "01b_message_only_calibration.log",
        )
    message_only_metrics = check_calibration(
        proxy_calibration_json,
        strict=args.strict_gates,
        expected_artifact="message_only",
    )
    full_diff_metrics = (
        check_calibration(
            primary_calibration_json,
            strict=args.strict_gates,
            expected_artifact="full_diff",
        )
        if args.fetch_diff or not reuse_proxy_calibration_json
        else None
    )
    calibration_diagnostics_payload = analysis_diagnostics.build_calibration_diagnostics_payload(
        primary_artifact=load_json(primary_calibration_json),
        proxy_artifact=load_json(proxy_calibration_json),
        annotation_agreement=annotation_agreement_payload,
    )
    calibration_diagnostics_paths = analysis_diagnostics.write_calibration_diagnostics(
        output_dir=calib_dir,
        payload=calibration_diagnostics_payload,
    )
    stage_checks.append(
        {
            "stage": "calibration",
            "metrics": {
                **message_only_metrics,
                "message_only_tau_a": message_only_metrics["tau_a"],
                "message_only_tau_b": message_only_metrics["tau_b"],
                "full_diff_tau_a": (
                    full_diff_metrics.get("tau_a") if full_diff_metrics else None
                ),
                "full_diff_tau_b": (
                    full_diff_metrics.get("tau_b") if full_diff_metrics else None
                ),
                "full_diff_threshold_source": (
                    full_diff_metrics.get("threshold_source")
                    if full_diff_metrics
                    else None
                ),
                "calibration_diagnostics_json": calibration_diagnostics_paths["json"],
            },
        }
    )
    if args.stop_after == "calibration":
        write_manifest(
            run_root / "run_manifest.json",
            {
                "run_root": run_root.as_posix(),
                "timestamp_suffix": run_suffix,
                "stopped_after": "calibration",
                "derived": {
                    "per_type": per_type,
                    "audit_target": audit_target,
                    "reference_time_utc": reference_time_utc,
                },
                "artifacts": {
                    "input_split_metadata_json": split_metadata_path.as_posix(),
                    "annotation_agreement_json": annotation_agreement_paths["json"],
                    "annotation_agreement_md": annotation_agreement_paths["markdown"],
                    "annotated_split_plan_json": annotated_split_artifacts["plan_json"],
                    "annotated_split_csvs": annotated_split_csvs,
                    "annotated_split_sha_csvs": annotated_split_sha_csvs,
                    "annotated_split_repo_summary_jsons": annotated_split_repo_summary_jsons,
                    "proxy_calibration_json": proxy_calibration_json.as_posix(),
                    "primary_calibration_json": path_as_str_or_empty(primary_calibration_json),
                    "calibration_diagnostics_json": calibration_diagnostics_paths["json"],
                    "calibration_diagnostics_md": calibration_diagnostics_paths["markdown"],
                    "selection_dir": selection_dir.as_posix(),
                    "selection_batch_csv": selection_batch_csv.as_posix(),
                    "selection_metrics_json": selection_metrics_json.as_posix(),
                    "enriched_dir": enriched_dir.as_posix(),
                    "validation_dir": validation_dir.as_posix(),
                    "analysis_dir": analysis_dir.as_posix(),
                    "logs_dir": logs_dir.as_posix(),
                },
                "stage_checks": stage_checks,
                "input_split_metadata": split_metadata,
                "args": vars(args),
            },
        )
        print(f"run_root={run_root.as_posix()}")
        return

    prefer_high_tier = True
    run_cmd_stream(
        [
            py,
            "-m",
            "src.pipeline.selection",
            "--input",
            args.allcommits,
            "--output",
            selection_batch_csv.as_posix(),
            "--audit-target",
            str(audit_target),
            "--per-type",
            str(args.per_type),
            "--seed",
            str(args.seed),
            "--proxy-calibration-json",
            proxy_calibration_json.as_posix(),
            "--min-prefilter-prob",
            str(args.min_prefilter_prob),
            "--debug-top-count",
            str(args.prefilter_target_count),
            "--metrics-json",
            selection_metrics_json.as_posix(),
            *(["--dump-debug-artifacts"] if args.dump_debug_artifacts else []),
            *(["--prefer-high-tier"] if prefer_high_tier else []),
        ],
        cwd=workdir,
        log_path=logs_dir / "02_select_batch.log",
    )
    selection_metrics = load_selection_metrics(selection_metrics_json)
    select_gate_metrics = check_select(
        selection_batch_csv, per_type=args.per_type, strict=args.strict_gates
    )
    select_metrics = {**selection_metrics, **select_gate_metrics}
    per_type = int(select_metrics["per_type"])
    stage_checks.append({"stage": "select_batch", "metrics": select_metrics})
    if args.stop_after in {"prefilter", "select_batch"}:
        write_manifest(
            run_root / "run_manifest.json",
            {
                "run_root": run_root.as_posix(),
                "timestamp_suffix": run_suffix,
                "stopped_after": args.stop_after,
                "derived": {
                    "per_type": per_type,
                    "audit_target": audit_target,
                    "reference_time_utc": reference_time_utc,
                },
                "artifacts": {
                    "input_split_metadata_json": split_metadata_path.as_posix(),
                    "annotation_agreement_json": annotation_agreement_paths["json"],
                    "annotation_agreement_md": annotation_agreement_paths["markdown"],
                    "annotated_split_plan_json": annotated_split_artifacts["plan_json"],
                    "annotated_split_csvs": annotated_split_csvs,
                    "annotated_split_sha_csvs": annotated_split_sha_csvs,
                    "annotated_split_repo_summary_jsons": annotated_split_repo_summary_jsons,
                    "proxy_calibration_json": proxy_calibration_json.as_posix(),
                    "primary_calibration_json": path_as_str_or_empty(primary_calibration_json),
                    "calibration_diagnostics_json": calibration_diagnostics_paths["json"],
                    "calibration_diagnostics_md": calibration_diagnostics_paths["markdown"],
                    "selection_dir": selection_dir.as_posix(),
                    "selection_batch_csv": selection_batch_csv.as_posix(),
                    "selection_metrics_json": selection_metrics_json.as_posix(),
                    "enriched_dir": enriched_dir.as_posix(),
                    "validation_dir": validation_dir.as_posix(),
                    "analysis_dir": analysis_dir.as_posix(),
                    "logs_dir": logs_dir.as_posix(),
                },
                "stage_checks": stage_checks,
                "input_split_metadata": split_metadata,
                "args": vars(args),
            },
        )
        print(f"run_root={run_root.as_posix()}")
        return

    selected_total = int(select_metrics["selected"])
    max_candidates = args.max_candidates if args.max_candidates > 0 else selected_total
    ensure(max_candidates > 0, "max_candidates must be > 0 after derivation")
    effective_min_resolved_ratio, min_resolved_ratio_source = derive_min_resolved_ratio(
        min_resolved_ratio_arg=args.min_resolved_ratio,
        audit_target=audit_target,
        expected_total=max_candidates,
    )
    enrich_success = False
    for attempt in range(1, max(1, int(args.enrich_max_retries)) + 1):
        enrich_cmd = build_enrich_command(
            python_executable=py,
            candidates_csv=selection_batch_csv,
            repo_list=args.repo_list,
            repo_cache=run_root / "repo_metadata.json",
            output_dir=enriched_dir,
            max_candidates=max_candidates,
            min_atomic_prior=args.min_atomic_prior,
            primary_calibration_json=(
                primary_calibration_json
                if path_as_str_or_empty(primary_calibration_json)
                else None
            ),
            proxy_calibration_json=proxy_calibration_json,
            search_sleep_seconds=args.enrich_search_sleep_seconds,
            retry_on_429=args.enrich_retry_on_429,
            progress_every=args.enrich_progress_every,
            checkpoint_interval=args.enrich_checkpoint_interval,
            reference_time_utc=reference_time_utc,
            fetch_diff=bool(args.fetch_diff),
            reset_output=(attempt == 1),
            require_complete=bool(
                args.require_enrich_complete and args.strict_gates
            ),
        )
        try:
            run_cmd_stream(
                enrich_cmd,
                cwd=workdir,
                log_path=logs_dir / f"04_enrich_attempt{attempt}.log",
            )
            enrich_metrics = check_enrich(
                enriched_dir=enriched_dir,
                expected_total=max_candidates,
                fetch_diff=args.fetch_diff,
                min_resolved_ratio=effective_min_resolved_ratio,
                min_diff_ratio=args.min_diff_ratio,
                require_complete=args.require_enrich_complete,
                strict=args.strict_gates,
            )
            enrich_metrics["min_resolved_ratio"] = round(
                effective_min_resolved_ratio, 6
            )
            enrich_metrics["min_resolved_ratio_source"] = min_resolved_ratio_source
            stage_checks.append(
                {"stage": f"enrich_attempt_{attempt}", "metrics": enrich_metrics}
            )
            enrich_success = True
            break
        except Exception as exc:
            print(f"[enrich retry] attempt={attempt} failed: {exc}", flush=True)
            if attempt >= max(1, int(args.enrich_max_retries)):
                raise
    ensure(enrich_success, "enrich stage did not complete successfully")
    if args.stop_after == "enrich":
        write_manifest(
            run_root / "run_manifest.json",
            {
                "run_root": run_root.as_posix(),
                "timestamp_suffix": run_suffix,
                "stopped_after": "enrich",
                "derived": {
                    "per_type": per_type,
                    "audit_target": audit_target,
                    "max_candidates": max_candidates,
                    "reference_time_utc": reference_time_utc,
                    "min_resolved_ratio": round(effective_min_resolved_ratio, 6),
                    "min_resolved_ratio_source": min_resolved_ratio_source,
                },
                "artifacts": {
                    "input_split_metadata_json": split_metadata_path.as_posix(),
                    "annotation_agreement_json": annotation_agreement_paths["json"],
                    "annotation_agreement_md": annotation_agreement_paths["markdown"],
                    "annotated_split_plan_json": annotated_split_artifacts["plan_json"],
                    "annotated_split_csvs": annotated_split_csvs,
                    "annotated_split_sha_csvs": annotated_split_sha_csvs,
                    "annotated_split_repo_summary_jsons": annotated_split_repo_summary_jsons,
                    "proxy_calibration_json": proxy_calibration_json.as_posix(),
                    "primary_calibration_json": path_as_str_or_empty(primary_calibration_json),
                    "calibration_diagnostics_json": calibration_diagnostics_paths["json"],
                    "calibration_diagnostics_md": calibration_diagnostics_paths["markdown"],
                    "selection_dir": selection_dir.as_posix(),
                    "selection_batch_csv": selection_batch_csv.as_posix(),
                    "selection_metrics_json": selection_metrics_json.as_posix(),
                    "enriched_dir": enriched_dir.as_posix(),
                    "resolved_candidates_csv": resolved_candidates_csv.as_posix(),
                    "validation_dir": validation_dir.as_posix(),
                    "analysis_dir": analysis_dir.as_posix(),
                    "logs_dir": logs_dir.as_posix(),
                },
                "stage_checks": stage_checks,
                "input_split_metadata": split_metadata,
                "args": vars(args),
            },
        )
        print(f"run_root={run_root.as_posix()}")
        return

    audit_tier = resolve_validate_audit_tier()
    threshold_mode = resolve_validate_threshold_mode()
    run_cmd_stream(
        build_validate_command(
            python_executable=py,
            candidates_csv=resolved_candidates_csv,
            pilot_csv=annotated_split_csvs["evaluation"],
            output_dir=validation_dir,
            sample_per_tier=args.sample_per_tier,
            seed=args.seed,
            diff_required=bool(args.fetch_diff),
            primary_calibration_json=primary_calibration_json,
            proxy_calibration_json=proxy_calibration_json,
            audit_size=audit_target,
            tier_a_audit_labeled_csv=args.audit_labeled_csv,
            tier_b_audit_labeled_csv="",
            require_audit_completion=bool(args.require_audit_completion),
            export_audit_samples=bool(args.run_audit_sample_export),
            audit_tier=audit_tier,
            threshold_mode=threshold_mode,
            annotated_split_plan_json=annotated_split_artifacts["plan_json"],
        ),
        cwd=workdir,
        log_path=logs_dir / "05_validate.log",
    )
    if args.run_proxy_gap_analysis:
        run_cmd_stream(
            build_proxy_gap_command(
                python_executable=py,
                selection_batch_csv=selection_batch_csv,
                resolved_candidates_csv=resolved_candidates_csv,
                validation_dir=validation_dir,
                annotated_csv=Path(annotated_split_csvs["proxy_gap"]),
                proxy_calibration_json=proxy_calibration_json,
                primary_calibration_json=primary_calibration_json,
                output_dir=analysis_dir,
                audit_target=audit_target,
                annotated_split_plan_json=annotated_split_artifacts["plan_json"],
            ),
            cwd=workdir,
            log_path=logs_dir / "06_proxy_gap_analysis.log",
        )
        analysis_metrics = load_json(analysis_dir / "proxy_gap_analysis.json")
    else:
        analysis_metrics = {
            "status": "skipped",
            "reason": "run_proxy_gap_analysis=false",
            "proxy_role": "recall_prefilter_only",
        }
    stage_checks.append({"stage": "analysis", "metrics": analysis_metrics})
    validate_metrics = check_validate(
        validation_dir=validation_dir,
        audit_target=audit_target,
        require_audit_completion=args.require_audit_completion,
        audit_labeled_csv=args.audit_labeled_csv,
        audit_tier=audit_tier,
        expect_audit_samples=bool(args.run_audit_sample_export),
        strict=args.strict_gates,
    )
    stage_checks.append({"stage": "validate", "metrics": validate_metrics})
    validate_precision_report = {}
    validate_precision_report_json = str(
        validate_metrics.get("audit_precision_report_json", "") or ""
    ).strip()
    if validate_precision_report_json and Path(validate_precision_report_json).exists():
        validate_precision_report = load_json(Path(validate_precision_report_json))
    main_results_payload = analysis_main_results.build_main_results_payload(
        primary_artifact=load_json(primary_calibration_json),
        validate_precision_report=validate_precision_report,
    )
    main_results_paths = analysis_main_results.write_main_results(
        output_dir=run_root / "main_results",
        payload=main_results_payload,
    )
    stage_checks.append(
        {
            "stage": "main_results",
            "metrics": {
                "main_results_json": main_results_paths["json"],
                "rule_tier_a_precision": (
                    (main_results_payload.get("rule_model_comparison") or {})
                    .get("rule_only", {})
                    .get("tier_a_precision")
                ),
                "model_tier_a_precision": (
                    (main_results_payload.get("rule_model_comparison") or {})
                    .get("model_on_rule_labels", {})
                    .get("tier_a_precision")
                ),
                "feature_reduced_tier_a_precision": (
                    (main_results_payload.get("rule_model_comparison") or {})
                    .get("feature_reduced_model", {})
                    .get("tier_a_precision")
                ),
                "tier_a_recall_gain_model_minus_rule": (
                    (main_results_payload.get("rule_model_comparison") or {})
                    .get("gain_summary", {})
                    .get("tier_a_recall_gain_model_minus_rule")
                ),
                "tier_a_recall_delta_full_minus_reduced": (
                    (main_results_payload.get("rule_model_comparison") or {})
                    .get("gain_summary", {})
                    .get("tier_a_recall_delta_full_minus_reduced")
                ),
            },
        }
    )

    strategy_compare_output_dir = run_root / f"strategy_compare_{run_suffix}"
    audit_labeled_path = Path(args.audit_labeled_csv) if args.audit_labeled_csv else None
    strategy_compare_outputs = analysis_strategy_compare.run_strategy_compare(
        run_root=run_root,
        resolved_candidates_csv=resolved_candidates_csv,
        evaluation_csv=Path(annotated_split_csvs["evaluation"]),
        primary_calibration_json=primary_calibration_json,
        selection_strategies=selection_strategies,
        target_count=int(args.strategy_target_count),
        proxy_gap_analysis_json=(
            analysis_dir / "proxy_gap_analysis.json"
            if args.run_proxy_gap_analysis
            else None
        ),
        audit_labeled_csv=audit_labeled_path,
        audit_precision_report_json=(
            Path(validate_precision_report_json) if validate_precision_report_json else None
        ),
        output_dir=strategy_compare_output_dir,
    )
    stage_checks.append(
        {
            "stage": "strategy_compare",
            "metrics": {
                "selection_strategies": selection_strategies,
                "strategy_target_count": int(args.strategy_target_count),
                "strategy_comparison_json": strategy_compare_outputs[
                    "strategy_comparison_json"
                ],
                "conservative_atomic_sources_csv": strategy_compare_outputs[
                    "conservative_atomic_sources_csv"
                ],
                "source_pool_metadata_json": strategy_compare_outputs[
                    "source_pool_metadata_json"
                ],
            },
        }
    )

    manifest = {
        "run_root": run_root.as_posix(),
        "timestamp_suffix": run_suffix,
        "derived": {
            "per_type": per_type,
            "audit_target": audit_target,
            "max_candidates": max_candidates,
            "reference_time_utc": reference_time_utc,
            "min_resolved_ratio": round(effective_min_resolved_ratio, 6),
            "min_resolved_ratio_source": min_resolved_ratio_source,
        },
        "artifacts": {
            "input_split_metadata_json": split_metadata_path.as_posix(),
            "annotation_agreement_json": annotation_agreement_paths["json"],
            "annotation_agreement_md": annotation_agreement_paths["markdown"],
            "annotated_split_plan_json": annotated_split_artifacts["plan_json"],
            "annotated_split_csvs": annotated_split_csvs,
            "annotated_split_sha_csvs": annotated_split_sha_csvs,
            "annotated_split_repo_summary_jsons": annotated_split_repo_summary_jsons,
            "proxy_calibration_json": proxy_calibration_json.as_posix(),
            "primary_calibration_json": path_as_str_or_empty(primary_calibration_json),
            "calibration_diagnostics_json": calibration_diagnostics_paths["json"],
            "calibration_diagnostics_md": calibration_diagnostics_paths["markdown"],
            "selection_dir": selection_dir.as_posix(),
            "selection_batch_csv": selection_batch_csv.as_posix(),
            "selection_metrics_json": selection_metrics_json.as_posix(),
            "enriched_dir": enriched_dir.as_posix(),
            "resolved_candidates_csv": resolved_candidates_csv.as_posix(),
            "validation_dir": validation_dir.as_posix(),
            "analysis_dir": analysis_dir.as_posix(),
            "logs_dir": logs_dir.as_posix(),
            "main_results_json": main_results_paths["json"],
            "main_results_md": main_results_paths["markdown"],
            "strategy_compare_dir": strategy_compare_outputs["output_dir"],
            "strategy_comparison_json": strategy_compare_outputs[
                "strategy_comparison_json"
            ],
            "strategy_comparison_md": strategy_compare_outputs[
                "strategy_comparison_md"
            ],
            "candidate_overlap_matrix_csv": strategy_compare_outputs[
                "candidate_overlap_matrix_csv"
            ],
            "precision_recall_summary_csv": strategy_compare_outputs[
                "precision_recall_summary_csv"
            ],
            "conservative_atomic_sources_csv": strategy_compare_outputs[
                "conservative_atomic_sources_csv"
            ],
            "source_pool_metadata_json": strategy_compare_outputs[
                "source_pool_metadata_json"
            ],
            "stage_quality_checks": (run_root / "stage_quality_checks.json").as_posix(),
        },
        "stage_checks": stage_checks,
        "input_split_metadata": split_metadata,
        "args": vars(args),
    }
    write_manifest(run_root / "run_manifest.json", manifest)
    write_manifest(
        run_root / "stage_quality_checks.json", {"stage_checks": stage_checks}
    )

    print(f"run_root={run_root.as_posix()}")
    print(f"manifest={(run_root / 'run_manifest.json').as_posix()}")
    print(f"logs_dir={logs_dir.as_posix()}")


if __name__ == "__main__":
    main()
