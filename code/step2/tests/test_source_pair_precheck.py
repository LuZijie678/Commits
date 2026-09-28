from __future__ import annotations

import builtins
import csv
import importlib.util
import json
import os
import subprocess
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "construct_simple_two_intent.py"
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def make_source(
    *,
    repo: str = "owner/repo",
    sha: str = "sha1",
    ctype: str = "fix",
    subject: str = "fix auth parser bug",
    message: str = "fix auth parser bug in login flow",
    files: list[str] | None = None,
) -> dict:
    file_list = files or ["src/auth.py"]
    return {
        "repo": repo,
        "sha": sha,
        "type": ctype,
        "subject": subject,
        "commit_message": message,
        "message": message,
        "file_path_set": set(file_list),
        "module_set": {item.split("/")[0] for item in file_list},
        "path_events": {
            "touched_paths": list(file_list),
            "deleted_paths": [],
            "added_paths": [],
            "rename_pairs": [],
            "copy_pairs": [],
        },
    }


def write_minimal_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["repo", "sha", "type", "subject", "message", "git_diff", "manual_label"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_conservative_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "repo",
        "sha",
        "commit_url",
        "type",
        "subject",
        "message",
        "git_diff",
        "model_prob",
        "model_tier",
        "tau_a",
        "tau_b",
        "rule_label",
        "rule_weight",
        "passed_rule_refilter",
        "conservative_tier",
        "selection_strategy",
        "selection_reason",
        "source_confidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_repo_sha_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["repo", "sha"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_diff(file_path: str) -> str:
    return "\n".join(
        [
            f"diff --git a/{file_path} b/{file_path}",
            f"--- a/{file_path}",
            f"+++ b/{file_path}",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ]
    )


def write_fewshot_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE fewshot_examples (
                example_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                sha TEXT NOT NULL,
                type_pair TEXT NOT NULL,
                type_signature_raw TEXT NOT NULL,
                type_signature_canonical TEXT NOT NULL,
                intent_k INTEGER NOT NULL,
                subject TEXT NOT NULL,
                split TEXT NOT NULL,
                verified_multi_intent INTEGER NOT NULL,
                quality_score REAL,
                fewshot_eligible INTEGER,
                quality_status TEXT,
                message_status TEXT,
                notes TEXT
            )
            """
        )
        payload_rows = []
        for row in rows:
            payload = dict(row)
            payload.setdefault("fewshot_eligible", None)
            payload.setdefault("quality_status", "")
            payload.setdefault("message_status", "")
            payload.setdefault("notes", "")
            payload_rows.append(payload)
        conn.executemany(
            """
            INSERT INTO fewshot_examples (
                example_id, repo, sha, type_pair, type_signature_raw,
                type_signature_canonical, intent_k, subject, split,
                verified_multi_intent, quality_score, fewshot_eligible,
                quality_status, message_status, notes
            )
            VALUES (
                :example_id, :repo, :sha, :type_pair, :type_signature_raw,
                :type_signature_canonical, :intent_k, :subject, :split,
                :verified_multi_intent, :quality_score, :fewshot_eligible,
                :quality_status, :message_status, :notes
            )
            """,
            payload_rows,
        )
        conn.commit()
    finally:
        conn.close()


def write_source_manifest(path: Path, csv_path: Path, *, total_selected: int = 2) -> None:
    payload = {
        "total_selected": total_selected,
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
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_write_partial_progress_artifacts_emits_progress_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    args = SimpleNamespace(skip_message_stage=False, progress_flush_every=2)
    samples = [
        {
            "sample_id": "simple2_0001",
            "repo": "owner/repo",
            "precheck_status": "pass",
            "generation_status": "generated",
            "message_status": "pass",
            "message_meta": {
                "llm_generation_attempted": True,
                "generation_success": True,
                "message_error_type": "",
            },
        },
        {
            "sample_id": "simple2_0002",
            "repo": "owner/repo",
            "precheck_status": "skip",
            "generation_status": "not_attempted_precheck_skip",
            "message_status": "not_generated_precheck_skip",
            "message_meta": {
                "llm_generation_attempted": False,
                "generation_success": False,
                "message_error_type": "source_pair_precheck_skip",
            },
        },
    ]

    payload = MOD.write_partial_progress_artifacts(
        output_dir,
        args,
        samples,
        processed_count=2,
        total_count=2,
        status="completed",
        last_sample=samples[-1],
        final_summary={
            "step3_ready_count": 1,
            "generated_count": 2,
        },
    )

    partial_samples_path = output_dir / "synthetic_samples.partial.jsonl"
    partial_precheck_path = output_dir / "synthetic_samples_precheck_rejected.partial.jsonl"
    progress_path = output_dir / "run_progress.json"

    assert partial_samples_path.exists()
    assert partial_precheck_path.exists()
    assert progress_path.exists()
    assert "simple2_0001" in partial_samples_path.read_text(encoding="utf-8")
    assert "simple2_0002" in partial_precheck_path.read_text(encoding="utf-8")
    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert progress_payload["processed_count"] == 2
    assert progress_payload["counts"]["precheck_skip_count"] == 1
    assert progress_payload["final_summary"]["step3_ready_count"] == 1


def write_fewshot_build_manifest(path: Path, db_path: Path, *, total_rows_train: int = 3) -> None:
    payload = {
        "asset_name": "fewshot_pool_formal_test",
        "asset_version": "v1-test",
        "build_date_utc": "2026-05-13T00:00:00Z",
        "builder": "test-suite",
        "source_datasets": ["test_fixture"],
        "schema_table": "fewshot_examples",
        "db_filename": db_path.name,
        "total_rows_train": total_rows_train,
        "eligible_rows_train": total_rows_train,
        "verified_rows_train": total_rows_train,
        "common_signature_coverage": {
            "fix+test": max(1, total_rows_train),
        },
        "style_cleaning_policy": {
            "strict_style": False,
            "max_subject_chars": 120,
            "max_subject_tokens": 20,
            "blocked_patterns": [],
        },
        "thresholds": {
            "min_total": 1,
            "min_per_common_signature": 0,
            "probe_type_signature": "fix+test",
            "probe_k": 1,
        },
        "validation": {
            "audit_pass": True,
            "retrieval_probe_ok": True,
            "preflight_passed": True,
        },
        "build_inputs": {
            "audit_script": "code/audit_fewshot_pool.py",
            "protocol_doc": "docs/plan-1-step2-experiment-protocol.md",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_fewshot_rows() -> list[dict]:
    return [
        {
            "example_id": "ex_fix_test",
            "repo": "fewshot/repo1",
            "sha": "fs1",
            "type_pair": "fix+test",
            "type_signature_raw": "fix+test",
            "type_signature_canonical": "fix+test",
            "intent_k": 2,
            "subject": "fix parser bug and add tests",
            "split": "train",
            "verified_multi_intent": 1,
            "quality_score": 0.95,
            "fewshot_eligible": 1,
            "quality_status": "verified",
        },
        {
            "example_id": "ex_refactor_test",
            "repo": "fewshot/repo2",
            "sha": "fs2",
            "type_pair": "refactor+test",
            "type_signature_raw": "refactor+test",
            "type_signature_canonical": "refactor+test",
            "intent_k": 2,
            "subject": "refactor auth helpers and add tests",
            "split": "train",
            "verified_multi_intent": 1,
            "quality_score": 0.9,
            "fewshot_eligible": 1,
            "quality_status": "verified",
        },
        {
            "example_id": "ex_generic",
            "repo": "fewshot/repo3",
            "sha": "fs3",
            "type_pair": "docs+feat",
            "type_signature_raw": "docs+feat",
            "type_signature_canonical": "docs+feat",
            "intent_k": 2,
            "subject": "add API support and update docs",
            "split": "train",
            "verified_multi_intent": 1,
            "quality_score": 0.8,
            "fewshot_eligible": 1,
            "quality_status": "verified",
        },
    ]


def make_runtime_config(tmp_path: Path, source_csv: Path, fewshot_db: Path, **overrides) -> Path:
    config_path = tmp_path / "runtime_config.json"
    source_manifest_path = tmp_path / "source_manifest.json"
    fewshot_build_manifest_path = tmp_path / "fewshot_build_manifest.json"
    write_source_manifest(source_manifest_path, source_csv)
    write_fewshot_build_manifest(fewshot_build_manifest_path, fewshot_db)
    payload = {
        "source_csv": str(source_csv),
        "source_manifest_path": str(source_manifest_path),
        "output_dir": str(tmp_path / "out"),
        "manual_label": "A",
        "seed": 42,
        "run_purpose": "formal",
        "intent_k": 2,
        "k_sweep_max": 2,
        "fewshot_db": str(fewshot_db),
        "fewshot_build_manifest_path": str(fewshot_build_manifest_path),
        "deepseek_api_key": "test",
        "message_stage_enabled": True,
        "message_gate_enabled": True,
        "fewshot_enabled": True,
        "require_fewshot_pool": True,
    }
    payload.update(overrides)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def make_args(tmp_path: Path, source_csv: Path, output_dir: Path, **overrides) -> SimpleNamespace:
    config_path = tmp_path / "runtime_config.json"
    config_path.write_text("{}", encoding="utf-8")
    fewshot_db = tmp_path / "fewshot.db"
    if not fewshot_db.exists():
        write_fewshot_db(fewshot_db, make_fewshot_rows())
    source_manifest_path = tmp_path / "source_manifest.json"
    fewshot_build_manifest_path = tmp_path / "fewshot_build_manifest.json"
    write_source_manifest(source_manifest_path, source_csv)
    write_fewshot_build_manifest(fewshot_build_manifest_path, fewshot_db)
    payload = {
        "source_csv": str(source_csv),
        "source_manifest_path": str(source_manifest_path),
        "config": str(config_path),
        "output_dir": str(output_dir),
        "manual_label": "A",
        "preset": "balanced_step3_ready",
        "seed": 42,
        "intent_k": 2,
        "k_sweep_max": 2,
        "group_combo_attempt_cap_per_repo": 200,
        "group_candidate_cap_per_repo": 200,
        "target_count": 1,
        "repo_cap": 5,
        "type_pair_cap": 5,
        "max_merged_files": 20,
        "max_merged_lines": 2000,
        "review_samples": 1,
        "min_target_ratio": 0.0,
        "require_different_type": True,
        "module_overlap_policy": "prefer",
        "prefer_module_overlap": True,
        "require_module_overlap": False,
        "block_order": "round_robin",
        "skip_message_stage": False,
        "message_stage_enabled": True,
        "debug_allow_skip_message_stage": False,
        "generator_provider": "deepseek_api",
        "generator_mode": "api",
        "generator_model": "deepseek-v4-pro",
        "deepseek_base_url": "https://api.deepseek.com/v1/chat/completions",
        "deepseek_api_key": "test",
        "deepseek_api_key_env": "DEEPSEEK_API_KEY",
        "_resolved_deepseek_api_key": "test",
        "_deepseek_api_key_source": "config_or_cli_plaintext",
        "api_timeout_sec": 10,
        "temperature": 0.2,
        "top_p": 1.0,
        "max_output_tokens": 32,
        "max_generation_attempts": 2,
        "max_abstractive_compress_attempts": 1,
        "max_rewrite_attempts": 1,
        "prompt_version": "test_prompt",
        "few_shot_k": 1,
        "few_shot_min_examples_per_sample": 1,
        "few_shot_warn_if_below_requested": True,
        "few_shot_generic_rate_warn_threshold": 0.5,
        "few_shot_failed_rate_gate_threshold": 0.1,
        "fewshot_db": str(fewshot_db),
        "fewshot_build_manifest_path": str(fewshot_build_manifest_path),
        "fewshot_source_csv": "",
        "fewshot_table": "fewshot_examples",
        "fewshot_enabled": True,
        "require_fewshot_pool": True,
        "fewshot_min_total_examples": 1,
        "fewshot_min_examples_per_common_signature": 0,
        "fewshot_audit_strict_style": False,
        "retrieval_query_version": "sqlite_fixed_cmd_v1",
        "scorer_backend": "bertscore_only_v1",
        "bertscore_model": "roberta-large",
        "bertscore_lang": "en",
        "bertscore_idf": False,
        "threshold_method": "kmeans_1d",
        "message_gate_reference": "",
        "reference_lower_quantile": 0.05,
        "reference_upper_quantile": 0.95,
        "enable_message_gate": True,
        "message_gate_enabled": True,
        "debug_allow_disable_message_gate": False,
        "message_gate_report_path": str(output_dir / "message_gate_report.json"),
        "gate_min_message_pass_rate": 0.0,
        "gate_max_message_reject_rate": 1.0,
        "gate_min_avg_message_quality_weight_non_reject": 0.0,
        "gate_max_fewshot_failure_rate": 1.0,
        "gate_max_precheck_skip_rate": 1.0,
        "gate_max_generation_failure_rate": 1.0,
        "gate_min_coverage_min_avg": 0.0,
        "gate_min_coverage_min_p10": 0.0,
        "enable_source_pair_precheck": True,
        "precheck_duplicate_jaccard_threshold": 0.92,
        "precheck_duplicate_seq_threshold": 0.95,
        "precheck_moderate_similarity_threshold": 0.75,
        "precheck_relation_low_threshold": 0.10,
        "precheck_heavy_overlap_threshold": 0.70,
        "generation_cache_enabled": False,
        "bertscore_cache_enabled": False,
        "generation_cache_path": str(output_dir / "cache" / "generation_cache.json"),
        "bertscore_cache_path": str(output_dir / "cache" / "bertscore_cache.json"),
        "preflight": False,
        "preflight_api_ping": False,
        "run_purpose": "formal",
        "run_purpose_source": "test_fixture",
        "formal_protocol_flags": {
            "message_stage_mandatory": True,
            "message_gate_mandatory": True,
            "few_shot_mandatory": True,
            "debug_override_used": False,
        },
        "protocol_violations": [],
        "debug_override_used": False,
        "formal_run": True,
        "run_valid_for_paper": True,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def install_fake_bertscore_module(monkeypatch) -> None:
    fake_module = types.SimpleNamespace(BERTScorer=object)
    monkeypatch.setitem(sys.modules, "bert_score", fake_module)


def test_compute_length_limit_stats_uses_subject_length_anchor():
    subject_a = "fix parser bug"
    subject_b = "add parser regression tests"
    pool = [
        make_source(sha="sha1", subject=subject_a, message="x" * 320),
        make_source(sha="sha2", subject=subject_b, message="y" * 12),
    ]

    stats = MOD.compute_length_limit_stats(pool)
    assert stats["p90"] == len(subject_b)
    assert stats["p95"] == len(subject_b)
    assert stats["policy"] == "p90(real_single_intent_commit_subject_length)"
    assert stats["source"] == "subject_column_of_a_tier_commits"


def test_run_single_reports_subject_length_limit_anchor(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "subject_anchor_source.csv"
    output_dir = tmp_path / "subject_anchor_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "x" * 320,
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser regression tests",
            "message": "y" * 12,
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix parser bug and add regression tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.9, 0.9],
                "coverage_by_source": [0.9, 0.9],
                "coverage_min_r": 0.9,
                "coverage_min": 0.9,
                "coverage_avg_r": 0.9,
                "coverage_avg": 0.9,
                "coverage_balance": 1.0,
                "faithfulness_p": 0.9,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 7,
                "imperative_head": 1,
                "message_quality_weight": 1.0,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    MOD.run_single(args, enforce_gates=False)

    expected_limit = len("add parser regression tests")
    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))

    assert sample["message_meta"]["length_limit"] == expected_limit
    assert sample["message_meta"]["length_limit_source"] == "subject_column_of_a_tier_commits"
    assert sample["message_meta"]["diff_evidence_available_by_source"] == [True, True]
    assert sample["message_meta"]["diff_evidence_source_by_source"] == ["git_diff", "git_diff"]
    assert sample["message_meta"]["diff_evidence_card_version"]
    assert metadata["message_config"]["length_limit"] == expected_limit
    assert metadata["message_config"]["length_limit_source"] == "subject_column_of_a_tier_commits"
    assert metadata["message_config"]["length_limit_policy"] == "p90(real_single_intent_commit_subject_length)"
    assert metadata["diff_evidence"]["diff_evidence_card_version"] == MOD.DIFF_EVIDENCE_CARD_VERSION
    assert metadata["diff_evidence"]["diff_evidence_required_for_formal"] is True
    assert metadata["run_stats"]["difficulty_realism_summary"]["pipeline_owner"] == "step2_controllable_synthetic_construction"
    assert metadata["run_stats"]["difficulty_realism_summary"]["pipeline_order"] == [
        "sample_construction",
        "difficulty_feature_extraction",
        "difficulty_level_assignment",
        "realism_feature_scoring",
        "joint_weight_metadata",
    ]
    assert metadata["fewshot_pool"]["fewshot_pool_path"] == args.fewshot_db
    assert Path(metadata["fewshot_pool"]["fewshot_pool_resolved_path"]).resolve() == Path(args.fewshot_db).resolve()
    assert metadata["formal_assets"]["formal_assets_ready"] is True
    assert metadata["formal_assets"]["source_manifest"]["exists"] is True
    assert metadata["formal_assets"]["fewshot_build_manifest"]["exists"] is True
    assert metadata["run_stats"]["message_metrics"]["real_subject_distribution_anchor"]["p90_token_count"] == 4
    assert sample["difficulty_level"] in {"C", "D"}
    assert sample["intent_cardinality"].startswith("multi-")
    assert "difficulty_realism_summary" in metadata["run_stats"]


def test_run_single_uses_configured_tau_realism_low_in_metadata_and_summary(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "tau_config_source.csv"
    output_dir = tmp_path / "tau_config_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "fix parser bug",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser regression tests",
            "message": "add parser regression tests",
            "git_diff": make_diff("tests/test_a.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)
    args.loaded_config = {"difficulty_realism": {"tau_realism_low": 0.7}}
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix parser bug and add parser regression tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.9, 0.9],
                "coverage_by_source": [0.9, 0.9],
                "coverage_min_r": 0.9,
                "coverage_min": 0.9,
                "coverage_avg_r": 0.9,
                "coverage_avg": 0.9,
                "coverage_balance": 1.0,
                "faithfulness_p": 0.9,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 7,
                "imperative_head": 1,
                "message_quality_weight": 1.0,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    MOD.run_single(args, enforce_gates=False)

    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    summary_text = (output_dir / "summary.md").read_text(encoding="utf-8")
    assert metadata["difficulty_realism"]["tau_realism_low"] == 0.7
    assert metadata["difficulty_realism"]["tau_realism_low_source"] == "config"
    assert metadata["run_stats"]["difficulty_realism_summary"]["realism_score_summary"]["tau_realism_low"] == 0.7
    assert "tau_realism_low" in summary_text
    assert "threshold_source" in summary_text
    assert "0.7" in summary_text


def test_run_single_defaults_tau_realism_low_when_config_missing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "tau_default_source.csv"
    output_dir = tmp_path / "tau_default_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "fix parser bug",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser regression tests",
            "message": "add parser regression tests",
            "git_diff": make_diff("tests/test_a.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)
    args.loaded_config = {}
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix parser bug and add parser regression tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.9, 0.9],
                "coverage_by_source": [0.9, 0.9],
                "coverage_min_r": 0.9,
                "coverage_min": 0.9,
                "coverage_avg_r": 0.9,
                "coverage_avg": 0.9,
                "coverage_balance": 1.0,
                "faithfulness_p": 0.9,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 7,
                "imperative_head": 1,
                "message_quality_weight": 1.0,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    MOD.run_single(args, enforce_gates=False)

    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["difficulty_realism"]["tau_realism_low"] == 0.5
    assert metadata["difficulty_realism"]["tau_realism_low_source"] == "default"
    assert metadata["run_stats"]["difficulty_realism_summary"]["realism_score_summary"]["tau_realism_low"] == 0.5


def test_run_single_entangled_candidates_can_emit_level_d(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "entangled_source.csv"
    output_dir = tmp_path / "entangled_out"
    shared_path = "src/session_cache.py"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix session cache invalidation bug",
            "message": "fix session cache invalidation bug",
            "git_diff": "\n".join(
                [
                    f"diff --git a/{shared_path} b/{shared_path}",
                    f"--- a/{shared_path}",
                    f"+++ b/{shared_path}",
                    "@@ -10 +10 @@",
                    "-old_cache",
                    "+new_cache",
                ]
            ),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "refactor",
            "subject": "refactor session cache helper naming",
            "message": "refactor session cache helper naming",
            "git_diff": "\n".join(
                [
                    f"diff --git a/{shared_path} b/{shared_path}",
                    f"--- a/{shared_path}",
                    f"+++ b/{shared_path}",
                    "@@ -30 +30 @@",
                    "-old_helper",
                    "+new_helper",
                ]
            ),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        allow_entangled_candidates=True,
        max_shared_files_per_group=1,
        require_different_type=True,
        target_count=1,
        repo_cap=1,
        type_pair_cap=1,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix session cache invalidation and refactor helper naming",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.9, 0.9],
                "coverage_by_source": [0.9, 0.9],
                "coverage_min_r": 0.9,
                "coverage_min": 0.9,
                "coverage_avg_r": 0.9,
                "coverage_avg": 0.9,
                "coverage_balance": 1.0,
                "faithfulness_p": 0.9,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 8,
                "imperative_head": 1,
                "message_quality_weight": 1.0,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    MOD.run_single(args, enforce_gates=False)

    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert sample["difficulty_level"] == "D"
    assert sample["structure_pattern"] == "entangled"
    assert sample["difficulty_features"]["shared_file_count"] >= 1
    assert metadata["resolved_config"]["allow_entangled_candidates"] is True


def test_precheck_different_repo_skip():
    left = make_source(repo="a/repo", sha="a1")
    right = make_source(repo="b/repo", sha="b1")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "different_repo_after_normalization"


def test_select_pairs_prioritizes_pair_quality_within_repo_bucket():
    repo_pairs = {
        "owner/repo": [
            {
                "repo": "owner/repo",
                "type_pair": "feat+fix",
                "different_type": True,
                "priority": (0, 1, 0, 2, 20, 10),
                "pair_quality_weight": 0.42,
                "precheck_status": "warn",
            },
            {
                "repo": "owner/repo",
                "type_pair": "feat+fix",
                "different_type": True,
                "priority": (0, 1, 0, 2, 20, 20),
                "pair_quality_weight": 1.0,
                "precheck_status": "pass",
            },
        ]
    }

    legacy_selected = MOD.select_pairs(
        {"owner/repo": [dict(item) for item in repo_pairs["owner/repo"]]},
        target_count=1,
        repo_cap=1,
        type_pair_cap=1,
        require_different_type=True,
        seed=42,
        selection_quality_priority="legacy",
    )
    quality_selected = MOD.select_pairs(
        {"owner/repo": [dict(item) for item in repo_pairs["owner/repo"]]},
        target_count=1,
        repo_cap=1,
        type_pair_cap=1,
        require_different_type=True,
        seed=42,
        selection_quality_priority="pair_quality",
    )

    assert legacy_selected[0]["pair_quality_weight"] == 0.42
    assert quality_selected[0]["pair_quality_weight"] == 1.0


def test_select_pairs_keeps_simpler_pair_ahead_of_higher_quality_pair():
    quality_selected = MOD.select_pairs(
        {
            "owner/repo": [
                {
                    "repo": "owner/repo",
                    "type_pair": "feat+fix",
                    "different_type": True,
                    "priority": (0, 1, 0, 2, 20, 10),
                    "pair_quality_weight": 0.42,
                    "precheck_status": "pass",
                },
                {
                    "repo": "owner/repo",
                    "type_pair": "feat+fix",
                    "different_type": True,
                    "priority": (0, 1, 0, 3, 40, 20),
                    "pair_quality_weight": 1.0,
                    "precheck_status": "pass",
                },
            ]
        },
        target_count=1,
        repo_cap=1,
        type_pair_cap=1,
        require_different_type=True,
        seed=42,
        selection_quality_priority="pair_quality",
    )

    assert quality_selected[0]["priority"] == (0, 1, 0, 2, 20, 10)


def test_select_pairs_legacy_guarded_defers_skip_and_filters_very_low_quality():
    guarded_selected = MOD.select_pairs(
        {
            "owner/repo": [
                {
                    "repo": "owner/repo",
                    "type_pair": "feat+fix",
                    "different_type": True,
                    "priority": (0, 1, 0, 2, 20, 10),
                    "pair_quality_weight": 0.0,
                    "precheck_status": "skip",
                },
                {
                    "repo": "owner/repo",
                    "type_pair": "feat+fix",
                    "different_type": True,
                    "priority": (0, 1, 0, 2, 20, 20),
                    "pair_quality_weight": 0.42,
                    "precheck_status": "warn",
                },
                {
                    "repo": "owner/repo",
                    "type_pair": "feat+fix",
                    "different_type": True,
                    "priority": (0, 1, 0, 2, 20, 30),
                    "pair_quality_weight": 0.56,
                    "precheck_status": "warn",
                },
            ]
        },
        target_count=1,
        repo_cap=1,
        type_pair_cap=1,
        require_different_type=True,
        seed=42,
        selection_quality_priority="legacy_guarded",
        selection_min_pair_quality_weight=0.42,
    )

    assert guarded_selected[0]["precheck_status"] == "warn"
    assert guarded_selected[0]["pair_quality_weight"] == 0.56


def test_precheck_same_sha_skip():
    left = make_source(sha="same-sha")
    right = make_source(sha="same-sha", ctype="feat")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "same_or_missing_sha"


def test_precheck_both_generic_skip():
    left = make_source(subject="update", message="wip update")
    right = make_source(sha="b2", ctype="feat", subject="cleanup", message="misc changes")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "both_messages_generic_low_information"
    assert result["pair_quality_weight"] == 0.0


def test_precheck_one_generic_warn():
    left = make_source(subject="update", message="minor update")
    right = make_source(sha="b2", ctype="feat", subject="add auth test", message="add auth test cases")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "warn"
    assert "one_message_generic_low_information" in result["precheck_warning_reasons"]
    assert 0.0 < result["pair_quality_weight"] < 1.0


def test_precheck_forbidden_type_pair_skip():
    left = make_source(ctype="revert", sha="a1")
    right = make_source(ctype="fix", sha="b1")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "forbidden_type_pair"


def test_precheck_high_compatible_type_pair_pass():
    left = make_source(
        ctype="fix",
        sha="a1",
        subject="fix auth parser crash",
        message="fix auth parser crash in middleware",
        files=["src/auth.py"],
    )
    right = make_source(
        ctype="test",
        sha="b1",
        subject="add auth parser regression tests",
        message="add regression tests for auth parser middleware",
        files=["tests/test_auth.py"],
    )
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "pass"
    assert result["precheck_warning_reasons"] == []
    assert result["precheck_scores"]["type_compatibility"] == 1.0
    assert result["pair_quality_weight"] == 1.0


def test_precheck_semantic_contradiction_add_remove_skip():
    left = make_source(subject="add cache for auth", message="add cache for auth token refresh")
    right = make_source(sha="b2", ctype="feat", subject="remove cache for auth", message="remove cache for auth token refresh")
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "semantic_contradiction_high_confidence"
    assert result["precheck_scores"]["semantic"] == 0.0


def test_precheck_near_duplicate_same_type_skip():
    left = make_source(subject="fix auth parser crash", message="fix auth parser crash in login flow")
    right = make_source(
        sha="b2",
        ctype="fix",
        subject="fix auth parser crash",
        message="fix auth parser crash in login flow",
    )
    result = MOD.run_source_pair_precheck(left, right, config={})
    assert result["precheck_status"] == "skip"
    assert result["precheck_skip_reason"] == "near_duplicate_pair_not_multi_intent"
    assert result["precheck_scores"]["non_duplicate"] == 0.0


def test_parse_args_rejects_skip_message_stage_in_formal_mode(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_cli.csv"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    fewshot_db = tmp_path / "fewshot_cli.db"
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--config", str(config_path), "--skip-message-stage"],
    )
    with pytest.raises(SystemExit) as exc_info:
        MOD.parse_args()
    assert "Message stage is mandatory in formal Step2 runs." in str(exc_info.value)


def test_parse_args_rejects_disable_message_gate_in_formal_mode(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_cli_gate.csv"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    fewshot_db = tmp_path / "fewshot_cli_gate.db"
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--config", str(config_path), "--disable-message-gate"],
    )
    with pytest.raises(SystemExit) as exc_info:
        MOD.parse_args()
    assert "Message gate is mandatory in formal Step2 runs." in str(exc_info.value)


def test_skip_samples_do_not_call_llm(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source.csv"
    output_dir = tmp_path / "out_skip"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "release",
            "subject": "release v1.2.3",
            "message": "release v1.2.3 package metadata",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "fix",
            "subject": "fix login bug",
            "message": "fix login bug in session validator",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)

    called = {"count": 0}

    def fake_generate_subject_with_repair(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("LLM generation should not be called for precheck-skipped sample")

    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(MOD, "generate_subject_with_repair", fake_generate_subject_with_repair)

    result = MOD.run_single(args, enforce_gates=False)
    assert result["generated_count"] == 1
    assert called["count"] == 0

    sample_path = output_dir / "synthetic_samples.jsonl"
    sample = json.loads(sample_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert sample["precheck_status"] == "skip"
    assert sample["generation_status"] == "not_attempted_precheck_skip"
    assert sample["message_status"] == "not_generated_precheck_skip"
    assert sample["message_meta"]["generation_skipped"] is True
    assert sample["message_meta"]["generation_failure_reason"] == "source_pair_precheck_skip"

    summary_text = (output_dir / "summary.md").read_text(encoding="utf-8")
    assert "precheck pass / warn / skip" in summary_text
    assert "llm_calls_saved_by_precheck" in summary_text


def test_k3_all_pairs_precheck_skip_blocks_llm(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_k3_skip.csv"
    output_dir = tmp_path / "out_k3_skip"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth parser bug",
            "message": "fix auth parser bug in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "feat",
            "subject": "add auth fallback flow",
            "message": "add auth fallback flow for SSO users",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha3",
            "type": "release",
            "subject": "release v1.2.3",
            "message": "release v1.2.3 package metadata",
            "git_diff": make_diff("src/c.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir, intent_k=3, k_sweep_max=3)

    called = {"count": 0}

    def fake_generate_subject_with_repair(*_args, **_kwargs):
        called["count"] += 1
        raise AssertionError("LLM generation should not be called for all-pairs precheck skip")

    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(MOD, "generate_subject_with_repair", fake_generate_subject_with_repair)

    result = MOD.run_single(args, enforce_gates=False)
    assert result["generated_count"] == 1
    assert called["count"] == 0

    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["precheck_status"] == "skip"
    assert sample["generation_status"] == "not_attempted_precheck_skip"
    assert sample["message_status"] == "not_generated_precheck_skip"
    assert sample["message_meta"]["generation_failure_reason"] == "source_pair_precheck_skip"
    assert len(sample["pair_precheck_results"]) == 3


def test_warn_sample_continues_generation_and_reduces_final_weight(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_warn.csv"
    output_dir = tmp_path / "out_warn"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth token parse",
            "message": "fix auth token parse in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "feat",
            "subject": "update",
            "message": "minor update",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)

    called = {"count": 0}
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "retrieve_fewshot_examples",
        lambda **_kwargs: {
            "examples": [{"example_id": "e1", "type_pair": "fix+feat", "subject": "fix parser and add tests"}],
            "few_shot_source": "type_overlap",
            "retrieval_backend": "sqlite_formal_kway_v2",
            "retrieval_result_count": 1,
            "retrieval_error": "",
            "retrieval_status": "partial",
            "few_shot_retrieval_log": {
                "requested_type_signature": "feat+fix",
                "query_levels_attempted": ["exact_kway", "type_overlap"],
                "examples_found_per_level": {"exact_kway": 0, "type_overlap": 1},
                "selected_example_ids": ["e1"],
                "selected_example_type_signatures": ["fix+test"],
                "selected_example_repos": ["fewshot/repo1"],
                "retrieval_status": "partial",
                "failure_reason": "",
            },
        },
    )
    def fake_generate_subject_with_repair(**_kwargs):
        called["count"] += 1
        return {
            "synthetic_subject": "fix auth token parser and add session hint",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["sha_req_1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        }

    monkeypatch.setattr(MOD, "generate_subject_with_repair", fake_generate_subject_with_repair)
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.9, 0.88],
                "coverage_by_source": [0.9, 0.88],
                "coverage_min_r": 0.88,
                "coverage_min": 0.88,
                "coverage_avg_r": 0.89,
                "coverage_avg": 0.89,
                "coverage_balance": 0.98,
                "faithfulness_p": 0.95,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 8,
                "imperative_head": 1,
                "message_quality_weight": 1.0,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    result = MOD.run_single(args, enforce_gates=False)
    assert result["generated_count"] == 1
    assert result["message_metrics"]["precheck_warn_count"] == 1
    assert called["count"] == 1

    sample_path = output_dir / "synthetic_samples.jsonl"
    sample = json.loads(sample_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert sample["precheck_status"] == "warn"
    assert sample["message_meta"]["generation_success"] is True
    assert sample["generation_status"] == "generated"
    assert sample["rho"] == sample["realism_score"]
    assert sample["realism_weight_config"]["enabled"] is True
    assert sample["difficulty_assignment_meta"]["pipeline_owner"] == "step2_controllable_synthetic_construction"
    assert sample["difficulty_assignment_meta"]["pipeline_order"] == [
        "sample_construction",
        "difficulty_feature_extraction",
        "difficulty_level_assignment",
        "realism_feature_scoring",
        "joint_weight_metadata",
    ]
    assert 0.0 < sample["final_sample_weight"] < sample["message_scores"]["message_quality_weight"]
    expected_weight = (
        sample["sample_confidence"]
        * sample["pair_quality_weight"]
        * sample["rho"]
        * sample["message_scores"]["message_quality_weight"]
    )
    assert abs(sample["final_sample_weight"] - expected_weight) < 1e-6
    assert len(sample["pair_precheck_results"]) == 1


def test_k3_warn_pair_all_pairs_still_calls_llm(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_k3_warn.csv"
    output_dir = tmp_path / "out_k3_warn"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth parser bug",
            "message": "fix auth parser bug in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "feat",
            "subject": "update",
            "message": "minor update",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha3",
            "type": "test",
            "subject": "add auth tests",
            "message": "add tests for auth parser",
            "git_diff": make_diff("src/c.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir, intent_k=3, k_sweep_max=3)

    called = {"count": 0}
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "retrieve_fewshot_examples",
        lambda **_kwargs: {
            "examples": [{"example_id": "e1", "type_signature_canonical": "fix+test", "subject": "fix parser and add tests"}],
            "few_shot_source": "pairwise_overlap",
            "retrieval_backend": "sqlite_formal_kway_v2",
            "retrieval_result_count": 1,
            "retrieval_error": "",
            "retrieval_status": "partial",
            "few_shot_retrieval_log": {
                "requested_type_signature": "feat+fix+test",
                "query_levels_attempted": ["exact_kway", "pairwise_overlap"],
                "examples_found_per_level": {"exact_kway": 0, "pairwise_overlap": 1},
                "selected_example_ids": ["e1"],
                "selected_example_type_signatures": ["fix+test"],
                "selected_example_repos": ["fewshot/repo1"],
                "retrieval_status": "partial",
                "failure_reason": "",
            },
        },
    )

    def fake_generate_subject_with_repair(**_kwargs):
        called["count"] += 1
        return {
            "synthetic_subject": "fix auth parser, add auth fallback, and add tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["sha_req_k3"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        }

    monkeypatch.setattr(MOD, "generate_subject_with_repair", fake_generate_subject_with_repair)
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.92, 0.84, 0.87],
                "coverage_by_source": [0.92, 0.84, 0.87],
                "coverage_min_r": 0.84,
                "coverage_min": 0.84,
                "coverage_avg_r": 0.876667,
                "coverage_avg": 0.876667,
                "coverage_balance": 0.92,
                "faithfulness_p": 0.94,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 9,
                "imperative_head": 1,
                "message_quality_weight": 0.9,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    result = MOD.run_single(args, enforce_gates=False)
    assert result["generated_count"] == 1
    assert called["count"] == 1

    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["precheck_status"] == "warn"
    assert len(sample["pair_precheck_results"]) == 3
    assert sample["pair_quality_weight"] < 1.0
    assert 0.0 < sample["min_pair_quality_weight"] <= sample["pair_quality_weight"] <= 1.0


def test_k3_prompt_uses_all_changes_language():
    sample = {
        "intent_messages": [
            "fix auth parser bug in middleware",
            "add auth fallback flow for SSO users",
            "add tests for auth parser",
        ],
        "intent_subjects": [
            "fix auth parser bug",
            "add auth fallback flow",
            "add auth tests",
        ],
        "diff_evidence_card_1": "Changed files:\n- src/auth.py",
        "diff_evidence_card_2": "Changed files:\n- src/fallback.py",
        "diff_evidence_card_3": "Changed files:\n- tests/test_auth.py",
    }
    prompt = MOD.build_prompt(sample, fewshots=[])
    assert "combines 3 existing commits" in prompt
    assert "covers all 3 changes" in prompt
    assert "both changes" not in prompt
    assert "Original commit message 3" in prompt
    assert "Diff evidence card 3" in prompt


def test_build_prompt_requires_anchor_from_each_subject():
    sample = {
        "intent_messages": [
            "fix auth parser bug in middleware",
            "add auth fallback flow for SSO users",
        ],
        "intent_subjects": [
            "fix auth parser bug",
            "add auth fallback flow",
        ],
        "diff_evidence_card_1": "Changed files:\n- src/auth.py",
        "diff_evidence_card_2": "Changed files:\n- src/fallback.py",
    }
    prompt = MOD.build_prompt(sample, fewshots=[])
    assert "Keep at least one concrete action or anchor noun from each original subject." in prompt


def test_feat_fix_repair_prompts_require_dual_anchor_preservation_only_when_collapse_risk_present():
    sample = {
        "intent_k": 2,
        "type_pair": "feat+fix",
        "type_signature_canonical": "feat+fix",
        "intent_subjects": [
            "feat(crons): change build script",
            "fix(api): validate feature flag keys",
        ],
    }

    compress_prompt = MOD.build_compress_prompt(
        sample,
        "feat: update build script and validate feature flag keys",
        62,
        feat_fix_repair_guidance_mode="collapse_risk",
    )
    rewrite_prompt = MOD.build_rewrite_prompt(
        sample,
        "feat: update build script and validate feature flag keys",
        62,
        feat_fix_repair_guidance_mode="collapse_risk",
    )
    stable_compress_prompt = MOD.build_compress_prompt(
        sample,
        "fix(vite): ensure buildDir exists before write and unpin vite from minor",
        62,
        feat_fix_repair_guidance_mode="collapse_risk",
    )
    default_compress_prompt = MOD.build_compress_prompt(
        sample,
        "feat: update build script and validate feature flag keys",
        62,
    )

    assert "For feat+fix pairs, keep one concrete feat-side anchor and one concrete fix-side anchor." in compress_prompt
    assert "Do not let either side collapse into generic verbs such as update, improve, or handle." in compress_prompt
    assert "For feat+fix pairs, keep one concrete feat-side anchor and one concrete fix-side anchor." in rewrite_prompt
    assert "Do not let either side collapse into generic verbs such as update, improve, or handle." in rewrite_prompt
    assert "For feat+fix pairs, keep one concrete feat-side anchor and one concrete fix-side anchor." not in stable_compress_prompt
    assert "For feat+fix pairs, keep one concrete feat-side anchor and one concrete fix-side anchor." not in default_compress_prompt


def test_compute_message_scores_k3_tracks_all_sources(monkeypatch):
    sample = {
        "intent_subjects": ["fix auth parser bug", "add auth fallback flow", "add auth tests"],
        "intent_messages": [
            "fix auth parser bug in middleware",
            "add auth fallback flow for SSO users",
            "add tests for auth parser",
        ],
        "diff_evidence_card_1": "Changed files:\n- src/auth.py",
        "diff_evidence_card_2": "Changed files:\n- src/fallback.py",
        "diff_evidence_card_3": "Changed files:\n- tests/test_auth.py",
    }
    args = SimpleNamespace(
        bertscore_model="roberta-large",
        bertscore_lang="en",
        bertscore_idf=False,
        bertscore_cache_enabled=False,
    )

    def fake_bertscore_pair(candidate, reference, *_args, **_kwargs):
        if reference == "fix auth parser bug":
            score = 0.93
        elif reference == "add auth fallback flow":
            score = 0.88
        elif reference == "add auth tests":
            score = 0.22
        else:
            score = 0.81
        return {
            "precision": score,
            "recall": score,
            "f1": score,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": f"cache:{reference}",
        }

    monkeypatch.setattr(MOD, "bertscore_pair", fake_bertscore_pair)
    scores, _ = MOD.compute_message_scores(
        sample=sample,
        synthetic_subject="fix auth parser, add fallback flow, and add tests",
        length_limit=120,
        args=args,
        bertscore_cache={},
        bertscorer=object(),
    )
    assert scores["coverage_by_source"] == [0.93, 0.88, 0.22]
    assert scores["coverage_min_r"] == 0.22
    assert scores["coverage_avg_r"] == pytest.approx((0.93 + 0.88 + 0.22) / 3, rel=1e-6)
    assert scores["coverage_balance"] == pytest.approx(1.0 - (0.93 - 0.22), rel=1e-6)


def test_diff_evidence_card_uses_git_diff_not_commit_message():
    source = {
        "commit_message": "fix auth parser bug in middleware",
        "git_diff": make_diff("src/auth.py"),
    }
    evidence = MOD.build_diff_evidence_card(source)
    assert evidence["available"] is True
    assert evidence["source"] == "git_diff"
    assert "Changed files:" in evidence["card"]
    assert "- src/auth.py" in evidence["card"]
    assert "Patch evidence:" in evidence["card"]
    assert "src/auth.py: + new" in evidence["card"]
    assert "fix auth parser bug in middleware" not in evidence["card"]


def test_diff_evidence_card_marks_unavailable_when_diff_missing():
    source = {"commit_message": "fix auth parser bug in middleware"}
    evidence = MOD.build_diff_evidence_card(source)
    assert evidence["available"] is False
    assert evidence["source"] == "missing"
    assert evidence["card"] == "Diff evidence unavailable"
    assert "fix auth parser bug in middleware" not in evidence["card"]

    sample = {
        "intent_diff_evidence_available": [False, True],
        "intent_diff_evidence_sources": ["missing", "git_diff"],
    }
    meta = MOD.make_diff_evidence_meta(sample)
    assert meta["diff_evidence_available_by_source"] == [False, True]
    assert meta["diff_evidence_source_by_source"] == ["missing", "git_diff"]
    assert meta["diff_evidence_card_version"]


def test_materialize_sample_k3_has_diff_evidence_card_per_source():
    members = []
    for idx, file_path in enumerate(["src/a.py", "src/b.py", "tests/test_c.py"], start=1):
        git_diff = make_diff(file_path)
        members.append(
            {
                "sha": f"sha{idx}",
                "repo": "owner/repo",
                "type": ["fix", "feat", "test"][idx - 1],
                "tier": "A",
                "subject": f"subject {idx}",
                "commit_message": f"message {idx}",
                "manual_label": "A",
                "file_count": 1,
                "changed_lines": 2,
                "file_paths": [file_path],
                "source_confidence": 1.0,
                "blocks": MOD.split_file_blocks(git_diff),
                "git_diff": git_diff,
            }
        )
    pair = {
        "repo": "owner/repo",
        "different_type": True,
        "module_overlap": True,
        "type_pair": "feat+fix+test",
        "type_signature_raw": "fix+feat+test",
        "type_signature_canonical": "feat+fix+test",
        "merged_files": 3,
        "merged_lines": 6,
        "members": members,
    }
    sample = MOD.materialize_sample(pair, sample_id="simple3_0001", block_order="round_robin", seed=42)
    assert "diff_evidence_card_1" in sample
    assert "diff_evidence_card_2" in sample
    assert "diff_evidence_card_3" in sample
    prompt = MOD.build_prompt(sample, fewshots=[])
    assert "Diff evidence card 1" in prompt
    assert "Diff evidence card 2" in prompt
    assert "Diff evidence card 3" in prompt


def test_missing_diff_evidence_is_not_faked_from_commit_message():
    left = {
        "sha": "sha-left",
        "repo": "owner/repo",
        "type": "fix",
        "tier": "A",
        "subject": "fix parser crash",
        "commit_message": "MESSAGE_TOKEN_LEFT should never appear in diff card",
        "manual_label": "A",
        "file_count": 0,
        "changed_lines": 1,
        "file_paths": [],
        "source_confidence": 1.0,
        "blocks": [],
        "git_diff": "",
    }
    right = {
        "sha": "sha-right",
        "repo": "owner/repo",
        "type": "test",
        "tier": "A",
        "subject": "add parser tests",
        "commit_message": "MESSAGE_TOKEN_RIGHT should never appear in diff card",
        "manual_label": "A",
        "file_count": 0,
        "changed_lines": 1,
        "file_paths": [],
        "source_confidence": 1.0,
        "blocks": [],
        "git_diff": "",
    }
    pair = {
        "repo": "owner/repo",
        "different_type": True,
        "module_overlap": True,
        "type_pair": "fix+test",
        "type_signature_raw": "fix+test",
        "type_signature_canonical": "fix+test",
        "merged_files": 0,
        "merged_lines": 0,
        "members": [left, right],
    }
    sample = MOD.materialize_sample(pair, sample_id="simple2_9999", block_order="round_robin", seed=7)
    assert sample["intent_diff_evidence_available"] == [False, False]
    assert sample["intent_diff_evidence_sources"] == ["missing", "missing"]
    assert sample["diff_evidence_card_1"] == "Diff evidence unavailable"
    assert sample["diff_evidence_card_2"] == "Diff evidence unavailable"
    assert "MESSAGE_TOKEN_LEFT" not in sample["diff_evidence_card_1"]
    assert "MESSAGE_TOKEN_RIGHT" not in sample["diff_evidence_card_2"]
    prompt = MOD.build_prompt(sample, fewshots=[])
    assert "Diff evidence card 1:\nDiff evidence unavailable" in prompt
    assert "Diff evidence card 2:\nDiff evidence unavailable" in prompt


def test_subject_format_check_does_not_treat_double_colon_symbol_as_second_prefix():
    subject = "feat(router): add RouterServer::router and fix test typo"
    fmt = MOD.subject_format_check(subject, 62)
    assert fmt["len_ok"] == 1
    assert fmt["prefix_count"] == 1
    assert fmt["dual_prefix_hit"] == 0
    assert fmt["format"] == 1


def test_generate_subject_with_repair_uses_source_aware_compress_prompt(monkeypatch):
    sample = {
        "sample_id": "simple2_test",
        "intent_k": 2,
        "intent_messages": [
            "feat(router): add RouterServer accessor",
            "test(router): improve test naming",
        ],
        "intent_subjects": [
            "feat(router): add RouterServer::router",
            "test: improve test naming",
        ],
        "diff_evidence_card_1": "Changed files:\n- src/router.rs",
        "diff_evidence_card_2": "Changed files:\n- tests/router.rs",
    }
    args = SimpleNamespace(
        generator_mode="api",
        generation_cache_enabled=False,
        max_generation_attempts=1,
        max_abstractive_compress_attempts=1,
        max_rewrite_attempts=0,
        feat_fix_repair_guidance_mode="collapse_risk",
        enable_final_strong_path_tail_compress=False,
    )
    prompts: list[str] = []
    responses = iter(
        [
            {
                "ok": True,
                "content": "feat(router): add `RouterServer::router` accessor and fix test typo",
                "cached": False,
                "request_sha256": "gen",
                "raw_response": {"stage": "generate"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(router): add RouterServer::router, improve tests",
                "cached": False,
                "request_sha256": "compress",
                "raw_response": {"stage": "compress"},
                "error_type": "",
            },
        ]
    )

    def fake_generate(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(MOD, "deepseek_generate", fake_generate)

    result = MOD.generate_subject_with_repair(
        sample=sample,
        args=args,
        length_limit=62,
        fewshot_info={"examples": []},
        generation_cache={},
    )

    assert result["generation_success"] is True
    assert len(prompts) == 2
    compress_prompt = prompts[1]
    assert "Original source subjects:" in compress_prompt
    assert "feat(router): add RouterServer::router" in compress_prompt
    assert "test: improve test naming" in compress_prompt
    assert "Keep at least one concrete action or anchor noun from each original subject." in compress_prompt


def test_generate_subject_with_repair_uses_final_strong_compress_for_overlength_failure(monkeypatch):
    sample = {
        "sample_id": "simple2_overlength",
        "intent_k": 2,
        "intent_messages": [
            "feat(schematics): output built libraries to dist/lib/@scope",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "intent_subjects": [
            "feat(schematics): output built libraries to `dist/lib/@scope`",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "diff_evidence_card_1": "Changed files:\n- tools/schematics/build.ts",
        "diff_evidence_card_2": "Changed files:\n- tools/schematics/lint.ts",
    }
    args = SimpleNamespace(
        generator_mode="api",
        generation_cache_enabled=False,
        max_generation_attempts=1,
        max_abstractive_compress_attempts=1,
        max_rewrite_attempts=1,
        max_final_strong_compress_attempts=1,
        feat_fix_repair_guidance_mode="none",
        enable_final_strong_path_tail_compress=True,
    )
    prompts: list[str] = []
    responses = iter(
        [
            {
                "ok": True,
                "content": "(feat+fix) output built libraries to `dist/lib/@scope` and remove no-trailing-whitespace lint check",
                "cached": False,
                "request_sha256": "gen",
                "raw_response": {"stage": "generate"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope, drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "compress",
                "raw_response": {"stage": "compress"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope and drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "rewrite",
                "raw_response": {"stage": "rewrite"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output libs to dist, drop trailing lint",
                "cached": False,
                "request_sha256": "final-strong-compress",
                "raw_response": {"stage": "final_strong_compress"},
                "error_type": "",
            },
        ]
    )

    def fake_generate(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(MOD, "deepseek_generate", fake_generate)

    result = MOD.generate_subject_with_repair(
        sample=sample,
        args=args,
        length_limit=62,
        fewshot_info={"examples": []},
        generation_cache={},
    )

    assert result["generation_success"] is True
    assert result["synthetic_subject"] == "feat(schematics): output libs to dist, drop trailing lint"
    assert result["final_strong_compress_attempts"] == 1
    assert [item["stage"] for item in result["generation_trace"]] == [
        "generate",
        "compress",
        "rewrite",
        "final_strong_compress",
    ]
    final_prompt = prompts[-1]
    assert "Original source subjects:" in final_prompt
    assert "You must fit within 62 characters." in final_prompt
    assert "Aggressively shorten wording" in final_prompt
    assert "You may use safe technical abbreviations" in final_prompt
    assert "Prefer shortening repeated context, long paths, and long technical compounds before dropping anchor nouns." in final_prompt
    assert "If a path-like anchor is necessary, keep the shortest identifiable tail of the path." in final_prompt
    assert "Remove backticks around paths or identifiers." in final_prompt


def test_generate_subject_with_repair_postprocesses_final_strong_path_tail(monkeypatch):
    sample = {
        "sample_id": "simple2_overlength_path_tail",
        "intent_k": 2,
        "intent_messages": [
            "feat(schematics): output built libraries to dist/lib/@scope",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "intent_subjects": [
            "feat(schematics): output built libraries to `dist/lib/@scope`",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "diff_evidence_card_1": "Changed files:\n- tools/schematics/build.ts",
        "diff_evidence_card_2": "Changed files:\n- tools/schematics/lint.ts",
    }
    args = SimpleNamespace(
        generator_mode="api",
        generation_cache_enabled=False,
        max_generation_attempts=1,
        max_abstractive_compress_attempts=1,
        max_rewrite_attempts=1,
        max_final_strong_compress_attempts=1,
        final_strong_relaxed_length_limit=68,
        feat_fix_repair_guidance_mode="none",
        enable_final_strong_path_tail_compress=True,
    )
    responses = iter(
        [
            {
                "ok": True,
                "content": "(feat+fix) output built libraries to `dist/lib/@scope` and remove no-trailing-whitespace lint check",
                "cached": False,
                "request_sha256": "gen",
                "raw_response": {"stage": "generate"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to `dist/lib/@scope` and remove no-trailing-whitespace",
                "cached": False,
                "request_sha256": "compress",
                "raw_response": {"stage": "compress"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to `dist/lib/@scope` and remove no-trailing-whitespace",
                "cached": False,
                "request_sha256": "rewrite",
                "raw_response": {"stage": "rewrite"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output libs to `dist/lib/@scope`, drop trailing ws lint",
                "cached": False,
                "request_sha256": "final-strong-compress",
                "raw_response": {"stage": "final_strong_compress"},
                "error_type": "",
            },
        ]
    )

    def fake_generate(prompt, *_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(MOD, "deepseek_generate", fake_generate)

    result = MOD.generate_subject_with_repair(
        sample=sample,
        args=args,
        length_limit=62,
        fewshot_info={"examples": []},
        generation_cache={},
    )

    assert result["generation_success"] is True
    assert result["synthetic_subject"] == "feat(schematics): output libs to lib/@scope, drop trailing ws lint"
    assert result["message_error_type"] == "ok"
    assert result["generation_trace"][-1]["subject_after"] == "feat(schematics): output libs to lib/@scope, drop trailing ws lint"
    assert result["generation_trace"][-1]["subject_after_char_len"] <= 68


def test_generate_subject_with_repair_allows_relaxed_length_only_in_final_strong_compress(monkeypatch):
    sample = {
        "sample_id": "simple2_overlength_relaxed",
        "intent_k": 2,
        "intent_messages": [
            "feat(schematics): output built libraries to dist/lib/@scope",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "intent_subjects": [
            "feat(schematics): output built libraries to `dist/lib/@scope`",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "diff_evidence_card_1": "Changed files:\n- tools/schematics/build.ts",
        "diff_evidence_card_2": "Changed files:\n- tools/schematics/lint.ts",
    }
    args = SimpleNamespace(
        generator_mode="api",
        generation_cache_enabled=False,
        max_generation_attempts=1,
        max_abstractive_compress_attempts=1,
        max_rewrite_attempts=1,
        max_final_strong_compress_attempts=1,
        _final_strong_relaxed_length_limit=68,
    )
    responses = iter(
        [
            {
                "ok": True,
                "content": "(feat+fix) output built libraries to `dist/lib/@scope` and remove no-trailing-whitespace lint check",
                "cached": False,
                "request_sha256": "gen",
                "raw_response": {"stage": "generate"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope, drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "compress",
                "raw_response": {"stage": "compress"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope and drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "rewrite",
                "raw_response": {"stage": "rewrite"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output libs to dist/lib/@scope, drop lint rule",
                "cached": False,
                "request_sha256": "final-strong-compress",
                "raw_response": {"stage": "final_strong_compress"},
                "error_type": "",
            },
        ]
    )

    monkeypatch.setattr(MOD, "deepseek_generate", lambda *args, **kwargs: next(responses))

    result = MOD.generate_subject_with_repair(
        sample=sample,
        args=args,
        length_limit=62,
        fewshot_info={"examples": []},
        generation_cache={},
    )

    assert result["generation_success"] is True
    assert len(result["synthetic_subject"]) == 64
    assert result["effective_length_limit"] == 68
    assert result["final_strong_compress_attempts"] == 1


def test_generate_subject_with_repair_resets_relaxed_length_on_later_base_limit_success(monkeypatch):
    sample = {
        "sample_id": "simple2_overlength_then_regenerate",
        "intent_k": 2,
        "intent_messages": [
            "feat(schematics): output built libraries to dist/lib/@scope",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "intent_subjects": [
            "feat(schematics): output built libraries to `dist/lib/@scope`",
            "fix(schematics): remove no-trailing-whitespace lint check",
        ],
        "diff_evidence_card_1": "Changed files:\n- tools/schematics/build.ts",
        "diff_evidence_card_2": "Changed files:\n- tools/schematics/lint.ts",
    }
    args = SimpleNamespace(
        generator_mode="api",
        generation_cache_enabled=False,
        max_generation_attempts=2,
        max_abstractive_compress_attempts=1,
        max_rewrite_attempts=1,
        max_final_strong_compress_attempts=1,
        _final_strong_relaxed_length_limit=68,
    )
    responses = iter(
        [
            {
                "ok": True,
                "content": "(feat+fix) output built libraries to `dist/lib/@scope` and remove no-trailing-whitespace lint check",
                "cached": False,
                "request_sha256": "gen-1",
                "raw_response": {"stage": "generate-1"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope, drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "compress-1",
                "raw_response": {"stage": "compress-1"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output built libs to dist/lib/@scope and drop trailing whitespace lint",
                "cached": False,
                "request_sha256": "rewrite-1",
                "raw_response": {"stage": "rewrite-1"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output libs to dist/lib/@scope, drop lint rule and extras",
                "cached": False,
                "request_sha256": "final-strong-compress-1",
                "raw_response": {"stage": "final_strong_compress-1"},
                "error_type": "",
            },
            {
                "ok": True,
                "content": "feat(schematics): output libs and drop lint",
                "cached": False,
                "request_sha256": "gen-2",
                "raw_response": {"stage": "generate-2"},
                "error_type": "",
            },
        ]
    )

    monkeypatch.setattr(MOD, "deepseek_generate", lambda *args, **kwargs: next(responses))

    result = MOD.generate_subject_with_repair(
        sample=sample,
        args=args,
        length_limit=62,
        fewshot_info={"examples": []},
        generation_cache={},
    )

    assert result["generation_success"] is True
    assert result["synthetic_subject"] == "feat(schematics): output libs and drop lint"
    assert result["effective_length_limit"] == 62
    assert result["final_strong_compress_attempts"] == 1


def test_compute_message_scores_k2_keeps_coverage_columns(monkeypatch):
    sample = {
        "intent_subjects": ["fix auth parser bug", "add auth tests"],
        "intent_messages": [
            "fix auth parser bug in middleware",
            "add tests for auth parser",
        ],
    }
    args = SimpleNamespace(
        bertscore_model="roberta-large",
        bertscore_lang="en",
        bertscore_idf=False,
        bertscore_cache_enabled=False,
    )

    def fake_bertscore_pair(candidate, reference, *_args, **_kwargs):
        score = 0.91 if reference == "fix auth parser bug" else 0.86
        return {
            "precision": score,
            "recall": score,
            "f1": score,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": f"cache:{reference}",
        }

    monkeypatch.setattr(MOD, "bertscore_pair", fake_bertscore_pair)
    scores, _ = MOD.compute_message_scores(
        sample=sample,
        synthetic_subject="fix auth parser and add tests",
        length_limit=120,
        args=args,
        bertscore_cache={},
        bertscorer=object(),
    )
    assert scores["coverage_1_r"] == 0.91
    assert scores["coverage_2_r"] == 0.86


def test_fewshot_exact_miss_falls_back_and_logs(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_fallback.db"
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    info = MOD.retrieve_fewshot_examples(
        db_path=str(fewshot_db),
        table="fewshot_examples",
        type_signature_canonical="fix+refactor+test",
        current_repo="owner/repo",
        k=3,
        seed=42,
    )
    assert info["few_shot_source"] == "generic_fallback"
    assert info["retrieval_status"] == "partial"
    assert info["retrieval_result_count"] == 3
    assert info["retrieval_error"] == ""
    retrieval_log = info["few_shot_retrieval_log"]
    assert retrieval_log["query_levels_attempted"] == [
        {"level": "exact_kway", "candidate_count": 0, "selected_count": 0},
        {"level": "type_overlap", "candidate_count": 2, "selected_count": 2},
        {"level": "pairwise_overlap", "candidate_count": 0, "selected_count": 0},
        {"level": "single_type_overlap", "candidate_count": 0, "selected_count": 0},
        {"level": "generic_fallback", "candidate_count": 1, "selected_count": 1},
    ]
    assert retrieval_log["examples_found_per_level"] == {
        "exact_kway": 0,
        "type_overlap": 2,
        "pairwise_overlap": 0,
        "single_type_overlap": 0,
        "generic_fallback": 1,
    }
    assert retrieval_log["selected_example_ids"] == ["ex_fix_test", "ex_refactor_test", "ex_generic"]


def test_fewshot_audit_detects_double_prefix(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_bad_style.db"
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "ex_bad",
                "repo": "fewshot/repo1",
                "sha": "fs_bad",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "test: add auth tests and fix(storage): prevent crash",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        ],
    )
    rows = MOD.load_fewshot_pool_rows(str(fewshot_db), "fewshot_examples")
    audit = MOD.audit_fewshot_pool(rows, min_total=1, min_per_common_signature=0, strict_style=True)
    assert audit["audit_pass"] is False
    assert audit["bad_style_count"] == 1
    assert audit["double_prefix_count"] == 1
    assert any("fewshot_bad_style_detected" in blocker for blocker in audit["blockers"])


def test_retrieve_fewshot_filters_ineligible_and_bad_style(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_filter.db"
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "ex_ineligible",
                "repo": "fewshot/repo1",
                "sha": "fs_ineligible",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 0,
                "quality_score": 0.9,
            },
            {
                "example_id": "ex_bad_style",
                "repo": "fewshot/repo2",
                "sha": "fs_bad_style",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "test: add tests and fix(parser): handle empty token",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.95,
            },
            {
                "example_id": "ex_good",
                "repo": "fewshot/repo3",
                "sha": "fs_good",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser fallback and add regression tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.99,
            },
        ],
    )
    info = MOD.retrieve_fewshot_examples(
        db_path=str(fewshot_db),
        table="fewshot_examples",
        type_signature_canonical="fix+test",
        current_repo="owner/repo",
        k=1,
        seed=42,
    )
    assert info["few_shot_retrieval_log"]["selected_example_ids"] == ["ex_good"]
    assert info["few_shot_retrieval_log"]["excluded_ineligible_count"] >= 1
    assert info["few_shot_retrieval_log"]["excluded_bad_style_count"] >= 1


def test_fewshot_audit_passes_for_clean_covered_pool(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_clean.db"
    signatures = [
        "fix+test",
        "feat+test",
        "fix+docs",
        "feat+docs",
        "fix+refactor",
        "feat+refactor",
        "docs+test",
        "perf+refactor",
        "fix+perf",
    ]
    rows = []
    for idx, signature in enumerate(signatures, start=1):
        rows.append(
            {
                "example_id": f"ex_{idx}",
                "repo": f"fewshot/repo{idx}",
                "sha": f"fs_{idx}",
                "type_pair": signature,
                "type_signature_raw": signature,
                "type_signature_canonical": signature,
                "intent_k": 2,
                "subject": f"improve {signature.replace('+', ' and ')} workflow",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        )
    write_fewshot_db(fewshot_db, rows)
    loaded_rows = MOD.load_fewshot_pool_rows(str(fewshot_db), "fewshot_examples")
    audit = MOD.audit_fewshot_pool(
        loaded_rows,
        min_total=len(signatures),
        min_per_common_signature=1,
        strict_style=True,
    )
    assert audit["audit_pass"] is True
    assert audit["blockers"] == []
    assert all(value >= 1 for value in audit["common_signature_coverage"].values())


def test_no_fewshot_pool_fails_early(tmp_path: Path):
    output_dir = tmp_path / "out_no_fewshot"
    args = make_args(
        tmp_path,
        tmp_path / "source_missing_pool.csv",
        output_dir,
        fewshot_db="",
        fewshot_source_csv=str(tmp_path / "missing_pool.csv"),
    )
    write_minimal_csv(
        Path(args.source_csv),
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    with pytest.raises(RuntimeError) as exc_info:
        MOD.run_single(args, enforce_gates=False)
    assert "Few-shot pool is mandatory for formal Step2 message generation." in str(exc_info.value)


def test_formal_run_blocks_non_formal_ready_fewshot_pool(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "formal_block_source.csv"
    output_dir = tmp_path / "formal_block_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        fewshot_min_total_examples=80,
        fewshot_min_examples_per_common_signature=3,
        fewshot_audit_strict_style=True,
        run_purpose="formal",
        formal_run=True,
        run_valid_for_paper=True,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    with pytest.raises(RuntimeError) as exc_info:
        MOD.run_single(args, enforce_gates=False)
    error_text = str(exc_info.value)
    assert "Default few-shot pool is pilot-sized and not formal-ready." in error_text
    assert "fewshot_total_below_min" in error_text
    assert "fewshot_common_signature_coverage_insufficient" in error_text
    assert not (output_dir / "synthetic_samples.jsonl").exists()


def test_canonical_type_signature_is_consistent():
    assert MOD.canonicalize_type("bugfix") == "fix"
    assert MOD.canonicalize_type("tests") == "test"
    assert MOD.canonicalize_type("fix(auth)") == "fix"
    assert MOD.canonical_type_signature(["bugfix", "tests"]) == "fix+test"
    assert MOD.canonical_type_signature(["performance", "refactor"]) == "perf+refactor"


def test_message_gate_failure_writes_report_and_exits_nonzero(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "source_gate_fail.csv"
    output_dir = tmp_path / "out_gate_fail"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth bug",
            "message": "fix auth bug in parser",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add auth tests",
            "message": "add auth tests for parser",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        gate_min_coverage_min_avg=0.95,
        gate_min_coverage_min_p10=0.95,
    )

    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "retrieve_fewshot_examples",
        lambda **_kwargs: {
            "examples": [{"example_id": "e1", "type_signature_canonical": "fix+test", "subject": "fix parser and add tests"}],
            "few_shot_source": "exact_kway",
            "retrieval_backend": "sqlite_formal_kway_v2",
            "retrieval_result_count": 1,
            "retrieval_error": "",
            "retrieval_status": "exact",
            "few_shot_retrieval_log": {
                "requested_type_signature": "fix+test",
                "query_levels_attempted": [{"level": "exact_kway", "candidate_count": 1, "selected_count": 1}],
                "examples_found_per_level": {"exact_kway": 1},
                "selected_example_ids": ["e1"],
                "selected_example_type_signatures": ["fix+test"],
                "selected_example_repos": ["fewshot/repo1"],
                "retrieval_status": "exact",
                "failure_reason": "",
            },
        },
    )
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix auth parser and add tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["gate_fail_req"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "compute_message_scores",
        lambda **_kwargs: (
            {
                "format": 1,
                "coverage_r_list": [0.2, 0.3],
                "coverage_by_source": [0.2, 0.3],
                "coverage_min_r": 0.2,
                "coverage_min": 0.2,
                "coverage_avg_r": 0.25,
                "coverage_avg": 0.25,
                "coverage_balance": 0.9,
                "faithfulness_p": 0.4,
                "artifact_hit_count": 0,
                "artifact_score": 1.0,
                "relevance_score": 1.0,
                "style_score": 1.0,
                "generic_phrase_hit": 0,
                "token_count": 6,
                "imperative_head": 1,
                "message_quality_weight": 0.08,
                "bertscore_compute_invalid": 0,
                "bertscore_error": "",
            },
            {"coverage_cache_keys": [], "faithfulness_cache_key": "", "format_detail": {"format": 1}},
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        MOD.run_single(args, enforce_gates=True)
    assert "Message gate failed" in str(exc_info.value)
    gate_report = json.loads((output_dir / "message_gate_report.json").read_text(encoding="utf-8"))
    assert gate_report["message_gate_passed"] is False
    assert gate_report["gate_metrics"]["coverage_min_avg"] == 0.2


def test_preflight_passes_with_mocked_resources(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_source.csv"
    output_dir = tmp_path / "preflight_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(tmp_path, source_csv, output_dir, preflight=True)
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})

    report = MOD.run_preflight(args)
    assert report["passed"] is True
    report_path = Path(report["report_path"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["checks"]["fewshot"]["passed"] is True
    assert payload["preflight_target_run_purpose"] == "formal"
    fewshot = payload["checks"]["fewshot"]
    assert fewshot["formal_required_for_target"] is True
    assert fewshot["fewshot_pool_formal_ready"] is True
    assert fewshot["fewshot_pool_total_examples"] == 3
    assert fewshot["fewshot_pool_verified_examples"] == 3
    assert fewshot["retrieval_probe"]["retrieval_status"] == "exact"
    assert fewshot["retrieval_probe"]["few_shot_source"] == "exact_kway"
    assert fewshot["retrieval_probe"]["retrieval_result_count"] == 1
    assert payload["diff_evidence"]["diff_evidence_policy"] == MOD.DIFF_EVIDENCE_POLICY
    assert payload["diff_evidence"]["diff_evidence_card_version"] == MOD.DIFF_EVIDENCE_CARD_VERSION
    stable_report_path = output_dir / "preflight_report.json"
    assert stable_report_path.exists()
    stable_payload = json.loads(stable_report_path.read_text(encoding="utf-8"))
    assert stable_payload["passed"] is True
    assert stable_payload["report_path"] == report["report_path"]
    assert stable_payload["report"]["checks"]["input_data"]["a_tier_count"] == 2


def test_preflight_formal_blocks_pilot_sized_pool(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_pilot_source.csv"
    output_dir = tmp_path / "preflight_pilot_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        preflight=True,
        fewshot_min_total_examples=80,
        fewshot_min_examples_per_common_signature=3,
        fewshot_audit_strict_style=True,
        run_purpose="formal",
    )
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})
    report = MOD.run_preflight(args)
    assert report["passed"] is False
    fewshot = report["checks"]["fewshot"]
    assert fewshot["passed"] is False
    assert fewshot["fewshot_pool_formal_ready"] is False
    assert fewshot["fewshot_pool_total_examples"] == 3
    assert "fewshot_total_below_min" in " ".join(fewshot["fewshot_pool_audit"]["blockers"])
    assert "type_signature_counts" in fewshot["fewshot_pool_audit"]
    assert report["diff_evidence"]["diff_evidence_policy"] == MOD.DIFF_EVIDENCE_POLICY


def test_preflight_fails_when_api_key_missing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_no_key.csv"
    output_dir = tmp_path / "preflight_no_key_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        preflight=True,
        deepseek_api_key="",
        _resolved_deepseek_api_key="",
    )
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})

    report = MOD.run_preflight(args)
    assert report["passed"] is False
    assert report["checks"]["generator"]["passed"] is False
    assert "DEEPSEEK_API_KEY" in report["checks"]["generator"]["detail"]


def test_preflight_api_ping_http_402_refreshes_stable_report(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_http_402.csv"
    output_dir = tmp_path / "preflight_http_402_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        preflight=True,
        preflight_api_ping=True,
        deepseek_api_key="test-key",
        _resolved_deepseek_api_key="test-key",
    )
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})
    monkeypatch.setattr(
        MOD,
        "run_generator_preflight_ping",
        lambda _args: {
            "ok": False,
            "error_type": "http_402",
            "error_guidance": "insufficient_balance_or_billing_blocked",
            "raw_response_preview": "{\"error\":{\"message\":\"Insufficient Balance\"}}",
        },
    )

    report = MOD.run_preflight(args)
    assert report["passed"] is False
    generator = report["checks"]["generator"]
    assert generator["passed"] is False
    assert generator["detail"] == "Remote API ping failed: http_402 (insufficient_balance_or_billing_blocked)"
    assert generator["api_ping"]["error_guidance"] == "insufficient_balance_or_billing_blocked"

    stable_report_path = output_dir / "preflight_report.json"
    assert stable_report_path.exists()
    stable_payload = json.loads(stable_report_path.read_text(encoding="utf-8"))
    assert stable_payload["passed"] is False
    assert stable_payload["report"]["checks"]["generator"]["detail"] == generator["detail"]
    assert stable_payload["report_path"] == report["report_path"]


def test_run_single_fails_fast_on_provider_blocking_error(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "provider_hard_fail.csv"
    output_dir = tmp_path / "provider_hard_fail_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(tmp_path, source_csv, output_dir, target_count=1)
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    call_tags: list[str] = []

    def fake_generate(*, prompt, args, generation_cache, cache_enabled, extra_tag):
        call_tags.append(extra_tag)
        return {
            "ok": False,
            "content": "",
            "cached": False,
            "request_sha256": f"req-{len(call_tags)}",
            "raw_response": "{\"error\":{\"message\":\"Insufficient Balance\"}}",
            "error_type": "http_402",
        }

    monkeypatch.setattr(MOD, "deepseek_generate", fake_generate)

    with pytest.raises(RuntimeError) as exc_info:
        MOD.run_single(args, enforce_gates=True)

    message = str(exc_info.value)
    assert "http_402" in message
    assert "insufficient_balance_or_billing_blocked" in message
    assert "Insufficient Balance" in message
    assert len(call_tags) == 1


def test_deepseek_generate_detects_reasoning_only_truncation(monkeypatch):
    class FakeResponse:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": "Need to think through the merge before answering.",
                },
            }
        ],
        "usage": {
            "completion_tokens": 32,
            "completion_tokens_details": {"reasoning_tokens": 32},
        },
    }
    monkeypatch.setattr(
        MOD.urllib.request,
        "urlopen",
        lambda _req, timeout=0: FakeResponse(payload),
    )
    args = SimpleNamespace(
        generator_model="deepseek-v4-pro",
        generator_provider="deepseek_api",
        deepseek_base_url="https://api.deepseek.com/v1/chat/completions",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=32,
        seed=42,
        api_timeout_sec=10,
        _resolved_deepseek_api_key="test-key",
    )

    result = MOD.deepseek_generate(
        prompt="Write one synthetic commit subject.",
        args=args,
        generation_cache={},
        cache_enabled=True,
        extra_tag="unit",
    )

    assert result["ok"] is False
    assert result["content"] == ""
    assert result["error_type"] == "reasoning_only_truncated"
    assert result["raw_response"]["choices"][0]["finish_reason"] == "length"


def test_deepseek_generate_sends_thinking_disabled_for_v4_pro(monkeypatch):
    captured_payload: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            payload = {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "fix parser bug and add tests",
                        },
                    }
                ]
            }
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        del timeout
        captured_payload.update(json.loads(req.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(MOD.urllib.request, "urlopen", fake_urlopen)
    args = SimpleNamespace(
        generator_model="deepseek-v4-pro",
        generator_provider="deepseek_api",
        generator_thinking_type="disabled",
        deepseek_base_url="https://api.deepseek.com/v1/chat/completions",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=128,
        seed=42,
        api_timeout_sec=10,
        _resolved_deepseek_api_key="test-key",
    )

    result = MOD.deepseek_generate(
        prompt="Write one synthetic commit subject.",
        args=args,
        generation_cache={},
        cache_enabled=False,
        extra_tag="unit",
    )

    assert result["ok"] is True
    assert captured_payload["model"] == "deepseek-v4-pro"
    assert captured_payload["thinking"] == {"type": "disabled"}


def test_init_bertscorer_prefers_offline_cache_when_available(monkeypatch):
    observed: dict[str, object] = {}

    class FakeBERTScorer:
        def __init__(self, **kwargs):
            observed["kwargs"] = kwargs
            observed["hf_hub_offline"] = os.environ.get("HF_HUB_OFFLINE")
            observed["transformers_offline"] = os.environ.get("TRANSFORMERS_OFFLINE")

    fake_module = types.SimpleNamespace(BERTScorer=FakeBERTScorer)
    monkeypatch.setitem(sys.modules, "bert_score", fake_module)
    monkeypatch.setattr(MOD, "has_local_hf_model_snapshot", lambda _model_name: True)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    args = SimpleNamespace(
        bertscore_model="roberta-large",
        bertscore_lang="en",
        bertscore_idf=False,
    )

    scorer = MOD.init_bertscorer(args)

    assert isinstance(scorer, FakeBERTScorer)
    assert observed["hf_hub_offline"] == "1"
    assert observed["transformers_offline"] == "1"
    assert os.environ.get("HF_HUB_OFFLINE") is None
    assert os.environ.get("TRANSFORMERS_OFFLINE") is None


def test_preflight_fails_when_fewshot_pool_missing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_no_pool.csv"
    output_dir = tmp_path / "preflight_no_pool_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        preflight=True,
        fewshot_db="",
        fewshot_source_csv=str(tmp_path / "missing.csv"),
    )
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})

    report = MOD.run_preflight(args)
    assert report["passed"] is False
    assert report["checks"]["fewshot"]["passed"] is False
    assert "Few-shot pool is mandatory" in report["checks"]["fewshot"]["detail"]


def test_preflight_fails_when_fewshot_build_manifest_missing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_manifest_source.csv"
    output_dir = tmp_path / "preflight_manifest_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        preflight=True,
        fewshot_build_manifest_path=str(tmp_path / "missing_fewshot_build_manifest.json"),
    )
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})

    report = MOD.run_preflight(args)
    assert report["passed"] is False
    assert report["checks"]["formal_assets"]["passed"] is False
    assert "fewshot_build_manifest_missing" in report["checks"]["formal_assets"]["blockers"]


def test_preflight_fails_when_required_input_columns_missing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "bad_source.csv"
    output_dir = tmp_path / "preflight_bad_source_out"
    with source_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repo", "sha", "type", "message", "git_diff", "manual_label"])
        writer.writeheader()
        writer.writerow(
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            }
        )
    args = make_args(tmp_path, source_csv, output_dir, preflight=True)
    monkeypatch.setattr(MOD, "check_scoring_backend_readiness", lambda _args: {"passed": True, "scorer_backend": "mock"})

    report = MOD.run_preflight(args)
    assert report["passed"] is False
    assert report["checks"]["input_data"]["passed"] is False
    assert "missing_fields" in report["checks"]["input_data"]["detail"]


def test_build_source_pool_accepts_conservative_source_rows_and_preserves_confidence(tmp_path: Path):
    source_csv = tmp_path / "conservative_atomic_sources.csv"
    write_conservative_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "commit_url": "https://github.com/owner/repo/commit/sha1",
                "type": "fix",
                "subject": "fix auth parser",
                "message": "fix auth parser in middleware",
                "git_diff": make_diff("src/auth.py"),
                "model_prob": "0.96",
                "model_tier": "A",
                "tau_a": "0.89",
                "tau_b": "0.41",
                "rule_label": "1",
                "rule_weight": "0.85",
                "passed_rule_refilter": "true",
                "conservative_tier": "A",
                "selection_strategy": "model_rule_refilter",
                "selection_reason": "model_tier_a_and_rule_positive",
                "source_confidence": "0.816",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "commit_url": "https://github.com/owner/repo/commit/sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add tests for auth parser",
                "git_diff": make_diff("tests/test_auth.py"),
                "model_prob": "0.93",
                "model_tier": "A",
                "tau_a": "0.89",
                "tau_b": "0.41",
                "rule_label": "1",
                "rule_weight": "0.90",
                "passed_rule_refilter": "true",
                "conservative_tier": "A",
                "selection_strategy": "model_rule_refilter",
                "selection_reason": "model_tier_a_and_rule_positive",
                "source_confidence": "0.837",
            },
        ],
    )

    rows = MOD.load_csv(source_csv)
    pool, stats = MOD.build_source_pool_from_minimal(rows, manual_label="A")

    assert stats["a_tier_rows"] == 2
    assert pool[0]["manual_label"] == "A"
    assert pool[0]["tier"] == "A"
    assert pool[0]["source_confidence"] == pytest.approx(0.816)
    assert pool[0]["selection_strategy"] == "model_rule_refilter"
    assert pool[0]["selection_reason"] == "model_tier_a_and_rule_positive"
    assert pool[0]["conservative_tier"] == "A"
    assert pool[0]["rule_label"] == "1"


def test_build_source_pool_legacy_rows_default_source_confidence_to_one() -> None:
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser",
            "message": "fix parser in auth flow",
            "git_diff": make_diff("src/auth.py"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add tests",
            "message": "add tests for parser",
            "git_diff": make_diff("tests/test_auth.py"),
            "manual_label": "A",
        },
    ]

    pool, stats = MOD.build_source_pool_from_minimal(rows, manual_label="A")

    assert stats["a_tier_rows"] == 2
    assert pool[0]["source_confidence"] == pytest.approx(1.0)


def test_smoke_config_validation_accepts_with_env_and_dependencies(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "smoke_source.csv"
    fewshot_db = tmp_path / "smoke_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(
        tmp_path,
        source_csv,
        fewshot_db,
        output_dir=str(tmp_path / "smoke_out"),
        target_count=3,
        deepseek_api_key="",
    )
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.message_stage_enabled is True
    assert args.enable_message_gate is True
    assert args.fewshot_enabled is True
    assert args._resolved_deepseek_api_key == "env-test-key"
    assert args._deepseek_api_key_source == "env"
    assert args.run_purpose == "formal"
    assert args.run_purpose_source == "explicit_config_or_cli"
    assert args.run_valid_for_paper is True
    assert args.protocol_violations == []


def test_smoke_config_validation_rejects_without_api_key(monkeypatch, tmp_path: Path, capsys):
    source_csv = tmp_path / "smoke_no_key_source.csv"
    fewshot_db = tmp_path / "smoke_no_key_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(
        tmp_path,
        source_csv,
        fewshot_db,
        output_dir=str(tmp_path / "smoke_no_key_out"),
        deepseek_api_key="",
    )
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    with pytest.raises(SystemExit):
        MOD.parse_args()
    assert (
        "Formal message generation requires config.deepseek_api_key, --deepseek-api-key, or DEEPSEEK_API_KEY."
        in capsys.readouterr().err
    )


def test_smoke_config_still_requires_fewshot_and_message_gate(monkeypatch, tmp_path: Path, capsys):
    source_csv = tmp_path / "smoke_requirements_source.csv"
    fewshot_db = tmp_path / "smoke_requirements_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")

    config_no_gate = make_runtime_config(tmp_path, source_csv, fewshot_db, message_gate_enabled=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_no_gate)])
    with pytest.raises(SystemExit) as gate_exc:
        MOD.parse_args()
    assert "Message gate is mandatory in formal Step2 runs." in str(gate_exc.value)

    config_no_fewshot = make_runtime_config(tmp_path, source_csv, fewshot_db, fewshot_enabled=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_no_fewshot)])
    with pytest.raises(SystemExit):
        MOD.parse_args()
    assert "Few-shot retrieval is mandatory in formal Step2 runs." in capsys.readouterr().err


def test_debug_mock_generator_runs_without_api_key_and_marks_non_formal(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "mock_source.csv"
    output_dir = tmp_path / "mock_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        generator_mode="mock",
        deepseek_api_key="",
        _resolved_deepseek_api_key="",
        formal_run=False,
        run_valid_for_paper=False,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())

    def fake_bertscore_pair(candidate, reference, *_args, **_kwargs):
        score = 0.9 if "fix auth bug" in reference else 0.88
        return {
            "precision": score,
            "recall": score,
            "f1": score,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": f"cache:{reference}",
        }

    monkeypatch.setattr(MOD, "bertscore_pair", fake_bertscore_pair)
    result = MOD.run_single(args, enforce_gates=True)
    assert result["formal_run"] is False
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["formal_run"] is False
    assert metadata["run_valid_for_paper"] is False
    assert metadata["message_config"]["generator_mode"] == "mock"
    assert (output_dir / "message_gate_report.json").exists()


def test_debug_mock_generator_exercises_kway_prompt_and_scoring(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "mock_k3_source.csv"
    output_dir = tmp_path / "mock_k3_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth parser bug",
                "message": "fix auth parser bug in middleware",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "feat",
                "subject": "add auth fallback flow",
                "message": "add auth fallback flow for SSO users",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha3",
                "type": "test",
                "subject": "add auth tests",
                "message": "add tests for auth parser",
                "git_diff": make_diff("src/c.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        intent_k=3,
        k_sweep_max=3,
        generator_mode="mock",
        deepseek_api_key="",
        _resolved_deepseek_api_key="",
        formal_run=False,
        run_valid_for_paper=False,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    captured_prompt = {"value": ""}
    original_build_prompt = MOD.build_prompt

    def wrapped_build_prompt(sample, fewshots):
        prompt = original_build_prompt(sample, fewshots)
        captured_prompt["value"] = prompt
        return prompt

    def fake_bertscore_pair(candidate, reference, *_args, **_kwargs):
        if reference == "fix auth parser bug":
            score = 0.93
        elif reference == "add auth fallback flow":
            score = 0.89
        elif reference == "add auth tests":
            score = 0.9
        else:
            score = 0.91
        return {
            "precision": score,
            "recall": score,
            "f1": score,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": f"cache:{reference}",
        }

    monkeypatch.setattr(MOD, "build_prompt", wrapped_build_prompt)
    monkeypatch.setattr(MOD, "bertscore_pair", fake_bertscore_pair)
    MOD.run_single(args, enforce_gates=True)
    assert "all 3 changes" in captured_prompt["value"]
    assert "Original commit message 1" in captured_prompt["value"]
    assert "Original commit message 2" in captured_prompt["value"]
    assert "Original commit message 3" in captured_prompt["value"]
    assert "Diff evidence card 1" in captured_prompt["value"]
    assert "Diff evidence card 2" in captured_prompt["value"]
    assert "Diff evidence card 3" in captured_prompt["value"]
    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["intent_k"] == 3
    assert sample["generation_status"] == "generated"
    expected_coverage = {
        "fix auth parser bug": 0.93,
        "add auth fallback flow": 0.89,
        "add auth tests": 0.9,
    }
    actual_coverage = {
        subject: score
        for subject, score in zip(sample["intent_subjects"], sample["message_scores"]["coverage_by_source"])
    }
    assert actual_coverage == expected_coverage
    assert sample["message_scores"]["coverage_min"] == 0.89
    assert sample["message_scores"]["coverage_avg"] == 0.906667
    assert sample["message_meta"]["few_shot_retrieval_log"]["few_shot_selected_count"] == 1


def test_precheck_skip_samples_do_not_call_generator_even_in_mock_mode(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "mock_skip_source.csv"
    output_dir = tmp_path / "mock_skip_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "release",
                "subject": "release v1.2.3",
                "message": "release v1.2.3 package metadata",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "fix",
                "subject": "fix login bug",
                "message": "fix login bug in session validator",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        generator_mode="mock",
        deepseek_api_key="",
        _resolved_deepseek_api_key="",
        formal_run=False,
        run_valid_for_paper=False,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    called = {"count": 0}
    original = MOD.generate_subject_with_repair

    def wrapped_generate(*_args, **_kwargs):
        called["count"] += 1
        return original(*_args, **_kwargs)

    monkeypatch.setattr(MOD, "generate_subject_with_repair", wrapped_generate)
    MOD.run_single(args, enforce_gates=False)
    assert called["count"] == 0
    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["precheck_status"] == "skip"
    assert sample["precheck_skip_reason"] == "forbidden_type_pair"
    assert sample["generation_status"] == "not_attempted_precheck_skip"
    assert sample["message_status"] == "not_generated_precheck_skip"
    assert sample["few_shot_source"] == "failed"
    assert sample["few_shot_retrieval_log"]["failure_reason"] == "not_attempted_precheck_skip"
    assert sample["message_meta"]["llm_generation_attempted"] is False
    assert sample["message_meta"]["generation_failure_reason"] == "source_pair_precheck_skip"
    assert sample["message_scores"]["bertscore_error"] == "skipped_by_source_pair_precheck"


def test_generated_samples_still_write_message_gate_report(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "gate_report_source.csv"
    output_dir = tmp_path / "gate_report_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(tmp_path, source_csv, output_dir)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix auth tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "bertscore_pair",
        lambda *_args, **_kwargs: {
            "precision": 0.9,
            "recall": 0.9,
            "f1": 0.9,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": "cache",
        },
    )
    MOD.run_single(args, enforce_gates=True)
    gate_report = json.loads((output_dir / "message_gate_report.json").read_text(encoding="utf-8"))
    synthetic_rows = [
        json.loads(line)
        for line in (output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    step3_rows = [
        json.loads(line)
        for line in (output_dir / "synthetic_samples_step3_ready.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert gate_report["message_gate_enabled"] is True
    assert gate_report["message_gate_source"] == "formal_thresholds_with_optional_reference"
    assert gate_report["run_purpose"] == "formal"
    assert gate_report["run_valid_for_paper"] is True
    assert gate_report["sampled_candidate_count"] == len(synthetic_rows)
    assert gate_report["step3_ready_count"] == len(step3_rows)
    assert gate_report["target_gate_passed"] == (len(step3_rows) >= 1)
    assert gate_report["fewshot_pool_total_examples"] == 3
    assert gate_report["fewshot_pool_verified_examples"] == 3
    assert gate_report["fewshot_pool_formal_ready"] is True
    assert gate_report["diff_evidence_policy"] == MOD.DIFF_EVIDENCE_POLICY
    assert gate_report["diff_evidence_card_version"] == MOD.DIFF_EVIDENCE_CARD_VERSION


def test_parse_args_debug_allow_skip_stage_marks_non_paper(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "debug_skip_source.csv"
    fewshot_db = tmp_path / "debug_skip_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(config_path),
            "--skip-message-stage",
            "--disable-message-gate",
            "--debug-allow-skip-message-stage",
        ],
    )
    args = MOD.parse_args()
    assert args.run_purpose == "debug"
    assert args.run_valid_for_paper is False
    assert "debug_override_used" in args.protocol_violations


def test_parse_args_debug_allow_disable_gate_marks_non_paper(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "debug_gate_source.csv"
    fewshot_db = tmp_path / "debug_gate_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(config_path),
            "--disable-message-gate",
            "--debug-allow-disable-message-gate",
        ],
    )
    args = MOD.parse_args()
    assert args.run_purpose == "debug"
    assert args.run_valid_for_paper is False
    assert "debug_override_used" in args.protocol_violations


def test_parse_args_formal_runtime_is_paper_valid(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "formal_source.csv"
    fewshot_db = tmp_path / "formal_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db, run_purpose="formal")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.run_purpose == "formal"
    assert args.run_valid_for_paper is True
    assert args.protocol_violations == []


def test_parse_args_config_key_overrides_cli_and_env(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "config_priority_source.csv"
    fewshot_db = tmp_path / "config_priority_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(
        tmp_path,
        source_csv,
        fewshot_db,
        run_purpose="formal",
        deepseek_api_key="config-test-key",
    )
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--config",
            str(config_path),
            "--deepseek-api-key",
            "cli-test-key",
        ],
    )
    args = MOD.parse_args()
    assert args._resolved_deepseek_api_key == "config-test-key"
    assert args._deepseek_api_key_source == "config"


def test_parse_args_api_smoke_is_non_paper(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "smoke_source.csv"
    fewshot_db = tmp_path / "smoke_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = tmp_path / "step2_api_smoke_config.json"
    payload = json.loads(make_runtime_config(tmp_path, source_csv, fewshot_db).read_text(encoding="utf-8"))
    payload["run_purpose"] = "api_smoke"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.run_purpose == "api_smoke"
    assert args.run_valid_for_paper is False
    assert "api_smoke_non_paper_run" in args.protocol_violations


def test_parse_args_infers_api_smoke_from_config_filename(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "smoke_infer_source.csv"
    fewshot_db = tmp_path / "smoke_infer_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = tmp_path / "step2_api_smoke_config.json"
    payload = json.loads(make_runtime_config(tmp_path, source_csv, fewshot_db).read_text(encoding="utf-8"))
    payload.pop("run_purpose", None)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.run_purpose == "api_smoke"
    assert args.run_purpose_source == "config_name_contains_smoke"
    assert args.run_valid_for_paper is False
    assert "api_smoke_non_paper_run" in args.protocol_violations


def test_parse_args_api_smoke_without_key_fails(monkeypatch, tmp_path: Path, capsys):
    source_csv = tmp_path / "smoke_no_key_source.csv"
    fewshot_db = tmp_path / "smoke_no_key_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = tmp_path / "step2_api_smoke_config.json"
    payload = json.loads(make_runtime_config(tmp_path, source_csv, fewshot_db).read_text(encoding="utf-8"))
    payload["run_purpose"] = "api_smoke"
    payload["deepseek_api_key"] = ""
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    with pytest.raises(SystemExit):
        MOD.parse_args()
    assert (
        "Formal message generation requires config.deepseek_api_key, --deepseek-api-key, or DEEPSEEK_API_KEY."
        in capsys.readouterr().err
    )


def test_parse_args_preflight_sets_non_paper(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "preflight_source_parse.csv"
    fewshot_db = tmp_path / "preflight_fewshot_parse.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path), "--preflight"])
    args = MOD.parse_args()
    assert args.run_purpose == "preflight"
    assert args.run_valid_for_paper is False


def test_parse_args_preflight_defaults_use_datasets_bridge_layout(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "step2_runtime_config.json"
    config_path.write_text(json.dumps({"output_dir": str(tmp_path / "out")}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path), "--preflight"])
    args = MOD.parse_args()
    assert args.source_csv == "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv"
    assert (
        args.source_manifest_path
        == "../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json"
    )


def test_repo_runtime_configs_default_to_formal_ready_fewshot_assets() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    expected_db = "../../datasets/step2/delivery/current/fewshot_pool.db"
    expected_manifest = "../../datasets/step2/delivery/current/build_manifest.json"
    for name in [
        "step2_runtime_config.json",
        "step2_from_step1_source_config.json",
        "step2_api_smoke_config.json",
    ]:
        payload = json.loads((config_dir / name).read_text(encoding="utf-8"))
        assert payload["fewshot_db"] == expected_db
        assert payload["fewshot_build_manifest_path"] == expected_manifest


def test_repo_runtime_configs_use_reasoning_safe_output_budget() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    for name in [
        "step2_runtime_config.json",
        "step2_runtime_config.template.json",
        "step2_from_step1_source_config.json",
        "step2_api_smoke_config.json",
    ]:
        payload = json.loads((config_dir / name).read_text(encoding="utf-8"))
        assert payload["max_output_tokens"] >= 128


def test_repo_runtime_configs_use_v4_pro_with_disabled_thinking() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    for name in [
        "step2_runtime_config.json",
        "step2_runtime_config.template.json",
        "step2_from_step1_source_config.json",
        "step2_api_smoke_config.json",
    ]:
        payload = json.loads((config_dir / name).read_text(encoding="utf-8"))
        assert payload["generator_model"] == "deepseek-v4-pro"
        assert payload["generator_thinking_type"] == "disabled"


def test_debug_mock_generator_flag_bypasses_api_key_validation(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "mock_parse_source.csv"
    fewshot_db = tmp_path / "mock_parse_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db, deepseek_api_key="")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path), "--debug-mock-generator"])
    args = MOD.parse_args()
    assert args.generator_mode == "mock"
    assert args.run_purpose == "debug"
    assert args.run_valid_for_paper is False


def test_parse_args_prefers_local_runtime_config_when_present(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "local_default_source.csv"
    fewshot_db = tmp_path / "local_default_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    base_payload = json.loads(make_runtime_config(tmp_path, source_csv, fewshot_db).read_text(encoding="utf-8"))
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    default_config_path = configs_dir / "step2_runtime_config.json"
    local_config_path = configs_dir / "step2_runtime_config.local.json"

    default_payload = dict(base_payload)
    default_payload["deepseek_api_key"] = "default-config-key"
    default_payload["output_dir"] = str(tmp_path / "default_out")
    default_config_path.write_text(json.dumps(default_payload), encoding="utf-8")

    local_payload = dict(base_payload)
    local_payload["deepseek_api_key"] = "local-config-key"
    local_payload["output_dir"] = str(tmp_path / "local_out")
    local_config_path.write_text(json.dumps(local_payload), encoding="utf-8")

    install_fake_bertscore_module(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog"])
    args = MOD.parse_args()
    assert args.config == "configs/step2_runtime_config.local.json"
    assert args._resolved_deepseek_api_key == "local-config-key"
    assert args._deepseek_api_key_source == "config"


def test_parse_args_defaults_reasoning_safe_output_budget(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "default_output_budget_source.csv"
    fewshot_db = tmp_path / "default_output_budget_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload.pop("max_output_tokens", None)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.max_output_tokens == 128


def test_parse_args_defaults_to_v4_pro_with_disabled_thinking(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "default_generator_source.csv"
    fewshot_db = tmp_path / "default_generator_fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(fewshot_db, make_fewshot_rows())
    config_path = make_runtime_config(tmp_path, source_csv, fewshot_db)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload.pop("generator_model", None)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    install_fake_bertscore_module(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    monkeypatch.setattr(sys, "argv", ["prog", "--config", str(config_path)])
    args = MOD.parse_args()
    assert args.generator_model == "deepseek-v4-pro"
    assert args.generator_thinking_type == "disabled"


def test_compute_message_metrics_separates_generation_failures_from_quality():
    samples = [
        {
            "precheck_status": "skip",
            "precheck_skip_reason": "case1",
            "precheck_warning_reasons": [],
            "pair_quality_weight": 1.0,
            "generation_status": "not_attempted_precheck_skip",
            "message_status": "not_generated_precheck_skip",
            "few_shot_source": "failed",
            "synthetic_subject": "",
            "message_scores": {"format": 0, "bertscore_compute_invalid": 0, "message_quality_weight": 0.0},
            "message_meta": {"llm_generation_attempted": False, "generation_skipped": True, "generation_failure_reason": "source_pair_precheck_skip"},
        },
        {
            "precheck_status": "skip",
            "precheck_skip_reason": "case2",
            "precheck_warning_reasons": [],
            "pair_quality_weight": 1.0,
            "generation_status": "not_attempted_precheck_skip",
            "message_status": "not_generated_precheck_skip",
            "few_shot_source": "failed",
            "synthetic_subject": "",
            "message_scores": {"format": 0, "bertscore_compute_invalid": 0, "message_quality_weight": 0.0},
            "message_meta": {"llm_generation_attempted": False, "generation_skipped": True, "generation_failure_reason": "source_pair_precheck_skip"},
        },
        {
            "precheck_status": "pass",
            "precheck_skip_reason": "",
            "precheck_warning_reasons": [],
            "pair_quality_weight": 1.0,
            "generation_status": "generation_failed",
            "message_status": "not_generated_generation_failed",
            "few_shot_source": "failed",
            "synthetic_subject": "",
            "message_scores": {"format": 0, "bertscore_compute_invalid": 0, "message_quality_weight": 0.0},
            "message_meta": {"llm_generation_attempted": True, "generation_skipped": False, "generation_failure_reason": "http_402"},
        },
    ]
    metrics = MOD.compute_message_metrics(samples)
    assert metrics["generation_attempted_count"] == 1
    assert metrics["generation_failure_rate_attempted"] == 1.0
    assert metrics["generated_scored_count"] == 0
    assert metrics["true_message_reject_rate"] == 0.0
    assert metrics["format_fail_rate"] == 0.0
    assert metrics["artifact_any_hit_rate"] == 0.0


def test_compute_message_metrics_counts_true_quality_reject():
    samples = [
        {
            "precheck_status": "pass",
            "precheck_skip_reason": "",
            "precheck_warning_reasons": [],
            "pair_quality_weight": 1.0,
            "generation_status": "generated",
            "message_status": "reject",
            "few_shot_source": "exact_kway",
            "synthetic_subject": "fix auth parser and add tests",
            "message_scores": {
                "format": 1,
                "bertscore_compute_invalid": 0,
                "message_quality_weight": 0.05,
                "coverage_min_r": 0.2,
                "coverage_balance": 0.8,
                "faithfulness_p": 0.3,
                "style_score": 1.0,
                "relevance_score": 1.0,
            },
            "message_meta": {"llm_generation_attempted": True, "generation_skipped": False, "generation_failure_reason": ""},
        }
    ]
    metrics = MOD.compute_message_metrics(samples)
    assert metrics["generated_scored_count"] == 1
    assert metrics["true_message_reject_count"] == 1
    assert metrics["true_message_reject_rate"] == 1.0


def test_message_gate_report_has_separate_infra_and_quality_metrics():
    metrics = {
        "message_pass_rate": 0.4,
        "true_message_reject_rate": 0.2,
        "avg_message_quality_weight_non_reject": 0.6,
        "few_shot_failed_rate": 0.05,
        "few_shot_generic_rate": 0.8,
        "precheck_skip_rate": 0.2,
        "generation_failure_rate_attempted": 0.1,
        "coverage_min_avg": 0.6,
        "coverage_min_p10": 0.4,
        "sampled_candidate_count": 10,
        "generated_scored_count": 5,
        "generation_attempted_count": 5,
        "precheck_skip_count": 2,
    }
    args = SimpleNamespace(
        enable_message_gate=True,
        gate_min_message_pass_rate=0.1,
        gate_max_message_reject_rate=0.9,
        gate_min_avg_message_quality_weight_non_reject=0.1,
        gate_max_fewshot_failure_rate=0.9,
        gate_max_precheck_skip_rate=1.0,
        gate_max_generation_failure_rate=0.9,
        gate_min_coverage_min_avg=0.1,
        gate_min_coverage_min_p10=0.1,
        few_shot_failed_rate_gate_threshold=0.2,
        few_shot_generic_rate_warn_threshold=0.5,
        reference_upper_quantile=0.95,
        reference_lower_quantile=0.05,
    )
    report = MOD.evaluate_message_gate(metrics, [], args)
    assert report["message_gate_passed"] is True
    assert "true_message_reject_rate" in report["gate_metrics"]
    assert "generation_failure_rate_attempted" in report["gate_metrics"]
    assert "gate_metric_denominators" in report
    assert report["warnings"]
    assert report["warnings"][0]["metric"] == "few_shot_generic_rate"


def test_generation_http_402_is_not_quality_reject(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "http402_source.csv"
    output_dir = tmp_path / "http402_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth token parse",
            "message": "fix auth token parse in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add auth tests",
            "message": "add tests for auth parser",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "retrieve_fewshot_examples",
        lambda **_kwargs: {
            "examples": [{"example_id": "e1", "type_pair": "fix+test", "subject": "fix parser and add tests"}],
            "few_shot_source": "exact_kway",
            "retrieval_backend": "sqlite_formal_kway_v2",
            "retrieval_result_count": 1,
            "retrieval_error": "",
            "retrieval_status": "exact",
            "few_shot_retrieval_log": {
                "requested_type_signature": "fix+test",
                "query_levels_attempted": [{"level": "exact_kway", "candidate_count": 1, "selected_count": 1}],
                "examples_found_per_level": {"exact_kway": 1},
                "selected_example_ids": ["e1"],
                "selected_example_type_signatures": ["fix+test"],
                "selected_example_repos": ["fewshot/repo1"],
                "retrieval_status": "exact",
                "failure_reason": "",
            },
        },
    )
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "",
            "generation_success": False,
            "message_error_type": "http_402",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req_http_402"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {"error": "insufficient balance"},
        },
    )
    result = MOD.run_single(args, enforce_gates=False)
    assert result["message_metrics"]["true_message_reject_count"] == 0
    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["generation_status"] == "generation_failed"
    assert sample["message_status"] == "not_generated_generation_failed"
    assert sample["message_meta"]["generation_failure_reason"] == "http_402"


def test_step3_ready_filter_requires_positive_weight_and_subject():
    bad = {
        "generation_status": "generated",
        "message_status": "fallback",
        "synthetic_subject": "fix and add tests",
        "final_sample_weight": 0.0,
        "precheck_status": "warn",
    }
    good = {
        "generation_status": "generated",
        "message_status": "pass",
        "synthetic_subject": "fix parser and add tests",
        "final_sample_weight": 0.7,
        "precheck_status": "pass",
    }
    failed = {
        "generation_status": "generation_failed",
        "message_status": "not_generated_generation_failed",
        "synthetic_subject": "",
        "final_sample_weight": 0.0,
        "precheck_status": "pass",
    }
    assert MOD.is_step3_ready_sample(bad) is False
    assert MOD.is_step3_ready_sample(good) is True
    assert MOD.is_step3_ready_sample(failed) is False


def test_run_metadata_redacts_cli_api_key(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "redact_source.csv"
    output_dir = tmp_path / "redact_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth token parse",
            "message": "fix auth token parse in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add auth tests",
            "message": "add tests for auth parser",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix auth parser and add tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "bertscore_pair",
        lambda *_args, **_kwargs: {
            "precision": 0.9,
            "recall": 0.9,
            "f1": 0.9,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": "cache",
        },
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--deepseek-api-key", "sk-xxx", "--config", str(args.config)])
    MOD.run_single(args, enforce_gates=False)
    metadata_text = (output_dir / "run_metadata.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert "sk-xxx" not in metadata_text
    assert "***REDACTED***" in json.dumps(metadata["argv"], ensure_ascii=False)


def test_api_smoke_run_marks_non_formal_ready_fewshot_pool(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "api_smoke_source.csv"
    output_dir = tmp_path / "api_smoke_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth token parse",
                "message": "fix auth token parse in middleware",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add tests for auth parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        run_purpose="api_smoke",
        formal_run=False,
        run_valid_for_paper=False,
        fewshot_min_total_examples=80,
        fewshot_min_examples_per_common_signature=3,
        fewshot_audit_strict_style=True,
    )
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "generate_subject_with_repair",
        lambda **_kwargs: {
            "synthetic_subject": "fix auth parser and add tests",
            "generation_success": True,
            "message_error_type": "ok",
            "generation_attempts": 1,
            "compress_attempts": 0,
            "rewrite_attempts": 0,
            "request_sha_chain": ["req1"],
            "generation_trace": [],
            "cache_hit_count": 0,
            "raw_response": {},
        },
    )
    monkeypatch.setattr(
        MOD,
        "bertscore_pair",
        lambda *_args, **_kwargs: {
            "precision": 0.9,
            "recall": 0.9,
            "f1": 0.9,
            "cached": False,
            "invalid": False,
            "error": "",
            "cache_key": "cache",
        },
    )
    MOD.run_single(args, enforce_gates=False)
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["run_purpose"] == "api_smoke"
    assert metadata["run_valid_for_paper"] is False
    assert metadata["fewshot_pool"]["fewshot_pool_formal_ready"] is False
    assert metadata["fewshot_pool"]["fewshot_pool_total_examples"] == 3
    assert metadata["fewshot_pool"]["fewshot_pool_verified_examples"] == 3
    blockers = metadata["fewshot_pool"]["fewshot_pool_audit"]["blockers"]
    assert any("fewshot_total_below_min" in item for item in blockers)
    assert any("fewshot_common_signature_coverage_insufficient" in item for item in blockers)
    gate_report = json.loads((output_dir / "message_gate_report.json").read_text(encoding="utf-8"))
    assert gate_report["run_purpose"] == "api_smoke"
    assert gate_report["run_valid_for_paper"] is False
    assert gate_report["fewshot_pool_formal_ready"] is False


def test_fewshot_excludes_same_repo_alias_and_source_sha(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_leak.db"
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "ex_same_repo_alias",
                "repo": "GitHub.com/Owner/Repo.git",
                "sha": "fs1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "quality_score": 0.9,
            },
            {
                "example_id": "ex_same_sha_other_repo",
                "repo": "other/repo",
                "sha": "source_sha_1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "quality_score": 0.9,
            },
            {
                "example_id": "ex_ok",
                "repo": "another/repo",
                "sha": "fs_ok",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "quality_score": 0.95,
            },
        ],
    )
    info = MOD.retrieve_fewshot_examples(
        db_path=str(fewshot_db),
        table="fewshot_examples",
        type_signature_canonical="fix+test",
        current_repo="owner/repo",
        k=2,
        seed=42,
        current_source_shas={"source_sha_1"},
    )
    selected_ids = set(info["few_shot_retrieval_log"]["selected_example_ids"])
    assert "ex_same_repo_alias" not in selected_ids
    assert "ex_same_sha_other_repo" not in selected_ids
    assert info["few_shot_retrieval_log"]["excluded_same_repo_count"] >= 1
    assert info["few_shot_retrieval_log"]["excluded_source_sha_count"] >= 1


def test_fewshot_min_examples_not_met_skips_generation(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "fewshot_min_source.csv"
    output_dir = tmp_path / "fewshot_min_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix auth token parse",
            "message": "fix auth token parse in middleware",
            "git_diff": make_diff("src/a.txt"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add auth tests",
            "message": "add tests for auth parser",
            "git_diff": make_diff("src/b.txt"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(tmp_path, source_csv, output_dir, few_shot_min_examples_per_sample=2, few_shot_k=2)
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: object())
    monkeypatch.setattr(
        MOD,
        "retrieve_fewshot_examples",
        lambda **_kwargs: {
            "examples": [{"example_id": "e1", "type_pair": "fix+test", "subject": "fix parser and add tests"}],
            "few_shot_source": "generic_fallback",
            "retrieval_backend": "sqlite_formal_kway_v2",
            "retrieval_result_count": 1,
            "retrieval_error": "",
            "retrieval_status": "partial",
            "few_shot_retrieval_log": {
                "requested_type_signature": "fix+test",
                "query_levels_attempted": [{"level": "generic_fallback", "candidate_count": 1, "selected_count": 1}],
                "examples_found_per_level": {"generic_fallback": 1},
                "selected_example_ids": ["e1"],
                "selected_example_type_signatures": ["fix+test"],
                "selected_example_repos": ["fewshot/repo1"],
                "retrieval_status": "partial",
                "failure_reason": "",
            },
        },
    )

    def should_not_call_generate(**_kwargs):
        raise AssertionError("LLM generation should not be called when few-shot min examples is not met.")

    monkeypatch.setattr(MOD, "generate_subject_with_repair", should_not_call_generate)
    MOD.run_single(args, enforce_gates=False)
    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    assert sample["generation_status"] == "generation_failed"
    assert sample["message_status"] == "not_generated_generation_failed"
    assert sample["message_meta"]["generation_failure_reason"] == "few_shot_min_examples_not_met"


def test_message_gate_fails_when_fewshot_failed_rate_too_high():
    metrics = {
        "message_pass_rate": 0.4,
        "true_message_reject_rate": 0.1,
        "avg_message_quality_weight_non_reject": 0.6,
        "few_shot_failed_rate": 0.7,
        "few_shot_generic_rate": 0.2,
        "precheck_skip_rate": 0.2,
        "generation_failure_rate_attempted": 0.1,
        "coverage_min_avg": 0.6,
        "coverage_min_p10": 0.4,
        "sampled_candidate_count": 10,
        "generated_scored_count": 5,
        "generation_attempted_count": 5,
        "precheck_skip_count": 2,
    }
    args = SimpleNamespace(
        enable_message_gate=True,
        gate_min_message_pass_rate=0.1,
        gate_max_message_reject_rate=0.9,
        gate_min_avg_message_quality_weight_non_reject=0.1,
        gate_max_fewshot_failure_rate=1.0,
        gate_max_precheck_skip_rate=1.0,
        gate_max_generation_failure_rate=1.0,
        gate_min_coverage_min_avg=0.1,
        gate_min_coverage_min_p10=0.1,
        few_shot_failed_rate_gate_threshold=0.2,
        few_shot_generic_rate_warn_threshold=0.9,
        reference_upper_quantile=0.95,
        reference_lower_quantile=0.05,
    )
    report = MOD.evaluate_message_gate(metrics, [], args)
    assert report["message_gate_passed"] is False
    assert "few_shot_failed_rate" in report["failed_metrics"]


def test_fewshot_audit_cli_passes_for_formal_ready_pool(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_cli_pass.db"
    rows = []
    for sig_idx, signature in enumerate(MOD.DEFAULT_FEWSHOT_COMMON_SIGNATURES, start=1):
        for replica in range(3):
            row_id = f"{sig_idx}_{replica}"
            rows.append(
                {
                    "example_id": f"ex_{row_id}",
                    "repo": f"fewshot/repo{sig_idx}_{replica}",
                    "sha": f"fs_{row_id}",
                    "type_pair": signature,
                    "type_signature_raw": signature,
                    "type_signature_canonical": signature,
                    "intent_k": 2,
                    "subject": f"improve {signature.replace('+', ' and ')} flow {replica}",
                    "split": "train",
                    "verified_multi_intent": 1,
                    "fewshot_eligible": 1,
                    "quality_score": 0.95,
                }
            )
    write_fewshot_db(fewshot_db, rows)
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_fewshot_pool.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--db",
            str(fewshot_db),
            "--min-total",
            "27",
            "--min-per-common-signature",
            "3",
            "--probe-type-signature",
            "fix+test",
            "--probe-k",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["passed"] is True
    assert payload["audit"]["audit_pass"] is True
    assert payload["retrieval_probe"]["retrieval_result_count"] == 1
    assert payload["db_path"] == str(fewshot_db)


def test_fewshot_audit_cli_fails_for_preview_like_pool(tmp_path: Path):
    fewshot_db = tmp_path / "fewshot_cli_fail.db"
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "ex_bad",
                "repo": "fewshot/repo1",
                "sha": "fs_bad",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "test: add tests and fix(parser): handle empty token",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        ],
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_fewshot_pool.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--db",
            str(fewshot_db),
            "--min-total",
            "1",
            "--min-per-common-signature",
            "1",
            "--probe-type-signature",
            "fix+test",
            "--probe-k",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["passed"] is False
    assert payload["audit"]["audit_pass"] is False
    assert any("fewshot_bad_style_detected" in blocker for blocker in payload["audit"]["blockers"])
    assert payload["retrieval_probe"]["retrieval_result_count"] == 0


def test_split_leakage_audit_cli_passes_when_only_source_fewshot_repo_overlap(tmp_path: Path):
    source_csv = tmp_path / "source.csv"
    eval_csv = tmp_path / "step3_eval.csv"
    fewshot_db = tmp_path / "fewshot.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo_a",
                "sha": "src_sha_1",
                "type": "fix",
                "subject": "fix parser bug",
                "message": "fix parser bug in auth flow",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo_b",
                "sha": "src_sha_2",
                "type": "test",
                "subject": "add parser tests",
                "message": "add parser tests",
                "git_diff": make_diff("tests/a.txt"),
                "manual_label": "A",
            },
        ],
    )
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "fs1",
                "repo": "owner/repo_a",
                "sha": "few_sha_1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser bug and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            },
            {
                "example_id": "fs2",
                "repo": "owner/repo_c",
                "sha": "few_sha_2",
                "type_pair": "feat+docs",
                "type_signature_raw": "feat+docs",
                "type_signature_canonical": "feat+docs",
                "intent_k": 2,
                "subject": "add export flag and update docs",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            },
        ],
    )
    write_repo_sha_csv(
        eval_csv,
        [
            {"repo": "owner/repo_eval_1", "sha": "eval_sha_1"},
            {"repo": "owner/repo_eval_2", "sha": "eval_sha_2"},
        ],
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_split_leakage.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--step2-source-csv",
            str(source_csv),
            "--fewshot-db",
            str(fewshot_db),
            "--step3-eval",
            f"test={eval_csv}",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["passed"] is True
    assert payload["checks"]["source_vs_fewshot"]["repo_overlap_count"] == 1
    assert payload["checks"]["source_vs_fewshot"]["sha_overlap_count"] == 0
    assert payload["checks"]["source_vs_test"]["repo_policy"] == "fail"
    assert payload["checks"]["source_vs_test"]["repo_overlap_count"] == 0
    assert payload["checks"]["fewshot_vs_test"]["sha_overlap_count"] == 0


def test_split_leakage_audit_cli_fails_on_eval_overlap(tmp_path: Path):
    source_csv = tmp_path / "source_fail.csv"
    eval_csv = tmp_path / "step3_eval_fail.csv"
    fewshot_db = tmp_path / "fewshot_fail.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo_a",
                "sha": "src_sha_1",
                "type": "fix",
                "subject": "fix parser bug",
                "message": "fix parser bug in auth flow",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            }
        ],
    )
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "fs1",
                "repo": "owner/repo_b",
                "sha": "few_sha_1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser bug and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        ],
    )
    write_repo_sha_csv(
        eval_csv,
        [
            {"repo": "owner/repo_a", "sha": "eval_sha_1"},
            {"repo": "owner/repo_eval_2", "sha": "few_sha_1"},
        ],
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_split_leakage.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--step2-source-csv",
            str(source_csv),
            "--fewshot-db",
            str(fewshot_db),
            "--step3-eval",
            f"test={eval_csv}",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["passed"] is False
    assert payload["checks"]["source_vs_test"]["repo_overlap_count"] == 1
    assert payload["checks"]["fewshot_vs_test"]["sha_overlap_count"] == 1
    assert any("repo_overlap_detected" in item for item in payload["checks"]["source_vs_test"]["errors"])
    assert any("sha_overlap_detected" in item for item in payload["checks"]["fewshot_vs_test"]["errors"])


def test_split_leakage_audit_cli_writes_report_json(tmp_path: Path):
    source_csv = tmp_path / "source_report.csv"
    eval_csv = tmp_path / "step3_eval_report.csv"
    fewshot_db = tmp_path / "fewshot_report.db"
    report_path = tmp_path / "leakage_report.json"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo_a",
                "sha": "src_sha_1",
                "type": "fix",
                "subject": "fix parser bug",
                "message": "fix parser bug in auth flow",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            }
        ],
    )
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "fs1",
                "repo": "owner/repo_b",
                "sha": "few_sha_1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser bug and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        ],
    )
    write_repo_sha_csv(
        eval_csv,
        [
            {"repo": "owner/repo_eval_1", "sha": "eval_sha_1"},
        ],
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_split_leakage.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--step2-source-csv",
            str(source_csv),
            "--fewshot-db",
            str(fewshot_db),
            "--step3-eval",
            f"test={eval_csv}",
            "--report-json",
            str(report_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert report_path.exists()
    stdout_payload = json.loads(proc.stdout)
    file_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert stdout_payload == file_payload
    assert file_payload["passed"] is True


def test_run_registry_cli_summarizes_runs(tmp_path: Path):
    run_root = tmp_path / "outputs"
    formal_dir = run_root / "formal_run"
    smoke_dir = run_root / "smoke_run"
    formal_dir.mkdir(parents=True)
    smoke_dir.mkdir(parents=True)

    (formal_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "run_valid_for_paper": True,
                "formal_run": True,
                "fewshot_pool": {
                    "fewshot_pool_formal_ready": True,
                    "fewshot_pool_total_examples": 120,
                },
                "formal_assets": {
                    "formal_assets_ready": True,
                },
                "outputs": {
                    "step3_ready_jsonl": str(formal_dir / "synthetic_samples_step3_ready.jsonl"),
                },
                "run_stats": {
                    "step3_ready_count": 42,
                },
            }
        ),
        encoding="utf-8",
    )
    (formal_dir / "message_gate_report.json").write_text(
        json.dumps({"message_gate_passed": True}),
        encoding="utf-8",
    )
    (formal_dir / "synthetic_samples_step3_ready.jsonl").write_text("{\"id\": 1}\n", encoding="utf-8")

    (smoke_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "api_smoke",
                "run_valid_for_paper": False,
                "formal_run": False,
                "fewshot_pool": {
                    "fewshot_pool_formal_ready": False,
                    "fewshot_pool_total_examples": 5,
                },
                "formal_assets": {
                    "formal_assets_ready": False,
                },
                "outputs": {
                    "step3_ready_jsonl": str(smoke_dir / "synthetic_samples_step3_ready.jsonl"),
                },
                "run_stats": {
                    "step3_ready_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    (smoke_dir / "message_gate_report.json").write_text(
        json.dumps({"message_gate_passed": False}),
        encoding="utf-8",
    )
    (smoke_dir / "synthetic_samples_step3_ready.jsonl").write_text("{\"id\": 1}\n", encoding="utf-8")

    cli_path = Path(__file__).resolve().parents[1] / "code" / "run_registry.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--outputs-root",
            str(run_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["run_count"] == 2
    runs = {row["run_dir_name"]: row for row in payload["runs"]}
    assert runs["formal_run"]["paper_valid_candidate"] is True
    assert runs["formal_run"]["message_gate_passed"] is True
    assert runs["formal_run"]["fewshot_pool_formal_ready"] is True
    assert runs["formal_run"]["formal_assets_ready"] is True
    assert runs["smoke_run"]["paper_valid_candidate"] is False
    assert runs["smoke_run"]["run_purpose"] == "api_smoke"


def test_run_registry_cli_handles_missing_gate_report(tmp_path: Path):
    run_root = tmp_path / "outputs_missing_gate"
    run_dir = run_root / "formal_missing_gate"
    run_dir.mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "run_valid_for_paper": True,
                "formal_run": True,
                "fewshot_pool": {
                    "fewshot_pool_formal_ready": True,
                    "fewshot_pool_total_examples": 100,
                },
                "formal_assets": {
                    "formal_assets_ready": False,
                },
                "outputs": {
                    "step3_ready_jsonl": str(run_dir / "synthetic_samples_step3_ready.jsonl"),
                },
                "run_stats": {
                    "step3_ready_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "run_registry.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--outputs-root",
            str(run_root),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["run_count"] == 1
    row = payload["runs"][0]
    assert row["run_dir_name"] == "formal_missing_gate"
    assert row["message_gate_report_present"] is False
    assert row["message_gate_passed"] is None
    assert row["formal_assets_ready"] is False
    assert row["paper_valid_candidate"] is False


def test_run_registry_cli_writes_csv(tmp_path: Path):
    run_root = tmp_path / "outputs_csv"
    run_dir = run_root / "formal_csv_run"
    csv_out = tmp_path / "run_registry.csv"
    run_dir.mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "run_purpose": "formal",
                "run_valid_for_paper": True,
                "formal_run": True,
                "fewshot_pool": {
                    "fewshot_pool_formal_ready": True,
                    "fewshot_pool_total_examples": 88,
                },
                "formal_assets": {
                    "formal_assets_ready": True,
                },
                "outputs": {
                    "step3_ready_jsonl": str(run_dir / "synthetic_samples_step3_ready.jsonl"),
                },
                "run_stats": {
                    "step3_ready_count": 9,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "message_gate_report.json").write_text(
        json.dumps({"message_gate_passed": True}),
        encoding="utf-8",
    )
    (run_dir / "synthetic_samples_step3_ready.jsonl").write_text("{\"id\": 1}\n", encoding="utf-8")
    cli_path = Path(__file__).resolve().parents[1] / "code" / "run_registry.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--outputs-root",
            str(run_root),
            "--csv-out",
            str(csv_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert csv_out.exists()
    rows = list(csv.DictReader(csv_out.open("r", encoding="utf-8", newline="")))
    assert len(rows) == 1
    row = rows[0]
    assert row["run_dir_name"] == "formal_csv_run"
    assert row["run_purpose"] == "formal"
    assert row["paper_valid_candidate"] == "True"
    assert row["formal_assets_ready"] == "True"
    assert row["step3_ready_count"] == "9"


def test_split_leakage_audit_cli_emits_appendix_summary(tmp_path: Path):
    source_csv = tmp_path / "source_appendix.csv"
    dev_csv = tmp_path / "step3_dev.csv"
    test_csv = tmp_path / "step3_test.csv"
    fewshot_db = tmp_path / "fewshot_appendix.db"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo_a",
                "sha": "src_sha_1",
                "type": "fix",
                "subject": "fix parser bug",
                "message": "fix parser bug in auth flow",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            }
        ],
    )
    write_fewshot_db(
        fewshot_db,
        [
            {
                "example_id": "fs1",
                "repo": "owner/repo_dev",
                "sha": "few_sha_1",
                "type_pair": "fix+test",
                "type_signature_raw": "fix+test",
                "type_signature_canonical": "fix+test",
                "intent_k": 2,
                "subject": "fix parser bug and add tests",
                "split": "train",
                "verified_multi_intent": 1,
                "fewshot_eligible": 1,
                "quality_score": 0.9,
            }
        ],
    )
    write_repo_sha_csv(
        dev_csv,
        [
            {"repo": "owner/repo_dev", "sha": "dev_sha_1"},
        ],
    )
    write_repo_sha_csv(
        test_csv,
        [
            {"repo": "owner/repo_test", "sha": "src_sha_1"},
        ],
    )
    cli_path = Path(__file__).resolve().parents[1] / "code" / "audit_split_leakage.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "--step2-source-csv",
            str(source_csv),
            "--fewshot-db",
            str(fewshot_db),
            "--step3-eval",
            f"dev={dev_csv}",
            "--step3-eval",
            f"test={test_csv}",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    appendix = payload["appendix_summary"]
    assert appendix["eval_split_count"] == 2
    assert appendix["failed_pair_count"] >= 1
    assert appendix["warning_pair_count"] >= 0
    assert appendix["overall_eval_repo_overlap_count"] == 1
    assert appendix["overall_eval_sha_overlap_count"] == 1
    assert "fewshot_vs_dev" in appendix["failed_pairs"] or "source_vs_test" in appendix["failed_pairs"]


def test_selected_pairs_plan_roundtrip_and_run_single_uses_sample_id_offset(tmp_path: Path) -> None:
    source_csv = tmp_path / "selected_pairs_source.csv"
    output_dir = tmp_path / "selected_pairs_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "fix parser bug in auth path",
            "git_diff": make_diff("src/auth.py"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser tests",
            "message": "add parser tests for auth path",
            "git_diff": make_diff("tests/auth_test.py"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha3",
            "type": "refactor",
            "subject": "refactor parser helpers",
            "message": "refactor parser helpers in auth path",
            "git_diff": make_diff("src/parser.py"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    source_rows = MOD.load_csv(source_csv)
    pool, _ = MOD.build_source_pool_from_minimal(source_rows, manual_label="A")
    pool_by_sha = {row["sha"]: row for row in pool}
    selected_pair = {
        "repo": "owner/repo",
        "members": [pool_by_sha["sha1"], pool_by_sha["sha3"]],
        "type_pair": "fix+refactor",
        "type_signature_raw": "fix+refactor",
        "type_signature_canonical": "fix+refactor",
        "different_type": True,
        "module_overlap": True,
        "merged_files": 2,
        "merged_lines": 2,
        "shared_files": [],
        "precheck_status": "pass",
        "precheck_skip_reason": "",
        "precheck_warning_reasons": [],
        "pair_quality_weight": 1.0,
        "min_pair_quality_weight": 1.0,
        "precheck_scores": {
            "merge": 1.0,
            "semantic": 1.0,
            "type_compatibility": 1.0,
            "non_duplicate": 1.0,
            "relation": 1.0,
            "input_message": 1.0,
        },
        "precheck_meta": {
            "precheck_version": MOD.SOURCE_PAIR_PRECHECK_VERSION,
            "rules_triggered": [],
            "generation_allowed": True,
            "semantic_check_mode": "rule_only",
            "git_check_method": "not_available",
        },
        "pair_precheck_results": [],
    }
    plan_path = tmp_path / "selected_pairs.jsonl"
    MOD.write_selected_pairs_plan_jsonl(plan_path, [selected_pair])
    records = MOD.load_selected_pairs_plan_jsonl(plan_path)
    rebuilt = MOD.materialize_selected_pairs_from_plan_records(records, pool)
    assert [member["sha"] for member in rebuilt[0]["members"]] == ["sha1", "sha3"]

    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        skip_message_stage=True,
        message_stage_enabled=False,
        enable_message_gate=False,
        message_gate_enabled=False,
        fewshot_enabled=False,
        require_fewshot_pool=False,
        run_purpose="debug",
        run_purpose_source="test_fixture",
        formal_run=False,
        run_valid_for_paper=False,
        selected_pairs_jsonl=str(plan_path),
        selected_pairs_manifest="",
        sample_id_offset=40,
    )

    MOD.run_single(args, enforce_gates=False)

    sample = json.loads((output_dir / "synthetic_samples.jsonl").read_text(encoding="utf-8").strip())
    metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))

    assert sample["sample_id"] == "simple2_0041"
    assert [source["sha"] for source in sample["sources"]] == ["sha1", "sha3"]
    assert metadata["inputs"]["selected_pairs_jsonl"] == str(plan_path)
    assert metadata["resolved_config"]["sample_id_offset"] == 40


def test_run_single_ignores_broken_pipe_from_progress_print(monkeypatch, tmp_path: Path) -> None:
    source_csv = tmp_path / "broken_pipe_source.csv"
    output_dir = tmp_path / "broken_pipe_out"
    rows = [
        {
            "repo": "owner/repo",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "fix parser bug in auth path",
            "git_diff": make_diff("src/auth.py"),
            "manual_label": "A",
        },
        {
            "repo": "owner/repo",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser tests",
            "message": "add parser tests for auth path",
            "git_diff": make_diff("tests/auth_test.py"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    args = make_args(
        tmp_path,
        source_csv,
        output_dir,
        skip_message_stage=True,
        message_stage_enabled=False,
        enable_message_gate=False,
        message_gate_enabled=False,
        fewshot_enabled=False,
        require_fewshot_pool=False,
        run_purpose="debug",
        run_purpose_source="test_fixture",
        formal_run=False,
        run_valid_for_paper=False,
        progress_flush_every=1,
    )

    original_print = builtins.print

    def fake_print(*args, **kwargs):
        text = "".join(str(arg) for arg in args)
        if "[progress]" in text:
            raise BrokenPipeError("stdout closed")
        return original_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", fake_print)

    result = MOD.run_single(args, enforce_gates=False)

    assert result["generated_count"] == 1
    assert (output_dir / "run_progress.json").exists()
    assert (output_dir / "run_metadata.json").exists()

def test_prepare_run_context_reuses_fewshot_and_source_pool(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "prepared_ctx_source.csv"
    output_dir = tmp_path / "prepared_ctx_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(tmp_path, source_csv, output_dir)

    calls = {
        "resolve_fewshot_pool_or_fail": 0,
        "load_fewshot_pool_rows": 0,
        "load_csv": 0,
        "build_source_pool_from_minimal": 0,
        "compute_length_limit_stats": 0,
        "summarize_subject_distribution": 0,
        "collect_formal_asset_status": 0,
        "audit_fewshot_pool": 0,
        "init_bertscorer": 0,
    }

    monkeypatch.setattr(
        MOD,
        "resolve_fewshot_pool_or_fail",
        lambda _args, _output_dir: calls.__setitem__("resolve_fewshot_pool_or_fail", calls["resolve_fewshot_pool_or_fail"] + 1) or (tmp_path / "fewshot.db", {"resolved_db": str(tmp_path / "fewshot.db")}),
    )
    monkeypatch.setattr(
        MOD,
        "load_fewshot_pool_rows",
        lambda _db, _table: calls.__setitem__("load_fewshot_pool_rows", calls["load_fewshot_pool_rows"] + 1) or [{"example_id": "e1"}],
    )
    monkeypatch.setattr(
        MOD,
        "audit_fewshot_pool",
        lambda *_args, **_kwargs: calls.__setitem__("audit_fewshot_pool", calls["audit_fewshot_pool"] + 1) or {"audit_pass": True, "total_examples": 1, "verified_examples": 1},
    )
    monkeypatch.setattr(
        MOD,
        "collect_formal_asset_status",
        lambda *_args, **_kwargs: calls.__setitem__("collect_formal_asset_status", calls["collect_formal_asset_status"] + 1) or {"formal_assets_ready": True, "blockers": []},
    )
    monkeypatch.setattr(
        MOD,
        "load_csv",
        lambda _path: calls.__setitem__("load_csv", calls["load_csv"] + 1) or [{"repo": "owner/repo", "sha": "sha1"}, {"repo": "owner/repo", "sha": "sha2"}],
    )
    monkeypatch.setattr(
        MOD,
        "build_source_pool_from_minimal",
        lambda _rows, manual_label: calls.__setitem__("build_source_pool_from_minimal", calls["build_source_pool_from_minimal"] + 1) or ([{"sha": "sha1", "repo": "owner/repo", "type": "fix", "subject": "fix auth bug", "commit_message": "fix auth bug"}, {"sha": "sha2", "repo": "owner/repo", "type": "test", "subject": "add auth tests", "commit_message": "add auth tests"}], {"a_tier_rows": 2, "repo_count": 1, "type_count": 2}),
    )
    monkeypatch.setattr(
        MOD,
        "compute_length_limit_stats",
        lambda _pool: calls.__setitem__("compute_length_limit_stats", calls["compute_length_limit_stats"] + 1) or {"p90": 62, "p95": 70, "source": "test", "policy": "test"},
    )
    monkeypatch.setattr(
        MOD,
        "summarize_subject_distribution",
        lambda _subjects: calls.__setitem__("summarize_subject_distribution", calls["summarize_subject_distribution"] + 1) or {"p50": 10},
    )
    monkeypatch.setattr(
        MOD,
        "init_bertscorer",
        lambda _args: calls.__setitem__("init_bertscorer", calls["init_bertscorer"] + 1) or object(),
    )

    context = MOD.prepare_run_context(args)

    assert context["pool_stats"]["a_tier_rows"] == 2
    assert context["length_limit_stats"]["p90"] == 62
    assert calls == {
        "resolve_fewshot_pool_or_fail": 1,
        "load_fewshot_pool_rows": 1,
        "load_csv": 1,
        "build_source_pool_from_minimal": 1,
        "compute_length_limit_stats": 1,
        "summarize_subject_distribution": 1,
        "collect_formal_asset_status": 1,
        "audit_fewshot_pool": 1,
        "init_bertscorer": 1,
    }


def test_run_single_uses_prepared_context_without_reinitializing(monkeypatch, tmp_path: Path):
    source_csv = tmp_path / "prepared_ctx_run_single.csv"
    output_dir = tmp_path / "prepared_ctx_run_single_out"
    write_minimal_csv(
        source_csv,
        [
            {
                "repo": "owner/repo",
                "sha": "sha1",
                "type": "fix",
                "subject": "fix auth bug",
                "message": "fix auth bug in parser",
                "git_diff": make_diff("src/a.txt"),
                "manual_label": "A",
            },
            {
                "repo": "owner/repo",
                "sha": "sha2",
                "type": "test",
                "subject": "add auth tests",
                "message": "add auth tests for parser",
                "git_diff": make_diff("src/b.txt"),
                "manual_label": "A",
            },
        ],
    )
    args = make_args(tmp_path, source_csv, output_dir, message_stage_enabled=False, skip_message_stage=True)

    prepared_context = {
        "fewshot_pool_resolution": {"source": "message_stage_skipped", "built_default_pool": False},
        "fewshot_pool_audit": {},
        "fewshot_pool_total_examples": 0,
        "fewshot_pool_verified_examples": 0,
        "fewshot_pool_formal_ready": False,
        "formal_assets": {"formal_assets_ready": True},
        "source_fingerprint": {"sha256": "src"},
        "config_fingerprint": None,
        "script_fingerprint": {"sha256": "script"},
        "source_rows": [
            {"repo": "owner/repo", "sha": "sha1", "type": "fix", "subject": "fix auth bug", "message": "fix auth bug in parser", "git_diff": make_diff("src/a.txt"), "manual_label": "A"},
            {"repo": "owner/repo", "sha": "sha2", "type": "test", "subject": "add auth tests", "message": "add auth tests for parser", "git_diff": make_diff("src/b.txt"), "manual_label": "A"},
        ],
        "pool": [
            {"sha": "sha1", "repo": "owner/repo", "type": "fix", "subject": "fix auth bug", "commit_message": "fix auth bug in parser", "file_path_set": {"src/a.txt"}, "module_set": {"src"}, "changed_lines": 2, "blocks": [{"file_path": "src/a.txt", "text": make_diff("src/a.txt")}], "git_diff": make_diff("src/a.txt"), "manual_label": "A"},
            {"sha": "sha2", "repo": "owner/repo", "type": "test", "subject": "add auth tests", "commit_message": "add auth tests for parser", "file_path_set": {"src/b.txt"}, "module_set": {"src"}, "changed_lines": 2, "blocks": [{"file_path": "src/b.txt", "text": make_diff("src/b.txt")}], "git_diff": make_diff("src/b.txt"), "manual_label": "A"},
        ],
        "pool_stats": {"a_tier_rows": 2, "repo_count": 1, "type_count": 2},
        "a_tier_fingerprint": {"sha256": "pool"},
        "length_limit_stats": {"p90": 62, "p95": 70, "source": "test", "policy": "test"},
        "real_subject_distribution": {"p50": 10},
        "bertscorer": None,
    }

    monkeypatch.setattr(MOD, "load_csv", lambda _path: (_ for _ in ()).throw(AssertionError("load_csv should not be called")))
    monkeypatch.setattr(MOD, "build_source_pool_from_minimal", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build_source_pool_from_minimal should not be called")))
    monkeypatch.setattr(MOD, "resolve_fewshot_pool_or_fail", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("resolve_fewshot_pool_or_fail should not be called")))
    monkeypatch.setattr(MOD, "init_bertscorer", lambda _args: (_ for _ in ()).throw(AssertionError("init_bertscorer should not be called")))

    result = MOD.run_single(args, enforce_gates=False, prepared_context=prepared_context)

    assert result["generated_count"] == 1
    assert result["step3_ready_count"] == 1
