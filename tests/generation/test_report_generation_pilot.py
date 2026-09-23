import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from evaluate_generation_outputs import evaluate_outputs
from fixtures import configure_fixture_sources
from report_generation_pilot import write_report
from run_generation_pilot import run_generation_pilot


def test_report_written(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    run_generation_pilot(cfg, output_root=tmp_path / "pilot")
    evaluate_outputs(tmp_path / "pilot")
    path = write_report(tmp_path / "pilot")
    assert path.exists()
    assert "Real API called: `False`" in path.read_text()
