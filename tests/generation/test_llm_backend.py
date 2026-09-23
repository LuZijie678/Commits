import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from llm_backend import LLMBackend


def test_mock_backend_caches(tmp_path):
    cfg = {"provider": "mock", "model": "m", "cache_path": str(tmp_path / "cache.json")}
    backend = LLMBackend(cfg)
    first = backend.generate("Subject: add parser")
    second = backend.generate("Subject: add parser")
    assert first["generated_subject"] == "add parser"
    assert second["cache_hit"] is True
    assert "api" not in json.dumps(second).lower()


def test_real_api_blocked_without_flag(tmp_path):
    cfg = {"provider": "openai_compatible", "model": "m", "cache_path": str(tmp_path / "cache.json")}
    backend = LLMBackend(cfg, allow_real_api=False)
    with pytest.raises(RuntimeError):
        backend.generate("hello")


def test_real_api_does_not_retry_402(tmp_path, monkeypatch):
    attempts = {"n": 0}

    def fake_urlopen(request, timeout=0):
        attempts["n"] += 1
        raise urllib.error.HTTPError(request.full_url, 402, "Payment Required", hdrs=None, fp=None)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key-value")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = {
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
        "max_retries": 2,
        "thinking": {"type": "disabled"},
        "cache_path": str(tmp_path / "cache.json"),
    }
    result = LLMBackend(cfg, allow_real_api=True).generate("Write one subject")
    assert attempts["n"] == 1
    assert result["status"] == "failed"
    assert result["http_status"] == 402
    assert result["retry_count"] == 0
