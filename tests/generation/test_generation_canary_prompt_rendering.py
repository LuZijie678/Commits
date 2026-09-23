import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from run_generation_pilot import run_generation_pilot
from common import read_json, read_jsonl
from fixtures import configure_fixture_sources


def test_canary_dry_run_plans_65_and_g5_only_synthetic(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_canary.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    result = run_generation_pilot(cfg, output_root=tmp_path / "canary", dry_run=True)
    assert result["metadata"]["planned_request_count"] == 65
    rows = read_jsonl(tmp_path / "canary" / "generations" / "mock" / "generation_outputs.jsonl")
    assert len(rows) == 65
    g5_rows = [row for row in rows if row["strategy"] == "G5"]
    assert len(g5_rows) == 5
    assert all(row["failure_reason"] == "dry_run" for row in g5_rows)
    summary = read_json(tmp_path / "canary" / "prompts_rendered" / "canary_prompt_summary.json")
    assert summary["prompt_count"] == 65
    assert summary["strategy_distribution"]["G5"] == 5
    assert summary["truncation_count"] == 0
    assert summary["g5_oracle_only"] is True
