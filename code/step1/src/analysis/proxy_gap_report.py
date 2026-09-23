from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    """将数据写入 JSON 文件（使用 UTF-8 编码）
    参数: path - 输出文件路径, payload - 要写入的数据字典
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """将文本内容写入文件（使用 UTF-8 编码）
    参数: path - 输出文件路径, content - 要写入的文本内容
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_proxy_gap_markdown(*, payload: dict, observed_tier_b: int) -> str:
    """构建 proxy gap 分析的 Markdown 格式报告
    参数: payload - 分析结果数据字典, observed_tier_b - 实际观测到的 tier B 数量
    返回: Markdown 格式的报告文本
    """
    # 获取 full-diff tier 分布统计
    resolved_tier_counts = dict(
        (payload.get("conversion_metrics") or {}).get("observed_full_diff_tier_counts")
        or {}
    )
    lines = [
        "# Proxy Gap Analysis",
        "",
        f"- Selection count: `{payload.get('selection_count')}`",
        f"- Resolved count: `{payload.get('resolved_count')}`",
        f"- Audit target (`Tier-B` / Validate Mid Band): `{payload.get('audit_target')}`",
        f"- Message-only proxy AUC: `{(payload.get('proxy_probability_gap') or {}).get('message_only_auc')}`",
        f"- Full-diff primary AUC: `{(payload.get('proxy_probability_gap') or {}).get('full_diff_auc')}`",
        f"- Message-only proxy Brier: `{(payload.get('proxy_probability_gap') or {}).get('message_only_brier')}`",
        f"- Full-diff primary Brier: `{(payload.get('proxy_probability_gap') or {}).get('full_diff_brier')}`",
        f"- Message-only proxy log-loss: `{(payload.get('proxy_probability_gap') or {}).get('message_only_logloss')}`",
        f"- Full-diff primary log-loss: `{(payload.get('proxy_probability_gap') or {}).get('full_diff_logloss')}`",
        f"- Tier consistency: `{(payload.get('conversion_metrics') or {}).get('tier_consistency')}`",
        f"- Missing-tier policy: `{(payload.get('conversion_metrics') or {}).get('missing_tier_policy')}`",
        f"- Unknown rate: `{(payload.get('conversion_metrics') or {}).get('unknown_rate')}`",
        f"- Downgrade rate (`message_only A -> full_diff C`): `{(payload.get('conversion_metrics') or {}).get('downgrade_rate_message_only_a_to_full_diff_c')}`",
        f"- Expected Tier-B yield from reference table: `{(payload.get('feasibility') or {}).get('expected_target_tier_yield')}`",
        f"- Conservative Tier-B lower bound (Wilson-based): `{(payload.get('feasibility') or {}).get('conservative_target_tier_lower_bound')}`",
        f"- Observed full-diff Tier-B yield: `{observed_tier_b}`",
        f"- Observed full-diff tier counts: `{resolved_tier_counts}`",
        "",
        "## Interpretation",
        "",
        f"- Classification: `{(payload.get('conclusion') or {}).get('classification')}`",
        f"- Reason: {(payload.get('conclusion') or {}).get('reason')}",
        f"- Paper sentence: {(payload.get('conclusion') or {}).get('paper_sentence')}",
        f"- Policy note: {(payload.get('conclusion') or {}).get('policy_note')}",
        "- This report keeps the static pipeline unchanged and quantifies the proxy gap between message-only selection-side signals and post-enrich full-diff validate tiers.",
        "- Main conversion statistics use `missing_as_unknown`; `missing_as_C` is reported only as sensitivity analysis.",
        "- `expected_target_tier_yield` and `conservative_target_tier_lower_bound` come from the annotated reference table grouped by `type x message_only_probability_band`.",
        "- `observed_tier_b_yield` is the realized full-diff Tier-B count in this run.",
    ]
    return "\n".join(lines) + "\n"
