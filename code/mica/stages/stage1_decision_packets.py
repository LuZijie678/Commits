from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json


def build_threshold_approval_packet(
    *,
    threshold_spec_path: str | Path,
    threshold_report_path: str | Path,
    split_exposure_audit: dict[str, Any],
) -> dict[str, Any]:
    threshold_spec = read_json(threshold_spec_path)
    threshold_report = read_json(threshold_report_path)
    if not isinstance(threshold_spec, dict) or not isinstance(threshold_report, dict):
        raise ValueError("Threshold inputs must be JSON objects.")
    selected_thresholds = {
        key: value
        for key, value in threshold_spec.items()
        if key.endswith(("_min", "_max"))
    }
    return {
        "schema_version": "mica-threshold-approval-packet-v1",
        "decision_version": str(threshold_spec.get("candidate_threshold_version") or "stage1_threshold_candidate"),
        "status": "pending_human_approval",
        "selected_thresholds": selected_thresholds,
        "checkpoint_hash": threshold_spec.get("selected_checkpoint_hash"),
        "dev_manifest_hash": threshold_spec.get("selected_dev_manifest_hash"),
        "threshold_report_hash": _sha256_json_file(threshold_report_path),
        "selection_rule": {
            "selection_split": threshold_report.get("selection_split"),
            "selection_criterion": threshold_report.get("selection_criterion"),
            "selected_operating_point": threshold_report.get("selected_operating_point"),
        },
        "dev_only": str(threshold_report.get("selection_split")) == "dev_only",
        "official_final_test_not_used": split_exposure_audit.get("conclusion") != "final_test_already_exposed",
        "candidate_validation_not_used_for_selection": True,
        "approved_by": None,
        "approved_at": None,
        "no_further_tuning_after_approval": True,
    }


def build_kmax_decision_packet(
    *,
    kmax_report_path: str | Path,
    proposed_tau: float,
) -> dict[str, Any]:
    report = read_json(kmax_report_path)
    if not isinstance(report, dict):
        raise ValueError("Kmax report must be a JSON object.")
    return {
        "schema_version": "mica-kmax-decision-packet-v1",
        "decision_version": f"kmax_decision_{report.get('kmax')}_{str(proposed_tau).replace('.', '_')}",
        "status": "pending_human_approval",
        "amendment_type": "pre_test_protocol_amendment",
        "predeclared": False,
        "proposed_tau": float(proposed_tau),
        "selected_Kmax": report.get("selected_Kmax", {}).get("value"),
        "full_coverage_curve": list(report.get("coverage_curve_train_dev", [])),
        "confidence_interval": dict(report.get("repository_cluster_bootstrap_ci", {})),
        "count_distribution": dict(report.get("train_dev_count_distribution", {})),
        "rationale": "Train/dev exact-count coverage has been computed, but Kmax remains pending human approval because tau was not predeclared before viewing the distribution.",
        "report_hashes": {
            "kmax_report": _sha256_json_file(kmax_report_path),
        },
        "manifest_hashes": dict(report.get("source_manifest_hashes", {})),
        "approved_by": None,
        "approved_at": None,
        "no_further_Kmax_tuning_after_approval": True,
    }


def _sha256_json_file(path: str | Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
