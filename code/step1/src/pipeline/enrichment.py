"""
预过滤候选增强脚本

本脚本是流水线的第四阶段，用于从GitHub解析完整的diff信息。

功能：
1. 解析GitHub仓库URL：搜索SHA对应的仓库
2. 仓库消歧：当多个仓库包含相同SHA时，根据主题相似度选择
3. 获取diff：获取完整的代码变更（如果启用）
4. 可恢复：支持断点续传
5. 速率限制处理：自动重试429错误

输出：
- resolved_candidates.csv: 解析后的候选（含仓库和diff）
- enrich_status.json: 增强状态
- search_cache.json: 搜索结果缓存
- patch_subject_cache.json: patch主题缓存
- summary.md: 统计摘要
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import atomic_mining as miner
from src.experiments import remine as rem


USER_AGENT = "Mozilla/5.0 (compatible; CodexResearchBot/1.0)"  # HTTP请求User-Agent
COMMIT_LINK_RE = re.compile(
    r"/([^/]+/[^/]+)/commit/([0-9a-f]{40})"
)  # 仓库commit链接正则
PATCH_SUBJECT_RE = re.compile(
    r"^Subject:\s*(?:\[[^\]]+\]\s*)?(?P<subject>.+)$", re.IGNORECASE
)  # Patch主题正则
TOKEN_RE = re.compile(r"[a-z0-9]+")  # 标记提取正则
DEFAULT_MAX_CANDIDATES = 100  # 默认最大候选数（0表示处理全部）
DEFAULT_MIN_STARS = 1000  # 默认最小star数（过滤小仓库）
DEFAULT_ACTIVE_YEARS = 2  # 默认活跃年数（过滤不活跃仓库）
DEFAULT_SLEEP_SECONDS = 0.2  # 默认休眠秒数（API调用间隔）
DEFAULT_SEARCH_SLEEP_SECONDS = 1.0  # 默认搜索休眠秒数（搜索API更严格）
DEFAULT_RETRY_ON_429 = 3  # 默认429重试次数（速率限制）
DEFAULT_DIFF_RETRY_LIMIT = 3  # 默认diff重试次数
DEFAULT_TOP_EXAMPLE_COUNT = 15  # 默认Top示例数量（摘要展示）
DEFAULT_HTTP_TIMEOUT_SECONDS = 30  # 默认HTTP超时秒数
RATE_LIMIT_STATUS_CODE = 429  # 速率限制状态码
SEARCH_REPO_LIST_CAP = 20  # 搜索仓库列表上限
DIFF_RETRY_BACKOFF_BASE_SECONDS = 1.5  # diff重试退避基准秒数
RETRY_EXP_BASE = 2  # 重试指数基数
CHECKPOINT_INTERVAL = 10  # 检查点间隔
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制
DEFAULT_PROGRESS_EVERY = 1  # 默认进度输出间隔
DEFAULT_SUBJECT_DISAMBIG_TOP_K = 5  # 默认主题消歧Top-K
DEFAULT_REQUIRE_COMPLETE = False  # 默认要求完成
DEFAULT_NO_RESUME = False  # 默认不禁用恢复
DEFAULT_RESET_OUTPUT = False  # 默认不重置输出
DEFAULT_LOCAL_COMMIT_TEXTS_JSONL = "../../datasets/step1/runtime_support/resolved_commit_texts.jsonl"  # 本地commit文本/仓库/diff缓存
ENRICH_STATUS_FILENAME = "enrich_status.json"  # 增强状态文件名
PATCH_SUBJECT_CACHE_FILENAME = "patch_subject_cache.json"  # patch主题缓存文件名
RESULT_CSV_FILENAME = "resolved_candidates.csv"  # 结果CSV文件名
SUMMARY_FILENAME = "summary.md"  # 摘要文件名
RESULT_JSONL_FILENAME = "resolved_commit_texts.jsonl"  # 结果JSONL文件名
SEARCH_CACHE_FILENAME = "search_cache.json"  # 搜索缓存文件名


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="outputs/prefilter/prefilter_stratified_batch.csv",
    )
    parser.add_argument(
        "--repo-list",
        default="../../datasets/step1/runtime_support/resolved_metadata.csv",
    )
    parser.add_argument(
        "--repo-cache",
        default="outputs/repo_metadata.json",
    )
    parser.add_argument("--output-dir", default="outputs/enriched")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS)
    parser.add_argument("--active-years", type=int, default=DEFAULT_ACTIVE_YEARS)
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument(
        "--search-sleep-seconds", type=float, default=DEFAULT_SEARCH_SLEEP_SECONDS
    )
    parser.add_argument("--retry-on-429", type=int, default=DEFAULT_RETRY_ON_429)
    parser.add_argument("--checkpoint-interval", type=int, default=CHECKPOINT_INTERVAL)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=DEFAULT_PROGRESS_EVERY,
        help="Print one progress line every N processed candidates.",
    )
    parser.add_argument(
        "--subject-disambig-top-k",
        type=int,
        default=DEFAULT_SUBJECT_DISAMBIG_TOP_K,
        help="When multiple repos match the same SHA, inspect top-k repos and pick by subject similarity.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        default=DEFAULT_REQUIRE_COMPLETE,
        help="Exit non-zero when not all candidates are processed (network/rate-limit interruption).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=DEFAULT_NO_RESUME,
        help="Disable resume mode; process all rows from scratch.",
    )
    parser.add_argument(
        "--reset-output",
        action="store_true",
        default=DEFAULT_RESET_OUTPUT,
        help="Delete previous resolved outputs under output-dir before running.",
    )
    parser.add_argument(
        "--allow-low-similarity-fallback",
        action="store_true",
        help="Allow star-based fallback even when subject disambiguation similarity is low (not recommended).",
    )
    parser.add_argument("--fetch-diff", action="store_true")
    parser.add_argument("--min-atomic-prior", type=float, default=0.0)
    parser.add_argument("--tau-a", type=float, default=miner.DEFAULT_TAU_A)
    parser.add_argument("--tau-b", type=float, default=miner.DEFAULT_TAU_B)
    parser.add_argument(
        "--primary-calibration-json",
        default="",
        help="Full-diff primary calibration artifact used for post-enrich scoring and tiers.",
    )
    parser.add_argument(
        "--proxy-calibration-json",
        default="",
        help="Message-only proxy calibration artifact used for low-cost proxy fields during enrich.",
    )
    parser.add_argument(
        "--calibration-json",
        default="",
        help="Deprecated alias of --primary-calibration-json.",
    )
    parser.add_argument(
        "--message-only-calibration-json",
        default="",
        help="Deprecated alias of --proxy-calibration-json.",
    )
    parser.add_argument(
        "--local-commit-texts-jsonl",
        default=DEFAULT_LOCAL_COMMIT_TEXTS_JSONL,
        help="Optional local resolved_commit_texts.jsonl used for offline enrich.",
    )
    parser.add_argument(
        "--reference-time-utc",
        default="",
        help="Optional UTC reference timestamp (ISO8601). If empty, use current UTC time.",
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


def load_local_commit_texts(path: Path, wanted_shas: set[str]) -> dict[str, dict]:
    """按需加载本地 resolved_commit_texts.jsonl。"""
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


def resolve_local_candidate_payload(
    row: dict, local_commit_texts: dict[str, dict]
) -> dict | None:
    """从本地commit文本缓存中直接解析 repo/message/diff。"""
    sha = str(row.get("sha", "")).strip()
    payload = local_commit_texts.get(sha)
    if not payload:
        return None
    git_diff = str(payload.get("git_diff", "")).strip()
    if not git_diff:
        return None
    return {
        "resolved_repo": str(payload.get("repo", "")).strip(),
        "commit_message": str(
            payload.get("commit_message", row.get("commit_message", ""))
        ),
        "git_diff": git_diff,
    }


def load_json_dict(path: Path) -> dict:
    """
    加载JSON文件

    参数:
        path: JSON文件路径

    返回:
        dict: JSON对象，空文件返回空字典
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_dict(path: Path, data: dict) -> None:
    """
    保存JSON文件

    参数:
        path: 输出文件路径
        data: 待保存的字典
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_url(url: str) -> tuple[str, str]:
    """
    获取URL内容

    使用HTTP GET请求获取URL内容，支持重定向。
    编码: UTF-8，忽略解码错误

    参数:
        url: 目标URL

    返回:
        tuple[str, str]: (响应体, 最终URL)
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        final_url = resp.geturl()
    return body, final_url


def search_commit_repos(
    sha: str, search_cache: dict, search_sleep_seconds: float, retry_on_429: int
) -> list[str]:
    """
    搜索包含特定SHA的仓库

    使用GitHub搜索API查找包含给定SHA的仓库。
    搜索结果会缓存以避免重复请求。

    参数:
        sha: Git提交SHA（40位十六进制）
        search_cache: 搜索缓存字典
        search_sleep_seconds: 搜索间隔秒数（避免限流）
        retry_on_429: 429错误重试次数

    返回:
        list[str]: 仓库列表（如["facebook/react", "microsoft/vscode"]）
    """
    # 检查缓存：如果已搜索过，直接返回缓存结果
    if sha in search_cache:
        return search_cache[sha].get("raw_repos", [])

    # 构建GitHub搜索URL参数
    query = urllib.parse.urlencode({"q": sha, "type": "commits"})

    # 请求搜索页面，处理429错误（速率限制），使用指数退避策略
    attempts = 0
    while True:
        try:
            html, _ = fetch_url(f"https://github.com/search?{query}")
            break
        except urllib.error.HTTPError as exc:
            attempts += 1
            # 如果不是429错误或重试次数用尽，则抛出异常
            if exc.code != RATE_LIMIT_STATUS_CODE or attempts > retry_on_429:
                raise
            # 指数退避: 1s, 2s, 4s, ... 避免频繁触发限流
            time.sleep(search_sleep_seconds * (RETRY_EXP_BASE**attempts))
        except urllib.error.URLError:
            attempts += 1
            if attempts > retry_on_429:
                raise
            time.sleep(search_sleep_seconds * (RETRY_EXP_BASE**attempts))

    # 搜索后等待一段时间（避免触发限流）
    time.sleep(search_sleep_seconds)

    # 解析搜索结果页面，提取包含该SHA的仓库列表
    seen = []
    for repo, found_sha in COMMIT_LINK_RE.findall(html):
        # 过滤掉SHA不匹配的记录
        if found_sha != sha:
            continue
        # 去重
        if repo not in seen:
            seen.append(repo)

    # 缓存搜索结果
    search_cache[sha] = {"raw_repos": seen}
    return seen


def load_existing_rows(path: Path) -> list[dict]:
    """
    加载已存在的CSV行

    如果文件不存在或为空，返回空列表。

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表
    """
    if not path.exists() or path.stat().st_size == 0:
        return []
    return load_rows(path)


def normalize_subject_tokens(text: str) -> set[str]:
    """
    标准化subject标记

    将subject文本转为小写并提取为标记集合。

    参数:
        text: subject文本

    返回:
        set[str]: 标记集合
    """
    return {token for token in TOKEN_RE.findall((text or "").lower()) if token}


def subject_similarity(left: str, right: str) -> float:
    """
    计算两个subject的相似度

    使用Jaccard相似系数：
    similarity = |left ∩ right| / |left ∪ right|

    参数:
        left: 第一个subject
        right: 第二个subject

    返回:
        float: 相似度 [0, 1]，1表示完全相同
    """
    left_tokens = normalize_subject_tokens(left)
    right_tokens = normalize_subject_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def derive_subject_match_requirements(
    expected_subject: str, scores: list[float]
) -> tuple[float, float]:
    """
    派生主题匹配要求

    基于token数和分数分布计算最小相似度和边距要求。

    参数:
        expected_subject: 预期主题文本
        scores: 候选分数列表

    返回:
        tuple[float, float]: (最小相似度, 所需边距)
    """
    # Token-driven minimum overlap + distribution-driven spread margin.
    token_count = len(normalize_subject_tokens(expected_subject))
    token_floor = 1.0 / max(2.0, float(token_count + 2))
    if not scores:
        return token_floor, 0.0
    median_score = statistics.median(scores)
    spread = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    min_similarity = min(1.0, max(token_floor, median_score + spread))
    required_margin = spread
    return min_similarity, required_margin


def fetch_patch_subject(
    repo: str, sha: str, retry_limit: int = DEFAULT_DIFF_RETRY_LIMIT
) -> str:
    """
    获取patch主题

    从GitHub获取.patch文件并提取Subject行。

    参数:
        repo: 仓库名（如facebook/react）
        sha: 提交SHA
        retry_limit: 重试次数

    返回:
        str: patch主题文本
    """
    patch_url = f"https://github.com/{repo}/commit/{sha}.patch"
    attempts = 0
    while True:
        try:
            req = urllib.request.Request(patch_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                req, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS
            ) as resp:
                patch_text = resp.read().decode("utf-8", errors="ignore")
            for line in patch_text.splitlines()[:60]:
                match = PATCH_SUBJECT_RE.match(line.strip())
                if match:
                    return match.group("subject").strip()
            return ""
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return ""
            attempts += 1
            if attempts > retry_limit:
                return ""
            time.sleep(DIFF_RETRY_BACKOFF_BASE_SECONDS * (RETRY_EXP_BASE**attempts))
        except urllib.error.URLError:
            attempts += 1
            if attempts > retry_limit:
                return ""
            time.sleep(DIFF_RETRY_BACKOFF_BASE_SECONDS * (RETRY_EXP_BASE**attempts))


def get_patch_subject_cached(repo: str, sha: str, cache: dict, cache_path: Path) -> str:
    """
    获取patch主题（带缓存）

    参数:
        repo: 仓库名
        sha: 提交SHA
        cache: 内存缓存字典
        cache_path: 缓存文件路径

    返回:
        str: patch主题文本
    """
    key = f"{repo}@{sha}"
    cached = cache.get(key)
    if isinstance(cached, str):
        return cached
    subject = fetch_patch_subject(repo=repo, sha=sha)
    cache[key] = subject
    save_json_dict(cache_path, cache)
    return subject


def pick_repo_by_subject_alignment(
    repo_star_pairs: list[tuple[str, int]],
    sha: str,
    expected_subject: str,
    patch_subject_cache: dict,
    patch_subject_cache_path: Path,
    top_k: int,
    allow_low_similarity_fallback: bool,
) -> tuple[str, float, str]:
    """
    根据主题对齐选择仓库

    比较候选仓库的patch主题与预期主题，选择最匹配的仓库。

    参数:
        repo_star_pairs: 仓库-star数对列表
        sha: 提交SHA
        expected_subject: 预期主题
        patch_subject_cache: patch主题缓存
        patch_subject_cache_path: 缓存文件路径
        top_k: 比较前k个仓库
        allow_low_similarity_fallback: 是否允许低相似度回退

    返回:
        tuple[str, float, str]: (选中的仓库, 相似度, 选择原因)
    """
    if not repo_star_pairs:
        return "", 0.0, "no_repo"
    ordered = sorted(repo_star_pairs, key=lambda item: (-item[1], item[0]))
    if len(ordered) == 1:
        return ordered[0][0], 0.0, "single_or_no_subject"
    if not expected_subject.strip():
        if allow_low_similarity_fallback:
            return ordered[0][0], 0.0, "no_subject_max_star_fallback"
        return "", 0.0, "no_subject_disambiguation_failfast"
    ranked = ordered[: max(1, top_k)]
    scored_candidates: list[tuple[str, int, float]] = []
    for repo, _stars in ranked:
        observed_subject = get_patch_subject_cached(
            repo=repo,
            sha=sha,
            cache=patch_subject_cache,
            cache_path=patch_subject_cache_path,
        )
        score = subject_similarity(expected_subject, observed_subject)
        scored_candidates.append((repo, _stars, score))
    scored_candidates.sort(key=lambda item: (-item[2], -item[1], item[0]))
    best_repo, _best_stars, best_score = scored_candidates[0]
    all_scores = [item[2] for item in scored_candidates]
    min_similarity, required_margin = derive_subject_match_requirements(
        expected_subject=expected_subject,
        scores=all_scores,
    )
    second_score = scored_candidates[1][2] if len(scored_candidates) > 1 else 0.0
    margin = best_score - second_score
    low_similarity = best_score < min_similarity
    low_margin = len(scored_candidates) > 1 and margin < required_margin
    if low_similarity or low_margin:
        if allow_low_similarity_fallback:
            return ranked[0][0], best_score, "low_similarity_max_star_fallback"
        return (
            "",
            best_score,
            (
                "low_similarity_failfast"
                f"(best={best_score:.4f},min={min_similarity:.4f},"
                f"margin={margin:.4f},required_margin={required_margin:.4f})"
            ),
        )
    return best_repo, best_score, "subject_match"


def ensure_repo_meta(
    repo: str,
    repo_meta_by_query: dict[str, dict],
    cache_path: Path,
    sleep_seconds: float,
) -> dict:
    """
    确保仓库元数据存在

    如果缓存中没有，则获取并保存。

    参数:
        repo: 仓库名
        repo_meta_by_query: 仓库元数据缓存
        cache_path: 缓存文件路径
        sleep_seconds: 请求间隔

    返回:
        dict: 仓库元数据
    """
    if repo not in repo_meta_by_query:
        repo_meta_by_query[repo] = rem.fetch_metadata(repo, sleep_seconds=sleep_seconds)
        rem.save_cache(cache_path, repo_meta_by_query)
    return repo_meta_by_query[repo]


def resolve_repo(
    sha: str,
    expected_subject: str,
    seed_repos: set[str],
    repo_meta_by_query: dict[str, dict],
    cache_path: Path,
    patch_subject_cache: dict,
    patch_subject_cache_path: Path,
    min_stars: int,
    active_years: int,
    now: datetime,
    search_cache: dict,
    sleep_seconds: float,
    search_sleep_seconds: float,
    retry_on_429: int,
    subject_disambig_top_k: int,
    allow_low_similarity_fallback: bool,
) -> tuple[str, list[str], str, float]:
    """
    解析仓库

    搜索包含给定SHA的仓库，根据主题对齐和元数据选择最佳仓库。

    参数:
        sha: 提交SHA
        expected_subject: 预期主题
        seed_repos: 种子仓库集合
        repo_meta_by_query: 仓库元数据缓存
        cache_path: 元数据缓存文件路径
        patch_subject_cache: patch主题缓存
        patch_subject_cache_path: patch主题缓存路径
        min_stars: 最小star数
        active_years: 最小活跃年数
        now: 当前时间
        search_cache: 搜索缓存
        sleep_seconds: API调用间隔
        search_sleep_seconds: 搜索间隔
        retry_on_429: 429重试次数
        subject_disambig_top_k: 主题消歧Top-K
        allow_low_similarity_fallback: 是否允许低相似度回退

    返回:
        tuple[str, list[str], str, float]: (仓库名, 候选仓库列表, 选择原因, 相似度)
    """
    raw_repos = search_commit_repos(
        sha,
        search_cache=search_cache,
        search_sleep_seconds=search_sleep_seconds,
        retry_on_429=retry_on_429,
    )
    seed_matches: list[tuple[str, int]] = []
    quality_matches: list[tuple[str, int]] = []

    for raw_repo in raw_repos:
        if raw_repo in seed_repos:
            seed_matches.append((raw_repo, 0))
            continue

        meta = ensure_repo_meta(
            raw_repo,
            repo_meta_by_query,
            cache_path=cache_path,
            sleep_seconds=sleep_seconds,
        )
        canonical_repo = meta.get("canonical_repo", raw_repo)
        stars = meta.get("stars") or 0

        if canonical_repo in seed_repos:
            seed_matches.append((canonical_repo, stars))
            continue

        if rem.repo_passes(
            meta, min_stars=min_stars, active_years=active_years, now=now
        ):
            quality_matches.append((canonical_repo, stars))

    seed_score_by_repo: dict[str, int] = {}
    for repo, stars in seed_matches:
        seed_score_by_repo[repo] = max(stars, seed_score_by_repo.get(repo, -1))
    seed_ranked = sorted(
        seed_score_by_repo.items(), key=lambda item: (-item[1], item[0])
    )
    if len(seed_ranked) == 1:
        return seed_ranked[0][0], raw_repos, "resolved", 1.0
    if len(seed_ranked) > 1:
        chosen_repo, match_score, pick_mode = pick_repo_by_subject_alignment(
            repo_star_pairs=seed_ranked,
            sha=sha,
            expected_subject=expected_subject,
            patch_subject_cache=patch_subject_cache,
            patch_subject_cache_path=patch_subject_cache_path,
            top_k=subject_disambig_top_k,
            allow_low_similarity_fallback=allow_low_similarity_fallback,
        )
        if chosen_repo:
            return (
                chosen_repo,
                raw_repos,
                f"resolved_multi_seed_{pick_mode}",
                match_score,
            )
        return "", raw_repos, f"unresolved_multi_seed_{pick_mode}", match_score

    quality_score_by_repo: dict[str, int] = {}
    for repo, stars in quality_matches:
        quality_score_by_repo[repo] = max(stars, quality_score_by_repo.get(repo, -1))
    quality_ranked = sorted(
        quality_score_by_repo.items(), key=lambda item: (-item[1], item[0])
    )
    if len(quality_ranked) == 1:
        return quality_ranked[0][0], raw_repos, "resolved_high_quality_non_seed", 1.0
    if len(quality_ranked) > 1:
        chosen_repo, match_score, pick_mode = pick_repo_by_subject_alignment(
            repo_star_pairs=quality_ranked,
            sha=sha,
            expected_subject=expected_subject,
            patch_subject_cache=patch_subject_cache,
            patch_subject_cache_path=patch_subject_cache_path,
            top_k=subject_disambig_top_k,
            allow_low_similarity_fallback=allow_low_similarity_fallback,
        )
        if chosen_repo:
            return (
                chosen_repo,
                raw_repos,
                f"resolved_high_quality_{pick_mode}",
                match_score,
            )
        return "", raw_repos, f"unresolved_high_quality_{pick_mode}", match_score

    if raw_repos:
        return "", raw_repos, "no_seed_match", 0.0
    return "", [], "no_search_match", 0.0


def fetch_diff(repo: str, sha: str, retry_limit: int = DEFAULT_DIFF_RETRY_LIMIT) -> str:
    """
    获取diff内容

    从GitHub获取.diff文件。

    参数:
        repo: 仓库名
        sha: 提交SHA
        retry_limit: 重试次数

    返回:
        str: diff内容
    """
    diff_url = f"https://github.com/{repo}/commit/{sha}.diff"
    attempts = 0
    while True:
        try:
            req = urllib.request.Request(diff_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                req, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS
            ) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError:
            attempts += 1
            if attempts > retry_limit:
                raise
            time.sleep(DIFF_RETRY_BACKOFF_BASE_SECONDS * (RETRY_EXP_BASE**attempts))


def write_csv(path: Path, rows: list[dict]) -> None:
    """
    写入CSV文件

    参数:
        path: 输出文件路径
        rows: 行字典列表
    """
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    """
    追加JSONL行

    参数:
        path: 输出文件路径
        rows: 行字典列表
    """
    if not rows:
        return
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary(path: Path, args: argparse.Namespace, rows: list[dict]) -> None:
    """
    写入统计摘要

    参数:
        path: 输出文件路径
        args: 命令行参数
        rows: 候选行列表
    """
    status_counter: dict[str, int] = {}
    tier_counter: dict[str, int] = {}
    pass_counter = 0
    for row in rows:
        status_counter[row["resolution_status"]] = (
            status_counter.get(row["resolution_status"], 0) + 1
        )
        tier = row.get("tier", "")
        if tier:
            tier_counter[tier] = tier_counter.get(tier, 0) + 1
        if row.get("passes_atomic_gate") == "1":
            pass_counter += 1

    lines = [
        "# Full Step1 Enrichment Summary",
        "",
        f"- Input candidates: `{args.input}`",
        f"- Attempted candidates: `{len(rows)}`",
        f"- Diff fetching enabled: `{args.fetch_diff}`",
        f"- Reference time UTC: `{args.reference_time_utc or 'runtime_now'}`",
        f"- Minimum atomic prior gate: `{args.min_atomic_prior}`",
        f"- Tier thresholds: `tau_a={args.tau_a}`, `tau_b={args.tau_b}`",
        f"- Passing atomic gate: `{pass_counter}`",
        "",
        "## Resolution Status",
        "",
    ]
    for key, value in sorted(status_counter.items()):
        lines.append(f"- `{key}`: {value}")
    if tier_counter:
        lines.extend(["", "## Tier Distribution", ""])
        for key, value in sorted(tier_counter.items()):
            lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Top Resolved Examples", ""])
    resolved_rows = [row for row in rows if row.get("tier")]
    for row in resolved_rows[:DEFAULT_TOP_EXAMPLE_COUNT]:
        lines.append(
            f"- `{row['tier']}` | prior `{row['atomic_prior_calibrated']}` | full score `{row.get('score', '')}` | utility `{row.get('utility', '')}` | `{row['resolved_repo']}` | `{row['subject']}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_enrich_tier_thresholds(
    *,
    message_only_probabilities: list[float],
    calibration: dict | None,
    tau_a: float | None,
    tau_b: float | None,
    fetch_diff: bool,
) -> tuple[float, float, str]:
    """
    解析enrich阶段Tier阈值，避免message-only与full-diff尺度混用。
    """
    if fetch_diff:
        resolved_a, resolved_b = miner.resolve_thresholds(
            calibration=calibration, tau_a=tau_a, tau_b=tau_b
        )
        if resolved_a is None or resolved_b is None:
            raise ValueError(
                "fetch-diff mode requires explicit --tau-a/--tau-b or calibration thresholds"
            )
        has_explicit_a = tau_a is not None
        has_explicit_b = tau_b is not None
        if has_explicit_a and has_explicit_b:
            source = "full_diff:fixed_from_args"
        elif has_explicit_a or has_explicit_b:
            source = "full_diff:mixed_calibration_and_args"
        else:
            source = "full_diff:constraint_from_calibration_precision"
        return float(resolved_a), float(resolved_b), source

    # 消息仅增强模式（不抓diff）使用同尺度分布阈值
    tau_a_value, tau_b_value, source = miner.derive_thresholds(
        probabilities=message_only_probabilities,
        calibration=None,
        tau_a=tau_a,
        tau_b=tau_b,
    )
    return float(tau_a_value), float(tau_b_value), f"message_only:{source}"


def resolve_enrich_gate_prior(
    *,
    message_only_probabilities: list[float],
    configured_min_prior: float,
    fetch_diff: bool,
) -> tuple[float, str]:
    """
    解析enrich阶段门控阈值，确保与目标概率语义一致。
    """
    if fetch_diff:
        if configured_min_prior > 0.0:
            return float(configured_min_prior), "full_diff:fixed_from_args"
        return 0.0, "full_diff:default_zero"
    gate, source = miner.derive_gate_threshold(
        probabilities=message_only_probabilities,
        configured_min_prior=configured_min_prior,
    )
    return float(gate), f"message_only:{source}"


def write_status(
    path: Path,
    total_candidates: int,
    processed_candidates: int,
    completed: bool,
    interrupted_reason: str,
    require_complete: bool,
    resume_enabled: bool,
) -> None:
    """
    写入增强状态

    参数:
        path: 输出文件路径
        total_candidates: 总候选数
        processed_candidates: 已处理候选数
        completed: 是否完成
        interrupted_reason: 中断原因
        require_complete: 是否要求完成
        resume_enabled: 是否启用恢复
    """
    payload = {
        "total_candidates": total_candidates,
        "processed_candidates": processed_candidates,
        "completed": completed,
        "interrupted_reason": interrupted_reason,
        "require_complete": require_complete,
        "resume_enabled": resume_enabled,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def progress_line(index: int, total: int, status: str) -> str:
    """
    生成进度行文本

    参数:
        index: 当前索引
        total: 总数
        status: 状态文本

    返回:
        str: 格式化进度行
    """
    if total <= 0:
        pct = 0.0
    else:
        pct = 100.0 * (index / total)
    return f"[progress] {index}/{total} ({pct:.1f}%) | {status}"


def main() -> None:
    """
    主函数：执行候选增强

    流程：
    1. 加载输入候选和仓库列表
    2. 搜索包含SHA的仓库
    3. 根据主题对齐和元数据选择仓库
    4. 获取diff信息
    5. 写入输出文件和摘要
    """
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_csv_path = output_dir / RESULT_CSV_FILENAME
    summary_path = output_dir / SUMMARY_FILENAME
    jsonl_path = output_dir / RESULT_JSONL_FILENAME
    search_cache_path = output_dir / SEARCH_CACHE_FILENAME
    patch_subject_cache_path = output_dir / PATCH_SUBJECT_CACHE_FILENAME
    status_path = output_dir / ENRICH_STATUS_FILENAME

    if args.reset_output:
        for path in [result_csv_path, summary_path, jsonl_path, status_path]:
            if path.exists():
                path.unlink()

    primary_calibration_path = args.primary_calibration_json or args.calibration_json
    proxy_calibration_path = (
        args.proxy_calibration_json or args.message_only_calibration_json
    )
    if args.calibration_json:
        print(
            "[deprecation] --calibration-json is deprecated; use --primary-calibration-json",
            flush=True,
        )
    if args.message_only_calibration_json:
        print(
            "[deprecation] --message-only-calibration-json is deprecated; use --proxy-calibration-json",
            flush=True,
        )
    calibration = (
        miner.load_calibration(primary_calibration_path)
        if primary_calibration_path
        else None
    )
    if calibration is not None:
        miner.require_calibration_mode(
            calibration,
            expected_mode="full_diff",
            context="enrich full-diff primary path",
        )
    message_only_calibration = (
        miner.load_calibration(proxy_calibration_path)
        if proxy_calibration_path
        else None
    )
    if message_only_calibration is not None:
        miner.require_calibration_mode(
            message_only_calibration,
            expected_mode="message_only",
            context="enrich message-only proxy path",
        )
    if not proxy_calibration_path:
        raise RuntimeError(
            "enrich requires --proxy-calibration-json to compute message-only proxy fields"
        )
    if args.fetch_diff and not primary_calibration_path:
        raise RuntimeError(
            "fetch-diff mode requires --primary-calibration-json for full-diff primary scoring"
        )
    all_candidates = load_rows(Path(args.input))
    candidates = (
        all_candidates[: args.max_candidates]
        if args.max_candidates > 0
        else all_candidates
    )
    total_candidates = len(candidates)
    progress_every = max(1, int(args.progress_every))
    checkpoint_interval = max(1, int(args.checkpoint_interval))
    resume_enabled = not args.no_resume
    print(
        (
            f"[start] candidates={total_candidates} | fetch_diff={args.fetch_diff} "
            f"| progress_every={progress_every} | checkpoint_interval={checkpoint_interval} "
            f"| resume_enabled={resume_enabled}"
        ),
        flush=True,
    )
    candidate_sha_set = {row.get("sha", "") for row in candidates}
    candidate_sha_order = {
        row.get("sha", ""): idx for idx, row in enumerate(candidates)
    }
    local_commit_texts = load_local_commit_texts(
        Path(args.local_commit_texts_jsonl),
        wanted_shas={str(sha).strip() for sha in candidate_sha_set if str(sha).strip()},
    )

    existing_rows: list[dict] = []
    if resume_enabled:
        existing_rows = load_existing_rows(result_csv_path)
    deduped_existing_rows: list[dict] = []
    seen_sha: set[str] = set()
    for row in existing_rows:
        sha = row.get("sha", "")
        if not sha or sha not in candidate_sha_set or sha in seen_sha:
            continue
        deduped_existing_rows.append(row)
        seen_sha.add(sha)
    rows_out: list[dict] = deduped_existing_rows
    processed_shas: set[str] = set(seen_sha)

    if rows_out:
        print(f"[resume] loaded_existing={len(rows_out)}", flush=True)

    message_feature_rows: list[dict] = []
    candidate_types: list[str] = []
    for row in candidates:
        message_feature_rows.append(miner.parse_message(row.get("commit_message", "")))
        candidate_types.append(row.get("type", ""))

    # 在当前批次上派生一个消息仅信号上下文，使所有候选在diff增强之前共享相同的先验校准基础
    message_protocol = (
        (calibration or {}).get("message_protocol")
        if isinstance(calibration, dict)
        else None
    )
    calibration_type_protocol = (
        (calibration or {}).get("type_protocol")
        if isinstance(calibration, dict)
        else None
    )
    if isinstance(calibration_type_protocol, dict):
        type_protocol = calibration_type_protocol
    else:
        type_protocol = miner.derive_type_protocol(candidate_types=candidate_types)
    scope_protocol = (
        (calibration or {}).get("scope_protocol")
        if isinstance(calibration, dict)
        else None
    )
    message_signal_maps = [
        miner.atomic_signal_map(
            message_features=message_features,
            candidate_type=candidate_type,
            diff_features=None,
            message_protocol=message_protocol,
            type_protocol=type_protocol,
        )
        for message_features, candidate_type in zip(
            message_feature_rows, candidate_types
        )
    ]
    calibration_signal_context = (calibration or {}).get("signal_context")
    if isinstance(calibration_signal_context, dict) and isinstance(
        calibration_signal_context.get("weights"), dict
    ):
        message_signal_context = calibration_signal_context
    else:
        message_signal_context = miner.derive_atomic_signal_context(message_signal_maps)
    calibration_global_stats = (
        (calibration or {}).get("feature_norm_stats", {}).get("global")
        if isinstance((calibration or {}).get("feature_norm_stats"), dict)
        else None
    )
    effective_message_only_calibration = message_only_calibration
    epistemic_ref = (
        (calibration or {}).get("epistemic_reference")
        if isinstance((calibration or {}).get("epistemic_reference"), dict)
        else {}
    )
    epistemic_center = float(epistemic_ref.get("center", 0.0))
    epistemic_scale = float(epistemic_ref.get("scale", 1.0))
    message_only_prior_rows: list[dict] = []
    message_only_probs: list[float] = []
    for msg_features, candidate_type in zip(message_feature_rows, candidate_types):
        logit = miner.atomic_logit(
            message_features=msg_features,
            candidate_type=candidate_type,
            diff_features=None,
            signal_context=message_signal_context,
            message_protocol=message_protocol,
            type_protocol=type_protocol,
        )
        prior = miner.clip_prob(miner.sigmoid(logit))
        calibrated = miner.apply_calibration_to_raw_prob(
            prior,
            logit,
            calibration=effective_message_only_calibration,
        )
        omega = miner.derive_atomic_weight(
            calibrated,
            epistemic_std=0.0,
            epistemic_center=epistemic_center,
            epistemic_scale=epistemic_scale,
        )
        feature_map = miner.build_atomic_feature_map(
            message_features=msg_features,
            candidate_type=candidate_type,
            diff_features=None,
            repo_stats=None,
            global_stats=None,
        )
        prior_info = {
            "atomic_logit": logit,
            "atomic_prior": prior,
            "atomic_prior_calibrated": calibrated,
            "p_raw": prior,
            "p_atomic": calibrated,
            "omega_atomic": miner.clip_prob(omega),
            "epistemic_std": 0.0,
            "x_atom": json.dumps(feature_map, ensure_ascii=False, sort_keys=True),
            "signal_context_source": (message_signal_context or {}).get(
                "source", "default_uniform_weight"
            ),
        }
        message_only_prior_rows.append(prior_info)
        message_only_probs.append(prior_info["p_atomic"])

    tau_a, tau_b, tau_source = resolve_enrich_tier_thresholds(
        message_only_probabilities=message_only_probs,
        calibration=calibration,
        tau_a=args.tau_a,
        tau_b=args.tau_b,
        fetch_diff=args.fetch_diff,
    )
    gate_prior, gate_source = resolve_enrich_gate_prior(
        message_only_probabilities=message_only_probs,
        configured_min_prior=args.min_atomic_prior,
        fetch_diff=args.fetch_diff,
    )
    args.tau_a = tau_a
    args.tau_b = tau_b
    args.min_atomic_prior = gate_prior
    repo_cache_path = Path(args.repo_cache)
    repo_meta_by_query = rem.load_cache(repo_cache_path)
    search_cache = load_json_dict(search_cache_path)
    patch_subject_cache = load_json_dict(patch_subject_cache_path)

    now = datetime.now(timezone.utc)
    if args.reference_time_utc:
        now = datetime.fromisoformat(args.reference_time_utc.replace("Z", "+00:00"))
    seed_repos_raw = rem.load_seed_repos(Path(args.repo_list))
    qualified_seed_repos = {
        repo_meta_by_query[repo]["canonical_repo"]
        for repo in seed_repos_raw
        if repo in repo_meta_by_query
        and rem.repo_passes(
            repo_meta_by_query[repo],
            min_stars=args.min_stars,
            active_years=args.active_years,
            now=now,
        )
    }

    diff_rows = []
    interrupted_reason = "completed"

    def persist_checkpoint() -> None:
        rows_out.sort(
            key=lambda item: candidate_sha_order.get(
                item.get("sha", ""), total_candidates + 1
            )
        )
        write_csv(result_csv_path, rows_out)
        append_jsonl(jsonl_path, diff_rows)
        diff_rows.clear()
        write_summary(summary_path, args, rows_out)
        save_json_dict(search_cache_path, search_cache)
        save_json_dict(patch_subject_cache_path, patch_subject_cache)
        write_status(
            path=status_path,
            total_candidates=total_candidates,
            processed_candidates=len(processed_shas),
            completed=len(processed_shas) == total_candidates,
            interrupted_reason=interrupted_reason,
            require_complete=args.require_complete,
            resume_enabled=resume_enabled,
        )

    for index, row in enumerate(candidates, start=1):
        sha = row["sha"]
        if sha in processed_shas:
            if index % progress_every == 0:
                print(
                    progress_line(
                        index=index,
                        total=total_candidates,
                        status=f"resume_skip sha={sha}",
                    ),
                    flush=True,
                )
            continue
        message_features = message_feature_rows[index - 1]
        message_only_prior = message_only_prior_rows[index - 1]
        expected_subject = message_features.get("subject_line", "")
        local_payload = resolve_local_candidate_payload(row, local_commit_texts)
        if local_payload is not None:
            resolved_repo = local_payload["resolved_repo"]
            raw_repos = [resolved_repo] if resolved_repo else []
            resolution_status = (
                "resolved_local_jsonl" if resolved_repo else "missing_local_repo"
            )
            disambig_score = 1.0 if resolved_repo else 0.0
            if index % progress_every == 0:
                print(
                    progress_line(
                        index=index,
                        total=total_candidates,
                        status=f"resolved_repo={resolved_repo or 'none'} status={resolution_status}",
                    ),
                    flush=True,
                )
        else:
            try:
                resolved_repo, raw_repos, resolution_status, disambig_score = (
                    resolve_repo(
                        sha=sha,
                        expected_subject=expected_subject,
                        seed_repos=qualified_seed_repos,
                        repo_meta_by_query=repo_meta_by_query,
                        cache_path=repo_cache_path,
                        patch_subject_cache=patch_subject_cache,
                        patch_subject_cache_path=patch_subject_cache_path,
                        min_stars=args.min_stars,
                        active_years=args.active_years,
                        now=now,
                        search_cache=search_cache,
                        sleep_seconds=args.sleep_seconds,
                        search_sleep_seconds=args.search_sleep_seconds,
                        retry_on_429=args.retry_on_429,
                        subject_disambig_top_k=args.subject_disambig_top_k,
                        allow_low_similarity_fallback=args.allow_low_similarity_fallback,
                    )
                )
                if index % progress_every == 0:
                    print(
                        progress_line(
                            index=index,
                            total=total_candidates,
                            status=f"resolved_repo={resolved_repo or 'none'} status={resolution_status}",
                        ),
                        flush=True,
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == RATE_LIMIT_STATUS_CODE:
                    interrupted_reason = "rate_limited"
                    persist_checkpoint()
                    print(
                        f"rate_limited_at={index} processed={len(rows_out)}", flush=True
                    )
                    break
                raise
            except urllib.error.URLError:
                interrupted_reason = "network_error"
                persist_checkpoint()
                print(f"network_error_at={index} processed={len(rows_out)}", flush=True)
                break

        output_row = dict(row)
        output_row["resolution_status"] = resolution_status
        output_row["repo_disambiguation_score"] = round(disambig_score, 6)
        output_row["search_repo_count"] = len(raw_repos)
        output_row["search_repos"] = ",".join(raw_repos[:SEARCH_REPO_LIST_CAP])
        output_row["resolved_repo"] = resolved_repo
        output_row["commit_url"] = (
            f"https://github.com/{resolved_repo}/commit/{sha}" if resolved_repo else ""
        )
        if local_payload is not None:
            output_row["commit_message"] = local_payload["commit_message"]

        output_row["x_atom_message_only"] = message_only_prior["x_atom"]
        output_row["proxy_model_mode"] = "message_only"
        output_row["proxy_model_role"] = "proxy"
        output_row["p_raw_message_only"] = round(message_only_prior["p_raw"], 6)
        output_row["p_atomic_message_only"] = round(message_only_prior["p_atomic"], 6)
        output_row["omega_atomic_message_only"] = round(
            message_only_prior["omega_atomic"], 6
        )
        output_row["atomic_logit_message_only"] = round(
            message_only_prior["atomic_logit"], 6
        )
        output_row["atomic_prior_message_only"] = round(
            message_only_prior["atomic_prior"], 6
        )
        output_row["atomic_prior_message_only_calibrated"] = round(
            message_only_prior["atomic_prior_calibrated"], 6
        )
        output_row["signal_context_source_message_only"] = message_only_prior.get(
            "signal_context_source", ""
        )
        output_row["gate_atomic_prior"] = round(gate_prior, 6)
        output_row["gate_source"] = gate_source
        output_row["passes_atomic_gate"] = (
            "1" if float(message_only_prior["p_atomic"]) >= gate_prior else "0"
        )

        if resolved_repo and args.fetch_diff:
            # Full Step1 score/tier is computed only when diff is available.
            try:
                git_diff = (
                    local_payload["git_diff"]
                    if local_payload is not None
                    else fetch_diff(resolved_repo, sha)
                )
                output_row["git_diff"] = git_diff
                diff_features = miner.parse_diff(git_diff)
                score, reasons = miner.score_commit(
                    message_features,
                    diff_features,
                    candidate_type=row["type"],
                    signal_context=message_signal_context,
                    message_protocol=message_protocol,
                    scope_protocol=scope_protocol,
                    type_protocol=type_protocol,
                )
                utility, utility_reasons = miner.utility_score(
                    row["type"],
                    diff_features,
                    scope_protocol=scope_protocol,
                    type_protocol=type_protocol,
                )

                prior_info = miner.atomic_prior(
                    message_features=message_features,
                    candidate_type=row["type"],
                    diff_features=diff_features,
                    calibration=calibration,
                    global_stats=calibration_global_stats,
                    signal_context=message_signal_context,
                    message_protocol=message_protocol,
                    scope_protocol=scope_protocol,
                    type_protocol=type_protocol,
                )
                p_atomic = prior_info["p_atomic"]
                tier = miner.assign_atomic_tier(p_atomic, tau_a=tau_a, tau_b=tau_b)

                output_row.update(
                    {
                        "primary_model_mode": "full_diff",
                        "primary_model_role": "primary",
                        "score": score,
                        "utility": utility,
                        "file_count": diff_features["file_count"],
                        "hunk_count": diff_features["hunk_count"],
                        "changed_lines": diff_features["changed_lines"],
                        "roles": ",".join(diff_features["roles"]),
                        "modules": ",".join(sorted(diff_features["module_counts"])),
                        "x_atom": prior_info["x_atom"],
                        "p_raw": round(prior_info["p_raw"], 6),
                        "p_atomic": round(prior_info["p_atomic"], 6),
                        "omega_atomic": round(prior_info["omega_atomic"], 6),
                        "tier": tier,
                        "tier_source": tau_source,
                        "atomic_logit": round(prior_info["atomic_logit"], 6),
                        "atomic_prior": round(prior_info["atomic_prior"], 6),
                        "atomic_prior_calibrated": round(
                            prior_info["atomic_prior_calibrated"], 6
                        ),
                        "atomic_weight": round(prior_info["omega_atomic"], 6),
                        "gate_atomic_prior": round(gate_prior, 6),
                        "gate_source": gate_source,
                        "passes_atomic_gate": "1" if p_atomic >= gate_prior else "0",
                        "full_reasons": ",".join(reasons),
                        "utility_reasons": ",".join(utility_reasons),
                    }
                )
                diff_rows.append(
                    {
                        "sha": sha,
                        "repo": resolved_repo,
                        "commit_message": row["commit_message"],
                        "git_diff": git_diff,
                    }
                )
            except urllib.error.HTTPError as exc:
                output_row["diff_error"] = f"HTTP {exc.code}"
            except Exception as exc:
                if "git_diff" not in output_row and local_payload is not None:
                    output_row["git_diff"] = local_payload["git_diff"]
                output_row["diff_error"] = str(exc)

        rows_out.append(output_row)
        processed_shas.add(sha)

        if index % checkpoint_interval == 0:
            persist_checkpoint()
            print(f"processed={index}", flush=True)

    persist_checkpoint()
    completed = len(processed_shas) == total_candidates
    if completed:
        interrupted_reason = "completed"
        write_status(
            path=status_path,
            total_candidates=total_candidates,
            processed_candidates=len(processed_shas),
            completed=True,
            interrupted_reason=interrupted_reason,
            require_complete=args.require_complete,
            resume_enabled=resume_enabled,
        )
    print(f"processed={len(rows_out)}", flush=True)
    print(f"completed={completed}", flush=True)
    print(result_csv_path.as_posix(), flush=True)
    print(status_path.as_posix(), flush=True)
    if args.require_complete and not completed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
