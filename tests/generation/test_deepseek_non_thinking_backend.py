import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from llm_backend import LLMBackend


def test_openai_compatible_payload_includes_disabled_thinking(tmp_path, monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "Fix null check"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.headers)
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_TEST_KEY",
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "top_p": 1.0,
        "max_output_tokens": 64,
        "thinking": {"type": "disabled"},
        "cache_path": str(tmp_path / "cache.json"),
    }
    result = LLMBackend(cfg, allow_real_api=True).generate("Write one subject")
    assert result["status"] == "generated"
    assert captured["body"]["thinking"]["type"] == "disabled"
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["top_p"] == 1.0
    assert captured["body"]["max_tokens"] == 64
    assert "secret-key-value" not in json.dumps(result)
    assert "secret-key-value" not in (tmp_path / "cache.json").read_text()


def test_real_api_requires_explicit_disabled_thinking(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-key-value")
    cfg = {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_TEST_KEY",
        "model": "deepseek-v4-flash",
        "cache_path": str(tmp_path / "cache.json"),
    }
    backend = LLMBackend(cfg, allow_real_api=True)
    with pytest.raises(RuntimeError, match="thinking.type=disabled"):
        backend.generate("Write one subject")


def test_backend_metadata_records_disabled_thinking_without_key(tmp_path):
    cfg = {
        "provider": "mock",
        "model": "mock-model",
        "thinking": {"type": "disabled"},
        "api_key_env": "DEEPSEEK_TEST_KEY",
        "cache_path": str(tmp_path / "cache.json"),
    }
    metadata = LLMBackend(cfg).metadata()
    assert metadata["thinking_mode"] == "disabled"
    assert "DEEPSEEK_TEST_KEY" not in json.dumps(metadata)
    assert "api_key" not in json.dumps(metadata).lower()
