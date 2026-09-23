import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from common import read_json, read_jsonl
from estimate_generation_canary_cost import estimate_canary_cost
from fixtures import configure_fixture_sources
from run_generation_pilot import run_generation_pilot


def _probe_cfg(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_real_api_probe.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path, per_category=4)
    cfg["backend"]["cache_path"] = str(tmp_path / "probe_cache.json")
    return cfg


def test_probe_plans_five_requests_and_four_categories(tmp_path):
    cfg = _probe_cfg(tmp_path)
    result = run_generation_pilot(cfg, output_root=tmp_path / "probe", dry_run=True)
    assert result["metadata"]["planned_request_count"] == 5
    assert result["metadata"]["dataset_manifest"]["selected_counts"] == {
        "atomic_simple": 1,
        "hard_b": 1,
        "synthetic_multi": 1,
        "M_real_multi": 1,
    }


def test_probe_g5_only_synthetic_and_retrieval_logs(tmp_path):
    cfg = _probe_cfg(tmp_path)
    run_generation_pilot(cfg, output_root=tmp_path / "probe", dry_run=True)
    rows = read_jsonl(tmp_path / "probe" / "generations" / "mock" / "generation_outputs.jsonl")
    g5_rows = [row for row in rows if row["strategy"] == "G5"]
    assert len(g5_rows) == 1
    samples = {row["sample_id"]: row for row in read_jsonl(tmp_path / "probe" / "dataset" / "canary_all.jsonl")}
    assert samples[g5_rows[0]["sample_id"]]["data_category"] == "synthetic_multi"
    logs = read_jsonl(tmp_path / "probe" / "retrieval_logs" / "retrieval_logs.jsonl")
    assert logs
    assert all(log["leakage_checks"]["same_repo"] is False for log in logs)
    assert all(log["leakage_checks"]["same_repo_canonical"] is False for log in logs)
    assert all(log["leakage_checks"]["source_sha_overlap"] is False for log in logs)


def test_probe_mock_cache_resume_and_no_key_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_TEST_SECRET", "sk-test-secret-value")
    cfg = _probe_cfg(tmp_path)
    first = run_generation_pilot(cfg, output_root=tmp_path / "probe")
    second = run_generation_pilot(cfg, output_root=tmp_path / "probe")
    assert first["metadata"]["planned_request_count"] == 5
    assert second["generation_count"] == 5
    rows = read_jsonl(tmp_path / "probe" / "generations" / "mock" / "generation_outputs.jsonl")
    assert len(rows) == 5
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in tmp_path.rglob("*") if path.is_file())
    assert "sk-test-secret-value" not in combined


def test_probe_cost_report_not_available_without_pricing(tmp_path):
    cfg = _probe_cfg(tmp_path)
    run_generation_pilot(cfg, output_root=tmp_path / "probe", dry_run=True)
    report = estimate_canary_cost(cfg, tmp_path / "probe", write_reports=False)
    assert report["planned_request_count"] == 5
    assert report["estimated_cost"] == "not_available"
    assert report["schema_version"] == "real_api_probe_execution_plan_v1"


def test_probe_real_api_missing_provider_model_key_env_fail_fast(tmp_path):
    cfg = _probe_cfg(tmp_path)
    cfg["backend"]["provider"] = ""
    cfg["backend"]["model"] = "m"
    with pytest.raises(RuntimeError, match="Missing provider"):
        run_generation_pilot(cfg, output_root=tmp_path / "missing_provider", allow_real_api=True)

    cfg = _probe_cfg(tmp_path)
    cfg["backend"]["provider"] = "openai_compatible"
    cfg["backend"]["model"] = ""
    with pytest.raises(RuntimeError, match="Missing model"):
        run_generation_pilot(cfg, output_root=tmp_path / "missing_model", allow_real_api=True)

    cfg = _probe_cfg(tmp_path)
    cfg["backend"]["provider"] = "openai_compatible"
    cfg["backend"]["model"] = "m"
    cfg["backend"]["api_key_env"] = ""
    with pytest.raises(RuntimeError, match="Missing api_key_env"):
        run_generation_pilot(cfg, output_root=tmp_path / "missing_key_env", allow_real_api=True)


def test_probe_output_roots_are_distinct(tmp_path):
    cfg = _probe_cfg(tmp_path)
    first = run_generation_pilot(cfg, output_root=tmp_path / "probe_a", dry_run=True)
    second = run_generation_pilot(cfg, output_root=tmp_path / "probe_b", dry_run=True)
    assert first["output_root"] != second["output_root"]
    assert read_json(tmp_path / "probe_a" / "run_metadata.json")["planned_request_count"] == 5
    assert read_json(tmp_path / "probe_b" / "run_metadata.json")["planned_request_count"] == 5
