"""
构建 message-only 校准扩充审计集

该脚本用于：
1. 统计当前 annotated_dataset 在 substantive type x label 维度上的覆盖
2. 从 prefilter 语料中分层挑选新增审计候选
3. 为后续人工审计输出包含 diff 的候选模板

设计约束：
- 只使用客观规则（类型覆盖缺口、message-only 概率排序、分位带分层）
- 不使用 top-N 保底或任何回退式覆盖逻辑
- 不修改已有标注集，只生成待审计扩充候选
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.pipeline import atomic_mining as miner


# 实质性的 commit 类型列表，用于分层分析
SUBSTANTIVE_TYPES = ("fix", "feat", "refactor", "test", "perf")
# 每种类型每种标签的默认最小样本数
DEFAULT_MIN_PER_TYPE_LABEL = 10
# 过采样因子，用于扩充候选池
DEFAULT_OVERSAMPLE_FACTOR = 4
# 分数分位带数量，用于分层抽样
DEFAULT_SCORE_BANDS = 5
# 随机种子，确保结果可复现
DEFAULT_SEED = 31
# CSV 字段大小限制
CSV_FIELD_SIZE_LIMIT = 2**31 - 1


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    主要参数:
        --annotated: 已标注数据集路径
        --prefilter: 预过滤候选数据集路径
        --commit-texts: 包含完整 commit 文本的 JSONL 文件路径
        --base-calibration: 基础校准参数文件路径
        --output: 输出的审计候选文件路径
        --min-per-type-label: 每种类型每种标签的最小数量
        --oversample-factor: 过采样因子
        --score-bands: 分数分位带数量
        --seed: 随机种子

    返回:
        解析后的命名空间对象
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--annotated",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    parser.add_argument(
        "--prefilter",
        default="../../datasets/step1/workspace/upstream_candidate_pool/prefilter_allcommits.csv",
    )
    parser.add_argument(
        "--commit-texts",
        default="../../datasets/step1/runtime_support/resolved_commit_texts.jsonl",
    )
    parser.add_argument(
        "--base-calibration",
        default="",
    )
    parser.add_argument(
        "--output",
        default="outputs/message_only_audit_expansion_candidates.csv",
    )
    parser.add_argument(
        "--min-per-type-label", type=int, default=DEFAULT_MIN_PER_TYPE_LABEL
    )
    parser.add_argument(
        "--oversample-factor", type=int, default=DEFAULT_OVERSAMPLE_FACTOR
    )
    parser.add_argument("--score-bands", type=int, default=DEFAULT_SCORE_BANDS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def load_csv_rows(path: Path) -> list[dict]:
    """
    从 CSV 文件加载行数据。

    参数:
        path: CSV 文件路径

    返回:
        行字典列表
    """
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_commit_texts(
    path: Path, wanted_shas: set[str] | None = None
) -> dict[str, dict]:
    """
    从 JSONL 文件加载 commit 文本数据。

    参数:
        path: JSONL 文件路径
        wanted_shas: 可选，仅加载指定 sha 的记录

    返回:
        sha 到 commit 数据的字典
    """
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            sha = str(payload.get("sha", "")).strip()
            if not sha:
                continue
            # 如果指定了 wanted_shas，则只加载需要的记录
            if wanted_shas is not None and sha not in wanted_shas:
                continue
            if sha:
                rows[sha] = payload
    return rows


def parse_label(raw: object) -> int | None:
    """
    解析标签值为整数。

    支持的标签格式:
    - "1", "true", "yes", "y", "single", "atomic" -> 1
    - "0", "false", "no", "n", "multi", "non-atomic" -> 0

    参数:
        raw: 原始标签值

    返回:
        解析后的整数标签 (0 或 1)，如果无法解析则返回 None
    """
    if raw in {None, ""}:
        return None
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "single", "atomic"}:
        return 1
    if value in {"0", "false", "no", "n", "multi", "non-atomic"}:
        return 0
    return None


def compute_type_label_coverage(
    rows: list[dict],
    substantive_types: tuple[str, ...] = SUBSTANTIVE_TYPES,
) -> dict[str, dict[int, int]]:
    """
    计算各类型各标签的覆盖数量。

    用于统计当前已标注数据集在不同 commit 类型和标签组合上的分布。

    参数:
        rows: 已标注的行数据
        substantive_types: 实质性 commit 类型列表

    返回:
        嵌套字典，键为 (commit_type, label)，值为计数
    """
    # 初始化覆盖统计字典，每种类型对应两种标签 (0 和 1)
    coverage: dict[str, dict[int, int]] = {
        commit_type: {0: 0, 1: 0} for commit_type in substantive_types
    }
    for row in rows:
        commit_type = str(row.get("type", "")).strip()
        # 跳过非实质性类型
        if commit_type not in coverage:
            continue
        label = parse_label(row.get("is_single_intent"))
        if label is None:
            continue
        coverage[commit_type][label] += 1
    return coverage


def compute_label_shortfalls(
    coverage: dict[str, dict[int, int]],
    min_per_type_label: int,
    substantive_types: tuple[str, ...] = SUBSTANTIVE_TYPES,
) -> dict[str, dict[int, int]]:
    """
    计算各类型各标签的缺口数量。

    缺口 = 目标最小数量 - 当前覆盖数量

    参数:
        coverage: 各类型各标签的覆盖数量
        min_per_type_label: 目标最小数量
        substantive_types: 实质性 commit 类型列表

    返回:
        嵌套字典，键为 (commit_type, label)，值为缺口数量
    """
    shortfalls: dict[str, dict[int, int]] = {}
    target = max(0, int(min_per_type_label))
    for commit_type in substantive_types:
        counts = coverage.get(commit_type, {})
        shortfalls[commit_type] = {
            1: max(0, target - int(counts.get(1, 0))),
            0: max(0, target - int(counts.get(0, 0))),
        }
    return shortfalls


def touched_files_from_diff(git_diff: str, limit: int = 8) -> list[str]:
    """
    从 git diff 中提取涉及的文件列表。

    参数:
        git_diff: git diff 文本
        limit: 最大返回文件数

    返回:
        涉及的文件路径列表（去重并限制数量）
    """
    files: list[str] = []
    for line in git_diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" ")
            if len(parts) >= 4:
                # 移除 "b/" 前缀
                files.append(parts[3].removeprefix("b/"))
    # 去重并保持顺序
    deduped: list[str] = []
    seen: set[str] = set()
    for item in files:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:limit]


def compute_message_only_raw_prob(row: dict, calibration: dict | None) -> float:
    """
    计算 commit 是 "仅消息" 类型的原始概率。

    使用消息特征和校准参数计算 logit 值，然后通过 sigmoid 转换得到概率。

    参数:
        row: 包含 commit 信息的字典
        calibration: 校准参数字典

    返回:
        0-1 之间的概率值
    """
    message_features = miner.parse_message(str(row.get("commit_message", "")))
    return miner.clip_prob(
        miner.sigmoid(
            miner.atomic_logit(
                message_features=message_features,
                candidate_type=str(row.get("type", "")).strip(),
                diff_features=None,
                signal_context=(calibration or {}).get("signal_context"),
                message_protocol=(calibration or {}).get("message_protocol"),
                type_protocol=(calibration or {}).get("type_protocol"),
            )
        )
    )


def assign_score_bands(rows: list[dict], score_bands: int) -> None:
    """
    为每行数据分配分数分位带标签。

    按 commit type 分组，然后在组内按 message_only_prob 排序，
    将数据划分为若干分位带。

    参数:
        rows: 行数据列表（原地修改）
        score_bands: 分位带数量
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[str(row.get("type", "")).strip()].append(row)
    band_count = max(1, int(score_bands))
    for bucket in by_type.values():
        # 按概率升序排序
        ordered = sorted(bucket, key=lambda item: float(item["message_only_prob"]))
        total = len(ordered)
        for index, row in enumerate(ordered):
            # 计算分位带索引
            band_index = min(band_count - 1, int(index * band_count / max(1, total)))
            row["score_band"] = f"q{band_index + 1}"


def _select_directional_candidates(
    pool: list[dict],
    required: int,
    target_label: int,
    oversample_factor: int,
    score_bands: int,
    picked_shas: set[str],
) -> list[dict]:
    """
    从候选池中按方向选择候选数据。

    根据目标标签决定选择策略：
    - target_label=1: 从高概率到低概率选择（期望选择更可能是 single intent 的）
    - target_label=0: 从低概率到高概率选择（期望选择更可能是 multi intent 的）

    参数:
        pool: 候选数据池
        required: 需要选择的数量
        target_label: 目标标签 (0 或 1)
        oversample_factor: 过采样因子
        score_bands: 分位带数量
        picked_shas: 已选择的 sha 集合

    返回:
        选中的候选数据列表
    """
    if required <= 0:
        return []
    # 生成带名称列表
    band_names = [f"q{i}" for i in range(1, max(1, score_bands) + 1)]
    # 如果目标是 1（单意图），则反转带顺序，优先从高概率带选择
    if target_label == 1:
        band_names = list(reversed(band_names))
    by_band: dict[str, list[dict]] = {band: [] for band in band_names}
    for row in pool:
        band = str(row.get("score_band", band_names[0]))
        if band in by_band:
            by_band[band].append(row)
    # 在每个带内排序：高概率目标优先
    for band in band_names:
        by_band[band].sort(
            key=lambda item: (
                -float(item["message_only_prob"])
                if target_label == 1
                else float(item["message_only_prob"]),
                item["sha"],
            )
        )
    picked: list[dict] = []
    # 计算目标数量（考虑过采样）
    target_count = max(required, required * max(1, oversample_factor))
    exhausted = False
    # 轮询各分位带选择，直到达到目标数量或所有带都耗尽
    while len(picked) < target_count and not exhausted:
        exhausted = True
        for band in band_names:
            while by_band[band]:
                candidate = by_band[band].pop(0)
                sha = str(candidate["sha"])
                if sha in picked_shas:
                    continue
                picked_shas.add(sha)
                copied = dict(candidate)
                copied["target_label"] = str(target_label)
                copied["selection_direction"] = (
                    "high_score_positive_seek"
                    if target_label == 1
                    else "low_score_negative_seek"
                )
                picked.append(copied)
                exhausted = False
                break
            if len(picked) >= target_count:
                break
    return picked


def build_expansion_candidate_rows(
    *,
    annotated_rows: list[dict],
    prefilter_rows: list[dict],
    calibration: dict | None,
    min_per_type_label: int,
    oversample_factor: int,
    score_bands: int,
    seed: int,
    substantive_types: tuple[str, ...] = SUBSTANTIVE_TYPES,
) -> tuple[list[dict], dict[str, dict[int, int]], dict[str, dict[int, int]]]:
    """
    构建审计扩充候选行数据。

    流程：
    1. 计算当前标注数据的类型-标签覆盖
    2. 计算各类型各标签的缺口
    3. 从预过滤数据中筛选不在已有数据中的候选
    4. 计算 message_only 概率并分配分位带
    5. 根据缺口选择候选数据

    参数:
        annotated_rows: 已标注的数据
        prefilter_rows: 预过滤候选数据
        calibration: 校准参数
        min_per_type_label: 每类型每标签的最小数量
        oversample_factor: 过采样因子
        score_bands: 分位带数量
        seed: 随机种子
        substantive_types: 实质性类型列表

    返回:
        (选中的候选数据, 覆盖统计, 缺口统计) 元组
    """
    # 计算当前覆盖和缺口
    coverage = compute_type_label_coverage(
        annotated_rows, substantive_types=substantive_types
    )
    shortfalls = compute_label_shortfalls(
        coverage,
        min_per_type_label=min_per_type_label,
        substantive_types=substantive_types,
    )
    # 记录已有数据的 sha，避免重复选择
    existing_shas = {
        str(row.get("sha", "")).strip()
        for row in annotated_rows
        if str(row.get("sha", "")).strip()
    }

    candidate_rows: list[dict] = []
    rng = random.Random(seed)
    # 从预过滤数据中筛选新候选
    for row in prefilter_rows:
        sha = str(row.get("sha", "")).strip()
        commit_type = str(row.get("type", "")).strip()
        # 跳过已有数据和非实质性类型
        if not sha or sha in existing_shas or commit_type not in substantive_types:
            continue
        candidate_rows.append(
            {
                "sha": sha,
                "repo": str(row.get("resolved_repo", "")).strip(),
                "type": commit_type,
                "commit_message": str(row.get("commit_message", "")),
                "git_diff": "",
                "message_only_prob": round(
                    compute_message_only_raw_prob(row, calibration), 6
                ),
                "diff_file_count": 0,
                "diff_hunk_count": 0,
                "diff_changed_lines": 0,
                "touched_files": "",
                "audit_is_single_intent": "",
                "audit_confidence": "",
                "audit_reviewer": "",
                "audit_notes": "",
            }
        )
    rng.shuffle(candidate_rows)
    # 分配分数分位带
    assign_score_bands(candidate_rows, score_bands=score_bands)

    # 按类型分组
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in candidate_rows:
        by_type[row["type"]].append(row)

    selected: list[dict] = []
    picked_shas: set[str] = set()
    # 对每种类型，分别选择正负样本
    for commit_type in substantive_types:
        pool = by_type.get(commit_type, [])
        # 先选择标签为 1 的候选（单意图）
        selected.extend(
            _select_directional_candidates(
                pool=pool,
                required=shortfalls[commit_type][1],
                target_label=1,
                oversample_factor=oversample_factor,
                score_bands=score_bands,
                picked_shas=picked_shas,
            )
        )
        # 再选择标签为 0 的候选（多意图）
        selected.extend(
            _select_directional_candidates(
                pool=pool,
                required=shortfalls[commit_type][0],
                target_label=0,
                oversample_factor=oversample_factor,
                score_bands=score_bands,
                picked_shas=picked_shas,
            )
        )

    # 按类型、标签、分位带、概率排序
    selected.sort(
        key=lambda item: (
            item["type"],
            item["target_label"],
            item["score_band"],
            -float(item["message_only_prob"]),
            item["sha"],
        )
    )
    return selected, coverage, shortfalls


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    将行数据写入 CSV 文件。

    参数:
        path: 输出文件路径
        rows: 行数据列表
    """
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """
    主函数：构建 message-only 审计扩充候选数据集。

    流程：
    1. 加载已标注数据和预过滤数据
    2. 加载校准参数（如果有）
    3. 构建扩充候选数据
    4. 加载完整的 commit 文本和 diff 信息
    5. 输出扩充候选 CSV 文件
    """
    args = parse_args()
    # 加载已标注数据和预过滤候选数据
    annotated_rows = load_csv_rows(Path(args.annotated))
    prefilter_rows = load_csv_rows(Path(args.prefilter))
    # 加载校准参数（可选，用于概率计算）
    calibration = (
        miner.load_calibration(args.base_calibration) if args.base_calibration else None
    )
    # 构建候选数据：根据覆盖缺口选择需要扩充的样本
    selected, coverage, shortfalls = build_expansion_candidate_rows(
        annotated_rows=annotated_rows,
        prefilter_rows=prefilter_rows,
        calibration=calibration,
        min_per_type_label=args.min_per_type_label,
        oversample_factor=args.oversample_factor,
        score_bands=args.score_bands,
        seed=args.seed,
    )
    # 加载选中的 commit 的完整文本和 diff 信息
    selected_shas = {str(row["sha"]).strip() for row in selected}
    commit_texts_by_sha = load_commit_texts(
        Path(args.commit_texts), wanted_shas=selected_shas
    )
    # 填充完整的 commit 信息：整合文本、diff 特征和文件列表
    complete_selected: list[dict] = []
    for row in selected:
        payload = commit_texts_by_sha.get(str(row["sha"]).strip())
        if not payload:
            continue
        git_diff = str(payload.get("git_diff", "")).strip()
        if not git_diff:
            continue
        enriched = dict(row)
        enriched["repo"] = str(payload.get("repo", enriched.get("repo", ""))).strip()
        enriched["commit_message"] = str(
            payload.get("commit_message", enriched.get("commit_message", ""))
        )
        enriched["git_diff"] = git_diff
        # 解析 diff 特征：文件数、块数、变更行数
        diff_features = miner.parse_diff(git_diff)
        enriched["diff_file_count"] = int(float(diff_features.get("file_count", 0.0)))
        enriched["diff_hunk_count"] = int(float(diff_features.get("hunk_count", 0.0)))
        enriched["diff_changed_lines"] = int(
            float(diff_features.get("changed_lines", 0.0))
        )
        # 提取涉及的文件列表
        enriched["touched_files"] = ",".join(touched_files_from_diff(git_diff))
        complete_selected.append(enriched)
    # 输出结果：创建目录并写入 CSV 文件
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(output_path, complete_selected)
    # 打印统计信息
    print(
        json.dumps({"coverage": coverage, "shortfalls": shortfalls}, ensure_ascii=False)
    )
    print(f"selected_candidates={len(complete_selected)}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
