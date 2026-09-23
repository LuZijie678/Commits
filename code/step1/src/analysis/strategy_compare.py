from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from src.labeling import label_protocol
from src.pipeline import atomic_mining as miner
from src.pipeline import full_diff_calibration as calibration

CSV_FIELD_SIZE_LIMIT = 2**31 - 1
SELECTION_STRATEGIES = ("rule_only", "model_only", "model_rule_refilter")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_selection_strategies(raw: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(raw, (list, tuple)):
        names = [str(item).strip() for item in raw if str(item).strip()]
    else:
        names = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not names:
        names = ["rule_only", "model_only", "model_rule_refilter"]
    for name in names:
        if name not in SELECTION_STRATEGIES:
            raise ValueError(f"unsupported selection strategy: {name}")
    return names


def load_csv_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if bool(value) else "false"


def _model_probability_from_row(row: dict) -> float | None:
    for key in ["atomic_prior_calibrated", "atomic_prior", "p_atomic", "p_raw"]:
        value = _safe_float(row.get(key))
        if value is not None:
            return float(min(1.0, max(0.0, value)))
    return None


def _repo_name(row: dict) -> str:
    resolved = str(row.get("resolved_repo", "")).strip()
    if resolved:
        return resolved
    repo = str(row.get("repo", "")).strip()
    if repo:
        return repo
    return miner.extract_repo(str(row.get("commit_url", "")))


def _commit_message(row: dict) -> str:
    return str(
        row.get("commit_message")
        or row.get("message")
        or row.get("masked_commit_message")
        or ""
    )


def _candidate_type(row: dict) -> str:
    return str(row.get("annotated_type") or row.get("type") or "").strip()


def _is_valid_diff_feature(diff_features: dict) -> bool:
    return bool(
        float(diff_features.get("file_count", 0.0)) > 0.0
        and float(diff_features.get("changed_lines", 0.0)) > 0.0
    )


def _build_rule_protocol(primary_calibration: dict) -> calibration.WeakLabelProtocol:
    fit_config = dict((primary_calibration or {}).get("fit_config") or {})
    protocol_payload = dict(fit_config.get("weak_label_protocol") or {})
    if not protocol_payload:
        raise RuntimeError(
            "primary calibration artifact missing fit_config.weak_label_protocol"
        )
    return calibration.WeakLabelProtocol(
        version=str(protocol_payload.get("version", "independent_rule_protocol_v1")),
        positive_file_count_max=float(protocol_payload["positive_file_count_max"]),
        positive_module_count_max=float(protocol_payload["positive_module_count_max"]),
        positive_patch_size_max=float(protocol_payload["positive_patch_size_max"]),
        positive_role_count_max=int(protocol_payload["positive_role_count_max"]),
        negative_file_count_min=float(protocol_payload["negative_file_count_min"]),
        negative_module_count_min=float(protocol_payload["negative_module_count_min"]),
        negative_patch_size_min=float(protocol_payload["negative_patch_size_min"]),
        negative_role_count_min=int(protocol_payload["negative_role_count_min"]),
        positive_issue_ref_max=int(protocol_payload["positive_issue_ref_max"]),
        negative_issue_ref_min=int(protocol_payload["negative_issue_ref_min"]),
        positive_subject_action_max=int(protocol_payload["positive_subject_action_max"]),
        negative_subject_action_min=int(protocol_payload["negative_subject_action_min"]),
        negative_structural_rule_min_fires=int(
            protocol_payload["negative_structural_rule_min_fires"]
        ),
        source=str(protocol_payload.get("source", "")),
    )


def score_candidates(
    *,
    candidates: list[dict],
    primary_calibration: dict,
) -> tuple[list[dict], dict]:
    thresholds = dict((primary_calibration or {}).get("thresholds") or {})
    tau_a = _safe_float(thresholds.get("tau_a"))
    tau_b = _safe_float(thresholds.get("tau_b"))
    if tau_a is None or tau_b is None:
        raise RuntimeError("primary calibration artifact missing thresholds.tau_a/tau_b")
    if not (0.0 < tau_b < tau_a < 1.0):
        raise RuntimeError(f"invalid thresholds: tau_a={tau_a}, tau_b={tau_b}")

    protocol = _build_rule_protocol(primary_calibration)

    parsed_valid_rows: list[dict] = []
    rule_by_index: dict[int, dict] = {}

    for index, row in enumerate(candidates):
        message_text = _commit_message(row)
        diff_text = str(row.get("git_diff", "") or "")
        message_features = miner.parse_message(message_text)
        diff_features = miner.parse_diff(diff_text)
        if not _is_valid_diff_feature(diff_features):
            rule_by_index[index] = {
                "rule_label": None,
                "rule_weight": None,
                "rule_decision_kind": "abstain_missing_diff_features",
                "rule_report": {
                    "protocol_version": protocol.version,
                    "label_name": "abstain",
                    "decision_kind": "abstain_missing_diff_features",
                    "positive_rules_fired": [],
                    "negative_rules_fired": [],
                },
            }
            continue
        row_with_index = dict(row)
        row_with_index["_strategy_row_index"] = str(index)
        parsed_valid_rows.append(
            {
                "row": row_with_index,
                "message_features": message_features,
                "diff_features": diff_features,
                "type": _candidate_type(row),
                "repo": _repo_name(row),
            }
        )

    if parsed_valid_rows:
        examples, _ = calibration.build_rule_labeled_examples(
            parsed_rows=parsed_valid_rows,
            protocol=protocol,
        )
        for parsed, example in zip(parsed_valid_rows, examples):
            row_index_raw = parsed["row"].get("_strategy_row_index", "")
            row_index = int(row_index_raw)
            label = example.get("label")
            rule_weight = None
            if label == 1:
                rule_weight = 1.0
            elif label == 0:
                rule_weight = 0.0
            rule_by_index[row_index] = {
                "rule_label": label,
                "rule_weight": rule_weight,
                "rule_decision_kind": str(example.get("decision_kind", "")),
                "rule_report": dict(example.get("rule_report") or {}),
            }

    scored_rows: list[dict] = []
    model_tier_a_count = 0
    model_tier_a_rule_positive_count = 0
    model_tier_a_rule_rejected_count = 0
    rule_positive_model_tier_a_count = 0
    rule_positive_model_not_a_count = 0

    for index, row in enumerate(candidates):
        copied = dict(row)
        model_prob = _model_probability_from_row(row)
        if model_prob is None:
            model_tier = "UNKNOWN"
        else:
            model_tier = miner.assign_atomic_tier(model_prob, tau_a=float(tau_a), tau_b=float(tau_b))

        rule_info = rule_by_index.get(index, {})
        rule_label = rule_info.get("rule_label")
        rule_weight = rule_info.get("rule_weight")

        if model_tier == "A":
            model_tier_a_count += 1
            if rule_label == 1:
                model_tier_a_rule_positive_count += 1
            else:
                model_tier_a_rule_rejected_count += 1

        if rule_label == 1:
            if model_tier == "A":
                rule_positive_model_tier_a_count += 1
            else:
                rule_positive_model_not_a_count += 1

        copied["model_prob"] = "" if model_prob is None else f"{float(model_prob):.6f}"
        copied["tau_a"] = f"{float(tau_a):.6f}"
        copied["tau_b"] = f"{float(tau_b):.6f}"
        copied["model_tier"] = model_tier
        copied["rule_label"] = "" if rule_label is None else str(int(rule_label))
        copied["rule_weight"] = "" if rule_weight is None else f"{float(rule_weight):.6f}"
        copied["rule_decision_kind"] = str(rule_info.get("rule_decision_kind", ""))
        copied["rule_protocol_version"] = protocol.version
        scored_rows.append(copied)

    summary = {
        "tau_a": float(tau_a),
        "tau_b": float(tau_b),
        "rule_protocol_version": protocol.version,
        "model_tier_a_count": model_tier_a_count,
        "model_tier_a_rule_positive_count": model_tier_a_rule_positive_count,
        "model_tier_a_rule_rejected_count": model_tier_a_rule_rejected_count,
        "rule_positive_model_tier_a_count": rule_positive_model_tier_a_count,
        "rule_positive_model_not_a_count": rule_positive_model_not_a_count,
    }
    return scored_rows, summary


def _row_model_prob(row: dict) -> float:
    return _safe_float(row.get("model_prob")) or 0.0


def apply_selection_strategy(
    *,
    scored_rows: list[dict],
    strategy: str,
    target_count: int,
) -> list[dict]:
    if strategy not in SELECTION_STRATEGIES:
        raise ValueError(f"unsupported selection strategy: {strategy}")

    rows: list[dict] = []
    for row in scored_rows:
        copied = dict(row)
        model_prob = _safe_float(copied.get("model_prob"))
        tau_a = _safe_float(copied.get("tau_a"))
        rule_label_raw = str(copied.get("rule_label", "")).strip()
        rule_label = int(rule_label_raw) if rule_label_raw in {"0", "1"} else None
        model_positive = bool(
            model_prob is not None and tau_a is not None and float(model_prob) > float(tau_a)
        )
        rule_positive = rule_label == 1

        copied["selection_strategy"] = strategy
        copied["conservative_tier"] = ""
        copied["passed_rule_refilter"] = ""
        copied["selection_reason"] = ""
        copied["refilter_reason"] = ""

        if strategy == "rule_only":
            is_selected = rule_positive
            copied["passed_rule_refilter"] = _as_bool_text(is_selected)
            copied["selection_reason"] = (
                "rule_positive" if is_selected else "rule_not_positive_or_abstain"
            )
            copied["model_prob"] = ""
        elif strategy == "model_only":
            is_selected = model_positive
            copied["selection_reason"] = (
                "model_prob_above_tau_a"
                if is_selected
                else "model_prob_not_above_tau_a"
            )
        else:
            if model_positive and rule_positive:
                is_selected = True
                copied["passed_rule_refilter"] = "true"
                copied["conservative_tier"] = "A"
                copied["selection_reason"] = "model_tier_a_and_rule_positive"
                copied["refilter_reason"] = "model_tier_a_and_rule_positive"
            elif model_positive and not rule_positive:
                is_selected = False
                copied["passed_rule_refilter"] = "false"
                copied["selection_reason"] = "model_tier_a_but_rule_not_positive"
                copied["refilter_reason"] = "model_tier_a_but_rule_not_positive"
            else:
                is_selected = False
                copied["passed_rule_refilter"] = "false"
                copied["selection_reason"] = "model_not_tier_a"
                copied["refilter_reason"] = "model_not_tier_a"

        copied["is_selected"] = "1" if is_selected else "0"
        rows.append(copied)

    if int(target_count) > 0:
        selected = [row for row in rows if row.get("is_selected") == "1"]
        selected.sort(
            key=lambda item: (
                -_row_model_prob(item),
                str(item.get("sha", "")),
            )
        )
        retained = {
            str(row.get("sha", ""))
            for row in selected[: int(target_count)]
            if str(row.get("sha", ""))
        }
        for row in rows:
            sha = str(row.get("sha", ""))
            if row.get("is_selected") == "1" and sha not in retained:
                row["is_selected"] = "0"
                row["selection_reason"] = (
                    str(row.get("selection_reason", "")) + "_trimmed_by_target_count"
                ).strip("_")
                row["conservative_tier"] = ""
                if strategy == "model_rule_refilter":
                    row["passed_rule_refilter"] = "false"
    return rows


def _selected_shas(rows: list[dict]) -> set[str]:
    return {
        str(row.get("sha", "")).strip()
        for row in rows
        if str(row.get("is_selected", "")) == "1" and str(row.get("sha", "")).strip()
    }


def build_label_by_sha(rows: list[dict], label_col: str = "is_single_intent") -> dict[str, int]:
    label_by_sha: dict[str, int] = {}
    for row in rows:
        sha = str(row.get("sha", "")).strip()
        if not sha:
            continue
        resolved = label_protocol.resolve_label_record(row, label_col=label_col)
        label = str(resolved.get("selected_label", "")).strip()
        if label in {"0", "1"}:
            label_by_sha[sha] = int(label)
    return label_by_sha


def compute_strategy_metrics(*, selected_shas: set[str], label_by_sha: dict[str, int]) -> dict:
    if not label_by_sha:
        return {
            "selected_count": len(selected_shas),
            "evaluation_labeled_count": 0,
            "evaluation_selected_labeled_count": 0,
            "gold_positive_count": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "estimated_noise_rate": None,
            "evaluation_metric_status": "evaluation_labels_missing",
            "evaluation_metric_note": "evaluation labels are unavailable, so direct precision/recall/F1 cannot be computed",
        }
    positives = {sha for sha, label in label_by_sha.items() if int(label) == 1}
    negatives = {sha for sha, label in label_by_sha.items() if int(label) == 0}

    selected_eval = selected_shas & set(label_by_sha.keys())
    if not selected_eval:
        return {
            "selected_count": len(selected_shas),
            "evaluation_labeled_count": len(label_by_sha),
            "evaluation_selected_labeled_count": 0,
            "gold_positive_count": len(positives),
            "precision": None,
            "recall": None,
            "f1": None,
            "estimated_noise_rate": None,
            "tp": 0,
            "fp": 0,
            "fn": len(positives),
            "evaluation_metric_status": "not_directly_computable_strict_disjoint",
            "evaluation_metric_note": "the formal protocol keeps evaluation labels SHA-disjoint from the candidate pool, so direct precision/recall/F1 are not directly computable from evaluation.csv",
        }
    tp = len(selected_eval & positives)
    fp = len(selected_eval & negatives)
    fn = len(positives - selected_shas)

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
    recall = (tp / len(positives)) if positives else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2.0 * precision * recall / (precision + recall)

    return {
        "selected_count": len(selected_shas),
        "evaluation_labeled_count": len(label_by_sha),
        "evaluation_selected_labeled_count": len(selected_eval),
        "gold_positive_count": len(positives),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "estimated_noise_rate": (None if precision is None else (1.0 - precision)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "evaluation_metric_status": "computed_from_overlap",
        "evaluation_metric_note": "direct precision/recall/F1 computed from the overlap between selected candidates and evaluation labels",
    }


def compute_source_confidence(model_prob: float | None, rule_weight: float | None) -> float:
    probability = float(model_prob or 0.0)
    if rule_weight is None:
        return probability
    return probability * float(rule_weight)


def build_conservative_source_rows(rows: list[dict]) -> list[dict]:
    exported: list[dict] = []
    for row in rows:
        if str(row.get("is_selected", "")) != "1":
            continue
        if str(row.get("selection_strategy", "")) != "model_rule_refilter":
            continue
        if str(row.get("conservative_tier", "")) != "A":
            continue
        model_prob = _safe_float(row.get("model_prob"))
        rule_weight = _safe_float(row.get("rule_weight"))
        exported.append(
            {
                "sha": str(row.get("sha", "")),
                "repo": _repo_name(row),
                "commit_url": str(row.get("commit_url", "")),
                "type": str(row.get("type", "")),
                "subject": str(row.get("subject", "")),
                "message": _commit_message(row),
                "git_diff": str(row.get("git_diff", "")),
                "model_prob": "" if model_prob is None else f"{float(model_prob):.6f}",
                "model_tier": str(row.get("model_tier", "")),
                "tau_a": str(row.get("tau_a", "")),
                "tau_b": str(row.get("tau_b", "")),
                "rule_label": str(row.get("rule_label", "")),
                "rule_weight": str(row.get("rule_weight", "")),
                "passed_rule_refilter": str(row.get("passed_rule_refilter", "")),
                "conservative_tier": str(row.get("conservative_tier", "")),
                "selection_strategy": str(row.get("selection_strategy", "")),
                "selection_reason": str(row.get("selection_reason", "")),
                "source_confidence": f"{compute_source_confidence(model_prob, rule_weight):.6f}",
            }
        )
    return exported


def build_proxy_role_summary(proxy_gap_payload: dict | None) -> dict:
    conversion = dict((proxy_gap_payload or {}).get("conversion_metrics") or {})
    tier_consistency = _safe_float(
        conversion.get("tier_consistency", (proxy_gap_payload or {}).get("tier_consistency"))
    )
    downgrade_rate = _safe_float(
        conversion.get(
            "downgrade_rate_message_only_a_to_full_diff_c",
            (proxy_gap_payload or {}).get("downgrade_rate_message_only_a_to_full_diff_c"),
        )
    )
    warning = bool(
        (downgrade_rate is not None and downgrade_rate >= 0.35)
        or (tier_consistency is not None and tier_consistency < 0.70)
    )
    return {
        "proxy_role": "recall_prefilter_only",
        "proxy_to_full_diff_agreement": tier_consistency,
        "proxy_a_to_full_diff_c_rate": downgrade_rate,
        "proxy_high_confidence_warning": warning,
        "proxy_metrics_missing": proxy_gap_payload is None,
    }


def _pair_overlap_count(left: set[str], right: set[str]) -> int:
    return len(left & right)


def build_overlap_matrix(strategy_to_selected_shas: dict[str, set[str]]) -> list[dict]:
    names = list(strategy_to_selected_shas.keys())
    rows: list[dict] = []
    for name in names:
        left = strategy_to_selected_shas[name]
        row = {"strategy": name}
        for other in names:
            right = strategy_to_selected_shas[other]
            row[f"overlap_count_with_{other}"] = _pair_overlap_count(left, right)
        rows.append(row)
    return rows


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.6f}"


def _build_strategy_markdown(
    *,
    strategy_metrics: dict[str, dict],
    proxy_role_summary: dict,
    global_summary: dict,
    audit_available: bool,
) -> str:
    strategy_names = list(strategy_metrics.keys())
    lines = [
        "# Step1 Strategy Comparison",
        "",
        "| 指标 | " + " | ".join(strategy_names) + " |",
        "|---|" + "|".join(["---:"] * len(strategy_names)) + "|",
    ]

    def row(metric_key: str, title: str) -> None:
        values = [
            _format_metric(strategy_metrics[name].get(metric_key)) for name in strategy_names
        ]
        lines.append(f"| {title} | " + " | ".join(values) + " |")

    row("selected_count", "selected_count")
    row("precision", "precision")
    row("recall", "recall")
    row("f1", "F1")
    row("estimated_noise_rate", "estimated_noise_rate")
    row("tier_a_audit_precision", "Tier-A audit precision")
    for strategy_name in strategy_names:
        row(
            f"candidate_overlap_with_{strategy_name}",
            f"candidate overlap with {strategy_name}",
        )

    lines.extend(
        [
            "",
            "## Evaluation Metric Notes",
            "",
        ]
    )
    for strategy_name in strategy_names:
        metrics = strategy_metrics[strategy_name]
        lines.append(
            f"- {strategy_name}: `{metrics.get('evaluation_metric_status')}`; {metrics.get('evaluation_metric_note')}"
        )

    lines.extend(
        [
            "",
            "## 模型与规则交叉计数",
            "",
            f"- model_tier_a_count: `{global_summary.get('model_tier_a_count')}`",
            f"- model_tier_a_rule_positive_count: `{global_summary.get('model_tier_a_rule_positive_count')}`",
            f"- model_tier_a_rule_rejected_count: `{global_summary.get('model_tier_a_rule_rejected_count')}`",
            f"- rule_positive_model_tier_a_count: `{global_summary.get('rule_positive_model_tier_a_count')}`",
            f"- rule_positive_model_not_a_count: `{global_summary.get('rule_positive_model_not_a_count')}`",
            "",
            "## Proxy 角色说明",
            "",
            f"- proxy_role: `{proxy_role_summary.get('proxy_role')}`",
            f"- proxy_to_full_diff_agreement: `{proxy_role_summary.get('proxy_to_full_diff_agreement')}`",
            f"- proxy_a_to_full_diff_c_rate: `{proxy_role_summary.get('proxy_a_to_full_diff_c_rate')}`",
            f"- proxy_high_confidence_warning: `{proxy_role_summary.get('proxy_high_confidence_warning')}`",
            "",
        ]
    )
    if not audit_available:
        lines.append("- audit precision not available")
    return "\n".join(lines) + "\n"


def run_strategy_compare(
    *,
    run_root: Path,
    resolved_candidates_csv: Path,
    evaluation_csv: Path,
    primary_calibration_json: Path,
    selection_strategies: list[str],
    target_count: int = 0,
    proxy_gap_analysis_json: Path | None = None,
    audit_labeled_csv: Path | None = None,
    audit_precision_report_json: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    if not resolved_candidates_csv.exists():
        raise RuntimeError(
            f"strategy compare blocker: missing candidates csv {resolved_candidates_csv.as_posix()}"
        )
    if not evaluation_csv.exists():
        raise RuntimeError(
            f"strategy compare blocker: missing evaluation csv {evaluation_csv.as_posix()}"
        )

    candidates = load_csv_rows(resolved_candidates_csv)
    if not candidates:
        raise RuntimeError("strategy compare blocker: resolved candidates is empty")

    evaluation_rows = load_csv_rows(evaluation_csv)
    evaluation_label_by_sha = build_label_by_sha(evaluation_rows)
    if not evaluation_label_by_sha:
        raise RuntimeError(
            "strategy compare blocker: evaluation split has no usable 0/1 labels"
        )

    primary_calibration = json.loads(primary_calibration_json.read_text(encoding="utf-8"))
    scored_rows, score_summary = score_candidates(
        candidates=candidates,
        primary_calibration=primary_calibration,
    )

    out_dir = output_dir or (run_root / f"strategy_compare_{utc_timestamp()}")
    comparison_dir = out_dir / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    strategy_rows_map: dict[str, list[dict]] = {}
    strategy_selected_map: dict[str, set[str]] = {}

    for strategy in selection_strategies:
        applied_rows = apply_selection_strategy(
            scored_rows=scored_rows,
            strategy=strategy,
            target_count=int(target_count),
        )
        strategy_rows_map[strategy] = applied_rows
        strategy_selected_map[strategy] = _selected_shas(applied_rows)
        if int(target_count) > 0 and len(strategy_selected_map[strategy]) < int(
            target_count
        ):
            raise RuntimeError(
                "strategy compare blocker: insufficient selected rows for "
                f"{strategy}; required target_count={int(target_count)}, "
                f"actual={len(strategy_selected_map[strategy])}"
            )

        strategy_dir = out_dir / strategy
        strategy_dir.mkdir(parents=True, exist_ok=True)
        write_csv(strategy_dir / "candidate_scores.csv", applied_rows)
        write_csv(
            strategy_dir / "selected_candidates.csv",
            [row for row in applied_rows if row.get("is_selected") == "1"],
        )
        write_json(
            strategy_dir / "summary.json",
            {
                "selection_strategy": strategy,
                "selected_count": len(strategy_selected_map[strategy]),
                "target_count": int(target_count),
            },
        )

    audit_label_by_sha: dict[str, int] = {}
    audit_available = False
    if audit_labeled_csv is not None and audit_labeled_csv.exists():
        audit_rows = load_csv_rows(audit_labeled_csv)
        audit_label_by_sha = build_label_by_sha(
            audit_rows,
            label_col="audit_is_single_intent",
        )
        audit_available = bool(audit_label_by_sha)

    audit_report_payload = {}
    if audit_precision_report_json is not None and audit_precision_report_json.exists():
        audit_report_payload = json.loads(
            audit_precision_report_json.read_text(encoding="utf-8")
        )

    strategy_metrics: dict[str, dict] = {}
    for strategy in selection_strategies:
        selected = strategy_selected_map[strategy]
        metrics = compute_strategy_metrics(
            selected_shas=selected,
            label_by_sha=evaluation_label_by_sha,
        )
        if audit_available:
            audit_selected = selected & set(audit_label_by_sha.keys())
            audit_positive = sum(1 for sha in audit_selected if audit_label_by_sha[sha] == 1)
            metrics["tier_a_audit_precision"] = (
                audit_positive / len(audit_selected) if audit_selected else None
            )
            metrics["tier_a_audit_sample_count"] = len(audit_selected)
        else:
            metrics["tier_a_audit_precision"] = (
                (audit_report_payload.get("tier_a") or {}).get("precision")
                if audit_report_payload
                else None
            )
            metrics["tier_a_audit_sample_count"] = (
                (audit_report_payload.get("tier_a") or {}).get("sample_count")
                if audit_report_payload
                else None
            )

        for other in selection_strategies:
            overlap = len(selected & strategy_selected_map[other])
            metrics[f"candidate_overlap_with_{other}"] = overlap

        strategy_metrics[strategy] = metrics

    overlap_matrix_rows = build_overlap_matrix(strategy_selected_map)
    write_csv(comparison_dir / "candidate_overlap_matrix.csv", overlap_matrix_rows)

    precision_recall_rows = []
    for strategy in selection_strategies:
        metric = strategy_metrics[strategy]
        precision_recall_rows.append(
            {
                "selection_strategy": strategy,
                "selected_count": metric.get("selected_count"),
                "precision": metric.get("precision"),
                "recall": metric.get("recall"),
                "f1": metric.get("f1"),
                "estimated_noise_rate": metric.get("estimated_noise_rate"),
                "evaluation_metric_status": metric.get("evaluation_metric_status"),
                "evaluation_metric_note": metric.get("evaluation_metric_note"),
                "tier_a_audit_precision": metric.get("tier_a_audit_precision"),
            }
        )
    write_csv(comparison_dir / "precision_recall_summary.csv", precision_recall_rows)

    proxy_payload = None
    if proxy_gap_analysis_json is not None and proxy_gap_analysis_json.exists():
        proxy_payload = json.loads(proxy_gap_analysis_json.read_text(encoding="utf-8"))
    proxy_role_summary = build_proxy_role_summary(proxy_payload)

    comparison_payload = {
        "artifact_version": "step1_strategy_compare_v1",
        "selection_strategies": selection_strategies,
        "target_count": int(target_count),
        "calibration_artifact": primary_calibration_json.as_posix(),
        "thresholds": {
            "tau_a": score_summary["tau_a"],
            "tau_b": score_summary["tau_b"],
        },
        "strategy_metrics": strategy_metrics,
        "global_counts": {
            "model_tier_a_count": score_summary["model_tier_a_count"],
            "model_tier_a_rule_positive_count": score_summary[
                "model_tier_a_rule_positive_count"
            ],
            "model_tier_a_rule_rejected_count": score_summary[
                "model_tier_a_rule_rejected_count"
            ],
            "rule_positive_model_tier_a_count": score_summary[
                "rule_positive_model_tier_a_count"
            ],
            "rule_positive_model_not_a_count": score_summary[
                "rule_positive_model_not_a_count"
            ],
        },
        "proxy_role": proxy_role_summary,
        "audit_precision_available": audit_available or bool(audit_report_payload),
        "audit_precision_note": (
            "audit precision not available"
            if not (audit_available or bool(audit_report_payload))
            else "audit precision available"
        ),
    }

    write_json(comparison_dir / "strategy_comparison.json", comparison_payload)
    markdown_text = _build_strategy_markdown(
        strategy_metrics=strategy_metrics,
        proxy_role_summary=proxy_role_summary,
        global_summary=comparison_payload["global_counts"],
        audit_available=bool(comparison_payload["audit_precision_available"]),
    )
    (comparison_dir / "strategy_comparison.md").write_text(
        markdown_text,
        encoding="utf-8",
    )

    conservative_rows = build_conservative_source_rows(
        strategy_rows_map.get("model_rule_refilter", [])
    )
    conservative_csv = out_dir / "conservative_atomic_sources.csv"
    write_csv(conservative_csv, conservative_rows)

    source_pool_metadata = {
        "source_pool_name": "conservative_atomic_sources",
        "selection_strategy": "model_rule_refilter",
        "source_confidence_formula": "calibrated_model_prob * rule_weight",
        "input_candidate_count": len(scored_rows),
        "model_tier_a_count": score_summary["model_tier_a_count"],
        "rule_retained_count": score_summary["model_tier_a_rule_positive_count"],
        "final_source_count": len(conservative_rows),
        "tau_a": score_summary["tau_a"],
        "tau_b": score_summary["tau_b"],
        "calibration_artifact": primary_calibration_json.as_posix(),
        "rule_protocol_version": score_summary["rule_protocol_version"],
        "created_at": utc_timestamp(),
    }
    source_pool_metadata_json = out_dir / "source_pool_metadata.json"
    write_json(source_pool_metadata_json, source_pool_metadata)

    return {
        "output_dir": out_dir.as_posix(),
        "strategy_comparison_json": (comparison_dir / "strategy_comparison.json").as_posix(),
        "strategy_comparison_md": (comparison_dir / "strategy_comparison.md").as_posix(),
        "candidate_overlap_matrix_csv": (comparison_dir / "candidate_overlap_matrix.csv").as_posix(),
        "precision_recall_summary_csv": (comparison_dir / "precision_recall_summary.csv").as_posix(),
        "conservative_atomic_sources_csv": conservative_csv.as_posix(),
        "source_pool_metadata_json": source_pool_metadata_json.as_posix(),
        "proxy_role": proxy_role_summary,
        "global_counts": comparison_payload["global_counts"],
    }
