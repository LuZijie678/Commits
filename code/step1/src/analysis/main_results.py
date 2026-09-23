from __future__ import annotations

import json
from pathlib import Path


def build_main_results_payload(
    *,
    primary_artifact: dict,
    validate_precision_report: dict | None,
) -> dict:
    """构建主结果数据载荷，包含规则 vs 模型对比、特征消融和独立审计结果
    参数: primary_artifact - 主要分析结果, validate_precision_report - 验证精确度报告
    返回: 包含各维度对比数据的字典
    """
    # 提取主要指标
    primary_metrics = dict((primary_artifact or {}).get("metrics") or {})
    rule_vs_model = dict(primary_metrics.get("rule_only_vs_model") or {})
    feature_reduced = dict(primary_metrics.get("feature_reduced_model_ablation") or {})
    if not rule_vs_model:
        raise ValueError(
            "main results require primary artifact metrics.rule_only_vs_model"
        )
    if not feature_reduced:
        raise ValueError(
            "main results require primary artifact metrics.feature_reduced_model_ablation"
        )
    coverage = dict(primary_metrics.get("coverage_metrics") or {})
    reliability = dict(primary_metrics.get("reliability_report") or {})
    reduced_rule_vs_model = dict(feature_reduced.get("rule_only_vs_model") or {})
    reduced_reliability = dict(feature_reduced.get("reliability_report") or {})

    # 构建规则-only 指标（无概率可靠性指标，因为是三态选择器）
    rule_only = {
        "tier_a_precision": rule_vs_model.get("rule_positive_precision"),
        "tier_a_recall": rule_vs_model.get("rule_positive_recall"),
        "tier_a_yield": rule_vs_model.get("rule_positive_count"),
        "gold_positive_count": rule_vs_model.get("gold_positive_count"),
        "rule_abstain_rate": rule_vs_model.get("rule_abstain_rate"),
        "brier": None,
        "logloss": None,
        "ece": None,
        "mce": None,
        "probabilistic_metrics_applicable": False,
    }
    # 构建模型在规则标签上的指标
    model_on_rule_labels = {
        "tier_a_precision": rule_vs_model.get("model_positive_precision"),
        "tier_a_recall": rule_vs_model.get("model_positive_recall"),
        "tier_a_yield": rule_vs_model.get("model_positive_count"),
        "gold_positive_count": rule_vs_model.get("gold_positive_count"),
        "positive_support": coverage.get("positive_support"),
        "tier_a_positive_recall_from_thresholds": coverage.get(
            "tier_a_positive_recall"
        ),
        "tier_b_or_higher_positive_recall": coverage.get(
            "tier_b_or_higher_positive_recall"
        ),
        "brier": primary_metrics.get("calibrated_brier_eval"),
        "logloss": primary_metrics.get("calibrated_logloss_eval"),
        "ece": reliability.get("ece"),
        "mce": reliability.get("mce"),
        "probabilistic_metrics_applicable": True,
    }
    # 构建特征消融模型指标
    feature_reduced_model = {
        "tier_a_precision": reduced_rule_vs_model.get("model_positive_precision"),
        "tier_a_recall": reduced_rule_vs_model.get("model_positive_recall"),
        "tier_a_yield": reduced_rule_vs_model.get("model_positive_count"),
        "gold_positive_count": reduced_rule_vs_model.get("gold_positive_count"),
        "brier": feature_reduced.get("calibrated_brier_eval"),
        "logloss": feature_reduced.get("calibrated_logloss_eval"),
        "ece": reduced_reliability.get("ece"),
        "mce": reduced_reliability.get("mce"),
        "removed_features": list(feature_reduced.get("removed_features") or []),
        "retained_feature_count": feature_reduced.get("retained_feature_count"),
        "probabilistic_metrics_applicable": True,
    }

    # 提取关键指标用于计算增益
    rule_precision = rule_only.get("tier_a_precision")
    model_precision = model_on_rule_labels.get("tier_a_precision")
    rule_recall = rule_only.get("tier_a_recall")
    model_recall = model_on_rule_labels.get("tier_a_recall")
    rule_yield = rule_only.get("tier_a_yield")
    model_yield = model_on_rule_labels.get("tier_a_yield")
    reduced_precision = feature_reduced_model.get("tier_a_precision")
    reduced_recall = feature_reduced_model.get("tier_a_recall")
    reduced_yield = feature_reduced_model.get("tier_a_yield")

    # 计算模型相对规则的各项增益
    gain_summary = {
        "tier_a_precision_gain_model_minus_rule": (
            None
            if rule_precision is None or model_precision is None
            else float(model_precision) - float(rule_precision)
        ),
        "tier_a_recall_gain_model_minus_rule": (
            None
            if rule_recall is None or model_recall is None
            else float(model_recall) - float(rule_recall)
        ),
        "tier_a_yield_gain_model_minus_rule": (
            None
            if rule_yield is None or model_yield is None
            else int(model_yield) - int(rule_yield)
        ),
        "tier_a_precision_gain_reduced_minus_rule": (
            None
            if rule_precision is None or reduced_precision is None
            else float(reduced_precision) - float(rule_precision)
        ),
        "tier_a_recall_gain_reduced_minus_rule": (
            None
            if rule_recall is None or reduced_recall is None
            else float(reduced_recall) - float(rule_recall)
        ),
        "tier_a_yield_gain_reduced_minus_rule": (
            None
            if rule_yield is None or reduced_yield is None
            else int(reduced_yield) - int(rule_yield)
        ),
        "tier_a_precision_delta_full_minus_reduced": (
            None
            if model_precision is None or reduced_precision is None
            else float(model_precision) - float(reduced_precision)
        ),
        "tier_a_recall_delta_full_minus_reduced": (
            None
            if model_recall is None or reduced_recall is None
            else float(model_recall) - float(reduced_recall)
        ),
        "tier_a_yield_delta_full_minus_reduced": (
            None
            if model_yield is None or reduced_yield is None
            else int(model_yield) - int(reduced_yield)
        ),
        "summary": (
            "Model-vs-rule comparison is unavailable."
            if rule_precision is None or model_precision is None
            else (
                "Full model improves over rule-only, and feature ablation quantifies how much of that gain survives after removing rule-adjacent features."
                if (
                    (
                        model_recall is not None
                        and rule_recall is not None
                        and float(model_recall) >= float(rule_recall)
                    )
                    and float(model_precision) >= float(rule_precision)
                )
                else "Model does not dominate rule-only on all Tier-A metrics."
            )
        ),
    }

    # 提取独立审计精确度报告
    validate_precision_report = dict(validate_precision_report or {})
    tier_a_report = dict(validate_precision_report.get("tier_a") or {})
    tier_b_report = dict(validate_precision_report.get("tier_b") or {})
    return {
        "artifact_version": "step1_rule_model_main_results_v1",
        "rule_model_comparison": {
            "evaluation_split_role": "evaluation",
            "rule_only": rule_only,
            "model_on_rule_labels": model_on_rule_labels,
            "feature_reduced_model": feature_reduced_model,
            "gain_summary": gain_summary,
        },
        "independent_audit_precision": {
            "tier_a_precision": tier_a_report.get("precision"),
            "tier_a_sample_count": tier_a_report.get("sample_count"),
            "tier_b_precision": tier_b_report.get("precision"),
            "tier_b_sample_count": tier_b_report.get("sample_count"),
        },
    }


def write_main_results(*, output_dir: Path, payload: dict) -> dict[str, str]:
    """将主结果写入 JSON 和 Markdown 文件
    参数: output_dir - 输出目录, payload - 结果数据字典
    返回: JSON 和 Markdown 文件路径的字典
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "main_results.json"
    md_path = output_dir / "main_results.md"
    # 写入 JSON 文件
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 提取各部分数据用于 Markdown 报告
    comparison = dict(payload.get("rule_model_comparison") or {})
    rule_only = dict(comparison.get("rule_only") or {})
    model = dict(comparison.get("model_on_rule_labels") or {})
    reduced = dict(comparison.get("feature_reduced_model") or {})
    gain = dict(comparison.get("gain_summary") or {})
    audit = dict(payload.get("independent_audit_precision") or {})
    # 构建 Markdown 表格和说明
    lines = [
        "# Step1 Main Results",
        "",
        "## Rule-only vs Model",
        "",
        "| Group | Tier-A precision | Tier-A recall | Tier-A yield | Brier | ECE |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Rule-only | `{rule_only.get('tier_a_precision')}` | `{rule_only.get('tier_a_recall')}` | `{rule_only.get('tier_a_yield')}` | `NA` | `NA` |",
        f"| Model-on-rule-labels | `{model.get('tier_a_precision')}` | `{model.get('tier_a_recall')}` | `{model.get('tier_a_yield')}` | `{model.get('brier')}` | `{model.get('ece')}` |",
        f"| Feature-reduced Model | `{reduced.get('tier_a_precision')}` | `{reduced.get('tier_a_recall')}` | `{reduced.get('tier_a_yield')}` | `{reduced.get('brier')}` | `{reduced.get('ece')}` |",
        "",
        "## Gain Summary",
        "",
        f"- Tier-A precision gain (model - rule): `{gain.get('tier_a_precision_gain_model_minus_rule')}`",
        f"- Tier-A recall gain (model - rule): `{gain.get('tier_a_recall_gain_model_minus_rule')}`",
        f"- Tier-A yield gain (model - rule): `{gain.get('tier_a_yield_gain_model_minus_rule')}`",
        f"- Tier-A precision gain (feature-reduced - rule): `{gain.get('tier_a_precision_gain_reduced_minus_rule')}`",
        f"- Tier-A recall gain (feature-reduced - rule): `{gain.get('tier_a_recall_gain_reduced_minus_rule')}`",
        f"- Tier-A yield gain (feature-reduced - rule): `{gain.get('tier_a_yield_gain_reduced_minus_rule')}`",
        f"- Tier-A precision delta (full - feature-reduced): `{gain.get('tier_a_precision_delta_full_minus_reduced')}`",
        f"- Tier-A recall delta (full - feature-reduced): `{gain.get('tier_a_recall_delta_full_minus_reduced')}`",
        f"- Tier-A yield delta (full - feature-reduced): `{gain.get('tier_a_yield_delta_full_minus_reduced')}`",
        f"- Summary: {gain.get('summary')}",
        "",
        "## Independent Audit Precision",
        "",
        f"- Tier-A precision: `{audit.get('tier_a_precision')}`",
        f"- Tier-A sample count: `{audit.get('tier_a_sample_count')}`",
        f"- Tier-B precision: `{audit.get('tier_b_precision')}`",
        f"- Tier-B sample count: `{audit.get('tier_b_sample_count')}`",
        "",
        "## Feature Ablation",
        "",
        f"- Removed rule-adjacent features: `{reduced.get('removed_features')}`",
        f"- Retained feature count: `{reduced.get('retained_feature_count')}`",
        "",
        "- Rule-only is reported as a tri-state selector; probabilistic reliability metrics are therefore `NA` rather than back-filled with an arbitrary score proxy.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path.as_posix(), "markdown": md_path.as_posix()}
