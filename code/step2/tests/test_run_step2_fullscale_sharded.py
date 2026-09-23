from __future__ import annotations

import csv
import importlib.util
import json
import builtins
from pathlib import Path
from types import SimpleNamespace


RUNNER_PATH = Path(__file__).resolve().parents[1] / "code" / "run_step2_fullscale_sharded.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("run_step2_fullscale_sharded", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
assert RUNNER_SPEC and RUNNER_SPEC.loader
RUNNER_SPEC.loader.exec_module(RUNNER)


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


def write_minimal_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["repo", "sha", "type", "subject", "message", "git_diff", "manual_label"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_runtime_config(path: Path, source_csv: Path) -> None:
    payload = {
        "source_csv": str(source_csv),
        "output_dir": str(path.parent / "out"),
        "progress_flush_every": 7,
        "manual_label": "A",
        "run_purpose": "formal",
        "intent_k": 2,
        "k_sweep_max": 2,
        "group_combo_attempt_cap_per_repo": 500,
        "group_candidate_cap_per_repo": 200,
        "target_count": 1000,
        "min_target_ratio": 0.0,
        "repo_cap": 1000,
        "type_pair_cap": 1000,
        "max_merged_files": 20,
        "max_merged_lines": 2000,
        "require_different_type": True,
        "module_overlap_policy": "prefer",
        "message_stage_enabled": False,
        "message_gate_enabled": True,
        "fewshot_enabled": False,
        "require_fewshot_pool": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_materialize_fullscale_plan_writes_shards_and_uncovered_report(tmp_path: Path) -> None:
    source_csv = tmp_path / "source.csv"
    config_path = tmp_path / "config.json"
    rows = [
        {
            "repo": "repo/A",
            "sha": "sha1",
            "type": "fix",
            "subject": "fix parser bug",
            "message": "fix parser bug",
            "git_diff": make_diff("src/a.py"),
            "manual_label": "A",
        },
        {
            "repo": "repo/A",
            "sha": "sha2",
            "type": "test",
            "subject": "add parser test",
            "message": "add parser test",
            "git_diff": make_diff("tests/a_test.py"),
            "manual_label": "A",
        },
        {
            "repo": "repo/B",
            "sha": "sha3",
            "type": "feat",
            "subject": "add cache hook",
            "message": "add cache hook",
            "git_diff": make_diff("src/b.py"),
            "manual_label": "A",
        },
        {
            "repo": "repo/B",
            "sha": "sha4",
            "type": "test",
            "subject": "add cache tests",
            "message": "add cache tests",
            "git_diff": make_diff("tests/b_test.py"),
            "manual_label": "A",
        },
        {
            "repo": "repo/C",
            "sha": "sha5",
            "type": "refactor",
            "subject": "refactor cli helpers",
            "message": "refactor cli helpers",
            "git_diff": make_diff("src/c.py"),
            "manual_label": "A",
        },
    ]
    write_minimal_csv(source_csv, rows)
    write_runtime_config(config_path, source_csv)

    planning_args = RUNNER.load_planning_args(config_path)
    plan_payload = RUNNER.build_primary_plan(
        planning_args,
        selection_target_count=RUNNER.UNBOUNDED_CAP,
        selection_repo_cap=RUNNER.UNBOUNDED_CAP,
        selection_type_pair_cap=RUNNER.UNBOUNDED_CAP,
    )
    manifest = RUNNER.materialize_fullscale_plan(
        tmp_path / "fullscale",
        config_path,
        config_path,
        planning_args,
        plan_payload,
        shard_size=1,
        selection_target_count=RUNNER.UNBOUNDED_CAP,
        selection_repo_cap=RUNNER.UNBOUNDED_CAP,
        selection_type_pair_cap=RUNNER.UNBOUNDED_CAP,
    )

    assert manifest["selected_pair_count"] == 2
    assert manifest["source_coverage_count"] == 4
    assert manifest["uncovered_source_count"] == 1
    assert manifest["uncovered_category_breakdown"]["category_1_no_eligible_diff_pair_count"] == 1
    assert manifest["uncovered_category_breakdown"]["category_2_filtered_by_legacy_guarded_count"] == 0
    assert manifest["shard_count"] == 2
    assert Path(manifest["paths"]["selected_pairs_primary_jsonl"]).exists()
    assert Path(manifest["paths"]["uncovered_sources_csv"]).exists()
    assert Path(manifest["paths"]["uncovered_sources_category1_csv"]).exists()
    assert Path(manifest["paths"]["uncovered_sources_category2_csv"]).exists()
    uncovered_csv = Path(manifest["paths"]["uncovered_sources_csv"]).read_text(encoding="utf-8")
    assert "sha5" in uncovered_csv
    assert all(Path(item["selected_pairs_jsonl"]).exists() for item in manifest["shards"])
    assert all(Path(item["selected_pairs_manifest"]).exists() for item in manifest["shards"])
    assert all(item["progress_flush_every"] == 7 for item in manifest["shards"])


def test_run_one_shard_respects_generation_config_and_message_gate(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_parse_args(argv):
        captured["argv"] = list(argv)
        return SimpleNamespace(
            output_dir=str(tmp_path / "shard_out"),
            generator_provider="mock_provider",
            generator_mode="mock",
        )

    def fake_run_single(args, enforce_gates, prepared_context=None):
        captured["enforce_gates"] = enforce_gates
        captured["prepared_context"] = prepared_context
        return {
            "generated_count": 3,
            "step3_ready_count": 2,
            "target_gate_passed": True,
            "message_metrics": {"message_pass_rate": 0.5, "message_reject_rate": 0.1},
        }

    monkeypatch.setattr(RUNNER.step2, "parse_args", fake_parse_args)
    monkeypatch.setattr(RUNNER.step2, "run_single", fake_run_single)

    shard_record = {
        "shard_id": "shard_0001",
        "shard_index": 1,
        "selected_pair_count": 3,
        "sample_id_offset": 10,
        "progress_flush_every": 7,
        "selected_pairs_jsonl": str(tmp_path / "pairs.jsonl"),
        "selected_pairs_manifest": str(tmp_path / "pairs_manifest.json"),
        "output_dir": str(tmp_path / "shard_out"),
        "intent_k": 2,
    }
    result = RUNNER.run_one_shard(
        tmp_path / "config.json",
        shard_record,
        disable_message_gate_for_shards=False,
        shard_min_target_ratio=0.0,
        api_ping_before_each_shard=True,
        resume=False,
        prepared_context=None,
    )

    assert result["status"] == "completed"
    assert captured["enforce_gates"] is False
    assert captured["prepared_context"] is None
    argv = captured["argv"]
    assert "--run-purpose" not in argv
    assert "--disable-message-gate" not in argv
    assert "--selected-pairs-jsonl" in argv
    assert "--sample-id-offset" in argv and "10" in argv
    assert "--progress-flush-every" in argv and "7" in argv


def test_run_one_shard_uses_prepared_context_and_does_not_reuse_partial_only(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "shard_out"
    run_dir.mkdir(parents=True)
    (run_dir / "run_progress.json").write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}
    prepared_context = {"prepared": True}

    def fake_parse_args(argv):
        captured["argv"] = list(argv)
        return SimpleNamespace(
            output_dir=str(run_dir),
            generator_provider="mock_provider",
            generator_mode="mock",
        )

    def fake_run_single(args, enforce_gates, prepared_context=None):
        captured["prepared_context"] = prepared_context
        return {
            "generated_count": 2,
            "step3_ready_count": 1,
            "target_gate_passed": True,
            "message_metrics": {"message_pass_rate": 0.5, "message_reject_rate": 0.5},
        }

    monkeypatch.setattr(RUNNER.step2, "parse_args", fake_parse_args)
    monkeypatch.setattr(RUNNER.step2, "run_single", fake_run_single)

    shard_record = {
        "shard_id": "shard_0003",
        "shard_index": 3,
        "selected_pair_count": 2,
        "sample_id_offset": 20,
        "progress_flush_every": 10,
        "selected_pairs_jsonl": str(tmp_path / "pairs.jsonl"),
        "selected_pairs_manifest": str(tmp_path / "pairs_manifest.json"),
        "output_dir": str(run_dir),
        "intent_k": 2,
    }
    result = RUNNER.run_one_shard(
        tmp_path / "config.json",
        shard_record,
        disable_message_gate_for_shards=False,
        shard_min_target_ratio=0.0,
        api_ping_before_each_shard=False,
        resume=True,
        prepared_context=prepared_context,
    )

    assert result["status"] == "completed"
    assert captured["prepared_context"] == prepared_context


def test_run_one_shard_fails_fast_when_api_ping_is_unreachable(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_parse_args(argv):
        captured["argv"] = list(argv)
        return SimpleNamespace(
            output_dir=str(tmp_path / "shard_out"),
            generator_provider="deepseek_api",
            generator_mode="api",
        )

    def fake_run_single(*args, **kwargs):
        raise AssertionError("run_single should not be called when api ping proves the provider is unreachable")

    monkeypatch.setattr(RUNNER.step2, "parse_args", fake_parse_args)
    monkeypatch.setattr(RUNNER.step2, "run_single", fake_run_single)
    monkeypatch.setattr(
        RUNNER,
        "run_shard_api_ping",
        lambda *args, **kwargs: {
            "attempted": True,
            "ok": False,
            "attempt_count": 3,
            "warning": "request_error (<urlopen error [Errno 8] nodename nor servname provided, or not known>)",
            "error_type": "request_error",
            "raw_response_preview": "<urlopen error [Errno 8] nodename nor servname provided, or not known>",
        },
    )

    shard_record = {
        "shard_id": "shard_0099",
        "shard_index": 99,
        "selected_pair_count": 100,
        "sample_id_offset": 9800,
        "progress_flush_every": 10,
        "selected_pairs_jsonl": str(tmp_path / "pairs.jsonl"),
        "selected_pairs_manifest": str(tmp_path / "pairs_manifest.json"),
        "output_dir": str(tmp_path / "shard_out"),
        "intent_k": 2,
    }
    result = RUNNER.run_one_shard(
        tmp_path / "config.json",
        shard_record,
        disable_message_gate_for_shards=False,
        shard_min_target_ratio=0.0,
        api_ping_before_each_shard=True,
        resume=False,
        prepared_context=None,
    )

    assert result["status"] == "failed"
    assert result["generated_count"] == 0
    assert result["step3_ready_count"] == 0
    assert result["api_ping_attempted"] is True
    assert result["api_ping_ok"] is False
    assert result["api_ping_attempt_count"] == 3
    assert result["error"] == "api_ping_request_error"


def test_write_runtime_state_persists_failed_and_pending_shards(tmp_path: Path) -> None:
    primary_manifest = {
        "shard_count": 3,
        "source_pool_size": 10,
        "selected_pair_count": 6,
        "source_coverage_count": 8,
        "uncovered_source_count": 2,
        "paths": {"selected_pairs_primary_manifest": "plan/manifest.json"},
        "shards": [
            {"shard_id": "shard_0001", "shard_index": 1},
            {"shard_id": "shard_0002", "shard_index": 2},
            {"shard_id": "shard_0003", "shard_index": 3},
        ],
    }
    shard_results = [
        {"shard_id": "shard_0001", "shard_index": 1, "status": "completed", "generated_count": 10, "step3_ready_count": 7},
        {"shard_id": "shard_0002", "shard_index": 2, "status": "failed", "error": "boom"},
    ]

    payload = RUNNER.write_runtime_state(
        tmp_path / "fullscale",
        primary_manifest,
        shard_results,
        active_shard_ids=["shard_0003"],
        worker_states=[{"worker_id": 0, "status": "running", "shard_id": "shard_0003"}],
    )
    state_path = tmp_path / "fullscale" / "aggregate" / "runtime_state.json"

    assert state_path.exists()
    assert payload["completed_shard_count"] == 1
    assert payload["failed_shard_count"] == 1
    assert payload["running_shards"] == ["shard_0003"]
    assert payload["pending_shards"] == []
    assert payload["failed_shards"][0]["shard_id"] == "shard_0002"


def test_run_shard_batch_reuses_prepared_context_once(monkeypatch, tmp_path: Path) -> None:
    prepared_calls: list[str] = []
    shard_calls: list[tuple[str, object]] = []

    def fake_prepare_context(config_path, *, output_dir=None):
        prepared_calls.append(str(config_path))
        return {"ctx": 1}

    def fake_run_one_shard(
        generation_config_path,
        shard_record,
        *,
        disable_message_gate_for_shards,
        shard_min_target_ratio,
        api_ping_before_each_shard,
        resume,
        prepared_context,
    ):
        shard_calls.append((shard_record["shard_id"], prepared_context))
        return {
            "shard_id": shard_record["shard_id"],
            "shard_index": shard_record["shard_index"],
            "output_dir": shard_record["output_dir"],
            "status": "completed",
            "selected_pair_count": shard_record["selected_pair_count"],
            "generated_count": 1,
            "step3_ready_count": 1,
            "target_gate_passed": True,
            "message_pass_rate": 1.0,
            "message_reject_rate": 0.0,
        }

    monkeypatch.setattr(RUNNER.step2, "prepare_run_context", fake_prepare_context)
    monkeypatch.setattr(RUNNER, "run_one_shard", fake_run_one_shard)

    shard_records = [
        {"shard_id": "shard_0001", "shard_index": 1, "output_dir": str(tmp_path / "s1"), "selected_pair_count": 1},
        {"shard_id": "shard_0002", "shard_index": 2, "output_dir": str(tmp_path / "s2"), "selected_pair_count": 1},
    ]
    results = RUNNER.run_shard_batch(
        worker_id=0,
        generation_config_path=tmp_path / "config.json",
        shard_records=shard_records,
        disable_message_gate_for_shards=False,
        shard_min_target_ratio=0.0,
        api_ping_before_each_shard=False,
        resume=False,
    )

    assert prepared_calls == [str(tmp_path / "config.json")]
    assert shard_calls == [("shard_0001", {"ctx": 1}), ("shard_0002", {"ctx": 1})]
    assert [item["shard_id"] for item in results] == ["shard_0001", "shard_0002"]


def test_log_event_ignores_broken_pipe(monkeypatch) -> None:
    def fake_print(*args, **kwargs):
        raise BrokenPipeError("stdout closed")

    monkeypatch.setattr(builtins, "print", fake_print)

    RUNNER.log_event("hello")
