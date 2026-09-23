from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .common import repo_path, safe_text
except ImportError:  # pragma: no cover - compatibility for direct script imports in legacy tests/tools.
    from common import repo_path, safe_text


class LLMBackend:
    def __init__(self, config: dict[str, Any], *, allow_real_api: bool = False, dry_run: bool = False) -> None:
        self.config = config
        self.allow_real_api = allow_real_api
        self.dry_run = dry_run
        self.provider = safe_text(config.get("provider", "mock"))
        self.model = safe_text(config.get("model", "mock-model"))
        if self.provider != "mock" and self.allow_real_api and not self.dry_run:
            if not self.provider:
                raise RuntimeError("Missing provider")
            if not self.model:
                raise RuntimeError("Missing model")
            if not safe_text(config.get("api_key_env")):
                raise RuntimeError("Missing api_key_env")
        self.cache_path = repo_path(config.get("cache_path", "outputs/llm_generation_cache.json"))
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, Any] = {}
        if self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "thinking_mode": self.thinking_mode,
        }

    @property
    def thinking_mode(self) -> str:
        thinking = self.config.get("thinking") or {}
        if isinstance(thinking, dict):
            return safe_text(thinking.get("type")) or "unspecified"
        return "unspecified"

    def _thinking_payload(self) -> dict[str, Any]:
        thinking = self.config.get("thinking") or {}
        if not isinstance(thinking, dict) or safe_text(thinking.get("type")) != "disabled":
            raise RuntimeError("Real API generation requires thinking.type=disabled")
        return {"type": "disabled"}

    def _cache_key(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "provider": self.provider,
                "model": self.model,
                "temperature": self.config.get("temperature"),
                "top_p": self.config.get("top_p"),
                "max_output_tokens": self.config.get("max_output_tokens"),
                "thinking": {"type": self.thinking_mode},
                "prompt": prompt,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def generate(self, prompt: str) -> dict[str, Any]:
        key = self._cache_key(prompt)
        if self.dry_run:
            return {
                "generated_subject": "",
                "status": "skipped",
                "failure_reason": "dry_run",
                "latency_ms": 0,
                "usage": {},
                "cache_hit": False,
                "retry_count": 0,
                "http_status": 0,
                "thinking_mode": self.thinking_mode,
            }
        if key in self.cache:
            cached = dict(self.cache[key])
            cached["cache_hit"] = True
            return cached
        if self.provider == "mock":
            subject = self._mock_subject(prompt)
            result = {
                "generated_subject": subject,
                "status": "generated",
                "failure_reason": "",
                "latency_ms": 0,
                "usage": {"prompt_chars": len(prompt), "completion_chars": len(subject)},
                "cache_hit": False,
                "retry_count": 0,
                "http_status": 0,
                "thinking_mode": self.thinking_mode,
            }
            self.cache[key] = result
            self._save_cache()
            return result
        if not self.allow_real_api:
            raise RuntimeError("Real API calls are disabled. Pass --allow-real-api explicitly.")
        result = self._openai_compatible(prompt)
        self.cache[key] = result
        self._save_cache()
        return result

    @staticmethod
    def _mock_subject(prompt: str) -> str:
        for marker in ["Reference subject:", "Subject:"]:
            if marker in prompt:
                text = prompt.split(marker, 1)[1].splitlines()[0].strip()
                if text:
                    return text[:120]
        for line in prompt.splitlines():
            if line.startswith("+") and len(line.strip(" +")) > 8:
                return "Update implementation based on diff"
        return "Summarize commit changes"

    def _openai_compatible(self, prompt: str) -> dict[str, Any]:
        api_env = safe_text(self.config.get("api_key_env"))
        api_key = os.environ.get(api_env, "") if api_env else ""
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {api_env}")
        base_url = safe_text(self.config.get("base_url")).rstrip("/")
        if not base_url:
            raise RuntimeError("Missing openai-compatible base_url")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(self.config.get("temperature", 0.2)),
            "top_p": float(self.config.get("top_p", 1.0)),
            "max_tokens": int(self.config.get("max_output_tokens", 64)),
            "thinking": self._thinking_payload(),
        }
        timeout = int(self.config.get("timeout_seconds", 60))
        retries = int(self.config.get("max_retries", 2))
        start = time.time()
        last_error = ""
        last_http_status = 0
        for attempt in range(retries + 1):
            try:
                request = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    http_status = int(getattr(response, "status", 200))
                    payload = json.loads(response.read().decode("utf-8"))
                content = safe_text(payload["choices"][0]["message"]["content"]).splitlines()[0]
                return {
                    "generated_subject": content,
                    "status": "generated",
                    "failure_reason": "",
                    "latency_ms": int((time.time() - start) * 1000),
                    "usage": payload.get("usage", {}),
                    "cache_hit": False,
                    "retry_count": attempt,
                    "http_status": http_status,
                    "thinking_mode": self.thinking_mode,
                }
            except urllib.error.HTTPError as exc:
                last_http_status = int(exc.code)
                last_error = f"HTTP {exc.code}: {safe_text(exc.reason)}"
                if attempt < retries and exc.code not in {401, 402, 404, 429}:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return {
                    "generated_subject": "",
                    "status": "failed",
                    "failure_reason": last_error,
                    "latency_ms": int((time.time() - start) * 1000),
                    "usage": {},
                    "cache_hit": False,
                    "retry_count": attempt,
                    "http_status": last_http_status,
                    "thinking_mode": self.thinking_mode,
                }
            except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
        return {
            "generated_subject": "",
            "status": "failed",
            "failure_reason": last_error,
            "latency_ms": int((time.time() - start) * 1000),
            "usage": {},
            "cache_hit": False,
            "retry_count": retries,
            "http_status": last_http_status,
            "thinking_mode": self.thinking_mode,
        }
