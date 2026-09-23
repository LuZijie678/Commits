from __future__ import annotations

from typing import Any


def validate_llm_backend_config(
    config: dict[str, Any],
    *,
    require_enabled: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(config, dict):
        return {"valid": False, "errors": ["config_must_be_mapping"], "warnings": warnings}

    provider = str(config.get("provider", "mock") or "mock").strip().lower()
    enabled = bool(config.get("enabled", True))
    if provider == "mock":
        return {"valid": True, "errors": errors, "warnings": warnings}

    for field_name in ("provider", "base_url", "api_key_env", "model", "cache_path"):
        if not str(config.get(field_name, "")).strip():
            errors.append(f"missing_{field_name}")

    thinking = config.get("thinking")
    if not isinstance(thinking, dict) or str(thinking.get("type", "")).strip().lower() != "disabled":
        errors.append("thinking_type_must_be_disabled")

    if require_enabled and not enabled:
        errors.append("backend_disabled")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
