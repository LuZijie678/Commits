import csv
import json
from pathlib import Path


def _diff(repo: str, index: int) -> str:
    return (
        f"diff --git a/src/{repo}_{index}.py b/src/{repo}_{index}.py\n"
        f"--- a/src/{repo}_{index}.py\n"
        f"+++ b/src/{repo}_{index}.py\n"
        "@@ -1 +1 @@\n"
        f"-old_{index}()\n"
        f"+new_{index}()\n"
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def configure_fixture_sources(cfg: dict, tmp_path: Path, *, per_category: int = 8) -> dict:
    source_root = tmp_path / "step3_source"
    strict_rows: list[dict] = []
    for idx in range(per_category):
        strict_rows.append(
            {
                "sample_uid": f"atomic-{idx}",
                "repo": f"atomic_repo_{idx}",
                "sha": f"atomic_sha_{idx}",
                "source_shas": [f"atomic_sha_{idx}"],
                "k": 1,
                "logical_intent_count": 1,
                "message_text": f"Update atomic behavior {idx}",
                "diff_text": _diff("atomic", idx),
            }
        )
        strict_rows.append(
            {
                "sample_uid": f"synthetic-{idx}",
                "repo": f"synthetic_repo_{idx}",
                "sha": f"synthetic_sha_{idx}",
                "source_shas": [f"synthetic_a_{idx}", f"synthetic_b_{idx}"],
                "k": 2,
                "logical_intent_count": 2,
                "message_text": f"Update parser and validation {idx}",
                "diff_text": _diff("synthetic", idx),
                "intent_subjects": [f"Update parser {idx}", f"Update validation {idx}"],
                "edit_to_intent": {"hunk_0": 0, "hunk_1": 1},
            }
        )
    _write_jsonl(source_root / "strict" / "step3_bootstrap_test.jsonl", strict_rows)
    _write_jsonl(source_root / "strict" / "step3_bootstrap_train.jsonl", strict_rows)
    _write_jsonl(source_root / "strict" / "step3_bootstrap_dev.jsonl", strict_rows)

    hard_b_csv = tmp_path / "hard_b.csv"
    m_csv = tmp_path / "m.csv"
    _write_csv(
        hard_b_csv,
        [
            {
                "repo": f"hard_repo_{idx}",
                "sha": f"hard_sha_{idx}",
                "subject": f"Refine hard single intent {idx}",
                "commit_message": f"Refine hard single intent {idx}",
                "git_diff": _diff("hard", idx),
            }
            for idx in range(per_category)
        ],
    )
    _write_csv(
        m_csv,
        [
            {
                "repo": f"m_repo_{idx}",
                "sha": f"m_sha_{idx}",
                "subject": f"Update service and tests {idx}",
                "commit_message": f"Update service and tests {idx}",
                "git_diff": _diff("m", idx),
                "llm_intent_count_estimate": "2",
                "llm_intent_summaries": f"Update service {idx}|Update tests {idx}",
            }
            for idx in range(per_category)
        ],
    )

    cfg = dict(cfg)
    cfg["data_sources"] = dict(cfg.get("data_sources", {}))
    cfg["data_sources"]["step3_source_root"] = str(source_root)
    cfg["data_sources"]["hard_b_csv"] = str(hard_b_csv)
    cfg["data_sources"]["m_csv"] = str(m_csv)
    return cfg


def create_real_api_probe_review_fixture(tmp_path: Path) -> dict[str, Path]:
    output_root = tmp_path / "outputs" / "llm_generation_real_api_probe_fixture"
    reports_root = tmp_path / "reports"
    output_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    samples = [
        {
            "sample_id": "atomic_simple:sample1",
            "repo": "acme/engine",
            "sha": "atomicsha",
            "data_category": "atomic_simple",
            "subject_reference": "test(engine): add signal validation tests",
            "message_reference": "test(engine): add signal validation tests",
            "diff_text": (
                "diff --git a/tests/test_signal.py b/tests/test_signal.py\n"
                "--- /dev/null\n"
                "+++ b/tests/test_signal.py\n"
                "@@ -0,0 +1,4 @@\n"
                "+def test_signal_validation():\n"
                "+    assert validate_signal('a')\n"
            ),
            "intent_count": 1,
            "intent_subjects": [],
            "intent_types": [],
            "edit_to_intent": {},
            "structure_supervision_level": "commit_level",
            "source_shas": ["atomicsha"],
            "split": "pilot_test",
        },
        {
            "sample_id": "hard_b:sample2",
            "repo": "acme/mongoid",
            "sha": "hardsha",
            "data_category": "hard_b",
            "subject_reference": "Add Criteria#eager_load pipeline support",
            "message_reference": "Add Criteria#eager_load pipeline support\n\n- update eager loading internals\n- add supporting tests",
            "diff_text": (
                "diff --git a/lib/eager.rb b/lib/eager.rb\n"
                "--- a/lib/eager.rb\n"
                "+++ b/lib/eager.rb\n"
                "@@ -10,2 +10,5 @@\n"
                "- preload(records)\n"
                "+ pipeline = build_lookup_pipeline(records)\n"
                "+ preload_for_lookup(pipeline)\n"
                "diff --git a/spec/eager_spec.rb b/spec/eager_spec.rb\n"
                "--- a/spec/eager_spec.rb\n"
                "+++ b/spec/eager_spec.rb\n"
                "@@ -1,1 +1,3 @@\n"
                "+it 'uses one query' do\n"
                "+  expect(query_count).to eq(1)\n"
            ),
            "intent_count": 1,
            "intent_subjects": [],
            "intent_types": [],
            "edit_to_intent": {},
            "structure_supervision_level": "commit_level",
            "source_shas": ["hardsha"],
            "split": "pilot_test",
        },
        {
            "sample_id": "synthetic_multi:sample3",
            "repo": "acme/docs",
            "sha": "syntheticsha",
            "data_category": "synthetic_multi",
            "subject_reference": "fix: correct doc paths and test greaterThanOrEqual",
            "message_reference": "fix: correct doc paths and test greaterThanOrEqual",
            "diff_text": (
                "diff --git a/src/compare.ts b/src/compare.ts\n"
                "--- a/src/compare.ts\n"
                "+++ b/src/compare.ts\n"
                "@@ -1,2 +1,4 @@\n"
                "- export const ge = (a, b) => a > b\n"
                "+ export const ge = (a, b) => a >= b\n"
                "+ export const unsafeCompare = (a, b) => a >= b\n"
                "diff --git a/docs/routes.ts b/docs/routes.ts\n"
                "--- a/docs/routes.ts\n"
                "+++ b/docs/routes.ts\n"
                "@@ -5,2 +5,3 @@\n"
                "- const path = '/old-docs'\n"
                "+ const path = '/docs'\n"
                "+ export const docsHome = path\n"
            ),
            "intent_count": 2,
            "intent_subjects": ["Test greaterThanOrEqual", "Fix docs path generation"],
            "intent_types": ["test", "docs"],
            "edit_to_intent": {"hunk_0": 0, "hunk_1": 1},
            "structure_supervision_level": "hunk_level",
            "source_shas": ["synthetic_a", "synthetic_b"],
            "split": "pilot_test",
        },
        {
            "sample_id": "M_real_multi:sample4",
            "repo": "acme/render",
            "sha": "msha",
            "data_category": "M_real_multi",
            "subject_reference": "Improve ABI stability and optimize rendering performance (#1271)",
            "message_reference": "Improve ABI stability and optimize rendering performance (#1271)",
            "diff_text": (
                "diff --git a/src/component_base.cpp b/src/component_base.cpp\n"
                "--- a/src/component_base.cpp\n"
                "+++ b/src/component_base.cpp\n"
                "@@ -1,2 +1,4 @@\n"
                "- void reset() {}\n"
                "+ void reset_storage() {}\n"
                "+ void reserve_surface_cells() {}\n"
                "diff --git a/src/surface.cpp b/src/surface.cpp\n"
                "--- a/src/surface.cpp\n"
                "+++ b/src/surface.cpp\n"
                "@@ -8,2 +8,4 @@\n"
                "- cells.push_back(cell)\n"
                "+ flat_cells.push_back(cell)\n"
                "+ return flat_cells.size()\n"
            ),
            "intent_count": 2,
            "intent_subjects": ["Refactor ComponentBase internals", "Flatten Surface cell storage"],
            "intent_types": [],
            "edit_to_intent": {},
            "structure_supervision_level": "commit_level",
            "source_shas": ["msha"],
            "split": "pilot_test",
        },
    ]
    _write_jsonl(output_root / "dataset" / "canary_all.jsonl", samples)

    generations = [
        {
            "sample_id": "atomic_simple:sample1",
            "data_category": "atomic_simple",
            "strategy": "G1",
            "generated_subject": "Add signal event validation tests",
            "status": "generated",
            "failure_reason": "",
            "latency_ms": 91,
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
            "cache_hit": False,
            "retry_count": 0,
            "http_status": 200,
            "thinking_mode": "disabled",
            "retrieved_exemplar_ids": [],
            "oracle_only": False,
            "deployable": True,
        },
        {
            "sample_id": "hard_b:sample2",
            "data_category": "hard_b",
            "strategy": "G1",
            "generated_subject": "Implement $lookup-based eager loading for associations",
            "status": "generated",
            "failure_reason": "",
            "latency_ms": 120,
            "usage": {"prompt_tokens": 200, "completion_tokens": 7},
            "cache_hit": False,
            "retry_count": 0,
            "http_status": 200,
            "thinking_mode": "disabled",
            "retrieved_exemplar_ids": [],
            "oracle_only": False,
            "deployable": True,
        },
        {
            "sample_id": "synthetic_multi:sample3",
            "data_category": "synthetic_multi",
            "strategy": "G4",
            "generated_subject": "Add unsafe comparison and improve docs page generation",
            "status": "generated",
            "failure_reason": "",
            "latency_ms": 150,
            "usage": {"prompt_tokens": 300, "completion_tokens": 8},
            "cache_hit": False,
            "retry_count": 0,
            "http_status": 200,
            "thinking_mode": "disabled",
            "retrieved_exemplar_ids": ["ex:synthetic:1", "ex:synthetic:2", "ex:synthetic:3"],
            "oracle_only": False,
            "deployable": True,
        },
        {
            "sample_id": "synthetic_multi:sample3",
            "data_category": "synthetic_multi",
            "strategy": "G5",
            "generated_subject": "Add tests for greaterThanOrEqual and fix docs path generation",
            "status": "generated",
            "failure_reason": "",
            "latency_ms": 155,
            "usage": {"prompt_tokens": 320, "completion_tokens": 9},
            "cache_hit": False,
            "retry_count": 0,
            "http_status": 200,
            "thinking_mode": "disabled",
            "retrieved_exemplar_ids": ["ex:synthetic:1", "ex:synthetic:2", "ex:synthetic:3"],
            "oracle_only": True,
            "deployable": False,
        },
        {
            "sample_id": "M_real_multi:sample4",
            "data_category": "M_real_multi",
            "strategy": "G4",
            "generated_subject": "Refactor ComponentBase internals and flatten Surface cell storage for ABI stability",
            "status": "generated",
            "failure_reason": "",
            "latency_ms": 175,
            "usage": {"prompt_tokens": 400, "completion_tokens": 12},
            "cache_hit": False,
            "retry_count": 0,
            "http_status": 200,
            "thinking_mode": "disabled",
            "retrieved_exemplar_ids": ["ex:m:1", "ex:m:2", "ex:m:3"],
            "oracle_only": False,
            "deployable": True,
        },
    ]
    _write_jsonl(output_root / "generations" / "real" / "generation_outputs.jsonl", generations)

    prompts = [
        {
            "sample_id": "atomic_simple:sample1",
            "strategy": "G1",
            "prompt": "Write one natural commit subject.\nRepository: acme/engine\nDiff: add signal validation tests\n",
        },
        {
            "sample_id": "hard_b:sample2",
            "strategy": "G1",
            "prompt": "Write one natural commit subject.\nRepository: acme/mongoid\nDiff: eager loading pipeline and tests\n",
        },
        {
            "sample_id": "synthetic_multi:sample3",
            "strategy": "G4",
            "prompt": "Write one natural commit subject.\nExamples:\nExample 1: docs path fix\nDiff: compare and docs routes\n",
        },
        {
            "sample_id": "synthetic_multi:sample3",
            "strategy": "G5",
            "prompt": (
                "Write one natural commit subject.\n"
                "Oracle intent count: 2\n"
                "Oracle intent subjects:\n- Test greaterThanOrEqual\n- Fix docs path generation\n"
                "Diff: compare and docs routes\n"
            ),
        },
        {
            "sample_id": "M_real_multi:sample4",
            "strategy": "G4",
            "prompt": "Write one natural commit subject.\nExamples:\nExample 1: storage flattening\nDiff: component and surface changes\n",
        },
    ]
    _write_jsonl(output_root / "prompts_rendered" / "probe_prompts.jsonl", prompts)

    retrieval_logs = [
        {
            "query_sample_id": "synthetic_multi:sample3",
            "strategy": "retrieval",
            "requested_k": 3,
            "returned_k": 3,
            "query_repo_original": "acme/docs",
            "query_repo_canonical": "acme/docs",
            "retrieved_exemplar_ids": ["ex:synthetic:1", "ex:synthetic:2", "ex:synthetic:3"],
            "retrieved_repo_original": ["example/docs", "example/tests", "example/mixed"],
            "retrieved_repo_canonical": ["example/docs", "example/tests", "example/mixed"],
            "similarity_scores": [0.9, 0.5, 0.4],
            "similarity_top1": 0.9,
            "similarity_min": 0.4,
            "similarity_mean": 0.6,
            "similarity_p50": 0.5,
            "low_similarity_threshold": 0.1,
            "low_similarity_count": 0,
            "low_similarity_ratio": 0.0,
            "low_similarity_warning": False,
            "retrieval_quality_status": "usable_with_diagnostics",
            "filter_reasons": {},
            "fallback_reason": "",
            "same_repo_original_string": False,
            "same_repo_canonical": False,
            "repo_identity_parse_status": {"query": "github_slug", "retrieved": ["github_slug", "github_slug", "github_slug"]},
            "repo_guard_applied": True,
            "repo_guard_exclusion_count": 0,
            "repo_guard_excluded_candidates": [],
            "leakage_checks": {
                "same_repo": False,
                "same_repo_original_string": False,
                "same_repo_canonical": False,
                "source_sha_overlap": False,
                "diff_fingerprint_overlap": False,
                "normalized_subject_overlap": False,
            },
            "generation_strategy": "G4",
        },
        {
            "query_sample_id": "synthetic_multi:sample3",
            "strategy": "retrieval",
            "requested_k": 3,
            "returned_k": 3,
            "query_repo_original": "acme/docs",
            "query_repo_canonical": "acme/docs",
            "retrieved_exemplar_ids": ["ex:synthetic:1", "ex:synthetic:2", "ex:synthetic:3"],
            "retrieved_repo_original": ["example/docs", "example/tests", "example/mixed"],
            "retrieved_repo_canonical": ["example/docs", "example/tests", "example/mixed"],
            "similarity_scores": [0.9, 0.5, 0.4],
            "similarity_top1": 0.9,
            "similarity_min": 0.4,
            "similarity_mean": 0.6,
            "similarity_p50": 0.5,
            "low_similarity_threshold": 0.1,
            "low_similarity_count": 0,
            "low_similarity_ratio": 0.0,
            "low_similarity_warning": False,
            "retrieval_quality_status": "usable_with_diagnostics",
            "filter_reasons": {},
            "fallback_reason": "",
            "same_repo_original_string": False,
            "same_repo_canonical": False,
            "repo_identity_parse_status": {"query": "github_slug", "retrieved": ["github_slug", "github_slug", "github_slug"]},
            "repo_guard_applied": True,
            "repo_guard_exclusion_count": 0,
            "repo_guard_excluded_candidates": [],
            "leakage_checks": {
                "same_repo": False,
                "same_repo_original_string": False,
                "same_repo_canonical": False,
                "source_sha_overlap": False,
                "diff_fingerprint_overlap": False,
                "normalized_subject_overlap": False,
            },
            "generation_strategy": "G5",
        },
        {
            "query_sample_id": "M_real_multi:sample4",
            "strategy": "retrieval",
            "requested_k": 3,
            "returned_k": 3,
            "query_repo_original": "acme/render",
            "query_repo_canonical": "acme/render",
            "retrieved_exemplar_ids": ["ex:m:1", "ex:m:2", "ex:m:3"],
            "retrieved_repo_original": ["example/render", "example/render2", "example/render3"],
            "retrieved_repo_canonical": ["example/render", "example/render2", "example/render3"],
            "similarity_scores": [0.7, 0.55, 0.2],
            "similarity_top1": 0.7,
            "similarity_min": 0.2,
            "similarity_mean": 0.48333333333333334,
            "similarity_p50": 0.55,
            "low_similarity_threshold": 0.1,
            "low_similarity_count": 0,
            "low_similarity_ratio": 0.0,
            "low_similarity_warning": False,
            "retrieval_quality_status": "usable_with_diagnostics",
            "filter_reasons": {},
            "fallback_reason": "",
            "same_repo_original_string": False,
            "same_repo_canonical": False,
            "repo_identity_parse_status": {"query": "github_slug", "retrieved": ["github_slug", "github_slug", "github_slug"]},
            "repo_guard_applied": True,
            "repo_guard_exclusion_count": 0,
            "repo_guard_excluded_candidates": [],
            "leakage_checks": {
                "same_repo": False,
                "same_repo_original_string": False,
                "same_repo_canonical": False,
                "source_sha_overlap": False,
                "diff_fingerprint_overlap": False,
                "normalized_subject_overlap": False,
            },
            "generation_strategy": "G4",
        },
    ]
    _write_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl", retrieval_logs)

    exemplars = [
        {
            "exemplar_id": "ex:synthetic:1",
            "repo": "example/docs",
            "sha": "esha1",
            "data_category": "synthetic_multi",
            "type_signature": "synthetic_multi|files=2|exts=.ts",
            "subject": "Fix docs path generation",
            "diff_summary": "docs route path fix",
            "diff_text": "diff --git a/docs/routes.ts b/docs/routes.ts\n@@ -1 +1 @@\n-/old\n+/docs\n",
            "embedding_text": "docs path generation",
        },
        {
            "exemplar_id": "ex:synthetic:2",
            "repo": "example/tests",
            "sha": "esha2",
            "data_category": "synthetic_multi",
            "type_signature": "synthetic_multi|files=1|exts=.ts",
            "subject": "Add greaterThanOrEqual tests",
            "diff_summary": "comparison test coverage",
            "diff_text": "diff --git a/tests/compare.test.ts b/tests/compare.test.ts\n@@ -1 +1 @@\n+it('supports >=' )\n",
            "embedding_text": "greater than or equal tests",
        },
        {
            "exemplar_id": "ex:synthetic:3",
            "repo": "example/mixed",
            "sha": "esha3",
            "data_category": "synthetic_multi",
            "type_signature": "synthetic_multi|files=2|exts=.ts",
            "subject": "Update comparison behavior and docs",
            "diff_summary": "comparison and docs update",
            "diff_text": "diff --git a/src/compare.ts b/src/compare.ts\n@@ -1 +1 @@\n-a>b\n+a>=b\n",
            "embedding_text": "comparison docs",
        },
        {
            "exemplar_id": "ex:m:1",
            "repo": "example/render",
            "sha": "m1",
            "data_category": "M_real_multi",
            "type_signature": "M_real_multi|files=2|exts=.cpp",
            "subject": "Refactor component storage layout",
            "diff_summary": "component storage refactor",
            "diff_text": "diff --git a/src/component.cpp b/src/component.cpp\n@@ -1 +1 @@\n-reset\n+reset_storage\n",
            "embedding_text": "component storage refactor",
        },
        {
            "exemplar_id": "ex:m:2",
            "repo": "example/render2",
            "sha": "m2",
            "data_category": "M_real_multi",
            "type_signature": "M_real_multi|files=1|exts=.cpp",
            "subject": "Flatten surface cell buffers",
            "diff_summary": "surface buffer flattening",
            "diff_text": "diff --git a/src/surface.cpp b/src/surface.cpp\n@@ -1 +1 @@\n-cells\n+flat_cells\n",
            "embedding_text": "surface cell flattening",
        },
        {
            "exemplar_id": "ex:m:3",
            "repo": "example/render3",
            "sha": "m3",
            "data_category": "M_real_multi",
            "type_signature": "M_real_multi|files=2|exts=.cpp",
            "subject": "Stabilize render ABI surface",
            "diff_summary": "abi stabilization work",
            "diff_text": "diff --git a/src/abi.cpp b/src/abi.cpp\n@@ -1 +1 @@\n-old\n+new\n",
            "embedding_text": "abi stability",
        },
    ]
    _write_jsonl(output_root / "exemplar_pool" / "exemplar_pool.jsonl", exemplars)

    (output_root / "run_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "llm_generation_pilot_run_v1",
                "output_root": str(output_root),
                "planned_request_count": 5,
                "sample_count": 4,
                "strategy_count": 3,
                "real_api_called": True,
                "thinking_mode": "disabled",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result_json = reports_root / "real_api_probe_result_fixture.json"
    result_json.write_text(
        json.dumps(
            {
                "schema_version": "real_api_probe_result_v1",
                "report_timestamp": "20260610T090000Z",
                "planned_request_count": 5,
                "completed_request_count": 5,
                "failed_request_count": 0,
                "api_success_rate": 1.0,
                "parse_success_rate": 1.0,
                "empty_output_rate": 0.0,
                "single_line_rate": 1.0,
                "artifact_rate": 0.0,
                "retry_count": 0,
                "timeout_count": 0,
                "cache_hit_count": 5,
                "resume_skip_count": 5,
                "new_real_request_count": 0,
                "latency_p50_ms": 120,
                "latency_p90_ms": 175,
                "actual_usage_available": True,
                "actual_input_tokens_total": 1320,
                "actual_output_tokens_total": 41,
                "estimated_actual_cost_usd": 0.0002,
                "strategy_distribution": {"G1": 2, "G4": 2, "G5": 1},
                "category_distribution": {"atomic_simple": 1, "hard_b": 1, "synthetic_multi": 2, "M_real_multi": 1},
                "thinking_mode": "disabled",
                "key_leakage_detected": False,
                "manual_review_completed": False,
                "recommend_65_request_canary": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    preflight_json = reports_root / "real_api_probe_preflight_fixture.json"
    preflight_json.write_text(
        json.dumps(
            {
                "schema_version": "real_api_probe_preflight_v1",
                "passed": True,
                "http_status": 200,
                "models_http_status": 200,
                "available_model_match": True,
                "parse_success": True,
                "content_non_empty": True,
                "single_line": True,
                "thinking_mode": "disabled",
                "key_leakage_detected": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "output_root": output_root,
        "reports_root": reports_root,
        "probe_result_json": result_json,
        "preflight_json": preflight_json,
    }


def create_targeted_regression_fixture(tmp_path: Path) -> dict[str, Path]:
    output_root = tmp_path / "outputs" / "llm_generation_targeted_regression_fixture"
    reports_root = tmp_path / "reports"
    output_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    sample = {
        "sample_id": "M_real_multi:7da239a00c1c6f17",
        "repo": "ArthurSonzogni/FTXUI",
        "repo_canonical": "arthursonzogni/ftxui",
        "repo_identity_parse_status": "github_slug",
        "sha": "98c650d2ba6c22cb00bf3a3b3a7d1acd3d92ca1e",
        "data_category": "M_real_multi",
        "subject_reference": "Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)",
        "message_reference": "Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)",
        "diff_text": (
            "diff --git a/src/ftxui/component/component.cpp b/src/ftxui/component/component.cpp\n"
            "@@ -1 +1 @@\n"
            "-children_\n"
            "+impl_->children\n"
            "diff --git a/src/ftxui/screen/surface.cpp b/src/ftxui/screen/surface.cpp\n"
            "@@ -1 +1 @@\n"
            "-cells_\n"
            "+flat_cells\n"
        ),
        "intent_count": 2,
        "intent_subjects": ["Improve ABI stability", "Optimize rendering performance"],
        "intent_types": [],
        "edit_to_intent": {},
        "structure_supervision_level": "commit_level",
        "source_shas": ["98c650d2ba6c22cb00bf3a3b3a7d1acd3d92ca1e"],
        "split": "pilot_test",
        "diff_fingerprint": "ftxui-fp",
        "normalized_subject": "improve abi stability for 7 0 0 and optimize rendering performance 1271",
    }
    _write_jsonl(output_root / "dataset" / "canary_all.jsonl", [sample])
    _write_jsonl(output_root / "dataset" / "pilot_all.jsonl", [sample])
    (output_root / "dataset" / "canary_manifest.json").write_text(
        json.dumps({"selected_counts": {"M_real_multi": 1}, "fixed_probe_dataset_root": "outputs/llm_generation_real_api_probe_20260610T082307Z"}) + "\n",
        encoding="utf-8",
    )
    (output_root / "dataset" / "canary_leakage_report.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")

    _write_jsonl(
        output_root / "exemplar_pool" / "exemplar_pool.jsonl",
        [
            {
                "exemplar_id": "ex:good1",
                "repo": "friendlyanon/cmake-init",
                "repo_canonical": "friendlyanon/cmake-init",
                "sha": "good1",
                "data_category": "M_real_multi",
                "type_signature": "M_real_multi|files=2|exts=.cpp",
                "subject": "Improve ABI checks and renderer behavior",
                "diff_summary": "summary1",
                "diff_text": "diff1",
                "diff_fingerprint": "fp1",
                "normalized_subject": "improve abi checks and renderer behavior",
                "embedding_text": "abi renderer",
            },
            {
                "exemplar_id": "ex:good2",
                "repo": "nvidia/dali",
                "repo_canonical": "nvidia/dali",
                "sha": "good2",
                "data_category": "M_real_multi",
                "type_signature": "M_real_multi|files=2|exts=.cpp",
                "subject": "Refactor internals and speed up surface clearing",
                "diff_summary": "summary2",
                "diff_text": "diff2",
                "diff_fingerprint": "fp2",
                "normalized_subject": "refactor internals and speed up surface clearing",
                "embedding_text": "surface clearing refactor",
            },
            {
                "exemplar_id": "ex:good3",
                "repo": "curl/curl",
                "repo_canonical": "curl/curl",
                "sha": "good3",
                "data_category": "M_real_multi",
                "type_signature": "M_real_multi|files=2|exts=.cpp",
                "subject": "Improve component layout and storage performance",
                "diff_summary": "summary3",
                "diff_text": "diff3",
                "diff_fingerprint": "fp3",
                "normalized_subject": "improve component layout and storage performance",
                "embedding_text": "component storage performance",
            },
        ],
    )
    _write_jsonl(
        output_root / "exemplar_pool" / "exemplar_pool_exclusion_log.jsonl",
        [
            {
                "candidate_id": "ex:c066b8142b1ab31b",
                "candidate_repo_original": "arthursonzogni/ftxui",
                "candidate_repo_canonical": "arthursonzogni/ftxui",
                "candidate_repo_parse_status": "github_slug",
                "candidate_sha": "117417e841c0b4d9764c41628ad2d831a218189e",
                "candidate_sample_id": "",
                "candidate_data_category": "hard_b",
                "reasons": ["same_repo_canonical"],
            }
        ],
    )
    _write_jsonl(
        output_root / "retrieval_logs" / "retrieval_logs.jsonl",
        [
            {
                "query_sample_id": "M_real_multi:7da239a00c1c6f17",
                "generation_strategy": "G4",
                "query_repo_original": "ArthurSonzogni/FTXUI",
                "query_repo_canonical": "arthursonzogni/ftxui",
                "retrieved_exemplar_ids": ["ex:good1", "ex:good2", "ex:good3"],
                "retrieved_repo_original": ["friendlyanon/cmake-init", "nvidia/dali", "curl/curl"],
                "retrieved_repo_canonical": ["friendlyanon/cmake-init", "nvidia/dali", "curl/curl"],
                "same_repo_original_string": False,
                "same_repo_canonical": False,
                "repo_guard_applied": True,
                "repo_guard_exclusion_count": 1,
                "repo_guard_excluded_candidates": [
                    {
                        "candidate_id": "ex:c066b8142b1ab31b",
                        "candidate_repo_original": "arthursonzogni/ftxui",
                        "candidate_repo_canonical": "arthursonzogni/ftxui",
                        "reason": "same_repo_canonical",
                    }
                ],
                "similarity_scores": [0.21, 0.18, 0.12],
                "similarity_top1": 0.21,
                "similarity_min": 0.12,
                "similarity_mean": 0.17,
                "similarity_p50": 0.18,
                "low_similarity_threshold": 0.10,
                "low_similarity_count": 0,
                "low_similarity_ratio": 0.0,
                "low_similarity_warning": False,
                "retrieval_quality_status": "usable_with_diagnostics",
                "leakage_checks": {
                    "same_repo": False,
                    "same_repo_original_string": False,
                    "same_repo_canonical": False,
                    "source_sha_overlap": False,
                    "diff_fingerprint_overlap": False,
                    "normalized_subject_overlap": False,
                },
            }
        ],
    )
    _write_jsonl(
        output_root / "prompts_rendered" / "probe_prompts.jsonl",
        [{"sample_id": "M_real_multi:7da239a00c1c6f17", "strategy": "G4", "prompt": "Write one commit subject"}],
    )
    _write_jsonl(
        output_root / "generations" / "real" / "generation_outputs.jsonl",
        [
            {
                "sample_id": "M_real_multi:7da239a00c1c6f17",
                "data_category": "M_real_multi",
                "strategy": "G4",
                "generator_model": "deepseek-v4-flash",
                "prompt_version": "v1",
                "retrieved_exemplar_ids": ["ex:good1", "ex:good2", "ex:good3"],
                "generated_subject": "Improve ABI stability and optimize Surface rendering performance",
                "status": "generated",
                "failure_reason": "",
                "latency_ms": 1111,
                "usage": {"prompt_tokens": 1234, "completion_tokens": 11},
                "cache_hit": False,
                "retry_count": 0,
                "http_status": 200,
                "thinking_mode": "disabled",
                "oracle_only": False,
                "deployable": True,
            }
        ],
    )
    (output_root / "run_metadata.json").write_text(
        json.dumps(
            {
                "planned_request_count": 1,
                "sample_count": 1,
                "strategy_count": 1,
                "real_api_called": True,
                "thinking_mode": "disabled",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"output_root": output_root, "reports_root": reports_root}
