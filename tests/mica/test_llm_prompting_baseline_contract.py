from __future__ import annotations

from code.mica.baselines.llm_prompting_baseline import build_llm_prompting_manifest


def test_llm_prompting_manifest_stays_api_disabled() -> None:
    manifest = build_llm_prompting_manifest(task_type="alignment", sample={"sample_id": "s1"})

    assert manifest["api_execution_enabled"] is False
    assert manifest["requires_manual_or_external_execution"] is True
    assert "prompt" in manifest
