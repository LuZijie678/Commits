import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from estimate_generation_canary_cost import estimate_canary_cost


def test_cost_estimate_marks_missing_price_not_available(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_canary.mock.json").read_text())
    report = estimate_canary_cost(cfg, output_root=tmp_path / "canary", write_reports=False)
    assert report["planned_request_count"] == 65
    assert report["estimated_cost"] == "not_available"
    assert report["cost_status"] == "requires_manual_provider_pricing"
    assert report["strategy_distribution"] == {"G0": 20, "G1": 20, "G4": 20, "G5": 5}


def test_prompt_strategy_template_plans_420_requests():
    cfg = json.loads(Path("configs/llm_generation_prompt_strategy_pilot.template.json").read_text())
    sizes = cfg["pilot_sample_size"]
    total = sum(sizes.values())
    synthetic = sizes["synthetic_multi"]
    assert total * 5 + synthetic == 420
