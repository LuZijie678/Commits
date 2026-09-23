import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from common import read_jsonl
from fixtures import configure_fixture_sources
from run_generation_pilot import run_generation_pilot


def test_mock_pilot_runs_without_real_api(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    result = run_generation_pilot(cfg, output_root=tmp_path / "pilot")
    assert result["metadata"]["real_api_called"] is False
    rows = read_jsonl(tmp_path / "pilot" / "generations" / "mock" / "generation_outputs.jsonl")
    assert rows
    assert "data_category" in rows[0]
    assert any(row["strategy"] == "G5" and row["status"] == "skipped" for row in rows)


def test_dry_run_skips_backend_generation(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    run_generation_pilot(cfg, output_root=tmp_path / "pilot", dry_run=True)
    rows = read_jsonl(tmp_path / "pilot" / "generations" / "mock" / "generation_outputs.jsonl")
    assert any(row["failure_reason"] == "dry_run" for row in rows)
