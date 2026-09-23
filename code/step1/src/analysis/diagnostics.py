from __future__ import annotations

import json
from pathlib import Path


def build_calibration_diagnostics_payload(
    *,
    primary_artifact: dict,
    proxy_artifact: dict,
    annotation_agreement: dict | None = None,
) -> dict:
    """构建校准诊断数据载荷，包含主模型、代理模型、损失对比和标注一致性
    参数: primary_artifact - 主模型结果, proxy_artifact - 代理模型结果
          annotation_agreement - 标注一致性数据（可选）
    返回: 包含诊断信息的字典
    """
    # 提取主模型和代理模型的指标
    primary_metrics = dict((primary_artifact or {}).get("metrics") or {})
    proxy_metrics = dict((proxy_artifact or {}).get("metrics") or {})

    # 主模型的原始和校准损失
    primary_loss = {
        "raw_brier_eval": primary_metrics.get("raw_brier_eval"),
        "calibrated_brier_eval": primary_metrics.get("calibrated_brier_eval"),
        "raw_logloss_eval": primary_metrics.get("raw_logloss_eval"),
        "calibrated_logloss_eval": primary_metrics.get("calibrated_logloss_eval"),
    }
    # 代理模型的原始和校准损失
    proxy_loss = {
        "raw_brier_eval": proxy_metrics.get("raw_brier_eval"),
        "calibrated_brier_eval": proxy_metrics.get("calibrated_brier_eval"),
        "raw_logloss_eval": proxy_metrics.get("raw_logloss_eval"),
        "calibrated_logloss_eval": proxy_metrics.get("calibrated_logloss_eval"),
    }

    # 提取校准后的指标用于计算差距
    calibrated_primary_brier = primary_loss.get("calibrated_brier_eval")
    calibrated_proxy_brier = proxy_loss.get("calibrated_brier_eval")
    calibrated_primary_logloss = primary_loss.get("calibrated_logloss_eval")
    calibrated_proxy_logloss = proxy_loss.get("calibrated_logloss_eval")

    # 计算 Brier 分数差距（主模型 - 代理模型）
    if calibrated_primary_brier is not None and calibrated_proxy_brier is not None:
        brier_delta = float(calibrated_primary_brier) - float(calibrated_proxy_brier)
    else:
        brier_delta = None

    # 计算 LogLoss 差距（主模型 - 代理模型）
    if calibrated_primary_logloss is not None and calibrated_proxy_logloss is not None:
        logloss_delta = float(calibrated_primary_logloss) - float(
            calibrated_proxy_logloss
        )
    else:
        logloss_delta = None

    # 附录声明：说明各指标的来源和含义
    appendix_claims = [
        {
            "id": "primary-calibration-split-isolation",
            "text": "Primary calibration diagnostics are computed after strict protocol/train/calibration/evaluation split isolation.",
        },
        {
            "id": "rule-vs-model",
            "text": "Rule-only versus model metrics quantify whether the learned scorer improves over the weak-label protocol itself.",
        },
        {
            "id": "proxy-vs-primary",
            "text": "Primary-versus-proxy loss deltas summarize the information loss introduced by the message-only route.",
        },
        {
            "id": "annotation-agreement",
            "text": "Annotation agreement metrics summarize overlap consistency and adjudication coverage for the Step1 ground-truth protocol.",
        },
    ]

    # 标注一致性摘要
    annotation_agreement_summary = {
        "status": str((annotation_agreement or {}).get("status", "unavailable")),
        "shared_sha_count": (annotation_agreement or {}).get("shared_sha_count"),
        "raw_agreement": (annotation_agreement or {}).get("raw_agreement"),
        "cohen_kappa": (annotation_agreement or {}).get("cohen_kappa"),
        "adjudication_coverage": (annotation_agreement or {}).get(
            "adjudication_coverage"
        ),
        "confusion_summary": dict(
            (annotation_agreement or {}).get("confusion_summary") or {}
        ),
    }

    # 组装最终输出
    return {
        "primary_model": {
            "artifact_version": str(
                (primary_artifact or {}).get("artifact_version", "")
            ),
            "thresholds": dict((primary_artifact or {}).get("thresholds") or {}),
            "coverage_metrics": dict(primary_metrics.get("coverage_metrics") or {}),
            "reliability_report": dict(primary_metrics.get("reliability_report") or {}),
            "rule_only_vs_model": dict(primary_metrics.get("rule_only_vs_model") or {}),
            "loss_metrics": primary_loss,
            "weak_label_source": str(
                ((primary_artifact or {}).get("fit_config") or {}).get(
                    "weak_label_source", ""
                )
            ),
            "annotated_split_roles": dict(
                ((primary_artifact or {}).get("fit_config") or {}).get(
                    "annotated_split_roles"
                )
                or {}
            ),
        },
        "proxy_model": {
            "artifact_version": str((proxy_artifact or {}).get("artifact_version", "")),
            "thresholds": dict((proxy_artifact or {}).get("thresholds") or {}),
            "loss_metrics": proxy_loss,
            "annotated_split_roles": dict(
                ((proxy_artifact or {}).get("fit_config") or {}).get(
                    "annotated_split_roles"
                )
                or {}
            ),
        },
        "side_by_side_delta_summary": {
            "brier_delta_primary_minus_proxy": brier_delta,
            "logloss_delta_primary_minus_proxy": logloss_delta,
        },
        "annotation_agreement_summary": annotation_agreement_summary,
        "appendix_claims": appendix_claims,
    }


def write_calibration_diagnostics(*, output_dir: Path, payload: dict) -> dict[str, str]:
    """将校准诊断结果写入 JSON 和 Markdown 文件
    参数: output_dir - 输出目录, payload - 诊断数据字典
    返回: JSON 和 Markdown 文件路径的字典
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "calibration_diagnostics.json"
    md_path = output_dir / "calibration_diagnostics.md"
    # 写入 JSON 文件
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 提取各部分数据
    primary_model = payload.get("primary_model") or {}
    agreement = payload.get("annotation_agreement_summary") or {}
    coverage = primary_model.get("coverage_metrics") or {}
    reliability = primary_model.get("reliability_report") or {}
    rule_vs_model = primary_model.get("rule_only_vs_model") or {}

    # 计算规则 vs 模型的召回率差距
    rule_recall = rule_vs_model.get("rule_positive_recall")
    model_recall = rule_vs_model.get("model_positive_recall")
    if rule_recall is not None and model_recall is not None:
        delta = round(float(model_recall) - float(rule_recall), 6)
        takeaway = (
            f"Model Tier-A recall exceeds rule-only recall by `{delta}`."
            if delta > 0
            else f"Model Tier-A recall does not exceed rule-only recall (`delta={delta}`)."
        )
    else:
        takeaway = "Rule-only vs model recall comparison is unavailable."

    # 构建 Markdown 报告
    lines = [
        "# Calibration Diagnostics",
        "",
        f"- Primary artifact: `{primary_model.get('artifact_version', '')}`",
        f"- Proxy artifact: `{(payload.get('proxy_model') or {}).get('artifact_version', '')}`",
        "",
        "## Primary Model",
        "",
        f"- Weak-label source: `{primary_model.get('weak_label_source', '')}`",
        f"- Tier-A positive recall: `{coverage.get('tier_a_positive_recall')}`",
        f"- ECE: `{reliability.get('ece')}`",
        f"- Rule-only recall: `{rule_recall}`",
        f"- Model recall: `{model_recall}`",
        "",
        "### Per-threshold Coverage",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tier-A predicted count | `{coverage.get('tier_a_predicted_count')}` |",
        f"| Tier-B-or-higher predicted count | `{coverage.get('tier_b_or_higher_predicted_count')}` |",
        f"| Tier-A positive recall | `{coverage.get('tier_a_positive_recall')}` |",
        f"| Tier-B-or-higher positive recall | `{coverage.get('tier_b_or_higher_positive_recall')}` |",
        "",
        "### Rule-only vs Model",
        "",
        f"- Rule-only recall: `{rule_recall}`",
        f"- Model recall: `{model_recall}`",
        f"- Takeaway: {takeaway}",
        "",
        "### ECE Bin Table",
        "",
        "| Bin | Range | Count | Avg confidence | Empirical accuracy | Absolute gap |",
        "|---|---|---:|---:|---:|---:|",
    ]
    # 添加 ECE 分箱信息
    for row in reliability.get("bins", []):
        lines.append(
            f"| `{row.get('bin_index')}` | `[{row.get('lower')}, {row.get('upper')}]` | `{row.get('count')}` | `{row.get('avg_confidence')}` | `{row.get('empirical_accuracy')}` | `{row.get('absolute_gap')}` |"
        )
    lines.extend(
        [
            "",
            f"- MCE: `{reliability.get('mce')}`",
            "",
            "## Proxy Model",
            "",
            f"- Raw Brier: `{((payload.get('proxy_model') or {}).get('loss_metrics') or {}).get('raw_brier_eval')}`",
            f"- Calibrated Brier: `{((payload.get('proxy_model') or {}).get('loss_metrics') or {}).get('calibrated_brier_eval')}`",
            f"- Raw log-loss: `{((payload.get('proxy_model') or {}).get('loss_metrics') or {}).get('raw_logloss_eval')}`",
            f"- Calibrated log-loss: `{((payload.get('proxy_model') or {}).get('loss_metrics') or {}).get('calibrated_logloss_eval')}`",
            "",
            "## Annotation Agreement",
            "",
            f"- Status: `{agreement.get('status')}`",
            f"- Shared overlap rows: `{agreement.get('shared_sha_count')}`",
            f"- Raw agreement: `{agreement.get('raw_agreement')}`",
            f"- Cohen's kappa: `{agreement.get('cohen_kappa')}`",
            f"- Adjudication coverage: `{agreement.get('adjudication_coverage')}`",
            "",
            "### Disagreement Summary",
            "",
        ]
    )
    # 添加分歧摘要
    for key, value in sorted((agreement.get("confusion_summary") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path.as_posix(), "markdown": md_path.as_posix()}
