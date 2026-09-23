from __future__ import annotations


DEFAULT_MISSING_TIER_POLICY = "missing_as_unknown"


def derive_proxy_conclusion(payload: dict) -> dict:
    """根据 proxy gap 分析结果推导最终分类结论
    参数: payload - 完整的分析结果数据
    返回: 包含分类、理由、论文句子和政策说明的字典
    """
    probability_gap = payload.get("proxy_probability_gap") or {}
    conversion_metrics = payload.get("conversion_metrics") or {}
    tier_consistency = conversion_metrics.get("tier_consistency")
    downgrade_rate = conversion_metrics.get(
        "downgrade_rate_message_only_a_to_full_diff_c"
    )
    missing_tier_policy = str(
        conversion_metrics.get("missing_tier_policy", DEFAULT_MISSING_TIER_POLICY)
    )
    unknown_rate = conversion_metrics.get("unknown_rate")
    message_only_auc = probability_gap.get("message_only_auc")
    full_diff_auc = probability_gap.get("full_diff_auc")

    # 默认结论：可用但有风险
    classification = "usable_with_risk"
    reason = (
        "Proxy quality is mixed; message-only should stay subordinate to full-diff."
    )
    paper_sentence = "The message-only proxy is usable for broad prefiltering but remains subordinate to the full-diff primary model."
    policy_note = "Primary proxy-gap statistics use missing_as_unknown; missing_as_C is reported only as a sensitivity analysis."

    # 判断条件：一致性>=0.8, 降级率<=5%, AUC>=0.85 -> 可用作可靠预过滤器
    if (
        tier_consistency is not None
        and downgrade_rate is not None
        and message_only_auc is not None
        and full_diff_auc is not None
        and tier_consistency >= 0.8
        and downgrade_rate <= 0.05
        and message_only_auc >= 0.85
    ):
        classification = "reliable_prefilter"
        reason = "Proxy fidelity is strong enough for broad low-cost prefiltering."
        paper_sentence = "The message-only proxy is suitable as a broad prefilter, but it should still remain subordinate to the full-diff primary model."
    # 判断条件：一致性<0.65 或 降级率>15% 或 AUC差距>0.15 -> 不可靠
    elif (
        tier_consistency is not None
        and downgrade_rate is not None
        and (
            tier_consistency < 0.65
            or downgrade_rate > 0.15
            or (
                message_only_auc is not None
                and full_diff_auc is not None
                and (full_diff_auc - message_only_auc) > 0.15
            )
        )
    ):
        classification = "not_reliable_for_atomic_filtering"
        reason = (
            "Proxy fidelity degrades too much relative to the full-diff primary model."
        )
        paper_sentence = "The message-only proxy is not reliable as a high-confidence atomicity decision rule and should be restricted to loose prefiltering."

    return {
        "classification": classification,
        "reason": reason,
        "paper_sentence": paper_sentence,
        "policy_note": policy_note,
        "missing_tier_policy": missing_tier_policy,
        "unknown_rate": unknown_rate,
    }


def build_proxy_quality_payload(
    *,
    selection_count: int,
    resolved_count: int,
    proxy_probability_gap: dict,
    conversion_metrics: dict,
    feasibility: dict | None = None,
    probability_bins: list[dict] | None = None,
    audit_target: int | None = None,
    sensitivity_analysis: dict | None = None,
) -> dict:
    """构建完整的 proxy quality 分析数据载荷
    参数: 各分析模块的统计结果
    返回: 包含所有分析结果的完整数据字典
    """
    payload = {
        "selection_count": int(selection_count),
        "resolved_count": int(resolved_count),
        "audit_target": int(audit_target) if audit_target is not None else None,
        "probability_bins": list(probability_bins or []),
        "proxy_probability_gap": dict(proxy_probability_gap),
        "conversion_metrics": dict(conversion_metrics),
    }
    if feasibility is not None:
        payload["feasibility"] = dict(feasibility)
    if sensitivity_analysis is not None:
        payload["sensitivity_analysis"] = dict(sensitivity_analysis)
    # 自动推导分类结论
    payload["conclusion"] = derive_proxy_conclusion(payload)
    return payload
