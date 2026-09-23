"""
message-only 校准拟合脚本

目标：
1. 输入带人工标签且 diff 非空的审计数据
2. 使用 message-only atomic logit/sigmoid 作为 raw probability
3. 通过 isotonic regression 进行概率校准
4. 基于人工标签在 message-only 概率尺度上选择 tau_a/tau_b

注意：
- 审计协议仍然要求每条样本同时具备 message 与 diff
- 但校准输入空间仅使用 message-only 特征
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from sklearn.isotonic import IsotonicRegression
from src.pipeline import full_diff_calibration as base_fit
from src.pipeline import atomic_mining as miner
import src.data_splitting.annotated_split_protocol as annotated_split_protocol
from src.labeling import label_protocol
from src.param_derivation.threshold_selection import (
    select_threshold_by_precision_report,
)


DEFAULT_OUTPUT = "outputs/calibration/message_only_calibration.json"
DEFAULT_LABEL_COL = "is_single_intent"
DEFAULT_SCHEME = "cv"
DEFAULT_CALIBRATION_MODE = "platt"
DEFAULT_HOLDOUT_RATIO = 0.20
DEFAULT_CV_FOLDS = 5
DEFAULT_TAU_A_PRECISION = 0.90
DEFAULT_TAU_B_PRECISION = 0.70
DEFAULT_RANDOM_STATE = 42
DEFAULT_THRESHOLD_FALLBACK_POLICY = "error"
CSV_FIELD_SIZE_LIMIT = 2**31 - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--calibration-input", default="")
    parser.add_argument("--evaluation-input", default="")
    parser.add_argument(
        "--allow-legacy-single-split",
        action="store_true",
        help="Explicitly allow reusing a single annotated input for calibration and threshold selection.",
    )
    parser.add_argument("--annotated-split-plan-json", default="")
    parser.add_argument("--base-calibration", required=True)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--label-col", default=DEFAULT_LABEL_COL)
    parser.add_argument(
        "--calibration-mode",
        choices=["isotonic", "platt"],
        default=DEFAULT_CALIBRATION_MODE,
    )
    parser.add_argument(
        "--labeled-calibration-scheme",
        choices=["holdout", "cv"],
        default=DEFAULT_SCHEME,
    )
    parser.add_argument(
        "--labeled-holdout-ratio", type=float, default=DEFAULT_HOLDOUT_RATIO
    )
    parser.add_argument("--labeled-cv-folds", type=int, default=DEFAULT_CV_FOLDS)
    parser.add_argument(
        "--tau-a-precision", type=float, default=DEFAULT_TAU_A_PRECISION
    )
    parser.add_argument(
        "--tau-b-precision", type=float, default=DEFAULT_TAU_B_PRECISION
    )
    parser.add_argument("--random-state", type=int, default=DEFAULT_RANDOM_STATE)
    parser.add_argument(
        "--threshold-fallback-policy",
        choices=[DEFAULT_THRESHOLD_FALLBACK_POLICY],
        default=DEFAULT_THRESHOLD_FALLBACK_POLICY,
    )
    parser.add_argument(
        "--require-repo-disjoint-eval",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require calibration/evaluation repo sets to be disjoint in explicit split mode.",
    )
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    """
    加载CSV文件

    参数:
        path: CSV文件路径

    返回:
        list[dict]: CSV行列表（每行是一个字典）
    """
    # 设置CSV字段大小限制，避免大字段导致解析错误
    csv.field_size_limit(min(sys.maxsize, CSV_FIELD_SIZE_LIMIT))
    # 打开文件并使用DictReader解析为字典列表
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_message_only_split_rows(
    args: argparse.Namespace,
    fallback_rows: list[dict],
) -> tuple[list[dict], list[dict], dict]:
    calibration_input = str(getattr(args, "calibration_input", "") or "").strip()
    evaluation_input = str(getattr(args, "evaluation_input", "") or "").strip()
    split_plan_json = str(getattr(args, "annotated_split_plan_json", "") or "").strip()
    if calibration_input or evaluation_input:
        if not calibration_input or not evaluation_input:
            raise ValueError(
                "message-only calibration requires calibration/evaluation split inputs together"
            )
        calibration_rows = load_rows(Path(calibration_input))
        evaluation_rows = load_rows(Path(evaluation_input))
        split_summary = (
            json.loads(Path(split_plan_json).read_text(encoding="utf-8"))
            if split_plan_json
            else {}
        )
        if split_summary:
            annotated_split_protocol.assert_rows_match_split(
                rows=calibration_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "calibration"
                ),
                split_name="calibration",
                context="message-only calibration fitting",
            )
            annotated_split_protocol.assert_rows_match_split(
                rows=evaluation_rows,
                split_sha_set=annotated_split_protocol.split_sha_set(
                    split_summary, "evaluation"
                ),
                split_name="evaluation",
                context="message-only threshold selection",
            )
        split_roles = {
            "calibration": {
                "source_csv": calibration_input,
                "summary": (split_summary.get("splits") or {}).get("calibration", {}),
            },
            "evaluation": {
                "source_csv": evaluation_input,
                "summary": (split_summary.get("splits") or {}).get("evaluation", {}),
            },
            "split_plan_json": split_plan_json,
        }
        return calibration_rows, evaluation_rows, split_roles
    if not fallback_rows:
        raise ValueError(
            "message-only calibration requires either split inputs or a non-empty --input"
        )
    return fallback_rows, fallback_rows, {}


def build_message_only_labeled_examples(
    *,
    rows: list[dict],
    base_calibration: dict | None,
    label_col: str,
) -> list[dict]:
    examples: list[dict] = []
    for row in rows:
        resolved = label_protocol.resolve_label_record(row, label_col=label_col)
        label = resolved["selected_label_int"]
        if label is None:
            continue
        git_diff = str(row.get("git_diff", "")).strip()
        if not git_diff:
            raise ValueError("message-only calibration requires non-empty git_diff")
        message_features = miner.parse_message(str(row.get("commit_message", "")))
        raw_logit = miner.atomic_logit(
            message_features=message_features,
            candidate_type=str(row.get("type", "")).strip(),
            diff_features=None,
            signal_context=(base_calibration or {}).get("signal_context"),
            message_protocol=(base_calibration or {}).get("message_protocol"),
            type_protocol=(base_calibration or {}).get("type_protocol"),
        )
        raw_probability = miner.clip_prob(miner.sigmoid(raw_logit))
        examples.append(
            {
                "sha": str(row.get("sha", "")).strip(),
                "repo": str(row.get("repo", "")).strip()
                or str(row.get("resolved_repo", "")).strip()
                or miner.extract_repo(str(row.get("commit_url", ""))),
                "type": str(row.get("type", "")).strip(),
                "label": int(label),
                "raw_logit": float(raw_logit),
                "raw_probability": float(raw_probability),
            }
        )
    return examples


def summarize_repo_protocol(
    *,
    calibration_examples: list[dict],
    evaluation_examples: list[dict],
) -> dict:
    calibration_repos = sorted(
        {
            str(item.get("repo", "")).strip()
            for item in calibration_examples
            if str(item.get("repo", "")).strip()
        }
    )
    evaluation_repos = sorted(
        {
            str(item.get("repo", "")).strip()
            for item in evaluation_examples
            if str(item.get("repo", "")).strip()
        }
    )
    overlap = sorted(set(calibration_repos) & set(evaluation_repos))
    return {
        "repo_set_calibration": calibration_repos,
        "repo_set_evaluation": evaluation_repos,
        "repo_overlap_count": len(overlap),
        "repo_overlap_examples": overlap[:10],
        "repo_disjoint_eval": len(overlap) == 0,
        "calibration_train_repo_count": len(calibration_repos),
        "threshold_eval_repo_count": len(evaluation_repos),
    }


def _fit_calibration_thresholds(
    *,
    examples: list[dict],
    scheme: str,
    calibration_mode: str,
    holdout_ratio: float,
    cv_folds: int,
    tau_a_precision: float,
    tau_b_precision: float,
    random_state: int,
    threshold_fallback_policy: str,
) -> tuple[dict, dict]:
    labels = [int(item["label"]) for item in examples]
    raw_probs = [float(item["raw_probability"]) for item in examples]
    raw_logits = [float(item["raw_logit"]) for item in examples]
    groups = [
        str(item.get("repo", "")).strip() or f"sha::{item.get('sha', '')}"
        for item in examples
    ]
    if len(labels) < 20 or len(set(labels)) < 2:
        raise ValueError(
            "message-only calibration requires at least 20 labeled rows with both classes"
        )

    isotonic_info: dict | None = None
    platt_slope: float | None = None
    platt_intercept: float | None = None
    eval_probs: list[float] = []
    eval_labels: list[int] = []
    metrics: dict[str, object] = {
        "labeled_n": len(labels),
        "labeled_positive_rate": sum(labels) / len(labels),
    }

    if scheme == "holdout":
        split = base_fit.repo_aware_holdout_indices(
            labels=labels,
            groups=groups,
            holdout_ratio=holdout_ratio,
            random_state=random_state,
        )
        if split is None:
            raise ValueError("message-only repo-aware holdout split unavailable")
        train_indices, val_indices = split
        train_repos = {groups[index] for index in train_indices}
        val_repos = {groups[index] for index in val_indices}
        train_raw = base_fit.subset(raw_probs, train_indices)
        train_logits = base_fit.subset(raw_logits, train_indices)
        train_labels = base_fit.subset_int(labels, train_indices)
        val_raw = base_fit.subset(raw_probs, val_indices)
        val_logits = base_fit.subset(raw_logits, val_indices)
        val_labels = base_fit.subset_int(labels, val_indices)
        if calibration_mode == "isotonic":
            isotonic = IsotonicRegression(out_of_bounds="clip")
            isotonic.fit(train_raw, train_labels)
            eval_probs = [float(value) for value in isotonic.predict(val_raw)]
            isotonic_info = {
                "x": [float(value) for value in isotonic.X_thresholds_],
                "y": [float(value) for value in isotonic.y_thresholds_],
                "n": len(train_labels),
                "scheme": "message_only_holdout_train_only",
            }
        else:
            platt_hparams = base_fit.derive_platt_hyperparams(
                n_samples=len(train_logits),
                iterations_arg=0,
                learning_rate_arg=0.0,
                l2_arg=0.0,
            )
            platt_slope, platt_intercept = base_fit.fit_platt_scaler(
                train_logits,
                train_labels,
                iterations=int(platt_hparams["iterations"]),
                learning_rate=float(platt_hparams["learning_rate"]),
                l2=float(platt_hparams["l2"]),
            )
            eval_probs = [
                miner.clip_prob(base_fit.sigmoid(platt_slope * logit + platt_intercept))
                for logit in val_logits
            ]
        metrics.update(
            {
                "raw_brier_eval": base_fit.brier_score(val_raw, val_labels),
                "calibrated_brier_eval": base_fit.brier_score(eval_probs, val_labels),
                "raw_logloss_eval": base_fit.log_loss(val_raw, val_labels),
                "calibrated_logloss_eval": base_fit.log_loss(eval_probs, val_labels),
                "calibration_train_n": len(train_labels),
                "threshold_eval_n": len(val_labels),
                "repo_disjoint_eval": train_repos.isdisjoint(val_repos),
                "calibration_train_repo_count": len(train_repos),
                "threshold_eval_repo_count": len(val_repos),
            }
        )
    else:
        split_bundle = base_fit.repo_aware_cv_splits(
            labels=labels,
            groups=groups,
            cv_folds=cv_folds,
            random_state=random_state,
        )
        if split_bundle is None:
            raise ValueError("message-only repo-aware cv unavailable")
        splits, n_splits = split_bundle
        oof = [0.0] * len(labels)
        fold_sizes: list[int] = []
        repo_overlap_detected = False
        for train_indices, val_indices in splits:
            train_repos = {groups[index] for index in train_indices}
            val_repos = {groups[index] for index in val_indices}
            repo_overlap_detected = repo_overlap_detected or bool(
                train_repos & val_repos
            )
            train_raw = [raw_probs[index] for index in train_indices]
            train_logits = [raw_logits[index] for index in train_indices]
            train_labels = [labels[index] for index in train_indices]
            val_raw = [raw_probs[index] for index in val_indices]
            val_logits = [raw_logits[index] for index in val_indices]
            if calibration_mode == "isotonic":
                isotonic_fold = IsotonicRegression(out_of_bounds="clip")
                isotonic_fold.fit(train_raw, train_labels)
                preds = [float(value) for value in isotonic_fold.predict(val_raw)]
            else:
                platt_hparams = base_fit.derive_platt_hyperparams(
                    n_samples=len(train_logits),
                    iterations_arg=0,
                    learning_rate_arg=0.0,
                    l2_arg=0.0,
                )
                slope, intercept = base_fit.fit_platt_scaler(
                    train_logits,
                    train_labels,
                    iterations=int(platt_hparams["iterations"]),
                    learning_rate=float(platt_hparams["learning_rate"]),
                    l2=float(platt_hparams["l2"]),
                )
                preds = [
                    miner.clip_prob(base_fit.sigmoid(slope * logit + intercept))
                    for logit in val_logits
                ]
            for idx, pred in zip(val_indices, preds):
                oof[int(idx)] = pred
            fold_sizes.append(len(val_indices))
        if calibration_mode == "isotonic":
            isotonic_final = IsotonicRegression(out_of_bounds="clip")
            isotonic_final.fit(raw_probs, labels)
            isotonic_info = {
                "x": [float(value) for value in isotonic_final.X_thresholds_],
                "y": [float(value) for value in isotonic_final.y_thresholds_],
                "n": len(labels),
                "scheme": "message_only_cv_oof_threshold_final_fit",
            }
        else:
            platt_hparams = base_fit.derive_platt_hyperparams(
                n_samples=len(raw_logits),
                iterations_arg=0,
                learning_rate_arg=0.0,
                l2_arg=0.0,
            )
            platt_slope, platt_intercept = base_fit.fit_platt_scaler(
                raw_logits,
                labels,
                iterations=int(platt_hparams["iterations"]),
                learning_rate=float(platt_hparams["learning_rate"]),
                l2=float(platt_hparams["l2"]),
            )
        eval_probs = list(oof)
        eval_labels = list(labels)
        metrics.update(
            {
                "raw_brier_oof": base_fit.brier_score(raw_probs, labels),
                "calibrated_brier_oof": base_fit.brier_score(eval_probs, labels),
                "raw_logloss_oof": base_fit.log_loss(raw_probs, labels),
                "calibrated_logloss_oof": base_fit.log_loss(eval_probs, labels),
                "threshold_eval_n": len(eval_labels),
                "cv_folds": n_splits,
                "cv_fold_sizes": fold_sizes,
                "repo_disjoint_eval": not repo_overlap_detected,
                "cv_group_count": len({group for group in groups if group}),
            }
        )

    fallback_tau_a, fallback_tau_b = miner.derive_threshold_seed_from_distribution(
        eval_probs
    )
    tau_a_report = select_threshold_by_precision_report(
        eval_probs,
        eval_labels,
        target_precision=tau_a_precision,
        fallback=fallback_tau_a,
    )
    tau_b_report = select_threshold_by_precision_report(
        eval_probs,
        eval_labels,
        target_precision=tau_b_precision,
        fallback=fallback_tau_b,
        upper_bound=tau_a_report.threshold,
    )
    selection_reports = {
        "tau_a": base_fit.threshold_report_to_dict(tau_a_report),
        "tau_b": base_fit.threshold_report_to_dict(tau_b_report),
    }
    base_fit.apply_threshold_fallback_policy(
        selection_reports, policy=threshold_fallback_policy
    )
    artifact_version = (
        "step1_message_only_isotonic_v1"
        if calibration_mode == "isotonic"
        else "step1_message_only_platt_v1"
    )
    fit_mode = (
        "message_only_isotonic"
        if calibration_mode == "isotonic"
        else "message_only_platt"
    )
    artifact = {
        "artifact_version": artifact_version,
        "model_mode": "message_only",
        "model_role": "proxy",
        "message_protocol": {},
        "scope_protocol": {},
        "type_protocol": {},
        "signal_context": {},
        "epistemic_reference": {},
        "thresholds": {
            "tau_a": float(tau_a_report.threshold),
            "tau_b": float(tau_b_report.threshold),
            "source": f"constraint_from_labeled_precision_message_only_{calibration_mode}_{scheme}",
            "target_precision_a": tau_a_precision,
            "target_precision_b": tau_b_precision,
            "achieved_precision_a": tau_a_report.achieved_precision,
            "achieved_precision_b": tau_b_report.achieved_precision,
            "selection_reports": selection_reports,
            "fallback_policy": threshold_fallback_policy,
            "adjusted_for_gap": False,
        },
        "metrics": metrics,
        "fit_config": {
            "mode": fit_mode,
            "label_col": DEFAULT_LABEL_COL,
            "labeled_calibration_scheme": scheme,
            "labeled_holdout_ratio": holdout_ratio,
            "labeled_cv_folds": cv_folds,
            "random_state": random_state,
            "threshold_fallback_policy": threshold_fallback_policy,
        },
    }
    if calibration_mode == "isotonic":
        artifact["isotonic"] = isotonic_info
    else:
        artifact["platt_slope"] = float(platt_slope if platt_slope is not None else 1.0)
        artifact["platt_intercept"] = float(
            platt_intercept if platt_intercept is not None else 0.0
        )
    return artifact, metrics


def fit_message_only_calibration(
    *,
    rows: list[dict],
    base_calibration: dict,
    label_col: str,
    scheme: str,
    holdout_ratio: float,
    cv_folds: int,
    tau_a_precision: float,
    tau_b_precision: float,
    random_state: int,
    threshold_fallback_policy: str,
    calibration_mode: str = DEFAULT_CALIBRATION_MODE,
    calibration_rows: list[dict] | None = None,
    evaluation_rows: list[dict] | None = None,
    split_roles: dict | None = None,
    require_repo_disjoint_eval: bool = True,
) -> dict:
    miner.require_calibration_mode(
        base_calibration,
        expected_mode="full_diff",
        context="message-only proxy calibration fit",
    )
    if calibration_rows is None and evaluation_rows is None:
        examples = build_message_only_labeled_examples(
            rows=rows,
            base_calibration=base_calibration,
            label_col=label_col,
        )
        artifact, _ = _fit_calibration_thresholds(
            examples=examples,
            scheme=scheme,
            calibration_mode=calibration_mode,
            holdout_ratio=holdout_ratio,
            cv_folds=cv_folds,
            tau_a_precision=tau_a_precision,
            tau_b_precision=tau_b_precision,
            random_state=random_state,
            threshold_fallback_policy=threshold_fallback_policy,
        )
    else:
        calibration_examples = build_message_only_labeled_examples(
            rows=(calibration_rows or []),
            base_calibration=base_calibration,
            label_col=label_col,
        )
        evaluation_examples = build_message_only_labeled_examples(
            rows=(evaluation_rows or []),
            base_calibration=base_calibration,
            label_col=label_col,
        )
        calibration_labels = [int(item["label"]) for item in calibration_examples]
        evaluation_labels = [int(item["label"]) for item in evaluation_examples]
        if len(calibration_labels) < 2 or len(set(calibration_labels)) < 2:
            raise ValueError(
                "message-only calibration split requires both classes with at least 2 rows"
            )
        if len(evaluation_labels) < 2 or len(set(evaluation_labels)) < 2:
            raise ValueError(
                "message-only evaluation split requires both classes with at least 2 rows"
            )
        calibration_raw_probs = [
            float(item["raw_probability"]) for item in calibration_examples
        ]
        calibration_raw_logits = [
            float(item["raw_logit"]) for item in calibration_examples
        ]
        evaluation_raw_probs = [
            float(item["raw_probability"]) for item in evaluation_examples
        ]
        evaluation_raw_logits = [
            float(item["raw_logit"]) for item in evaluation_examples
        ]
        repo_protocol = summarize_repo_protocol(
            calibration_examples=calibration_examples,
            evaluation_examples=evaluation_examples,
        )
        protocol_violation = bool(
            require_repo_disjoint_eval and not repo_protocol["repo_disjoint_eval"]
        )
        if protocol_violation:
            overlap_examples = ", ".join(repo_protocol["repo_overlap_examples"])
            raise ValueError(
                "message-only explicit split protocol violation: calibration/evaluation repo sets overlap; "
                f"repo_overlap_count={repo_protocol['repo_overlap_count']}, examples=[{overlap_examples}]"
            )
        metrics: dict[str, object] = {
            "labeled_n": len(calibration_labels),
            "labeled_positive_rate": sum(calibration_labels) / len(calibration_labels),
            **repo_protocol,
            "protocol_violation": protocol_violation,
        }
        isotonic_info: dict | None = None
        platt_slope: float | None = None
        platt_intercept: float | None = None
        if calibration_mode == "isotonic":
            isotonic = IsotonicRegression(out_of_bounds="clip")
            isotonic.fit(calibration_raw_probs, calibration_labels)
            eval_probs = [
                float(value) for value in isotonic.predict(evaluation_raw_probs)
            ]
            isotonic_info = {
                "x": [float(value) for value in isotonic.X_thresholds_],
                "y": [float(value) for value in isotonic.y_thresholds_],
                "n": len(calibration_labels),
                "scheme": "explicit_calibration_split_then_evaluation_split",
            }
        else:
            platt_hparams = base_fit.derive_platt_hyperparams(
                n_samples=len(calibration_raw_logits),
                iterations_arg=0,
                learning_rate_arg=0.0,
                l2_arg=0.0,
            )
            platt_slope, platt_intercept = base_fit.fit_platt_scaler(
                calibration_raw_logits,
                calibration_labels,
                iterations=int(platt_hparams["iterations"]),
                learning_rate=float(platt_hparams["learning_rate"]),
                l2=float(platt_hparams["l2"]),
            )
            eval_probs = [
                miner.clip_prob(base_fit.sigmoid(platt_slope * logit + platt_intercept))
                for logit in evaluation_raw_logits
            ]
        metrics.update(
            {
                "raw_brier_eval": base_fit.brier_score(
                    evaluation_raw_probs, evaluation_labels
                ),
                "calibrated_brier_eval": base_fit.brier_score(
                    eval_probs, evaluation_labels
                ),
                "raw_logloss_eval": base_fit.log_loss(
                    evaluation_raw_probs, evaluation_labels
                ),
                "calibrated_logloss_eval": base_fit.log_loss(
                    eval_probs, evaluation_labels
                ),
                "calibration_train_n": len(calibration_labels),
                "threshold_eval_n": len(evaluation_labels),
            }
        )
        eval_fallback_tau_a, eval_fallback_tau_b = (
            base_fit.miner.derive_threshold_seed_from_distribution(eval_probs)
        )
        tau_a_report = select_threshold_by_precision_report(
            eval_probs,
            evaluation_labels,
            target_precision=tau_a_precision,
            fallback=eval_fallback_tau_a,
        )
        tau_b_report = select_threshold_by_precision_report(
            eval_probs,
            evaluation_labels,
            target_precision=tau_b_precision,
            fallback=eval_fallback_tau_b,
            upper_bound=tau_a_report.threshold,
        )
        selection_reports = {
            "tau_a": base_fit.threshold_report_to_dict(tau_a_report),
            "tau_b": base_fit.threshold_report_to_dict(tau_b_report),
        }
        base_fit.apply_threshold_fallback_policy(
            selection_reports, policy=threshold_fallback_policy
        )
        artifact_version = (
            "step1_message_only_isotonic_v1"
            if calibration_mode == "isotonic"
            else "step1_message_only_platt_v1"
        )
        fit_mode = (
            "message_only_isotonic"
            if calibration_mode == "isotonic"
            else "message_only_platt"
        )
        artifact = {
            "artifact_version": artifact_version,
            "model_mode": "message_only",
            "model_role": "proxy",
            "message_protocol": {},
            "scope_protocol": {},
            "type_protocol": {},
            "signal_context": {},
            "epistemic_reference": {},
            "thresholds": {
                "tau_a": float(tau_a_report.threshold),
                "tau_b": float(tau_b_report.threshold),
                "source": f"constraint_from_labeled_precision_message_only_{calibration_mode}_explicit_split",
                "target_precision_a": tau_a_precision,
                "target_precision_b": tau_b_precision,
                "achieved_precision_a": tau_a_report.achieved_precision,
                "achieved_precision_b": tau_b_report.achieved_precision,
                "selection_reports": selection_reports,
                "fallback_policy": threshold_fallback_policy,
                "adjusted_for_gap": False,
            },
            "metrics": metrics,
            "fit_config": {
                "mode": fit_mode,
                "label_col": DEFAULT_LABEL_COL,
                "labeled_calibration_scheme": "explicit_annotated_split_protocol",
                "labeled_holdout_ratio": holdout_ratio,
                "labeled_cv_folds": cv_folds,
                "random_state": random_state,
                "threshold_fallback_policy": threshold_fallback_policy,
                "require_repo_disjoint_eval": bool(require_repo_disjoint_eval),
            },
        }
        if calibration_mode == "isotonic":
            artifact["isotonic"] = isotonic_info
        else:
            artifact["platt_slope"] = float(
                platt_slope if platt_slope is not None else 1.0
            )
            artifact["platt_intercept"] = float(
                platt_intercept if platt_intercept is not None else 0.0
            )
    artifact["message_protocol"] = dict(base_calibration.get("message_protocol") or {})
    artifact["scope_protocol"] = dict(base_calibration.get("scope_protocol") or {})
    artifact["type_protocol"] = dict(base_calibration.get("type_protocol") or {})
    artifact["signal_context"] = dict(base_calibration.get("signal_context") or {})
    artifact["epistemic_reference"] = dict(
        base_calibration.get("epistemic_reference") or {}
    )
    artifact["fit_config"]["label_col"] = label_col
    artifact["fit_config"]["base_calibration_artifact"] = str(
        base_calibration.get("artifact_version", "")
    )
    artifact["fit_config"]["base_primary_artifact_version"] = str(
        base_calibration.get("artifact_version", "")
    )
    artifact["fit_config"]["base_primary_model_mode"] = str(
        base_calibration.get("model_mode")
        or miner.calibration_model_mode(base_calibration)
    )
    artifact["fit_config"]["annotated_split_roles"] = split_roles or {}
    artifact["fit_config"]["require_repo_disjoint_eval"] = bool(
        require_repo_disjoint_eval
    )
    usage_rows = (
        list(calibration_rows or []) + list(evaluation_rows or [])
        if (calibration_rows is not None or evaluation_rows is not None)
        else list(rows)
    )
    coverage = base_fit.Counter(
        (
            str(row.get("type", "")).strip(),
            label_protocol.resolve_label_record(row, label_col=label_col)[
                "selected_label_int"
            ],
        )
        for row in usage_rows
        if label_protocol.resolve_label_record(row, label_col=label_col)[
            "selected_label_int"
        ]
        is not None
    )
    artifact["metrics"]["type_label_counts"] = {
        f"{commit_type}:{label}": count
        for (commit_type, label), count in sorted(coverage.items())
    }
    artifact["fit_config"]["label_usage_summary"] = {
        "calibration": label_protocol.build_label_usage_summary(
            list(calibration_rows or rows), label_col=label_col
        ),
        "evaluation": label_protocol.build_label_usage_summary(
            list(evaluation_rows or rows), label_col=label_col
        ),
    }
    return artifact


def main() -> None:
    args = parse_args()
    if not args.allow_legacy_single_split and not (
        args.calibration_input and args.evaluation_input
    ):
        raise ValueError(
            "message-only calibration now requires explicit calibration/evaluation split inputs; "
            "pass --allow-legacy-single-split to bypass this guard"
        )
    rows = load_rows(Path(args.input)) if args.input else []
    calibration_rows, evaluation_rows, split_roles = resolve_message_only_split_rows(
        args, rows
    )
    base_calibration = miner.load_calibration(args.base_calibration)
    artifact = fit_message_only_calibration(
        rows=rows,
        base_calibration=base_calibration,
        label_col=args.label_col,
        scheme=args.labeled_calibration_scheme,
        holdout_ratio=args.labeled_holdout_ratio,
        cv_folds=args.labeled_cv_folds,
        tau_a_precision=args.tau_a_precision,
        tau_b_precision=args.tau_b_precision,
        random_state=args.random_state,
        threshold_fallback_policy=args.threshold_fallback_policy,
        calibration_mode=args.calibration_mode,
        calibration_rows=calibration_rows,
        evaluation_rows=evaluation_rows,
        split_roles=split_roles,
        require_repo_disjoint_eval=bool(args.require_repo_disjoint_eval),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    thresholds = artifact.get("thresholds", {})
    print(f"tau_a={float(thresholds.get('tau_a', float('nan'))):.6f}")
    print(f"tau_b={float(thresholds.get('tau_b', float('nan'))):.6f}")
    print(output_path.as_posix())


if __name__ == "__main__":
    main()
