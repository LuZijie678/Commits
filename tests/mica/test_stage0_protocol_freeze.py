from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json
from code.mica.runners.run_stage0_protocol_freeze import main as stage0_main
from code.mica.stage0.leakage_report import build_global_leakage_report, check_asset_boundary


def test_stage0_runner_requires_dry_run(tmp_path) -> None:
    data_card = tmp_path / "DATA_CARD.md"
    eval_protocol = tmp_path / "EVAL_PROTOCOL.md"
    registry = tmp_path / "registry.json"
    kmax_rows = tmp_path / "kmax_rows.jsonl"
    data_card.write_text("# DATA_CARD\n", encoding="utf-8")
    eval_protocol.write_text("# EVAL_PROTOCOL\n", encoding="utf-8")
    registry.write_text(json.dumps({"assets": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="requires explicit --dry-run"):
        stage0_main(
            [
                "--data-card",
                str(data_card),
                "--eval-protocol",
                str(eval_protocol),
                "--asset-registry",
                str(registry),
                "--output-report",
                str(tmp_path / "report.json"),
                "--output-md",
                str(tmp_path / "report.md"),
            ]
        )


def test_stage0_leakage_report_flags_eval_only_and_overlap(tmp_path) -> None:
    registry = {
        "assets": {
            "hard_b_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage2_calibration", "tuning"]},
            "m_final_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"]},
            "real_domain_split_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"]},
            "real_domain_selective_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"]},
        }
    }
    rows = {
        "hard_b_test": [{"sample_id": "s1", "sha": "a"}],
        "m_final_test": [{"sample_id": "s1", "sha": "b"}],
    }

    boundary = check_asset_boundary(registry)
    report = build_global_leakage_report(registry, rows)

    assert boundary["valid"] is True
    assert report["cross_asset_overlap"]["sample_id_overlap_count"] == 1
    assert "hard_b_test" in report["eval_only_assets"]


def test_stage0_runner_writes_readiness_reports(tmp_path) -> None:
    data_card = tmp_path / "DATA_CARD.md"
    eval_protocol = tmp_path / "EVAL_PROTOCOL.md"
    registry = tmp_path / "registry.json"
    kmax_rows = tmp_path / "kmax_rows.jsonl"
    data_card.write_text(
        "\n".join(
            [
                "# DATA_CARD",
                "Step1 high-confidence k=1",
                "Step2 strict synthetic k1/k2",
                "Step2 Step3-ready synthetic",
                "hard_b train/dev/test",
                "M weak train/dev/final-test",
                "M-align-calib",
                "RealDomainSplit split:",
                "RealDomainSelective split:",
                "RealDomainSelective labels:",
                "RealDomainBinary is deprecated and must not be used in final tables",
                "renderer data, optional",
                "high",
                "medium-high",
                "medium",
                "medium-low",
                "eval-only",
                "M-final-test = eval-only",
                "hard_b-test = eval-only",
                "RealDomainSplit-test = eval-only",
                "RealDomainSelective-test = eval-only",
                "M weak = censored k>=2 only",
                "M-align-calib = small real alignment calibration/eval only",
                "intent_subjects/messages = renderer only, not attribution matching",
                "Kmax is a task-scope constant, not a tuned model hyperparameter",
                "Kmax coverage statistics must be recorded before training",
                "k > Kmax commits are treated as complex/overflow cases",
                "overflow/abstention is required for out-of-scope decomposition",
                "Kmax selection protocol uses train/dev annotation assets only",
                "coverage@Kmax must be reported on every evaluation split",
                "never tune Kmax according to final-test attribution or message utility scores",
                "synthetic cardinality distribution alone cannot justify Kmax",
                "Kmax=4 is acceptable only if DATA_CARD shows target-domain coverage",
                "Kmax freeze protocol",
                "status: protocol_defined_but_value_not_populated",
                "status: protocol_defined_but_stats_not_populated",
                "paper_readiness: not ready until train/dev coverage stats are populated and frozen",
                "current_workspace_state: implementation_default_not_final_paper_task_boundary",
                "atomic-source leakage is prohibited",
                "synthetic variants from the same atomic source cannot cross train/dev/test",
                "no commits from the same PR/tangled construction group may cross splits",
                "commit messages / PR titles / issue texts / gold intent ids / synthetic construction metadata are forbidden as attribution inputs",
                "real_alignment_benchmark",
                "heldout_policy: to_be_frozen_before_final_evaluation",
                "pseudo_alignment_allowed_as_gold: false",
                "synthetic_labels_allowed_as_real_gold: false",
            ]
        ),
        encoding="utf-8",
    )
    eval_protocol.write_text(
        "\n".join(
            [
                "# EVAL_PROTOCOL",
                "Stage 1 synthetic attribution validation",
                "Stage 2 hard_b / M calibration",
                "Stage 3 real alignment calibration/eval",
                "Stage 4 deterministic evidence-locked rendering",
                "RealDomainSplit / hard_b main table",
                "alignment benchmark table",
                "message utility table",
                "anti-shortcut / OOD stress",
                "baseline table",
                "RealDomainSplit table",
                "RealDomainSelective table",
                "Abstention thresholds:",
                "selection_split: dev only",
                "default_rule: fixed target coverage or full coverage-risk curve",
                "final_test_tuning: forbidden",
                "values_to_be_populated_by_dev_calibration_script",
                "real alignment benchmark held-out policy:",
                "status: protocol_requires_freeze_before_final_evaluation",
                "cross_repository_heldout_primary",
                "time_based_heldout_secondary",
                "unspecified repo overlap",
                "final-test never used for training/tuning",
                "Kmax coverage reporting is mandatory on every evaluation split",
                "oracle-k vs predicted-k must be reported",
                "generation is downstream utility, not main contribution",
                "overflow / abstention rate must be reported",
                "clustering is a baseline, not the primary formulation",
                "renderer scores cannot select attribution checkpoints",
                "background/null must be audited separately from semantic uncertainty",
                "oracle-k / predicted-k / overflow must be jointly reported where applicable",
                "Stage 2 uses hard_b and M weak labels only for split/no-split/abstain boundary calibration",
                "Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration",
                "renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings",
                "alignment benchmark construction must be documented",
                "coverage-risk curve must be reported for abstaining models",
                "selective attribution metrics must be reported at fixed coverage levels",
                "abstention precision and false-abstain rate must be reported",
                "forced-decomposition error on out-of-scope commits must be reported",
                "RealDomainSplit = k=1 vs k>=2 split / no-split boundary evaluation",
                "RealDomainSelective = in-scope decomposable vs overflow / abstain evaluation",
                "FPR_hard_b = percentage of hard_b single-intent commits predicted as multi-intent",
                "pseudo alignment cannot be used as final real-alignment gold",
                "synthetic construction labels cannot be mixed into the real alignment benchmark",
                "these diagnostics are validity checks, not method-selection ablations",
                "Primary setting:",
                "cross-repository held-out evaluation",
                "no repository overlap between train/dev calibration assets and final real alignment test",
                "Secondary setting, if cross-repository sample size is insufficient:",
                "time-based held-out evaluation within repository",
                "repo overlap decision cannot remain pending in the final protocol",
                "Background slot audit metrics",
                "background assignment rate",
                "foreground evidence swallowed by background",
                "foreground-to-background error",
                "missing-intent rate by file role",
                "background precision on rule-verified background units",
                "background recall on rule-verified background units",
                "semantic uncertainty must not be counted as correct background assignment",
            ]
        ),
        encoding="utf-8",
    )
    registry.write_text(
        json.dumps(
            {
                "assets": {
                    "hard_b_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage2_calibration", "tuning"]},
                    "m_final_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"]},
                    "real_domain_split_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"]},
                    "real_domain_selective_test": {"eval_only": True, "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"]},
                }
            }
        ),
        encoding="utf-8",
    )
    kmax_rows.write_text(
        "\n".join(
            [
                json.dumps({"sample_id": "tr1", "split": "train", "gold_count": 1, "cardinality_label_type": "exact_k1_gold", "source_type": "step1_high_conf_single"}),
                json.dumps({"sample_id": "dv1", "split": "dev", "gold_count": 4, "cardinality_label_type": "exact_k4_gold", "source_type": "manual_real"}),
                json.dumps({"sample_id": "ts1", "split": "test", "gold_count": 6, "cardinality_label_type": "exact_k6_gold", "source_type": "manual_real"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    stage0_main(
        [
            "--data-card",
            str(data_card),
            "--eval-protocol",
            str(eval_protocol),
            "--asset-registry",
            str(registry),
            "--output-report",
            str(tmp_path / "report.json"),
            "--output-md",
            str(tmp_path / "report.md"),
            "--kmax-coverage-rows-jsonl",
            str(kmax_rows),
            "--kmax",
            "4",
            "--kmax-tau",
            "0.9",
            "--dry-run",
        ]
    )

    report = read_json(tmp_path / "report.json")
    assert report["dry_run"] is True
    assert report["protocol_freeze_ready"] is True
    assert report["training_executed"] is False
    assert report["experiment_manifest"]["runner_name"] == "run_stage0_protocol_freeze"
    assert report["report_schema"]["schema_version"] == "mica-report-v1"
    assert report["kmax_coverage_report"]["status"] == "protocol_defined"
    assert report["kmax_coverage_report"]["train_dev_selection_basis"]["sample_count"] == 2
    assert report["kmax_coverage_report"]["train_dev_selection_basis"]["exact_real_multi_intent_row_count"] == 1
    assert report["kmax_coverage_report"]["coverage_at_Kmax"]["test"]["overflow_rate"] == 1.0
    assert report["report_schema"]["metrics"]["kmax_train_dev_sample_count"] == 2


def test_stage0_formal_readiness_requires_materialized_assets_and_frozen_thresholds(tmp_path) -> None:
    data_card = tmp_path / "DATA_CARD.md"
    eval_protocol = tmp_path / "EVAL_PROTOCOL.md"
    registry = tmp_path / "registry.json"
    thresholds = tmp_path / "thresholds.json"
    data_card.write_text((Path("docs/DATA_CARD.md")).read_text(encoding="utf-8"), encoding="utf-8")
    eval_protocol.write_text((Path("docs/EVAL_PROTOCOL.md")).read_text(encoding="utf-8"), encoding="utf-8")
    thresholds.write_text(json.dumps({"threshold_status": "candidate_sanity_thresholds_pending_advisor_confirmation"}), encoding="utf-8")
    registry.write_text(
        json.dumps(
            {
                "schema_version": "mica-data-asset-registry-v2",
                "registry_status": "formal_assets_populated",
                "assets": {
                    "hard_b_test": {
                        "path": None,
                        "status": "missing",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage2_calibration", "tuning"],
                    },
                    "m_final_test": {
                        "path": None,
                        "status": "missing",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/m_verified/canonical/usable_m_with_real_diff.csv",
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning", "pseudo_label", "filtering"],
                    },
                    "real_domain_split_test": {
                        "path": None,
                        "status": "pending_generation",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": None,
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"],
                    },
                    "real_domain_selective_test": {
                        "path": None,
                        "status": "pending_generation",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": None,
                        "split": "test",
                        "record_count": None,
                        "checksum": None,
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "eval_only": True,
                        "forbidden_stages": ["stage2_train", "stage3_train", "calibration", "tuning"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    stage0_main(
        [
            "--data-card",
            str(data_card),
            "--eval-protocol",
            str(eval_protocol),
            "--asset-registry",
            str(registry),
            "--metric-thresholds",
            str(thresholds),
            "--output-report",
            str(tmp_path / "report.json"),
            "--output-md",
            str(tmp_path / "report.md"),
            "--dry-run",
        ]
    )

    report = read_json(tmp_path / "report.json")
    assert report["protocol_schema_valid"] is True
    assert report["registry_schema_valid"] is True
    assert report["assets_materialized"] is False
    assert report["thresholds_frozen"] is False
    assert report["splits_leakage_clean"] is True
    assert report["formal_ready"] is False


def test_stage0_runner_can_derive_kmax_rows_from_registry_and_fail_closed_without_exact_multi_intent_support(tmp_path) -> None:
    data_card = tmp_path / "DATA_CARD.md"
    eval_protocol = tmp_path / "EVAL_PROTOCOL.md"
    registry = tmp_path / "registry.json"
    step1_train = tmp_path / "step1_train.json"
    hard_b_dev = tmp_path / "hard_b_dev.json"
    data_card.write_text((Path("docs/DATA_CARD.md")).read_text(encoding="utf-8"), encoding="utf-8")
    eval_protocol.write_text((Path("docs/EVAL_PROTOCOL.md")).read_text(encoding="utf-8"), encoding="utf-8")
    step1_train.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "step1_high_conf_single_train",
                "split": "train",
                "formal_ready": True,
                "summary": {"record_count": 1, "repo_count": 1, "duplicate_count": 0, "leakage_group_overlap_count": 0},
                "rows": [
                    {
                        "sample_id": "tr1",
                        "split": "train",
                        "source_type": "step1_high_conf_single",
                        "cardinality_label_type": "exact_k1_gold",
                        "gold_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    hard_b_dev.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": "hard_b_dev",
                "split": "dev",
                "formal_ready": True,
                "summary": {"record_count": 1, "repo_count": 1, "duplicate_count": 0, "leakage_group_overlap_count": 0},
                "rows": [
                    {
                        "sample_id": "dv1",
                        "split": "dev",
                        "source_type": "hard_b",
                        "cardinality_label_type": "exact_k1_gold",
                        "gold_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry.write_text(
        json.dumps(
            {
                "schema_version": "mica-data-asset-registry-v2",
                "registry_status": "formal_assets_populated",
                "assets": {
                    "step1_high_conf_single_train": {
                        "path": str(step1_train),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv",
                        "split": "train",
                        "record_count": 1,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage1_train"],
                        "allowed_stages": ["stage1_train"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                    "hard_b_dev": {
                        "path": str(hard_b_dev),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv",
                        "split": "dev",
                        "record_count": 1,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage2_dev"],
                        "allowed_stages": ["stage2_dev"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    stage0_main(
        [
            "--data-card",
            str(data_card),
            "--eval-protocol",
            str(eval_protocol),
            "--asset-registry",
            str(registry),
            "--output-report",
            str(tmp_path / "report.json"),
            "--output-md",
            str(tmp_path / "report.md"),
            "--dry-run",
        ]
    )

    report = read_json(tmp_path / "report.json")
    assert report["kmax_coverage_report"]["status"] == "protocol_defined_but_real_multi_intent_counts_not_populated"
    assert report["kmax_coverage_report"]["train_dev_selection_basis"]["sample_count"] == 2
    assert report["kmax_coverage_report"]["train_dev_selection_basis"]["exact_real_multi_intent_row_count"] == 0
    assert report["Kmax_protocol_frozen"] is False
