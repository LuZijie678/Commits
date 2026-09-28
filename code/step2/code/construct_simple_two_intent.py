#!/usr/bin/env python3
"""
Step2 Simple Multi-Intent synthetic 样本构建脚本（balanced_step3_ready）。

能力概览：
1. 从当前 Step1->Step2 bridge source CSV 中筛选 A-tier source commits。
2. 在同仓库内构建 k-intent 可合并组并生成 synthetic diff。
3. 调用 DeepSeek API 生成 synthetic_subject（含 few-shot 检索、长度修复）。
4. 使用 BERTScore 计算 coverage / faithfulness，并补充 artifact/relevance/style/distribution 监控。
5. 用分布校准阈值自动分段为 pass / fallback / reject。
6. 写出样本、索引、summary 与完整 run metadata（含输入指纹、seed、gate 结果）。
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import itertools
import json
import math
import os
import platform
import random
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
REPO_ROOT = CURRENT_DIR.parents[2]

from difficulty_realism import annotate_samples_difficulty_and_realism, summarize_difficulty_realism
from formal_assets import summarize_formal_assets


# ============================================================
# 常量定义区
# ============================================================

# 基础方案名称，用于输出目录和元数据标识
BASE_SCHEME = "balanced_step3_ready"
# Formal protocol 版本号
FORMAL_PROTOCOL_VERSION = "step2_formal_protocol_v2_2026_04_30"
# Prompt 版本号，用于追踪提示词变更
PROMPT_VERSION = "step2_msg_v1_2026_04_28"
# Step2 默认要求使用的生成模型
DEFAULT_GENERATOR_MODEL = "deepseek-v4-pro"
# 对 v4 系推理模型显式关闭 thinking，避免输出预算被 reasoning 通道吞掉
DEFAULT_GENERATOR_THINKING_TYPE = "disabled"
# 推理型模型至少需要为最终正文保留足够输出预算。
DEFAULT_MAX_OUTPUT_TOKENS = 128
# 默认 few-shot 资源路径
DEFAULT_PACKAGED_FEWSHOT_DB = "../../datasets/step2/delivery/current/fewshot_pool.db"
DEFAULT_FEWSHOT_SOURCE_CSV = "examples/synthetic_index_harder.csv"
DEFAULT_SOURCE_MANIFEST_PATH = (
    "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json"
)
# 默认 message gate report 文件名
DEFAULT_MESSAGE_GATE_REPORT_NAME = "message_gate_report.json"
# 默认 DeepSeek API Key 环境变量
DEFAULT_DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
RUN_PURPOSE_VALUES = {"formal", "api_smoke", "debug", "preflight"}
SENSITIVE_TOKEN_KEYWORDS = ("deepseek-api-key", "api-key", "token", "authorization", "secret", "password")

# 正则表达式：匹配标准 git diff 头（diff --git a/... b/...）
FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
# 正则表达式：匹配合并提交的 diff 头（diff --cc 或 diff --combined）
FILE_RE_COMBINED = re.compile(r"^diff --(?:cc|combined) (.+)$")
# 模块重叠策略集合：not_used（不使用）、prefer（优先）、require（必须）
MODULE_OVERLAP_POLICIES = {"not_used", "prefer", "require"}
# 有效的阈值方法
VALID_THRESHOLD_METHODS = {"kmeans_1d", "jenks_1d", "reference_quantile_band"}
# 有效的生成器提供商
VALID_GENERATOR_PROVIDERS = {"deepseek_api"}
# 有效的评分后端
VALID_SCORER_BACKENDS = {"bertscore_only_v1"}
# 源 CSV 必需的字段
REQUIRED_SOURCE_FIELDS = {"repo", "sha", "type", "subject", "message", "git_diff"}
LEGACY_SOURCE_LABEL_FIELDS = {"manual_label"}
CONSERVATIVE_SOURCE_LABEL_FIELDS = {"conservative_tier"}
# 匹配标签模板（如 "change 1", "intent 3" 等）
LABEL_TEMPLATE_RE = re.compile(r"\b(change|intent)\s*\d+\b", flags=re.IGNORECASE)
# 匹配常规提交前缀（如 "feat:", "fix(auth):" 等）
# 仅匹配小写 conventional-like 前缀，避免把 `RouterServer::router` 之类的符号误判成第二个前缀。
PREFIX_RE = re.compile(r"(?<!:)\b[a-z]+(?:\([^)]+\))?:")
# 匹配 "and" 连接词
AND_RE = re.compile(r"\band\b", flags=re.IGNORECASE)
# 匹配项目符号行（bullet）
BULLET_LINE_RE = re.compile(r"^\s*[-*]\s+", flags=re.MULTILINE)
# 匹配数字编号行（numbered list）
NUMBERED_LINE_RE = re.compile(r"^\s*\d+\.\s+", flags=re.MULTILINE)
# 匹配 issue id 形态（#123）
ISSUE_ID_RE = re.compile(r"#\d+")
# 通用 token 提取
WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
# 常见空泛短语（用于 relevance/style 监控）
GENERIC_PHRASE_PATTERNS = [
    re.compile(r"\bupdate code\b", flags=re.IGNORECASE),
    re.compile(r"\bimprove functionality\b", flags=re.IGNORECASE),
    re.compile(r"\bmisc(?:ellaneous)? changes?\b", flags=re.IGNORECASE),
    re.compile(r"\bcleanup\b", flags=re.IGNORECASE),
    re.compile(r"\bvarious fixes?\b", flags=re.IGNORECASE),
    re.compile(r"\bimprove system stability\b", flags=re.IGNORECASE),
]
# 轻量 imperative-like 动词词表（首词命中视为 1）
IMPERATIVE_HEAD_VERBS = {
    "add",
    "allow",
    "avoid",
    "bump",
    "clean",
    "convert",
    "create",
    "disable",
    "drop",
    "enable",
    "fix",
    "handle",
    "implement",
    "improve",
    "introduce",
    "migrate",
    "move",
    "optimize",
    "prevent",
    "refactor",
    "remove",
    "rename",
    "replace",
    "set",
    "simplify",
    "support",
    "update",
    "use",
}

# 默认配置文件路径
DEFAULT_CONFIG_PATH = "configs/step2_runtime_config.json"
DEFAULT_LOCAL_CONFIG_PATH = "configs/step2_runtime_config.local.json"


# 语义预校验关键词（用于 LLM 合成前过滤明显冲突对）
POSITIVE_POLARITY_KEYWORDS = {
    "add",
    "enable",
    "allow",
    "introduce",
    "support",
    "create",
    "improve",
    "upgrade",
    "update",
    "migrate",
    "refactor",
    "optimize",
}
NEGATIVE_POLARITY_KEYWORDS = {
    "remove",
    "disable",
    "drop",
    "deprecate",
    "delete",
    "revert",
    "rollback",
    "undo",
}
REVERT_PATTERN = re.compile(r"\b(revert|rollback|roll\s+back|undo)\b", flags=re.IGNORECASE)
SEMANTIC_TOKEN_RE = re.compile(r"[a-z0-9]+")
SEMANTIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "fix",
    "feat",
    "chore",
    "docs",
    "refactor",
    "test",
    "build",
    "style",
    "perf",
    "ci",
    "api",
    "code",
    "file",
}

# Source Pair Precheck 版本号
SOURCE_PAIR_PRECHECK_VERSION = "source_pair_precheck_v1_2026_04_30"
# 默认 generic 低信息短语
DEFAULT_GENERIC_MESSAGE_PHRASES = [
    "update",
    "fix bug",
    "cleanup",
    "minor update",
    "misc changes",
    "changes",
    "wip",
    "tweak",
    "improve",
    "refactor",
    "work in progress",
]
DEFAULT_GENERIC_MESSAGE_PHRASES_LOWER = {item.lower() for item in DEFAULT_GENERIC_MESSAGE_PHRASES}
FEAT_FIX_COLLAPSE_RISK_VERBS = {"update", "improve", "handle", "change", "adjust", "tweak", "cleanup"}
VALID_FEAT_FIX_REPAIR_GUIDANCE_MODES = {"none", "collapse_risk", "always"}
# type 兼容列表（无序 pair）
DEFAULT_TYPE_COMPAT_HIGH = {
    "fix+test",
    "feat+test",
    "feat+docs",
    "fix+docs",
    "fix+refactor",
    "perf+refactor",
    "fix+perf",
}
DEFAULT_TYPE_COMPAT_MEDIUM = {
    "fix+feat",
    "feat+refactor",
    "test+refactor",
    "docs+test",
}
DEFAULT_TYPE_FORBIDDEN_HEADS = {"revert", "merge", "release", "chore_release"}
# 常见 type 归一化映射
COMMIT_TYPE_NORMALIZE_MAP = {
    "feature": "feat",
    "features": "feat",
    "bugfix": "fix",
    "bug": "fix",
    "hotfix": "fix",
    "doc": "docs",
    "documentation": "docs",
    "tests": "test",
    "testing": "test",
    "perfomance": "perf",
    "performance": "perf",
    "optimize": "perf",
    "optimization": "perf",
    "chore-release": "chore_release",
    "chore/release": "chore_release",
}
# 默认 message gate 阈值
DEFAULT_MESSAGE_GATE_THRESHOLDS = {
    "gate_min_message_pass_rate": 0.10,
    "gate_max_message_reject_rate": 0.65,
    "gate_min_avg_message_quality_weight_non_reject": 0.20,
    "gate_max_fewshot_failure_rate": 0.20,
    "gate_max_precheck_skip_rate": 0.80,
    "gate_max_generation_failure_rate": 0.35,
    "gate_min_coverage_min_avg": 0.45,
    "gate_min_coverage_min_p10": 0.25,
}
DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_SAMPLE = 1
DEFAULT_FEWSHOT_WARN_IF_BELOW_REQUESTED = True
DEFAULT_FEWSHOT_GENERIC_RATE_WARN_THRESHOLD = 0.50
DEFAULT_FEWSHOT_FAILED_RATE_GATE_THRESHOLD = 0.10
DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES = 80
DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE = 3
DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_CHARS = 120
DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_TOKENS = 20
DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE = True
DEFAULT_FEWSHOT_ELIGIBILITY_POLICY = "train_split + (fewshot_eligible==1 if present) + (verified_multi_intent==1 if present) + style_clean"
DEFAULT_FEWSHOT_COMMON_SIGNATURES = [
    "fix+test",
    "feat+test",
    "fix+docs",
    "feat+docs",
    "fix+refactor",
    "feat+refactor",
    "docs+test",
    "perf+refactor",
    "fix+perf",
]
DIFF_EVIDENCE_CARD_VERSION = "diff_evidence_card_v1_2026_05_11"
DIFF_EVIDENCE_POLICY = "lightweight_diff_evidence_required"
DIFF_EVIDENCE_REQUIRED_FOR_FORMAL = True
DEFAULT_TAU_REALISM_LOW = 0.5
# 方向性语义冲突动词组
SEMANTIC_DIRECTIONAL_CONFLICT_PAIRS = [
    ({"add", "introduce"}, {"remove", "delete"}),
    ({"enable"}, {"disable"}),
    ({"increase", "raise"}, {"decrease", "lower"}),
    ({"create"}, {"delete", "remove"}),
    ({"introduce"}, {"revert"}),
    ({"rename"}, {"restore"}),
    ({"allow"}, {"prevent"}),
    ({"start"}, {"stop"}),
]
SEMANTIC_DIRECTIONAL_ALL_VERBS = set().union(
    *[left | right for left, right in SEMANTIC_DIRECTIONAL_CONFLICT_PAIRS]
)


def load_runtime_config(config_path: Path) -> dict[str, Any]:
    """加载运行时配置文件（JSON格式）

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典

    Raises:
        RuntimeError: 配置文件不存在、不是文件或格式错误时
    """
    if not config_path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")
    if not config_path.is_file():
        raise RuntimeError(f"Config path is not a file: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Config file must contain a JSON object: {config_path}")
    return payload


def cfg_value(cfg: dict[str, Any], key: str, default: Any) -> Any:
    """从配置字典中获取值，如果不存在则返回默认值"""
    return cfg.get(key, default)


def cfg_nested_value(cfg: dict[str, Any], path: list[str], default: Any) -> Any:
    current: Any = cfg
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def cfg_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    """从配置字典中获取布尔值，支持字符串和数字的布尔转换

    Args:
        cfg: 配置字典
        key: 配置键
        default: 默认值

    Returns:
        转换后的布尔值
    """
    value = cfg.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(default)


def model_supports_thinking_control(model_name: str) -> bool:
    normalized = safe_strip(model_name).lower()
    return normalized.startswith("deepseek-v4") or normalized.startswith("deepseek-v3.1")


def huggingface_hub_cache_root() -> Path:
    cache_from_env = safe_strip(os.environ.get("HF_HUB_CACHE", ""))
    if cache_from_env:
        return Path(cache_from_env)
    try:
        from huggingface_hub import constants as hf_constants

        return Path(hf_constants.HF_HUB_CACHE)
    except Exception:
        return Path.home() / ".cache" / "huggingface" / "hub"


def has_local_hf_model_snapshot(model_name: str) -> bool:
    normalized = safe_strip(model_name)
    if not normalized:
        return False
    snapshot_root = huggingface_hub_cache_root() / f"models--{normalized.replace('/', '--')}" / "snapshots"
    if not snapshot_root.exists():
        return False
    try:
        return any(path.is_file() for path in snapshot_root.rglob("*"))
    except Exception:
        return False


def bertscore_offline_env_overrides(model_name: str) -> dict[str, str]:
    if has_local_hf_model_snapshot(model_name):
        return {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    return {}


@contextlib.contextmanager
def temporary_env_overrides(overrides: dict[str, str]) -> Any:
    saved = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_print(*args: Any, **kwargs: Any) -> None:
    try:
        print(*args, **kwargs)
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


def build_difficulty_realism_runtime_config(args: argparse.Namespace) -> dict[str, Any]:
    loaded_cfg = getattr(args, "loaded_config", {})
    tau_from_config = cfg_nested_value(
        loaded_cfg if isinstance(loaded_cfg, dict) else {},
        ["difficulty_realism", "tau_realism_low"],
        None,
    )
    source = "config"
    tau_realism_low = safe_float(tau_from_config, DEFAULT_TAU_REALISM_LOW)
    if tau_from_config is None:
        tau_realism_low = DEFAULT_TAU_REALISM_LOW
        source = "default"
    return {
        "tau_realism_low": tau_realism_low,
        "tau_realism_low_source": source,
    }


def has_debug_override(args: argparse.Namespace) -> bool:
    """判断是否启用了任何 debug override（跳过 message 阶段或禁用 message gate）。

    debug override 会导致 run_valid_for_paper=False，不满足 paper 实验要求。
    """
    return bool(
        getattr(args, "debug_allow_skip_message_stage", False)
        or getattr(args, "debug_allow_disable_message_gate", False)
    )


def infer_run_purpose(args: argparse.Namespace) -> tuple[str, str]:
    """推导本次运行目的（formal/api_smoke/debug/preflight）及推导来源。

    优先级：
    1. --preflight 标志 → "preflight"
    2. --debug-mock-generator 或 generator_mode=mock → "debug"
    3. 任何 debug override → "debug"
    4. 显式 --run-purpose 参数
    5. 配置文件名包含 "smoke" → "api_smoke"
    6. 默认 → "formal"

    Returns:
        (run_purpose, source): 运行目的和推导来源标识
    """
    if bool(getattr(args, "preflight", False)):
        return "preflight", "cli_preflight"

    if bool(getattr(args, "debug_mock_generator", False)) or safe_strip(getattr(args, "generator_mode", "api")) == "mock":
        return "debug", "debug_mock_generator"

    if has_debug_override(args):
        return "debug", "debug_override"

    explicit = safe_strip(getattr(args, "run_purpose", ""))
    if explicit in RUN_PURPOSE_VALUES:
        return explicit, "explicit_config_or_cli"
    if explicit:
        return explicit, "explicit_config_or_cli_invalid"

    config_name = Path(safe_strip(getattr(args, "config", "")) or "runtime.json").name.lower()
    if "smoke" in config_name:
        return "api_smoke", "config_name_contains_smoke"

    return "formal", "default_formal"


def infer_preflight_target_run_purpose(args: argparse.Namespace) -> str:
    """推断 preflight 预检预期验证的运行目的（formal/api_smoke/debug）。

    用于决定 preflight 时是否要求 few-shot pool 满足 formal-ready 条件。
    优先从 loaded_config 中读取，其次从 CLI --run-purpose，再次从配置文件名推断。
    """
    loaded_cfg = getattr(args, "loaded_config", {})
    if isinstance(loaded_cfg, dict):
        cfg_value_raw = safe_strip(loaded_cfg.get("run_purpose", ""))
        if cfg_value_raw in {"formal", "api_smoke", "debug"}:
            return cfg_value_raw
    explicit = safe_strip(getattr(args, "run_purpose", ""))
    if explicit in {"formal", "api_smoke", "debug"}:
        return explicit
    config_name = Path(safe_strip(getattr(args, "config", "")) or "runtime.json").name.lower()
    if "smoke" in config_name:
        return "api_smoke"
    return "formal"


def compute_protocol_violations(args: argparse.Namespace) -> list[str]:
    """根据当前参数计算 formal protocol 违规项列表。

    检查项包括：
    - preflight_mode_not_formal: 处于 preflight 模式
    - mock_generator_mode: 使用 mock 生成器
    - message_stage_disabled: 跳过了 message 生成阶段
    - message_gate_disabled: 禁用了 message gate
    - few_shot_disabled: 禁用了 few-shot 检索
    - debug_override_used: 使用了 debug override
    - api_smoke_non_paper_run: API smoke 测试模式

    用于判断 run_valid_for_paper 和输出到 run_metadata.json。
    """
    violations: list[str] = []
    if bool(getattr(args, "preflight", False)):
        violations.append("preflight_mode_not_formal")
    if safe_strip(getattr(args, "generator_mode", "api")) == "mock":
        violations.append("mock_generator_mode")
    if bool(getattr(args, "skip_message_stage", False)):
        violations.append("message_stage_disabled")
    if not bool(getattr(args, "enable_message_gate", True)):
        violations.append("message_gate_disabled")
    if not bool(getattr(args, "fewshot_enabled", True)):
        violations.append("few_shot_disabled")
    if has_debug_override(args):
        violations.append("debug_override_used")
    if safe_strip(getattr(args, "run_purpose", "")) == "api_smoke":
        violations.append("api_smoke_non_paper_run")
    return violations


def is_run_valid_for_paper(args: argparse.Namespace) -> bool:
    """判断当前运行是否满足 paper-valid formal 协议要求。

    必须同时满足：
    - run_purpose == "formal"
    - 非 preflight 模式
    - 非 mock 生成器
    - message stage 已启用
    - message gate 已启用
    - few-shot 已启用
    - diff evidence 策略已启用（如果要求）
    - 未使用 debug override
    """
    return bool(
        safe_strip(getattr(args, "run_purpose", "")) == "formal"
        and not bool(getattr(args, "preflight", False))
        and safe_strip(getattr(args, "generator_mode", "api")) != "mock"
        and not bool(getattr(args, "skip_message_stage", False))
        and bool(getattr(args, "enable_message_gate", True))
        and bool(getattr(args, "fewshot_enabled", True))
        and (not bool(DIFF_EVIDENCE_REQUIRED_FOR_FORMAL) or bool(DIFF_EVIDENCE_POLICY))
        and not has_debug_override(args)
    )


def redact_argv(argv: list[str]) -> list[str]:
    """对 argv 中可能包含的敏感参数做脱敏处理。

    识别包含 deepseek-api-key、api-key、token、authorization、secret、password
    等关键词的参数，将其值替换为 ***REDACTED***。用于 run_metadata.json 中的
    argv 字段，防止 API key 泄漏。
    """
    redacted: list[str] = []
    redact_next = False
    for token in argv:
        if redact_next:
            redacted.append("***REDACTED***")
            redact_next = False
            continue
        if token.startswith("--"):
            if "=" in token:
                key, value = token.split("=", 1)
                normalized_key = key.lstrip("-").lower().replace("_", "-")
                if any(keyword in normalized_key for keyword in SENSITIVE_TOKEN_KEYWORDS):
                    redacted.append(f"{key}=***REDACTED***")
                else:
                    redacted.append(token)
                continue
            normalized_key = token.lstrip("-").lower().replace("_", "-")
            redacted.append(token)
            if any(keyword in normalized_key for keyword in SENSITIVE_TOKEN_KEYWORDS):
                redact_next = True
            continue
        redacted.append(token)
    return redacted


def cli_option_provided(argv: list[str], flag: str) -> bool:
    """判断 CLI 参数列表中是否显式提供了某个 --flag。

    支持两种形式：--flag=value 和 --flag value。
    用于区分"用户显式传参"和"使用默认值"的场景，
    如判断 API key 来源是 CLI 还是 config 还是环境变量。
    """
    prefix = f"--{flag}="
    exact = f"--{flag}"
    for token in argv:
        if token == exact or token.startswith(prefix):
            return True
    return False


def resolve_default_config_path() -> str:
    """返回默认配置路径，本地覆盖配置存在时优先使用。"""
    local_path = Path(DEFAULT_LOCAL_CONFIG_PATH)
    if local_path.exists() and local_path.is_file():
        return local_path.as_posix()
    return DEFAULT_CONFIG_PATH


def resolve_deepseek_api_key(args: argparse.Namespace) -> tuple[str, str]:
    """统一解析 DeepSeek API key 来源。

    优先级：
    1. config.deepseek_api_key（最高）
    2. --deepseek-api-key（仅当 config 为空时）
    3. DEEPSEEK_API_KEY 或 deepseek_api_key_env 指定的环境变量
    """
    loaded_config = getattr(args, "loaded_config", {}) or {}
    config_api_key = safe_strip(cfg_value(loaded_config, "deepseek_api_key", ""))
    if config_api_key:
        return config_api_key, "config"

    cli_api_key = safe_strip(getattr(args, "deepseek_api_key", ""))
    if cli_api_key and cli_option_provided(sys.argv, "deepseek-api-key"):
        return cli_api_key, "cli"

    api_key_env = safe_strip(getattr(args, "deepseek_api_key_env", ""))
    if api_key_env:
        env_api_key = safe_strip(os.environ.get(api_key_env))
        if env_api_key:
            return env_api_key, "env"

    return "", "missing"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数和配置文件

    采用两阶段解析：
    1. 先解析 --config 参数获取配置文件路径
    2. 加载配置文件后，用配置文件值作为默认值继续解析其他参数
    绝大多数 CLI 参数优先级高于配置文件；DeepSeek API key 例外，非空 config 值最高优先

    Returns:
        解析后的参数命名空间
    """
    # 第一阶段：仅解析 --config 以获取配置文件路径
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=resolve_default_config_path())
    pre_args, _ = pre_parser.parse_known_args(argv)
    config_path = Path(pre_args.config)
    try:
        config = load_runtime_config(config_path)
    except Exception as exc:
        pre_parser.error(f"Failed to load config from {config_path}: {exc}")

    # 第二阶段：定义所有参数，配置文件值作为默认值
    parser = argparse.ArgumentParser(description="Step2 Simple Multi-Intent 合成样本构建脚本")
    parser.add_argument(
        "--config",
        default=config_path.as_posix(),
        help="JSON config file path. Most CLI args override config values; non-empty config.deepseek_api_key has highest priority.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Validate whether the current environment can run a formal Step2 experiment.",
    )
    parser.add_argument(
        "--preflight-api-ping",
        action="store_true",
        help="During preflight, send one minimal generator request to validate remote API readiness.",
    )
    parser.add_argument(
        "--run-purpose",
        default=cfg_value(config, "run_purpose", ""),
        help="Optional explicit run purpose: formal | api_smoke | debug | preflight. Empty means auto-infer.",
    )
    # 源数据参数
    parser.add_argument(
        "--source-csv",
        default=cfg_value(
            config,
            "source_csv",
            "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv",
        ),
        help="Step2 source CSV. Must include A-tier rows and git_diff/message/subject/type fields.",
    )
    parser.add_argument(
        "--source-manifest-path",
        default=cfg_value(config, "source_manifest_path", DEFAULT_SOURCE_MANIFEST_PATH),
        help="Source dataset manifest used for formal asset validation.",
    )
    parser.add_argument(
        "--selected-pairs-jsonl",
        default=cfg_value(config, "selected_pairs_jsonl", ""),
        help="Optional pre-selected pair plan JSONL. When provided, skip pair mining and selection.",
    )
    parser.add_argument(
        "--selected-pairs-manifest",
        default=cfg_value(config, "selected_pairs_manifest", ""),
        help="Optional manifest JSON for the pre-selected pair plan.",
    )
    # 输出目录
    parser.add_argument(
        "--output-dir",
        default=cfg_value(config, "output_dir", "outputs/step2_balanced_step3_ready"),
    )
    parser.add_argument(
        "--progress-flush-every",
        type=int,
        default=cfg_value(config, "progress_flush_every", 0),
        help="Write partial progress artifacts every N processed samples. 0 disables partial flushing.",
    )
    parser.add_argument(
        "--sample-id-offset",
        type=int,
        default=cfg_value(config, "sample_id_offset", 0),
        help="Optional offset applied to generated sample ids. Useful for sharded full-scale runs.",
    )
    # 只处理 A-tier 的提交
    parser.add_argument("--manual-label", default=cfg_value(config, "manual_label", "A"), choices=["A"])
    # 每个样本融合的原料提交数（k）
    parser.add_argument("--intent-k", type=int, default=cfg_value(config, "intent_k", 2))
    # sweep 模式的最大 k（当 > intent_k 时触发 k 递增批次实验）
    parser.add_argument("--k-sweep-max", type=int, default=cfg_value(config, "k_sweep_max", 2))
    # 每个 repo 在构建 k-组合候选时最多尝试多少个组合（防止组合爆炸）
    parser.add_argument(
        "--group-combo-attempt-cap-per-repo",
        type=int,
        default=cfg_value(config, "group_combo_attempt_cap_per_repo", 50000),
    )
    # 每个 repo 最多保留多少个通过约束的候选组合
    parser.add_argument(
        "--group-candidate-cap-per-repo",
        type=int,
        default=cfg_value(config, "group_candidate_cap_per_repo", 3000),
    )
    # 目标生成样本数量
    parser.add_argument("--target-count", type=int, default=cfg_value(config, "target_count", 100))
    # 每个仓库最多选取的样本数
    parser.add_argument("--repo-cap", type=int, default=cfg_value(config, "repo_cap", 12))
    # 每种类型组合最多选取的样本数
    parser.add_argument("--type-pair-cap", type=int, default=cfg_value(config, "type_pair_cap", 25))
    parser.add_argument(
        "--selection-quality-priority",
        default=cfg_value(config, "selection_quality_priority", "legacy_guarded"),
        choices=["legacy", "legacy_guarded", "pair_quality"],
        help="How to prioritize candidate groups within the existing diversity buckets.",
    )
    parser.add_argument(
        "--selection-min-pair-quality-weight",
        type=float,
        default=cfg_value(config, "selection_min_pair_quality_weight", 0.42),
        help="Used by legacy_guarded to filter extremely low-quality non-skip candidate groups.",
    )
    # 合并后最大文件数
    parser.add_argument("--max-merged-files", type=int, default=cfg_value(config, "max_merged_files", 6))
    # 合并后最大变更行数
    parser.add_argument("--max-merged-lines", type=int, default=cfg_value(config, "max_merged_lines", 240))
    # 输出到 review 文件的样本数
    parser.add_argument("--review-samples", type=int, default=cfg_value(config, "review_samples", 6))
    # 随机种子，用于可复现的结果
    parser.add_argument("--seed", type=int, default=cfg_value(config, "seed", 42))
    parser.add_argument(
        "--min-target-ratio",
        type=float,
        default=cfg_value(config, "min_target_ratio", 1.0),
        help="Target coverage gate in [0, 1]. 1.0 means generated count must reach target_count.",
    )

    # 仅保留 single preset，允许 CLI 覆盖各项参数。
    parser.add_argument(
        "--preset",
        default=cfg_value(config, "preset", BASE_SCHEME),
        choices=[BASE_SCHEME],
        help="Single supported preset; keep for explicit metadata.",
    )

    # 类型过滤：是否要求两个不同的类型
    parser.add_argument("--require-different-type", dest="require_different_type", action="store_true")
    parser.add_argument("--allow-same-type", dest="require_different_type", action="store_false")
    parser.set_defaults(require_different_type=cfg_bool(config, "require_different_type", True))

    # 模块重叠策略
    parser.add_argument(
        "--module-overlap-policy",
        choices=sorted(MODULE_OVERLAP_POLICIES),
        default=cfg_value(config, "module_overlap_policy", None),
        help="Use one value from {not_used, prefer, require}. Defaults to `prefer`.",
    )
    parser.add_argument("--prefer-module-overlap", action="store_true")
    parser.add_argument("--require-module-overlap", action="store_true")
    # diff 块排序方式
    parser.add_argument(
        "--block-order",
        choices=["path_sorted", "round_robin"],
        default=cfg_value(config, "block_order", "round_robin"),
    )

    # ============================================================
    # Message 生成阶段参数
    # ============================================================
    message_stage_enabled_default = cfg_bool(
        config,
        "message_stage_enabled",
        (not cfg_bool(config, "skip_message_stage", False)),
    )
    parser.add_argument("--skip-message-stage", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--debug-allow-skip-message-stage",
        action="store_true",
        help="Debug only: allow bypassing mandatory LLM message generation.",
    )
    parser.set_defaults(skip_message_stage=(not message_stage_enabled_default))
    # 生成器提供商
    parser.add_argument(
        "--generator-provider",
        default=cfg_value(config, "generator_provider", "deepseek_api"),
        choices=sorted(VALID_GENERATOR_PROVIDERS),
    )
    parser.add_argument(
        "--generator-mode",
        default=cfg_value(config, "generator_mode", "api"),
        choices=["api", "mock"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--debug-mock-generator",
        action="store_true",
        help="Debug only: use a deterministic local mock generator instead of the real API.",
    )
    # 生成模型
    parser.add_argument("--generator-model", default=cfg_value(config, "generator_model", DEFAULT_GENERATOR_MODEL))
    parser.add_argument(
        "--generator-thinking-type",
        default=cfg_value(config, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
        choices=["enabled", "disabled"],
        help="Thinking mode for DeepSeek reasoning-capable models.",
    )
    # API 地址
    parser.add_argument(
        "--deepseek-base-url",
        default=cfg_value(config, "deepseek_base_url", "https://api.deepseek.com/v1/chat/completions"),
    )
    # API Key
    parser.add_argument(
        "--deepseek-api-key",
        default=cfg_value(config, "deepseek_api_key", ""),
        help="Fallback DeepSeek API key from CLI. Ignored when config.deepseek_api_key is non-empty.",
    )
    parser.add_argument(
        "--deepseek-api-key-env",
        default=cfg_value(config, "deepseek_api_key_env", DEFAULT_DEEPSEEK_API_KEY_ENV),
        help="Environment variable used as the final fallback for the DeepSeek API key.",
    )
    # API 超时时间（秒）
    parser.add_argument("--api-timeout-sec", type=int, default=cfg_value(config, "api_timeout_sec", 90))
    # 生成参数
    parser.add_argument("--temperature", type=float, default=cfg_value(config, "temperature", 0.2))
    parser.add_argument("--top-p", type=float, default=cfg_value(config, "top_p", 1.0))
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=cfg_value(config, "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS),
    )
    # 生成重试次数
    parser.add_argument("--max-generation-attempts", type=int, default=cfg_value(config, "max_generation_attempts", 2))
    # 压缩重试次数（当生成结果超长时）
    parser.add_argument(
        "--max-abstractive-compress-attempts",
        type=int,
        default=cfg_value(config, "max_abstractive_compress_attempts", 1),
    )
    # 重写重试次数
    parser.add_argument("--max-rewrite-attempts", type=int, default=cfg_value(config, "max_rewrite_attempts", 1))
    parser.add_argument(
        "--feat-fix-repair-guidance-mode",
        default=cfg_value(config, "feat_fix_repair_guidance_mode", "none"),
        choices=sorted(VALID_FEAT_FIX_REPAIR_GUIDANCE_MODES),
        help="Experimental repair guidance for feat+fix samples. Keep `none` for the formal baseline.",
    )
    # 最终强压缩重试次数（仅针对仍然超长的 repair 失败样本）
    parser.add_argument(
        "--max-final-strong-compress-attempts",
        type=int,
        default=cfg_value(config, "max_final_strong_compress_attempts", 1),
    )
    parser.add_argument(
        "--enable-final-strong-path-tail-compress",
        dest="enable_final_strong_path_tail_compress",
        action="store_true",
        help="Experimental: allow final strong compress to keep only the shortest identifiable path tail.",
    )
    parser.set_defaults(
        enable_final_strong_path_tail_compress=cfg_bool(config, "enable_final_strong_path_tail_compress", False)
    )
    # Prompt 版本
    parser.add_argument("--prompt-version", default=cfg_value(config, "prompt_version", PROMPT_VERSION))

    # ============================================================
    # Few-shot 检索参数
    # ============================================================
    # few-shot 样本数量
    parser.add_argument("--few-shot-k", type=int, default=cfg_value(config, "few_shot_k", 2))
    # few-shot 数据库路径
    parser.add_argument("--fewshot-db", default=cfg_value(config, "fewshot_db", ""))
    parser.add_argument(
        "--fewshot-build-manifest-path",
        default=cfg_value(config, "fewshot_build_manifest_path", ""),
        help="Formal-ready few-shot asset build manifest used for formal asset validation.",
    )
    parser.add_argument(
        "--fewshot-source-csv",
        default=cfg_value(config, "fewshot_source_csv", DEFAULT_FEWSHOT_SOURCE_CSV),
        help="Packaged CSV used to build the default few-shot pool when no DB is provided.",
    )
    # few-shot 表名
    parser.add_argument("--fewshot-table", default=cfg_value(config, "fewshot_table", "fewshot_examples"))
    parser.add_argument(
        "--fewshot-enabled",
        dest="fewshot_enabled",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(fewshot_enabled=cfg_bool(config, "fewshot_enabled", True))
    parser.add_argument(
        "--require-fewshot-pool",
        dest="require_fewshot_pool",
        action="store_true",
        help="Require a resolvable few-shot pool for formal Step2 runs.",
    )
    parser.set_defaults(require_fewshot_pool=cfg_bool(config, "require_fewshot_pool", True))
    # 检索查询版本
    parser.add_argument(
        "--retrieval-query-version",
        default=cfg_value(config, "retrieval_query_version", "sqlite_formal_kway_v2"),
    )
    parser.add_argument(
        "--few-shot-min-examples-per-sample",
        type=int,
        default=cfg_value(config, "few_shot_min_examples_per_sample", DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_SAMPLE),
    )
    parser.add_argument(
        "--few-shot-warn-if-below-requested",
        dest="few_shot_warn_if_below_requested",
        action="store_true",
        help="Warn when selected few-shot examples are below requested k.",
    )
    parser.add_argument(
        "--disable-few-shot-warn-if-below-requested",
        dest="few_shot_warn_if_below_requested",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(
        few_shot_warn_if_below_requested=cfg_bool(
            config,
            "few_shot_warn_if_below_requested",
            DEFAULT_FEWSHOT_WARN_IF_BELOW_REQUESTED,
        )
    )
    parser.add_argument(
        "--few-shot-generic-rate-warn-threshold",
        type=float,
        default=cfg_value(
            config,
            "few_shot_generic_rate_warn_threshold",
            DEFAULT_FEWSHOT_GENERIC_RATE_WARN_THRESHOLD,
        ),
    )
    parser.add_argument(
        "--few-shot-failed-rate-gate-threshold",
        type=float,
        default=cfg_value(
            config,
            "few_shot_failed_rate_gate_threshold",
            cfg_value(config, "gate_max_fewshot_failure_rate", DEFAULT_FEWSHOT_FAILED_RATE_GATE_THRESHOLD),
        ),
    )
    parser.add_argument(
        "--fewshot-min-total-examples",
        type=int,
        default=cfg_value(config, "fewshot_min_total_examples", DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES),
        help="Minimum few-shot pool size required for formal-ready runs.",
    )
    parser.add_argument(
        "--fewshot-min-examples-per-common-signature",
        type=int,
        default=cfg_value(
            config,
            "fewshot_min_examples_per_common_signature",
            DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
        ),
        help="Minimum examples per common signature required for formal-ready runs.",
    )
    parser.add_argument(
        "--fewshot-audit-strict-style",
        dest="fewshot_audit_strict_style",
        action="store_true",
        help="Treat style issues in few-shot pool as formal blockers.",
    )
    parser.add_argument(
        "--disable-fewshot-audit-strict-style",
        dest="fewshot_audit_strict_style",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(
        fewshot_audit_strict_style=cfg_bool(
            config,
            "fewshot_audit_strict_style",
            DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE,
        )
    )

    # ============================================================
    # 评分 / 阈值 / Gate 参数
    # ============================================================
    # 评分后端
    parser.add_argument(
        "--scorer-backend",
        default=cfg_value(config, "scorer_backend", "bertscore_only_v1"),
        choices=sorted(VALID_SCORER_BACKENDS),
    )
    # BERTScore 模型
    parser.add_argument("--bertscore-model", default=cfg_value(config, "bertscore_model", "roberta-large"))
    # BERTScore 语言
    parser.add_argument("--bertscore-lang", default=cfg_value(config, "bertscore_lang", "en"))
    # 是否使用 IDF 加权
    parser.add_argument("--bertscore-idf", action="store_true")
    parser.set_defaults(bertscore_idf=cfg_bool(config, "bertscore_idf", False))
    # 阈值方法
    parser.add_argument(
        "--threshold-method",
        default=cfg_value(config, "threshold_method", "kmeans_1d"),
        choices=sorted(VALID_THRESHOLD_METHODS),
    )
    # Message Gate 参考文件
    parser.add_argument("--message-gate-reference", default=cfg_value(config, "message_gate_reference", ""))
    # 参考分布的分位数
    parser.add_argument(
        "--reference-lower-quantile",
        type=float,
        default=cfg_value(config, "reference_lower_quantile", 0.05),
    )
    parser.add_argument(
        "--reference-upper-quantile",
        type=float,
        default=cfg_value(config, "reference_upper_quantile", 0.95),
    )
    # 是否启用 message gate
    parser.add_argument("--disable-message-gate", dest="enable_message_gate", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument(
        "--debug-allow-disable-message-gate",
        action="store_true",
        help="Debug only: allow bypassing the mandatory message gate.",
    )
    parser.set_defaults(
        enable_message_gate=cfg_bool(
            config,
            "message_gate_enabled",
            cfg_bool(config, "enable_message_gate", True),
        )
    )
    parser.add_argument(
        "--message-gate-report-path",
        default=cfg_value(config, "message_gate_report_path", ""),
        help="JSON path for the formal message gate report.",
    )
    parser.add_argument(
        "--gate-min-message-pass-rate",
        type=float,
        default=cfg_value(
            config,
            "gate_min_message_pass_rate",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_min_message_pass_rate"],
        ),
    )
    parser.add_argument(
        "--gate-max-message-reject-rate",
        type=float,
        default=cfg_value(
            config,
            "gate_max_message_reject_rate",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_max_message_reject_rate"],
        ),
    )
    parser.add_argument(
        "--gate-min-avg-message-quality-weight-non-reject",
        type=float,
        default=cfg_value(
            config,
            "gate_min_avg_message_quality_weight_non_reject",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_min_avg_message_quality_weight_non_reject"],
        ),
    )
    parser.add_argument(
        "--gate-max-fewshot-failure-rate",
        type=float,
        default=cfg_value(
            config,
            "gate_max_fewshot_failure_rate",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_max_fewshot_failure_rate"],
        ),
    )
    parser.add_argument(
        "--gate-max-precheck-skip-rate",
        type=float,
        default=cfg_value(
            config,
            "gate_max_precheck_skip_rate",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_max_precheck_skip_rate"],
        ),
    )
    parser.add_argument(
        "--gate-max-generation-failure-rate",
        type=float,
        default=cfg_value(
            config,
            "gate_max_generation_failure_rate",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_max_generation_failure_rate"],
        ),
    )
    parser.add_argument(
        "--gate-min-coverage-min-avg",
        type=float,
        default=cfg_value(
            config,
            "gate_min_coverage_min_avg",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_min_coverage_min_avg"],
        ),
    )
    parser.add_argument(
        "--gate-min-coverage-min-p10",
        type=float,
        default=cfg_value(
            config,
            "gate_min_coverage_min_p10",
            DEFAULT_MESSAGE_GATE_THRESHOLDS["gate_min_coverage_min_p10"],
        ),
    )
    parser.add_argument(
        "--allow-entangled-candidates",
        dest="allow_entangled_candidates",
        action="store_true",
        help="Allow limited shared-file candidate groups for Level D difficulty construction.",
    )
    parser.add_argument(
        "--disable-allow-entangled-candidates",
        dest="allow_entangled_candidates",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(allow_entangled_candidates=cfg_bool(config, "allow_entangled_candidates", False))
    parser.add_argument(
        "--max-shared-files-per-group",
        type=int,
        default=cfg_value(config, "max_shared_files_per_group", 0),
        help="Maximum shared files allowed when entangled candidates are enabled.",
    )

    # ============================================================
    # Source Pair Precheck 参数
    # ============================================================
    parser.add_argument("--enable-source-pair-precheck", dest="enable_source_pair_precheck", action="store_true")
    parser.add_argument("--disable-source-pair-precheck", dest="enable_source_pair_precheck", action="store_false")
    parser.set_defaults(enable_source_pair_precheck=cfg_bool(config, "enable_source_pair_precheck", True))
    parser.add_argument(
        "--precheck-duplicate-jaccard-threshold",
        type=float,
        default=cfg_value(config, "precheck_duplicate_jaccard_threshold", 0.92),
    )
    parser.add_argument(
        "--precheck-duplicate-seq-threshold",
        type=float,
        default=cfg_value(config, "precheck_duplicate_seq_threshold", 0.95),
    )
    parser.add_argument(
        "--precheck-moderate-similarity-threshold",
        type=float,
        default=cfg_value(config, "precheck_moderate_similarity_threshold", 0.75),
    )
    parser.add_argument(
        "--precheck-relation-low-threshold",
        type=float,
        default=cfg_value(config, "precheck_relation_low_threshold", 0.10),
    )
    parser.add_argument(
        "--precheck-heavy-overlap-threshold",
        type=float,
        default=cfg_value(config, "precheck_heavy_overlap_threshold", 0.70),
    )

    # ============================================================
    # 缓存路径参数
    # ============================================================
    parser.add_argument("--generation-cache-path", default=cfg_value(config, "generation_cache_path", ""))
    parser.add_argument("--bertscore-cache-path", default=cfg_value(config, "bertscore_cache_path", ""))
    parser.add_argument("--disable-generation-cache", dest="generation_cache_enabled", action="store_false")
    parser.add_argument("--disable-bertscore-cache", dest="bertscore_cache_enabled", action="store_false")
    parser.set_defaults(
        generation_cache_enabled=cfg_bool(config, "generation_cache_enabled", True),
        bertscore_cache_enabled=cfg_bool(config, "bertscore_cache_enabled", True),
    )

    args = parser.parse_args(argv)
    args.loaded_config = config
    args._invocation_argv = list(argv) if argv is not None else list(sys.argv[1:])
    # 先验证再派生，避免派生结果影响原始参数互斥检查语义
    validate_args(parser, args)
    resolve_derived_args(args)
    return args


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """验证参数合法性，遇到错误立即终止程序

    Args:
        parser: ArgumentParser 实例，用于输出错误
        args: 解析后的参数

    Raises:
        SystemExit: 参数验证失败时
    """
    # 模块重叠策略参数互斥检查
    if args.prefer_module_overlap and args.require_module_overlap:
        parser.error("`--prefer-module-overlap` and `--require-module-overlap` cannot be used together.")
    if args.module_overlap_policy and (args.prefer_module_overlap or args.require_module_overlap):
        parser.error("`--module-overlap-policy` cannot be mixed with legacy overlap flags.")
    # 目标比率必须在 [0, 1] 范围内
    if not 0.0 <= args.min_target_ratio <= 1.0:
        parser.error("`--min-target-ratio` must be in [0, 1].")
    # 参考分位数必须合法：0 <= low < high <= 1
    if not 0.0 <= args.reference_lower_quantile < args.reference_upper_quantile <= 1.0:
        parser.error("reference quantiles must satisfy 0 <= low < high <= 1.")
    effective_run_purpose, _ = infer_run_purpose(args)
    effective_generator_mode = "mock" if bool(getattr(args, "debug_mock_generator", False)) else safe_strip(
        getattr(args, "generator_mode", "api")
    )
    if safe_strip(effective_run_purpose) not in RUN_PURPOSE_VALUES:
        parser.error(
            f"`--run-purpose` must be one of {sorted(RUN_PURPOSE_VALUES)} when provided."
        )
    requires_mandatory_protocol = safe_strip(effective_run_purpose) in {"formal", "api_smoke"}
    if requires_mandatory_protocol and args.skip_message_stage:
        raise SystemExit("Message stage is mandatory in formal Step2 runs.")
    if requires_mandatory_protocol and (not args.enable_message_gate):
        raise SystemExit("Message gate is mandatory in formal Step2 runs.")
    if requires_mandatory_protocol and (not bool(getattr(args, "fewshot_enabled", True))):
        parser.error("Few-shot retrieval is mandatory in formal Step2 runs.")
    if args.skip_message_stage and args.enable_message_gate:
        parser.error("`--skip-message-stage` requires the message gate to be disabled in debug mode.")
    if int(args.intent_k) < 2:
        parser.error(f"Invalid intent_k={args.intent_k}. Formal Step2 requires intent_k >= 2.")
    if args.preflight_api_ping and not args.preflight:
        parser.error("`--preflight-api-ping` requires `--preflight`.")
    if args.preflight_api_ping and effective_generator_mode == "mock":
        parser.error("`--preflight-api-ping` cannot be used with mock generator mode.")

    # 检查必须为正整数（>0）的字段
    positive_int_fields = [
        "intent_k",
        "k_sweep_max",
        "group_combo_attempt_cap_per_repo",
        "group_candidate_cap_per_repo",
        "target_count",
        "repo_cap",
        "type_pair_cap",
        "max_merged_files",
        "max_merged_lines",
        "seed",
        "max_output_tokens",
        "max_generation_attempts",
        "max_abstractive_compress_attempts",
        "max_rewrite_attempts",
        "max_final_strong_compress_attempts",
        "few_shot_k",
        "few_shot_min_examples_per_sample",
        "fewshot_min_total_examples",
        "fewshot_min_examples_per_common_signature",
        "api_timeout_sec",
    ]
    for field_name in positive_int_fields:
        value = getattr(args, field_name)
        if value <= 0:
            parser.error(f"`--{field_name.replace('_', '-')}` must be a positive integer.")
    if args.k_sweep_max < args.intent_k:
        parser.error("`--k-sweep-max` must be >= `--intent-k`.")
    # review_samples 可以为 0，但不能为负数
    if args.review_samples < 0:
        parser.error("`--review-samples` must be >= 0.")
    if int(args.sample_id_offset) < 0:
        parser.error("`--sample-id-offset` must be >= 0.")
    # temperature 必须 >= 0
    if args.temperature < 0.0:
        parser.error("`--temperature` must be >= 0.")
    # top_p 必须在 (0, 1] 范围内
    if args.top_p <= 0.0 or args.top_p > 1.0:
        parser.error("`--top-p` must be in (0, 1].")
    # precheck 阈值必须在 [0,1]
    bounded_fields = [
        "precheck_duplicate_jaccard_threshold",
        "precheck_duplicate_seq_threshold",
        "precheck_moderate_similarity_threshold",
        "precheck_relation_low_threshold",
        "precheck_heavy_overlap_threshold",
        "gate_min_message_pass_rate",
        "gate_max_message_reject_rate",
        "gate_min_avg_message_quality_weight_non_reject",
        "gate_max_fewshot_failure_rate",
        "gate_max_precheck_skip_rate",
        "gate_max_generation_failure_rate",
        "gate_min_coverage_min_avg",
        "gate_min_coverage_min_p10",
        "few_shot_generic_rate_warn_threshold",
        "few_shot_failed_rate_gate_threshold",
        "max_shared_files_per_group",
    ]
    for field_name in bounded_fields:
        value = float(getattr(args, field_name))
        if value < 0.0 or value > 1.0:
            parser.error(f"`--{field_name.replace('_', '-')}` must be in [0, 1].")

    # 验证配置文件存在
    config_path = Path(args.config)
    if not config_path.exists() or not config_path.is_file():
        parser.error(f"`--config` must point to an existing JSON file: {config_path}")

    if args.preflight:
        return

    # 验证源 CSV 文件存在
    source_path = Path(args.source_csv)
    if not source_path.exists() or not source_path.is_file():
        parser.error(f"Input source CSV not found at expected path: {source_path}")
    if args.selected_pairs_jsonl:
        selected_pairs_path = Path(args.selected_pairs_jsonl)
        if not selected_pairs_path.exists() or not selected_pairs_path.is_file():
            parser.error(f"`--selected-pairs-jsonl` path is invalid: {selected_pairs_path}")
    if args.selected_pairs_manifest:
        selected_pairs_manifest_path = Path(args.selected_pairs_manifest)
        if not selected_pairs_manifest_path.exists() or not selected_pairs_manifest_path.is_file():
            parser.error(f"`--selected-pairs-manifest` path is invalid: {selected_pairs_manifest_path}")

    # 验证 few-shot 数据库文件（如果提供）
    if args.fewshot_db:
        fewshot_path = Path(args.fewshot_db)
        if not fewshot_path.exists() or not fewshot_path.is_file():
            parser.error(f"`--fewshot-db` path is invalid: {fewshot_path}")
    if args.fewshot_source_csv:
        fewshot_source_csv = Path(args.fewshot_source_csv)
        if fewshot_source_csv.exists() and not fewshot_source_csv.is_file():
            parser.error(f"`--fewshot-source-csv` must be a file when provided: {fewshot_source_csv}")

    # 验证 message gate 参考文件（如果提供）
    if args.message_gate_reference:
        ref_path = Path(args.message_gate_reference)
        if not ref_path.exists() or not ref_path.is_file():
            parser.error(f"`--message-gate-reference` path is invalid: {ref_path}")

    # 如果启用 message 阶段，需要额外验证依赖
    if not args.skip_message_stage:
        # 提前做依赖和 API key 校验，确保配置错误 fail fast。
        if args.scorer_backend == "bertscore_only_v1":
            try:
                with temporary_env_overrides(bertscore_offline_env_overrides(args.bertscore_model)):
                    from bert_score import BERTScorer as _  # noqa: F401
            except Exception as exc:  # pragma: no cover - runtime environment dependent
                parser.error(
                    "Coverage scoring dependency missing. Install `bert-score` or configure a supported scorer backend. "
                    f"detail={exc}"
                )
        # 验证 DeepSeek API key
        if args.generator_provider == "deepseek_api" and effective_generator_mode != "mock":
            api_key, source = resolve_deepseek_api_key(args)
            if not api_key:
                parser.error(
                    "Formal message generation requires config.deepseek_api_key, --deepseek-api-key, "
                    "or DEEPSEEK_API_KEY."
                )
            # 将解析后的 API key 存储到 args 中，供后续使用
            args._resolved_deepseek_api_key = api_key
            args._deepseek_api_key_source = source


def resolve_derived_args(args: argparse.Namespace) -> None:
    """解析派生参数，处理模块重叠策略和 API key

    将多种参数形式（module_overlap_policy / prefer_module_overlap / require_module_overlap）
    统一为 module_overlap_policy 字符串，并设置对应的布尔标志。

    Args:
        args: 参数命名空间（会被修改）
    """
    # 确定模块重叠策略：优先使用 module_overlap_policy，其次是指令式标志
    if args.module_overlap_policy is not None:
        overlap_policy = args.module_overlap_policy
    elif args.require_module_overlap:
        overlap_policy = "require"
    elif args.prefer_module_overlap:
        overlap_policy = "prefer"
    else:
        overlap_policy = "prefer"  # 默认策略
    args.module_overlap_policy = overlap_policy
    args.require_module_overlap = overlap_policy == "require"
    args.prefer_module_overlap = overlap_policy == "prefer"
    if getattr(args, "debug_mock_generator", False):
        args.generator_mode = "mock"
    run_purpose, run_purpose_source = infer_run_purpose(args)
    args.run_purpose = run_purpose
    args.run_purpose_source = run_purpose_source
    args.debug_override_used = has_debug_override(args)
    args.formal_protocol_flags = {
        "message_stage_mandatory": True,
        "message_gate_mandatory": True,
        "few_shot_mandatory": True,
        "debug_override_used": bool(args.debug_override_used),
    }
    args.protocol_violations = compute_protocol_violations(args)
    args.formal_run = bool(args.run_purpose == "formal")
    args.run_valid_for_paper = bool(is_run_valid_for_paper(args))

    # 解析 DeepSeek API key（如果使用的是 DeepSeek）
    if args.generator_provider == "deepseek_api":
        if not getattr(args, "_resolved_deepseek_api_key", ""):
            resolved, source = resolve_deepseek_api_key(args)
            args._resolved_deepseek_api_key = resolved
            args._deepseek_api_key_source = source
        if getattr(args, "generator_mode", "api") == "mock":
            args._resolved_deepseek_api_key = ""
            args._deepseek_api_key_source = "not_required_mock_mode"
    else:
        args._resolved_deepseek_api_key = ""
        args._deepseek_api_key_source = "not_used"

    # 设置缓存路径默认值（如果未指定）
    output_dir = Path(args.output_dir)
    if not args.generation_cache_path:
        args.generation_cache_path = str(output_dir / "cache" / "generation_cache.json")
    if not args.bertscore_cache_path:
        args.bertscore_cache_path = str(output_dir / "cache" / "bertscore_cache.json")
    if not getattr(args, "message_gate_report_path", ""):
        args.message_gate_report_path = str(output_dir / DEFAULT_MESSAGE_GATE_REPORT_NAME)
    args.message_stage_enabled = not bool(args.skip_message_stage)
    args.message_gate_enabled = bool(args.enable_message_gate)


# ============================================================
# 工具函数：哈希、种子、文件操作
# ============================================================

def stable_rank(seed: int, *parts: str) -> str:
    """生成稳定的排名哈希值，用于确定性随机排序

    Args:
        seed: 随机种子
        *parts: 参与哈希的字段

    Returns:
        SHA256 哈希值（十六进制字符串）
    """
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(f"{seed}|{payload}".encode("utf-8")).hexdigest()


def set_global_seed(seed: int) -> None:
    """设置全局随机种子，确保结果可复现

    设置 Python random、numpy（如果可用）、torch（如果可用）的随机种子。

    Args:
        seed: 随机种子值
    """
    random.seed(seed)
    try:  # pragma: no cover - optional dependency
        import numpy as np
        np.random.seed(seed)
    except Exception:
        pass
    try:  # pragma: no cover - optional dependency
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass


def compute_sha256(path: Path) -> str:
    """计算文件的 SHA256 哈希值

    Args:
        path: 文件路径

    Returns:
        SHA256 哈希值（十六进制字符串）
    """
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)  # 每次读取 1MB
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def count_text_lines(path: Path) -> int:
    """计算文本文件的行数"""
    line_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in handle:
            line_count += 1
    return line_count


def file_fingerprint(path: Path) -> dict[str, Any]:
    """生成文件的指纹信息，用于追踪输入文件的变化

    Returns:
        包含路径、大小、修改时间、行数、SHA256 的字典
    """
    resolved = path.expanduser().resolve(strict=True)
    stat = resolved.stat()
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "size_bytes": stat.st_size,
        "mtime_utc": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC).isoformat(),
        "line_count": count_text_lines(resolved),
        "sha256": compute_sha256(resolved),
    }


def canonical_json_hash(payload: Any) -> str:
    """对对象进行规范化的 JSON 序列化并计算 SHA256

    使用 sort_keys=True 和紧凑分隔符确保序列化结果唯一。

    Args:
        payload: 任意可 JSON 序列化的对象

    Returns:
        SHA256 哈希值
    """
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rows_fingerprint(rows: list[dict[str, Any]], fields: list[str], sort_key: str) -> dict[str, Any]:
    """计算数据行的指纹，用于追踪数据集的变化

    Args:
        rows: 数据行列表
        fields: 需要投影的字段
        sort_key: 排序键

    Returns:
        包含行数、字段列表和 SHA256 的字典
    """
    projected = []
    for row in rows:
        projected.append({field: row.get(field) for field in fields})
    projected.sort(key=lambda item: str(item.get(sort_key, "")))
    return {
        "row_count": len(projected),
        "fields": fields,
        "sha256": canonical_json_hash(projected),
    }


def normalize_header_key(raw_key: str) -> str:
    """规范化 CSV 表头键名

    移除 BOM、引号和空白字符，处理数据源中的异常列名。

    Args:
        raw_key: 原始键名

    Returns:
        规范化后的键名
    """
    key = (raw_key or "").replace("\ufeff", "").strip()
    # 数据源有异常列名：﻿"repo"
    key = key.strip('"').strip()
    return key


def normalize_row_keys(row: dict[str, Any]) -> dict[str, Any]:
    """规范化数据行的键名"""
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized[normalize_header_key(key)] = value
    return normalized


def safe_strip(value: Any) -> str:
    """安全地将值转换为去除空白的字符串

    Args:
        value: 任意值

    Returns:
        去除首尾空白的字符串，None 返回空字符串
    """
    if value is None:
        return ""
    return str(value).strip()


def repo_rel(path: Any) -> str:
    text = safe_strip(path)
    if not text:
        return ""
    path_obj = Path(text)
    if not path_obj.is_absolute() and not text.startswith("."):
        return path_obj.as_posix()
    try:
        return str(path_obj.resolve().relative_to(REPO_ROOT.resolve()))
    except Exception:
        return text


PATH_FIELD_EXACT = {
    "candidate_csv",
    "fewshot_build_manifest_path",
    "input_csv",
    "output_csv",
    "path",
    "report_dir",
    "report_path",
    "resolved_db",
    "review_sheet_csv",
    "source_csv",
    "source_manifest_path",
    "step2_source_csv",
}
PATH_FIELD_TOKENS = ("_path", "_dir", "_csv", "_db", "_manifest")


def is_path_field(field_name: str) -> bool:
    key = safe_strip(field_name)
    if not key:
        return False
    return key in PATH_FIELD_EXACT or any(token in key for token in PATH_FIELD_TOKENS)


def relativize_repo_paths(value: Any, *, field_name: str = "") -> Any:
    if isinstance(value, dict):
        return {key: relativize_repo_paths(item, field_name=key) for key, item in value.items()}
    if isinstance(value, list):
        return [relativize_repo_paths(item, field_name=field_name) for item in value]
    if isinstance(value, str) and is_path_field(field_name):
        return repo_rel(value)
    return value


def parse_optional_float(value: Any, default: float) -> float:
    """将可选数值字段解析为 float，解析失败时回退到默认值。"""
    text = safe_strip(value)
    if not text:
        return float(default)
    try:
        return float(text)
    except (TypeError, ValueError):
        return float(default)


def canonicalize_type(raw_type: str) -> str:
    """归一化 commit type，作为全流程统一类型签名口径。"""
    normalized = safe_strip(raw_type).lower().replace(" ", "_")
    if not normalized:
        return ""
    normalized = normalized.replace("-", "_").replace("/", "_")
    normalized = COMMIT_TYPE_NORMALIZE_MAP.get(normalized, normalized)
    m = re.match(r"^([a-z_]+)\(", normalized)
    if m:
        normalized = m.group(1)
    return normalized


def raw_type_signature(types: list[str]) -> str:
    """保留原始 type 信息的稳定签名。"""
    cleaned = [safe_strip(item) for item in types if safe_strip(item)]
    return "+".join(sorted(cleaned))


def canonical_type_signature(types: list[str]) -> str:
    """将 type 列表规范化后构造成稳定 k-way 签名。"""
    canonical = [canonicalize_type(item) for item in types if canonicalize_type(item)]
    return "+".join(sorted(canonical))


def signature_types(signature: str) -> list[str]:
    """从 `a+b+c` 形式的签名中恢复 type 列表。"""
    return [safe_strip(item) for item in safe_strip(signature).split("+") if safe_strip(item)]


def geometric_mean(values: list[float]) -> float:
    """计算几何平均，要求输入均为正数。"""
    positive = [float(value) for value in values if float(value) > 0.0]
    if not positive:
        return 0.0
    return float(math.exp(sum(math.log(value) for value in positive) / len(positive)))


# ============================================================
# 代码变更分析相关函数
# ============================================================

def infer_module_set(file_paths: list[str]) -> set[str]:
    """从文件路径列表推断涉及的模块（顶层目录）

    Args:
        file_paths: 文件路径列表

    Returns:
        模块名称集合（顶层目录名）
    """
    modules: set[str] = set()
    for file_path in file_paths:
        normalized = safe_strip(file_path).lstrip("./")
        if not normalized:
            continue
        # 取第一个路径组件作为模块名
        modules.add(normalized.split("/", 1)[0])
    return modules


def first_nonempty_line(text: str) -> str:
    """获取文本中第一个非空行"""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def split_file_blocks(diff: str) -> list[dict[str, Any]]:
    """将 git diff 文本分割为按文件组织的块

    Args:
        diff: git diff 文本

    Returns:
        包含 file_path 和 text 的字典列表
    """
    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_path = ""
    for line in diff.splitlines():
        match = FILE_RE.match(line)
        combined_match = FILE_RE_COMBINED.match(line)
        # 遇到新文件，保存当前块并开始新块
        if match:
            if current_lines:
                blocks.append({"file_path": current_path, "text": "\n".join(current_lines)})
            current_path = match.group(2)
            current_lines = [line]
        elif combined_match:
            if current_lines:
                blocks.append({"file_path": current_path, "text": "\n".join(current_lines)})
            current_path = combined_match.group(1)
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)
    if current_lines:
        blocks.append({"file_path": current_path, "text": "\n".join(current_lines)})
    return blocks


def estimate_changed_lines(diff: str) -> int:
    """估算 diff 中的变更行数（+/- 行）"""
    count = 0
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


def normalize_diff_path(path: str) -> str:
    """规范化 diff 路径表示（移除 a/、b/ 前缀）"""
    normalized = safe_strip(path)
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return normalized


def collect_diff_path_events(diff: str) -> dict[str, Any]:
    """从 diff 文本提取路径事件（用于文件冲突校验）"""
    touched_paths: set[str] = set()
    deleted_paths: set[str] = set()
    added_paths: set[str] = set()
    rename_pairs: set[tuple[str, str]] = set()
    copy_pairs: set[tuple[str, str]] = set()

    current_from = ""
    current_to = ""
    pending_rename_from = ""
    pending_copy_from = ""

    for raw_line in diff.splitlines():
        line = raw_line.strip()
        match = FILE_RE.match(raw_line)
        combined_match = FILE_RE_COMBINED.match(raw_line)
        if match:
            current_from = normalize_diff_path(match.group(1))
            current_to = normalize_diff_path(match.group(2))
            if current_from and current_from != "/dev/null":
                touched_paths.add(current_from)
            if current_to and current_to != "/dev/null":
                touched_paths.add(current_to)
            pending_rename_from = ""
            pending_copy_from = ""
            continue
        if combined_match:
            current_from = ""
            current_to = normalize_diff_path(combined_match.group(1))
            if current_to and current_to != "/dev/null":
                touched_paths.add(current_to)
            pending_rename_from = ""
            pending_copy_from = ""
            continue

        if line.startswith("rename from "):
            pending_rename_from = normalize_diff_path(line[len("rename from ") :])
            if pending_rename_from:
                touched_paths.add(pending_rename_from)
            continue
        if line.startswith("rename to "):
            rename_to = normalize_diff_path(line[len("rename to ") :])
            if rename_to:
                touched_paths.add(rename_to)
            if pending_rename_from and rename_to:
                rename_pairs.add((pending_rename_from, rename_to))
            pending_rename_from = ""
            continue
        if line.startswith("copy from "):
            pending_copy_from = normalize_diff_path(line[len("copy from ") :])
            if pending_copy_from:
                touched_paths.add(pending_copy_from)
            continue
        if line.startswith("copy to "):
            copy_to = normalize_diff_path(line[len("copy to ") :])
            if copy_to:
                touched_paths.add(copy_to)
            if pending_copy_from and copy_to:
                copy_pairs.add((pending_copy_from, copy_to))
            pending_copy_from = ""
            continue

        if line.startswith("deleted file mode "):
            deleted_path = current_from or current_to
            deleted_path = normalize_diff_path(deleted_path)
            if deleted_path and deleted_path != "/dev/null":
                deleted_paths.add(deleted_path)
                touched_paths.add(deleted_path)
            continue
        if line.startswith("new file mode "):
            added_path = normalize_diff_path(current_to)
            if added_path and added_path != "/dev/null":
                added_paths.add(added_path)
                touched_paths.add(added_path)
            continue

        if line.startswith("--- "):
            old_path = normalize_diff_path(line[4:])
            if old_path == "/dev/null":
                added_path = normalize_diff_path(current_to)
                if added_path:
                    added_paths.add(added_path)
                    touched_paths.add(added_path)
            elif old_path:
                touched_paths.add(old_path)
            continue
        if line.startswith("+++ "):
            new_path = normalize_diff_path(line[4:])
            if new_path == "/dev/null":
                deleted_path = normalize_diff_path(current_from or current_to)
                if deleted_path:
                    deleted_paths.add(deleted_path)
                    touched_paths.add(deleted_path)
            elif new_path:
                touched_paths.add(new_path)
            continue

    return {
        "touched_paths": sorted(touched_paths),
        "deleted_paths": sorted(deleted_paths),
        "added_paths": sorted(added_paths),
        "rename_pairs": sorted(rename_pairs),
        "copy_pairs": sorted(copy_pairs),
    }


def tokenize_semantic_text(text: str) -> set[str]:
    """将文本规范化为语义 token 集合（去停用词）"""
    normalized = re.sub(r"[/_.:\-]+", " ", text.lower())
    tokens = set()
    for token in SEMANTIC_TOKEN_RE.findall(normalized):
        if len(token) < 3:
            continue
        if token in SEMANTIC_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.add(token)
    return tokens


def classify_action_polarity(source: dict[str, Any]) -> str:
    """基于 subject/message 判断动作极性：positive/negative/mixed/neutral"""
    text = f"{safe_strip(source.get('subject'))} {safe_strip(source.get('commit_message'))}".lower()
    tokens = set(SEMANTIC_TOKEN_RE.findall(text))
    has_positive = any(keyword in tokens for keyword in POSITIVE_POLARITY_KEYWORDS)
    has_negative = any(keyword in tokens for keyword in NEGATIVE_POLARITY_KEYWORDS)
    if has_positive and has_negative:
        return "mixed"
    if has_positive:
        return "positive"
    if has_negative:
        return "negative"
    return "neutral"


def source_semantic_signature(source: dict[str, Any]) -> dict[str, Any]:
    """抽取提交的语义签名（实体、极性、是否回滚、规范化签名）"""
    subject = safe_strip(source.get("subject"))
    commit_message = safe_strip(source.get("commit_message"))
    file_paths = [safe_strip(path) for path in source.get("file_paths", []) if safe_strip(path)]
    modules = [safe_strip(module).lower() for module in source.get("module_set", set()) if safe_strip(module)]

    subject_tokens = tokenize_semantic_text(subject)
    message_tokens = tokenize_semantic_text(commit_message)
    path_tokens = tokenize_semantic_text(" ".join(file_paths))
    module_tokens = tokenize_semantic_text(" ".join(modules))
    entity_tokens = subject_tokens | message_tokens | path_tokens | module_tokens

    return {
        "entity_tokens": entity_tokens,
        "subject_signature": "|".join(sorted(subject_tokens)),
        "message_signature": "|".join(sorted(message_tokens)),
        "polarity": classify_action_polarity(source),
        "is_revert": bool(REVERT_PATTERN.search(f"{subject}\n{commit_message}")),
    }


def premerge_file_conflict_reasons(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """检测文件层冲突，返回命中规则代码列表"""
    reasons: list[str] = []
    left_events = left["path_events"]
    right_events = right["path_events"]

    left_touched = set(left_events["touched_paths"])
    right_touched = set(right_events["touched_paths"])
    left_deleted = set(left_events["deleted_paths"])
    right_deleted = set(right_events["deleted_paths"])

    if left_touched & right_touched:
        reasons.append("file_path_overlap")

    left_pairs = list(left_events["rename_pairs"]) + list(left_events["copy_pairs"])
    right_pairs = list(right_events["rename_pairs"]) + list(right_events["copy_pairs"])
    left_rename_copy_hits = any((src in right_touched or dst in right_touched) for src, dst in left_pairs)
    right_rename_copy_hits = any((src in left_touched or dst in left_touched) for src, dst in right_pairs)
    if left_rename_copy_hits or right_rename_copy_hits:
        reasons.append("file_rename_or_copy_conflict")

    left_modified = left_touched - left_deleted
    right_modified = right_touched - right_deleted
    if (left_deleted & right_modified) or (right_deleted & left_modified):
        reasons.append("file_delete_modify_conflict")
    return reasons


def premerge_semantic_conflict_reasons(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """检测语义层冲突，返回命中规则代码列表"""
    reasons: list[str] = []
    left_sig = source_semantic_signature(left)
    right_sig = source_semantic_signature(right)

    entity_overlap = left_sig["entity_tokens"] & right_sig["entity_tokens"]
    left_polarity = left_sig["polarity"]
    right_polarity = right_sig["polarity"]

    if entity_overlap and {left_polarity, right_polarity} == {"positive", "negative"}:
        reasons.append("semantic_opposite_polarity_overlap")

    if entity_overlap and (left_sig["is_revert"] != right_sig["is_revert"]) and (left_sig["is_revert"] or right_sig["is_revert"]):
        reasons.append("semantic_revert_overlap")

    if left_sig["subject_signature"] and left_sig["subject_signature"] == right_sig["subject_signature"]:
        reasons.append("semantic_duplicate_signature")
    elif left_sig["message_signature"] and left_sig["message_signature"] == right_sig["message_signature"]:
        reasons.append("semantic_duplicate_signature")
    return reasons


def premerge_validate_pair(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    allow_file_path_overlap_only: bool = False,
) -> dict[str, Any]:
    """LLM 前置校验：文件冲突 + 语义冲突（命中即拒绝）"""
    file_conflict_reasons = premerge_file_conflict_reasons(left, right)
    semantic_conflict_reasons = premerge_semantic_conflict_reasons(left, right)
    if allow_file_path_overlap_only:
        remaining_file_conflicts = [reason for reason in file_conflict_reasons if reason != "file_path_overlap"]
        if not remaining_file_conflicts and not semantic_conflict_reasons:
            file_conflict_reasons = []
    reasons = file_conflict_reasons + semantic_conflict_reasons
    return {
        "passed": not reasons,
        "reasons": reasons,
        "file_conflict_reasons": file_conflict_reasons,
        "semantic_conflict_reasons": semantic_conflict_reasons,
        "file_conflict": bool(file_conflict_reasons),
        "semantic_conflict": bool(semantic_conflict_reasons),
    }


# ============================================================
# Source Pair Precheck (Step2 before LLM generation)
# ============================================================

def normalize_repo_name(payload: dict[str, Any]) -> str:
    """归一化 repo 字段，兼容异常列名。"""
    for key in ("repo", '"repo"', '\ufeff"repo"', "\ufeffrepo"):
        value = safe_strip(payload.get(key))
        if value:
            return value
    return ""


def normalize_commit_type_for_precheck(raw_type: str) -> str:
    """保守归一化 commit type。"""
    return canonicalize_type(raw_type)


def canonical_type_pair(type_left: str, type_right: str) -> str:
    """将两个 commit type 规范化后组成稳定的 pair 签名（如 "fix+test"）。"""
    return canonical_type_signature([type_left, type_right])


def extract_pair_precheck_config(config: dict[str, Any] | argparse.Namespace | None) -> dict[str, Any]:
    """抽取 Source Pair Precheck 配置，支持 dict / argparse.Namespace。"""
    if config is None:
        cfg = {}
    elif isinstance(config, argparse.Namespace):
        cfg = vars(config)
    elif hasattr(config, "__dict__"):
        cfg = vars(config)
    else:
        cfg = dict(config)

    generic_phrases = cfg.get("precheck_generic_phrases", DEFAULT_GENERIC_MESSAGE_PHRASES)
    if not isinstance(generic_phrases, list):
        generic_phrases = DEFAULT_GENERIC_MESSAGE_PHRASES

    high_pairs = cfg.get("precheck_type_compat_high", sorted(DEFAULT_TYPE_COMPAT_HIGH))
    medium_pairs = cfg.get("precheck_type_compat_medium", sorted(DEFAULT_TYPE_COMPAT_MEDIUM))
    forbidden_heads = cfg.get("precheck_type_forbidden_heads", sorted(DEFAULT_TYPE_FORBIDDEN_HEADS))

    high_pair_set = {canonical_type_pair(*item.split("+", 1)) if "+" in item else item for item in high_pairs}
    medium_pair_set = {canonical_type_pair(*item.split("+", 1)) if "+" in item else item for item in medium_pairs}
    forbidden_head_set = {normalize_commit_type_for_precheck(item) for item in forbidden_heads}

    return {
        "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
        "duplicate_jaccard_threshold": float(cfg.get("precheck_duplicate_jaccard_threshold", 0.92)),
        "duplicate_seq_threshold": float(cfg.get("precheck_duplicate_seq_threshold", 0.95)),
        "moderate_similarity_threshold": float(cfg.get("precheck_moderate_similarity_threshold", 0.75)),
        "relation_low_threshold": float(cfg.get("precheck_relation_low_threshold", 0.10)),
        "heavy_overlap_threshold": float(cfg.get("precheck_heavy_overlap_threshold", 0.70)),
        "generic_phrases": [safe_strip(item).lower() for item in generic_phrases if safe_strip(item)],
        "type_compat_high": sorted(high_pair_set),
        "type_compat_medium": sorted(medium_pair_set),
        "type_forbidden_heads": sorted(forbidden_head_set),
    }


def precheck_tokenize_text(text: str) -> set[str]:
    """将文本分词为小写 token 集合（过滤长度 < 2 的 token）。

    用于 Source Pair Precheck 中的文本相似度计算（Jaccard、序列比对等）。
    """
    tokens = set()
    for token in WORD_TOKEN_RE.findall(safe_strip(text).lower()):
        if len(token) < 2:
            continue
        tokens.add(token)
    return tokens


def jaccard_similarity(left_tokens: set[str], right_tokens: set[str]) -> float:
    """计算两个 token 集合的 Jaccard 相似度。

    Jaccard = |A ∩ B| / |A ∪ B|。两个空集合返回 1.0，一个空一个非空返回 0.0。
    用于 Source Pair Precheck 中检测 near-duplicate 和文本重叠。
    """
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return float(len(left_tokens & right_tokens) / len(union))


def is_generic_low_information_message(text: str, generic_phrases: list[str]) -> bool:
    """检测文本是否为低信息量的泛化消息（如 "update", "fix bug", "cleanup" 等）。

    判定逻辑：
    1. 空文本直接判定为泛化
    2. 包含预定义的泛化短语则判定为泛化
    3. 过短（<=3 token）且几乎全部由泛化词构成则判定为泛化

    用于 Source Pair Precheck 中过滤两个提交的消息都过于泛化的情况。
    """
    normalized = safe_strip(text).lower()
    if not normalized:
        return True
    for phrase in generic_phrases:
        if phrase and phrase in normalized:
            return True
    compact = normalized.replace("-", " ").replace("_", " ")
    # 过短且几乎只包含泛化词
    tokens = precheck_tokenize_text(compact)
    generic_token_bank = set()
    for phrase in generic_phrases:
        generic_token_bank.update(precheck_tokenize_text(phrase))
    if tokens and len(tokens) <= 3 and tokens.issubset(generic_token_bank | {"change", "changes", "code"}):
        return True
    return False


def has_complementary_relation(type_left: str, type_right: str) -> bool:
    """判断两个 commit type 是否具有互补关系。

    互补关系包括：
    - 任一类型是 "test"（fix+test, feat+test 等）
    - 任一类型是 "docs"（fix+docs, feat+docs 等）

    互补对在 near-duplicate 检测中会被豁免，因为它们天然意图不同。
    """
    left = normalize_commit_type_for_precheck(type_left)
    right = normalize_commit_type_for_precheck(type_right)
    pair = {left, right}
    if len(pair) < 2:
        return False
    if "test" in pair and len(pair) == 2:
        return True
    if "docs" in pair and len(pair) == 2:
        return True
    return False


def semantic_direction_conflict_score(left_text: str, right_text: str) -> tuple[float, str, list[str]]:
    """方向性语义冲突评分：检测两个提交消息是否存在语义方向矛盾。

    返回三元组 (score, label, triggered_rules)：
    - score=1.0, "compatible": 无方向冲突
    - score=0.5, "unclear": 存在方向矛盾动词但无共同操作对象，判定不确定
    - score=0.0, "contradictory": 存在方向矛盾动词且有共同操作对象，判定冲突

    检测规则：对每对方向性矛盾动词组（如 add/remove, enable/disable），
    如果两个文本分别命中对立方向且共享操作对象 token，则判定为冲突。
    """
    left_tokens = precheck_tokenize_text(left_text)
    right_tokens = precheck_tokenize_text(right_text)
    left_objects = left_tokens - SEMANTIC_DIRECTIONAL_ALL_VERBS
    right_objects = right_tokens - SEMANTIC_DIRECTIONAL_ALL_VERBS
    overlap_objects = left_objects & right_objects
    triggered: list[str] = []
    ambiguous = False
    for pos_set, neg_set in SEMANTIC_DIRECTIONAL_CONFLICT_PAIRS:
        left_pos = bool(left_tokens & pos_set)
        left_neg = bool(left_tokens & neg_set)
        right_pos = bool(right_tokens & pos_set)
        right_neg = bool(right_tokens & neg_set)
        contradictory = (left_pos and right_neg) or (left_neg and right_pos)
        if not contradictory:
            continue
        rule_name = f"semantic_direction:{'+'.join(sorted(pos_set))}_vs_{'+'.join(sorted(neg_set))}"
        if overlap_objects:
            triggered.append(rule_name)
            return 0.0, "contradictory", triggered
        ambiguous = True
        triggered.append(rule_name)
    if ambiguous:
        return 0.5, "unclear", triggered
    return 1.0, "compatible", triggered


def evaluate_optional_git_merge_check(
    left: dict[str, Any],
    right: dict[str, Any],
    git_context: dict[str, Any] | None,
) -> tuple[float, str, bool]:
    """可选的 git merge 冲突检查。

    通过外部注入的 check_merge_conflict_fn 钩子来检测两个提交是否可以在
    git 层面干净合并。默认 not_available，不阻塞主流程。

    Args:
        left: 左侧提交数据
        right: 右侧提交数据
        git_context: 可选的 git 上下文，包含 check_merge_conflict_fn 钩子

    Returns:
        (score, method, available)：
        - score: 1.0=通过, 0.0=冲突
        - method: 检查方法标识
        - available: 是否实际执行了检查
    """
    if not git_context:
        return 1.0, "not_available", False
    checker = git_context.get("check_merge_conflict_fn")
    if callable(checker):
        try:
            ok = bool(checker(left, right, git_context))
        except Exception:
            ok = False
        return (1.0 if ok else 0.0), "external_hook", True
    return 1.0, "not_available", False


def run_source_pair_precheck(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    config: dict[str, Any] | argparse.Namespace | None,
    git_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行 Step2 source pair precheck。"""
    cfg = extract_pair_precheck_config(config)
    rules_triggered: list[str] = []
    warning_reasons: list[str] = []
    precheck_status = "pass"
    precheck_skip_reason = ""

    left_repo = normalize_repo_name(left)
    right_repo = normalize_repo_name(right)
    left_sha = safe_strip(left.get("sha"))
    right_sha = safe_strip(right.get("sha"))
    left_subject = safe_strip(left.get("subject"))
    right_subject = safe_strip(right.get("subject"))
    left_message = safe_strip(left.get("commit_message") or left.get("message"))
    right_message = safe_strip(right.get("commit_message") or right.get("message"))
    left_type = normalize_commit_type_for_precheck(safe_strip(left.get("type")))
    right_type = normalize_commit_type_for_precheck(safe_strip(right.get("type")))
    type_pair = canonical_type_pair(left_type, right_type)

    scores = {
        "merge": 1.0,
        "semantic": 1.0,
        "type_compatibility": 1.0,
        "non_duplicate": 1.0,
        "relation": 1.0,
        "input_message": 1.0,
    }

    # ----------------------------
    # Hard skip rules: input integrity
    # ----------------------------
    if not left_repo or not right_repo or left_repo != right_repo:
        precheck_status = "skip"
        precheck_skip_reason = "different_repo_after_normalization"
        rules_triggered.append(precheck_skip_reason)
    if not precheck_skip_reason and (not left_sha or not right_sha or left_sha == right_sha):
        precheck_status = "skip"
        precheck_skip_reason = "same_or_missing_sha"
        rules_triggered.append(precheck_skip_reason)
    if not precheck_skip_reason and (not left_subject or not right_subject or not left_message or not right_message):
        precheck_status = "skip"
        precheck_skip_reason = "empty_subject_or_message"
        rules_triggered.append(precheck_skip_reason)

    # ----------------------------
    # Generic message risk
    # ----------------------------
    left_generic = is_generic_low_information_message(
        f"{left_subject} {left_message}",
        cfg["generic_phrases"],
    )
    right_generic = is_generic_low_information_message(
        f"{right_subject} {right_message}",
        cfg["generic_phrases"],
    )
    if not precheck_skip_reason and left_generic and right_generic:
        scores["input_message"] = 0.0
        precheck_status = "skip"
        precheck_skip_reason = "both_messages_generic_low_information"
        rules_triggered.append(precheck_skip_reason)
    elif (left_generic or right_generic) and not precheck_skip_reason:
        scores["input_message"] = 0.6
        warning_reasons.append("one_message_generic_low_information")
        rules_triggered.append("warn_one_message_generic_low_information")

    # ----------------------------
    # Type compatibility
    # ----------------------------
    forbidden = left_type in cfg["type_forbidden_heads"] or right_type in cfg["type_forbidden_heads"]
    if forbidden and not precheck_skip_reason:
        scores["type_compatibility"] = 0.0
        precheck_status = "skip"
        precheck_skip_reason = "forbidden_type_pair"
        rules_triggered.append(precheck_skip_reason)
    elif type_pair in cfg["type_compat_high"]:
        scores["type_compatibility"] = 1.0
    elif type_pair in cfg["type_compat_medium"]:
        scores["type_compatibility"] = 0.8
        warning_reasons.append("medium_type_compatibility")
        rules_triggered.append("warn_medium_type_compatibility")
    else:
        scores["type_compatibility"] = 0.6
        warning_reasons.append("unknown_type_pair")
        rules_triggered.append("warn_unknown_type_pair")

    # ----------------------------
    # Semantic contradiction
    # ----------------------------
    semantic_score, semantic_label, semantic_rules = semantic_direction_conflict_score(
        f"{left_subject} {left_message}",
        f"{right_subject} {right_message}",
    )
    scores["semantic"] = semantic_score
    rules_triggered.extend(semantic_rules)
    semantic_check_mode = "rule_only"
    if semantic_score == 0.0 and not precheck_skip_reason:
        precheck_status = "skip"
        precheck_skip_reason = "semantic_contradiction_high_confidence"
        rules_triggered.append(precheck_skip_reason)
    elif semantic_score == 0.5 and not precheck_skip_reason:
        warning_reasons.append("semantic_unclear")
        rules_triggered.append("warn_semantic_unclear")

    # ----------------------------
    # Near-duplicate check
    # ----------------------------
    left_text = f"{left_subject} {left_message}".strip()
    right_text = f"{right_subject} {right_message}".strip()
    left_tokens = precheck_tokenize_text(left_text)
    right_tokens = precheck_tokenize_text(right_text)
    sim_jaccard = jaccard_similarity(left_tokens, right_tokens)
    sim_seq = float(SequenceMatcher(None, left_text.lower(), right_text.lower()).ratio()) if left_text or right_text else 1.0
    same_type = left_type == right_type and bool(left_type)
    complementary = has_complementary_relation(left_type, right_type)

    duplicate_like = (
        same_type
        and sim_jaccard >= cfg["duplicate_jaccard_threshold"]
        and sim_seq >= cfg["duplicate_seq_threshold"]
        and (not complementary)
    )
    if duplicate_like and not precheck_skip_reason:
        scores["non_duplicate"] = 0.0
        precheck_status = "skip"
        precheck_skip_reason = "near_duplicate_pair_not_multi_intent"
        rules_triggered.append(precheck_skip_reason)
    elif sim_jaccard >= cfg["moderate_similarity_threshold"] or sim_seq >= cfg["moderate_similarity_threshold"]:
        scores["non_duplicate"] = 0.5
        warning_reasons.append("moderate_subject_message_similarity")
        rules_triggered.append("warn_moderate_subject_message_similarity")

    # ----------------------------
    # Relation score
    # ----------------------------
    token_relation = jaccard_similarity(
        precheck_tokenize_text(left_subject),
        precheck_tokenize_text(right_subject),
    )
    module_overlap = bool(set(left.get("module_set", set())) & set(right.get("module_set", set())))
    relation_score = token_relation
    if module_overlap:
        relation_score = max(relation_score, 0.4)
    if complementary:
        relation_score = max(relation_score, 0.7)
    if relation_score <= cfg["relation_low_threshold"]:
        scores["relation"] = 0.7
        if not precheck_skip_reason:
            warning_reasons.append("low_relation_score")
            rules_triggered.append("warn_low_relation_score")
    else:
        scores["relation"] = 1.0

    # ----------------------------
    # Heavy file overlap warning (no hard conflict)
    # ----------------------------
    left_files = set(left.get("file_path_set", set()))
    right_files = set(right.get("file_path_set", set()))
    union_files = left_files | right_files
    overlap_ratio = float(len(left_files & right_files) / len(union_files)) if union_files else 0.0
    if overlap_ratio >= cfg["heavy_overlap_threshold"] and not precheck_skip_reason:
        warning_reasons.append("heavy_changed_files_overlap")
        rules_triggered.append("warn_heavy_changed_files_overlap")

    # ----------------------------
    # Optional git merge check
    # ----------------------------
    merge_score, git_check_method, merge_check_available = evaluate_optional_git_merge_check(left, right, git_context)
    scores["merge"] = merge_score
    if merge_check_available and merge_score == 0.0 and not precheck_skip_reason:
        precheck_status = "skip"
        precheck_skip_reason = "git_clean_apply_or_merge_check_failed"
        rules_triggered.append(precheck_skip_reason)

    # ----------------------------
    # Final status + pair weight
    # ----------------------------
    if precheck_status != "skip" and warning_reasons:
        precheck_status = "warn"
    pair_quality_weight = 0.0 if precheck_status == "skip" else float(
        scores["merge"]
        * scores["semantic"]
        * scores["type_compatibility"]
        * scores["non_duplicate"]
        * scores["relation"]
        * scores["input_message"]
    )
    pair_quality_weight = max(0.0, min(1.0, pair_quality_weight))

    return {
        "precheck_status": precheck_status,
        "precheck_skip_reason": precheck_skip_reason,
        "precheck_warning_reasons": sorted(set(warning_reasons)),
        "pair_quality_weight": round(pair_quality_weight, 6),
        "min_pair_quality_weight": round(pair_quality_weight, 6),
        "precheck_scores": {key: round(float(value), 6) for key, value in scores.items()},
        "precheck_meta": {
            "precheck_version": cfg["precheck_version"],
            "rules_triggered": rules_triggered,
            "generation_allowed": bool(precheck_status != "skip"),
            "semantic_check_mode": semantic_check_mode,
            "semantic_judge": semantic_label,
            "git_check_method": git_check_method,
            "merge_check_available": bool(merge_check_available),
            "text_similarity": {
                "jaccard": round(sim_jaccard, 6),
                "sequence_ratio": round(sim_seq, 6),
            },
            "relation_score_raw": round(relation_score, 6),
            "file_overlap_ratio": round(overlap_ratio, 6),
            "thresholds": {
                "duplicate_jaccard_threshold": cfg["duplicate_jaccard_threshold"],
                "duplicate_seq_threshold": cfg["duplicate_seq_threshold"],
                "moderate_similarity_threshold": cfg["moderate_similarity_threshold"],
                "relation_low_threshold": cfg["relation_low_threshold"],
                "heavy_overlap_threshold": cfg["heavy_overlap_threshold"],
            },
            "type_compatibility_lists": {
                "high": cfg["type_compat_high"],
                "medium": cfg["type_compat_medium"],
                "forbidden_heads": cfg["type_forbidden_heads"],
            },
        },
        "pair_precheck_results": [],
    }


def aggregate_source_set_precheck(
    sources: list[dict[str, Any]],
    *,
    config: dict[str, Any] | argparse.Namespace | None,
    git_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对 source set 执行 all-pairs precheck，并聚合成 sample 级结果。

    对 k 个源提交执行 C(k, 2) 次 pairwise precheck，然后聚合：
    - 任何一对 skip → 整个 sample skip（generation_allowed=False）
    - 任何一对 warn → 整个 sample warn
    - pair_quality_weight: 各对权重的几何平均
    - precheck_scores: 各维度分数的算术平均

    Returns:
        包含 precheck_status、pair_quality_weight、precheck_scores 等的字典
    """
    if len(sources) < 2:
        return {
            "precheck_status": "skip",
            "precheck_skip_reason": "not_enough_sources_for_pair_precheck",
            "precheck_warning_reasons": [],
            "pair_quality_weight": 0.0,
            "min_pair_quality_weight": 0.0,
            "precheck_scores": {
                "merge": 0.0,
                "semantic": 0.0,
                "type_compatibility": 0.0,
                "non_duplicate": 0.0,
                "relation": 0.0,
                "input_message": 0.0,
            },
            "precheck_meta": {
                "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
                "rules_triggered": ["not_enough_sources_for_pair_precheck"],
                "generation_allowed": False,
                "pair_count": 0,
                "pair_status_counts": {"skip": 1},
                "weight_aggregation": "geometric_mean",
                "score_aggregation": "arithmetic_mean",
            },
            "pair_precheck_results": [],
        }

    pair_results: list[dict[str, Any]] = []
    warning_reasons: set[str] = set()
    score_lists: dict[str, list[float]] = defaultdict(list)
    pair_weights: list[float] = []
    min_pair_weight = 1.0
    status_counter: Counter[str] = Counter()
    first_skip_reason = ""
    rules_triggered: list[str] = []

    for left_index in range(len(sources)):
        for right_index in range(left_index + 1, len(sources)):
            result = run_source_pair_precheck(
                sources[left_index],
                sources[right_index],
                config=config,
                git_context=git_context,
            )
            pair_entry = {
                "left_index": int(left_index),
                "right_index": int(right_index),
                "left_sha": safe_strip(sources[left_index].get("sha")),
                "right_sha": safe_strip(sources[right_index].get("sha")),
                "result": result,
            }
            pair_results.append(pair_entry)
            status = safe_strip(result.get("precheck_status", "pass")) or "pass"
            status_counter[status] += 1
            skip_reason = safe_strip(result.get("precheck_skip_reason"))
            if (not first_skip_reason) and skip_reason:
                first_skip_reason = skip_reason
            warning_reasons.update(result.get("precheck_warning_reasons", []))
            rules_triggered.extend(result.get("precheck_meta", {}).get("rules_triggered", []))
            pair_weight = float(result.get("pair_quality_weight", 0.0))
            pair_weights.append(pair_weight)
            min_pair_weight = min(min_pair_weight, pair_weight)
            for key, value in result.get("precheck_scores", {}).items():
                score_lists[key].append(float(value))

    if status_counter.get("skip", 0) > 0:
        precheck_status = "skip"
        pair_quality_weight = 0.0
        generation_allowed = False
        min_pair_quality_weight = 0.0
    else:
        precheck_status = "warn" if status_counter.get("warn", 0) > 0 else "pass"
        pair_quality_weight = geometric_mean(pair_weights)
        generation_allowed = True
        min_pair_quality_weight = min_pair_weight if pair_weights else 0.0

    precheck_scores = {
        key: round(sum(values) / len(values), 6) if values else 0.0
        for key, values in score_lists.items()
    }
    return {
        "precheck_status": precheck_status,
        "precheck_skip_reason": first_skip_reason,
        "precheck_warning_reasons": sorted(reason for reason in warning_reasons if safe_strip(reason)),
        "pair_quality_weight": round(pair_quality_weight, 6),
        "min_pair_quality_weight": round(min_pair_quality_weight, 6),
        "precheck_scores": precheck_scores,
        "precheck_meta": {
            "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
            "rules_triggered": rules_triggered,
            "generation_allowed": generation_allowed,
            "pair_count": len(pair_results),
            "pair_status_counts": dict(status_counter),
            "weight_aggregation": "geometric_mean",
            "score_aggregation": "arithmetic_mean",
        },
        "pair_precheck_results": pair_results,
    }


def extract_hunk_units(blocks: list[dict[str, Any]], intent_id: int, source_sha: str) -> list[dict[str, Any]]:
    """从 diff 块中提取 hunk 单元信息

    Args:
        blocks: diff 块列表
        intent_id: 意图 ID（0 或 1）
        source_sha: 源提交 SHA

    Returns:
        包含 hunk 信息的字典列表
    """
    units: list[dict[str, Any]] = []
    for block in blocks:
        hunk_index = 0
        for line in block["text"].splitlines():
            if line.startswith("@@"):
                hunk_index += 1
                units.append(
                    {
                        "file_path": block["file_path"],
                        "hunk_index_in_file": hunk_index,
                        "header": line,
                        "intent_id": intent_id,
                        "source_sha": source_sha,
                    }
                )
    return units


def compact_diff(text: str, max_lines: int = 60) -> str:
    """压缩 diff 文本，超过指定行数时截断"""
    lines = text.splitlines()
    selected = lines[:max_lines]
    out = "\n".join(selected)
    if len(lines) > max_lines:
        out += "\n... [truncated]"
    return out


def classify_file_role_tag(file_path: str) -> str:
    """将文件路径映射到轻量 role 标签。"""
    path = safe_strip(file_path).lower()
    if not path:
        return "other"

    base = Path(path).name
    parts = [part for part in path.split("/") if part]
    if (
        "test" in base
        or base.endswith("_test.py")
        or ".test." in base
        or ".spec." in base
        or any(part in {"test", "tests", "__tests__"} for part in parts)
    ):
        return "test"
    if (
        base.endswith((".md", ".rst", ".txt", ".adoc"))
        or any(part in {"doc", "docs"} for part in parts)
        or "changelog" in base
    ):
        return "doc"
    if (
        base in {"dockerfile", "makefile", "cmakelists.txt"}
        or path.startswith(".github/workflows/")
        or "build.gradle" in path
        or "pom.xml" in path
        or "package-lock.json" in path
        or any(part in {"build", "scripts", "ci"} for part in parts)
    ):
        return "build"
    if (
        base.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties"))
        or "config" in parts
        or "configs" in parts
    ):
        return "config"
    if any(part in {"src", "lib", "app", "server", "client"} for part in parts):
        return "source"
    if "." in base and len(base.rsplit(".", 1)[-1]) <= 6:
        return "source"
    return "other"


def _normalize_changed_file_candidates(value: Any) -> list[str]:
    """规范化 changed_files / file_paths 等结构化字段为文件路径列表。

    支持多种输入格式：
    - 字符串（逗号或换行分隔）
    - 列表/元组/集合（元素可以是字符串或含 path 键的字典）
    - 嵌套字典（递归查找 touched_paths/files/changed_files/paths 键）
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = safe_strip(value)
        if not text:
            return []
        parts = [safe_strip(item) for item in re.split(r"[\n,]", text)]
        return [item for item in parts if item]
    if isinstance(value, (list, tuple, set)):
        results: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = safe_strip(item)
                if normalized:
                    results.append(normalized)
            elif isinstance(item, dict):
                for key in ("path", "file", "file_path", "new_path", "old_path"):
                    normalized = safe_strip(item.get(key))
                    if normalized:
                        results.append(normalized)
                        break
        return results
    if isinstance(value, dict):
        for key in ("touched_paths", "files", "changed_files", "paths"):
            nested = _normalize_changed_file_candidates(value.get(key))
            if nested:
                return nested
    return []


def _extract_structured_changed_files(source: dict[str, Any]) -> list[str]:
    """从源提交数据的结构化字段中抽取变更文件列表。

    依次从 changed_files、file_paths、files 字段和 path_events.touched_paths 中
    提取文件路径，去重并规范化后返回。作为 diff evidence card 的 fallback 数据源。
    """
    candidates: list[str] = []
    for key in ("changed_files", "file_paths", "files"):
        candidates.extend(_normalize_changed_file_candidates(source.get(key)))
    path_events = source.get("path_events")
    if isinstance(path_events, dict):
        candidates.extend(_normalize_changed_file_candidates(path_events.get("touched_paths")))
    deduped = []
    seen: set[str] = set()
    for item in candidates:
        normalized = normalize_diff_path(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _count_added_deleted_lines(diff_text: str) -> tuple[int, int]:
    """统计 diff 文本中新增行和删除行的数量。

    仅计算以 +/- 开头的行（排除 +++ / --- 头行）。
    作为 build_diff_evidence_card 的 fallback 统计方法。
    """
    added = 0
    deleted = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def build_diff_evidence_card(
    source: dict[str, Any],
    *,
    max_files: int = 6,
    max_hunks: int = 3,
    max_patch_lines: int = 8,
) -> dict[str, Any]:
    """为单个源提交构建轻量 diff evidence card。

    从 git_diff 中提取变更文件列表、hunk 头、patch 片段和统计信息，
    组织为结构化的 evidence card 文本。用于 LLM 生成 prompt 时提供
    diff 上下文，帮助模型更好地理解变更内容。

    返回包含 card（文本）、available、source、changed_files、
    added_lines、deleted_lines 等字段的字典。
    """
    diff_text = ""
    diff_source = ""
    for key in ("git_diff", "diff", "patch", "synthetic_diff"):
        candidate = source.get(key)
        if isinstance(candidate, str) and safe_strip(candidate):
            diff_text = candidate
            diff_source = key
            break

    changed_files: list[str] = []
    added_lines = 0
    deleted_lines = 0
    hunk_headers: list[str] = []
    patch_evidence: list[str] = []

    if diff_text:
        blocks = split_file_blocks(diff_text)
        if blocks:
            selected_blocks = blocks[:max_files]
            changed_files = [normalize_diff_path(block.get("file_path", "")) for block in selected_blocks]
            changed_files = [item for item in changed_files if item]
            for block in selected_blocks:
                file_path = normalize_diff_path(block.get("file_path", ""))
                current_hunk = ""
                for raw_line in block.get("text", "").splitlines():
                    line = raw_line.rstrip()
                    if line.startswith("@@"):
                        current_hunk = line.strip()
                        if len(hunk_headers) < max_hunks:
                            hunk_headers.append(f"{file_path}: {current_hunk}")
                        continue
                    if line.startswith("+++ ") or line.startswith("--- "):
                        continue
                    if not (line.startswith("+") or line.startswith("-")):
                        continue
                    payload = line[1:].strip()
                    if not payload:
                        continue
                    if line.startswith("+"):
                        added_lines += 1
                    else:
                        deleted_lines += 1
                    if len(patch_evidence) >= max_patch_lines:
                        continue
                    compact_line = payload if len(payload) <= 140 else f"{payload[:137]}..."
                    patch_evidence.append(f"{file_path}: {line[0]} {compact_line}")
            if not (added_lines or deleted_lines):
                added_lines, deleted_lines = _count_added_deleted_lines(diff_text)
        else:
            added_lines, deleted_lines = _count_added_deleted_lines(diff_text)

    if not changed_files:
        changed_files = _extract_structured_changed_files(source)[:max_files]
        if changed_files and not diff_source:
            diff_source = "changed_files"

    file_roles: list[str] = []
    seen_roles: set[str] = set()
    for item in changed_files:
        role = classify_file_role_tag(item)
        if role in seen_roles:
            continue
        seen_roles.add(role)
        file_roles.append(role)

    evidence_available = bool(changed_files or patch_evidence or hunk_headers or (added_lines + deleted_lines) > 0)
    source_label = diff_source if evidence_available and diff_source else ("changed_files" if changed_files else "missing")

    if not evidence_available:
        return {
            "card": "Diff evidence unavailable",
            "available": False,
            "source": "missing",
            "changed_files": [],
            "added_lines": 0,
            "deleted_lines": 0,
            "hunk_count": 0,
            "patch_evidence_count": 0,
        }

    lines = ["Changed files:"]
    for item in changed_files or ["(unavailable)"]:
        lines.append(f"- {item}")
    lines.append("File roles:")
    for role in file_roles or ["other"]:
        lines.append(f"- {role}")
    if hunk_headers:
        lines.append("Hunk headers:")
        for header in hunk_headers[:max_hunks]:
            lines.append(f"- {header}")
    lines.append("Patch evidence:")
    if patch_evidence:
        for snippet in patch_evidence[:max_patch_lines]:
            lines.append(f"- {snippet}")
    else:
        lines.append("- unavailable_from_structured_metadata")
    lines.extend(
        [
            "Patch stats:",
            (
                "- files="
                f"{len(changed_files)}, added_lines={added_lines}, deleted_lines={deleted_lines}, "
                f"hunks={len(hunk_headers)}, sampled_patch_lines={len(patch_evidence)}"
            ),
            f"Diff evidence source: {source_label}",
        ]
    )
    return {
        "card": "\n".join(lines),
        "available": True,
        "source": source_label,
        "changed_files": changed_files,
        "added_lines": int(added_lines),
        "deleted_lines": int(deleted_lines),
        "hunk_count": int(len(hunk_headers)),
        "patch_evidence_count": int(len(patch_evidence)),
    }


def make_diff_evidence_meta(sample: dict[str, Any]) -> dict[str, Any]:
    """从样本中提取 diff evidence 元信息，供 message_meta 复用。

    读取 intent_diff_evidence_available 和 intent_diff_evidence_sources 字段，
    构造标准化的元信息字典，附加到 message_meta 中便于追踪。
    """
    available = [bool(item) for item in sample.get("intent_diff_evidence_available", [])]
    sources = [safe_strip(item) for item in sample.get("intent_diff_evidence_sources", [])]
    return {
        "diff_evidence_available_by_source": available,
        "diff_evidence_source_by_source": sources,
        "diff_evidence_card_version": DIFF_EVIDENCE_CARD_VERSION,
    }


# ============================================================
# CSV 加载和源数据池构建
# ============================================================

def load_csv(path: Path) -> list[dict[str, Any]]:
    """加载并验证源 CSV 文件

    Args:
        path: CSV 文件路径

    Returns:
        规范化后的数据行列表

    Raises:
        RuntimeError: 文件格式错误或缺少必需字段
    """
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_fields = reader.fieldnames or []
        normalized_fields = [normalize_header_key(field) for field in raw_fields]
        missing_fields = sorted(REQUIRED_SOURCE_FIELDS - set(normalized_fields))
        if missing_fields:
            raise RuntimeError(
                f"Source CSV schema mismatch. missing_fields={missing_fields}, normalized_fields={normalized_fields}"
            )
        has_legacy_label = LEGACY_SOURCE_LABEL_FIELDS.issubset(set(normalized_fields))
        has_conservative_label = CONSERVATIVE_SOURCE_LABEL_FIELDS.issubset(set(normalized_fields))
        if not has_legacy_label and not has_conservative_label:
            raise RuntimeError(
                "Source CSV schema mismatch. require manual_label for legacy source csv "
                f"or conservative_tier for conservative source csv. normalized_fields={normalized_fields}"
            )

        rows: list[dict[str, Any]] = []
        for row in reader:
            normalized = normalize_row_keys(row)
            if not safe_strip(normalized.get("manual_label")) and safe_strip(normalized.get("conservative_tier")):
                normalized["manual_label"] = safe_strip(normalized.get("conservative_tier"))
            rows.append(normalized)
        return rows


def build_source_pool_from_minimal(rows: list[dict[str, Any]], manual_label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从 CSV 行构建 A-tier 源数据池

    筛选指定 manual_label（应为 "A"）的行，提取必要字段，
    解析 git diff 为块结构，计算统计信息。

    Args:
        rows: CSV 数据行列表
        manual_label: 要筛选的标签（"A" 表示高质量）

    Returns:
        (源数据池列表, 统计信息字典)

    Raises:
        RuntimeError: 数据无效或不足时
    """
    required_fields = ["repo", "sha", "type", "subject", "message", "git_diff", "manual_label"]
    missing_examples: list[dict[str, Any]] = []
    pool: list[dict[str, Any]] = []
    seen_sha: set[str] = set()

    for row in rows:
        # 只保留指定标签的行
        if safe_strip(row.get("manual_label")) != manual_label:
            continue
        # 检查必需字段是否完整
        missing = [field for field in required_fields if not safe_strip(row.get(field))]
        if missing:
            missing_examples.append({"sha": row.get("sha"), "missing_fields": missing})
            continue

        repo = safe_strip(row.get("repo"))
        sha = safe_strip(row.get("sha"))
        # 检查 SHA 是否重复
        if sha in seen_sha:
            raise RuntimeError(f"Duplicate A-tier sha detected in source csv: {sha}")
        seen_sha.add(sha)
        ctype = safe_strip(row.get("type"))
        subject = safe_strip(row.get("subject"))
        commit_message = safe_strip(row.get("message"))
        git_diff = str(row.get("git_diff") or "")
        # 解析 diff 为文件块
        blocks = split_file_blocks(git_diff)
        if not blocks:
            missing_examples.append({"sha": sha, "missing_fields": ["git_diff_blocks"]})
            continue

        file_paths = [block["file_path"] for block in blocks]
        file_count = len(file_paths)
        changed_lines = estimate_changed_lines(git_diff)
        module_set = infer_module_set(file_paths)
        path_events = collect_diff_path_events(git_diff)
        source_confidence = parse_optional_float(row.get("source_confidence"), default=1.0)

        pool.append(
            {
                "sha": sha,
                "repo": repo,
                "type": ctype,
                "tier": "A",
                "subject": subject or first_nonempty_line(commit_message),
                "commit_message": commit_message,
                "file_count": file_count,
                "changed_lines": changed_lines,
                "module_set": module_set,
                "file_paths": file_paths,
                "file_path_set": set(file_paths),
                "blocks": blocks,
                "git_diff": git_diff,
                "path_events": path_events,
                "manual_label": manual_label,
                "source_confidence": source_confidence,
                "selection_strategy": safe_strip(row.get("selection_strategy")),
                "selection_reason": safe_strip(row.get("selection_reason")),
                "conservative_tier": safe_strip(row.get("conservative_tier")) or manual_label,
                "model_tier": safe_strip(row.get("model_tier")),
                "rule_label": safe_strip(row.get("rule_label")),
                "rule_weight": safe_strip(row.get("rule_weight")),
                "passed_rule_refilter": safe_strip(row.get("passed_rule_refilter")),
            }
        )

    # 检查是否有无效行
    if missing_examples:
        preview = missing_examples[:3]
        raise RuntimeError(
            f"Source CSV has invalid A-tier rows. invalid_count={len(missing_examples)} preview={preview}"
        )
    # 至少需要 2 行才能构建配对
    if len(pool) < 2:
        raise RuntimeError(f"Not enough valid A-tier rows to build pairs. pool_size={len(pool)}")

    # 计算统计信息
    stats = {
        "a_tier_rows": len(pool),
        "repo_count": len({row["repo"] for row in pool}),
        "type_count": len({row["type"] for row in pool}),
    }
    return pool, stats


def json_safe_payload(value: Any) -> Any:
    """Convert nested payloads to JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): json_safe_payload(item) for key, item in value.items()}
    if isinstance(value, set):
        return [json_safe_payload(item) for item in sorted(value)]
    if isinstance(value, tuple):
        return [json_safe_payload(item) for item in value]
    if isinstance(value, list):
        return [json_safe_payload(item) for item in value]
    return value


def serialize_selected_pair_plan_record(pair: dict[str, Any], *, pair_rank: int | None = None) -> dict[str, Any]:
    """Serialize one selected pair/group to a compact JSONL record."""
    record = {
        "plan_version": "step2_selected_pairs_plan_v1",
        "repo": safe_strip(pair.get("repo")),
        "member_shas": [safe_strip(member.get("sha")) for member in pair.get("members", [])],
        "type_pair": safe_strip(pair.get("type_pair")),
        "type_signature_raw": safe_strip(pair.get("type_signature_raw")),
        "type_signature_canonical": safe_strip(pair.get("type_signature_canonical")),
        "different_type": bool(pair.get("different_type", False)),
        "module_overlap": bool(pair.get("module_overlap", False)),
        "merged_files": int(pair.get("merged_files", 0) or 0),
        "merged_lines": int(pair.get("merged_lines", 0) or 0),
        "shared_files": list(pair.get("shared_files", []) or []),
        "precheck_status": safe_strip(pair.get("precheck_status", "pass")) or "pass",
        "precheck_skip_reason": safe_strip(pair.get("precheck_skip_reason")),
        "precheck_warning_reasons": list(pair.get("precheck_warning_reasons", []) or []),
        "pair_quality_weight": float(pair.get("pair_quality_weight", 1.0) or 1.0),
        "min_pair_quality_weight": float(pair.get("min_pair_quality_weight", pair.get("pair_quality_weight", 1.0)) or 1.0),
        "precheck_scores": dict(pair.get("precheck_scores", {}) or {}),
        "precheck_meta": dict(pair.get("precheck_meta", {}) or {}),
        "pair_precheck_results": list(pair.get("pair_precheck_results", []) or []),
    }
    if pair_rank is not None:
        record["pair_rank"] = int(pair_rank)
    return json_safe_payload(record)


def write_selected_pairs_plan_jsonl(path: Path, pairs: list[dict[str, Any]]) -> None:
    """Write selected pairs/groups to a JSONL plan file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for pair_rank, pair in enumerate(pairs, start=1):
            handle.write(json.dumps(serialize_selected_pair_plan_record(pair, pair_rank=pair_rank), ensure_ascii=False) + "\n")


def load_selected_pairs_plan_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load selected pair/group plan records from JSONL."""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise RuntimeError(f"Invalid selected pair plan row at line {line_number}: expect JSON object.")
            records.append(payload)
    if not records:
        raise RuntimeError(f"Selected pair plan is empty: {path}")
    return records


def materialize_selected_pairs_from_plan_records(
    plan_records: list[dict[str, Any]],
    pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild selected pair/group payloads from JSONL plan records and the current source pool."""
    pool_by_sha = {safe_strip(row.get("sha")): row for row in pool}
    rebuilt_pairs: list[dict[str, Any]] = []
    for index, record in enumerate(plan_records, start=1):
        member_shas = [safe_strip(item) for item in record.get("member_shas", []) if safe_strip(item)]
        if len(member_shas) < 2:
            raise RuntimeError(f"Invalid selected pair plan at row {index}: member_shas must contain at least 2 shas.")
        missing = [sha for sha in member_shas if sha not in pool_by_sha]
        if missing:
            raise RuntimeError(
                f"Selected pair plan row {index} references sha(s) missing from current source pool: {missing}"
            )
        members = [pool_by_sha[sha] for sha in member_shas]
        canonical_types = [canonicalize_type(member.get("type")) for member in members]
        rebuilt_pairs.append(
            {
                "repo": safe_strip(record.get("repo")) or safe_strip(members[0].get("repo")),
                "members": members,
                "type_pair": safe_strip(record.get("type_pair")) or "+".join(sorted(canonical_types)),
                "type_signature_raw": safe_strip(record.get("type_signature_raw")) or "+".join(member.get("type", "") for member in members),
                "type_signature_canonical": safe_strip(record.get("type_signature_canonical")) or "+".join(sorted(canonical_types)),
                "different_type": bool(record.get("different_type", len(set(canonical_types)) > 1)),
                "module_overlap": bool(record.get("module_overlap", has_any_module_overlap(members))),
                "merged_files": int(record.get("merged_files", len(set().union(*(member.get("file_path_set", set()) for member in members)))) or 0),
                "merged_lines": int(record.get("merged_lines", sum(int(member.get("changed_lines", 0) or 0) for member in members)) or 0),
                "shared_files": list(record.get("shared_files", []) or []),
                "precheck_status": safe_strip(record.get("precheck_status", "pass")) or "pass",
                "precheck_skip_reason": safe_strip(record.get("precheck_skip_reason")),
                "precheck_warning_reasons": list(record.get("precheck_warning_reasons", []) or []),
                "pair_quality_weight": float(record.get("pair_quality_weight", 1.0) or 1.0),
                "min_pair_quality_weight": float(record.get("min_pair_quality_weight", record.get("pair_quality_weight", 1.0)) or 1.0),
                "precheck_scores": dict(record.get("precheck_scores", {}) or {}),
                "precheck_meta": dict(record.get("precheck_meta", {}) or {}),
                "pair_precheck_results": list(record.get("pair_precheck_results", []) or []),
            }
        )
    return rebuilt_pairs


def has_any_module_overlap(members: list[dict[str, Any]]) -> bool:
    """判断组内任意两条提交是否有 module overlap。"""
    for i in range(len(members)):
        left_modules = members[i]["module_set"]
        for j in range(i + 1, len(members)):
            if left_modules & members[j]["module_set"]:
                return True
    return False


def validate_group_with_precheck(
    members: list[dict[str, Any]],
    *,
    allow_file_path_overlap_only: bool = False,
) -> dict[str, Any]:
    """对 k 组原料做 pre-merge precheck：任意一对冲突即拒绝整个组。

    检查所有 C(k, 2) 对的文件冲突和语义冲突：
    - 文件冲突：路径重叠、rename/copy 冲突、delete-modify 冲突
    - 语义冲突：极性对立、revert 重叠、完全重复签名

    Returns:
        包含 passed（是否通过）、reasons（冲突原因列表）、
        file_conflict/semantic_conflict 标志的字典
    """
    reason_counter: Counter[str] = Counter()
    file_conflict_hit = False
    semantic_conflict_hit = False
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            result = premerge_validate_pair(
                members[i],
                members[j],
                allow_file_path_overlap_only=allow_file_path_overlap_only,
            )
            if not result["passed"]:
                reason_counter.update(result["reasons"])
                file_conflict_hit = file_conflict_hit or bool(result["file_conflict"])
                semantic_conflict_hit = semantic_conflict_hit or bool(result["semantic_conflict"])
    reasons = [reason for reason, _ in reason_counter.most_common()]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "file_conflict": file_conflict_hit,
        "semantic_conflict": semantic_conflict_hit,
    }


def build_groups(
    pool: list[dict[str, Any]],
    intent_k: int,
    max_merged_files: int,
    max_merged_lines: int,
    prefer_module_overlap: bool,
    require_module_overlap: bool,
    group_combo_attempt_cap_per_repo: int,
    group_candidate_cap_per_repo: int,
    seed: int,
    allow_entangled_candidates: bool = False,
    max_shared_files_per_group: int = 0,
    selection_quality_priority: str = "legacy",
    selection_quality_config: dict[str, Any] | argparse.Namespace | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """构建同仓库内的 k-intent 可合并候选组。

    对每个仓库的 A-tier 提交进行 C(n, k) 组合枚举，施加以下约束：
    1. 默认文件路径两两不重叠；若显式开启 entangled candidate 模式，则允许轻度共享文件
    2. 合并后文件数 <= max_merged_files
    3. 合并后变更行数 <= max_merged_lines
    4. module_overlap 策略检查（require 时强制要求）
    5. Pre-merge precheck（文件冲突 + 语义冲突检测）

    通过约束的候选组按优先级排序：
    - 不同 type 优先
    - module overlap 优先（如果 prefer）
    - 文件数少优先
    - 变更行数少优先
    - 稳定哈希打破平局

    Returns:
        (repo_groups, precheck_stats): 按仓库分组的候选组和 precheck 统计信息
    """
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool:
        by_repo[row["repo"]].append(row)

    repo_groups: dict[str, list[dict[str, Any]]] = {}
    precheck_total = 0
    precheck_passed = 0
    precheck_file_reject = 0
    precheck_semantic_reject = 0
    precheck_reason_counter: Counter[str] = Counter()

    for repo, items in by_repo.items():
        if len(items) < intent_k:
            continue
        ordered_items = sorted(items, key=lambda item: stable_rank(seed, repo, item["sha"]))
        groups: list[dict[str, Any]] = []
        attempts = 0

        for members_tuple in itertools.combinations(ordered_items, intent_k):
            attempts += 1
            if attempts > group_combo_attempt_cap_per_repo:
                break
            if len(groups) >= group_candidate_cap_per_repo:
                break

            members = list(members_tuple)
            # 约束1：默认文件路径两两不重叠；entangled 模式允许轻度共享文件
            disjoint_ok = True
            seen_paths: set[str] = set()
            shared_files: set[str] = set()
            merged_files = 0
            merged_lines = 0
            for source in members:
                source_paths = source["file_path_set"]
                overlap = seen_paths & source_paths
                if overlap:
                    if not allow_entangled_candidates:
                        disjoint_ok = False
                        break
                    shared_files |= set(overlap)
                    if len(shared_files) > max_shared_files_per_group:
                        disjoint_ok = False
                        break
                seen_paths |= source_paths
                merged_files = len(seen_paths)
                merged_lines += source["changed_lines"]
            if not disjoint_ok:
                continue
            # 约束2：总量限制
            if merged_files > max_merged_files or merged_lines > max_merged_lines:
                continue

            types = [source["type"] for source in members]
            canonical_types = [canonicalize_type(source["type"]) for source in members]
            type_signature_raw = raw_type_signature(types)
            type_signature_canonical = canonical_type_signature(types)
            module_overlap = has_any_module_overlap(members)
            if require_module_overlap and not module_overlap:
                continue

            precheck_total += 1
            precheck = validate_group_with_precheck(
                members,
                allow_file_path_overlap_only=bool(allow_entangled_candidates and shared_files),
            )
            if not precheck["passed"]:
                precheck_reason_counter.update(precheck["reasons"])
                if precheck["file_conflict"]:
                    precheck_file_reject += 1
                if precheck["semantic_conflict"]:
                    precheck_semantic_reject += 1
                continue
            precheck_passed += 1

            selection_precheck_payload = {
                "precheck_status": "pass",
                "precheck_skip_reason": "",
                "precheck_warning_reasons": [],
                "pair_quality_weight": 1.0,
                "min_pair_quality_weight": 1.0,
                "precheck_scores": {
                    "merge": 1.0,
                    "semantic": 1.0,
                    "type_compatibility": 1.0,
                    "non_duplicate": 1.0,
                    "relation": 1.0,
                    "input_message": 1.0,
                },
                "precheck_meta": {
                    "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
                    "rules_triggered": [],
                    "generation_allowed": True,
                    "semantic_check_mode": "rule_only",
                    "git_check_method": "not_available",
                },
                "pair_precheck_results": [],
            }
            if selection_quality_priority in {"pair_quality", "legacy_guarded"}:
                selection_precheck_payload = aggregate_source_set_precheck(
                    members,
                    config=selection_quality_config,
                    git_context=None,
                )

            member_shas = [source["sha"] for source in members]
            module_priority = 0 if (prefer_module_overlap and module_overlap) else (1 if prefer_module_overlap else 0)
            groups.append(
                {
                    "repo": repo,
                    "members": members,
                    "type_pair": type_signature_canonical,
                    "type_signature_raw": type_signature_raw,
                    "type_signature_canonical": type_signature_canonical,
                    "different_type": len(set(canonical_types)) > 1,
                    "module_overlap": module_overlap,
                    "merged_files": merged_files,
                    "merged_lines": merged_lines,
                    "shared_files": sorted(shared_files),
                    "precheck_status": selection_precheck_payload["precheck_status"],
                    "precheck_skip_reason": selection_precheck_payload["precheck_skip_reason"],
                    "precheck_warning_reasons": selection_precheck_payload["precheck_warning_reasons"],
                    "pair_quality_weight": selection_precheck_payload["pair_quality_weight"],
                    "min_pair_quality_weight": selection_precheck_payload["min_pair_quality_weight"],
                    "precheck_scores": selection_precheck_payload["precheck_scores"],
                    "precheck_meta": selection_precheck_payload["precheck_meta"],
                    "pair_precheck_results": selection_precheck_payload.get("pair_precheck_results", []),
                    "priority": (
                        0 if len(set(canonical_types)) > 1 else 1,
                        0 if shared_files else 1,
                        module_priority,
                        merged_files,
                        merged_lines,
                        stable_rank(seed, repo, *sorted(member_shas)),
                    ),
                }
            )
        groups.sort(key=lambda item: item["priority"])
        if groups:
            repo_groups[repo] = groups

    precheck_stats = {
        "total_checked": int(precheck_total),
        "passed": int(precheck_passed),
        "rejected": int(precheck_total - precheck_passed),
        "reject_file_conflict": int(precheck_file_reject),
        "reject_semantic_conflict": int(precheck_semantic_reject),
        "reject_by_reason": dict(precheck_reason_counter.most_common()),
    }
    return repo_groups, precheck_stats


def pair_selection_sort_key(pair: dict[str, Any], selection_quality_priority: str) -> tuple[Any, ...]:
    """构造候选组选择排序键。

    `legacy` 保持旧的结构优先级顺序。
    `pair_quality` 仅在现有结构桶内再按 source-pair 质量排序：
    pass > warn > skip, 然后 pair_quality_weight 高的优先。
    """
    base_priority = tuple(pair.get("priority", ()))
    if selection_quality_priority != "pair_quality":
        return base_priority

    precheck_status_rank = {
        "pass": 0,
        "warn": 1,
        "skip": 2,
    }.get(safe_strip(pair.get("precheck_status")) or "pass", 3)
    pair_quality_weight = float(pair.get("pair_quality_weight", 0.0) or 0.0)
    if len(base_priority) < 6:
        return (precheck_status_rank, -pair_quality_weight, *base_priority)
    return (
        base_priority[0],
        base_priority[1],
        base_priority[2],
        precheck_status_rank,
        base_priority[3],
        base_priority[4],
        -pair_quality_weight,
        *base_priority[5:],
    )


def prepare_pairs_for_selection(
    pairs: list[dict[str, Any]],
    selection_quality_priority: str,
    selection_min_pair_quality_weight: float,
) -> list[dict[str, Any]]:
    """根据选样模式预处理候选列表。"""
    if selection_quality_priority == "pair_quality":
        return sorted(list(pairs), key=lambda pair: pair_selection_sort_key(pair, selection_quality_priority))

    base_sorted = sorted(list(pairs), key=lambda pair: pair_selection_sort_key(pair, "legacy"))
    if selection_quality_priority != "legacy_guarded":
        return base_sorted

    guarded_pairs: list[dict[str, Any]] = []
    deferred_skip_pairs: list[dict[str, Any]] = []
    for pair in base_sorted:
        status = safe_strip(pair.get("precheck_status")) or "pass"
        weight = float(pair.get("pair_quality_weight", 1.0) or 0.0)
        if status != "skip" and weight <= float(selection_min_pair_quality_weight):
            continue
        if status == "skip":
            deferred_skip_pairs.append(pair)
        else:
            guarded_pairs.append(pair)
    return guarded_pairs + deferred_skip_pairs


def select_pairs(
    repo_pairs: dict[str, list[dict[str, Any]]],
    target_count: int,
    repo_cap: int,
    type_pair_cap: int,
    require_different_type: bool,
    seed: int,
    selection_quality_priority: str = "legacy",
    selection_min_pair_quality_weight: float = 0.0,
) -> list[dict[str, Any]]:
    """从候选组中选择满足条件的样本，实现多样化采样。

    选择策略（round-robin + 多样性约束）：
    1. 仓库优先级：候选多的仓库优先（用稳定哈希打破平局）
    2. 每个仓库最多选 repo_cap 个（防止仓库倾斜）
    3. 每种类型组合最多选 type_pair_cap 个（防止类型倾斜）
    4. 可选：只选不同类型（different_type）的组
    5. 每轮遍历所有仓库，每仓库最多选 1 个，循环直到达到目标或无法继续

    Args:
        repo_pairs: 按仓库分组的候选组
        target_count: 目标样本数
        repo_cap: 每个仓库最多选几个
        type_pair_cap: 每种类型组合最多选几个
        require_different_type: 是否要求不同类型
        seed: 随机种子

    Returns:
        选中的候选组列表
    """
    repo_counter: Counter[str] = Counter()
    type_pair_counter: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    repo_pairs = {
        repo: prepare_pairs_for_selection(
            pairs,
            selection_quality_priority=selection_quality_priority,
            selection_min_pair_quality_weight=selection_min_pair_quality_weight,
        )
        for repo, pairs in repo_pairs.items()
    }
    # 仓库排序：候选多的优先，用稳定哈希打破平局
    repo_order = sorted(
        repo_pairs.keys(),
        key=lambda key: (-len(repo_pairs[key]), stable_rank(seed, "repo", key)),
    )

    # 循环选择，直到达到目标数量或无法继续
    while len(selected) < target_count:
        progressed = False
        for repo in repo_order:
            if len(selected) >= target_count:
                break
            if repo_counter[repo] >= repo_cap:
                continue
            pairs = repo_pairs[repo]
            pick_index = None
            # 遍历该仓库的候选组，找到第一个满足条件的
            for index, pair in enumerate(pairs):
                if require_different_type and not pair["different_type"]:
                    continue
                if type_pair_counter[pair["type_pair"]] >= type_pair_cap:
                    continue
                pick_index = index
                break
            if pick_index is None:
                continue
            # 选出并移除该候选组（避免重复选择）
            pair = pairs.pop(pick_index)
            selected.append(pair)
            # 更新计数器
            repo_counter[repo] += 1
            type_pair_counter[pair["type_pair"]] += 1
            progressed = True
        # 如果没有进展，说明无法达到目标数量
        if not progressed:
            break
    return selected


def decorate_blocks(source: dict[str, Any], intent_id: int) -> list[dict[str, Any]]:
    """为 diff 块添加 intent_id 和 source_sha 标记

    Args:
        source: 源提交数据
        intent_id: 意图 ID（0 或 1）

    Returns:
        带标记的块列表，按文件路径排序
    """
    blocks: list[dict[str, Any]] = []
    for block in source["blocks"]:
        blocks.append(
            {
                "file_path": block["file_path"],
                "text": block["text"],
                "intent_id": intent_id,
                "source_sha": source["sha"],
            }
        )
    blocks.sort(key=lambda item: item["file_path"])
    return blocks


def round_robin_blocks_multi(
    source_blocks: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    seed: int,
) -> list[dict[str, Any]]:
    """多源 round-robin 合并块列表。"""
    ordered = sorted(
        source_blocks,
        key=lambda item: (
            -len(item[1]),
            stable_rank(seed, "rr-start", item[0]["sha"]),
        ),
    )
    queues: list[list[dict[str, Any]]] = [list(blocks) for _, blocks in ordered]
    merged: list[dict[str, Any]] = []
    while True:
        progressed = False
        for queue in queues:
            if queue:
                merged.append(queue.pop(0))
                progressed = True
        if not progressed:
            break
    return merged


def materialize_sample(pair: dict[str, Any], sample_id: str, block_order: str, seed: int) -> dict[str, Any]:
    """将选中的候选组物化为完整样本，生成 synthetic diff 和相关元数据。

    主要工作：
    1. 为 k 个提交的 diff 块添加 intent_id 标记（0, 1, ...）
    2. 按指定策略合并块：
       - round_robin: 交替排列各提交的块（默认，增加交错度）
       - path_sorted: 按文件路径排序（同文件的变更聚集）
    3. 拼接生成 synthetic diff 文本
    4. 提取 edit units（每个 hunk 作为一个 unit，记录 intent_id）
    5. 构建源提交信息和 diff evidence card
    6. 计算块级统计（switches、hunk counts 等）

    Args:
        pair: 选中的候选组（包含 members、type_pair 等）
        sample_id: 样本 ID（如 "simple2_0001"）
        block_order: 块排序策略（"round_robin" 或 "path_sorted"）
        seed: 随机种子（用于 round_robin 的稳定排序）

    Returns:
        完整的样本字典（包含 synthetic_diff、sources、edit_units 等）
    """
    members = list(pair["members"])
    source_blocks: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for intent_id, member in enumerate(members):
        source_blocks.append((member, decorate_blocks(member, intent_id=intent_id)))

    # 按策略合并块
    if block_order == "round_robin":
        merged_blocks = round_robin_blocks_multi(source_blocks, seed=seed)
        construction_type = "same_repo_multi_round_robin_v1"
    else:
        # 按文件路径排序合并
        all_blocks: list[dict[str, Any]] = []
        for _, blocks in source_blocks:
            all_blocks.extend(blocks)
        merged_blocks = sorted(
            all_blocks,
            key=lambda item: (item["file_path"], item["intent_id"], item["source_sha"]),
        )
        construction_type = "same_repo_multi_path_sorted_v1"

    # 生成合成 diff 文本
    synthetic_diff = "\n".join(block["text"] for block in merged_blocks)
    # 提取 edit units（每个 hunk 作为一个 unit）
    edit_units: list[dict[str, Any]] = []
    for block in merged_blocks:
        edit_units.extend(
            extract_hunk_units(
                [{"file_path": block["file_path"], "text": block["text"]}],
                intent_id=block["intent_id"],
                source_sha=block["source_sha"],
            )
        )

    # 构建源提交信息
    sources: list[dict[str, Any]] = []
    for source in members:
        sources.append(
            {
                "sha": source["sha"],
                "repo": source["repo"],
                "type": source["type"],
                "type_canonical": canonicalize_type(source["type"]),
                "tier": source["tier"],
                "subject": source["subject"],
                "commit_message": source["commit_message"],
                "manual_label": source["manual_label"],
                "file_count": source["file_count"],
                "changed_lines": source["changed_lines"],
                "file_paths": source["file_paths"],
                "source_confidence": source["source_confidence"],
            }
        )

    # 计算块级别的统计信息
    block_intent_sequence = [block["intent_id"] for block in merged_blocks]
    # 计算意图切换次数（反映交错的复杂度）
    block_switches = sum(
        1
        for index in range(1, len(block_intent_sequence))
        if block_intent_sequence[index] != block_intent_sequence[index - 1]
    )
    # 每个 edit unit 对应的意图
    edit_to_intent = [unit["intent_id"] for unit in edit_units]
    # 每个意图的 hunk 数量
    intent_hunk_counts = [
        sum(1 for unit in edit_units if unit["intent_id"] == intent_id)
        for intent_id in range(len(sources))
    ]
    sample_confidence = 1.0
    diff_evidence_cards: list[str] = []
    diff_evidence_available: list[bool] = []
    diff_evidence_sources: list[str] = []
    for member in members:
        evidence = build_diff_evidence_card(member)
        diff_evidence_cards.append(evidence["card"])
        diff_evidence_available.append(bool(evidence["available"]))
        diff_evidence_sources.append(safe_strip(evidence["source"]) or "missing")
    source_types_raw = [source["type"] for source in sources]
    source_types_canonical = [source["type_canonical"] for source in sources]

    payload = {
        "sample_id": sample_id,
        "repo": pair["repo"],
        "construction_type": construction_type,
        "intent_count": len(sources),
        "intent_k": len(sources),
        "different_type": pair["different_type"],
        "module_overlap": pair["module_overlap"],
        "type_pair": pair["type_pair"],
        "type_signature_raw": pair["type_signature_raw"],
        "type_signature_canonical": pair["type_signature_canonical"],
        "source_types_raw": source_types_raw,
        "source_types_canonical": source_types_canonical,
        "merged_file_count": pair["merged_files"],
        "merged_changed_lines": pair["merged_lines"],
        "merged_hunk_count": len(edit_units),
        "block_intent_sequence": block_intent_sequence,
        "block_switches": block_switches,
        "source_confidences": [source["source_confidence"] for source in sources],
        "sample_confidence": sample_confidence,
        "intent_types": [source["type"] for source in sources],
        "intent_messages": [source["commit_message"] for source in sources],
        "intent_subjects": [source["subject"] for source in sources],
        "intent_diff_evidence_cards": diff_evidence_cards,
        "intent_diff_evidence_available": diff_evidence_available,
        "intent_diff_evidence_sources": diff_evidence_sources,
        "intent_hunk_counts": intent_hunk_counts,
        "edit_to_intent": edit_to_intent,
        "sources": sources,
        "edit_units": edit_units,
        "synthetic_diff": synthetic_diff,
        "precheck_status": safe_strip(pair.get("precheck_status")) or "pass",
        "precheck_skip_reason": safe_strip(pair.get("precheck_skip_reason")),
        "precheck_warning_reasons": list(pair.get("precheck_warning_reasons", []) or []),
        "pair_quality_weight": float(pair.get("pair_quality_weight", 1.0) or 1.0),
        "min_pair_quality_weight": float(pair.get("min_pair_quality_weight", pair.get("pair_quality_weight", 1.0)) or 1.0),
        "precheck_scores": dict(
            pair.get(
                "precheck_scores",
                {
                    "merge": 1.0,
                    "semantic": 1.0,
                    "type_compatibility": 1.0,
                    "non_duplicate": 1.0,
                    "relation": 1.0,
                    "input_message": 1.0,
                },
            )
        ),
        "precheck_meta": dict(
            pair.get(
                "precheck_meta",
                {
                    "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
                    "rules_triggered": [],
                    "generation_allowed": True,
                    "semantic_check_mode": "rule_only",
                    "git_check_method": "not_available",
                },
            )
        ),
        "pair_precheck_results": list(pair.get("pair_precheck_results", []) or []),
    }
    for index, card in enumerate(diff_evidence_cards, start=1):
        payload[f"diff_evidence_card_{index}"] = card
    return payload


def nearest_rank_percentile(values: list[int | float], p: float) -> float:
    """计算最近秩百分位数（nearest rank percentile）。

    将值排序后，取第 ceil(p * n) 个值作为结果。
    用于阈值校准和长度限制计算。

    Args:
        values: 数值列表
        p: 百分位（0.0 ~ 1.0）

    Returns:
        百分位对应的值
    """
    if not values:
        raise ValueError("empty values for percentile")
    sorted_values = sorted(values)
    rank = int(math.ceil(p * len(sorted_values)))
    rank = max(1, min(rank, len(sorted_values)))
    return float(sorted_values[rank - 1])


def compute_length_limit_stats(pool: list[dict[str, Any]]) -> dict[str, Any]:
    """计算合成消息的长度限制统计信息

    使用源提交 subject 的长度 P90 作为合成消息的长度上限，
    防止生成过长的 subject。

    Args:
        pool: 源数据池

    Returns:
        包含长度统计数据（min, max, p50, p90 等）的字典

    Raises:
        RuntimeError: 没有有效的提交 subject 时
    """
    lengths: list[int] = []
    for row in pool:
        subject = safe_strip(row.get("subject"))
        if subject:
            lengths.append(len(subject))
    if not lengths:
        raise RuntimeError("length_limit computation failed: no valid single-intent commit subjects found.")
    stats = {
        "count": len(lengths),
        "min": int(min(lengths)),
        "max": int(max(lengths)),
        "p50": int(nearest_rank_percentile(lengths, 0.5)),
        "p90": int(nearest_rank_percentile(lengths, 0.9)),
        "p95": int(nearest_rank_percentile(lengths, 0.95)),
        "sha256": canonical_json_hash(sorted(lengths)),
        "policy": "p90(real_single_intent_commit_subject_length)",
        "source": "subject_column_of_a_tier_commits",
    }
    if stats["p90"] <= 0:
        raise RuntimeError(f"Invalid computed P90 length_limit: {stats['p90']}")
    return stats


# ============================================================
# 缓存操作函数
# ============================================================

def load_cache(path: Path) -> dict[str, Any]:
    """加载缓存文件（JSON 格式）"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        return payload
    return {}


def save_cache(path: Path, payload: dict[str, Any]) -> None:
    """保存缓存到文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ============================================================
# Few-shot 检索函数
# ============================================================

def validate_sql_identifier(identifier: str) -> None:
    """验证 SQL 标识符的安全性（防止 SQL 注入）"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")


def canonical_repo(repo: str) -> str:
    """规范化仓库标识，统一收敛到 owner/repo 格式。

    支持多种输入格式：
    - SSH: git@github.com:owner/repo.git
    - HTTPS: https://github.com/owner/repo
    - 纯文本: owner/repo
    - 带 .git 后缀的变体

    用于 few-shot 检索时排除同仓库样本，避免数据泄漏。
    """
    text = safe_strip(repo).lower()
    if not text:
        return ""
    text = text.rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/]+)$", text)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"
    https_match = re.match(r"^(?:https?://|ssh://git@)?github\.com/([^/]+)/([^/]+)$", text)
    if https_match:
        return f"{https_match.group(1)}/{https_match.group(2)}"
    raw_match = re.match(r"^github\.com/([^/]+)/([^/]+)$", text)
    if raw_match:
        return f"{raw_match.group(1)}/{raw_match.group(2)}"
    if text.count("/") >= 2:
        parts = [part for part in text.split("/") if part]
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
    return text


def build_default_fewshot_subject(subjects: list[str]) -> str:
    """用仓库内 preview 样本的 subject 列表构造默认的 few-shot subject。

    合并规则：
    - 1 个 subject: 直接返回
    - 2 个 subject: 用 "and" 连接
    - 3+ 个 subject: 用逗号分隔，最后两个用 "and" 连接

    用于从打包的 synthetic_index_harder.csv 构建 few-shot pool 时生成 subject 字段。
    """
    cleaned = [safe_strip(item) for item in subjects if safe_strip(item)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def build_default_fewshot_pool_db(csv_path: Path, db_path: Path, table: str) -> None:
    """从仓库内的 preview CSV 构建默认 few-shot SQLite pool。"""
    validate_sql_identifier(table)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(
            f"""
            CREATE TABLE {table} (
                example_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                sha TEXT NOT NULL,
                type_pair TEXT NOT NULL,
                type_signature_raw TEXT NOT NULL,
                type_signature_canonical TEXT NOT NULL,
                intent_k INTEGER NOT NULL,
                subject TEXT NOT NULL,
                split TEXT NOT NULL,
                verified_multi_intent INTEGER NOT NULL,
                quality_score REAL,
                fewshot_eligible INTEGER,
                quality_status TEXT,
                message_status TEXT,
                notes TEXT
            )
            """
        )
        payload_rows = []
        for row in rows:
            normalized = normalize_row_keys(row)
            source_types = []
            source_subjects = []
            for key, value in normalized.items():
                if key.startswith("source_type_") and safe_strip(value):
                    source_types.append(safe_strip(value))
                if key.startswith("source_subject_") and safe_strip(value):
                    source_subjects.append(safe_strip(value))
            type_signature_raw = safe_strip(normalized.get("type_pair")) or raw_type_signature(source_types)
            type_signature_canonical = canonical_type_signature(source_types or signature_types(type_signature_raw))
            subject = build_default_fewshot_subject(source_subjects)
            if not type_signature_canonical or not subject:
                continue
            payload_rows.append(
                {
                    "example_id": safe_strip(normalized.get("sample_id")) or canonical_json_hash(normalized),
                    "repo": safe_strip(normalized.get("repo")) or "default/fewshot",
                    "sha": safe_strip(normalized.get("sample_id")) or canonical_json_hash(normalized),
                    "type_pair": type_signature_canonical,
                    "type_signature_raw": type_signature_raw or type_signature_canonical,
                    "type_signature_canonical": type_signature_canonical,
                    "intent_k": max(2, len(signature_types(type_signature_canonical))),
                    "subject": subject,
                    "split": "train",
                    "verified_multi_intent": 1,
                    "quality_score": 1.0,
                    "fewshot_eligible": 1,
                    "quality_status": "pilot_preview",
                    "message_status": "unverified_preview",
                    "notes": "packaged_preview_pool_not_formal_verified",
                }
            )
        conn.executemany(
            f"""
            INSERT INTO {table} (
                example_id, repo, sha, type_pair, type_signature_raw,
                type_signature_canonical, intent_k, subject, split,
                verified_multi_intent, quality_score, fewshot_eligible,
                quality_status, message_status, notes
            )
            VALUES (
                :example_id, :repo, :sha, :type_pair, :type_signature_raw,
                :type_signature_canonical, :intent_k, :subject, :split,
                :verified_multi_intent, :quality_score, :fewshot_eligible,
                :quality_status, :message_status, :notes
            )
            """,
            payload_rows,
        )
        conn.commit()
    finally:
        conn.close()


def resolve_fewshot_pool_or_fail(args: argparse.Namespace, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    """解析 formal run 的 few-shot pool，必要时构建默认 DB。"""
    explicit_db = safe_strip(getattr(args, "fewshot_db", ""))
    if explicit_db:
        resolved = Path(explicit_db)
        if not resolved.exists() or not resolved.is_file():
            raise RuntimeError(f"Few-shot DB path is invalid: {resolved}")
        return resolved, {"source": "explicit_db", "built_default_pool": False, "resolved_db": repo_rel(resolved)}

    packaged_db = Path(DEFAULT_PACKAGED_FEWSHOT_DB)
    if packaged_db.exists() and packaged_db.is_file():
        return packaged_db, {"source": "packaged_db", "built_default_pool": False, "resolved_db": repo_rel(packaged_db)}

    source_csv = Path(safe_strip(getattr(args, "fewshot_source_csv", DEFAULT_FEWSHOT_SOURCE_CSV)) or DEFAULT_FEWSHOT_SOURCE_CSV)
    if source_csv.exists() and source_csv.is_file():
        built_db = output_dir / "cache" / "default_fewshot_pool.sqlite"
        build_default_fewshot_pool_db(source_csv, built_db, getattr(args, "fewshot_table", "fewshot_examples"))
        return built_db, {
            "source": "packaged_csv_built_default_db",
            "built_default_pool": True,
            "source_csv": repo_rel(source_csv),
            "resolved_db": repo_rel(built_db),
        }

    if bool(getattr(args, "require_fewshot_pool", True)):
        raise RuntimeError(
            "Few-shot pool is mandatory for formal Step2 message generation. "
            f"Provide --fewshot-db or build default pool at {source_csv}."
        )
    raise RuntimeError("Few-shot pool could not be resolved.")


def collect_formal_asset_status(
    args: argparse.Namespace,
    *,
    resolved_fewshot_db: str | Path | None = None,
    require_fewshot_build_manifest: bool | None = None,
) -> dict[str, Any]:
    require_source_manifest = bool(getattr(args, "formal_run", False) or getattr(args, "preflight", False))
    if require_fewshot_build_manifest is None:
        require_fewshot_build_manifest = bool(getattr(args, "formal_run", False))
    return summarize_formal_assets(
        source_data_path=getattr(args, "source_csv", ""),
        source_manifest_path=getattr(args, "source_manifest_path", ""),
        fewshot_pool_path=resolved_fewshot_db or getattr(args, "fewshot_db", ""),
        fewshot_build_manifest_path=getattr(args, "fewshot_build_manifest_path", ""),
        require_source_manifest=require_source_manifest,
        require_fewshot_build_manifest=bool(require_fewshot_build_manifest),
    )


def _to_int_or_none(value: Any) -> int | None:
    """将任意值安全转换为整数，无法转换时返回 None。

    支持字符串、浮点数等类型的隐式转换（先转 float 再转 int）。
    用于读取 few-shot pool 中的可选整数字段（如 verified_multi_intent, fewshot_eligible）。
    """
    if value is None:
        return None
    text = safe_strip(str(value))
    if text == "":
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def analyze_fewshot_subject_style(
    subject: str,
    *,
    max_chars: int = DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_CHARS,
    max_tokens: int = DEFAULT_FEWSHOT_STYLE_MAX_SUBJECT_TOKENS,
) -> dict[str, Any]:
    """检测 few-shot subject 风格是否干净。"""
    text = safe_strip(subject)
    flags = detect_message_pattern_flags(text)
    token_count = len(WORD_TOKEN_RE.findall(text))
    reasons: list[str] = []
    if not text:
        reasons.append("empty_subject")
    if int(flags.get("dual_prefix", 0)) == 1:
        reasons.append("double_prefix")
    if int(flags.get("label_template_hit", 0)) == 1:
        reasons.append("label_template")
    if int(flags.get("bullet_hit", 0)) == 1:
        reasons.append("bullet_list")
    if int(flags.get("numbered_list_hit", 0)) == 1:
        reasons.append("numbered_list")
    if int(flags.get("mechanical_semicolon", 0)) == 1:
        reasons.append("mechanical_semicolon")
    if len(text) > max_chars or token_count > max_tokens:
        reasons.append("overlong_subject")
    lowered = text.lower()
    if contains_generic_phrase(text) == 1 or lowered in DEFAULT_GENERIC_MESSAGE_PHRASES_LOWER:
        reasons.append("generic_subject")
    return {
        "clean": len(reasons) == 0,
        "reasons": reasons,
        "token_count": token_count,
        "char_count": len(text),
        "flags": flags,
    }


def load_fewshot_pool_rows(db_path: str, table: str) -> list[dict[str, Any]]:
    """从 SQLite few-shot pool 中读取原始样本（含可选字段）。"""
    validate_sql_identifier(table)
    db_file = Path(db_path)
    if not db_file.exists() or not db_file.is_file():
        raise RuntimeError(f"Few-shot DB path is invalid: {db_path}")
    uri = f"file:{db_file.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to open few-shot DB in readonly mode: {exc}") from exc
    try:
        col_rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        columns = {str(row[1]) for row in col_rows}
        if not columns:
            raise RuntimeError(f"Few-shot table not found or empty schema: {table}")
        select_columns = [
            item
            for item in [
                "example_id",
                "repo",
                "sha",
                "type_pair",
                "type_signature_raw",
                "type_signature_canonical",
                "intent_k",
                "subject",
                "split",
                "verified_multi_intent",
                "fewshot_eligible",
                "quality_score",
                "quality_status",
                "message_status",
                "notes",
            ]
            if item in columns
        ]
        query = f"SELECT {', '.join(select_columns)} FROM {table}"
        cursor = conn.execute(query)
        rows = []
        for raw_row in cursor.fetchall():
            payload = dict(zip(select_columns, raw_row))
            type_signature_raw = safe_strip(payload.get("type_signature_raw") or payload.get("type_pair"))
            type_signature_canonical = safe_strip(payload.get("type_signature_canonical"))
            if not type_signature_canonical:
                type_signature_canonical = canonical_type_signature(signature_types(type_signature_raw))
            if not type_signature_canonical:
                continue
            subject = safe_strip(payload.get("subject"))
            style = analyze_fewshot_subject_style(subject)
            rows.append(
                {
                    "example_id": safe_strip(payload.get("example_id")) or canonical_json_hash(payload),
                    "repo": safe_strip(payload.get("repo")),
                    "sha": safe_strip(payload.get("sha")),
                    "type_signature_raw": type_signature_raw or type_signature_canonical,
                    "type_signature_canonical": type_signature_canonical,
                    "intent_k": int(payload.get("intent_k") or max(2, len(signature_types(type_signature_canonical)))),
                    "subject": subject,
                    "split": safe_strip(payload.get("split") or "train"),
                    "verified_multi_intent": _to_int_or_none(payload.get("verified_multi_intent")),
                    "fewshot_eligible": _to_int_or_none(payload.get("fewshot_eligible")),
                    "quality_score": float(payload.get("quality_score") or 0.0),
                    "quality_status": safe_strip(payload.get("quality_status")),
                    "message_status": safe_strip(payload.get("message_status")),
                    "notes": safe_strip(payload.get("notes")),
                    "style_clean": bool(style["clean"]),
                    "style_reasons": list(style["reasons"]),
                    "style_token_count": int(style["token_count"]),
                    "style_char_count": int(style["char_count"]),
                    "style_flags": dict(style["flags"]),
                }
            )
        return rows
    finally:
        conn.close()


def filter_fewshot_pool_rows_for_retrieval(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """按正式策略过滤 few-shot rows，返回可检索样本和过滤统计。"""
    stats = {
        "filtered_non_train": 0,
        "filtered_ineligible_flag": 0,
        "filtered_unverified_flag": 0,
        "filtered_bad_style": 0,
    }
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        split = safe_strip(row.get("split") or "train")
        if split and split != "train":
            stats["filtered_non_train"] += 1
            continue
        fewshot_eligible = row.get("fewshot_eligible")
        verified = row.get("verified_multi_intent")
        if fewshot_eligible is not None and int(fewshot_eligible) != 1:
            stats["filtered_ineligible_flag"] += 1
            continue
        if verified is not None and int(verified) != 1:
            stats["filtered_unverified_flag"] += 1
            continue
        if not bool(row.get("style_clean", True)):
            stats["filtered_bad_style"] += 1
            continue
        eligible_rows.append(row)
    return eligible_rows, stats


def load_fewshot_pool_examples(db_path: str, table: str) -> list[dict[str, Any]]:
    """读取并返回可检索 few-shot 示例。"""
    rows = load_fewshot_pool_rows(db_path=db_path, table=table)
    eligible_rows, _ = filter_fewshot_pool_rows_for_retrieval(rows)
    return eligible_rows


def audit_fewshot_pool(
    rows: list[dict[str, Any]],
    *,
    min_total: int = DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES,
    min_per_common_signature: int = DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
    strict_style: bool = DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE,
) -> dict[str, Any]:
    """审计 few-shot pool 的规模、风格和覆盖，输出 formal-ready 判定。"""
    train_rows = [row for row in rows if safe_strip(row.get("split") or "train") in {"", "train"}]
    total_examples = len(train_rows)
    verified_examples = sum(
        1
        for row in train_rows
        if (
            (row.get("verified_multi_intent") is None and row.get("fewshot_eligible") is None)
            or int(row.get("verified_multi_intent") or 0) == 1
            or int(row.get("fewshot_eligible") or 0) == 1
        )
    )
    bad_style_rows = [row for row in train_rows if not bool(row.get("style_clean", True))]
    bad_style_examples = [
        {
            "example_id": row.get("example_id", ""),
            "subject": row.get("subject", ""),
            "reasons": row.get("style_reasons", []),
        }
        for row in bad_style_rows[:20]
    ]
    double_prefix_count = sum(1 for row in bad_style_rows if "double_prefix" in row.get("style_reasons", []))
    overlong_count = sum(1 for row in bad_style_rows if "overlong_subject" in row.get("style_reasons", []))
    generic_subject_count = sum(1 for row in bad_style_rows if "generic_subject" in row.get("style_reasons", []))
    eligible_rows, filter_stats = filter_fewshot_pool_rows_for_retrieval(train_rows)
    signature_counter = Counter(row.get("type_signature_canonical", "") for row in eligible_rows if row.get("type_signature_canonical"))
    type_signature_counts = dict(sorted(signature_counter.items()))
    common_signature_coverage = {
        signature: int(signature_counter.get(signature, 0))
        for signature in DEFAULT_FEWSHOT_COMMON_SIGNATURES
    }

    blockers: list[str] = []
    warnings: list[str] = []
    if total_examples < int(min_total):
        blockers.append(
            f"fewshot_total_below_min(total={total_examples}, min_required={int(min_total)})"
        )
    missing_common = [
        signature
        for signature, count in common_signature_coverage.items()
        if count < int(min_per_common_signature)
    ]
    if missing_common:
        blockers.append(
            "fewshot_common_signature_coverage_insufficient("
            f"min_per_signature={int(min_per_common_signature)}, signatures={missing_common})"
        )
    if strict_style and bad_style_rows:
        blockers.append(f"fewshot_bad_style_detected(count={len(bad_style_rows)})")
    elif bad_style_rows:
        warnings.append(f"fewshot_bad_style_detected(count={len(bad_style_rows)})")
    if verified_examples == 0:
        blockers.append("fewshot_verified_examples_zero")
    if int(filter_stats.get("filtered_bad_style", 0)) > 0:
        warnings.append(f"retrieval_filtered_bad_style={int(filter_stats['filtered_bad_style'])}")
    if int(filter_stats.get("filtered_ineligible_flag", 0)) > 0:
        warnings.append(f"retrieval_filtered_ineligible={int(filter_stats['filtered_ineligible_flag'])}")
    if int(filter_stats.get("filtered_unverified_flag", 0)) > 0:
        warnings.append(f"retrieval_filtered_unverified={int(filter_stats['filtered_unverified_flag'])}")
    if not any(row.get("verified_multi_intent") is not None for row in train_rows):
        warnings.append("verified_multi_intent_column_missing")
    if not any(row.get("fewshot_eligible") is not None for row in train_rows):
        warnings.append("fewshot_eligible_column_missing")

    return {
        "total_examples": int(total_examples),
        "verified_examples": int(verified_examples),
        "eligible_examples_for_retrieval": int(len(eligible_rows)),
        "type_signature_counts": type_signature_counts,
        "common_signature_coverage": common_signature_coverage,
        "bad_style_count": int(len(bad_style_rows)),
        "bad_style_examples": bad_style_examples,
        "double_prefix_count": int(double_prefix_count),
        "overlong_count": int(overlong_count),
        "generic_subject_count": int(generic_subject_count),
        "audit_pass": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
        "retrieval_filter_stats": filter_stats,
        "common_signatures_checked": list(DEFAULT_FEWSHOT_COMMON_SIGNATURES),
        "min_total_required": int(min_total),
        "min_per_common_signature_required": int(min_per_common_signature),
        "strict_style": bool(strict_style),
    }


def retrieve_fewshot_examples(
    db_path: str,
    table: str,
    type_signature_canonical: str,
    current_repo: str,
    k: int,
    seed: int,
    current_source_shas: set[str] | None = None,
) -> dict[str, Any]:
    """使用 k-aware fallback 策略检索 formal few-shot 示例。"""
    if not db_path:
        raise RuntimeError("Few-shot retrieval requires non-empty `fewshot_db`.")
    raw_rows = load_fewshot_pool_rows(db_path=db_path, table=table)
    rows, retrieval_filter_stats = filter_fewshot_pool_rows_for_retrieval(raw_rows)
    requested_types = signature_types(type_signature_canonical)
    requested_type_set = set(requested_types)
    requested_pairs = {
        "+".join(sorted(pair))
        for pair in itertools.combinations(sorted(requested_type_set), 2)
    }
    current_repo_canonical = canonical_repo(current_repo)
    source_sha_set = {
        safe_strip(item)
        for item in (current_source_shas or set())
        if safe_strip(item)
    }
    excluded_same_repo_count = 0
    excluded_source_sha_count = 0
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        row_repo_canonical = canonical_repo(row.get("repo", ""))
        row_sha = safe_strip(row.get("sha"))
        if row_repo_canonical and current_repo_canonical and row_repo_canonical == current_repo_canonical:
            excluded_same_repo_count += 1
            continue
        if row_sha and row_sha in source_sha_set:
            excluded_source_sha_count += 1
            continue
        eligible_rows.append(row)

    def stable_row_key(row: dict[str, Any], tag: str) -> tuple[Any, ...]:
        """构造稳定的排序键，用于在同一 fallback 级别内对候选样本排序。

        排序优先级：
        1. type 重叠数（越多越好）
        2. type pair 重叠数（越多越好）
        3. intent_k 差距（越接近越好）
        4. quality_score（越高越好）
        5. 稳定哈希（打破平局，确保确定性）
        """
        row_types = signature_types(row["type_signature_canonical"])
        overlap_count = len(set(row_types) & requested_type_set)
        pair_overlap = len(
            {
                "+".join(sorted(pair))
                for pair in itertools.combinations(sorted(set(row_types)), 2)
            } & requested_pairs
        )
        return (
            -overlap_count,
            -pair_overlap,
            abs(int(row["intent_k"]) - len(requested_types)),
            -float(row.get("quality_score", 0.0)),
            stable_rank(seed, tag, safe_strip(row.get("example_id"))),
        )

    # 定义 5 级 fallback 检索策略（从精确到泛化）
    # 每一级使用不同的谓词过滤候选样本，逐级放宽约束
    level_specs = [
        # 第 1 级：精确匹配 — type signature 完全相同且 intent_k 一致
        ("exact_kway", lambda row: row["type_signature_canonical"] == type_signature_canonical and int(row["intent_k"]) == len(requested_types)),
        # 第 2 级：type 重叠 — 至少有一个 type 匹配，且重叠数达到候选池最大值
        (
            "type_overlap",
            lambda row: (
                len(set(signature_types(row["type_signature_canonical"])) & requested_type_set) > 0
                and len(set(signature_types(row["type_signature_canonical"])) & requested_type_set)
                == max(
                    [len(set(signature_types(item["type_signature_canonical"])) & requested_type_set) for item in eligible_rows] or [0]
                )
            ),
        ),
        # 第 3 级：pairwise 重叠 — 至少有一对 type pair 匹配
        (
            "pairwise_overlap",
            lambda row: len(
                {
                    "+".join(sorted(pair))
                    for pair in itertools.combinations(sorted(set(signature_types(row["type_signature_canonical"]))), 2)
                } & requested_pairs
            ) > 0,
        ),
        # 第 4 级：单 type 重叠 — 至少有一个 type 匹配
        ("single_type_overlap", lambda row: len(set(signature_types(row["type_signature_canonical"])) & requested_type_set) > 0),
        # 第 5 级：generic fallback — 无条件接受任何可用样本
        ("generic_fallback", lambda _row: True),
    ]

    selected_examples: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_levels: list[str] = []
    query_levels_attempted: list[dict[str, Any]] = []
    examples_found_per_level: dict[str, int] = {}

    for level_name, predicate in level_specs:
        candidates = [row for row in eligible_rows if row["example_id"] not in selected_ids and predicate(row)]
        candidates.sort(key=lambda row: stable_row_key(row, level_name))
        examples_found_per_level[level_name] = len(candidates)
        remaining = max(0, k - len(selected_examples))
        picks = candidates[:remaining] if remaining else []
        for picked in picks:
            selected_examples.append(
                {
                    "example_id": picked["example_id"],
                    "repo": picked["repo"],
                    "sha": picked["sha"],
                    "type_signature_canonical": picked["type_signature_canonical"],
                    "type_pair": picked["type_signature_canonical"],
                    "subject": picked["subject"],
                }
            )
            selected_ids.add(picked["example_id"])
            selected_levels.append(level_name)
        query_levels_attempted.append(
            {
                "level": level_name,
                "candidate_count": len(candidates),
                "selected_count": len(picks),
            }
        )
        if len(selected_examples) >= k:
            break

    if not selected_examples:
        retrieval_status = "failed"
        few_shot_source = "failed"
        failure_reason = "no_examples_after_all_levels"
    else:
        failure_reason = ""
        if selected_levels and all(level == "exact_kway" for level in selected_levels):
            retrieval_status = "exact"
            few_shot_source = "exact_kway"
        elif selected_levels and all(level == "generic_fallback" for level in selected_levels):
            retrieval_status = "generic"
            few_shot_source = "generic_fallback"
        else:
            retrieval_status = "partial"
            deepest_level = selected_levels[-1]
            few_shot_source = deepest_level if deepest_level != "generic_fallback" else "generic_fallback"

    retrieval_log = {
        "requested_type_signature": type_signature_canonical,
        "requested_types_canonical": requested_types,
        "intent_k": int(len(requested_types)),
        "few_shot_requested_k": int(k),
        "query_levels_attempted": query_levels_attempted,
        "examples_found_per_level": examples_found_per_level,
        "selected_example_ids": [row["example_id"] for row in selected_examples],
        "selected_example_type_signatures": [row["type_signature_canonical"] for row in selected_examples],
        "selected_example_repos": [row["repo"] for row in selected_examples],
        "retrieval_status": retrieval_status,
        "failure_reason": failure_reason,
        "excluded_same_repo_count": int(excluded_same_repo_count),
        "excluded_source_sha_count": int(excluded_source_sha_count),
        "excluded_non_train_count": int(retrieval_filter_stats.get("filtered_non_train", 0)),
        "excluded_ineligible_count": int(retrieval_filter_stats.get("filtered_ineligible_flag", 0)),
        "excluded_unverified_count": int(retrieval_filter_stats.get("filtered_unverified_flag", 0)),
        "excluded_bad_style_count": int(retrieval_filter_stats.get("filtered_bad_style", 0)),
        "eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
    }
    return {
        "examples": selected_examples,
        "few_shot_source": few_shot_source,
        "retrieval_backend": "sqlite_formal_kway_v2",
        "retrieval_result_count": len(selected_examples),
        "retrieval_error": failure_reason,
        "retrieval_status": retrieval_status,
        "few_shot_retrieval_log": retrieval_log,
    }


# ============================================================
# Prompt 构建和文本生成函数
# ============================================================

def build_prompt(sample: dict[str, Any], fewshots: list[dict[str, Any]]) -> str:
    """构建用于生成 synthetic subject 的 LLM prompt。

    Prompt 结构：
    1. 角色设定：你正在为一个合并了 N 个提交的 commit 编写消息
    2. Few-shot 示例块（可选）：从 few-shot pool 检索的参考示例
    3. 源信息块：每个 intent 的原始 message、subject 和 diff evidence card
    4. 任务指令：编写一个覆盖所有变更的自然 commit subject
    5. 13 条生成规则（防止常见伪迹）：
       - 规则 1-2: 单行输出，不分开
       - 规则 3-5: 禁止标签模板、bullet points、双前缀
       - 规则 6: 禁止分号机械拼接
       - 规则 7: 禁止编造未在原始消息或 diff evidence 中出现的行为
       - 规则 8-10: 尽量保留所有变更，并保留每个 source subject 的具体锚点，保持简洁
       - 规则 11-13: 允许 "and"，只输出最终结果，禁止列表式输出

    Args:
        sample: 样本数据
        fewshots: few-shot 示例列表

    Returns:
        构建好的 prompt 字符串
    """
    intent_messages = list(sample.get("intent_messages", []))
    intent_subjects = list(sample.get("intent_subjects", []))
    intent_count = len(intent_messages)

    # 构建 few-shot 示例块
    fewshot_block = ""
    if fewshots:
        lines = ["Reference examples of realistic multi-intent commit subjects:"]
        for index, example in enumerate(fewshots, start=1):
            lines.append(f'{index}. ({example["type_pair"]}) {example["subject"]}')
        fewshot_block = "\n".join(lines) + "\n\n"

    source_lines: list[str] = []
    for index, (message, subject) in enumerate(zip(intent_messages, intent_subjects), start=1):
        source_lines.append(f'Original commit message {index}:\n"{message}"')
        source_lines.append(f'Original subject {index}:\n"{subject}"')
        diff_evidence_card = safe_strip(sample.get(f"diff_evidence_card_{index}") or "")
        if not diff_evidence_card:
            diff_evidence_card = "Diff evidence unavailable"
        source_lines.append(f"Diff evidence card {index}:\n{diff_evidence_card}")
    source_block = "\n".join(source_lines)
    task_line = f"Write one natural commit subject that covers all {intent_count} changes.\n"
    return (
        f"You are writing ONE realistic commit message for a commit that combines {intent_count} existing commits.\n"
        f"{fewshot_block}"
        f"{source_block}\n"
        f"{task_line}"
        "Rules:\n"
        "1. Output only one line.\n"
        "2. Do not output separate commit messages.\n"
        f"3. Do not use labels such as \"Change 1\", \"Change {intent_count}\", \"Intent 1\", or \"Intent {intent_count}\".\n"
        "4. Do not use bullet points.\n"
        "5. Do not use multiple conventional prefixes in the same subject.\n"
        "6. Do not use mechanical forms such as \"fix: ...; test: ...\".\n"
        "7. Do not invent behavior not supported by the original messages or diff evidence cards.\n"
        "8. Preserve all changes when possible.\n"
        "9. Keep at least one concrete action or anchor noun from each original subject.\n"
        "10. Keep the subject concise and realistic.\n"
        "11. It is allowed to use \"and\" if that is natural.\n"
        "12. Output only the final commit message.\n"
        "13. Do not use list-like output such as \"change A / change B / change C\".\n"
    )


def build_repair_source_subject_block(sample: dict[str, Any]) -> str:
    """构造 repair 阶段使用的原始 source subject 语义锚点。"""
    subjects = [safe_strip(item) for item in sample.get("intent_subjects", []) if safe_strip(item)]
    if not subjects:
        return "Original source subjects:\n- unavailable"
    lines = ["Original source subjects:"]
    for index, subject in enumerate(subjects, start=1):
        lines.append(f'{index}. "{subject}"')
    return "\n".join(lines)


def is_feat_fix_pair(sample: dict[str, Any]) -> bool:
    """判断当前样本是否为 feat+fix 二元组合。"""
    type_pair = safe_strip(sample.get("type_signature_canonical") or sample.get("type_pair")).lower()
    if type_pair:
        return type_pair == "feat+fix"
    intent_types = [safe_strip(item).lower() for item in sample.get("intent_types", []) if safe_strip(item)]
    if len(intent_types) == 2:
        return "+".join(sorted(intent_types)) == "feat+fix"
    return False


def feat_fix_repair_guidance_needed(sample: dict[str, Any], draft_subject: str, mode: str) -> bool:
    """仅在 feat+fix 草稿出现弱侧塌缩信号时启用更强约束。"""
    if not is_feat_fix_pair(sample):
        return False
    normalized_mode = safe_strip(mode).lower() or "none"
    if normalized_mode == "none":
        return False
    if normalized_mode == "always":
        return True
    lowered = safe_strip(draft_subject).lower()
    if not lowered:
        return False
    body_match = re.match(r"^(?:\([^)]+\)\s*)?(?:[a-z]+(?:\([^)]+\))?:\s*)?(.*)$", lowered)
    body = body_match.group(1) if body_match else lowered
    body_tokens = set(WORD_TOKEN_RE.findall(body))
    return any(token in FEAT_FIX_COLLAPSE_RISK_VERBS for token in body_tokens)


def build_feat_fix_repair_guidance(sample: dict[str, Any], draft_subject: str, mode: str) -> str:
    """为 feat+fix repair 提供额外约束，减少一侧语义塌缩。"""
    if not feat_fix_repair_guidance_needed(sample, draft_subject, mode):
        return ""
    return (
        "- For feat+fix pairs, keep one concrete feat-side anchor and one concrete fix-side anchor.\n"
        "- Prefer a concrete feat object or path anchor and a concrete fix action when both are available.\n"
        "- Do not let either side collapse into generic verbs such as update, improve, or handle.\n"
    )


def build_compress_prompt(
    sample: dict[str, Any],
    draft_subject: str,
    length_limit: int,
    feat_fix_repair_guidance_mode: str = "none",
) -> str:
    """构造 source-aware 压缩提示，尽量避免压缩时丢失某个 intent。"""
    intent_count = int(sample.get("intent_k") or len(sample.get("intent_subjects", [])) or 0)
    source_block = build_repair_source_subject_block(sample)
    feat_fix_guidance = build_feat_fix_repair_guidance(sample, draft_subject, feat_fix_repair_guidance_mode)
    return (
        f"Rewrite this draft commit subject into ONE realistic commit subject within {length_limit} characters.\n"
        f"{source_block}\n"
        f'Draft subject:\n"{draft_subject}"\n'
        "Requirements:\n"
        f"- Preserve all {intent_count} source changes.\n"
        "- Keep at least one concrete action or anchor noun from each original subject.\n"
        f"{feat_fix_guidance}"
        "- Use one natural commit subject, not a list.\n"
        "- Prefer one natural conventional prefix or no prefix.\n"
        "- Output only the rewritten subject.\n"
    )


def build_rewrite_prompt(
    sample: dict[str, Any],
    draft_subject: str,
    length_limit: int,
    feat_fix_repair_guidance_mode: str = "none",
) -> str:
    """构造 source-aware 重写提示，兼顾格式修复与语义保真。"""
    intent_count = int(sample.get("intent_k") or len(sample.get("intent_subjects", [])) or 0)
    source_block = build_repair_source_subject_block(sample)
    feat_fix_guidance = build_feat_fix_repair_guidance(sample, draft_subject, feat_fix_repair_guidance_mode)
    return (
        "Rewrite the following text into one natural commit subject.\n"
        f"{source_block}\n"
        f'Text:\n"{draft_subject}"\n'
        "Constraints:\n"
        f"- single line, <= {length_limit} chars\n"
        "- no labels, no bullets, no list-like output\n"
        "- no multiple conventional prefixes in the same subject\n"
        f"- preserve all {intent_count} source changes\n"
        "- keep at least one concrete action or anchor noun from each original subject\n"
        f"{feat_fix_guidance}"
        "- output only the rewritten subject\n"
    )


def build_final_strong_compress_prompt(
    sample: dict[str, Any],
    draft_subject: str,
    length_limit: int,
    enable_path_tail_compress: bool = False,
) -> str:
    """构造最终强压缩提示，仅用于仍然超长的 repair 失败样本。"""
    intent_count = int(sample.get("intent_k") or len(sample.get("intent_subjects", [])) or 0)
    source_block = build_repair_source_subject_block(sample)
    path_tail_guidance = ""
    if enable_path_tail_compress:
        path_tail_guidance = (
            "- If a path-like anchor is necessary, keep the shortest identifiable tail of the path.\n"
            "- Remove backticks around paths or identifiers.\n"
            "- Compress path segments before the tail before dropping the path anchor entirely.\n"
        )
    return (
        "Do one final aggressive compression of this draft commit subject.\n"
        f"{source_block}\n"
        f'Draft subject:\n"{draft_subject}"\n'
        "Requirements:\n"
        f"- You must fit within {length_limit} characters.\n"
        f"- Preserve all {intent_count} source changes.\n"
        "- Keep at least one concrete action or anchor noun from each original subject.\n"
        "- Aggressively shorten wording by dropping modifiers, abbreviating phrases, and merging repeated context.\n"
        "- You may use safe technical abbreviations when they stay faithful to the source subjects.\n"
        "- Prefer shortening repeated context, long paths, and long technical compounds before dropping anchor nouns.\n"
        f"{path_tail_guidance}"
        "- Keep one natural commit subject, not a list.\n"
        "- Output only the rewritten subject.\n"
    )


def compress_final_strong_path_tail(subject: str, length_limit: int) -> str:
    """对 final_strong_compress 结果做极窄的路径尾部压缩。"""
    text = safe_strip(subject)
    if not text:
        return ""
    text = text.replace("`", "")
    if len(text) <= length_limit:
        return text

    path_pattern = re.compile(r"[@A-Za-z0-9_.-]+(?:/[@A-Za-z0-9_.-]+)+")

    def replace_with_tail(current_text: str, keep_segments: int) -> str:
        changed = False

        def repl(match: re.Match[str]) -> str:
            nonlocal changed
            raw = match.group(0)
            parts = [part for part in raw.split("/") if part]
            if len(parts) <= keep_segments:
                return raw
            changed = True
            return "/".join(parts[-keep_segments:])

        updated = path_pattern.sub(repl, current_text)
        return updated if changed else current_text

    for keep_segments in (2, 1):
        updated = replace_with_tail(text, keep_segments)
        text = updated
        if len(text) <= length_limit:
            break
    return text


def normalize_generated_subject(text: str) -> str:
    """规范化生成的 subject，去除多余的引号和代码块标记"""
    if text is None:
        return ""
    out = str(text).replace("\r", "").strip()
    if out.startswith(("```", "\"", "'")) and out.endswith(("```", "\"", "'")):
        out = out.strip("`").strip("\"").strip("'").strip()
    return out


def contains_generic_phrase(text: str) -> int:
    """检测是否命中常见空泛短语。"""
    target = safe_strip(text)
    if not target:
        return 0
    return int(any(pattern.search(target) for pattern in GENERIC_PHRASE_PATTERNS))


def subject_surface_features(subject: str) -> dict[str, Any]:
    """抽取提交 subject 的表层风格特征（用于质量监控）。"""
    text = safe_strip(subject)
    if not text:
        return {
            "token_count": 0,
            "and_used": 0,
            "comma_used": 0,
            "prefix_used": 0,
            "issue_id_present": 0,
            "single_sentence": 0,
            "imperative_head": 0,
            "generic_phrase_hit": 0,
        }

    token_count = len(WORD_TOKEN_RE.findall(text))
    and_used = int(bool(AND_RE.search(text)))
    comma_used = int("," in text)
    prefix_used = int(bool(PREFIX_RE.search(text)))
    issue_id_present = int(bool(ISSUE_ID_RE.search(text)))
    single_sentence = int("\n" not in text and not BULLET_LINE_RE.search(text) and not NUMBERED_LINE_RE.search(text))
    generic_phrase_hit = contains_generic_phrase(text)

    lowered = text.lower()
    prefix_match = re.match(r"^[a-z]+(?:\([^)]+\))?:\s*(.+)$", lowered)
    head_region = prefix_match.group(1) if prefix_match else lowered
    head_tokens = WORD_TOKEN_RE.findall(head_region)
    head_token = head_tokens[0] if head_tokens else ""
    imperative_head = int(head_token in IMPERATIVE_HEAD_VERBS)

    return {
        "token_count": token_count,
        "and_used": and_used,
        "comma_used": comma_used,
        "prefix_used": prefix_used,
        "issue_id_present": issue_id_present,
        "single_sentence": single_sentence,
        "imperative_head": imperative_head,
        "generic_phrase_hit": generic_phrase_hit,
    }


def short_text_preview(payload: Any, limit: int = 400) -> str:
    """生成用于审计日志的短文本预览。"""
    if payload is None:
        return ""
    if isinstance(payload, str):
        text = payload
    else:
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            text = str(payload)
    text = text.replace("\r", " ").replace("\n", "\\n")
    if len(text) > limit:
        return text[:limit] + "...[truncated]"
    return text


RUN_BLOCKING_PROVIDER_ERROR_TYPES = {
    "http_401",
    "http_402",
    "http_403",
    "http_404",
    "http_429",
}


def is_run_blocking_provider_error(error_type: str) -> bool:
    """判断是否属于应立即中止整轮运行的 provider 硬错误。"""
    return safe_strip(error_type) in RUN_BLOCKING_PROVIDER_ERROR_TYPES


def provider_error_guidance(error_type: str) -> str:
    """给 provider 硬错误补充可操作的人工处理提示。"""
    normalized = safe_strip(error_type)
    if normalized == "http_401":
        return "api_key_invalid_or_expired"
    if normalized == "http_402":
        return "insufficient_balance_or_billing_blocked"
    if normalized == "http_403":
        return "provider_forbidden_or_account_not_allowed"
    if normalized == "http_404":
        return "model_or_endpoint_not_found"
    if normalized == "http_429":
        return "provider_rate_limited_or_quota_exhausted"
    return "provider_request_blocked"


def subject_format_check(subject: str, length_limit: int) -> dict[str, Any]:
    """检查生成的 subject 格式是否合法

    检查项：
    1. 非空
    2. 单行
    3. 长度不超过限制
    4. 不含标签模板（Change 1 / Intent 2）
    5. 不含 bullet / numbered list
    6. 不含双 conventional prefix
    7. 不含分号式机械拼接

    Returns:
        包含格式检查结果和字符长度的字典
    """
    text = safe_strip(subject)
    nonempty = bool(text)
    single_line = "\n" not in text
    char_len = len(text)
    len_ok = char_len <= length_limit
    label_template_hit = int(bool(LABEL_TEMPLATE_RE.search(text)))
    bullet_hit = int(bool(BULLET_LINE_RE.search(text)))
    numbered_list_hit = int(bool(NUMBERED_LINE_RE.search(text)))
    prefix_count = len(PREFIX_RE.findall(text))
    dual_prefix_hit = int(prefix_count >= 2)
    mechanical_semicolon_hit = int(";" in text)
    # format=1 表示格式完全合法（通过所有检查项）
    fmt = 1 if (
        nonempty
        and single_line
        and len_ok
        and (label_template_hit == 0)
        and (bullet_hit == 0)
        and (numbered_list_hit == 0)
        and (dual_prefix_hit == 0)
        and (mechanical_semicolon_hit == 0)
    ) else 0
    return {
        "format": fmt,
        "nonempty": int(nonempty),
        "single_line": int(single_line),
        "char_len": char_len,
        "len_ok": int(len_ok),
        "label_template_hit": label_template_hit,
        "bullet_hit": bullet_hit,
        "numbered_list_hit": numbered_list_hit,
        "prefix_count": prefix_count,
        "dual_prefix_hit": dual_prefix_hit,
        "mechanical_semicolon_hit": mechanical_semicolon_hit,
    }


def deepseek_generate(
    prompt: str,
    args: argparse.Namespace,
    generation_cache: dict[str, Any],
    cache_enabled: bool,
    extra_tag: str,
) -> dict[str, Any]:
    """调用 DeepSeek API 生成文本

    支持缓存：相同请求会先检查缓存，命中则直接返回。

    Args:
        prompt: 输入 prompt
        args: 参数命名空间
        generation_cache: 生成缓存字典
        cache_enabled: 是否启用缓存
        extra_tag: 额外标签（用于区分不同阶段的请求）

    Returns:
        包含生成结果、缓存状态、错误信息的字典
    """
    api_key = safe_strip(getattr(args, "_resolved_deepseek_api_key", ""))
    # 构建请求 payload
    payload = {
        "model": args.generator_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_output_tokens,
        "seed": args.seed,
    }
    thinking_type = safe_strip(getattr(args, "generator_thinking_type", ""))
    if thinking_type and model_supports_thinking_control(args.generator_model):
        payload["thinking"] = {"type": thinking_type}
    # 计算缓存 key（基于请求内容）
    cache_key_payload = {
        "provider": args.generator_provider,
        "base_url": args.deepseek_base_url,
        "payload": payload,
        "extra_tag": extra_tag,
    }
    cache_key = canonical_json_hash(cache_key_payload)
    # 缓存命中，直接返回
    if cache_enabled and cache_key in generation_cache:
        cached = generation_cache[cache_key]
        return {
            "ok": True,
            "content": cached.get("content", ""),
            "cached": True,
            "request_sha256": cache_key,
            "raw_response": cached.get("raw_response"),
            "error_type": "",
        }

    # 发送 API 请求
    req = urllib.request.Request(
        args.deepseek_base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.api_timeout_sec) as response:
            raw_text = response.read().decode("utf-8")
            decoded = json.loads(raw_text)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network runtime dependent
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "content": "",
            "cached": False,
            "request_sha256": cache_key,
            "raw_response": detail,
            "error_type": f"http_{exc.code}",
        }
    except Exception as exc:  # pragma: no cover - network runtime dependent
        return {
            "ok": False,
            "content": "",
            "cached": False,
            "request_sha256": cache_key,
            "raw_response": str(exc),
            "error_type": "request_error",
        }

    # 解析响应内容
    content = ""
    try:
        choice = decoded["choices"][0]
        message = choice["message"]
        content = message.get("content")
    except Exception:
        return {
            "ok": False,
            "content": "",
            "cached": False,
            "request_sha256": cache_key,
            "raw_response": decoded,
            "error_type": "response_parse_error",
        }
    content = "" if content is None else str(content)
    finish_reason = safe_strip(choice.get("finish_reason"))
    reasoning_content = safe_strip(message.get("reasoning_content"))
    usage = decoded.get("usage") or {}
    token_details = usage.get("completion_tokens_details") or {}
    reasoning_tokens = token_details.get("reasoning_tokens")
    if not safe_strip(content):
        error_type = "empty_content_response"
        if finish_reason == "length" and reasoning_content:
            error_type = "reasoning_only_truncated"
            if reasoning_tokens in (None, ""):
                token_details["reasoning_tokens"] = usage.get("completion_tokens")
        return {
            "ok": False,
            "content": "",
            "cached": False,
            "request_sha256": cache_key,
            "raw_response": decoded,
            "error_type": error_type,
        }

    # 更新缓存
    if cache_enabled:
        generation_cache[cache_key] = {
            "content": content,
            "raw_response": decoded,
            "cached_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        }
    return {
        "ok": True,
        "content": content,
        "cached": False,
        "request_sha256": cache_key,
        "raw_response": decoded,
        "error_type": "",
    }


def build_mock_subject(sample: dict[str, Any], length_limit: int) -> str:
    """为 debug mock 模式构造确定性的 synthetic subject。

    不调用远程 API，直接将原始 intent subject 用 "and" 连接。
    如果超长则截断。用于 --debug-mock-generator 或 --generator-mode mock 调试。
    """
    subjects = [safe_strip(item) for item in sample.get("intent_subjects", []) if safe_strip(item)]
    if not subjects:
        return "mock synthetic subject"
    subject = build_default_fewshot_subject(subjects)
    if len(subject) <= length_limit:
        return subject
    shortened = " and ".join(subjects[:2])
    if len(shortened) <= length_limit:
        return shortened
    return subject[:length_limit].rstrip(" ,;")


def generate_subject_with_repair(
    sample: dict[str, Any],
    args: argparse.Namespace,
    length_limit: int,
    fewshot_info: dict[str, Any],
    generation_cache: dict[str, Any],
) -> dict[str, Any]:
    """生成 synthetic subject 并自动修复格式问题。

    四阶段修复策略（以 generation attempt 为外层循环）：
    1. 生成阶段：调用 DeepSeek API 生成 subject，检查格式是否合法
    2. 压缩阶段：如果超长（char_len > length_limit），调用 API 做抽象式压缩
    3. 重写阶段：如果格式仍不合法（标签、bullet 等），调用 API 完全重写
    4. 最终强压缩阶段：如果前面 repair 后仍然只是“超长”，再做一次更激进的缩句

    每个阶段成功则立即返回，失败则进入下一阶段。
    所有阶段都失败后，返回空 subject，后续被硬拒绝（weight=0）。

    Args:
        sample: 样本数据（包含 intent_subjects, intent_messages 等）
        args: 命令行参数（包含 API 配置、重试次数等）
        length_limit: subject 长度上限（字符数，来自 P90 统计）
        fewshot_info: few-shot 检索结果
        generation_cache: 生成缓存字典

    Returns:
        包含以下字段的字典：
        - synthetic_subject: 生成的 subject（失败时为空字符串）
        - generation_success: 是否生成成功
        - message_error_type: 错误类型（成功时为 "ok"）
        - generation/compress/rewrite/final_strong_compress_attempts: 各阶段尝试次数
        - request_sha_chain: 请求哈希链（用于审计）
        - generation_trace: 详细的生成轨迹
        - cache_hit_count: 缓存命中次数
    """
    prompt = build_prompt(sample, fewshot_info["examples"])
    generation_attempts = 0
    compress_attempts = 0
    rewrite_attempts = 0
    final_strong_compress_attempts = 0
    cache_hit_count = 0
    last_error_type = ""
    request_sha_chain: list[str] = []
    generation_trace: list[dict[str, Any]] = []
    intent_count = int(sample.get("intent_k") or len(sample.get("intent_subjects", [])) or 0)
    effective_length_limit = int(length_limit)

    if getattr(args, "generator_mode", "api") == "mock":
        prompt = build_prompt(sample, fewshot_info["examples"])
        subject = normalize_generated_subject(build_mock_subject(sample, length_limit))
        fmt = subject_format_check(subject, length_limit)
        generation_trace.append(
            {
                "stage": "mock_generate",
                "attempt_index": 1,
                "ok": True,
                "cached": False,
                "request_sha256": canonical_json_hash(
                    {"sample_id": sample.get("sample_id"), "prompt": prompt, "mode": "mock"}
                ),
                "error_type": "",
                "subject_after": subject,
                "subject_after_char_len": int(fmt["char_len"]),
                "subject_after_format_ok": int(fmt["format"]),
                "raw_response_preview": short_text_preview({"generator_mode": "mock", "prompt_preview": prompt[:240]}),
            }
        )
        return {
            "synthetic_subject": subject if fmt["format"] == 1 else "",
            "generation_success": bool(fmt["format"] == 1),
            "message_error_type": "ok" if fmt["format"] == 1 else "mock_generation_format_failed",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "final_strong_compress_attempts": 0,
            "effective_length_limit": int(length_limit),
            "request_sha_chain": [generation_trace[0]["request_sha256"]],
            "generation_trace": generation_trace,
            "cache_hit_count": 0,
            "raw_response": {"generator_mode": "mock"},
        }

    def append_trace(
        stage: str,
        attempt_index: int,
        response: dict[str, Any],
        subject_after: str,
    ) -> None:
        trace_length_limit = int(effective_length_limit if stage == "final_strong_compress" else length_limit)
        fmt = subject_format_check(subject_after, trace_length_limit)
        generation_trace.append(
            {
                "stage": stage,
                "attempt_index": int(attempt_index),
                "ok": bool(response["ok"]),
                "cached": bool(response["cached"]),
                "request_sha256": response["request_sha256"],
                "error_type": response.get("error_type", ""),
                "length_limit_used": trace_length_limit,
                "subject_after": subject_after,
                "subject_after_char_len": int(fmt["char_len"]),
                "subject_after_format_ok": int(fmt["format"]),
                "raw_response_preview": short_text_preview(response.get("raw_response")),
            }
        )

    subject = ""
    raw_response = None
    generation_success = False
    provider_blocking_error = False
    provider_blocking_error_type = ""
    provider_blocking_error_detail = ""

    # 允许“生成失败/修复失败后重新生成”：以 generation attempt 为外层循环
    for gen_index in range(1, args.max_generation_attempts + 1):
        effective_length_limit = int(length_limit)
        generation_attempts += 1
        response = deepseek_generate(
            prompt=prompt,
            args=args,
            generation_cache=generation_cache,
            cache_enabled=args.generation_cache_enabled,
            extra_tag=f"{sample['sample_id']}:generate:{gen_index}",
        )
        request_sha_chain.append(response["request_sha256"])
        if response["cached"]:
            cache_hit_count += 1

        if not response["ok"]:
            last_error_type = response["error_type"] or "generation_failed"
            raw_response = response["raw_response"]
            append_trace("generate", gen_index, response, subject_after="")
            if is_run_blocking_provider_error(last_error_type):
                provider_blocking_error = True
                provider_blocking_error_type = last_error_type
                provider_blocking_error_detail = short_text_preview(response["raw_response"])
                break
            continue

        subject = normalize_generated_subject(response["content"])
        raw_response = response["raw_response"]
        append_trace("generate", gen_index, response, subject_after=subject)
        format_state = subject_format_check(subject, length_limit)
        if format_state["format"] == 1:
            generation_success = True
            last_error_type = ""
            break

        # 阶段2：压缩（如果超长）
        if format_state["char_len"] > length_limit:
            for _ in range(args.max_abstractive_compress_attempts):
                compress_attempts += 1
                compress_prompt = build_compress_prompt(
                    sample,
                    subject,
                    length_limit,
                    feat_fix_repair_guidance_mode=safe_strip(
                        getattr(args, "feat_fix_repair_guidance_mode", "none")
                    ),
                )
                response = deepseek_generate(
                    prompt=compress_prompt,
                    args=args,
                    generation_cache=generation_cache,
                    cache_enabled=args.generation_cache_enabled,
                    extra_tag=f"{sample['sample_id']}:compress:{gen_index}:{compress_attempts}",
                )
                request_sha_chain.append(response["request_sha256"])
                if response["cached"]:
                    cache_hit_count += 1
                if not response["ok"]:
                    last_error_type = response["error_type"] or "compress_failed"
                    append_trace("compress", compress_attempts, response, subject_after=subject)
                    if is_run_blocking_provider_error(last_error_type):
                        provider_blocking_error = True
                        provider_blocking_error_type = last_error_type
                        provider_blocking_error_detail = short_text_preview(response["raw_response"])
                        break
                    continue
                subject = normalize_generated_subject(response["content"])
                raw_response = response["raw_response"]
                append_trace("compress", compress_attempts, response, subject_after=subject)
                if subject_format_check(subject, length_limit)["format"] == 1:
                    generation_success = True
                    last_error_type = ""
                    break
            if provider_blocking_error:
                break
            if generation_success:
                break

        # 阶段3：重写（如果格式仍不合法）
        if subject_format_check(subject, length_limit)["format"] == 0:
            for _ in range(args.max_rewrite_attempts):
                rewrite_attempts += 1
                rewrite_prompt = build_rewrite_prompt(
                    sample,
                    subject,
                    length_limit,
                    feat_fix_repair_guidance_mode=safe_strip(
                        getattr(args, "feat_fix_repair_guidance_mode", "none")
                    ),
                )
                response = deepseek_generate(
                    prompt=rewrite_prompt,
                    args=args,
                    generation_cache=generation_cache,
                    cache_enabled=args.generation_cache_enabled,
                    extra_tag=f"{sample['sample_id']}:rewrite:{gen_index}:{rewrite_attempts}",
                )
                request_sha_chain.append(response["request_sha256"])
                if response["cached"]:
                    cache_hit_count += 1
                if not response["ok"]:
                    last_error_type = response["error_type"] or "rewrite_failed"
                    append_trace("rewrite", rewrite_attempts, response, subject_after=subject)
                    if is_run_blocking_provider_error(last_error_type):
                        provider_blocking_error = True
                        provider_blocking_error_type = last_error_type
                        provider_blocking_error_detail = short_text_preview(response["raw_response"])
                        break
                    continue
                subject = normalize_generated_subject(response["content"])
                raw_response = response["raw_response"]
                append_trace("rewrite", rewrite_attempts, response, subject_after=subject)
                if subject_format_check(subject, length_limit)["format"] == 1:
                    generation_success = True
                    last_error_type = ""
                    break
            if provider_blocking_error:
                break
            if generation_success:
                break

        # 阶段4：最终强压缩（仅针对 repair 后仍然超长的样本）
        final_format_state = subject_format_check(subject, length_limit)
        if final_format_state["format"] == 0 and final_format_state["char_len"] > length_limit:
            relaxed_length_limit = int(
                max(
                    length_limit,
                    getattr(
                        args,
                        "_final_strong_relaxed_length_limit",
                        getattr(args, "final_strong_relaxed_length_limit", length_limit),
                    ),
                )
            )
            for _ in range(getattr(args, "max_final_strong_compress_attempts", 1)):
                final_strong_compress_attempts += 1
                effective_length_limit = relaxed_length_limit
                final_compress_prompt = build_final_strong_compress_prompt(
                    sample,
                    subject,
                    relaxed_length_limit,
                    enable_path_tail_compress=bool(
                        getattr(args, "enable_final_strong_path_tail_compress", False)
                    ),
                )
                response = deepseek_generate(
                    prompt=final_compress_prompt,
                    args=args,
                    generation_cache=generation_cache,
                    cache_enabled=args.generation_cache_enabled,
                    extra_tag=f"{sample['sample_id']}:final_strong_compress:{gen_index}:{final_strong_compress_attempts}",
                )
                request_sha_chain.append(response["request_sha256"])
                if response["cached"]:
                    cache_hit_count += 1
                if not response["ok"]:
                    last_error_type = response["error_type"] or "final_strong_compress_failed"
                    append_trace("final_strong_compress", final_strong_compress_attempts, response, subject_after=subject)
                    if is_run_blocking_provider_error(last_error_type):
                        provider_blocking_error = True
                        provider_blocking_error_type = last_error_type
                        provider_blocking_error_detail = short_text_preview(response["raw_response"])
                        break
                    continue
                subject = normalize_generated_subject(response["content"])
                if bool(getattr(args, "enable_final_strong_path_tail_compress", False)):
                    subject = compress_final_strong_path_tail(subject, relaxed_length_limit)
                raw_response = response["raw_response"]
                append_trace("final_strong_compress", final_strong_compress_attempts, response, subject_after=subject)
                if subject_format_check(subject, relaxed_length_limit)["format"] == 1:
                    generation_success = True
                    last_error_type = ""
                    break
            if provider_blocking_error:
                break
            if generation_success:
                break

        last_error_type = "quality_not_pass_after_repair"
        if provider_blocking_error:
            break

    if not generation_success:
        # 失败结果不进入后续质量流程：返回空 subject，后续会被硬拒绝
        subject = ""

    return {
        "synthetic_subject": subject,
        "generation_success": bool(generation_success),
        "message_error_type": last_error_type or ("ok" if generation_success else "generation_failed"),
        "generation_attempts": generation_attempts,
        "compress_attempts": compress_attempts,
        "rewrite_attempts": rewrite_attempts,
        "final_strong_compress_attempts": final_strong_compress_attempts,
        "effective_length_limit": int(effective_length_limit),
        "request_sha_chain": request_sha_chain,
        "generation_trace": generation_trace,
        "cache_hit_count": cache_hit_count,
        "raw_response": raw_response,
        "provider_blocking_error": provider_blocking_error,
        "provider_blocking_error_type": provider_blocking_error_type,
        "provider_blocking_error_detail": provider_blocking_error_detail,
    }


# ============================================================
# BERTScore 评分函数
# ============================================================

def init_bertscorer(args: argparse.Namespace) -> Any:
    """初始化 BERTScorer 实例"""
    with temporary_env_overrides(bertscore_offline_env_overrides(args.bertscore_model)):
        from bert_score import BERTScorer

        return BERTScorer(
            model_type=args.bertscore_model,
            lang=args.bertscore_lang,
            idf=bool(args.bertscore_idf),
            rescale_with_baseline=False,
        )


def bertscore_pair(
    candidate: str,
    reference: str,
    args: argparse.Namespace,
    bertscore_cache: dict[str, Any],
    bertscorer: Any,
) -> dict[str, Any]:
    """计算候选文本和参考文本的 BERTScore

    计算 precision、recall、f1 三个指标，支持缓存。

    Args:
        candidate: 候选文本（synthetic subject）
        reference: 参考文本（原始 subject 或上下文）
        args: 参数
        bertscore_cache: BERTScore 缓存字典
        bertscorer: BERTScorer 实例

    Returns:
        包含评分结果和缓存状态的字典
    """
    key_payload = {
        "candidate": candidate,
        "reference": reference,
        "model": args.bertscore_model,
        "lang": args.bertscore_lang,
        "idf": bool(args.bertscore_idf),
    }
    cache_key = canonical_json_hash(key_payload)
    # 缓存命中
    if args.bertscore_cache_enabled and cache_key in bertscore_cache:
        cached = bertscore_cache[cache_key]
        return {
            "precision": float(cached["precision"]),
            "recall": float(cached["recall"]),
            "f1": float(cached["f1"]),
            "cached": True,
            "invalid": False,
            "error": "",
            "cache_key": cache_key,
        }

    # 计算 BERTScore
    try:
        p, r, f = bertscorer.score([candidate], [reference], verbose=False)
        precision = float(p[0].item())
        recall = float(r[0].item())
        f1 = float(f[0].item())
    except Exception as exc:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "cached": False,
            "invalid": True,
            "error": str(exc),
            "cache_key": cache_key,
        }

    # 更新缓存
    if args.bertscore_cache_enabled:
        bertscore_cache[cache_key] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "cached_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        }
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "cached": False,
        "invalid": False,
        "error": "",
        "cache_key": cache_key,
    }


def compute_message_scores(
    sample: dict[str, Any],
    synthetic_subject: str,
    length_limit: int,
    args: argparse.Namespace,
    bertscore_cache: dict[str, Any],
    bertscorer: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """计算消息评分（BERT 主评分 + 规则监控维度）

    计算：
    1. coverage_i_r: synthetic subject 对每个 intent subject 的 BERTScore recall
    2. coverage_min_r: 所有 coverage_i_r 的最小值
    3. coverage_balance: 覆盖平衡度（1 - max-min）
    4. faithfulness_p: synthetic subject 对源上下文的 BERTScore precision
    5. artifact/relevance/style 监控项（不参与当前硬 gate）
    6. message_quality_weight: 主质量权重 = format * faithfulness * min(coverage_i)

    Args:
        sample: 样本数据
        synthetic_subject: 生成的合成主题
        length_limit: 长度限制
        args: 参数
        bertscore_cache: BERTScore 缓存
        bertscorer: BERTScorer 实例

    Returns:
        (评分字典, 评分元数据字典)
    """
    format_state = subject_format_check(synthetic_subject, length_limit)

    # 空 subject 直接返回零分
    if not synthetic_subject.strip():
        pattern_flags = detect_message_pattern_flags(synthetic_subject)
        surface_features = subject_surface_features(synthetic_subject)
        scores = {
            "format": 0,
            "coverage_r_list": [],
            "coverage_by_source": [],
            "coverage_min_r": 0.0,
            "coverage_min": 0.0,
            "coverage_avg_r": 0.0,
            "coverage_avg": 0.0,
            "coverage_balance": 0.0,
            "faithfulness_p": 0.0,
            "artifact_hit_count": int(pattern_flags.get("artifact_hit_count", 0)),
            "artifact_score": 0.0,
            "relevance_score": 0.0,
            "style_score": 0.0,
            "generic_phrase_hit": int(surface_features.get("generic_phrase_hit", 0)),
            "token_count": int(surface_features.get("token_count", 0)),
            "imperative_head": int(surface_features.get("imperative_head", 0)),
            "message_quality_weight": 0.0,
            "bertscore_compute_invalid": 0,
            "bertscore_error": "",
        }
        score_meta = {
            "coverage_cache_keys": [],
            "faithfulness_cache_key": "",
            "format_detail": format_state,
            "pattern_flags": pattern_flags,
            "surface_features": surface_features,
        }
        return scores, score_meta

    subjects = list(sample.get("intent_subjects", []))
    messages = list(sample.get("intent_messages", []))
    if not subjects or not messages or len(subjects) != len(messages):
        raise RuntimeError(
            "Invalid sample intent fields for scoring: "
            f"subjects={len(subjects)} messages={len(messages)}"
        )
    # 构建源上下文（用于计算 faithfulness）
    source_context_parts: list[str] = []
    for index, (subject, message) in enumerate(zip(subjects, messages), start=1):
        source_context_parts.append(subject)
        source_context_parts.append(message)
        source_context_parts.append(sample.get(f"diff_evidence_card_{index}", ""))
    source_context = " ".join(part for part in source_context_parts if part).strip()

    coverage_items = [
        bertscore_pair(synthetic_subject, subject, args, bertscore_cache, bertscorer=bertscorer)
        for subject in subjects
    ]
    faith = bertscore_pair(synthetic_subject, source_context, args, bertscore_cache, bertscorer=bertscorer)

    invalid = int(any(item["invalid"] for item in coverage_items) or faith["invalid"])
    coverage_r_list = [item["recall"] if not item["invalid"] else 0.0 for item in coverage_items]
    # 取所有 coverage 的最小值（木桶效应：最弱的 intent 决定整体覆盖质量）
    coverage_min_r = min(coverage_r_list) if coverage_r_list else 0.0
    coverage_avg_r = (sum(coverage_r_list) / len(coverage_r_list)) if coverage_r_list else 0.0
    coverage_span = (max(coverage_r_list) - min(coverage_r_list)) if coverage_r_list else 1.0
    # coverage_balance: 覆盖平衡度，1 - (max - min)，越接近 1 表示各 intent 覆盖越均匀
    coverage_balance = max(0.0, 1.0 - coverage_span)
    faithfulness_p = faith["precision"] if not faith["invalid"] else 0.0
    pattern_flags = detect_message_pattern_flags(synthetic_subject)
    surface_features = subject_surface_features(synthetic_subject)
    artifact_hit_count = int(pattern_flags.get("artifact_hit_count", 0))
    # 取值区间 (0, 1]，命中越多分值越低；仅作监控，不参与硬拒绝。
    artifact_score = 1.0 / (1.0 + float(artifact_hit_count))
    relevance_score = 1.0 - float(surface_features.get("generic_phrase_hit", 0))
    style_components = [
        float(surface_features.get("single_sentence", 0)),
        float(surface_features.get("imperative_head", 0)),
        1.0 - float(surface_features.get("generic_phrase_hit", 0)),
        1.0 if artifact_hit_count == 0 else 0.0,
    ]
    style_score = sum(style_components) / len(style_components)
    # 综合质量权重 = 格式合法 * 忠实度 * 最小覆盖率
    message_quality_weight = float(format_state["format"]) * faithfulness_p * coverage_min_r

    scores = {
        "format": int(format_state["format"]),
        "coverage_r_list": [round(value, 6) for value in coverage_r_list],
        "coverage_by_source": [round(value, 6) for value in coverage_r_list],
        "coverage_min_r": round(coverage_min_r, 6),
        "coverage_min": round(coverage_min_r, 6),
        "coverage_avg_r": round(coverage_avg_r, 6),
        "coverage_avg": round(coverage_avg_r, 6),
        "coverage_balance": round(coverage_balance, 6),
        "faithfulness_p": round(faithfulness_p, 6),
        "artifact_hit_count": artifact_hit_count,
        "artifact_score": round(artifact_score, 6),
        "relevance_score": round(relevance_score, 6),
        "style_score": round(style_score, 6),
        "generic_phrase_hit": int(surface_features.get("generic_phrase_hit", 0)),
        "token_count": int(surface_features.get("token_count", 0)),
        "imperative_head": int(surface_features.get("imperative_head", 0)),
        "message_quality_weight": round(message_quality_weight, 6),
        "bertscore_compute_invalid": invalid,
        "bertscore_error": ";".join(error for error in ([item["error"] for item in coverage_items] + [faith["error"]]) if error),
    }
    if coverage_r_list:
        scores["coverage_1_r"] = round(coverage_r_list[0], 6)
    if len(coverage_r_list) >= 2:
        scores["coverage_2_r"] = round(coverage_r_list[1], 6)
    score_meta = {
        "coverage_cache_keys": [item["cache_key"] for item in coverage_items],
        "faithfulness_cache_key": faith["cache_key"],
        "format_detail": format_state,
        "pattern_flags": pattern_flags,
        "surface_features": surface_features,
    }
    return scores, score_meta


# ============================================================
# 阈值校准函数
# ============================================================

def kmeans_1d_thresholds(values: list[float], k: int = 3, max_iter: int = 60) -> tuple[float, float, dict[str, Any]]:
    """使用 1D K-means 将一维数据聚为 k=3 类，计算 reject/pass 阈值。

    聚类目标：将 message_quality_weight 分为 reject / fallback / pass 三档。
    阈值计算：取相邻类中心的中点作为分界线。

    当数据不足（< k 个或 < k 个不同值）时，退化为使用分位数（33% / 67%）。

    Args:
        values: 一维数值列表（message_quality_weight）
        k: 聚类数量（固定为 3）
        max_iter: 最大迭代次数

    Returns:
        (t_reject, t_pass, detail):
        - t_reject: reject/fallback 分界阈值
        - t_pass: fallback/pass 分界阈值
        - detail: 详细信息（centroids 或 fallback 原因）
    """
    sorted_values = sorted(values)
    if not sorted_values:
        return 0.0, 0.0, {"fallback": "empty_values"}
    # 数据不足时，使用分位数作为 fallback
    if len(sorted_values) < k or len(set(sorted_values)) < k:
        t_reject = nearest_rank_percentile(sorted_values, 0.33)
        t_pass = nearest_rank_percentile(sorted_values, 0.67)
        return t_reject, t_pass, {"fallback": "quantile_33_67"}

    # 初始化质心（使用分位数）
    centroids = [nearest_rank_percentile(sorted_values, (i + 0.5) / k) for i in range(k)]
    # K-means 迭代
    for _ in range(max_iter):
        buckets: list[list[float]] = [[] for _ in range(k)]
        for value in sorted_values:
            distances = [abs(value - center) for center in centroids]
            bucket_index = distances.index(min(distances))
            buckets[bucket_index].append(value)
        new_centroids = []
        for idx, bucket in enumerate(buckets):
            if bucket:
                new_centroids.append(sum(bucket) / len(bucket))
            else:
                new_centroids.append(centroids[idx])
        # 检查收敛
        if all(abs(old - new) < 1e-9 for old, new in zip(centroids, new_centroids)):
            centroids = new_centroids
            break
        centroids = new_centroids

    # 用相邻质心的中点作为阈值
    ordered = sorted(centroids)
    t_reject = (ordered[0] + ordered[1]) / 2
    t_pass = (ordered[1] + ordered[2]) / 2
    return float(t_reject), float(t_pass), {"centroids": ordered}


def calibrate_message_thresholds(values: list[float], method: str) -> dict[str, Any]:
    """校准消息评分的阈值

    支持的方法：
    - kmeans_1d: 使用 1D K-means
    - jenks_1d: 目前复用 kmeans_1d
    - reference_quantile_band: 使用当前批次分位数

    Args:
        values: 要校准的数值列表（message_quality_weight）
        method: 校准方法

    Returns:
        包含阈值和元数据的字典
    """
    if not values:
        return {
            "message_threshold_source": "distribution_calibrated",
            "threshold_method": method,
            "t_reject": 0.0,
            "t_pass": 0.0,
            "detail": {"fallback": "empty_values"},
        }

    if method in {"kmeans_1d", "jenks_1d"}:
        # jenks_1d 当前复用 kmeans_1d 实现，避免引入额外依赖（如 jenkspy）
        # method 名称会如实记录到 metadata，便于未来替换实现
        t_reject, t_pass, detail = kmeans_1d_thresholds(values, k=3)
        if method == "jenks_1d":
            detail = {**detail, "implemented_as": "kmeans_1d_emulation"}
    elif method == "reference_quantile_band":
        t_reject = nearest_rank_percentile(values, 0.33)
        t_pass = nearest_rank_percentile(values, 0.67)
        detail = {"quantiles": [0.33, 0.67]}
    else:
        raise ValueError(f"Unsupported threshold method: {method}")

    # 确保 t_reject <= t_pass
    if t_reject > t_pass:
        t_reject, t_pass = t_pass, t_reject
    return {
        "message_threshold_source": "distribution_calibrated",
        "threshold_method": method,
        "t_reject": round(float(t_reject), 6),
        "t_pass": round(float(t_pass), 6),
        "detail": detail,
    }


def assign_message_status_and_weight(
    samples: list[dict[str, Any]],
    threshold_payload: dict[str, Any],
) -> None:
    """为每个样本分配消息状态和计算最终权重

    状态判定规则：
    - precheck skip → not_generated_precheck_skip
    - generation/judge/scoring 失败 → not_generated_generation_failed / not_scored
    - hard_fail（格式错误或 BERTScore 无效）→ reject，weight=0
    - weight >= t_pass → pass
    - t_reject <= weight < t_pass → fallback
    - weight < t_reject → reject

    当分布退化时（t_reject == t_pass），只有严格大于 t_pass 才判为 pass。

    Args:
        samples: 样本列表（会被修改）
        threshold_payload: 阈值信息
    """
    t_reject = threshold_payload["t_reject"]
    t_pass = threshold_payload["t_pass"]
    # 检查分布是否退化（两个阈值几乎相同）
    degenerate = abs(float(t_pass) - float(t_reject)) < 1e-12
    for row in samples:
        scores = row["message_scores"]
        generation_status = safe_strip(row.get("generation_status"))
        if generation_status == "not_attempted_precheck_skip":
            row["message_status"] = "not_generated_precheck_skip"
            row["message_scores"]["message_quality_weight"] = 0.0
            row["final_sample_weight"] = 0.0
            continue
        if generation_status == "generation_failed":
            row["message_status"] = "not_generated_generation_failed"
            row["message_scores"]["message_quality_weight"] = 0.0
            row["final_sample_weight"] = 0.0
            continue
        if generation_status in {"judge_failed", "scoring_failed"}:
            row["message_status"] = "not_scored"
            row["message_scores"]["message_quality_weight"] = 0.0
            row["final_sample_weight"] = 0.0
            continue
        generation_success = bool(row.get("message_meta", {}).get("generation_success", True))
        if not generation_success:
            row["message_status"] = "not_generated_generation_failed"
            row["message_scores"]["message_quality_weight"] = 0.0
            row["final_sample_weight"] = 0.0
            continue
        hard_fail = (
            scores["format"] == 0
            or scores["bertscore_compute_invalid"] == 1
        )
        weight = float(scores["message_quality_weight"])
        if hard_fail:
            status = "reject"
            weight = 0.0
        else:
            if degenerate:
                # 分布完全退化时，不把边界值直接判成 pass，避免"全样本 pass"。
                if weight > t_pass:
                    status = "pass"
                elif weight == t_pass:
                    status = "fallback"
                else:
                    status = "reject"
            else:
                if weight >= t_pass:
                    status = "pass"
                elif weight >= t_reject:
                    status = "fallback"
                else:
                    status = "reject"
        row["message_status"] = status
        row["message_scores"]["message_quality_weight"] = round(weight, 6)
        pair_quality_weight = float(row.get("pair_quality_weight", 1.0))
        rho = row.get("rho")
        if rho is None:
            rho_value = 1.0
        else:
            try:
                rho_value = float(rho)
            except Exception:
                rho_value = 1.0
        # 最终样本权重 = 样本置信度 * pair_quality_weight * rho * 消息质量权重
        row["final_sample_weight"] = round(float(row["sample_confidence"]) * pair_quality_weight * rho_value * weight, 6)


# ============================================================
# 消息模式检测和指标计算
# ============================================================

def detect_message_pattern_flags(subject: str) -> dict[str, int]:
    """检测生成消息中的不良模式

    检测项：
    - label_template_hit: 是否使用 "Change 1" 等标签模板
    - mechanical_semicolon: 是否使用分号机械拼接
    - dual_prefix: 是否使用两个常规前缀（如 "feat: ... fix: ..."）
    - bullet_hit / numbered_list_hit: 是否出现列表痕迹
    - and_used: 是否使用了 "and" 连接词
    - artifact_hit_count: 伪迹命中总数

    Returns:
        包含各模式命中标志的字典（0/1 值）
    """
    text = subject.strip()
    if not text:
        return {
            "label_template_hit": 0,
            "mechanical_semicolon": 0,
            "dual_prefix": 0,
            "bullet_hit": 0,
            "numbered_list_hit": 0,
            "and_used": 0,
            "artifact_hit_count": 0,
        }

    prefixes = PREFIX_RE.findall(text)
    flags = {
        "label_template_hit": int(bool(LABEL_TEMPLATE_RE.search(text))),
        "mechanical_semicolon": int(";" in text),
        "dual_prefix": int(len(prefixes) >= 2),
        "bullet_hit": int(bool(BULLET_LINE_RE.search(text))),
        "numbered_list_hit": int(bool(NUMBERED_LINE_RE.search(text))),
        "and_used": int(bool(AND_RE.search(text))),
    }
    flags["artifact_hit_count"] = (
        flags["label_template_hit"]
        + flags["mechanical_semicolon"]
        + flags["dual_prefix"]
        + flags["bullet_hit"]
        + flags["numbered_list_hit"]
    )
    # artifact_hit_count: 伪迹命中总数，用于计算 artifact_score = 1/(1+count)
    # 仅作监控，不参与硬拒绝；但 format 检查中这些项会导致 format=0
    return flags


def is_step3_ready_sample(row: dict[str, Any]) -> bool:
    """判定样本是否可进入 Step3-ready 产物。"""
    subject = safe_strip(row.get("synthetic_subject", ""))
    try:
        final_weight = float(row.get("final_sample_weight", 0.0))
    except Exception:
        final_weight = 0.0
    return bool(
        safe_strip(row.get("generation_status", "")) == "generated"
        and row.get("message_status") in {"pass", "fallback"}
        and row.get("precheck_status") in {"pass", "warn"}
        and bool(subject)
        and final_weight > 0.0
    )


def summarize_subject_distribution(subjects: list[str]) -> dict[str, Any]:
    """统计 subject 的分布特征（用于 synthetic vs real 对比）。"""
    features = [subject_surface_features(subject) for subject in subjects]
    total = len(features)
    token_counts = [int(item["token_count"]) for item in features]
    if not total:
        return {
            "count": 0,
            "avg_token_count": 0.0,
            "p50_token_count": 0,
            "p90_token_count": 0,
            "and_rate": 0.0,
            "comma_rate": 0.0,
            "prefix_rate": 0.0,
            "issue_id_rate": 0.0,
            "single_sentence_rate": 0.0,
            "imperative_head_rate": 0.0,
            "generic_phrase_rate": 0.0,
        }

    def avg_rate(key: str) -> float:
        return float(sum(int(item[key]) for item in features) / total)

    return {
        "count": total,
        "avg_token_count": round(sum(token_counts) / total, 6),
        "p50_token_count": int(nearest_rank_percentile(token_counts, 0.5)),
        "p90_token_count": int(nearest_rank_percentile(token_counts, 0.9)),
        "and_rate": round(avg_rate("and_used"), 6),
        "comma_rate": round(avg_rate("comma_used"), 6),
        "prefix_rate": round(avg_rate("prefix_used"), 6),
        "issue_id_rate": round(avg_rate("issue_id_present"), 6),
        "single_sentence_rate": round(avg_rate("single_sentence"), 6),
        "imperative_head_rate": round(avg_rate("imperative_head"), 6),
        "generic_phrase_rate": round(avg_rate("generic_phrase_hit"), 6),
    }


def compute_message_metrics(
    samples: list[dict[str, Any]],
    real_subject_distribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """计算消息阶段的总体指标，区分基础设施失败与真实质量失败。

    核心指标分组：
    - Precheck 指标：pass/warn/skip 分布、跳过原因、LLM 调用节省数
    - Generation 指标：尝试数、成功数、失败数、失败原因分布
    - 质量指标（仅针对 generated+scored 样本）：
      - pass/fallback/reject 分布和比率
      - avg_coverage、avg_faithfulness、avg_style、avg_relevance
      - format_fail_rate、bertscore_compute_invalid_rate
    - Few-shot 指标：failed_rate、generic_rate、type_matched_rate
    - 伪迹指标：label_template、mechanical_semicolon、dual_prefix 等命中率
    - 分布真实性：synthetic vs real subject 的 token_count、and_rate 等对比
    - Step3 就绪数：满足 pass/fallback + precheck 通过 + 有 subject + weight>0 的样本数
    """
    total = len(samples)
    status_counter = Counter(row.get("message_status", "reject") for row in samples)
    precheck_counter = Counter(row.get("precheck_status", "pass") for row in samples)
    precheck_skip_reason_counter: Counter[str] = Counter(
        safe_strip(row.get("precheck_skip_reason"))
        for row in samples
        if safe_strip(row.get("precheck_skip_reason"))
    )
    precheck_warning_reason_counter: Counter[str] = Counter()
    for row in samples:
        for reason in row.get("precheck_warning_reasons", []) or []:
            reason_text = safe_strip(reason)
            if reason_text:
                precheck_warning_reason_counter[reason_text] += 1

    meta_list = [row.get("message_meta", {}) for row in samples]
    generation_status_counter = Counter(safe_strip(row.get("generation_status", "")) for row in samples)
    generation_precheck_skip_count = generation_status_counter.get("not_attempted_precheck_skip", 0)
    generation_eval_total = total - generation_precheck_skip_count
    llm_calls_saved_by_precheck = precheck_counter.get("skip", 0)
    attempted_rows = [row for row in samples if bool(row.get("message_meta", {}).get("llm_generation_attempted", False))]
    generation_attempted_count = len(attempted_rows)
    generation_success_count = generation_status_counter.get("generated", 0)
    generation_failure_count = sum(
        1
        for row in attempted_rows
        if safe_strip(row.get("generation_status")) == "generation_failed"
    )
    judge_failure_count = generation_status_counter.get("judge_failed", 0)
    scoring_failure_count = generation_status_counter.get("scoring_failed", 0)
    generated_or_judged_count = generation_success_count + judge_failure_count

    generated_scored_rows = [
        row for row in samples
        if safe_strip(row.get("generation_status")) == "generated"
        and row.get("message_status") in {"pass", "fallback", "reject"}
    ]
    generated_scored_count = len(generated_scored_rows)
    passed = sum(1 for row in generated_scored_rows if row.get("message_status") == "pass")
    fallback = sum(1 for row in generated_scored_rows if row.get("message_status") == "fallback")
    true_reject_count = sum(1 for row in generated_scored_rows if row.get("message_status") == "reject")
    non_reject_rows = [row for row in generated_scored_rows if row.get("message_status") in {"pass", "fallback"}]

    non_skipped_rows = [row for row in samples if row.get("precheck_status") != "skip"]
    non_skipped_count = len(non_skipped_rows)
    fewshot_source_dist = Counter(row.get("few_shot_source", "none") for row in non_skipped_rows)
    fewshot_failed_count = fewshot_source_dist.get("failed", 0)
    fewshot_generic_count = fewshot_source_dist.get("generic_fallback", 0)
    fewshot_fallback_count = sum(
        fewshot_source_dist.get(label, 0)
        for label in {"type_overlap", "pairwise_overlap", "single_type_overlap", "generic_fallback"}
    )
    fewshot_type_matched_count = fewshot_source_dist.get("exact_kway", 0)

    failure_reason_counter = Counter(
        safe_strip(meta.get("generation_failure_reason"))
        for meta in meta_list
        if safe_strip(meta.get("generation_failure_reason"))
    )
    avg_generation_attempts = (
        sum(int(meta.get("generation_attempts", 0)) for meta in meta_list if not bool(meta.get("generation_skipped", False)))
        / generation_eval_total
        if generation_eval_total
        else 0.0
    )
    avg_compress_attempts = (
        sum(int(meta.get("compress_attempts", 0)) for meta in meta_list if not bool(meta.get("generation_skipped", False)))
        / generation_eval_total
        if generation_eval_total
        else 0.0
    )
    avg_rewrite_attempts = (
        sum(int(meta.get("rewrite_attempts", 0)) for meta in meta_list if not bool(meta.get("generation_skipped", False)))
        / generation_eval_total
        if generation_eval_total
        else 0.0
    )
    retry_heavy_count = sum(
        1
        for meta in meta_list
        if (not bool(meta.get("generation_skipped", False)))
        and (int(meta.get("generation_attempts", 0)) + int(meta.get("compress_attempts", 0)) + int(meta.get("rewrite_attempts", 0)) > 1)
    )

    format_fails = sum(1 for row in generated_scored_rows if row["message_scores"]["format"] == 0)
    bert_invalid = sum(1 for row in generated_scored_rows if row["message_scores"]["bertscore_compute_invalid"] == 1)
    avg_cov_non_reject = (
        sum(row["message_scores"]["coverage_min_r"] for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_cov_balance_non_reject = (
        sum(float(row["message_scores"].get("coverage_balance", 0.0)) for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_faith_non_reject = (
        sum(row["message_scores"]["faithfulness_p"] for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_style_non_reject = (
        sum(float(row["message_scores"].get("style_score", 0.0)) for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_relevance_non_reject = (
        sum(float(row["message_scores"].get("relevance_score", 0.0)) for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_message_quality_weight_non_reject = (
        sum(float(row["message_scores"].get("message_quality_weight", 0.0)) for row in non_reject_rows) / len(non_reject_rows)
        if non_reject_rows
        else 0.0
    )
    avg_weight = (
        sum(float(row["message_scores"].get("message_quality_weight", 0.0)) for row in generated_scored_rows) / generated_scored_count
        if generated_scored_count
        else 0.0
    )

    coverage_min_values = [
        float(row.get("message_scores", {}).get("coverage_min_r", 0.0))
        for row in generated_scored_rows
        if row.get("message_scores", {}).get("format", 0) == 1
    ]
    pattern_flags = [detect_message_pattern_flags(row.get("synthetic_subject", "")) for row in generated_scored_rows]
    label_template_hits = sum(flag["label_template_hit"] for flag in pattern_flags)
    mechanical_semicolon_hits = sum(flag["mechanical_semicolon"] for flag in pattern_flags)
    dual_prefix_hits = sum(flag["dual_prefix"] for flag in pattern_flags)
    bullet_hits = sum(flag["bullet_hit"] for flag in pattern_flags)
    numbered_list_hits = sum(flag["numbered_list_hit"] for flag in pattern_flags)
    and_used_hits = sum(flag["and_used"] for flag in pattern_flags)
    artifact_hit_positive = sum(1 for flag in pattern_flags if int(flag["artifact_hit_count"]) > 0)
    artifact_avg_hits = (
        sum(int(flag["artifact_hit_count"]) for flag in pattern_flags) / generated_scored_count
        if generated_scored_count
        else 0.0
    )

    synthetic_subjects = [safe_strip(row.get("synthetic_subject", "")) for row in generated_scored_rows if safe_strip(row.get("synthetic_subject", ""))]
    synthetic_distribution = summarize_subject_distribution(synthetic_subjects)
    distribution_delta: dict[str, Any] = {}
    if isinstance(real_subject_distribution, dict) and real_subject_distribution:
        comparable_keys = [
            "avg_token_count",
            "p90_token_count",
            "and_rate",
            "comma_rate",
            "prefix_rate",
            "issue_id_rate",
            "single_sentence_rate",
            "imperative_head_rate",
            "generic_phrase_rate",
        ]
        for key in comparable_keys:
            if key in real_subject_distribution and key in synthetic_distribution:
                distribution_delta[f"{key}_delta"] = round(
                    float(synthetic_distribution[key]) - float(real_subject_distribution[key]),
                    6,
                )

    pair_weight_non_skipped = [
        float(row.get("pair_quality_weight", 0.0))
        for row in samples
        if row.get("precheck_status") != "skip"
    ]
    step3_ready_count = sum(1 for row in samples if is_step3_ready_sample(row))

    generation_failure_rate_attempted = (
        float(generation_failure_count / generation_attempted_count)
        if generation_attempted_count
        else 0.0
    )
    judge_failure_rate_generated_or_judged = (
        float(judge_failure_count / generated_or_judged_count)
        if generated_or_judged_count
        else 0.0
    )
    true_reject_rate = (
        float(true_reject_count / generated_scored_count)
        if generated_scored_count
        else 0.0
    )
    message_pass_rate = (
        float(passed / generated_scored_count)
        if generated_scored_count
        else 0.0
    )
    message_fallback_rate = (
        float(fallback / generated_scored_count)
        if generated_scored_count
        else 0.0
    )
    fewshot_failed_rate = (
        float(fewshot_failed_count / non_skipped_count)
        if non_skipped_count
        else 0.0
    )
    fewshot_generic_rate = (
        float(fewshot_generic_count / non_skipped_count)
        if non_skipped_count
        else 0.0
    )
    fewshot_fallback_rate = (
        float(fewshot_fallback_count / non_skipped_count)
        if non_skipped_count
        else 0.0
    )

    return {
        "precheck_pass_count": precheck_counter.get("pass", 0),
        "precheck_warn_count": precheck_counter.get("warn", 0),
        "precheck_skip_count": precheck_counter.get("skip", 0),
        "precheck_skip_reason_counts": dict(precheck_skip_reason_counter.most_common()),
        "precheck_warning_reason_counts": dict(precheck_warning_reason_counter.most_common()),
        "avg_pair_quality_weight_non_skipped": round(
            sum(pair_weight_non_skipped) / len(pair_weight_non_skipped), 6
        ) if pair_weight_non_skipped else 0.0,
        "llm_calls_saved_by_precheck": int(llm_calls_saved_by_precheck),
        "sampled_candidate_count": total,
        "precheck_skip_rate": round(precheck_counter.get("skip", 0) / total, 6) if total else 0.0,
        "generation_attempted_count": int(generation_attempted_count),
        "generation_eval_total": int(generation_eval_total),
        "generation_success_count": int(generation_success_count),
        "generation_failed_count": int(generation_failure_count),
        "generation_failure_count": int(generation_failure_count),
        "generation_failure_rate_attempted": round(generation_failure_rate_attempted, 6),
        "judge_failure_count": int(judge_failure_count),
        "judge_failure_rate_generated_or_judged": round(judge_failure_rate_generated_or_judged, 6),
        "scoring_failure_count": int(scoring_failure_count),
        "generated_scored_count": int(generated_scored_count),
        "true_message_reject_count": int(true_reject_count),
        "true_message_reject_rate": round(true_reject_rate, 6),
        "message_pass_count": int(passed),
        "message_fallback_count": int(fallback),
        "message_reject_count": int(true_reject_count),
        "message_not_generated_precheck_skip_count": status_counter.get("not_generated_precheck_skip", 0),
        "message_not_generated_generation_failed_count": status_counter.get("not_generated_generation_failed", 0),
        "message_not_scored_count": status_counter.get("not_scored", 0),
        "message_pass_rate": round(message_pass_rate, 6),
        "message_fallback_rate": round(message_fallback_rate, 6),
        "fallback_rate": round(message_fallback_rate, 6),
        "message_reject_rate": round(true_reject_rate, 6),
        "format_fail_rate": round(format_fails / generated_scored_count, 6) if generated_scored_count else 0.0,
        "bertscore_compute_invalid_rate": round(bert_invalid / generated_scored_count, 6) if generated_scored_count else 0.0,
        "avg_message_quality_weight": round(avg_weight, 6),
        "avg_message_quality_weight_non_reject": round(avg_message_quality_weight_non_reject, 6),
        "avg_coverage_non_reject": round(avg_cov_non_reject, 6),
        "avg_coverage_balance_non_reject": round(avg_cov_balance_non_reject, 6),
        "avg_faithfulness_non_reject": round(avg_faith_non_reject, 6),
        "avg_style_non_reject": round(avg_style_non_reject, 6),
        "avg_relevance_non_reject": round(avg_relevance_non_reject, 6),
        "few_shot_source_distribution": dict(fewshot_source_dist),
        "few_shot_requested_k": int(max((int(row.get("message_meta", {}).get("retrieval_params", {}).get("k", 0) or 0) for row in samples), default=0)),
        "few_shot_type_matched_rate": round(fewshot_type_matched_count / non_skipped_count, 6) if non_skipped_count else 0.0,
        "few_shot_failed_count": int(fewshot_failed_count),
        "few_shot_failed_rate": round(fewshot_failed_rate, 6),
        "few_shot_failure_rate": round(fewshot_failed_rate, 6),
        "few_shot_generic_count": int(fewshot_generic_count),
        "few_shot_generic_rate": round(fewshot_generic_rate, 6),
        "few_shot_fallback_count": int(fewshot_fallback_count),
        "few_shot_fallback_rate": round(fewshot_fallback_rate, 6),
        "llm_generation_attempted_count": int(generation_attempted_count),
        "llm_generation_skipped_by_precheck_count": int(llm_calls_saved_by_precheck),
        "generation_failed_rate": round(generation_failure_rate_attempted, 6),
        "generation_retry_heavy_count": retry_heavy_count,
        "generation_retry_heavy_rate": round(retry_heavy_count / generation_eval_total, 6) if generation_eval_total else 0.0,
        "avg_generation_attempts": round(avg_generation_attempts, 6),
        "avg_compress_attempts": round(avg_compress_attempts, 6),
        "avg_rewrite_attempts": round(avg_rewrite_attempts, 6),
        "generation_failure_reason_distribution": dict(failure_reason_counter.most_common()),
        "coverage_min_avg": round(sum(coverage_min_values) / len(coverage_min_values), 6) if coverage_min_values else 0.0,
        "coverage_min_p10": round(nearest_rank_percentile(coverage_min_values, 0.1), 6) if coverage_min_values else 0.0,
        "label_template_hit_rate": round(label_template_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "mechanical_semicolon_rate": round(mechanical_semicolon_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "dual_prefix_rate": round(dual_prefix_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "bullet_hit_rate": round(bullet_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "numbered_list_hit_rate": round(numbered_list_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "and_usage_rate": round(and_used_hits / generated_scored_count, 6) if generated_scored_count else 0.0,
        "artifact_any_hit_rate": round(artifact_hit_positive / generated_scored_count, 6) if generated_scored_count else 0.0,
        "artifact_avg_hit_count": round(artifact_avg_hits, 6),
        "synthetic_subject_distribution": synthetic_distribution,
        "real_subject_distribution_anchor": real_subject_distribution or {},
        "distribution_delta_vs_real_anchor": distribution_delta,
        "step3_ready_count": int(step3_ready_count),
        "final_usable_sample_count": int(step3_ready_count),
    }


def load_message_gate_reference(path: str) -> list[dict[str, Any]]:
    """加载 Message Gate 参考文件（JSON 或 JSONL 格式）。

    参考文件包含历史运行的指标数据，用于分布校准。
    支持的格式：
    - JSONL: 每行一个 JSON 对象
    - JSON 数组: 直接返回
    - JSON 对象: 从 runs 字段提取或包装为单元素列表
    """
    if not path:
        return []
    ref_path = Path(path)
    if ref_path.suffix.lower() == ".jsonl":
        rows = []
        with ref_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows

    payload = json.loads(ref_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("runs"), list):
            return payload["runs"]
        return [payload]
    return []


def extract_ref_metric(rows: list[dict[str, Any]], key: str) -> list[float]:
    """从参考运行记录中提取指定指标的值列表。

    支持从嵌套结构中查找指标：直接顶层、message_metrics 子对象、
    message_gate_metrics 子对象。用于 Message Gate 的可选 reference band 对照。

    Args:
        rows: 参考运行记录列表
        key: 指标键名

    Returns:
        提取到的浮点数值列表
    """
    values: list[float] = []
    for row in rows:
        if key in row:
            values.append(float(row[key]))
            continue
        if isinstance(row.get("message_metrics"), dict) and key in row["message_metrics"]:
            values.append(float(row["message_metrics"][key]))
            continue
        if isinstance(row.get("message_gate_metrics"), dict) and key in row["message_gate_metrics"]:
            values.append(float(row["message_gate_metrics"][key]))
            continue
    return values


def evaluate_message_gate(
    current_metrics: dict[str, Any],
    reference_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """评估 Message Gate：检查各项指标是否满足 formal 运行的质量门槛。

    检查项包括：
    - message_pass_rate >= gate_min_message_pass_rate
    - true_message_reject_rate <= gate_max_message_reject_rate
    - avg_message_quality_weight_non_reject >= gate_min_avg_message_quality_weight_non_reject
    - few_shot_failed_rate <= gate_max_fewshot_failure_rate
    - precheck_skip_rate <= gate_max_precheck_skip_rate
    - generation_failure_rate_attempted <= gate_max_generation_failure_rate
    - coverage_min_avg >= gate_min_coverage_min_avg
    - coverage_min_p10 >= gate_min_coverage_min_p10
    - 可选的 external reference band 对照（由 message_gate_reference 提供）

    所有检查项通过时返回 message_gate_passed=True。
    """
    if not args.enable_message_gate:
        return {
            "message_gate_enabled": False,
            "message_gate_passed": True,
            "message_gate_source": "disabled",
            "reason": "message_gate_disabled",
            "gate_metrics": {},
            "gate_metric_denominators": {},
            "gate_checks": [],
            "warnings": [],
        }

    few_shot_failed_rate_gate_threshold = float(
        getattr(args, "few_shot_failed_rate_gate_threshold", args.gate_max_fewshot_failure_rate)
    )
    few_shot_generic_rate_warn_threshold = float(
        getattr(args, "few_shot_generic_rate_warn_threshold", DEFAULT_FEWSHOT_GENERIC_RATE_WARN_THRESHOLD)
    )
    gate_metrics = {
        "message_pass_rate": float(current_metrics.get("message_pass_rate", 0.0)),
        "true_message_reject_rate": float(current_metrics.get("true_message_reject_rate", 0.0)),
        "avg_message_quality_weight_non_reject": float(
            current_metrics.get("avg_message_quality_weight_non_reject", 0.0)
        ),
        "few_shot_failed_rate": float(current_metrics.get("few_shot_failed_rate", 0.0)),
        "few_shot_generic_rate": float(current_metrics.get("few_shot_generic_rate", 0.0)),
        "precheck_skip_rate": float(current_metrics.get("precheck_skip_rate", 0.0)),
        "generation_failure_rate_attempted": float(current_metrics.get("generation_failure_rate_attempted", 0.0)),
        "coverage_min_avg": float(current_metrics.get("coverage_min_avg", 0.0)),
        "coverage_min_p10": float(current_metrics.get("coverage_min_p10", 0.0)),
    }
    gate_metric_denominators = {
        "sampled_candidate_count": int(current_metrics.get("sampled_candidate_count", 0)),
        "generated_scored_count": int(current_metrics.get("generated_scored_count", 0)),
        "generation_attempted_count": int(current_metrics.get("generation_attempted_count", 0)),
        "non_precheck_skipped_count": int(
            int(current_metrics.get("sampled_candidate_count", 0))
            - int(current_metrics.get("precheck_skip_count", 0))
        ),
    }
    gate_checks = [
        {
            "metric": "message_pass_rate",
            "category": "quality",
            "comparison": ">=",
            "threshold": float(args.gate_min_message_pass_rate),
            "actual": gate_metrics["message_pass_rate"],
            "passed": gate_metrics["message_pass_rate"] >= float(args.gate_min_message_pass_rate),
        },
        {
            "metric": "true_message_reject_rate",
            "category": "quality",
            "comparison": "<=",
            "threshold": float(args.gate_max_message_reject_rate),
            "actual": gate_metrics["true_message_reject_rate"],
            "passed": gate_metrics["true_message_reject_rate"] <= float(args.gate_max_message_reject_rate),
        },
        {
            "metric": "avg_message_quality_weight_non_reject",
            "category": "quality",
            "comparison": ">=",
            "threshold": float(args.gate_min_avg_message_quality_weight_non_reject),
            "actual": gate_metrics["avg_message_quality_weight_non_reject"],
            "passed": gate_metrics["avg_message_quality_weight_non_reject"]
            >= float(args.gate_min_avg_message_quality_weight_non_reject),
        },
        {
            "metric": "few_shot_failed_rate",
            "category": "fewshot",
            "comparison": "<=",
            "threshold": few_shot_failed_rate_gate_threshold,
            "actual": gate_metrics["few_shot_failed_rate"],
            "passed": gate_metrics["few_shot_failed_rate"] <= few_shot_failed_rate_gate_threshold,
        },
        {
            "metric": "precheck_skip_rate",
            "category": "precheck",
            "comparison": "<=",
            "threshold": float(args.gate_max_precheck_skip_rate),
            "actual": gate_metrics["precheck_skip_rate"],
            "passed": gate_metrics["precheck_skip_rate"] <= float(args.gate_max_precheck_skip_rate),
        },
        {
            "metric": "generation_failure_rate_attempted",
            "category": "infrastructure",
            "comparison": "<=",
            "threshold": float(args.gate_max_generation_failure_rate),
            "actual": gate_metrics["generation_failure_rate_attempted"],
            "passed": gate_metrics["generation_failure_rate_attempted"] <= float(args.gate_max_generation_failure_rate),
        },
        {
            "metric": "coverage_min_avg",
            "category": "quality",
            "comparison": ">=",
            "threshold": float(args.gate_min_coverage_min_avg),
            "actual": gate_metrics["coverage_min_avg"],
            "passed": gate_metrics["coverage_min_avg"] >= float(args.gate_min_coverage_min_avg),
        },
        {
            "metric": "coverage_min_p10",
            "category": "quality",
            "comparison": ">=",
            "threshold": float(args.gate_min_coverage_min_p10),
            "actual": gate_metrics["coverage_min_p10"],
            "passed": gate_metrics["coverage_min_p10"] >= float(args.gate_min_coverage_min_p10),
        },
    ]

    reference_gate: dict[str, Any] = {
        "enabled": False,
        "passed": True,
        "reference_count": len(reference_rows),
        "reject_rate_upper": None,
        "coverage_lower": None,
        "reason": "not_used",
    }
    if reference_rows:
        reject_values = extract_ref_metric(reference_rows, "true_message_reject_rate")
        if not reject_values:
            reject_values = extract_ref_metric(reference_rows, "message_reject_rate")
        coverage_values = extract_ref_metric(reference_rows, "avg_coverage_non_reject")
        if reject_values and coverage_values:
            reject_upper = nearest_rank_percentile(reject_values, args.reference_upper_quantile)
            coverage_lower = nearest_rank_percentile(coverage_values, args.reference_lower_quantile)
            reference_passed = (
                gate_metrics["true_message_reject_rate"] <= reject_upper
                and float(current_metrics.get("avg_coverage_non_reject", 0.0)) >= coverage_lower
            )
            reference_gate = {
                "enabled": True,
                "passed": bool(reference_passed),
                "reference_count": len(reference_rows),
                "reject_rate_upper": round(float(reject_upper), 6),
                "coverage_lower": round(float(coverage_lower), 6),
                "reason": "ok" if reference_passed else "out_of_control_band",
            }
            gate_checks.append(
                {
                    "metric": "reference_quantile_band",
                    "comparison": "band",
                    "threshold": {
                        "reject_rate_upper": round(float(reject_upper), 6),
                        "coverage_lower": round(float(coverage_lower), 6),
                    },
                    "actual": {
                        "true_message_reject_rate": gate_metrics["true_message_reject_rate"],
                        "avg_coverage_non_reject": float(current_metrics.get("avg_coverage_non_reject", 0.0)),
                    },
                    "passed": bool(reference_passed),
                }
            )
        else:
            reference_gate = {
                "enabled": True,
                "passed": False,
                "reference_count": len(reference_rows),
                "reject_rate_upper": None,
                "coverage_lower": None,
                "reason": "reference_missing_required_metrics",
            }
            gate_checks.append(
                {
                    "metric": "reference_quantile_band",
                    "comparison": "band",
                    "threshold": None,
                    "actual": None,
                    "passed": False,
                }
            )

    passed = all(bool(item["passed"]) for item in gate_checks)
    failed_metrics = [item["metric"] for item in gate_checks if not bool(item["passed"])]
    warnings: list[dict[str, Any]] = []
    if gate_metrics["few_shot_generic_rate"] > few_shot_generic_rate_warn_threshold:
        warnings.append(
            {
                "metric": "few_shot_generic_rate",
                "threshold": few_shot_generic_rate_warn_threshold,
                "actual": gate_metrics["few_shot_generic_rate"],
                "severity": "warn",
                "reason": "generic_fallback_over_warn_threshold",
            }
        )
    reason = "ok"
    if not passed:
        reason = "threshold_failure"
    elif warnings:
        reason = "ok_with_warnings"
    return {
        "message_gate_enabled": True,
        "message_gate_passed": bool(passed),
        "message_gate_source": "formal_thresholds_with_optional_reference",
        "reason": reason,
        "gate_metrics": gate_metrics,
        "gate_metric_denominators": gate_metric_denominators,
        "gate_checks": gate_checks,
        "failed_metrics": failed_metrics,
        "warnings": warnings,
        "reference_gate": reference_gate,
    }


def check_scoring_backend_readiness(args: argparse.Namespace) -> dict[str, Any]:
    """检查当前配置的评分后端（scorer backend）的依赖是否可用。

    目前仅支持 bertscore_only_v1，需要 bert-score 包可导入。
    用于 preflight 预检和运行前的依赖验证。
    """
    if args.scorer_backend == "bertscore_only_v1":
        try:
            with temporary_env_overrides(bertscore_offline_env_overrides(args.bertscore_model)):
                from bert_score import BERTScorer as _  # noqa: F401
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            return {
                "passed": False,
                "scorer_backend": args.scorer_backend,
                "detail": str(exc),
                "guidance": "Coverage scoring dependency missing. Install `bert-score` or configure a supported scorer backend.",
            }
        return {
            "passed": True,
            "scorer_backend": args.scorer_backend,
            "detail": "bert-score importable",
            "guidance": "",
        }
    return {
        "passed": False,
        "scorer_backend": args.scorer_backend,
        "detail": "unsupported_scorer_backend",
        "guidance": f"Unsupported scorer backend: {args.scorer_backend}",
    }


def run_generator_preflight_ping(args: argparse.Namespace) -> dict[str, Any]:
    """执行一次可选的最小 API ping，验证远程 API 可达性。

    发送 "Return exactly: ok" 请求，不使用缓存。
    仅在 --preflight-api-ping 时调用。
    """
    response = deepseek_generate(
        prompt="Return exactly: ok",
        args=args,
        generation_cache={},
        cache_enabled=False,
        extra_tag="preflight_api_ping",
    )
    return {
        "ok": bool(response["ok"]),
        "error_type": response.get("error_type", ""),
        "error_guidance": (
            provider_error_guidance(response.get("error_type", ""))
            if is_run_blocking_provider_error(response.get("error_type", ""))
            else ""
        ),
        "raw_response_preview": short_text_preview(response.get("raw_response")),
    }


def build_stable_preflight_wrapper(
    *,
    report: dict[str, Any],
    summary_lines: list[str],
    passed: bool,
) -> dict[str, Any]:
    return {
        "attempted": True,
        "passed": bool(passed),
        "reason": "",
        "report_path": report.get("report_path", ""),
        "stdout": "\n".join(summary_lines) + "\n",
        "stderr": "",
        "returncode": 0 if passed else 1,
        "command": [sys.executable, *sys.argv],
        "report": report,
    }


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """执行 formal Step2 运行环境的预检（preflight），不执行真正的样本生成。

    检查项包括：
    1. output: 输出目录是否可写
    2. generator: API key 是否配置、模型是否指定、可选 API ping
    3. scoring: BERTScore 依赖是否可用
    4. input_data: 源 CSV 是否存在且有足够的 A-tier 行
    5. fewshot: few-shot pool 是否可解析、检索探针是否成功、formal-ready 审计
    6. formal_assets: source manifest / few-shot build manifest 是否齐备并可审计

    所有检查通过时返回 passed=True，否则 passed=False 并输出详细报告。
    """
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    report_dir = Path(args.output_dir) / f"preflight_{timestamp}"
    report_path = report_dir / "preflight_report.json"
    stable_report_path = Path(args.output_dir) / "preflight_report.json"
    checks: dict[str, Any] = {}
    preflight_target_run_purpose = infer_preflight_target_run_purpose(args)
    formal_fewshot_required = preflight_target_run_purpose == "formal"

    output_check = {"passed": True, "report_dir": repo_rel(report_dir), "detail": ""}
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        output_check = {"passed": False, "report_dir": repo_rel(report_dir), "detail": str(exc)}
    checks["output"] = output_check

    api_key = safe_strip(getattr(args, "_resolved_deepseek_api_key", ""))
    if getattr(args, "generator_mode", "api") == "mock":
        generator_check = {
            "passed": False,
            "generator_mode": "mock",
            "detail": "Mock generator is debug-only and not valid for formal preflight.",
            "api_key_present": False,
            "api_ping": None,
        }
    else:
        generator_check = {
            "passed": bool(api_key and safe_strip(args.generator_model)),
            "generator_mode": getattr(args, "generator_mode", "api"),
            "generator_model": args.generator_model,
            "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
            "api_key_present": bool(api_key),
            "api_key_source": getattr(args, "_deepseek_api_key_source", "unknown"),
            "detail": "",
            "api_ping": None,
        }
        if not api_key:
            generator_check["detail"] = (
                "Formal message generation requires config.deepseek_api_key, --deepseek-api-key, "
                "or DEEPSEEK_API_KEY."
            )
        elif not safe_strip(args.generator_model):
            generator_check["detail"] = "Generator model is not configured."
        if args.preflight_api_ping and generator_check["passed"]:
            generator_check["api_ping"] = run_generator_preflight_ping(args)
            generator_check["passed"] = bool(generator_check["api_ping"]["ok"])
            if not generator_check["passed"]:
                ping_error_type = safe_strip((generator_check.get("api_ping") or {}).get("error_type"))
                guidance = safe_strip((generator_check.get("api_ping") or {}).get("error_guidance"))
                if ping_error_type:
                    generator_check["detail"] = f"Remote API ping failed: {ping_error_type}"
                    if guidance:
                        generator_check["detail"] += f" ({guidance})"
                else:
                    generator_check["detail"] = "Remote API ping failed."
    checks["generator"] = generator_check

    scoring_check = check_scoring_backend_readiness(args)
    checks["scoring"] = scoring_check

    source_path = Path(args.source_csv)
    input_check: dict[str, Any]
    if not source_path.exists() or not source_path.is_file():
        input_check = {
            "passed": False,
            "source_csv": repo_rel(source_path),
            "detail": f"Input source CSV not found at expected path: {source_path}",
        }
    else:
        try:
            source_rows = load_csv(source_path)
            pool, pool_stats = build_source_pool_from_minimal(source_rows, manual_label=args.manual_label)
            input_check = {
                "passed": len(pool) >= int(args.intent_k),
                "source_csv": repo_rel(source_path),
                "normalized_required_columns": sorted(REQUIRED_SOURCE_FIELDS),
                "a_tier_count": len(pool),
                "pool_stats": pool_stats,
                "detail": "" if len(pool) >= int(args.intent_k) else f"Not enough A-tier rows for intent_k={args.intent_k}",
            }
        except Exception as exc:
            input_check = {
                "passed": False,
                "source_csv": repo_rel(source_path),
                "detail": str(exc),
            }
    checks["input_data"] = input_check

    if output_check["passed"]:
        try:
            resolved_fewshot_db, resolution_meta = resolve_fewshot_pool_or_fail(args, report_dir)
            raw_rows = load_fewshot_pool_rows(str(resolved_fewshot_db), args.fewshot_table)
            rows, _ = filter_fewshot_pool_rows_for_retrieval(raw_rows)
            fewshot_audit = audit_fewshot_pool(
                raw_rows,
                min_total=int(getattr(args, "fewshot_min_total_examples", DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES)),
                min_per_common_signature=int(
                    getattr(
                        args,
                        "fewshot_min_examples_per_common_signature",
                        DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
                    )
                ),
                strict_style=bool(getattr(args, "fewshot_audit_strict_style", DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE)),
            )
            retrieval_probe = retrieve_fewshot_examples(
                db_path=str(resolved_fewshot_db),
                table=args.fewshot_table,
                type_signature_canonical="fix+test",
                current_repo="preflight/repo",
                k=1,
                seed=args.seed,
                current_source_shas=set(),
            )
            retrieval_probe_ok = bool(rows) and retrieval_probe["retrieval_result_count"] >= int(
                getattr(args, "few_shot_min_examples_per_sample", 1)
            )
            formal_ready = bool(fewshot_audit.get("audit_pass", False))
            passed = bool(retrieval_probe_ok and (formal_ready if formal_fewshot_required else True))
            detail = ""
            if not retrieval_probe_ok:
                detail = "Few-shot retrieval probe failed."
            elif formal_fewshot_required and not formal_ready:
                detail = (
                    "Default few-shot pool is pilot-sized and not formal-ready. "
                    "Provide --fewshot-db or build a verified few-shot pool. "
                    f"blockers={fewshot_audit.get('blockers', [])}"
                )
            fewshot_check = {
                "passed": passed,
                "resolved_db": repo_rel(resolved_fewshot_db),
                "resolution": relativize_repo_paths(resolution_meta),
                "example_count": len(rows),
                "raw_example_count": len(raw_rows),
                "retrieval_probe": retrieval_probe,
                "fewshot_pool_audit": fewshot_audit,
                "fewshot_pool_formal_ready": formal_ready,
                "fewshot_pool_total_examples": int(fewshot_audit.get("total_examples", 0)),
                "fewshot_pool_verified_examples": int(fewshot_audit.get("verified_examples", 0)),
                "common_signature_coverage": fewshot_audit.get("common_signature_coverage", {}),
                "bad_style_count": int(fewshot_audit.get("bad_style_count", 0)),
                "fewshot_eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
                "formal_required_for_target": bool(formal_fewshot_required),
                "target_run_purpose": preflight_target_run_purpose,
                "detail": detail,
            }
            formal_assets_check = collect_formal_asset_status(
                args,
                resolved_fewshot_db=resolved_fewshot_db,
                require_fewshot_build_manifest=formal_fewshot_required,
            )
            formal_assets_check = relativize_repo_paths(formal_assets_check)
            formal_assets_check["passed"] = bool(formal_assets_check.get("formal_assets_ready", False))
        except Exception as exc:
            fewshot_check = {
                "passed": False,
                "resolved_db": repo_rel(getattr(args, "fewshot_db", "")),
                "resolution": {},
                "example_count": 0,
                "retrieval_probe": {},
                "fewshot_pool_audit": {},
                "fewshot_pool_formal_ready": False,
                "fewshot_pool_total_examples": 0,
                "fewshot_pool_verified_examples": 0,
                "common_signature_coverage": {},
                "bad_style_count": 0,
                "fewshot_eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
                "formal_required_for_target": bool(formal_fewshot_required),
                "target_run_purpose": preflight_target_run_purpose,
                "detail": str(exc),
            }
            formal_assets_check = collect_formal_asset_status(
                args,
                resolved_fewshot_db=getattr(args, "fewshot_db", ""),
                require_fewshot_build_manifest=formal_fewshot_required,
            )
            formal_assets_check = relativize_repo_paths(formal_assets_check)
            formal_assets_check["passed"] = bool(formal_assets_check.get("formal_assets_ready", False))
    else:
        fewshot_check = {
            "passed": False,
            "resolved_db": repo_rel(getattr(args, "fewshot_db", "")),
            "resolution": {},
            "example_count": 0,
            "retrieval_probe": {},
            "fewshot_pool_audit": {},
            "fewshot_pool_formal_ready": False,
            "fewshot_pool_total_examples": 0,
            "fewshot_pool_verified_examples": 0,
            "common_signature_coverage": {},
            "bad_style_count": 0,
            "fewshot_eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
            "formal_required_for_target": bool(formal_fewshot_required),
            "target_run_purpose": preflight_target_run_purpose,
            "detail": "Output directory is not writable; skipped few-shot pool resolution.",
        }
        formal_assets_check = collect_formal_asset_status(
            args,
            resolved_fewshot_db=getattr(args, "fewshot_db", ""),
            require_fewshot_build_manifest=formal_fewshot_required,
        )
        formal_assets_check = relativize_repo_paths(formal_assets_check)
        formal_assets_check["passed"] = bool(formal_assets_check.get("formal_assets_ready", False))
    checks["fewshot"] = fewshot_check
    checks["formal_assets"] = formal_assets_check

    overall_passed = all(bool(section.get("passed", False)) for section in checks.values())
    report = {
        "formal_protocol_version": FORMAL_PROTOCOL_VERSION,
        "preflight_timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
        "passed": bool(overall_passed),
        "preflight_target_run_purpose": preflight_target_run_purpose,
        "report_dir": repo_rel(report_dir),
        "report_path": repo_rel(report_path),
        "diff_evidence": {
            "diff_evidence_card_version": DIFF_EVIDENCE_CARD_VERSION,
            "diff_evidence_policy": DIFF_EVIDENCE_POLICY,
            "diff_evidence_required_for_formal": bool(DIFF_EVIDENCE_REQUIRED_FOR_FORMAL),
        },
        "checks": checks,
    }
    report = relativize_repo_paths(report)
    if output_check["passed"]:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary_lines = [
        f"preflight_passed={int(bool(overall_passed))}",
        f"generator={int(bool(generator_check.get('passed', False)))}",
        f"fewshot={int(bool(fewshot_check.get('passed', False)))}",
        f"formal_assets={int(bool(formal_assets_check.get('passed', False)))}",
        f"scoring={int(bool(scoring_check.get('passed', False)))}",
        f"input_data={int(bool(input_check.get('passed', False)))}",
        f"output={int(bool(output_check.get('passed', False)))}",
        report["report_path"],
    ]
    if output_check["passed"]:
        stable_wrapper = build_stable_preflight_wrapper(
            report=report,
            summary_lines=summary_lines,
            passed=bool(overall_passed),
        )
        stable_report_path.write_text(json.dumps(stable_wrapper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for line in summary_lines:
        safe_print(line)
    return report


def write_message_gate_report(path: Path, payload: dict[str, Any]) -> None:
    """写出 formal message gate report JSON 文件。

    包含 gate 检查结果、各项指标、阈值、few-shot pool 审计信息等，
    供失败时审计和后续可选 gate reference 对照使用。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def persist_runtime_caches(
    args: argparse.Namespace,
    generation_cache: dict[str, Any],
    bertscore_cache: dict[str, Any],
) -> None:
    """在中途失败或正常收尾前统一落盘缓存。"""
    if args.generation_cache_enabled:
        save_cache(Path(args.generation_cache_path), generation_cache)
    if args.bertscore_cache_enabled:
        save_cache(Path(args.bertscore_cache_path), bertscore_cache)


# ============================================================
# 输出写入函数
# ============================================================

def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """将样本列表写入 JSONL 文件（每行一个 JSON 对象）。

    用于输出 synthetic_samples.jsonl、step3_ready.jsonl、precheck_rejected.jsonl。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    """写出 JSON 文件，统一处理父目录创建。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_partial_progress_artifacts(
    output_dir: Path,
    args: argparse.Namespace,
    samples: list[dict[str, Any]],
    *,
    processed_count: int,
    total_count: int,
    status: str,
    last_sample: dict[str, Any] | None = None,
    note: str = "",
    final_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """落盘运行中的中间产物，提升长分片运行的可观测性。"""
    processed_rows = list(samples[:processed_count])
    partial_samples_path = output_dir / "synthetic_samples.partial.jsonl"
    partial_precheck_path = output_dir / "synthetic_samples_precheck_rejected.partial.jsonl"
    partial_progress_path = output_dir / "run_progress.json"

    write_jsonl(partial_samples_path, processed_rows)
    write_jsonl(
        partial_precheck_path,
        [row for row in processed_rows if safe_strip(row.get("precheck_status", "")) == "skip"],
    )

    generation_status_counts = Counter(
        safe_strip(row.get("generation_status", "")) or "pending"
        for row in processed_rows
    )
    message_status_counts = Counter(
        safe_strip(row.get("message_status", "")) or "pending"
        for row in processed_rows
    )
    llm_attempted_count = sum(
        1
        for row in processed_rows
        if bool((row.get("message_meta") or {}).get("llm_generation_attempted", False))
    )
    generation_success_count = sum(
        1
        for row in processed_rows
        if bool((row.get("message_meta") or {}).get("generation_success", False))
    )
    progress_payload = {
        "status": status,
        "run_stage": "message_generation" if not bool(args.skip_message_stage) else "message_stage_skipped",
        "processed_count": int(processed_count),
        "total_count": int(total_count),
        "remaining_count": int(max(total_count - processed_count, 0)),
        "progress_ratio": round(processed_count / total_count, 6) if total_count else 1.0,
        "progress_flush_every": int(max(0, int(getattr(args, "progress_flush_every", 0)))),
        "note": note or (
            "Partial artifacts are observational only. Final thresholds and step3-ready outputs are stable only after shard completion."
        ),
        "counts": {
            "precheck_skip_count": int(
                sum(1 for row in processed_rows if safe_strip(row.get("precheck_status", "")) == "skip")
            ),
            "llm_attempted_count": int(llm_attempted_count),
            "generation_success_count": int(generation_success_count),
            "generation_failure_count": int(
                sum(
                    generation_status_counts.get(key, 0)
                    for key in ("generation_failed", "judge_failed", "scoring_failed")
                )
            ),
            "fewshot_failure_count": int(
                sum(
                    1
                    for row in processed_rows
                    if safe_strip((row.get("message_meta") or {}).get("message_error_type", "")) in {
                        "few_shot_min_examples_not_met",
                        "fewshot_retrieval_failed",
                    }
                )
            ),
        },
        "generation_status_counts": dict(generation_status_counts),
        "message_status_counts": dict(message_status_counts),
        "last_sample": {
            "sample_id": safe_strip((last_sample or {}).get("sample_id", "")),
            "repo": safe_strip((last_sample or {}).get("repo", "")),
            "generation_status": safe_strip((last_sample or {}).get("generation_status", "")),
            "message_status": safe_strip((last_sample or {}).get("message_status", "")),
        },
        "partial_outputs": {
            "samples_jsonl": str(partial_samples_path),
            "precheck_rejected_jsonl": str(partial_precheck_path),
            "progress_json": str(partial_progress_path),
        },
        "final_summary_available": bool(final_summary),
    }
    if final_summary:
        progress_payload["final_summary"] = dict(final_summary)
    write_json_payload(partial_progress_path, progress_payload)
    return progress_payload


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """将样本索引写入 CSV 文件，便于人工检查和数据分析。

    每行包含：
    - 样本基本信息（sample_id, repo, intent_k, construction_type 等）
    - Precheck 状态和跳过原因
    - Few-shot 检索来源
    - 生成的 synthetic subject 和 message status
    - 消息评分指标（coverage, faithfulness, style 等）
    - 各 intent 的源提交 SHA、type、subject
    """
    max_intent_count = max((len(row.get("sources", [])) for row in rows), default=0)
    fieldnames = [
        "sample_id", "repo", "intent_k", "construction_type", "type_pair",
        "type_signature_canonical", "source_types_canonical",
        "different_type", "module_overlap", "merged_file_count",
        "merged_changed_lines", "merged_hunk_count", "block_switches",
        "difficulty_level", "difficulty_name", "intent_cardinality", "structure_pattern", "realism_score",
        "sample_confidence", "precheck_status", "precheck_skip_reason", "precheck_warning_reasons",
        "pair_quality_weight", "min_pair_quality_weight", "few_shot_source", "few_shot_retrieval_log",
        "synthetic_subject", "generation_status", "message_status",
        "message_quality_weight", "final_sample_weight",
        "generation_success", "generation_failure_reason",
        "coverage_min_r", "coverage_avg_r", "coverage_balance",
        "faithfulness_p", "style_score", "relevance_score",
        "artifact_hit_count", "generic_phrase_hit", "format",
    ]
    for index in range(1, max_intent_count + 1):
        fieldnames.extend([f"source_sha_{index}", f"type_{index}", f"subject_{index}"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            source_payload = {}
            for index in range(1, max_intent_count + 1):
                if index <= len(row.get("sources", [])):
                    source = row["sources"][index - 1]
                    source_payload[f"source_sha_{index}"] = source["sha"]
                    source_payload[f"type_{index}"] = source["type"]
                    source_payload[f"subject_{index}"] = source["subject"]
                else:
                    source_payload[f"source_sha_{index}"] = ""
                    source_payload[f"type_{index}"] = ""
                    source_payload[f"subject_{index}"] = ""
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "repo": row["repo"],
                    "intent_k": row.get("intent_k", row.get("intent_count", 0)),
                    "construction_type": row["construction_type"],
                    "type_pair": row["type_pair"],
                    "type_signature_canonical": row.get("type_signature_canonical", row["type_pair"]),
                    "source_types_canonical": json.dumps(row.get("source_types_canonical", []), ensure_ascii=False),
                    "different_type": int(bool(row["different_type"])),
                    "module_overlap": int(bool(row["module_overlap"])),
                    "merged_file_count": row["merged_file_count"],
                    "merged_changed_lines": row["merged_changed_lines"],
                    "merged_hunk_count": row["merged_hunk_count"],
                    "block_switches": row["block_switches"],
                    "difficulty_level": row.get("difficulty_level", ""),
                    "difficulty_name": row.get("difficulty_name", ""),
                    "intent_cardinality": row.get("intent_cardinality", ""),
                    "structure_pattern": row.get("structure_pattern", ""),
                    "realism_score": row.get("realism_score", 0.0),
                    "sample_confidence": row["sample_confidence"],
                    "precheck_status": row.get("precheck_status", "pass"),
                    "precheck_skip_reason": row.get("precheck_skip_reason", ""),
                    "precheck_warning_reasons": json.dumps(row.get("precheck_warning_reasons", []), ensure_ascii=False),
                    "pair_quality_weight": row.get("pair_quality_weight", 1.0),
                    "min_pair_quality_weight": row.get("min_pair_quality_weight", row.get("pair_quality_weight", 1.0)),
                    "few_shot_source": row.get("few_shot_source", "none"),
                    "few_shot_retrieval_log": json.dumps(row.get("few_shot_retrieval_log", {}), ensure_ascii=False),
                    "synthetic_subject": row.get("synthetic_subject", ""),
                    "generation_status": row.get("generation_status", ""),
                    "message_status": row.get("message_status", "reject"),
                    "message_quality_weight": row.get("message_scores", {}).get("message_quality_weight", 0.0),
                    "final_sample_weight": row.get("final_sample_weight", 0.0),
                    "generation_success": int(bool(row.get("message_meta", {}).get("generation_success", False))),
                    "generation_failure_reason": row.get("message_meta", {}).get("generation_failure_reason", ""),
                    "coverage_min_r": row.get("message_scores", {}).get("coverage_min_r", 0.0),
                    "coverage_avg_r": row.get("message_scores", {}).get("coverage_avg_r", 0.0),
                    "coverage_balance": row.get("message_scores", {}).get("coverage_balance", 0.0),
                    "faithfulness_p": row.get("message_scores", {}).get("faithfulness_p", 0.0),
                    "style_score": row.get("message_scores", {}).get("style_score", 0.0),
                    "relevance_score": row.get("message_scores", {}).get("relevance_score", 0.0),
                    "artifact_hit_count": row.get("message_scores", {}).get("artifact_hit_count", 0),
                    "generic_phrase_hit": row.get("message_scores", {}).get("generic_phrase_hit", 0),
                    "format": row.get("message_scores", {}).get("format", 0),
                    **source_payload,
                }
            )


def write_summary(
    path: Path,
    samples: list[dict[str, Any]],
    intent_k: int,
    pool_size: int,
    pair_pool_size: int,
    seed: int,
    target_count: int,
    min_target_ratio: float,
    required_samples: int,
    target_gate_passed: bool,
    repo_cap: int,
    type_pair_cap: int,
    max_merged_files: int,
    max_merged_lines: int,
    require_different_type: bool,
    selection_quality_priority: str,
    selection_min_pair_quality_weight: float,
    prefer_module_overlap: bool,
    require_module_overlap: bool,
    block_order: str,
    message_metrics: dict[str, Any],
    message_gate_payload: dict[str, Any],
    precheck_stats: dict[str, Any],
    length_limit: int,
    run_purpose: str,
    run_valid_for_paper: bool,
    protocol_violations: list[str],
    difficulty_realism_summary: dict[str, Any] | None = None,
    difficulty_realism_runtime_config: dict[str, Any] | None = None,
) -> None:
    """写入运行摘要 Markdown 文件，汇总整个 Step2 运行的关键信息。

    报告结构：
    1. 配置参数汇总（scheme、seed、intent_k、策略参数等）
    2. Source Pair Precheck 统计（pass/warn/skip 分布、LLM 调用节省数）
    3. Message 指标（pass/fallback/reject、coverage、faithfulness、style 等）
    4. 分布真实性对比（synthetic vs real A-tier subject 的各项特征）
    5. Message Gate 结果
    6. 仓库分布和类型签名分布
    """
    repo_counter = Counter(row["repo"] for row in samples)
    type_pair_counter = Counter(row["type_pair"] for row in samples)
    different_type_count = sum(1 for row in samples if row["different_type"])
    module_overlap_count = sum(1 for row in samples if row["module_overlap"])
    unique_source_commits = {source["sha"] for row in samples for source in row["sources"]}

    # 计算平均值
    avg_files = sum(row["merged_file_count"] for row in samples) / len(samples) if samples else 0.0
    avg_lines = sum(row["merged_changed_lines"] for row in samples) / len(samples) if samples else 0.0
    avg_hunks = sum(row["merged_hunk_count"] for row in samples) / len(samples) if samples else 0.0
    avg_switches = sum(row["block_switches"] for row in samples) / len(samples) if samples else 0.0
    avg_confidence = sum(row["sample_confidence"] for row in samples) / len(samples) if samples else 0.0

    # 构建 Markdown 内容
    lines = [
        "# Step2 Simple Multi-Intent Summary",
        "",
        f"- Base scheme: `{BASE_SCHEME}`",
        f"- Preset: `{BASE_SCHEME}` (single scheme, CLI-overridable)",
        f"- Run purpose: `{run_purpose}`",
        f"- run_valid_for_paper: `{int(bool(run_valid_for_paper))}`",
        f"- protocol_violations: `{json.dumps(protocol_violations, ensure_ascii=False)}`",
        f"- Intent k: `{intent_k}`",
        f"- K distribution: `{json.dumps({str(intent_k): len(samples)}, ensure_ascii=False)}`",
        f"- Seed: `{seed}`",
        f"- Length limit (P90 subject chars): `{length_limit}`",
        f"- Construction strategy: `{block_order}`",
        f"- Selection filter: `{'different_type_only' if require_different_type else 'mixed_type_allowed'}`",
        f"- Selection quality priority: `{safe_strip(selection_quality_priority)}`",
        f"- Selection min pair quality weight: `{float(selection_min_pair_quality_weight):.2f}`",
        f"- Module overlap policy: `{'require' if require_module_overlap else 'prefer' if prefer_module_overlap else 'not_used'}`",
        f"- Selection caps: `repo_cap={repo_cap}, type_pair_cap={type_pair_cap}`",
        f"- Merge limits: `max_merged_files={max_merged_files}, max_merged_lines={max_merged_lines}`",
        f"- Target gate: `min_target_ratio={min_target_ratio:.3f}, required_samples={required_samples}, target_count={target_count}, passed={int(target_gate_passed)}`",
        f"- Tier-A source pool size: `{pool_size}`",
        f"- Eligible group pool size: `{pair_pool_size}`",
        (
            "- Pre-merge precheck (checked/passed/rejected): "
            f"`{precheck_stats.get('total_checked', 0)}` / `{precheck_stats.get('passed', 0)}` / "
            f"`{precheck_stats.get('rejected', 0)}`"
        ),
        (
            "- Pre-merge reject split (file_conflict/semantic_conflict): "
            f"`{precheck_stats.get('reject_file_conflict', 0)}` / "
            f"`{precheck_stats.get('reject_semantic_conflict', 0)}`"
        ),
        f"- Generated samples: `{len(samples)}`",
        f"- Unique source commits used: `{len(unique_source_commits)}`",
        f"- Different-type groups: `{different_type_count}`",
        f"- Same-type groups: `{len(samples) - different_type_count}`",
        f"- Module-overlap groups: `{module_overlap_count}`",
        f"- Average merged file count: `{avg_files:.2f}`",
        f"- Average merged changed lines: `{avg_lines:.2f}`",
        f"- Average merged hunk count: `{avg_hunks:.2f}`",
        f"- Average block switches: `{avg_switches:.2f}`",
        f"- Average sample confidence: `{avg_confidence:.4f}`",
        "",
        "## Source Pair Precheck",
        "",
        f"- precheck pass / warn / skip: `{message_metrics['precheck_pass_count']}` / `{message_metrics['precheck_warn_count']}` / `{message_metrics['precheck_skip_count']}`",
        f"- avg_pair_quality_weight_non_skipped: `{message_metrics['avg_pair_quality_weight_non_skipped']:.4f}`",
        f"- llm_calls_saved_by_precheck: `{message_metrics['llm_calls_saved_by_precheck']}`",
        f"- sampled_candidate_count: `{message_metrics['sampled_candidate_count']}`",
        f"- llm_generation_attempted_count: `{message_metrics['llm_generation_attempted_count']}`",
        f"- llm_generation_skipped_by_precheck_count: `{message_metrics['llm_generation_skipped_by_precheck_count']}`",
        f"- step3_ready_count: `{message_metrics['step3_ready_count']}`",
        f"- final_usable_sample_count: `{message_metrics['final_usable_sample_count']}`",
        f"- precheck_skip_reason_counts: `{json.dumps(message_metrics['precheck_skip_reason_counts'], ensure_ascii=False)}`",
        f"- precheck_warning_reason_counts: `{json.dumps(message_metrics['precheck_warning_reason_counts'], ensure_ascii=False)}`",
        "",
        "## Message Metrics",
        "",
        f"- pass / fallback / reject: `{message_metrics['message_pass_count']}` / `{message_metrics['message_fallback_count']}` / `{message_metrics['message_reject_count']}`",
        f"- pass_rate / fallback_rate / true_reject_rate: `{message_metrics['message_pass_rate']:.4f}` / `{message_metrics['message_fallback_rate']:.4f}` / `{message_metrics['true_message_reject_rate']:.4f}`",
        f"- avg_message_quality_weight: `{message_metrics['avg_message_quality_weight']:.4f}`",
        f"- avg_coverage_non_reject: `{message_metrics['avg_coverage_non_reject']:.4f}`",
        f"- avg_coverage_balance_non_reject: `{message_metrics['avg_coverage_balance_non_reject']:.4f}`",
        f"- avg_faithfulness_non_reject: `{message_metrics['avg_faithfulness_non_reject']:.4f}`",
        f"- avg_style_non_reject: `{message_metrics['avg_style_non_reject']:.4f}`",
        f"- avg_relevance_non_reject: `{message_metrics['avg_relevance_non_reject']:.4f}`",
        f"- avg_message_quality_weight_non_reject: `{message_metrics['avg_message_quality_weight_non_reject']:.4f}`",
        f"- format_fail_rate: `{message_metrics['format_fail_rate']:.4f}`",
        f"- bertscore_compute_invalid_rate: `{message_metrics['bertscore_compute_invalid_rate']:.4f}`",
        f"- generation_failure_rate_attempted: `{message_metrics['generation_failure_rate_attempted']:.4f}` (`{message_metrics['generation_failure_count']}/{message_metrics['generation_attempted_count']}`)",
        f"- few_shot_failed_rate / generic_rate: `{message_metrics['few_shot_failed_rate']:.4f}` / `{message_metrics['few_shot_generic_rate']:.4f}`",
        f"- precheck_skip_rate: `{message_metrics['precheck_skip_rate']:.4f}`",
        f"- coverage_min_avg / coverage_min_p10: `{message_metrics['coverage_min_avg']:.4f}` / `{message_metrics['coverage_min_p10']:.4f}`",
        f"- retry_heavy_rate: `{message_metrics['generation_retry_heavy_rate']:.4f}`",
        f"- avg_generation/compress/rewrite attempts: `{message_metrics['avg_generation_attempts']:.3f}` / `{message_metrics['avg_compress_attempts']:.3f}` / `{message_metrics['avg_rewrite_attempts']:.3f}`",
        f"- few_shot_type_matched_rate: `{message_metrics['few_shot_type_matched_rate']:.4f}`",
        f"- few_shot_source_distribution: `{json.dumps(message_metrics['few_shot_source_distribution'], ensure_ascii=False)}`",
        f"- label_template_hit_rate (monitor only): `{message_metrics['label_template_hit_rate']:.4f}`",
        f"- mechanical_semicolon_rate (monitor only): `{message_metrics['mechanical_semicolon_rate']:.4f}`",
        f"- dual_prefix_rate (monitor only): `{message_metrics['dual_prefix_rate']:.4f}`",
        f"- bullet_hit_rate (monitor only): `{message_metrics['bullet_hit_rate']:.4f}`",
        f"- numbered_list_hit_rate (monitor only): `{message_metrics['numbered_list_hit_rate']:.4f}`",
        f"- and_usage_rate (monitor only): `{message_metrics['and_usage_rate']:.4f}`",
        f"- artifact_any_hit_rate (monitor only): `{message_metrics['artifact_any_hit_rate']:.4f}`",
        f"- artifact_avg_hit_count (monitor only): `{message_metrics['artifact_avg_hit_count']:.4f}`",
        "",
        "## Distributional Realism (Synthetic vs Real A-tier Subject Anchor)",
        "",
        (
            "- token_count avg/p90 (real -> synthetic): "
            f"`{message_metrics['real_subject_distribution_anchor'].get('avg_token_count', 0.0):.3f}` / "
            f"`{message_metrics['real_subject_distribution_anchor'].get('p90_token_count', 0)}` -> "
            f"`{message_metrics['synthetic_subject_distribution'].get('avg_token_count', 0.0):.3f}` / "
            f"`{message_metrics['synthetic_subject_distribution'].get('p90_token_count', 0)}`"
        ),
        (
            "- and/comma/prefix/generic rates (real -> synthetic): "
            f"`{message_metrics['real_subject_distribution_anchor'].get('and_rate', 0.0):.3f}` / "
            f"`{message_metrics['real_subject_distribution_anchor'].get('comma_rate', 0.0):.3f}` / "
            f"`{message_metrics['real_subject_distribution_anchor'].get('prefix_rate', 0.0):.3f}` / "
            f"`{message_metrics['real_subject_distribution_anchor'].get('generic_phrase_rate', 0.0):.3f}` -> "
            f"`{message_metrics['synthetic_subject_distribution'].get('and_rate', 0.0):.3f}` / "
            f"`{message_metrics['synthetic_subject_distribution'].get('comma_rate', 0.0):.3f}` / "
            f"`{message_metrics['synthetic_subject_distribution'].get('prefix_rate', 0.0):.3f}` / "
            f"`{message_metrics['synthetic_subject_distribution'].get('generic_phrase_rate', 0.0):.3f}`"
        ),
        "",
        "## Message Gate",
        "",
        f"- enabled: `{int(bool(message_gate_payload.get('message_gate_enabled', False)))}`",
        f"- passed: `{int(bool(message_gate_payload.get('message_gate_passed', False)))}`",
        f"- source: `{message_gate_payload.get('message_gate_source')}`",
        f"- reason: `{message_gate_payload.get('reason')}`",
        f"- failed_metrics: `{json.dumps(message_gate_payload.get('failed_metrics', []), ensure_ascii=False)}`",
        f"- gate_metrics: `{json.dumps(message_gate_payload.get('gate_metrics', {}), ensure_ascii=False)}`",
        "",
        "## Difficulty And Realism",
        "",
        f"- level_distribution: `{json.dumps((difficulty_realism_summary or {}).get('level_distribution', {}), ensure_ascii=False)}`",
        f"- difficulty_level_counts: `{json.dumps((difficulty_realism_summary or {}).get('difficulty_level_counts', {}), ensure_ascii=False)}`",
        f"- intent_cardinality_distribution: `{json.dumps((difficulty_realism_summary or {}).get('intent_cardinality_distribution', {}), ensure_ascii=False)}`",
        f"- structure_pattern_distribution: `{json.dumps((difficulty_realism_summary or {}).get('structure_pattern_distribution', {}), ensure_ascii=False)}`",
        f"- construction_route_distribution: `{json.dumps((difficulty_realism_summary or {}).get('construction_route_distribution', {}), ensure_ascii=False)}`",
        f"- realism_score_summary: `{json.dumps((difficulty_realism_summary or {}).get('realism_score_summary', {}), ensure_ascii=False)}`",
        f"- rho_summary: `{json.dumps((difficulty_realism_summary or {}).get('rho_summary', {}), ensure_ascii=False)}`",
        f"- tau_realism_low: `{safe_float((difficulty_realism_runtime_config or {}).get('tau_realism_low', DEFAULT_TAU_REALISM_LOW))}`",
        f"- threshold_source: `{safe_strip((difficulty_realism_runtime_config or {}).get('tau_realism_low_source', 'default'))}`",
        f"- realism_weight_formula: `{safe_strip((difficulty_realism_summary or {}).get('realism_weight_formula', ''))}`",
        f"- realism_weight_config: `{json.dumps((difficulty_realism_summary or {}).get('realism_weight_config', {}), ensure_ascii=False)}`",
        f"- pipeline_owner: `{safe_strip((difficulty_realism_summary or {}).get('pipeline_owner', ''))}`",
        f"- pipeline_order: `{json.dumps((difficulty_realism_summary or {}).get('pipeline_order', []), ensure_ascii=False)}`",
        f"- feature_distributions: `{json.dumps((difficulty_realism_summary or {}).get('feature_distributions', {}), ensure_ascii=False)}`",
        "",
        "## Repo Distribution",
        "",
    ]
    # 添加仓库分布
    for repo, count in repo_counter.most_common():
        lines.append(f"- `{repo}`: {count}")
    lines.extend(["", "## Type-Signature Distribution", ""])
    # 添加类型对分布
    for pair_type, count in type_pair_counter.most_common():
        lines.append(f"- `{pair_type}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def samples_pair_fingerprint(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """计算样本集合的配对指纹，用于追踪选定的 source commit 组合。

    将每个样本的 sample_id、repo、type_pair、source_shas 排序后
    计算 canonical JSON hash，用于检测选定配对是否发生变化。
    """
    payload = []
    for row in samples:
        source_shas = sorted(source["sha"] for source in row["sources"])
        payload.append(
            {
                "sample_id": row["sample_id"],
                "repo": row["repo"],
                "type_pair": row.get("type_signature_canonical", row["type_pair"]),
                "source_shas": source_shas,
            }
        )
    payload.sort(key=lambda item: item["sample_id"])
    return {
        "pair_count": len(payload),
        "sha256": canonical_json_hash(payload),
    }


def write_run_metadata(
    path: Path,
    args: argparse.Namespace,
    source_fingerprint: dict[str, Any],
    config_fingerprint: dict[str, Any] | None,
    script_fingerprint: dict[str, Any],
    a_tier_fingerprint: dict[str, Any],
    selected_pairs_fingerprint: dict[str, Any],
    step3_ready_fingerprint: dict[str, Any],
    length_limit_stats: dict[str, Any],
    pool_stats: dict[str, Any],
    pair_pool_size: int,
    samples: list[dict[str, Any]],
    required_samples: int,
    target_gate_passed: bool,
    threshold_payload: dict[str, Any],
    message_metrics: dict[str, Any],
    message_gate_payload: dict[str, Any],
    precheck_stats: dict[str, Any],
    source_pair_precheck_stats: dict[str, Any],
    difficulty_realism_summary: dict[str, Any] | None = None,
    difficulty_realism_runtime_config: dict[str, Any] | None = None,
) -> None:
    """写出完整的 run_metadata.json，记录整个运行的元数据。

    用于可复现性审计，包含：
    - 运行环境（Python 版本、平台、argv 脱敏）
    - 协议版本和 formal_run 判定
    - 输入文件指纹（SHA256、大小、修改时间）
    - 解析后的完整配置
    - Few-shot pool 审计信息
    - Diff evidence 策略和可用率
    - 阈值校准结果和 gate 检查详情
    - 运行统计（源池大小、生成数、step3 就绪数等）
    - 运行指纹（所有关键输入的组合 hash）
    """
    repo_counter = Counter(row["repo"] for row in samples)
    type_pair_counter = Counter(row["type_pair"] for row in samples)
    unique_source_commits = {source["sha"] for row in samples for source in row["sources"]}
    few_shot_source_dist = Counter(row.get("few_shot_source", "none") for row in samples)
    diff_evidence_sources = Counter(
        safe_strip(source)
        for row in samples
        for source in row.get("intent_diff_evidence_sources", [])
        if safe_strip(source)
    )
    diff_evidence_flags = [
        bool(flag)
        for row in samples
        for flag in row.get("intent_diff_evidence_available", [])
    ]
    diff_evidence_available_rate = (
        round(sum(1 for flag in diff_evidence_flags if flag) / len(diff_evidence_flags), 6)
        if diff_evidence_flags
        else 0.0
    )
    fewshot_audit = dict(getattr(args, "_fewshot_pool_audit", {}))
    fewshot_pool_total_examples = int(getattr(args, "_fewshot_pool_total_examples", 0))
    fewshot_pool_verified_examples = int(getattr(args, "_fewshot_pool_verified_examples", 0))
    fewshot_pool_formal_ready = bool(getattr(args, "_fewshot_pool_formal_ready", False))
    formal_assets = dict(getattr(args, "_formal_assets", {}))

    payload = {
        "run_utc": dt.datetime.now(dt.UTC).isoformat(),
        "script": str(Path(__file__).resolve()),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "argv": redact_argv(getattr(args, "_invocation_argv", sys.argv)),
        "formal_protocol_version": FORMAL_PROTOCOL_VERSION,
        "script_fingerprint": script_fingerprint,
        "base_scheme": BASE_SCHEME,
        "preset": args.preset,
        "seed": args.seed,
        "run_purpose": safe_strip(getattr(args, "run_purpose", "")),
        "run_purpose_source": safe_strip(getattr(args, "run_purpose_source", "")),
        "formal_run": bool(args.formal_run),
        "run_valid_for_paper": bool(args.run_valid_for_paper),
        "protocol_violations": list(getattr(args, "protocol_violations", [])),
        "formal_protocol_flags": dict(getattr(args, "formal_protocol_flags", {})),
        "inputs": {
            "source_csv": str(Path(args.source_csv)),
            "config": str(Path(args.config)),
            "selected_pairs_jsonl": safe_strip(getattr(args, "selected_pairs_jsonl", "")),
            "selected_pairs_manifest": safe_strip(getattr(args, "selected_pairs_manifest", "")),
        },
        "input_fingerprints": {
            "source_csv": source_fingerprint,
            "a_tier_pool": a_tier_fingerprint,
            "selected_pairs": selected_pairs_fingerprint,
        },
        "outputs": {
            "output_dir": str(Path(args.output_dir)),
            "summary": str((Path(args.output_dir) / "summary.md")),
            "index_csv": str((Path(args.output_dir) / "synthetic_index.csv")),
            "samples_jsonl": str((Path(args.output_dir) / "synthetic_samples.jsonl")),
            "partial_samples_jsonl": str((Path(args.output_dir) / "synthetic_samples.partial.jsonl")),
            "precheck_rejected_jsonl": str((Path(args.output_dir) / "synthetic_samples_precheck_rejected.jsonl")),
            "partial_precheck_rejected_jsonl": str(
                (Path(args.output_dir) / "synthetic_samples_precheck_rejected.partial.jsonl")
            ),
            "review_md": str((Path(args.output_dir) / "review_samples.md")),
            "step3_ready_jsonl": str((Path(args.output_dir) / "synthetic_samples_step3_ready.jsonl")),
            "message_gate_report": str(Path(args.message_gate_report_path)),
            "run_progress_json": str((Path(args.output_dir) / "run_progress.json")),
            "metadata_json": str(path),
        },
        "resolved_config": {
            "intent_k": int(args.intent_k),
            "k_sweep_max": int(args.k_sweep_max),
            "require_different_type": bool(args.require_different_type),
            "module_overlap_policy": args.module_overlap_policy,
            "allow_entangled_candidates": bool(getattr(args, "allow_entangled_candidates", False)),
            "max_shared_files_per_group": int(getattr(args, "max_shared_files_per_group", 0)),
            "block_order": args.block_order,
            "target_count": int(args.target_count),
            "repo_cap": int(args.repo_cap),
            "type_pair_cap": int(args.type_pair_cap),
            "selection_quality_priority": safe_strip(getattr(args, "selection_quality_priority", "legacy")),
            "selection_min_pair_quality_weight": float(getattr(args, "selection_min_pair_quality_weight", 0.0)),
            "max_merged_files": int(args.max_merged_files),
            "max_merged_lines": int(args.max_merged_lines),
            "group_combo_attempt_cap_per_repo": int(args.group_combo_attempt_cap_per_repo),
            "group_candidate_cap_per_repo": int(args.group_candidate_cap_per_repo),
            "review_samples": int(args.review_samples),
            "min_target_ratio": float(args.min_target_ratio),
            "required_samples": int(required_samples),
            "sample_id_offset": int(getattr(args, "sample_id_offset", 0)),
            "progress_flush_every": int(max(0, int(getattr(args, "progress_flush_every", 0)))),
            "manual_label": args.manual_label,
            "config_path": str(Path(args.config)),
        },
        "message_config": {
            "skip_message_stage": bool(args.skip_message_stage),
            "message_stage_mandatory": bool(getattr(args, "formal_protocol_flags", {}).get("message_stage_mandatory", True)),
            "message_gate_mandatory": bool(getattr(args, "formal_protocol_flags", {}).get("message_gate_mandatory", True)),
            "few_shot_mandatory": bool(getattr(args, "formal_protocol_flags", {}).get("few_shot_mandatory", True)),
            "debug_override_used": bool(getattr(args, "formal_protocol_flags", {}).get("debug_override_used", False)),
            "generator_mode": getattr(args, "generator_mode", "api"),
            "prompt_version": args.prompt_version,
            "k_way_prompt_enabled": True,
            "generator_provider": args.generator_provider,
            "generator_model": args.generator_model,
            "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
            "deepseek_base_url": args.deepseek_base_url,
            "api_key_source": getattr(args, "_deepseek_api_key_source", "unknown"),
            "deepseek_api_key_source": getattr(args, "_deepseek_api_key_source", "unknown"),
            "scorer_backend": args.scorer_backend,
            "bertscore_model": args.bertscore_model,
            "bertscore_lang": args.bertscore_lang,
            "bertscore_idf": bool(args.bertscore_idf),
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_output_tokens": args.max_output_tokens,
            "max_generation_attempts": args.max_generation_attempts,
            "max_abstractive_compress_attempts": args.max_abstractive_compress_attempts,
            "max_rewrite_attempts": args.max_rewrite_attempts,
            "max_final_strong_compress_attempts": int(getattr(args, "max_final_strong_compress_attempts", 1)),
            "few_shot_k": args.few_shot_k,
            "fewshot_db": args.fewshot_db,
            "fewshot_source_csv": getattr(args, "fewshot_source_csv", ""),
            "fewshot_table": args.fewshot_table,
            "retrieval_query_version": args.retrieval_query_version,
            "fewshot_pool_resolution": getattr(args, "_fewshot_pool_resolution", {}),
            "few_shot_min_examples_per_sample": int(getattr(args, "few_shot_min_examples_per_sample", 1)),
            "few_shot_warn_if_below_requested": bool(getattr(args, "few_shot_warn_if_below_requested", True)),
            "few_shot_generic_rate_warn_threshold": float(getattr(args, "few_shot_generic_rate_warn_threshold", DEFAULT_FEWSHOT_GENERIC_RATE_WARN_THRESHOLD)),
            "few_shot_failed_rate_gate_threshold": float(getattr(args, "few_shot_failed_rate_gate_threshold", args.gate_max_fewshot_failure_rate)),
            "fewshot_min_total_examples": int(getattr(args, "fewshot_min_total_examples", DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES)),
            "fewshot_min_examples_per_common_signature": int(
                getattr(args, "fewshot_min_examples_per_common_signature", DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE)
            ),
            "fewshot_audit_strict_style": bool(
                getattr(args, "fewshot_audit_strict_style", DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE)
            ),
            "retrieval_cmd_template": (
                "python code/retrieve_fewshot.py "
                "--db <DB> --table <TABLE> --type-pair <TYPE_PAIR> --repo <REPO> "
                "--k <K> --seed <SEED> --query-version <QUERY_VERSION>"
            ),
            "generation_cache_enabled": bool(args.generation_cache_enabled),
            "generation_cache_path": args.generation_cache_path,
            "bertscore_cache_enabled": bool(args.bertscore_cache_enabled),
            "bertscore_cache_path": args.bertscore_cache_path,
            "length_limit": int(length_limit_stats["p90"]),
            "final_strong_relaxed_length_limit": int(length_limit_stats.get("p95", length_limit_stats["p90"])),
            "final_strong_relaxed_length_policy": "p95(real_single_intent_commit_subject_length)",
            "length_limit_policy": length_limit_stats["policy"],
            "length_limit_source": length_limit_stats["source"],
            "length_limit_stats": length_limit_stats,
            "source_pair_precheck_enabled": bool(getattr(args, "enable_source_pair_precheck", True)),
        },
        "diff_evidence": {
            "diff_evidence_card_version": DIFF_EVIDENCE_CARD_VERSION,
            "diff_evidence_policy": DIFF_EVIDENCE_POLICY,
            "diff_evidence_required_for_formal": bool(DIFF_EVIDENCE_REQUIRED_FOR_FORMAL),
            "diff_evidence_available_rate": diff_evidence_available_rate,
            "diff_evidence_source_distribution": dict(diff_evidence_sources),
        },
        "difficulty_realism": {
            "tau_realism_low": safe_float((difficulty_realism_runtime_config or {}).get("tau_realism_low", DEFAULT_TAU_REALISM_LOW)),
            "tau_realism_low_source": safe_strip((difficulty_realism_runtime_config or {}).get("tau_realism_low_source", "default")),
            "level_a_b_route_status": "schema_ready_route_not_implemented",
            "realism_weight_formula": safe_strip((difficulty_realism_summary or {}).get("realism_weight_formula", "")),
            "realism_weight_config": dict((difficulty_realism_summary or {}).get("realism_weight_config", {}) or {}),
            "pipeline_owner": safe_strip((difficulty_realism_summary or {}).get("pipeline_owner", "")),
            "pipeline_order": list((difficulty_realism_summary or {}).get("pipeline_order", []) or []),
        },
        "fewshot_pool": {
            "fewshot_pool_path": safe_strip(getattr(args, "fewshot_db", "")),
            "fewshot_pool_resolved_path": safe_strip((getattr(args, "_fewshot_pool_resolution", {}) or {}).get("resolved_db", getattr(args, "fewshot_db", ""))),
            "fewshot_pool_total_examples": fewshot_pool_total_examples,
            "fewshot_pool_verified_examples": fewshot_pool_verified_examples,
            "fewshot_pool_formal_ready": fewshot_pool_formal_ready,
            "fewshot_pool_audit": fewshot_audit,
            "common_signature_coverage": fewshot_audit.get("common_signature_coverage", {}),
            "bad_style_count": int(fewshot_audit.get("bad_style_count", 0)),
            "fewshot_eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
        },
        "formal_assets": formal_assets,
        "type_canonicalization_map": COMMIT_TYPE_NORMALIZE_MAP,
        "source_pair_precheck": source_pair_precheck_stats,
        "thresholds": {
            **threshold_payload,
            "gate_thresholds": {
                "gate_min_message_pass_rate": float(args.gate_min_message_pass_rate),
                "gate_max_message_reject_rate": float(args.gate_max_message_reject_rate),
                "gate_min_avg_message_quality_weight_non_reject": float(
                    args.gate_min_avg_message_quality_weight_non_reject
                ),
                "gate_max_fewshot_failure_rate": float(args.gate_max_fewshot_failure_rate),
                "few_shot_failed_rate_gate_threshold": float(
                    getattr(args, "few_shot_failed_rate_gate_threshold", args.gate_max_fewshot_failure_rate)
                ),
                "few_shot_generic_rate_warn_threshold": float(
                    getattr(args, "few_shot_generic_rate_warn_threshold", DEFAULT_FEWSHOT_GENERIC_RATE_WARN_THRESHOLD)
                ),
                "gate_max_precheck_skip_rate": float(args.gate_max_precheck_skip_rate),
                "gate_max_generation_failure_rate": float(args.gate_max_generation_failure_rate),
                "gate_min_coverage_min_avg": float(args.gate_min_coverage_min_avg),
                "gate_min_coverage_min_p10": float(args.gate_min_coverage_min_p10),
            },
            "calibration_data_fingerprint": canonical_json_hash(
                [row["message_scores"]["message_quality_weight"] for row in samples]
            ),
        },
        "message_gate": message_gate_payload,
        "reproducibility": {
            "global_seed": args.seed,
            "seed_targets": ["python_random", "numpy_if_available", "torch_if_available", "llm_request_seed"],
            "api_provider": args.generator_provider,
            "model_snapshot": args.generator_model,
            "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
            "config_path": str(Path(args.config)),
            "generation_cache_enabled": bool(args.generation_cache_enabled),
            "generation_cache_path": args.generation_cache_path,
            "bertscore_cache_enabled": bool(args.bertscore_cache_enabled),
            "bertscore_cache_path": args.bertscore_cache_path,
        },
        "run_stats": {
            "source_pool_size": int(pool_stats["a_tier_rows"]),
            "pool_repo_count": int(pool_stats["repo_count"]),
            "pool_type_count": int(pool_stats["type_count"]),
            "eligible_pair_pool_size": int(pair_pool_size),
            "generated_samples": int(len(samples)),
            "target_gate_passed": bool(target_gate_passed),
            "unique_source_commits": int(len(unique_source_commits)),
            "repo_distribution": dict(repo_counter.most_common()),
            "type_pair_distribution": dict(type_pair_counter.most_common()),
            "few_shot_source_distribution": dict(few_shot_source_dist),
            "premerge_precheck": precheck_stats,
            "source_pair_precheck_summary": source_pair_precheck_stats,
            "message_metrics": message_metrics,
            "difficulty_realism_summary": difficulty_realism_summary or {},
            "step3_ready_count": int(step3_ready_fingerprint["pair_count"]),
            "step3_ready_fingerprint": step3_ready_fingerprint["sha256"],
        },
    }
    if config_fingerprint is not None:
        payload["input_fingerprints"]["runtime_config"] = config_fingerprint

    payload["run_fingerprint"] = canonical_json_hash(
        {
            "input_sha": source_fingerprint["sha256"],
            "config_sha": config_fingerprint["sha256"] if config_fingerprint else "",
            "selected_pairs_sha": selected_pairs_fingerprint["sha256"],
            "seed": args.seed,
            "preset": args.preset,
            "resolved_config": payload["resolved_config"],
            "message_config": payload["message_config"],
            "formal_assets": payload.get("formal_assets", {}),
            "source_pair_precheck": payload.get("source_pair_precheck", {}),
            "thresholds": payload["thresholds"],
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_review(path: Path, samples: list[dict[str, Any]]) -> None:
    """写入供人工审查的 Markdown 文件

    包含每个样本的详细信息：
    - 基本信息（repo、类型、状态等）
    - 两个意图的源信息
    - 消息评分
    - Edit units（前 12 个）
    - Synthetic diff 摘要

    Args:
        path: 输出文件路径
        samples: 要输出的样本列表
    """
    lines = ["# Step2 Simple Multi-Intent Review Samples", ""]
    for row in samples:
        intent_sections: list[str] = []
        for index, source in enumerate(row["sources"]):
            intent_sections.extend(
                [
                    f"### Intent {index}",
                    "",
                    f"- SHA: `{source['sha']}`",
                    f"- Type: `{source['type']}`",
                    f"- Subject: `{source['subject']}`",
                    "",
                ]
            )
        lines.extend(
            [
                f"## {row['sample_id']}",
                "",
                f"- Repo: `{row['repo']}`",
                f"- Construction: `{row['construction_type']}`",
                f"- Type Pair: `{row['type_pair']}`",
                f"- Different Type: `{row['different_type']}`",
                f"- Module Overlap: `{row['module_overlap']}`",
                f"- Merged Files: `{row['merged_file_count']}`",
                f"- Merged Changed Lines: `{row['merged_changed_lines']}`",
                f"- Merged Hunk Count: `{row['merged_hunk_count']}`",
                f"- Block Switches: `{row['block_switches']}`",
                f"- Sample Confidence: `{row['sample_confidence']}`",
                f"- Precheck Status: `{row.get('precheck_status', 'pass')}`",
                f"- Precheck Skip Reason: `{row.get('precheck_skip_reason', '')}`",
                f"- Pair Quality Weight: `{row.get('pair_quality_weight', 1.0)}`",
                f"- Synthetic Subject: `{row.get('synthetic_subject', '')}`",
                f"- Message Status: `{row.get('message_status', 'reject')}`",
                f"- Message Weight: `{row.get('message_scores', {}).get('message_quality_weight', 0.0)}`",
                "",
                *intent_sections,
                "### Message Scores",
                "",
                "```json",
                json.dumps(row.get("message_scores", {}), ensure_ascii=False, indent=2),
                "```",
                "",
                "### Message Meta",
                "",
                "```json",
                json.dumps(row.get("message_meta", {}), ensure_ascii=False, indent=2),
                "```",
                "",
                "### Edit Units",
                "",
                "```json",
                json.dumps(row["edit_units"][:12], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Synthetic Diff Excerpt",
                "",
                "```diff",
                compact_diff(row["synthetic_diff"]),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def apply_source_pair_precheck_to_samples(
    samples: list[dict[str, Any]],
    config: argparse.Namespace,
    git_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对所有样本执行 source pair precheck，并将结果写回样本字段。

    对每个样本的所有源提交对执行 all-pairs precheck：
    - 检测 near-duplicate、语义冲突、type 兼容性等
    - 聚合为 sample 级的 precheck_status（pass/warn/skip）
    - 计算 pair_quality_weight（几何平均）

    返回整体 precheck 统计信息（状态分布、跳过原因、LLM 调用节省数等）。
    """
    status_counter: Counter[str] = Counter()
    skip_reason_counter: Counter[str] = Counter()
    warning_reason_counter: Counter[str] = Counter()
    weight_sum_non_skipped = 0.0
    non_skipped = 0
    llm_calls_saved = 0

    enabled = bool(getattr(config, "enable_source_pair_precheck", True))
    pre_cfg = extract_pair_precheck_config(config)
    for sample in samples:
        sources = list(sample.get("sources", []))
        if not enabled:
            payload = {
                "precheck_status": "pass",
                "precheck_skip_reason": "",
                "precheck_warning_reasons": [],
                "pair_quality_weight": 1.0,
                "min_pair_quality_weight": 1.0,
                "precheck_scores": {
                    "merge": 1.0,
                    "semantic": 1.0,
                    "type_compatibility": 1.0,
                    "non_duplicate": 1.0,
                    "relation": 1.0,
                    "input_message": 1.0,
                },
                "precheck_meta": {
                    "precheck_version": pre_cfg["precheck_version"],
                    "rules_triggered": [],
                    "generation_allowed": True,
                    "semantic_check_mode": "rule_only",
                    "git_check_method": "disabled",
                    "enabled": False,
                },
                "pair_precheck_results": [],
            }
        else:
            payload = aggregate_source_set_precheck(
                sources,
                config=config,
                git_context=git_context,
            )

        sample["precheck_status"] = payload["precheck_status"]
        sample["precheck_skip_reason"] = payload["precheck_skip_reason"]
        sample["precheck_warning_reasons"] = payload["precheck_warning_reasons"]
        sample["pair_quality_weight"] = payload["pair_quality_weight"]
        sample["min_pair_quality_weight"] = payload.get("min_pair_quality_weight", payload["pair_quality_weight"])
        sample["precheck_scores"] = payload["precheck_scores"]
        sample["precheck_meta"] = payload["precheck_meta"]
        sample["pair_precheck_results"] = payload.get("pair_precheck_results", [])

        status_counter[sample["precheck_status"]] += 1
        if sample["precheck_skip_reason"]:
            skip_reason_counter[sample["precheck_skip_reason"]] += 1
        for reason in sample["precheck_warning_reasons"]:
            warning_reason_counter[reason] += 1
        if sample["precheck_status"] != "skip":
            non_skipped += 1
            weight_sum_non_skipped += float(sample.get("pair_quality_weight", 0.0))
        else:
            llm_calls_saved += 1

    return {
        "enabled": enabled,
        "precheck_version": pre_cfg["precheck_version"],
        "status_counts": dict(status_counter),
        "skip_reason_counts": dict(skip_reason_counter),
        "warning_reason_counts": dict(warning_reason_counter),
        "avg_pair_quality_weight_non_skipped": round(weight_sum_non_skipped / non_skipped, 6) if non_skipped else 0.0,
        "llm_calls_saved_by_precheck": int(llm_calls_saved),
        "non_skipped_count": int(non_skipped),
        "thresholds": {
            "duplicate_jaccard_threshold": pre_cfg["duplicate_jaccard_threshold"],
            "duplicate_seq_threshold": pre_cfg["duplicate_seq_threshold"],
            "moderate_similarity_threshold": pre_cfg["moderate_similarity_threshold"],
            "relation_low_threshold": pre_cfg["relation_low_threshold"],
            "heavy_overlap_threshold": pre_cfg["heavy_overlap_threshold"],
        },
        "type_compatibility": {
            "high": pre_cfg["type_compat_high"],
            "medium": pre_cfg["type_compat_medium"],
            "forbidden_heads": pre_cfg["type_forbidden_heads"],
        },
        "semantic_check_mode": "rule_only",
        "git_check_method": "not_available",
    }


def build_message_fields_for_skipped_stage(sample: dict[str, Any]) -> None:
    """为跳过 message 阶段的样本构建占位字段

    Args:
        sample: 样本字典（会被修改）
    """
    sample.setdefault("precheck_status", "pass")
    sample.setdefault("precheck_skip_reason", "")
    sample.setdefault("precheck_warning_reasons", [])
    sample.setdefault("pair_quality_weight", 1.0)
    sample.setdefault(
        "precheck_scores",
        {
            "merge": 1.0,
            "semantic": 1.0,
            "type_compatibility": 1.0,
            "non_duplicate": 1.0,
            "relation": 1.0,
            "input_message": 1.0,
        },
    )
    sample.setdefault(
        "precheck_meta",
        {
            "precheck_version": SOURCE_PAIR_PRECHECK_VERSION,
            "rules_triggered": [],
            "generation_allowed": True,
            "semantic_check_mode": "rule_only",
            "git_check_method": "not_available",
        },
    )
    source_subjects = [
        safe_strip(source.get("subject", ""))
        for source in sample.get("sources", [])
        if safe_strip(source.get("subject", ""))
    ]
    placeholder_subject = " / ".join(source_subjects[:2]) if source_subjects else "message stage skipped"
    surface = subject_surface_features(placeholder_subject)
    sample["synthetic_subject"] = placeholder_subject
    sample["generation_status"] = "generated"
    sample["message_status"] = "fallback"
    sample["few_shot_source"] = "skipped"
    sample["few_shot_retrieval_log"] = {
        "requested_type_signature": sample.get("type_signature_canonical", sample.get("type_pair", "")),
        "requested_types_canonical": list(sample.get("source_types_canonical", [])),
        "intent_k": int(sample.get("intent_k", sample.get("intent_count", 0))),
        "few_shot_requested_k": 0,
        "query_levels_attempted": [],
        "examples_found_per_level": {},
        "selected_example_ids": [],
        "selected_example_type_signatures": [],
        "selected_example_repos": [],
        "retrieval_status": "skipped",
        "failure_reason": "message_stage_skipped",
    }
    sample["message_scores"] = {
        "format": 1,
        "coverage_r_list": [],
        "coverage_by_source": [],
        "coverage_min_r": 0.0,
        "coverage_min": 0.0,
        "coverage_avg_r": 0.0,
        "coverage_avg": 0.0,
        "coverage_balance": 0.0,
        "faithfulness_p": 0.0,
        "artifact_hit_count": 0,
        "artifact_score": 0.0,
        "relevance_score": 0.0,
        "style_score": 1.0,
        "generic_phrase_hit": 0,
        "token_count": int(surface.get("token_count", 0)),
        "imperative_head": int(surface.get("imperative_head", 0)),
        "message_quality_weight": 1.0,
        "bertscore_compute_invalid": 0,
        "bertscore_error": "",
    }
    sample["message_meta"] = {
        "generator_provider": "skipped",
        "generator_model": "skipped",
        "generator_mode": "skipped",
        "scorer_backend": "skipped",
        "prompt_version": "skipped",
        "generation_success": False,
        "generation_skipped": True,
        "generation_failure_reason": "message_stage_skipped",
        "formal_run": False,
        "run_valid_for_paper": False,
        "generation_attempts": 0,
        "compress_attempts": 0,
        "rewrite_attempts": 0,
        "generation_trace": [],
        "length_limit": 0,
        "length_limit_source": "skipped",
        "few_shot_ids": [],
        "few_shot_source": "skipped",
        **make_diff_evidence_meta(sample),
    }
    sample["final_sample_weight"] = 1.0


def prepare_run_context(
    args: argparse.Namespace | str | Path,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """预热单次 Step2 运行所需的重型只读上下文，供多个 shard 复用。"""
    if isinstance(args, (str, Path)):
        parse_argv = ["--config", str(args)]
        if output_dir is not None:
            parse_argv.extend(["--output-dir", str(output_dir)])
        args = parse_args(parse_argv)

    effective_output_dir = Path(output_dir) if output_dir is not None else Path(args.output_dir)
    effective_output_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_message_stage:
        resolved_fewshot_db, fewshot_pool_resolution = resolve_fewshot_pool_or_fail(args, effective_output_dir)
        args.fewshot_db = str(resolved_fewshot_db)
        raw_fewshot_rows = load_fewshot_pool_rows(str(resolved_fewshot_db), args.fewshot_table)
        fewshot_audit = audit_fewshot_pool(
            raw_fewshot_rows,
            min_total=int(getattr(args, "fewshot_min_total_examples", DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES)),
            min_per_common_signature=int(
                getattr(
                    args,
                    "fewshot_min_examples_per_common_signature",
                    DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
                )
            ),
            strict_style=bool(getattr(args, "fewshot_audit_strict_style", DEFAULT_FEWSHOT_AUDIT_STRICT_STYLE)),
        )
        fewshot_pool_total_examples = int(fewshot_audit.get("total_examples", 0))
        fewshot_pool_verified_examples = int(fewshot_audit.get("verified_examples", 0))
        fewshot_pool_formal_ready = bool(fewshot_audit.get("audit_pass", False))
        formal_assets = collect_formal_asset_status(
            args,
            resolved_fewshot_db=resolved_fewshot_db,
            require_fewshot_build_manifest=bool(getattr(args, "formal_run", False)),
        )
        if bool(getattr(args, "formal_run", False)) and not fewshot_pool_formal_ready:
            raise RuntimeError(
                "Default few-shot pool is pilot-sized and not formal-ready. "
                "Provide --fewshot-db or build a verified few-shot pool. "
                f"blockers={fewshot_audit.get('blockers', [])}"
            )
        if bool(getattr(args, "formal_run", False)) and not bool((formal_assets or {}).get("formal_assets_ready", False)):
            raise RuntimeError(
                "Formal asset validation failed. "
                f"blockers={(formal_assets or {}).get('blockers', [])}"
            )
        if bool(getattr(args, "formal_run", False)) and bool(DIFF_EVIDENCE_REQUIRED_FOR_FORMAL) and (not bool(DIFF_EVIDENCE_POLICY)):
            raise RuntimeError("Diff evidence policy is required for formal runs but is not enabled.")
        bertscorer = init_bertscorer(args)
        fewshot_db_path = str(resolved_fewshot_db)
    else:
        fewshot_pool_resolution = {"source": "message_stage_skipped", "built_default_pool": False}
        fewshot_audit = {}
        fewshot_pool_total_examples = 0
        fewshot_pool_verified_examples = 0
        fewshot_pool_formal_ready = False
        formal_assets = collect_formal_asset_status(
            args,
            resolved_fewshot_db=getattr(args, "fewshot_db", ""),
            require_fewshot_build_manifest=False,
        )
        bertscorer = None
        fewshot_db_path = safe_strip(getattr(args, "fewshot_db", ""))

    source_path = Path(args.source_csv)
    config_path = Path(args.config)
    source_fingerprint = file_fingerprint(source_path)
    config_fingerprint = file_fingerprint(config_path) if config_path.exists() else None
    script_fingerprint = file_fingerprint(Path(__file__))

    source_rows = load_csv(source_path)
    pool, pool_stats = build_source_pool_from_minimal(source_rows, manual_label=args.manual_label)
    a_tier_fingerprint = rows_fingerprint(
        pool,
        fields=["sha", "repo", "type", "subject", "commit_message", "manual_label"],
        sort_key="sha",
    )
    length_limit_stats = compute_length_limit_stats(pool)
    real_subject_distribution = summarize_subject_distribution(
        [safe_strip(row.get("subject", "")) for row in pool]
    )
    return {
        "resolved_fewshot_db": fewshot_db_path,
        "fewshot_pool_resolution": fewshot_pool_resolution,
        "fewshot_pool_audit": fewshot_audit,
        "fewshot_pool_total_examples": fewshot_pool_total_examples,
        "fewshot_pool_verified_examples": fewshot_pool_verified_examples,
        "fewshot_pool_formal_ready": fewshot_pool_formal_ready,
        "formal_assets": formal_assets,
        "source_fingerprint": source_fingerprint,
        "config_fingerprint": config_fingerprint,
        "script_fingerprint": script_fingerprint,
        "source_rows": source_rows,
        "pool": pool,
        "pool_stats": pool_stats,
        "a_tier_fingerprint": a_tier_fingerprint,
        "length_limit_stats": length_limit_stats,
        "real_subject_distribution": real_subject_distribution,
        "bertscorer": bertscorer,
    }


def _apply_prepared_context(args: argparse.Namespace, prepared_context: dict[str, Any]) -> None:
    resolved_fewshot_db = safe_strip(prepared_context.get("resolved_fewshot_db", ""))
    if resolved_fewshot_db:
        args.fewshot_db = resolved_fewshot_db
    args._fewshot_pool_resolution = dict(prepared_context.get("fewshot_pool_resolution", {}))
    args._fewshot_pool_audit = dict(prepared_context.get("fewshot_pool_audit", {}))
    args._fewshot_pool_total_examples = int(prepared_context.get("fewshot_pool_total_examples", 0))
    args._fewshot_pool_verified_examples = int(prepared_context.get("fewshot_pool_verified_examples", 0))
    args._fewshot_pool_formal_ready = bool(prepared_context.get("fewshot_pool_formal_ready", False))
    args._formal_assets = dict(prepared_context.get("formal_assets", {}))
    length_limit_stats = dict(prepared_context.get("length_limit_stats", {}))
    args._final_strong_relaxed_length_limit = int(
        length_limit_stats.get("p95", length_limit_stats.get("p90", 0))
    )


def _normalize_prepared_pool_rows(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in pool:
        payload = dict(row)
        git_diff = str(payload.get("git_diff") or "")
        blocks = list(payload.get("blocks") or [])
        if not blocks and git_diff:
            blocks = split_file_blocks(git_diff)
        file_paths = [
            normalize_diff_path(block.get("file_path", ""))
            for block in blocks
            if safe_strip(block.get("file_path", ""))
        ]
        if not file_paths:
            file_paths = [
                normalize_diff_path(path)
                for path in payload.get("file_paths", [])
                if safe_strip(path)
            ]
        if not file_paths:
            file_paths = [
                normalize_diff_path(path)
                for path in payload.get("file_path_set", set())
                if safe_strip(path)
            ]
        path_events = dict(payload.get("path_events") or {})
        path_events.setdefault("touched_paths", list(file_paths))
        path_events.setdefault("deleted_paths", [])
        path_events.setdefault("added_paths", [])
        path_events.setdefault("rename_pairs", [])
        path_events.setdefault("copy_pairs", [])
        payload["blocks"] = blocks
        payload["file_paths"] = list(file_paths)
        payload["file_path_set"] = set(payload.get("file_path_set", set()) or set(file_paths))
        payload["module_set"] = set(payload.get("module_set", set()) or infer_module_set(file_paths))
        payload["path_events"] = path_events
        payload["tier"] = safe_strip(payload.get("tier")) or "A"
        payload["manual_label"] = safe_strip(payload.get("manual_label")) or "A"
        payload["source_confidence"] = parse_optional_float(payload.get("source_confidence"), default=1.0)
        payload["file_count"] = int(payload.get("file_count", len(file_paths)) or len(file_paths))
        payload["changed_lines"] = int(payload.get("changed_lines", estimate_changed_lines(git_diff)) or 0)
        payload["commit_message"] = safe_strip(payload.get("commit_message", payload.get("message", "")))
        payload["subject"] = safe_strip(payload.get("subject")) or first_nonempty_line(payload["commit_message"])
        normalized_rows.append(payload)
    return normalized_rows


def run_single(
    args: argparse.Namespace,
    enforce_gates: bool = True,
    prepared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行单个固定 k 批次的完整 Step2 样本构建流程。

    完整流程概述：
    1. 设置全局随机种子，确保可复现
    2. 解析 few-shot pool（如果 message stage 启用）
    3. 加载源 CSV 并构建 A-tier 源数据池
    4. 计算 subject 长度限制（P90）
    5. 构建同仓库 k-intent 候选组并选择样本
    6. 物化样本（生成 synthetic diff）
    7. 执行 source pair precheck
    8. （可选）执行 message 生成阶段：
       a. 检索 few-shot 示例
       b. 调用 LLM 生成 synthetic subject（含修复）
       c. 使用 BERTScore 计算 coverage/faithfulness
       d. 校准阈值并分配 pass/fallback/reject 状态
       e. 评估 message gate
    9. 写出所有输出文件（samples, index, summary, metadata）
    10. 检查 gate 是否通过

    Args:
        args: 解析后的命令行参数
        enforce_gates: 是否强制执行 gate 检查（sweep 模式下由外层控制）

    Returns:
        包含运行结果摘要的字典（intent_k, output_dir, message_metrics 等）
    """
    # 设置全局随机种子，确保可复现
    set_global_seed(args.seed)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_flush_every = max(0, int(getattr(args, "progress_flush_every", 0)))
    partial_artifact_paths = [
        output_dir / "synthetic_samples.partial.jsonl",
        output_dir / "synthetic_samples_precheck_rejected.partial.jsonl",
        output_dir / "run_progress.json",
    ]
    for partial_path in partial_artifact_paths:
        if partial_path.exists():
            partial_path.unlink()

    prepared = prepared_context if prepared_context is not None else prepare_run_context(args, output_dir=output_dir)
    _apply_prepared_context(args, prepared)
    source_fingerprint = prepared["source_fingerprint"]
    config_fingerprint = prepared["config_fingerprint"]
    script_fingerprint = prepared["script_fingerprint"]
    source_rows = prepared["source_rows"]
    pool = _normalize_prepared_pool_rows(prepared["pool"])
    pool_stats = prepared["pool_stats"]
    a_tier_fingerprint = prepared["a_tier_fingerprint"]
    length_limit_stats = prepared["length_limit_stats"]
    length_limit = int(length_limit_stats["p90"])
    length_limit_source = str(length_limit_stats["source"])
    real_subject_distribution = prepared["real_subject_distribution"]

    selected_pairs_manifest_path = safe_strip(getattr(args, "selected_pairs_manifest", ""))
    selected_pairs_plan_path = safe_strip(getattr(args, "selected_pairs_jsonl", ""))
    if selected_pairs_plan_path:
        plan_records = load_selected_pairs_plan_jsonl(Path(selected_pairs_plan_path))
        selected_pairs = materialize_selected_pairs_from_plan_records(plan_records, pool)
        selected_pairs_manifest_payload: dict[str, Any] = {}
        if selected_pairs_manifest_path:
            selected_pairs_manifest_payload = json.loads(Path(selected_pairs_manifest_path).read_text(encoding="utf-8"))
        pair_pool_size = int(
            selected_pairs_manifest_payload.get(
                "pair_pool_size_after_group_constraints",
                selected_pairs_manifest_payload.get("selected_pair_count", len(selected_pairs)),
            )
            or len(selected_pairs)
        )
        precheck_stats = dict(selected_pairs_manifest_payload.get("precheck_stats", {}) or {})
        if not precheck_stats:
            precheck_stats = {
                "mode": "selected_pairs_plan",
                "selected_pair_count": len(selected_pairs),
                "plan_path": selected_pairs_plan_path,
            }
    else:
        # 构建候选组并选择样本
        repo_pairs, precheck_stats = build_groups(
            pool,
            intent_k=args.intent_k,
            max_merged_files=args.max_merged_files,
            max_merged_lines=args.max_merged_lines,
            prefer_module_overlap=args.prefer_module_overlap,
            require_module_overlap=args.require_module_overlap,
            group_combo_attempt_cap_per_repo=args.group_combo_attempt_cap_per_repo,
            group_candidate_cap_per_repo=args.group_candidate_cap_per_repo,
            seed=args.seed,
            allow_entangled_candidates=bool(getattr(args, "allow_entangled_candidates", False)),
            max_shared_files_per_group=int(getattr(args, "max_shared_files_per_group", 0)),
            selection_quality_priority=safe_strip(getattr(args, "selection_quality_priority", "legacy")),
            selection_quality_config=args,
        )
        pair_pool_size = sum(len(items) for items in repo_pairs.values())
        selected_pairs = select_pairs(
            repo_pairs,
            target_count=args.target_count,
            repo_cap=args.repo_cap,
            type_pair_cap=args.type_pair_cap,
            require_different_type=args.require_different_type,
            seed=args.seed,
            selection_quality_priority=safe_strip(getattr(args, "selection_quality_priority", "legacy")),
            selection_min_pair_quality_weight=float(getattr(args, "selection_min_pair_quality_weight", 0.0)),
        )
    # 物化样本（生成 synthetic diff 等）
    sample_id_offset = int(getattr(args, "sample_id_offset", 0))
    samples = [
        materialize_sample(
            pair,
            sample_id=f"simple{args.intent_k}_{sample_id_offset + index:04d}",
            block_order=args.block_order,
            seed=args.seed,
        )
        for index, pair in enumerate(selected_pairs, start=1)
    ]
    difficulty_realism_runtime_config = build_difficulty_realism_runtime_config(args)
    annotate_samples_difficulty_and_realism(
        samples,
        config={
            "tau_hunk_simple": 2,
            "tau_module_simple": 1,
            "tau_file_simple": 2,
            "tau_shared_file_low": 0,
            "tau_overlap_low": 0.12,
            "tau_overlap_medium": 0.25,
            "tau_dependency_low": 0.12,
            "tau_dependency_medium": 0.25,
            "tau_same_file_hunk_entangled": 2,
            "tau_topic_high": 0.75,
            "tau_realism_low": difficulty_realism_runtime_config["tau_realism_low"],
        },
    )
    source_pair_precheck_stats = apply_source_pair_precheck_to_samples(samples, config=args, git_context=None)
    selected_pairs_fingerprint = samples_pair_fingerprint(samples)
    total_samples = len(samples)

    def maybe_flush_partial_progress(
        processed_count: int,
        *,
        last_sample: dict[str, Any] | None = None,
        status: str = "running",
        force: bool = False,
        note: str = "",
        final_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if progress_flush_every <= 0 and not force:
            return None
        if not force and processed_count > 0 and processed_count % progress_flush_every != 0 and processed_count != total_samples:
            return None
        payload = write_partial_progress_artifacts(
            output_dir,
            args,
            samples,
            processed_count=processed_count,
            total_count=total_samples,
            status=status,
            last_sample=last_sample,
            note=note,
            final_summary=final_summary,
        )
        if force or status != "completed":
            safe_print(
                "[progress] "
                f"processed={processed_count}/{total_samples} "
                f"status={status} "
                f"last_sample={payload['last_sample'].get('sample_id', '')} "
                f"gen_ok={payload['counts']['generation_success_count']} "
                f"gen_fail={payload['counts']['generation_failure_count']} "
                f"precheck_skip={payload['counts']['precheck_skip_count']}",
                flush=True,
            )
        return payload

    # 加载缓存
    generation_cache: dict[str, Any] = {}
    bertscore_cache: dict[str, Any] = {}
    if args.generation_cache_enabled:
        generation_cache = load_cache(Path(args.generation_cache_path))
    if args.bertscore_cache_enabled:
        bertscore_cache = load_cache(Path(args.bertscore_cache_path))

    # ============================================================
    # Message 生成阶段（可选）
    # ============================================================
    if args.skip_message_stage:
        # 跳过：为所有样本设置占位字段
        for sample_index, sample in enumerate(samples, start=1):
            build_message_fields_for_skipped_stage(sample)
        maybe_flush_partial_progress(
            total_samples,
            status="message_stage_skipped",
            force=True,
            note="Message stage skipped. Partial artifacts mirror placeholder fields before final outputs are written.",
        )
        threshold_payload = {
            "message_threshold_source": "skipped",
            "threshold_method": "skipped",
            "t_reject": 0.0,
            "t_pass": 0.0,
            "detail": {"reason": "message_stage_skipped"},
        }
        message_metrics = compute_message_metrics(
            samples,
            real_subject_distribution=real_subject_distribution,
        )
        message_gate_payload = {
            "message_gate_enabled": args.enable_message_gate,
            "message_gate_passed": True,
            "message_gate_source": "disabled_for_skip_message_stage",
            "reason": "message_stage_skipped",
        }
    else:
        # 执行消息生成阶段
        bertscorer = prepared.get("bertscorer")
        if bertscorer is None:
            try:
                bertscorer = init_bertscorer(args)
            except Exception as exc:
                raise RuntimeError(
                    "Coverage scoring dependency missing. Install `bert-score` or configure a supported scorer backend. "
                    f"detail={exc}"
                ) from exc
        relaxed_length_limit = int(getattr(args, "_final_strong_relaxed_length_limit", length_limit))
        for sample_index, sample in enumerate(samples, start=1):
            if sample.get("precheck_status") == "skip":
                sample["synthetic_subject"] = ""
                sample["generation_status"] = "not_attempted_precheck_skip"
                sample["message_status"] = "not_generated_precheck_skip"
                sample["few_shot_source"] = "failed"
                sample["few_shot_retrieval_log"] = {
                    "requested_type_signature": sample.get("type_signature_canonical", sample.get("type_pair", "")),
                    "requested_types_canonical": list(sample.get("source_types_canonical", [])),
                    "intent_k": int(sample.get("intent_k", sample.get("intent_count", 0))),
                    "few_shot_requested_k": int(args.few_shot_k),
                    "query_levels_attempted": [],
                    "examples_found_per_level": {},
                    "selected_example_ids": [],
                    "selected_example_type_signatures": [],
                    "selected_example_repos": [],
                    "retrieval_status": "failed",
                    "failure_reason": "not_attempted_precheck_skip",
                }
                sample["message_scores"] = {
                    "format": 0,
                    "coverage_r_list": [],
                    "coverage_by_source": [],
                    "coverage_min_r": 0.0,
                    "coverage_min": 0.0,
                    "coverage_avg_r": 0.0,
                    "coverage_avg": 0.0,
                    "coverage_balance": 0.0,
                    "faithfulness_p": 0.0,
                    "artifact_hit_count": 0,
                    "artifact_score": 0.0,
                    "relevance_score": 0.0,
                    "style_score": 0.0,
                    "generic_phrase_hit": 0,
                    "token_count": 0,
                    "imperative_head": 0,
                    "message_quality_weight": 0.0,
                    "bertscore_compute_invalid": 0,
                    "bertscore_error": "skipped_by_source_pair_precheck",
                }
                sample["message_meta"] = {
                    "generator_provider": args.generator_provider,
                    "generator_model": args.generator_model,
                    "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
                    "generator_mode": getattr(args, "generator_mode", "api"),
                    "scorer_backend": args.scorer_backend,
                    "bertscore_model": args.bertscore_model,
                    "prompt_version": args.prompt_version,
                    "generation_success": False,
                    "generation_skipped": True,
                    "generation_failure_reason": "source_pair_precheck_skip",
                    "formal_run": bool(args.formal_run),
                    "run_valid_for_paper": bool(args.run_valid_for_paper),
                    "llm_generation_attempted": False,
                    "generation_attempts": 0,
                    "compress_attempts": 0,
                    "rewrite_attempts": 0,
                    "final_strong_compress_attempts": 0,
                    "generation_trace": [],
                    "length_limit": length_limit,
                    "length_limit_base": length_limit,
                    "length_limit_relaxed_candidate": relaxed_length_limit,
                    "length_limit_relaxed_used": False,
                    "length_limit_source": length_limit_source,
                    "few_shot_ids": [],
                    "few_shot_source": "failed",
                    "retrieval_backend": "skipped",
                    "retrieval_query_version": args.retrieval_query_version,
                    "retrieval_params": {
                        "type_signature_canonical": sample["type_signature_canonical"],
                        "repo": sample["repo"],
                        "k": args.few_shot_k,
                        "seed": args.seed,
                    },
                    "retrieval_cmd": "",
                    "retrieval_result_count": 0,
                    "retrieval_error": "source_pair_precheck_skip",
                    "few_shot_retrieval_log": sample["few_shot_retrieval_log"],
                    "request_sha_chain": [],
                    "generation_cache_hit_count": 0,
                    "message_error_type": "source_pair_precheck_skip",
                    "score_meta": {
                        "coverage_cache_keys": [],
                        "faithfulness_cache_key": "",
                        "format_detail": {
                            "format": 0,
                            "nonempty": 0,
                            "single_line": 0,
                            "char_len": 0,
                            "len_ok": 0,
                            "label_template_hit": 0,
                            "bullet_hit": 0,
                            "numbered_list_hit": 0,
                            "prefix_count": 0,
                            "dual_prefix_hit": 0,
                            "mechanical_semicolon_hit": 0,
                        },
                        "pattern_flags": detect_message_pattern_flags(""),
                        "surface_features": subject_surface_features(""),
                        "score_skipped_reason": "source_pair_precheck_skip",
                    },
                    **make_diff_evidence_meta(sample),
                }
                sample["final_sample_weight"] = 0.0
                maybe_flush_partial_progress(
                    sample_index,
                    last_sample=sample,
                    note="Partial artifacts updated after a source-pair precheck skip.",
                )
                continue
            # 1. 检索 few-shot 示例
            fewshot_info = retrieve_fewshot_examples(
                db_path=args.fewshot_db,
                table=args.fewshot_table,
                type_signature_canonical=sample["type_signature_canonical"],
                current_repo=sample["repo"],
                k=args.few_shot_k,
                seed=args.seed,
                current_source_shas={safe_strip(source.get("sha")) for source in sample.get("sources", [])},
            )
            sample["few_shot_retrieval_log"] = fewshot_info["few_shot_retrieval_log"]
            selected_count = int(fewshot_info.get("retrieval_result_count", 0))
            sample["few_shot_retrieval_log"]["few_shot_selected_count"] = selected_count
            sample["few_shot_retrieval_log"]["few_shot_requested_k"] = int(args.few_shot_k)
            min_examples_required = int(getattr(args, "few_shot_min_examples_per_sample", 1))
            if (
                bool(getattr(args, "few_shot_warn_if_below_requested", True))
                and selected_count < int(args.few_shot_k)
                and fewshot_info["retrieval_status"] != "failed"
            ):
                sample["few_shot_retrieval_log"]["below_requested_warning"] = True
            min_examples_not_met = selected_count < min_examples_required
            if min_examples_not_met:
                sample["few_shot_retrieval_log"]["few_shot_min_examples_required"] = min_examples_required
                sample["few_shot_retrieval_log"]["few_shot_selected_count"] = selected_count
                sample["few_shot_retrieval_log"]["failure_reason"] = "few_shot_min_examples_not_met"
            if fewshot_info["retrieval_status"] == "failed" or min_examples_not_met:
                sample["synthetic_subject"] = ""
                sample["generation_status"] = "generation_failed"
                sample["message_status"] = "not_generated_generation_failed"
                sample["few_shot_source"] = "failed"
                sample["message_scores"] = {
                    "format": 0,
                    "coverage_r_list": [],
                    "coverage_by_source": [],
                    "coverage_min_r": 0.0,
                    "coverage_min": 0.0,
                    "coverage_avg_r": 0.0,
                    "coverage_avg": 0.0,
                    "coverage_balance": 0.0,
                    "faithfulness_p": 0.0,
                    "artifact_hit_count": 0,
                    "artifact_score": 0.0,
                    "relevance_score": 0.0,
                    "style_score": 0.0,
                    "generic_phrase_hit": 0,
                    "token_count": 0,
                    "imperative_head": 0,
                    "message_quality_weight": 0.0,
                    "bertscore_compute_invalid": 0,
                    "bertscore_error": "fewshot_retrieval_failed",
                }
                sample["message_meta"] = {
                    "generator_provider": args.generator_provider,
                    "generator_model": args.generator_model,
                    "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
                    "generator_mode": getattr(args, "generator_mode", "api"),
                    "scorer_backend": args.scorer_backend,
                    "bertscore_model": args.bertscore_model,
                    "prompt_version": args.prompt_version,
                    "generation_success": False,
                    "generation_skipped": False,
                    "generation_failure_reason": (
                        "few_shot_min_examples_not_met" if min_examples_not_met else "fewshot_retrieval_failed"
                    ),
                    "formal_run": bool(args.formal_run),
                    "run_valid_for_paper": bool(args.run_valid_for_paper),
                    "llm_generation_attempted": False,
                    "generation_attempts": 0,
                    "compress_attempts": 0,
                    "rewrite_attempts": 0,
                    "final_strong_compress_attempts": 0,
                    "generation_trace": [],
                    "length_limit": length_limit,
                    "length_limit_base": length_limit,
                    "length_limit_relaxed_candidate": relaxed_length_limit,
                    "length_limit_relaxed_used": False,
                    "length_limit_source": length_limit_source,
                    "few_shot_ids": [],
                    "few_shot_source": "failed",
                    "retrieval_backend": fewshot_info["retrieval_backend"],
                    "retrieval_query_version": args.retrieval_query_version,
                    "retrieval_params": {
                        "type_signature_canonical": sample["type_signature_canonical"],
                        "repo": sample["repo"],
                        "k": args.few_shot_k,
                        "seed": args.seed,
                    },
                    "retrieval_cmd": (
                        "python code/retrieve_fewshot.py "
                        f"--db {args.fewshot_db} "
                        f"--table {args.fewshot_table} "
                        f"--type-pair {sample['type_signature_canonical']} "
                        f"--repo {sample['repo']} "
                        f"--k {args.few_shot_k} "
                        f"--seed {args.seed} "
                        f"--query-version {args.retrieval_query_version}"
                    ),
                    "retrieval_result_count": fewshot_info["retrieval_result_count"],
                    "retrieval_error": (
                        "few_shot_min_examples_not_met"
                        if min_examples_not_met
                        else fewshot_info["retrieval_error"]
                    ),
                    "few_shot_retrieval_log": sample["few_shot_retrieval_log"],
                    "request_sha_chain": [],
                    "generation_cache_hit_count": 0,
                    "message_error_type": (
                        "few_shot_min_examples_not_met" if min_examples_not_met else "fewshot_retrieval_failed"
                    ),
                    "score_meta": {
                        "coverage_cache_keys": [],
                        "faithfulness_cache_key": "",
                        "format_detail": {
                            "format": 0,
                            "nonempty": 0,
                            "single_line": 0,
                            "char_len": 0,
                            "len_ok": 0,
                            "label_template_hit": 0,
                            "bullet_hit": 0,
                            "numbered_list_hit": 0,
                            "prefix_count": 0,
                            "dual_prefix_hit": 0,
                            "mechanical_semicolon_hit": 0,
                        },
                        "pattern_flags": detect_message_pattern_flags(""),
                        "surface_features": subject_surface_features(""),
                        "score_skipped_reason": "fewshot_retrieval_failed",
                    },
                    **make_diff_evidence_meta(sample),
                }
                sample["final_sample_weight"] = 0.0
                maybe_flush_partial_progress(
                    sample_index,
                    last_sample=sample,
                    note="Partial artifacts updated after a few-shot retrieval failure.",
                )
                continue
            # 2. 生成 synthetic subject（含修复）
            generation_result = generate_subject_with_repair(
                sample=sample,
                args=args,
                length_limit=length_limit,
                fewshot_info=fewshot_info,
                generation_cache=generation_cache,
            )
            if generation_result.get("provider_blocking_error", False):
                persist_runtime_caches(args, generation_cache, bertscore_cache)
                provider_error_type = safe_strip(generation_result.get("provider_blocking_error_type", ""))
                provider_error_detail = safe_strip(generation_result.get("provider_blocking_error_detail", ""))
                provider_guidance = provider_error_guidance(provider_error_type)
                maybe_flush_partial_progress(
                    sample_index - 1,
                    last_sample=samples[sample_index - 2] if sample_index >= 2 else None,
                    status="provider_blocked",
                    force=True,
                    note=(
                        "Provider blocked mid-shard. Partial artifacts contain only the fully processed prefix; "
                        "current sample has not been committed."
                    ),
                )
                raise RuntimeError(
                    "Generator blocked by provider hard failure: "
                    f"error_type={provider_error_type or 'unknown'}; "
                    f"guidance={provider_guidance or 'provider_request_blocked'}; "
                    f"detail={provider_error_detail or 'no_detail'}"
                )
            applied_length_limit = int(generation_result.get("effective_length_limit", length_limit))
            synthetic_subject = generation_result["synthetic_subject"]
            generation_success = bool(generation_result.get("generation_success", False))
            generation_status = "generated" if generation_success else "generation_failed"
            # 3. 生成失败时，不进入后续评分流程（硬隔离）
            if generation_success:
                try:
                    message_scores, score_meta = compute_message_scores(
                        sample=sample,
                        synthetic_subject=synthetic_subject,
                        length_limit=applied_length_limit,
                        args=args,
                        bertscore_cache=bertscore_cache,
                        bertscorer=bertscorer,
                    )
                    if int(message_scores.get("bertscore_compute_invalid", 0)) == 1:
                        generation_status = "judge_failed"
                except Exception as exc:
                    generation_status = "scoring_failed"
                    generation_success = False
                    synthetic_subject = ""
                    message_scores = {
                        "format": 0,
                        "coverage_r_list": [],
                        "coverage_by_source": [],
                        "coverage_min_r": 0.0,
                        "coverage_min": 0.0,
                        "coverage_avg_r": 0.0,
                        "coverage_avg": 0.0,
                        "coverage_balance": 0.0,
                        "faithfulness_p": 0.0,
                        "artifact_hit_count": 0,
                        "artifact_score": 0.0,
                        "relevance_score": 0.0,
                        "style_score": 0.0,
                        "generic_phrase_hit": 0,
                        "token_count": 0,
                        "imperative_head": 0,
                        "message_quality_weight": 0.0,
                        "bertscore_compute_invalid": 1,
                        "bertscore_error": f"scoring_failed:{exc}",
                    }
                    score_meta = {
                        "coverage_cache_keys": [],
                        "faithfulness_cache_key": "",
                        "format_detail": {
                            "format": 0,
                            "nonempty": 0,
                            "single_line": 0,
                            "char_len": 0,
                            "len_ok": 0,
                            "label_template_hit": 0,
                            "bullet_hit": 0,
                            "numbered_list_hit": 0,
                            "prefix_count": 0,
                            "dual_prefix_hit": 0,
                            "mechanical_semicolon_hit": 0,
                        },
                        "pattern_flags": detect_message_pattern_flags(""),
                        "surface_features": subject_surface_features(""),
                        "score_skipped_reason": "scoring_failed",
                    }
            else:
                message_scores = {
                    "format": 0,
                    "coverage_r_list": [],
                    "coverage_by_source": [],
                    "coverage_min_r": 0.0,
                    "coverage_min": 0.0,
                    "coverage_avg_r": 0.0,
                    "coverage_avg": 0.0,
                    "coverage_balance": 0.0,
                    "faithfulness_p": 0.0,
                    "artifact_hit_count": 0,
                    "artifact_score": 0.0,
                    "relevance_score": 0.0,
                    "style_score": 0.0,
                    "generic_phrase_hit": 0,
                    "token_count": 0,
                    "imperative_head": 0,
                    "message_quality_weight": 0.0,
                    "bertscore_compute_invalid": 0,
                    "bertscore_error": "generation_failed_or_quality_not_pass",
                }
                score_meta = {
                    "coverage_cache_keys": [],
                    "faithfulness_cache_key": "",
                    "format_detail": {
                        "format": 0,
                        "nonempty": 0,
                        "single_line": 0,
                        "char_len": 0,
                        "len_ok": 0,
                        "label_template_hit": 0,
                        "bullet_hit": 0,
                        "numbered_list_hit": 0,
                        "prefix_count": 0,
                        "dual_prefix_hit": 0,
                        "mechanical_semicolon_hit": 0,
                    },
                    "pattern_flags": detect_message_pattern_flags(""),
                    "surface_features": subject_surface_features(""),
                    "score_skipped_reason": "generation_failed",
                }

            # 4. 更新样本信息
            sample["synthetic_subject"] = synthetic_subject
            sample["generation_status"] = generation_status
            sample["few_shot_source"] = fewshot_info["few_shot_source"]
            sample["message_scores"] = message_scores
            sample["message_meta"] = {
                "generator_provider": args.generator_provider,
                "generator_model": args.generator_model,
                "generator_thinking_type": getattr(args, "generator_thinking_type", DEFAULT_GENERATOR_THINKING_TYPE),
                "generator_mode": getattr(args, "generator_mode", "api"),
                "scorer_backend": args.scorer_backend,
                "bertscore_model": args.bertscore_model,
                "prompt_version": args.prompt_version,
                "generation_success": generation_success,
                "generation_skipped": False,
                "formal_run": bool(args.formal_run),
                "run_valid_for_paper": bool(args.run_valid_for_paper),
                "llm_generation_attempted": True,
                "generation_failure_reason": (
                    "judge_failed"
                    if generation_status == "judge_failed"
                    else (
                        "scoring_failed"
                        if generation_status == "scoring_failed"
                        else (
                            ""
                            if generation_success
                            else generation_result.get("message_error_type", "generation_failed")
                        )
                    )
                ),
                "generation_attempts": generation_result["generation_attempts"],
                "compress_attempts": generation_result["compress_attempts"],
                "rewrite_attempts": generation_result["rewrite_attempts"],
                "final_strong_compress_attempts": generation_result.get("final_strong_compress_attempts", 0),
                "generation_trace": generation_result.get("generation_trace", []),
                "length_limit": applied_length_limit,
                "length_limit_base": length_limit,
                "length_limit_relaxed_candidate": relaxed_length_limit,
                "length_limit_relaxed_used": bool(applied_length_limit > length_limit),
                "length_limit_source": length_limit_source,
                "few_shot_ids": [example["example_id"] for example in fewshot_info["examples"]],
                "few_shot_source": fewshot_info["few_shot_source"],
                "retrieval_backend": fewshot_info["retrieval_backend"],
                "retrieval_query_version": args.retrieval_query_version,
                "retrieval_params": {
                    "type_signature_canonical": sample["type_signature_canonical"],
                    "repo": sample["repo"],
                    "k": args.few_shot_k,
                    "seed": args.seed,
                },
                "retrieval_cmd": (
                    ""
                    if not args.fewshot_db
                    else (
                        "python code/retrieve_fewshot.py "
                        f"--db {args.fewshot_db} "
                        f"--table {args.fewshot_table} "
                        f"--type-pair {sample['type_signature_canonical']} "
                        f"--repo {sample['repo']} "
                        f"--k {args.few_shot_k} "
                        f"--seed {args.seed} "
                        f"--query-version {args.retrieval_query_version}"
                    )
                ),
                "retrieval_result_count": fewshot_info["retrieval_result_count"],
                "retrieval_error": fewshot_info["retrieval_error"],
                "few_shot_retrieval_log": sample["few_shot_retrieval_log"],
                "request_sha_chain": generation_result["request_sha_chain"],
                "generation_cache_hit_count": generation_result["cache_hit_count"],
                "message_error_type": (
                    "judge_failed"
                    if generation_status == "judge_failed"
                    else (
                        "scoring_failed"
                        if generation_status == "scoring_failed"
                        else generation_result["message_error_type"]
                    )
                ),
                "score_meta": score_meta,
                **make_diff_evidence_meta(sample),
            }
            maybe_flush_partial_progress(
                sample_index,
                last_sample=sample,
            )

        # 5. 校准阈值并分配状态（pass/fallback/reject）
        values = [
            float(row["message_scores"]["message_quality_weight"])
            for row in samples
            if row["message_scores"]["format"] == 1 and row["message_scores"]["bertscore_compute_invalid"] == 0
        ]
        threshold_payload = calibrate_message_thresholds(values, method=args.threshold_method)
        assign_message_status_and_weight(samples, threshold_payload)
        message_metrics = compute_message_metrics(
            samples,
            real_subject_distribution=real_subject_distribution,
        )
        # 6. 评估 message gate
        reference_rows = load_message_gate_reference(args.message_gate_reference)
        message_gate_payload = evaluate_message_gate(message_metrics, reference_rows, args)

    # 保存缓存
    persist_runtime_caches(args, generation_cache, bertscore_cache)

    # ============================================================
    # 输出阶段
    # ============================================================
    # 筛选 step3 就绪的样本（非 reject）
    step3_ready_samples = [
        row
        for row in samples
        if is_step3_ready_sample(row)
    ]
    difficulty_realism_summary = summarize_difficulty_realism(
        samples,
        config={"tau_realism_low": difficulty_realism_runtime_config["tau_realism_low"]},
    )
    step3_ready_fingerprint = samples_pair_fingerprint(step3_ready_samples)
    required_samples = math.ceil(args.target_count * args.min_target_ratio)
    target_gate_passed = len(step3_ready_samples) >= required_samples

    # 写入输出文件
    write_jsonl(output_dir / "synthetic_samples.jsonl", samples)
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", step3_ready_samples)
    write_jsonl(
        output_dir / "synthetic_samples_precheck_rejected.jsonl",
        [row for row in samples if row.get("precheck_status") == "skip"],
    )
    diff_evidence_flags = [
        bool(flag)
        for row in samples
        for flag in row.get("intent_diff_evidence_available", [])
    ]
    diff_evidence_available_rate = (
        round(sum(1 for flag in diff_evidence_flags if flag) / len(diff_evidence_flags), 6)
        if diff_evidence_flags
        else 0.0
    )
    write_message_gate_report(
        Path(args.message_gate_report_path),
        {
            **message_gate_payload,
            "formal_protocol_version": FORMAL_PROTOCOL_VERSION,
            "run_purpose": safe_strip(getattr(args, "run_purpose", "")),
            "run_valid_for_paper": bool(args.run_valid_for_paper),
            "protocol_violations": list(getattr(args, "protocol_violations", [])),
            "target_gate_passed": bool(target_gate_passed),
            "step3_ready_count": int(len(step3_ready_samples)),
            "sampled_candidate_count": int(len(samples)),
            "fewshot_pool_total_examples": int(getattr(args, "_fewshot_pool_total_examples", 0)),
            "fewshot_pool_verified_examples": int(getattr(args, "_fewshot_pool_verified_examples", 0)),
            "fewshot_pool_formal_ready": bool(getattr(args, "_fewshot_pool_formal_ready", False)),
            "fewshot_pool_audit": dict(getattr(args, "_fewshot_pool_audit", {})),
            "fewshot_eligibility_policy": DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
            "diff_evidence_card_version": DIFF_EVIDENCE_CARD_VERSION,
            "diff_evidence_policy": DIFF_EVIDENCE_POLICY,
            "diff_evidence_required_for_formal": bool(DIFF_EVIDENCE_REQUIRED_FOR_FORMAL),
            "diff_evidence_available_rate": diff_evidence_available_rate,
            "difficulty_realism_summary": difficulty_realism_summary,
        },
    )
    write_index_csv(output_dir / "synthetic_index.csv", samples)
    write_summary(
        output_dir / "summary.md",
        samples=samples,
        intent_k=args.intent_k,
        pool_size=len(pool),
        pair_pool_size=pair_pool_size,
        seed=args.seed,
        target_count=args.target_count,
        min_target_ratio=args.min_target_ratio,
        required_samples=required_samples,
        target_gate_passed=target_gate_passed,
        repo_cap=args.repo_cap,
        type_pair_cap=args.type_pair_cap,
        max_merged_files=args.max_merged_files,
        max_merged_lines=args.max_merged_lines,
        require_different_type=args.require_different_type,
        selection_quality_priority=safe_strip(getattr(args, "selection_quality_priority", "legacy")),
        selection_min_pair_quality_weight=float(getattr(args, "selection_min_pair_quality_weight", 0.0)),
        prefer_module_overlap=args.prefer_module_overlap,
        require_module_overlap=args.require_module_overlap,
        block_order=args.block_order,
        message_metrics=message_metrics,
        message_gate_payload=message_gate_payload,
        precheck_stats=precheck_stats,
        length_limit=length_limit,
        run_purpose=safe_strip(getattr(args, "run_purpose", "")),
        run_valid_for_paper=bool(args.run_valid_for_paper),
        protocol_violations=list(getattr(args, "protocol_violations", [])),
        difficulty_realism_summary=difficulty_realism_summary,
        difficulty_realism_runtime_config=difficulty_realism_runtime_config,
    )
    write_review(output_dir / "review_samples.md", samples[: args.review_samples])
    write_run_metadata(
        output_dir / "run_metadata.json",
        args=args,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        script_fingerprint=script_fingerprint,
        a_tier_fingerprint=a_tier_fingerprint,
        selected_pairs_fingerprint=selected_pairs_fingerprint,
        step3_ready_fingerprint=step3_ready_fingerprint,
        length_limit_stats=length_limit_stats,
        pool_stats=pool_stats,
        pair_pool_size=pair_pool_size,
        samples=samples,
        required_samples=required_samples,
        target_gate_passed=target_gate_passed,
        threshold_payload=threshold_payload,
        message_metrics=message_metrics,
        message_gate_payload=message_gate_payload,
        precheck_stats=precheck_stats,
        source_pair_precheck_stats=source_pair_precheck_stats,
        difficulty_realism_summary=difficulty_realism_summary,
        difficulty_realism_runtime_config=difficulty_realism_runtime_config,
    )
    maybe_flush_partial_progress(
        total_samples,
        last_sample=samples[-1] if samples else None,
        status="completed",
        force=True,
        note="Shard completed. Final outputs are now stable and consistent with run_metadata.json.",
        final_summary={
            "step3_ready_count": int(len(step3_ready_samples)),
            "generated_count": int(len(samples)),
            "target_gate_passed": bool(target_gate_passed),
            "message_gate_passed": bool(message_gate_payload.get("message_gate_passed", True)),
            "threshold_method": safe_strip(threshold_payload.get("threshold_method", "")),
            "run_metadata_json": str(output_dir / "run_metadata.json"),
        },
    )

    # ============================================================
    # Gate 检查
    # ============================================================
    # 检查 gate（single-run 默认强校验；sweep 模式由外层决定是否停止）
    if enforce_gates:
        if not target_gate_passed:
            raise RuntimeError(
                f"Target gate failed: step3_ready={len(step3_ready_samples)}, generated={len(samples)}, required={required_samples}, "
                f"target_count={args.target_count}, min_target_ratio={args.min_target_ratio:.3f}"
            )
        if args.enable_message_gate and not bool(message_gate_payload.get("message_gate_passed", False)):
            raise RuntimeError(
                "Message gate failed: "
                f"source={message_gate_payload.get('message_gate_source')} "
                f"reason={message_gate_payload.get('reason')}"
            )

    # 打印摘要信息
    safe_print(f"source_pool={len(pool)}")
    safe_print(
        "premerge_precheck="
        f"{precheck_stats.get('total_checked', 0)} checked, "
        f"{precheck_stats.get('passed', 0)} passed, "
        f"{precheck_stats.get('rejected', 0)} rejected"
    )
    safe_print(
        "source_pair_precheck="
        f"{message_metrics.get('precheck_pass_count', 0)} pass, "
        f"{message_metrics.get('precheck_warn_count', 0)} warn, "
        f"{message_metrics.get('precheck_skip_count', 0)} skip"
    )
    safe_print(f"eligible_group_pool={pair_pool_size}")
    safe_print(f"selected_groups={len(selected_pairs)}")
    safe_print(f"step3_ready_samples={len(step3_ready_samples)}")
    safe_print((output_dir / "summary.md").as_posix())
    safe_print((output_dir / "run_metadata.json").as_posix())
    return {
        "intent_k": int(args.intent_k),
        "output_dir": str(output_dir),
        "run_purpose": safe_strip(getattr(args, "run_purpose", "")),
        "formal_run": bool(args.formal_run),
        "run_valid_for_paper": bool(args.run_valid_for_paper),
        "protocol_violations": list(getattr(args, "protocol_violations", [])),
        "target_gate_passed": bool(target_gate_passed),
        "message_gate_passed": bool(message_gate_payload.get("message_gate_passed", True)),
        "message_metrics": message_metrics,
        "step3_ready_count": int(len(step3_ready_samples)),
        "generated_count": int(len(samples)),
        "precheck_stats": precheck_stats,
        "difficulty_realism_summary": difficulty_realism_summary,
    }


def is_quality_degraded(previous_run: dict[str, Any], current_run: dict[str, Any]) -> tuple[bool, str]:
    """判断当前 k 批次是否相对上一个批次出现明显质量下降。

    判定条件（需同时满足）：
    1. target_gate 或 message_gate 失败（直接判定）
    2. 四项核心指标同时朝"变差方向"移动：
       - avg_coverage_non_reject 下降
       - avg_faithfulness_non_reject 下降
       - message_pass_rate 下降
       - message_reject_rate 上升

    用于 k-sweep 模式中决定是否提前终止 k 递增实验。
    """
    if not current_run["target_gate_passed"]:
        return True, "target_gate_failed"
    if not current_run["message_gate_passed"]:
        return True, "message_gate_failed"

    prev_metrics = previous_run.get("message_metrics", {})
    cur_metrics = current_run.get("message_metrics", {})
    # 无需手工阈值：仅当核心指标同时朝“变差方向”移动时判定明显下降。
    coverage_down = float(cur_metrics.get("avg_coverage_non_reject", 0.0)) < float(
        prev_metrics.get("avg_coverage_non_reject", 0.0)
    )
    faithfulness_down = float(cur_metrics.get("avg_faithfulness_non_reject", 0.0)) < float(
        prev_metrics.get("avg_faithfulness_non_reject", 0.0)
    )
    pass_rate_down = float(cur_metrics.get("message_pass_rate", 0.0)) < float(
        prev_metrics.get("message_pass_rate", 0.0)
    )
    reject_rate_up = float(cur_metrics.get("message_reject_rate", 0.0)) > float(
        prev_metrics.get("message_reject_rate", 0.0)
    )
    if coverage_down and faithfulness_down and pass_rate_down and reject_rate_up:
        return True, "coverage_faithfulness_passrate_down_and_rejectrate_up"
    return False, "not_degraded"


def write_k_sweep_report(path: Path, records: list[dict[str, Any]], stop_reason: str) -> None:
    """写入 k 递增批次实验的 Markdown 报告。

    报告包含：
    - 停止原因（如 degraded_at_k_3:coverage_faithfulness_passrate_down_and_rejectrate_up）
    - 各 k 值的生成数、step3 就绪数、pass_rate、reject_rate、
      avg_coverage_non_reject、avg_faithfulness_non_reject
    """
    lines = [
        "# Step2 Intent-K Sweep Report",
        "",
        f"- stop_reason: `{stop_reason}`",
        "",
        "| k | generated | step3_ready | pass_rate | reject_rate | avg_coverage_non_reject | avg_faithfulness_non_reject | output_dir |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        metrics = record.get("message_metrics", {})
        lines.append(
            "| "
            f"{record.get('intent_k')} | "
            f"{record.get('generated_count')} | "
            f"{record.get('step3_ready_count')} | "
            f"{metrics.get('message_pass_rate', 0.0):.4f} | "
            f"{metrics.get('message_reject_rate', 0.0):.4f} | "
            f"{metrics.get('avg_coverage_non_reject', 0.0):.4f} | "
            f"{metrics.get('avg_faithfulness_non_reject', 0.0):.4f} | "
            f"{record.get('output_dir')} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """入口函数：支持单 k 批次或 k 递增 sweep 两种运行模式。

    运行模式由 --k-sweep-max 和 --intent-k 的关系决定：
    - k_sweep_max == intent_k: 单批次模式，直接执行 run_single()
    - k_sweep_max > intent_k: sweep 模式，从 intent_k 递增到 k_sweep_max，
      每次运行后检查质量是否下降，下降则提前终止

    sweep 模式下每个 k 的输出写入 output_dir/k_{k}/ 子目录，
    最终生成 k_sweep_report.md 和 k_sweep_results.json 汇总报告。
    """
    args = parse_args()
    if bool(getattr(args, "preflight", False)):
        report = run_preflight(args)
        if not bool(report.get("passed", False)):
            raise SystemExit(1)
        return
    if args.k_sweep_max == args.intent_k:
        run_single(args, enforce_gates=True)
        return

    base_output_dir = Path(args.output_dir)
    base_generation_cache_default = str(base_output_dir / "cache" / "generation_cache.json")
    base_bertscore_cache_default = str(base_output_dir / "cache" / "bertscore_cache.json")
    records: list[dict[str, Any]] = []
    stop_reason = "reached_k_sweep_max"
    previous_run: dict[str, Any] | None = None
    for k in range(int(args.intent_k), int(args.k_sweep_max) + 1):
        run_args = argparse.Namespace(**vars(args))
        run_args.intent_k = k
        run_output_dir = base_output_dir / f"k_{k}"
        run_args.output_dir = str(run_output_dir)
        if args.generation_cache_path == base_generation_cache_default:
            run_args.generation_cache_path = str(run_output_dir / "cache" / "generation_cache.json")
        if args.bertscore_cache_path == base_bertscore_cache_default:
            run_args.bertscore_cache_path = str(run_output_dir / "cache" / "bertscore_cache.json")
        result = run_single(run_args, enforce_gates=False)
        records.append(result)
        if previous_run is None:
            if not result["target_gate_passed"]:
                stop_reason = f"degraded_at_k_{k}:target_gate_failed"
                break
            if not result["message_gate_passed"]:
                stop_reason = f"degraded_at_k_{k}:message_gate_failed"
                break
            previous_run = result
            continue
        if previous_run is not None:
            degraded, reason = is_quality_degraded(previous_run, result)
            if degraded:
                stop_reason = f"degraded_at_k_{k}:{reason}"
                break
        previous_run = result

    sweep_json = base_output_dir / "k_sweep_results.json"
    sweep_md = base_output_dir / "k_sweep_report.md"
    sweep_json.parent.mkdir(parents=True, exist_ok=True)
    sweep_json.write_text(
        json.dumps({"stop_reason": stop_reason, "runs": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_k_sweep_report(sweep_md, records, stop_reason=stop_reason)
    safe_print(str(sweep_md))
    safe_print(str(sweep_json))


if __name__ == "__main__":
    main()
