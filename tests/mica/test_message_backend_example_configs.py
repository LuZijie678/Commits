from __future__ import annotations

from code.mica.io_utils import read_json
from code.mica.llm_backend_config import validate_llm_backend_config


def test_example_llm_and_message_baseline_configs_exist_and_are_safely_disabled() -> None:
    llm_config = read_json("configs/mica/frozen_llm_renderer_openai_compatible.example.json")
    baseline_spec = read_json("configs/mica/message_baseline_generation_spec.example.json")
    llm_validation = validate_llm_backend_config(llm_config)
    llm_enabled_validation = validate_llm_backend_config(llm_config, require_enabled=True)
    baseline_validation = validate_llm_backend_config(baseline_spec["backend"])

    assert llm_config["enabled"] is False
    assert llm_config["provider"] == "openai_compatible"
    assert llm_config["base_url"]
    assert llm_config["api_key_env"]
    assert llm_config["model"]
    assert llm_config["thinking"]["type"] == "disabled"
    assert llm_validation["valid"] is True
    assert llm_enabled_validation["valid"] is False
    assert "backend_disabled" in llm_enabled_validation["errors"]

    assert baseline_spec["baselines"]
    assert baseline_spec["backend"]["enabled"] is False
    assert baseline_spec["backend"]["provider"] == "openai_compatible"
    assert baseline_spec["backend"]["api_key_env"]
    assert baseline_validation["valid"] is True
