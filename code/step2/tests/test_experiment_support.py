from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "code"


def load_module(filename: str):
    module_path = CODE_DIR / filename
    if str(CODE_DIR) not in sys.path:
        sys.path.insert(0, str(CODE_DIR))
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_tool_module(filename: str):
    module_path = ROOT / "tools" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_source_manifest(path: Path, csv_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "total_selected": 1,
                "previously_labeled_excluded": 0,
                "sampling_plan": [],
                "label_schema": {
                    "A": "strong single-intent",
                    "B": "broad but cohesive single-intent",
                    "U": "uncertain/boundary",
                    "M": "true multi-intent",
                },
                "paths": {
                    "csv": str(csv_path),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_fewshot_build_manifest(path: Path, pool_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "asset_name": "fewshot_pool_formal_test",
                "asset_version": "v1-test",
                "build_date_utc": "2026-05-13T00:00:00Z",
                "builder": "test-suite",
                "source_datasets": ["test_fixture"],
                "schema_table": "fewshot_examples",
                "db_filename": pool_path.name,
                "total_rows_train": 10,
                "eligible_rows_train": 10,
                "verified_rows_train": 10,
                "common_signature_coverage": {"fix+test": 3},
                "style_cleaning_policy": {"strict_style": True, "max_subject_chars": 120, "max_subject_tokens": 20},
                "thresholds": {"min_total": 1, "min_per_common_signature": 0, "probe_type_signature": "fix+test", "probe_k": 1},
                "validation": {"audit_pass": True, "retrieval_probe_ok": True, "preflight_passed": True},
                "build_inputs": {"audit_script": "code/audit_fewshot_pool.py"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_message_score(
    *,
    coverage_min_r: float = 0.0,
    faithfulness_p: float = 0.0,
    quality_weight: float = 0.0,
    format_ok: int = 1,
) -> dict:
    return {
        "coverage_min_r": coverage_min_r,
        "coverage_avg_r": coverage_min_r,
        "coverage_balance": 1.0 if coverage_min_r else 0.0,
        "faithfulness_p": faithfulness_p,
        "style_score": 1.0 if format_ok else 0.0,
        "relevance_score": 1.0 if format_ok else 0.0,
        "artifact_hit_count": 0,
        "generic_phrase_hit": 0,
        "format": format_ok,
        "bertscore_compute_invalid": 0,
        "message_quality_weight": quality_weight,
    }


def make_sample(
    sample_id: str,
    *,
    repo: str = "owner/repo",
    precheck_status: str = "pass",
    generation_status: str = "generated",
    message_status: str = "pass",
    few_shot_source: str = "exact_kway",
    synthetic_subject: str = "fix parser and add tests",
    final_sample_weight: float = 0.8,
    coverage_min_r: float = 0.7,
    faithfulness_p: float = 0.9,
    quality_weight: float = 0.8,
    generation_attempted: bool = True,
    generation_failure_reason: str = "",
    difficulty_level: str = "",
    type_pair: str = "fix+test",
) -> dict:
    return {
        "sample_id": sample_id,
        "repo": repo,
        "type_pair": type_pair,
        "precheck_status": precheck_status,
        "generation_status": generation_status,
        "message_status": message_status,
        "few_shot_source": few_shot_source,
        "synthetic_subject": synthetic_subject,
        "synthetic_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n" * 20,
        "intent_subjects": ["fix parser", "add tests"],
        "message_scores": make_message_score(
            coverage_min_r=coverage_min_r,
            faithfulness_p=faithfulness_p,
            quality_weight=quality_weight,
            format_ok=1,
        ),
        "message_meta": {
            "llm_generation_attempted": generation_attempted,
            "generation_success": generation_status == "generated",
            "generation_failure_reason": generation_failure_reason,
            "generation_attempts": 1 if generation_attempted else 0,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
        },
        "final_sample_weight": final_sample_weight,
        "difficulty_level": difficulty_level,
        "sources": [
            {
                "sha": f"{sample_id}_sha1",
                "repo": repo,
                "type": "fix",
                "subject": "fix parser",
                "message": "fix parser",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
            },
            {
                "sha": f"{sample_id}_sha2",
                "repo": repo,
                "type": "test",
                "subject": "add tests",
                "message": "add tests",
                "git_diff": "diff --git a/test_a.py b/test_a.py\n@@ -1 +1 @@\n-old\n+new\n",
            },
        ],
    }


def test_emit_proxy_env_builds_http_and_https_exports() -> None:
    mod = load_tool_module("emit_proxy_env.py")
    values = {
        "HTTPEnable": "1",
        "HTTPProxy": "127.0.0.1",
        "HTTPPort": "7890",
        "HTTPSEnable": "1",
        "HTTPSProxy": "127.0.0.1",
        "HTTPSPort": "7890",
    }
    exports = mod.build_proxy_exports(values)
    assert 'export HTTP_PROXY="http://127.0.0.1:7890"' in exports
    assert 'export HTTPS_PROXY="http://127.0.0.1:7890"' in exports


def enrich_difficulty_realism(
    row: dict,
    *,
    difficulty_level: str = "C",
    difficulty_name: str = "multi-intent separable",
    intent_cardinality: str = "multi-2",
    structure_pattern: str = "separable",
    construction_route: str = "route_2_multi_intent",
    realism_score: float = 0.72,
    rho: float = 0.72,
    threshold_tau_realism_low: float = 0.5,
) -> dict:
    row["difficulty_level"] = difficulty_level
    row["difficulty_name"] = difficulty_name
    row["intent_cardinality"] = intent_cardinality
    row["structure_pattern"] = structure_pattern
    row["construction_route"] = construction_route
    row["training_focus"] = ["intent count prediction", "multi-intent message coverage"]
    row["difficulty_features"] = {
        "intent_count": 2,
        "intent_cardinality": intent_cardinality,
        "structure_pattern": structure_pattern,
        "total_file_count": 2,
        "hunk_count": 3,
        "module_count": 2,
        "file_role_mix": 0.5,
        "main_topic_coherence": 0.44,
        "shared_file_count": 1,
        "shared_file_ratio": 0.5,
        "same_file_hunk_count": 2,
        "identifier_overlap_score": 0.33,
        "max_pairwise_identifier_overlap": 0.4,
        "avg_pairwise_identifier_overlap": 0.33,
        "module_overlap_score": 0.25,
        "dependency_hint_score": 0.28,
        "patch_conflict_risk": 0.1,
    }
    row["difficulty_assignment_meta"] = {
        "threshold_source": "v1_default_thresholds",
        "feature_basis": "construction_units",
        "rule": f"{intent_cardinality}+{structure_pattern}->{difficulty_level}",
        "thresholds": {"tau_realism_low": threshold_tau_realism_low},
        "pipeline_owner": "step2_controllable_synthetic_construction",
        "pipeline_order": [
            "sample_construction",
            "difficulty_feature_extraction",
            "difficulty_level_assignment",
            "realism_feature_scoring",
            "joint_weight_metadata",
        ],
    }
    row["realism_features"] = {
        "s_structure": 0.71,
        "s_interleave": 0.66,
        "s_context": 0.82,
        "s_overlap": 0.57,
        "s_style": 0.86,
    }
    row["realism_score"] = realism_score
    row["rho"] = rho
    row["realism_weight_config"] = {
        "enabled": True,
        "owner_stage": "step2_controllable_synthetic_construction",
        "rho_field": "rho",
        "realism_score_field": "realism_score",
        "weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight",
    }
    row["perturbation_plan"] = {
        "interleaving": {"enabled": True, "mode": "round_robin"},
        "context_normalization": {"enabled": True, "mode": "light"},
    }
    row["perturbation_applied"] = {
        "interleaving": {"enabled": True, "applied": True},
        "context_normalization": {"enabled": True, "applied": True},
    }
    return row


def test_experiment_manifest_create_validate_and_redact(tmp_path: Path) -> None:
    mod = load_module("experiment_manifest.py")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "seed": 7,
                "message_stage_enabled": True,
                "message_gate_enabled": True,
                "fewshot_enabled": True,
                "deepseek_api_key": "SECRET_KEY_SHOULD_NOT_LEAK",
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "source.csv"
    source_path.write_text("repo,sha\nowner/repo,abc123\n", encoding="utf-8")
    fewshot_path = tmp_path / "fewshot.csv"
    fewshot_path.write_text("repo,sha\nfewshot/repo,def456\n", encoding="utf-8")
    source_manifest_path = tmp_path / "source_manifest.json"
    fewshot_build_manifest_path = tmp_path / "fewshot_build_manifest.json"
    write_source_manifest(source_manifest_path, source_path)
    write_fewshot_build_manifest(fewshot_build_manifest_path, fewshot_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    manifest = mod.build_manifest(
        project_root=tmp_path,
        config_path=config_path,
        source_data_path=source_path,
        fewshot_pool_path=fewshot_path,
        source_manifest_path=source_manifest_path,
        fewshot_build_manifest_path=fewshot_build_manifest_path,
        output_dir=output_dir,
        run_purpose="formal",
        random_seed=7,
    )
    errors = mod.validate_manifest_dict(manifest)

    assert errors == []
    assert manifest["inputs"]["source_data"]["exists"] is True
    assert manifest["inputs"]["fewshot_pool"]["type"] == "csv"
    assert manifest["protocol"]["run_valid_for_paper"] is True
    assert manifest["inputs"]["source_manifest"]["exists"] is True
    assert manifest["inputs"]["fewshot_build_manifest"]["exists"] is True
    assert manifest["protocol"]["formal_assets_ready"] is True
    assert "SECRET_KEY_SHOULD_NOT_LEAK" not in json.dumps(manifest, ensure_ascii=False)


def test_experiment_manifest_missing_file_and_validate_failure(tmp_path: Path) -> None:
    mod = load_module("experiment_manifest.py")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    manifest = mod.build_manifest(
        project_root=tmp_path,
        config_path=config_path,
        source_data_path=tmp_path / "missing_source.csv",
        fewshot_pool_path=tmp_path / "missing_pool.sqlite",
        source_manifest_path=tmp_path / "missing_source_manifest.json",
        fewshot_build_manifest_path=tmp_path / "missing_fewshot_build_manifest.json",
        output_dir=output_dir,
        run_purpose="debug",
        random_seed=42,
    )
    assert manifest["inputs"]["source_data"]["exists"] is False
    assert manifest["inputs"]["fewshot_pool"]["exists"] is False
    assert manifest["protocol"]["run_valid_for_paper"] is False
    assert manifest["protocol"]["formal_assets_ready"] is False

    broken = {"manifest_version": "step2_experiment_manifest_v1"}
    errors = mod.validate_manifest_dict(broken)
    assert errors


def test_formal_assets_accept_windows_style_source_manifest_path(tmp_path: Path) -> None:
    mod = load_module("formal_assets.py")
    source_path = tmp_path / "annotation_round3_atomicity_spectrum_3000_minimal.csv"
    source_path.write_text("repo,sha\nowner/repo,abc123\n", encoding="utf-8")
    source_manifest_path = tmp_path / "annotation_round3_atomicity_spectrum_3000_manifest.json"
    source_manifest_path.write_text(
        json.dumps(
            {
                "total_selected": 1,
                "sampling_plan": [],
                "label_schema": {"A": "strong single-intent"},
                "paths": {
                    "csv": "D:\\Multi-intent\\sample_label\\annotation_round3_atomicity_spectrum_3000_minimal.csv",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fewshot_pool_path = tmp_path / "fewshot_pool.db"
    fewshot_pool_path.write_text("placeholder", encoding="utf-8")
    fewshot_build_manifest_path = tmp_path / "build_manifest.json"
    write_fewshot_build_manifest(fewshot_build_manifest_path, fewshot_pool_path)

    status = mod.summarize_formal_assets(
        source_data_path=source_path,
        source_manifest_path=source_manifest_path,
        fewshot_pool_path=fewshot_pool_path,
        fewshot_build_manifest_path=fewshot_build_manifest_path,
        require_source_manifest=True,
        require_fewshot_build_manifest=True,
    )

    assert status["source_manifest"]["matches_source_csv"] is True
    assert "source_manifest_csv_mismatch" not in status["blockers"]


def test_experiment_metrics_denominators_and_failure_taxonomy(tmp_path: Path) -> None:
    mod = load_module("experiment_metrics.py")
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    samples = [
        make_sample(
            "skip_1",
            precheck_status="skip",
            generation_status="not_attempted_precheck_skip",
            message_status="not_generated_precheck_skip",
            few_shot_source="failed",
            synthetic_subject="",
            final_sample_weight=0.0,
            quality_weight=0.0,
            generation_attempted=False,
        ),
        make_sample(
            "gen_fail",
            generation_status="generation_failed",
            message_status="not_generated_generation_failed",
            few_shot_source="failed",
            synthetic_subject="",
            final_sample_weight=0.0,
            quality_weight=0.0,
            generation_failure_reason="api_timeout",
        ),
        make_sample(
            "judge_fail",
            generation_status="judge_failed",
            message_status="not_scored",
            few_shot_source="type_overlap",
            synthetic_subject="",
            final_sample_weight=0.0,
            quality_weight=0.0,
        ),
        make_sample(
            "reject_1",
            generation_status="generated",
            message_status="reject",
            few_shot_source="single_type_overlap",
            synthetic_subject="reject message",
            final_sample_weight=0.0,
            coverage_min_r=0.3,
            faithfulness_p=0.5,
            quality_weight=0.2,
        ),
        make_sample(
            "pass_1",
            generation_status="generated",
            message_status="pass",
            few_shot_source="exact_kway",
            synthetic_subject="fix parser and add tests",
            final_sample_weight=0.9,
            coverage_min_r=0.9,
            faithfulness_p=0.95,
            quality_weight=0.9,
        ),
        make_sample(
            "fallback_1",
            generation_status="generated",
            message_status="fallback",
            few_shot_source="generic_fallback",
            synthetic_subject="update docs and fix typo",
            final_sample_weight=0.5,
            coverage_min_r=0.6,
            faithfulness_p=0.8,
            quality_weight=0.6,
        ),
    ]
    write_jsonl(output_dir / "synthetic_samples.jsonl", samples)
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", [samples[4], samples[5]])

    metrics = mod.aggregate_experiment_metrics(output_dir=output_dir)

    assert metrics["counts"]["total_samples"] == 6
    assert metrics["counts"]["precheck_skip"] == 1
    assert metrics["counts"]["generation_attempted"] == 5
    assert metrics["counts"]["generation_success"] == 3
    assert metrics["counts"]["generation_failed"] == 1
    assert metrics["counts"]["judge_failed"] == 1
    assert metrics["counts"]["true_message_reject"] == 1
    assert metrics["counts"]["message_pass"] == 1
    assert metrics["counts"]["message_fallback"] == 1
    assert metrics["counts"]["step3_ready"] == 2
    assert metrics["rates"]["generation_failure_rate_attempted"] == pytest.approx(0.2)
    assert metrics["rates"]["true_message_reject_rate_scored"] == pytest.approx(1 / 3)
    assert metrics["fewshot"]["exact_count"] == 1
    assert metrics["fewshot"]["partial_count"] == 2
    assert metrics["fewshot"]["generic_count"] == 1
    assert metrics["fewshot"]["failed_count"] == 1
    assert metrics["errors"]["by_error_code"]["generation_failure:api_timeout"] == 1


def test_experiment_metrics_includes_difficulty_realism_summary(tmp_path: Path) -> None:
    mod = load_module("experiment_metrics.py")
    output_dir = tmp_path / "difficulty_metrics"
    output_dir.mkdir()
    sample_c = enrich_difficulty_realism(make_sample("c1"), difficulty_level="C", structure_pattern="separable", realism_score=0.4, rho=0.4, threshold_tau_realism_low=0.7)
    sample_d = enrich_difficulty_realism(make_sample("d1"), difficulty_level="D", difficulty_name="multi-intent entangled", structure_pattern="entangled", construction_route="route_2_multi_intent", realism_score=0.9, rho=0.9, threshold_tau_realism_low=0.7)
    write_jsonl(output_dir / "synthetic_samples.jsonl", [sample_c, sample_d])
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", [sample_c, sample_d])
    (output_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "run_valid_for_paper": True,
                "difficulty_realism": {
                    "tau_realism_low": 0.7,
                    "tau_realism_low_source": "config",
                },
                "run_stats": {
                    "difficulty_realism_summary": {
                        "level_distribution": {"C": 1, "D": 1},
                        "intent_cardinality_distribution": {"multi-2": 2},
                        "structure_pattern_distribution": {"separable": 1, "entangled": 1},
                        "pipeline_owner": "step2_controllable_synthetic_construction",
                        "pipeline_order": [
                            "sample_construction",
                            "difficulty_feature_extraction",
                            "difficulty_level_assignment",
                            "realism_feature_scoring",
                            "joint_weight_metadata",
                        ],
                        "realism_weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight",
                        "realism_score_summary": {
                            "mean": 0.65,
                            "p50": 0.4,
                            "p90": 0.9,
                            "low_realism_count": 1,
                            "tau_realism_low": 0.7,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "message_gate_report.json").write_text(
        json.dumps({"message_gate_passed": True}),
        encoding="utf-8",
    )

    metrics = mod.aggregate_experiment_metrics(output_dir=output_dir)
    difficulty = metrics["difficulty_realism"]
    assert difficulty["difficulty_level_counts"] == {"C": 1, "D": 1}
    assert difficulty["intent_cardinality_counts"] == {"multi-2": 2}
    assert difficulty["structure_pattern_counts"] == {"separable": 1, "entangled": 1}
    assert difficulty["construction_route_counts"] == {"route_2_multi_intent": 2}
    assert difficulty["realism_score"] == {
        "mean": 0.65,
        "p50": 0.4,
        "p90": 0.9,
        "low_count": 1,
        "tau_low": 0.7,
    }
    assert difficulty["rho"] == {"mean": 0.65, "p50": 0.4, "p90": 0.9}
    assert difficulty["identifier_overlap_score"] == {"mean": 0.33, "p50": 0.33, "p90": 0.33}
    assert difficulty["dependency_hint_score"] == {"mean": 0.28, "p50": 0.28, "p90": 0.28}
    assert difficulty["main_topic_coherence"] == {"mean": 0.44, "p50": 0.44, "p90": 0.44}
    assert difficulty["shared_file_ratio"] == {"mean": 0.5, "p50": 0.5, "p90": 0.5}
    assert difficulty["realism_weight_formula"] == "sample_confidence * pair_quality_weight * rho * message_quality_weight"
    assert difficulty["realism_weight_config"]["enabled"] is True
    assert difficulty["pipeline_owner"] == "step2_controllable_synthetic_construction"
    assert difficulty["pipeline_order"] == [
        "sample_construction",
        "difficulty_feature_extraction",
        "difficulty_level_assignment",
        "realism_feature_scoring",
        "joint_weight_metadata",
    ]


def test_experiment_metrics_missing_difficulty_realism_warns_instead_of_crash(tmp_path: Path) -> None:
    mod = load_module("experiment_metrics.py")
    output_dir = tmp_path / "missing_difficulty_metrics"
    output_dir.mkdir()
    sample = make_sample("plain_1")
    write_jsonl(output_dir / "synthetic_samples.jsonl", [sample])
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", [sample])
    metrics = mod.aggregate_experiment_metrics(output_dir=output_dir)
    assert metrics["difficulty_realism"]["difficulty_level_counts"] == {}
    assert any(item.startswith("difficulty_realism_missing:") for item in metrics["warnings"])


def test_experiment_metrics_missing_files_warn_instead_of_crash(tmp_path: Path) -> None:
    mod = load_module("experiment_metrics.py")
    output_dir = tmp_path / "empty"
    output_dir.mkdir()
    metrics = mod.aggregate_experiment_metrics(output_dir=output_dir)
    assert metrics["warnings"]
    assert metrics["counts"]["total_samples"] == 0


def test_experiment_report_handles_missing_gate_report_and_redacts(tmp_path: Path) -> None:
    mod = load_module("experiment_report.py")
    manifest = {
        "manifest_version": "step2_experiment_manifest_v1",
        "created_at_utc": "2026-05-13T00:00:00Z",
        "project_root": str(tmp_path),
        "git": {"commit": "abc", "branch": "main", "dirty": False},
        "run": {
            "run_id": "run_demo",
            "run_purpose": "analysis",
            "config_path": "configs/x.json",
            "output_dir": "outputs/demo",
            "random_seed": 42,
        },
        "inputs": {
            "source_data": {"path": "data/source.csv", "sha256": "x", "exists": True},
            "fewshot_pool": {"path": "examples/fewshot.sqlite", "sha256": "y", "exists": True, "type": "sqlite"},
            "config": {"path": "configs/x.json", "sha256": "z", "exists": True},
            "source_manifest": {"path": "data/source_manifest.json", "sha256": "m1", "exists": True},
            "fewshot_build_manifest": {"path": "data/fewshot_build_manifest.json", "sha256": "m2", "exists": False},
        },
        "protocol": {
            "message_stage_mandatory": True,
            "message_gate_mandatory": True,
            "few_shot_mandatory": True,
            "run_valid_for_paper": False,
            "formal_assets_ready": False,
            "blockers": ["formal_ready_fewshot_pool_missing", "fewshot_build_manifest_missing"],
        },
        "notes": [],
    }
    metrics = {
        "counts": {
            "total_samples": 3,
            "generation_attempted": 2,
            "generation_success": 2,
            "generation_failed": 0,
            "judge_failed": 0,
            "message_pass": 1,
            "message_fallback": 1,
            "true_message_reject": 0,
            "step3_ready": 2,
        },
        "rates": {
            "generation_failure_rate_attempted": 0.0,
            "true_message_reject_rate_scored": 0.0,
            "message_pass_rate_scored": 0.5,
            "message_fallback_rate_scored": 0.5,
            "step3_ready_ratio_total": 2 / 3,
        },
        "quality": {"coverage_min_mean": 0.7, "message_quality_weight_mean": 0.8},
        "fewshot": {"exact_count": 1, "partial_count": 1, "generic_count": 0, "failed_count": 0},
        "errors": {"by_error_code": {}},
        "warnings": ["message_gate_report_missing"],
    }
    run_metadata = {
        "argv": ["python3", "code/construct_simple_two_intent.py", "--deepseek-api-key", "SECRET_VALUE"],
        "run_valid_for_paper": False,
        "run_purpose": "analysis",
        "message_gate": {"message_gate_passed": False, "reason": "not_run"},
        "message_config": {"api_key_source": "env"},
    }

    report = mod.build_experiment_report(
        manifest=manifest,
        metrics=metrics,
        run_metadata=run_metadata,
        gate_report=None,
        fewshot_audit=None,
    )

    dumped = json.dumps(report, ensure_ascii=False)
    assert report["protocol_status"]["paper_valid"] is False
    assert report["protocol_status"]["formal_assets_ready"] is False
    assert report["fewshot_pool_audit"]["status"] == "not_provided"
    assert report["difficulty_and_realism_summary"]["status"] == "missing"
    assert "formal_ready_fewshot_pool_missing" in report["limitations"]
    assert "fewshot_build_manifest_missing" in report["limitations"]
    assert "message_gate_report_missing" in report["warnings"]
    assert "SECRET_VALUE" not in dumped


def test_experiment_report_includes_difficulty_realism_and_fewshot_audit(tmp_path: Path) -> None:
    mod = load_module("experiment_report.py")
    manifest = {
        "created_at_utc": "2026-05-13T00:00:00Z",
        "run": {"run_id": "run_demo", "run_purpose": "formal", "random_seed": 42},
        "git": {"commit": "abc", "branch": "main"},
        "inputs": {
            "source_data": {"path": "data/source.csv", "sha256": "x", "exists": True},
            "fewshot_pool": {"path": "data/fewshot.db", "sha256": "y", "exists": True},
            "config": {"path": "configs/runtime.json", "sha256": "z", "exists": True},
        },
        "protocol": {
            "run_valid_for_paper": True,
            "formal_assets_ready": True,
            "blockers": [],
            "message_stage_mandatory": True,
            "message_gate_mandatory": True,
            "few_shot_mandatory": True,
        },
    }
    metrics = {
        "counts": {"total_samples": 2, "generation_attempted": 2, "generation_success": 2, "generation_failed": 0, "judge_failed": 0, "message_pass": 2, "message_fallback": 0, "true_message_reject": 0, "step3_ready": 2},
        "rates": {"generation_failure_rate_attempted": 0.0, "true_message_reject_rate_scored": 0.0, "message_pass_rate_scored": 1.0, "message_fallback_rate_scored": 0.0, "step3_ready_ratio_total": 1.0},
        "quality": {"coverage_min_mean": 0.8, "message_quality_weight_mean": 0.9},
        "fewshot": {"exact_count": 2, "partial_count": 0, "generic_count": 0, "failed_count": 0},
        "errors": {"by_error_code": {}},
        "warnings": [],
        "difficulty_realism": {
            "difficulty_level_counts": {"C": 1, "D": 1},
            "intent_cardinality_counts": {"multi-2": 2},
            "structure_pattern_counts": {"separable": 1, "entangled": 1},
            "construction_route_counts": {"route_2_multi_intent": 2},
            "realism_score": {"mean": 0.65, "p50": 0.4, "p90": 0.9, "low_count": 1, "tau_low": 0.7},
            "rho": {"mean": 0.65, "p50": 0.4, "p90": 0.9},
            "identifier_overlap_score": {"mean": 0.33, "p50": 0.33, "p90": 0.33},
            "dependency_hint_score": {"mean": 0.28, "p50": 0.28, "p90": 0.28},
            "main_topic_coherence": {"mean": 0.44, "p50": 0.44, "p90": 0.44},
            "shared_file_ratio": {"mean": 0.5, "p50": 0.5, "p90": 0.5},
            "realism_weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight",
            "realism_weight_config": {"enabled": True},
            "pipeline_owner": "step2_controllable_synthetic_construction",
            "pipeline_order": [
                "sample_construction",
                "difficulty_feature_extraction",
                "difficulty_level_assignment",
                "realism_feature_scoring",
                "joint_weight_metadata",
            ],
        },
    }
    run_metadata = {
        "run_purpose": "formal",
        "message_gate": {"message_gate_passed": True, "reason": "ok"},
        "difficulty_realism": {
            "tau_realism_low": 0.7,
            "tau_realism_low_source": "config",
            "level_a_b_route_status": "schema_ready_route_not_implemented",
        },
    }
    fewshot_audit = {
        "passed": False,
        "pool_path": "data/fewshot.db",
        "audit": {
            "total_examples": 60,
            "verified_examples": 58,
            "generic_subject_count": 1,
            "probe_summary": {"retrieval_status": "partial", "retrieval_result_count": 1},
            "warnings": ["schema_column_missing:notes"],
            "blockers": ["fewshot_total_below_min"],
        },
    }

    report = mod.build_experiment_report(
        manifest=manifest,
        metrics=metrics,
        run_metadata=run_metadata,
        gate_report={"message_gate_passed": True, "reason": "ok"},
        fewshot_audit=fewshot_audit,
    )
    markdown = mod.render_markdown(report)

    assert report["difficulty_and_realism_summary"]["tau_realism_low"] == 0.7
    assert report["difficulty_and_realism_summary"]["tau_realism_low_source"] == "config"
    assert report["difficulty_and_realism_summary"]["realism_weight_formula"] == "sample_confidence * pair_quality_weight * rho * message_quality_weight"
    assert report["difficulty_and_realism_summary"]["level_a_b_route_status"] == "schema_ready_route_not_implemented"
    assert report["fewshot_pool_audit"]["status"] == "provided"
    assert report["fewshot_pool_audit"]["passed"] is False
    assert report["fewshot_pool_audit"]["blockers"] == ["fewshot_total_below_min"]
    assert "fewshot_audit_not_passed" in report["limitations"]
    assert "tau_realism_low" in markdown
    assert "Few-shot Pool Audit" in markdown
    assert "schema_ready_route_not_implemented" in markdown


def test_check_dataset_leakage_detects_sha_and_repo_alias(tmp_path: Path) -> None:
    mod = load_module("check_dataset_leakage.py")
    source_path = tmp_path / "source.csv"
    write_csv(
        source_path,
        ["repo", "sha"],
        [{"repo": "https://github.com/Owner/Repo.git", "sha": "AbC123"}],
    )
    fewshot_path = tmp_path / "fewshot.jsonl"
    write_jsonl(
        fewshot_path,
        [{"repository": "owner/repo", "commit_sha": "abc123"}],
    )
    audit_path = tmp_path / "audit.jsonl"
    write_jsonl(
        audit_path,
        [{"commit_url": "https://github.com/other/project/commit/ffff1111"}],
    )

    payload = mod.build_leakage_report(
        dataset_specs=[
            ("source", source_path),
            ("fewshot", fewshot_path),
            ("audit", audit_path),
        ],
        require_sha_disjoint=True,
        require_repo_disjoint=True,
        max_examples=5,
    )

    assert payload["passed"] is False
    source_vs_fewshot = payload["pairwise"][0]
    assert source_vs_fewshot["sha_overlap_count"] == 1
    assert source_vs_fewshot["repo_overlap_count"] == 1
    assert "owner/repo" in source_vs_fewshot["repo_overlap_examples"]


def test_export_audit_samples_deterministic_and_excerpt(tmp_path: Path) -> None:
    mod = load_module("export_audit_samples.py")
    input_path = tmp_path / "synthetic_samples.jsonl"
    rows = [
        make_sample("a1", message_status="pass", difficulty_level="Level B"),
        make_sample("a2", message_status="fallback", difficulty_level="Level D"),
        make_sample("a3", message_status="reject", difficulty_level="Level C"),
    ]
    write_jsonl(input_path, rows)

    out1 = tmp_path / "audit1.csv"
    out2 = tmp_path / "audit2.csv"
    mod.export_audit_csv(
        input_path=input_path,
        output_path=out1,
        audit_type="message",
        n=2,
        seed=42,
        stratify_fields=["message_status"],
    )
    mod.export_audit_csv(
        input_path=input_path,
        output_path=out2,
        audit_type="message",
        n=2,
        seed=42,
        stratify_fields=["message_status"],
    )

    data1 = out1.read_text(encoding="utf-8")
    data2 = out2.read_text(encoding="utf-8")
    assert data1 == data2
    assert "synthetic_diff_excerpt" in data1
    assert len(data1) < sum(len(row["synthetic_diff"]) for row in rows)


def test_export_structural_audit_contains_difficulty_realism_fields(tmp_path: Path) -> None:
    mod = load_module("export_audit_samples.py")
    input_path = tmp_path / "structural_samples.jsonl"
    row = enrich_difficulty_realism(make_sample("struct_1"), difficulty_level="D", difficulty_name="multi-intent entangled", structure_pattern="entangled", construction_route="route_2_multi_intent", realism_score=0.61, rho=0.61)
    write_jsonl(input_path, [row])

    out_path = tmp_path / "structural_audit.csv"
    mod.export_audit_csv(
        input_path=input_path,
        output_path=out_path,
        audit_type="structural",
        n=1,
        seed=7,
        stratify_fields=["difficulty_level"],
    )

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8", newline="")))
    assert rows[0]["construction_route"] == "route_2_multi_intent"
    assert rows[0]["intent_cardinality"] == "multi-2"
    assert rows[0]["structure_pattern"] == "entangled"
    assert rows[0]["difficulty_name"] == "multi-intent entangled"
    assert rows[0]["realism_score"] == "0.61"
    assert rows[0]["rho"] == "0.61"
    assert rows[0]["identifier_overlap_score"] == "0.33"
    assert rows[0]["dependency_hint_score"] == "0.28"
    assert rows[0]["main_topic_coherence"] == "0.44"
    assert rows[0]["synthetic_diff_excerpt"]
    assert len(rows[0]["synthetic_diff_excerpt"]) < len(row["synthetic_diff"])


def test_export_structural_audit_missing_difficulty_realism_fields_stays_blank(tmp_path: Path) -> None:
    mod = load_module("export_audit_samples.py")
    input_path = tmp_path / "structural_missing.jsonl"
    write_jsonl(input_path, [make_sample("plain_struct")])
    out_path = tmp_path / "structural_missing.csv"
    mod.export_audit_csv(
        input_path=input_path,
        output_path=out_path,
        audit_type="structural",
        n=1,
        seed=7,
        stratify_fields=["difficulty_level"],
    )
    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8", newline="")))
    assert rows[0]["construction_route"] == ""
    assert rows[0]["realism_score"] == ""
    assert rows[0]["main_topic_coherence"] == ""


def test_export_source_audit_from_source_csv(tmp_path: Path) -> None:
    mod = load_module("export_audit_samples.py")
    source_path = tmp_path / "source.csv"
    write_csv(
        source_path,
        ["sha", "repo", "type", "subject", "git_diff"],
        [
            {
                "sha": "abc123",
                "repo": "owner/repo",
                "type": "fix",
                "subject": "fix parser",
                "git_diff": "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n" * 5,
            }
        ],
    )
    out_path = tmp_path / "source_audit.csv"
    mod.export_source_audit_csv(source_csv_path=source_path, output_path=out_path, n=1, seed=1)
    text = out_path.read_text(encoding="utf-8")
    assert "is_single_intent" in text
    assert "abc123" in text


def test_run_experiment_suite_dry_run_and_postrun(tmp_path: Path) -> None:
    mod = load_module("run_experiment_suite.py")
    output_dir = tmp_path / "outputs" / "demo_run"
    output_dir.mkdir(parents=True)
    sample = make_sample("pass_1")
    write_jsonl(output_dir / "synthetic_samples.jsonl", [sample])
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", [sample])
    run_metadata_path = output_dir / "run_metadata.json"
    run_metadata_path.write_text(
        json.dumps(
            {
                "run_purpose": "debug",
                "run_valid_for_paper": False,
                "argv": ["python3", "code/construct_simple_two_intent.py"],
                "outputs": {"step3_ready_jsonl": str(output_dir / "synthetic_samples_step3_ready.jsonl")},
                "message_gate": {"message_gate_passed": True, "reason": "ok"},
                "difficulty_realism": {
                    "tau_realism_low": 0.5,
                    "tau_realism_low_source": "default",
                    "level_a_b_route_status": "schema_ready_route_not_implemented",
                },
            }
        ),
        encoding="utf-8",
    )
    fewshot_audit_path = output_dir / "fewshot_audit_report.json"
    fewshot_audit_path.write_text(
        json.dumps(
            {
                "passed": True,
                "pool_path": "data/fewshot.db",
                "audit": {
                    "total_examples": 100,
                    "verified_examples": 100,
                    "warnings": [],
                    "blockers": [],
                    "probe_summary": {"retrieval_status": "exact", "retrieval_result_count": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "suite.json"
    source_path = tmp_path / "source.csv"
    source_path.write_text("repo,sha\nowner/repo,abc123\n", encoding="utf-8")
    fewshot_path = tmp_path / "fewshot.csv"
    fewshot_path.write_text("repo,sha\nfewshot/repo,def456\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "suite_name": "local_postrun_analysis",
                "run_purpose": "analysis",
                "output_dir": str(output_dir),
                "config_path": "configs/step2_api_smoke_config.json",
                "source_data": str(source_path),
                "fewshot_pool": str(fewshot_path),
                "fewshot_audit_report": str(fewshot_audit_path),
                "steps": {
                    "manifest": True,
                    "metrics": True,
                    "report": True,
                    "fewshot_audit": True,
                    "leakage": False,
                    "audit_export": False,
                },
            }
        ),
        encoding="utf-8",
    )

    dry_run = mod.run_suite(config_path=config_path, dry_run=True)
    assert dry_run["dry_run"] is True
    assert not (output_dir / "experiment_manifest.json").exists()

    result = mod.run_suite(config_path=config_path, dry_run=False)
    assert result["dry_run"] is False
    assert (output_dir / "experiment_manifest.json").exists()
    assert (output_dir / "experiment_metrics.json").exists()
    assert (output_dir / "experiment_report.json").exists()
    report = json.loads((output_dir / "experiment_report.json").read_text(encoding="utf-8"))
    assert report["fewshot_pool_audit"]["status"] == "provided"
    assert report["fewshot_pool_audit"]["passed"] is True


def test_run_experiment_suite_missing_fewshot_audit_warns_when_not_strict(tmp_path: Path) -> None:
    mod = load_module("run_experiment_suite.py")
    output_dir = tmp_path / "outputs" / "missing_fewshot_audit"
    output_dir.mkdir(parents=True)
    sample = make_sample("pass_1")
    write_jsonl(output_dir / "synthetic_samples.jsonl", [sample])
    write_jsonl(output_dir / "synthetic_samples_step3_ready.jsonl", [sample])
    (output_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "run_valid_for_paper": False,
                "argv": ["python3", "code/construct_simple_two_intent.py"],
                "message_gate": {"message_gate_passed": True, "reason": "ok"},
            }
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "source.csv"
    source_path.write_text("repo,sha\nowner/repo,abc123\n", encoding="utf-8")
    fewshot_path = tmp_path / "fewshot.csv"
    fewshot_path.write_text("repo,sha\nfewshot/repo,def456\n", encoding="utf-8")
    config_path = tmp_path / "suite_missing_audit.json"
    config_path.write_text(
        json.dumps(
            {
                "suite_name": "local_postrun_analysis",
                "run_purpose": "analysis",
                "output_dir": str(output_dir),
                "config_path": "configs/step2_api_smoke_config.json",
                "source_data": str(source_path),
                "fewshot_pool": str(fewshot_path),
                "fewshot_audit_report": str(output_dir / "missing_fewshot_audit_report.json"),
                "strict_fewshot_audit": False,
                "steps": {
                    "manifest": True,
                    "metrics": True,
                    "report": True,
                    "fewshot_audit": True,
                },
            }
        ),
        encoding="utf-8",
    )

    mod.run_suite(config_path=config_path, dry_run=False)
    report = json.loads((output_dir / "experiment_report.json").read_text(encoding="utf-8"))
    assert report["fewshot_pool_audit"]["status"] == "not_provided"
    assert "fewshot_audit_report_missing" in report["warnings"]


def test_run_experiment_suite_missing_output_dir_errors(tmp_path: Path) -> None:
    mod = load_module("run_experiment_suite.py")
    config_path = tmp_path / "suite_missing.json"
    config_path.write_text(
        json.dumps(
            {
                "suite_name": "broken",
                "run_purpose": "analysis",
                "output_dir": str(tmp_path / "does_not_exist"),
                "config_path": "configs/step2_api_smoke_config.json",
                "source_data": str(tmp_path / "source.csv"),
                "fewshot_pool": str(tmp_path / "fewshot.csv"),
                "steps": {"manifest": True, "metrics": True, "report": True},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        mod.run_suite(config_path=config_path, dry_run=False)


def test_difficulty_realism_assigns_level_c_for_separable_multi_intent() -> None:
    mod = load_module("difficulty_realism.py")
    sample = make_sample(
        "c1",
        difficulty_level="",
        type_pair="fix+test",
    )
    sample["sources"][0]["file_paths"] = ["src/auth.py"]
    sample["sources"][1]["file_paths"] = ["tests/test_auth.py"]
    sample["sources"][0]["commit_message"] = "fix auth parser crash"
    sample["sources"][1]["commit_message"] = "add auth parser regression tests"
    sample["sources"][0]["subject"] = "fix auth parser crash"
    sample["sources"][1]["subject"] = "add auth parser regression tests"
    sample["edit_units"] = [
        {"file_path": "src/auth.py", "hunk_index_in_file": 1, "header": "@@ -10,2 +10,2 @@", "intent_id": 0, "source_sha": "c1_sha1"},
        {"file_path": "tests/test_auth.py", "hunk_index_in_file": 1, "header": "@@ -1,2 +1,3 @@", "intent_id": 1, "source_sha": "c1_sha2"},
    ]
    sample["synthetic_diff"] = (
        "diff --git a/src/auth.py b/src/auth.py\n@@ -10,2 +10,2 @@\n-old\n+new\n"
        "diff --git a/tests/test_auth.py b/tests/test_auth.py\n@@ -1,2 +1,3 @@\n-old\n+new\n"
    )

    annotated = mod.annotate_sample_difficulty_and_realism(sample, config={})
    assert annotated["difficulty_level"] == "C"
    assert annotated["intent_cardinality"] == "multi-2"
    assert annotated["structure_pattern"] == "separable"
    assert annotated["difficulty_features"]["shared_file_count"] == 0
    assert annotated["difficulty_features"]["identifier_overlap_score"] <= 0.35
    assert annotated["rho"] == annotated["realism_score"]
    assert annotated["difficulty_assignment_meta"]["pipeline_owner"] == "step2_controllable_synthetic_construction"
    assert annotated["difficulty_assignment_meta"]["pipeline_order"] == [
        "sample_construction",
        "difficulty_feature_extraction",
        "difficulty_level_assignment",
        "realism_feature_scoring",
        "joint_weight_metadata",
    ]
    assert annotated["realism_weight_config"] == {
        "enabled": True,
        "owner_stage": "step2_controllable_synthetic_construction",
        "rho_field": "rho",
        "realism_score_field": "realism_score",
        "weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight",
    }


def test_difficulty_realism_assigns_level_d_for_entangled_shared_file() -> None:
    mod = load_module("difficulty_realism.py")
    sample = make_sample(
        "d1",
        difficulty_level="",
        type_pair="fix+refactor",
    )
    shared_path = "src/cache/session_cache.py"
    for source in sample["sources"]:
        source["file_paths"] = [shared_path]
    sample["sources"][0]["commit_message"] = "fix session cache invalidation bug"
    sample["sources"][1]["commit_message"] = "refactor session cache helper naming"
    sample["sources"][0]["subject"] = "fix session cache invalidation bug"
    sample["sources"][1]["subject"] = "refactor session cache helper naming"
    sample["edit_units"] = [
        {"file_path": shared_path, "hunk_index_in_file": 1, "header": "@@ -10,2 +10,2 @@", "intent_id": 0, "source_sha": "d1_sha1"},
        {"file_path": shared_path, "hunk_index_in_file": 2, "header": "@@ -30,2 +30,3 @@", "intent_id": 1, "source_sha": "d1_sha2"},
    ]
    sample["synthetic_diff"] = (
        f"diff --git a/{shared_path} b/{shared_path}\n@@ -10,2 +10,2 @@\n-old cache\n+new cache\n"
        f"diff --git a/{shared_path} b/{shared_path}\n@@ -30,2 +30,3 @@\n-old helper\n+new helper\n"
    )

    annotated = mod.annotate_sample_difficulty_and_realism(sample, config={})
    assert annotated["difficulty_level"] == "D"
    assert annotated["structure_pattern"] == "entangled"
    assert annotated["difficulty_features"]["shared_file_count"] >= 1
    assert annotated["difficulty_features"]["same_file_hunk_count"] >= 2
    assert annotated["realism_score"] is not None
    assert annotated["rho"] == annotated["realism_score"]
