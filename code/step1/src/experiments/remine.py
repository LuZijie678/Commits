"""
高质量单意图再挖掘脚本

本脚本用于从GitHub仓库中挖掘高质量的单意图候选提交。

功能：
1. 解析仓库元数据：获取star数、fork状态、归档状态
2. 仓库过滤：根据star数和活跃时间过滤
3. 仓库匹配：根据仓库名称匹配提交
4. 活动性检查：检查仓库是否活跃

输出：
- repo_metadata.json: 仓库元数据缓存
- 高质量单意图候选CSV文件
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.pipeline import atomic_mining as miner


USER_AGENT = (
    "Mozilla/5.0 (compatible; CodexResearchBot/1.0)"  # HTTP请求的User-Agent标识
)
# star数正则：从GitHub仓库页面提取star数量
# 匹配: aria-label="1,234 users starred this repository"
STAR_RE = re.compile(r'aria-label="([0-9,]+)\s+user[s]?\s+starred this repository"')
# fork状态正则：从JSON-LD提取fork状态
# 匹配: "isFork":true 或 "isFork":false
FORK_RE = re.compile(r'"isFork":(true|false)')
# 归档状态正则：从JSON-LD提取归档状态
# 匹配: "isArchived":true 或 "isArchived":false
ARCHIVED_RE = re.compile(r'"isArchived":(true|false)')
# 仓库URL正则：从任意GitHub URL提取仓库名（owner/repo格式）
# 支持: https://github.com/owner/repo 或带有其他路径的情况
REPO_URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)")
# commit仓库正则：从commit URL提取仓库名
# 匹配: github.com/owner/repo/commit/xxxxx
COMMIT_REPO_RE = re.compile(r"github\.com/([^/]+/[^/]+)/commit/")
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}  # Atom命名空间（用于RSS解析）
DEFAULT_TARGET_COUNT = 100  # 默认目标候选数量（从候选集中选取的数量上限）
DEFAULT_MIN_STARS = 1000  # 默认最小star数（用于过滤小仓库，低于此值不考虑）
DEFAULT_ACTIVE_YEARS = 2  # 默认活跃年数（用于检查仓库是否在近年内有活动）
DEFAULT_SLEEP_SECONDS = 0.2  # 默认休眠秒数（API调用间隔，避免过快请求被限流）
DEFAULT_HTTP_TIMEOUT_SECONDS = 30  # 默认HTTP超时秒数（单个请求的最大等待时间）
DAYS_PER_YEAR = 365  # 每年天数（用于将年数转换为天数计算活跃时间窗口）
DEFAULT_TOP_REPO_COUNT = 15  # 默认Top仓库数量（摘要报告中展示的仓库数量上限）
CSV_FIELD_SIZE_LIMIT = 2**31 - 1  # CSV字段大小限制（避免大字段导致解析错误）


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    # 创建参数解析器
    parser = argparse.ArgumentParser()
    # 输入CSV文件路径（包含候选提交）
    parser.add_argument(
        "--input",
        default="../../datasets/step1/canonical/annotated_dataset.csv",
    )
    # 种子仓库列表文件路径
    parser.add_argument(
        "--repo-list",
        default="../../datasets/step1/runtime_support/resolved_metadata.csv",
    )
    # 输出目录路径
    parser.add_argument(
        "--output-dir", default="outputs/remine_high_quality_single_intent"
    )
    # 目标候选数量
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    # 最小分数阈值
    parser.add_argument("--min-score", type=int, default=0)
    # 最小原子性先验阈值
    parser.add_argument("--min-atomic-prior", type=float, default=0.0)
    # Tier A阈值
    parser.add_argument("--tau-a", type=float, default=miner.DEFAULT_TAU_A)
    # Tier B阈值
    parser.add_argument("--tau-b", type=float, default=miner.DEFAULT_TAU_B)
    # 校准JSON文件路径
    parser.add_argument("--calibration-json", default="")
    # 最小star数阈值（过滤小仓库）
    parser.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS)
    # 最小活跃年数
    parser.add_argument("--active-years", type=int, default=DEFAULT_ACTIVE_YEARS)
    # 请求间隔秒数（避免API限流）
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    # 可选的UTC参考时间戳
    parser.add_argument(
        "--reference-time-utc",
        default="",
        help="可选的UTC参考时间戳 (ISO8601)。为空时使用当前时间。",
    )
    return parser.parse_args()


def fetch_url(url: str) -> tuple[str, str]:
    """
    获取URL内容

    使用HTTP GET请求获取URL内容，返回响应体和最终URL（考虑重定向）。

    参数:
        url: 目标URL

    返回:
        tuple[str, str]: (响应体, 最终URL)
        - 响应体: UTF-8解码的响应内容
        - 最终URL: 跟随重定向后的实际URL
    """
    # 构建HTTP请求，设置User-Agent避免被拒绝
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # 打开URL并读取响应
    with urllib.request.urlopen(req, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as resp:
        # 解码响应体
        body = resp.read().decode("utf-8", errors="ignore")
        # 获取最终URL（可能因重定向而变化）
        final_url = resp.geturl()
    return body, final_url


def parse_repo_from_url(url: str) -> str:
    """
    从URL提取仓库名

    从各种GitHub URL格式中提取owner/repo：
    - https://github.com/facebook/react -> facebook/react
    - https://github.com/facebook/react/pull/123 -> facebook/react
    - https://github.com/facebook/react/commit/abc -> facebook/react

    参数:
        url: GitHub URL

    返回:
        str: 仓库名（如"facebook/react"），无法提取时返回空字符串
    """
    # 使用正则从标准URL格式提取
    match = REPO_URL_RE.search(url)
    if match:
        return match.group(1)
    # 兼容 owner/repo 直填格式（非 URL）。
    candidate = str(url or "").strip().strip("/")
    if candidate and " " not in candidate and candidate.count("/") == 1:
        return candidate
    return ""
    """
    从URL解析仓库名

    参数:
        url: GitHub仓库URL

    返回:
        str: 仓库名（owner/repo格式）
    """
    match = REPO_URL_RE.search(url)
    return match.group(1) if match else ""


def fetch_repo_page_metadata(repo: str) -> dict:
    """
    获取仓库页面元数据

    从GitHub仓库首页解析star数、fork状态、归档状态

    参数:
        repo: 仓库名（owner/repo格式）

    返回:
        dict: 仓库元数据
    """
    # 构建仓库首页URL
    url = f"https://github.com/{repo}"
    # 获取页面HTML和最终URL（可能因重定向变化）
    html, final_url = fetch_url(url)
    # 从最终URL解析规范化的仓库名
    canonical_repo = parse_repo_from_url(final_url)
    # 使用正则解析star数量
    star_match = STAR_RE.search(html)
    # 使用正则解析fork状态
    fork_match = FORK_RE.search(html)
    # 使用正则解析归档状态
    archived_match = ARCHIVED_RE.search(html)
    # 检查页面中是否有归档提示文本
    archived_text = "This repository was archived by the owner" in html
    # 构建返回的元数据字典
    return {
        "query_repo": repo,  # 原始查询的仓库名
        "canonical_repo": canonical_repo or repo,  # 规范化后的仓库名
        "final_url": final_url,  # 最终URL
        "stars": int(star_match.group(1).replace(",", ""))
        if star_match
        else None,  # star数
        "fork": fork_match.group(1) == "true" if fork_match else None,  # 是否fork
        "archived": archived_text  # 是否归档（优先检查页面文本）
        or (
            archived_match.group(1) == "true" if archived_match else False
        ),  # 或JSON-LD标记
    }


def fetch_atom_updated(repo: str) -> str | None:
    """
    获取仓库最新更新时间

    使用GitHub Atom feed获取仓库最后更新时间

    参数:
        repo: 仓库名

    返回:
        str | None: ISO格式更新时间或None
    """
    # 构建Atom feed URL
    url = f"https://github.com/{repo}/commits.atom"
    # 获取XML内容
    xml_text, _ = fetch_url(url)
    # 解析XML
    root = ET.fromstring(xml_text)
    # 查找updated元素
    updated = root.find("a:updated", ATOM_NS)
    return updated.text if updated is not None else None


def fetch_metadata(repo: str, sleep_seconds: float) -> dict:
    """
    获取仓库元数据

    获取仓库的star数、fork数、更新时间等信息。

    参数:
        repo: 仓库名
        sleep_seconds: 请求间隔秒数

    返回:
        dict: 仓库元数据
    """
    # 初始化结果字典，包含原始查询仓库名
    result = {"query_repo": repo}
    try:
        # 获取仓库页面元数据（star、fork、archived等）
        page_meta = fetch_repo_page_metadata(repo)
        result.update(page_meta)
        # 尝试获取最新更新时间
        try:
            # 使用规范化后的仓库名获取Atom feed
            result["feed_updated"] = fetch_atom_updated(result["canonical_repo"])
        except Exception as exc:
            # 记录错误但继续
            result["feed_updated_error"] = str(exc)
            result["feed_updated"] = None
    except urllib.error.HTTPError as exc:
        # 记录HTTP错误
        result["error"] = f"HTTP {exc.code}"
    except Exception as exc:
        # 记录其他错误
        result["error"] = str(exc)
    # 休眠指定秒数，避免API限流
    time.sleep(sleep_seconds)
    return result


def load_commit_rows(path: Path) -> list[dict]:
    """
    加载提交行

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表
    """
    # 设置CSV字段大小限制
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并读取
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_seed_repos(path: Path) -> list[str]:
    """
    加载种子仓库列表

    参数:
        path: 仓库列表CSV文件路径

    返回:
        list[str]: 仓库名列表
    """
    # 打开文件并读取
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        repos = []
        for row in reader:
            # 尝试从多个字段提取仓库名
            repo = (
                parse_repo_from_url(row.get("repo", ""))
                or parse_repo_from_url(row.get("resolved_repo", ""))
                or parse_repo_from_url(row.get("commit_url", ""))
            )
            if repo:
                repos.append(repo)
        return repos


def extract_commit_repo(commit_url: str) -> str:
    """
    从提交URL提取仓库名

    参数:
        commit_url: 提交URL

    返回:
        str: 仓库名（如facebook/react）
    """
    # 使用正则提取
    match = COMMIT_REPO_RE.search(commit_url)
    return match.group(1) if match else ""


def load_cache(path: Path) -> dict[str, dict]:
    """
    加载缓存文件

    参数:
        path: 缓存JSON文件路径

    返回:
        dict[str, dict]: 仓库名到元数据的映射
    """
    # 如果文件不存在，返回空字典
    if not path.exists():
        return {}
    # 读取并解析JSON
    items = json.loads(path.read_text(encoding="utf-8"))
    # 转换为以query_repo为键的字典
    return {item["query_repo"]: item for item in items}


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    """
    保存缓存到文件

    参数:
        path: 输出文件路径
        cache: 缓存字典
    """
    # 将字典转换为列表并按仓库名排序
    rows = [cache[key] for key in sorted(cache)]
    # 写入JSON文件
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_metadata(
    repos: list[str], cache_path: Path, sleep_seconds: float
) -> dict[str, dict]:
    """
    确保仓库元数据完整

    加载缓存，对于缺失的仓库逐个获取元数据。

    参数:
        repos: 仓库列表
        cache_path: 缓存文件路径
        sleep_seconds: 请求间隔秒数

    返回:
        dict[str, dict]: 仓库名到元数据的映射
    """
    # 加载现有缓存
    cache = load_cache(cache_path)
    # 找出缺失的仓库
    missing = [repo for repo in repos if repo not in cache]
    # 逐个获取缺失仓库的元数据
    for index, repo in enumerate(missing, start=1):
        print(f"fetching {index}/{len(missing)} {repo}")
        cache[repo] = fetch_metadata(repo, sleep_seconds=sleep_seconds)
        # 每10个或最后一个时保存缓存
        if index % 10 == 0 or index == len(missing):
            save_cache(cache_path, cache)
    # 最终保存一次
    save_cache(cache_path, cache)
    return cache


def parse_dt(value: str | None) -> datetime | None:
    """
    解析ISO格式日期时间

    参数:
        value: ISO格式日期字符串

    返回:
        datetime | None: 解析后的datetime对象
    """
    # 空值返回None
    if not value:
        return None
    # 解析ISO格式，替换Z为UTC时区
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_recent(value: str | None, years: int, now: datetime) -> bool:
    """
    检查日期是否在指定年数内

    参数:
        value: ISO格式日期字符串
        years: 年数阈值
        now: 当前时间

    返回:
        bool: 是否在活跃期内
    """
    # 解析日期
    dt = parse_dt(value)
    if dt is None:
        return False
    # 计算时间差阈值
    threshold = timedelta(days=DAYS_PER_YEAR * years)
    return dt >= now - threshold


def repo_passes(meta: dict, min_stars: int, active_years: int, now: datetime) -> bool:
    """
    检查仓库是否满足质量要求

    参数:
        meta: 仓库元数据
        min_stars: 最小star数
        active_years: 最小活跃年数
        now: 当前时间

    返回:
        bool: 是否通过质量检查
    """
    # 检查是否有错误
    if meta.get("error"):
        return False
    # 检查star数是否足够
    if meta.get("stars") is None or meta["stars"] < min_stars:
        return False
    # 排除fork的仓库
    if meta.get("fork") is True:
        return False
    # 排除已归档的仓库
    if meta.get("archived") is True:
        return False
    # 检查最近活跃时间
    if not is_recent(meta.get("feed_updated"), active_years, now):
        return False
    return True


def canonicalize_rows(rows: list[dict], repo_meta: dict[str, dict]) -> list[dict]:
    """
    规范化候选行

    根据仓库元数据过滤和规范化候选行。

    参数:
        rows: 候选行列表
        repo_meta: 仓库元数据映射

    返回:
        list[dict]: 规范化后的行列表
    """
    enriched = []
    # 遍历每行，从commit_url提取仓库名并附加元数据
    for row in rows:
        # 从commit_url提取仓库名
        query_repo = extract_commit_repo(row["commit_url"])
        # 获取仓库元数据（缺失时使用默认错误信息）
        meta = repo_meta.get(
            query_repo, {"query_repo": query_repo, "error": "missing_metadata"}
        )
        # 复制原始行
        copied = dict(row)
        # 附加仓库信息
        copied["query_repo"] = query_repo
        copied["canonical_repo"] = meta.get("canonical_repo", query_repo)
        copied["repo_stars"] = meta.get("stars")
        copied["repo_fork"] = meta.get("fork")
        copied["repo_archived"] = meta.get("archived")
        copied["repo_feed_updated"] = meta.get("feed_updated")
        copied["repo_error"] = meta.get("error")
        enriched.append(copied)
    return enriched


def summarize_selected(
    rows: list[dict],
    repo_meta: dict[str, dict],
    path: Path,
    args: argparse.Namespace,
    filtered_row_count: int,
    seed_repo_pass_count: int,
    tau_a: float,
    tau_b: float,
) -> None:
    """
    写入选择摘要

    生成Markdown格式的摘要报告，包含类型分布、仓库分布等统计信息。

    参数:
        rows: 候选行列表
        repo_meta: 仓库元数据映射
        path: 输出文件路径
        args: 命令行参数
        filtered_row_count: 过滤后的行数
        seed_repo_pass_count: 通过种子仓库检查的行数
        tau_a: Tier A阈值
        tau_b: Tier B阈值
    """
    # 统计类型分布
    type_counter = Counter(row["type"] for row in rows)
    # 统计仓库分布
    repo_counter = Counter(row["repo"] for row in rows)
    # 统计角色分布
    role_counter = Counter(row["roles"] for row in rows)
    # 构建摘要内容
    lines = [
        "# High-Quality Single-Intent Re-mining Summary",
        "",
        f"- Input dataset: `{args.input}`",
        f"- Seed CCS repo list: `{args.repo_list}`",
        f"- Repo filter: `stars >= {args.min_stars}`, `not fork`, `not archived`, `active within {args.active_years} years`",
        f"- Atomic prior gate: `>= {args.min_atomic_prior}`",
        f"- Tier thresholds: `tau_a={tau_a}`, `tau_b={tau_b}`",
        f"- Qualified seed repos: `{seed_repo_pass_count}`",
        f"- Filtered commit rows before mining: `{filtered_row_count}`",
        f"- Selected candidates: `{len(rows)}`",
        "",
        "## Type Distribution",
        "",
    ]
    # 添加类型分布
    for key, value in type_counter.most_common():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Repo Distribution", ""])
    # 添加仓库分布（限制数量）
    for key, value in repo_counter.most_common(DEFAULT_TOP_REPO_COUNT):
        meta = repo_meta.get(key, {})
        stars = meta.get("stars", "NA")
        lines.append(f"- `{key}`: {value} commits, stars `{stars}`")
    lines.extend(["", "## Role Distribution", ""])
    # 添加角色分布
    for key, value in role_counter.most_common():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Top Examples", ""])
    # 添加Top 10示例
    for row in rows[:10]:
        lines.append(
            f"- prior `{row.get('atomic_prior_calibrated', '')}` tier `{row.get('tier', '')}` | score `{row['score']}` utility `{row['utility']}` | `{row['repo']}` | `{row['subject']}` | files `{row['file_count']}` | lines `{row['changed_lines']}`"
        )
    # 写入文件
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_candidate_repos(
    candidates: list[dict], repo_meta_by_query: dict[str, dict]
) -> list[dict]:
    """
    规范化候选仓库名

    将原始仓库名替换为规范化的canonical_repo。

    参数:
        candidates: 候选行列表
        repo_meta_by_query: 仓库元数据映射

    返回:
        list[dict]: 规范化后的行列表
    """
    normalized = []
    # 遍历每个候选，将原始repo替换为规范化仓库名
    for item in candidates:
        copied = dict(item)
        raw_repo = copied.get("repo", "")
        meta = repo_meta_by_query.get(raw_repo)
        # 如果有元数据且有canonical_repo，则进行替换
        if meta and meta.get("canonical_repo"):
            copied["repo_raw"] = raw_repo  # 保存原始仓库名
            copied["repo"] = meta["canonical_repo"]  # 替换为规范化名称
        normalized.append(copied)
    return normalized


def main() -> None:
    """
    主函数：执行高质量单意图重挖掘

    流程：
    1. 加载候选和种子仓库
    2. 获取仓库元数据
    3. 规范化仓库名并过滤
    4. 执行挖掘
    5. 写入输出文件
    """
    # 解析命令行参数
    args = parse_args()
    # 确定参考时间（使用指定时间或当前UTC时间）
    now = datetime.now(timezone.utc)
    if args.reference_time_utc:
        now = datetime.fromisoformat(args.reference_time_utc.replace("Z", "+00:00"))
    # 创建输出目录（如果不存在）
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 加载校准文件（如果有指定）
    calibration = (
        miner.load_calibration(args.calibration_json) if args.calibration_json else None
    )
    # 解析Tier阈值（支持校准后的阈值）
    tau_a, tau_b = miner.resolve_thresholds(
        calibration=calibration, tau_a=args.tau_a, tau_b=args.tau_b
    )

    # 加载候选提交数据（CSV格式）
    rows = load_commit_rows(Path(args.input))
    # 加载种子仓库列表
    seed_repos = load_seed_repos(Path(args.repo_list))
    # 从所有提交中提取仓库名（去重并排序）
    commit_repos = sorted(
        {
            extract_commit_repo(row["commit_url"])
            for row in rows
            if extract_commit_repo(row["commit_url"])
        }
    )

    # 合并种子仓库和提交仓库，组成需要获取元数据的完整列表
    all_repos = sorted(set(seed_repos) | set(commit_repos))
    # 缓存文件路径：存储仓库元数据避免重复请求
    cache_path = output_dir / "repo_metadata.json"
    # 确保所有仓库都有元数据（从缓存加载或请求获取）
    repo_meta_by_query = ensure_metadata(
        all_repos, cache_path=cache_path, sleep_seconds=args.sleep_seconds
    )

    # 筛选符合质量要求的种子仓库（star数、fork状态、归档状态、活跃时间）
    qualified_seed_repos = {
        meta["canonical_repo"]
        for meta in (
            repo_meta_by_query[repo]
            for repo in seed_repos
            if repo in repo_meta_by_query
        )
        if repo_passes(
            meta, min_stars=args.min_stars, active_years=args.active_years, now=now
        )
    }

    # 规范化候选行：附加仓库元数据信息
    enriched_rows = canonicalize_rows(rows, repo_meta_by_query)
    # 过滤：只保留来自合格仓库的提交
    filtered_rows = [
        row for row in enriched_rows if row["canonical_repo"] in qualified_seed_repos
    ]

    # 执行挖掘：根据阈值筛选高质量单意图候选
    mined = miner.mine_rows(
        filtered_rows,
        min_score=args.min_score,
        min_atomic_prior=args.min_atomic_prior,
        tau_a=tau_a,
        tau_b=tau_b,
        calibration=calibration,
    )
    # 规范化候选仓库名：将原始仓库名替换为规范化的canonical_repo
    mined = normalize_candidate_repos(mined, repo_meta_by_query)
    # 截取目标数量的候选
    selected = mined[: args.target_count]

    # 写入输出文件：候选CSV和摘要报告
    miner.write_csv(output_dir / "single_intent_candidates.csv", selected)
    miner.write_csv(output_dir / "all_passing_candidates.csv", mined)
    # 写入摘要Markdown报告
    summarize_selected(
        selected,
        {
            meta["canonical_repo"]: meta
            for meta in repo_meta_by_query.values()
            if meta.get("canonical_repo")
        },
        output_dir / "summary.md",
        args=args,
        filtered_row_count=len(filtered_rows),
        seed_repo_pass_count=len(qualified_seed_repos),
        tau_a=tau_a,
        tau_b=tau_b,
    )

    # 打印摘要信息到控制台
    print(f"qualified_seed_repos={len(qualified_seed_repos)}")
    print(f"filtered_rows={len(filtered_rows)}")
    print(f"passing_candidates={len(mined)}")
    print(f"selected={len(selected)}")


if __name__ == "__main__":
    main()
