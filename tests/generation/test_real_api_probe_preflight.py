import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from fixtures import configure_fixture_sources
from llm_backend import LLMBackend
from real_api_probe import (
    ProbeBlockedError,
    estimate_probe_budget,
    preflight_deepseek_probe,
    run_real_api_probe_with_preflight,
    write_probe_result_report,
)
from common import read_jsonl


def _cfg(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_real_api_probe.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path, per_category=4)
    cfg["experiment_name"] = "llm_generation_real_api_probe"
    cfg["context_window"] = 1000000
    cfg["rate_limit"] = "5 requests/minute"
    cfg["probe_budget_cap"] = 0.10
    cfg["backend"] = {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "top_p": 1.0,
        "max_output_tokens": 64,
        "timeout_seconds": 60,
        "max_retries": 0,
        "thinking": {"type": "disabled"},
        "cache_path": str(tmp_path / "probe_cache.json"),
    }
    cfg["pricing"] = {
        "cache_miss_input_per_1m_tokens": 0.14,
        "input_per_1m_tokens": 0.14,
        "output_per_1m_tokens": 0.28,
    }
    return cfg


def test_preflight_payload_and_reports_success(tmp_path, monkeypatch):
    captured = {"chat_body": None}

    class FakeResponse:
        def __init__(self, payload, status=200):
            self.payload = payload
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if url.endswith("/models"):
            return FakeResponse({"data": [{"id": "deepseek-v4-flash"}]})
        captured["chat_body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "choices": [{"message": {"content": "Fix null check"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            }
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    report = preflight_deepseek_probe(_cfg(tmp_path), reports_dir=tmp_path / "reports")
    assert report["passed"] is True
    assert report["available_model_match"] is True
    assert report["thinking_mode"] == "disabled"
    assert report["key_leakage_detected"] is False
    assert captured["chat_body"]["thinking"]["type"] == "disabled"
    report_files = list((tmp_path / "reports").glob("real_api_probe_preflight_*.json"))
    assert len(report_files) == 1
    combined = "\n".join(path.read_text() for path in (tmp_path / "reports").glob("*"))
    assert "secret-key-value" not in combined


def test_preflight_failure_blocks_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")

    def fake_preflight(config, reports_dir=Path("reports"), report_timestamp=None):
        return {"passed": False, "blocker": "model not found"}

    called = {"probe": False}

    def fake_runner(*args, **kwargs):
        called["probe"] = True
        return {}

    monkeypatch.setattr("real_api_probe.preflight_deepseek_probe", fake_preflight)
    monkeypatch.setattr("real_api_probe.run_generation_pilot", fake_runner)
    with pytest.raises(ProbeBlockedError, match="model not found"):
        run_real_api_probe_with_preflight(_cfg(tmp_path), output_root=tmp_path / "probe", reports_root=tmp_path / "reports")
    assert called["probe"] is False


def test_budget_over_limit_blocks_before_probe(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg["probe_budget_cap"] = 0.000001
    output_root = tmp_path / "probe"
    output_root.mkdir()
    (output_root / "prompts_rendered").mkdir()
    (output_root / "prompts_rendered" / "probe_prompt_summary.json").write_text(
        json.dumps({"estimated_input_token_count": 1000000})
    )
    with pytest.raises(ProbeBlockedError, match="budget"):
        estimate_probe_budget(cfg, output_root, enforce_cap=True)


def test_resume_after_real_probe_does_not_repeat_requests(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")

    def fake_preflight(config, reports_dir=Path("reports"), report_timestamp=None):
        return {"passed": True, "thinking_mode": "disabled"}

    call_count = {"n": 0}

    class FakeBackend:
        provider = "openai_compatible"
        model = "deepseek-v4-flash"
        thinking_mode = "disabled"

        def __init__(self, config, *, allow_real_api=False, dry_run=False):
            self.dry_run = dry_run

        def metadata(self):
            return {"provider": self.provider, "model": self.model, "thinking_mode": "disabled"}

        def generate(self, prompt):
            if self.dry_run:
                return {
                    "generated_subject": "",
                    "status": "skipped",
                    "failure_reason": "dry_run",
                    "latency_ms": 0,
                    "usage": {},
                    "cache_hit": False,
                    "retry_count": 0,
                    "http_status": 0,
                    "thinking_mode": "disabled",
                }
            call_count["n"] += 1
            return {
                "generated_subject": "Fix generated subject",
                "status": "generated",
                "failure_reason": "",
                "latency_ms": 1,
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                "cache_hit": False,
                "retry_count": 0,
                "http_status": 200,
            }

    monkeypatch.setattr("real_api_probe.preflight_deepseek_probe", fake_preflight)
    monkeypatch.setattr("run_generation_pilot.LLMBackend", FakeBackend)
    first = run_real_api_probe_with_preflight(cfg, output_root=tmp_path / "probe", reports_root=tmp_path / "reports")
    prompt_path = tmp_path / "probe" / "prompts_rendered" / "probe_prompts.jsonl"
    cache_backend = LLMBackend(cfg["backend"], allow_real_api=True, dry_run=False)
    generated_rows = {
        (row["sample_id"], row["strategy"]): row
        for row in read_jsonl(tmp_path / "probe" / "generations" / "real" / "generation_outputs.jsonl")
    }
    for prompt_row in read_jsonl(prompt_path):
        row = generated_rows[(prompt_row["sample_id"], prompt_row["strategy"])]
        cache_backend.cache[cache_backend._cache_key(prompt_row["prompt"])] = {
            "generated_subject": row["generated_subject"],
            "status": row["status"],
            "failure_reason": row["failure_reason"],
            "latency_ms": row["latency_ms"],
            "usage": row["usage"],
            "cache_hit": False,
            "retry_count": row["retry_count"],
            "http_status": row["http_status"],
            "thinking_mode": row["thinking_mode"],
        }
    cache_backend._save_cache()
    prompt_path.write_text("", encoding="utf-8")
    second = run_real_api_probe_with_preflight(
        cfg,
        output_root=tmp_path / "probe",
        skip_preflight=True,
        reports_root=tmp_path / "reports",
    )
    assert first["metadata"]["planned_request_count"] == 5
    assert first["result_report"]["actual_usage_available"] is True
    assert first["result_report"]["key_leakage_detected"] is False
    assert second["result_report"]["new_real_request_count"] == 0
    assert second["result_report"]["cache_hit_count"] == 5
    assert second["result_report"]["resume_skip_count"] >= 5
    assert second["result_report"]["manual_review_completed"] is False
    assert second["result_report"]["recommend_65_request_canary"] is False
    assert len(prompt_path.read_text(encoding="utf-8").splitlines()) == 5
    assert len(list((tmp_path / "reports").glob("real_api_probe_result_*.json"))) >= 1
    assert len(list((tmp_path / "reports").glob("real_api_probe_manual_review_*.csv"))) >= 1
    assert call_count["n"] == 5


def test_probe_result_report_contains_new_validity_and_leakage_fields(tmp_path):
    output_root = tmp_path / "probe"
    (output_root / "generations" / "real").mkdir(parents=True)
    (output_root / "dataset").mkdir(parents=True)
    (output_root / "retrieval_logs").mkdir(parents=True)
    (output_root / "generations" / "real" / "generation_outputs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "sample_id": "atomic_simple:a",
                        "status": "generated",
                        "generated_subject": "Fix null check",
                        "retry_count": 0,
                        "latency_ms": 1,
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                        "strategy": "G1",
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (output_root / "dataset" / "canary_all.jsonl").write_text(
        json.dumps({"sample_id": "atomic_simple:a", "data_category": "atomic_simple", "subject_reference": "Fix null check"}) + "\n",
        encoding="utf-8",
    )
    (output_root / "retrieval_logs" / "retrieval_logs.jsonl").write_text(
        json.dumps(
            {
                "query_sample_id": "synthetic_multi:b",
                "generation_strategy": "G4",
                "retrieval_quality_status": "usable_with_diagnostics",
                "low_similarity_warning": True,
                "leakage_checks": {
                    "same_repo_canonical": False,
                    "source_sha_overlap": False,
                    "diff_fingerprint_overlap": False,
                    "normalized_subject_overlap": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = write_probe_result_report({"manual_review_completed": False}, output_root, reports_root=tmp_path / "reports", report_timestamp="20260610T120000Z")
    assert report["probe_valid"] is False
    assert report["invalidated_by_repo_leakage"] is False
    assert report["same_repo_canonical_any"] is False
    assert report["retrieval_quality_summary"]["low_similarity_warning_count"] == 1
    assert report["automatic_gate_passed"] is False
    assert report["manual_review_completed"] is False
    assert report["recommend_65_request_canary"] is False
    assert report["reason"] == "pending_manual_review"
