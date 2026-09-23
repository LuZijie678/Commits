import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from common import read_jsonl
from evaluate_generation_outputs import evaluate_outputs
from fixtures import configure_fixture_sources
from report_generation_pilot import write_report
from run_generation_pilot import run_generation_pilot


def test_mock_canary_runs_cache_and_resume(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_canary.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["backend"]["cache_path"] = str(tmp_path / "cache.json")
    first = run_generation_pilot(cfg, output_root=tmp_path / "canary")
    second = run_generation_pilot(cfg, output_root=tmp_path / "canary")
    assert first["metadata"]["planned_request_count"] == 65
    assert second["generation_count"] == 65
    rows = read_jsonl(tmp_path / "canary" / "generations" / "mock" / "generation_outputs.jsonl")
    assert len(rows) == 65
    assert all(row["strategy"] != "G5" or row["status"] == "generated" for row in rows)
    logs = read_jsonl(tmp_path / "canary" / "retrieval_logs" / "retrieval_logs.jsonl")
    assert logs
    assert {"query_sample_id", "retrieved_exemplar_ids", "leakage_checks"} <= set(logs[0])
    evaluation = evaluate_outputs(tmp_path / "canary", run_kind="mock")
    assert "strategy_metrics" in evaluation
    report = write_report(tmp_path / "canary", run_kind="mock")
    assert report.exists()
