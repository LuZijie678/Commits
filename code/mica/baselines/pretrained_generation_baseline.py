from __future__ import annotations

from typing import Any

from code.mica.baselines.llm_prompting_baseline import (
    build_llm_prompting_manifest,
    coerce_structured_plan,
    render_mock_message_from_plan,
    render_plan_to_eval_payload,
)
from code.mica.llm_backend_config import validate_llm_backend_config


def build_pretrained_generation_manifest(*, model_name: str, sample: dict[str, Any]) -> dict[str, Any]:
    payload = build_llm_prompting_manifest(task_type="message", sample=sample)
    payload.update(
        {
            "model_name": model_name,
            "baseline_name": "pretrained_generation",
            "status": "external_reference",
        }
    )
    return payload


def run_pretrained_generation_baseline(
    plan_payload: dict[str, Any],
    *,
    backend_config: dict[str, Any],
    allow_real_api: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = coerce_structured_plan(plan_payload)
    eval_payload = render_plan_to_eval_payload(plan)
    if str(backend_config.get("provider", "mock")).strip().lower() == "mock":
        message = render_mock_message_from_plan(plan, style="pretrained_generation")
        return {
            **eval_payload,
            "message": message,
            "model_name": str(backend_config.get("model", "mock-model")),
            "generator_metadata": {
                "baseline": "pretrained_generation",
                "provider": "mock",
                "real_api_called": False,
                "dry_run": dry_run,
            },
        }

    validation = validate_llm_backend_config(backend_config, require_enabled=True)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    from code.generation.llm_backend import LLMBackend

    backend = LLMBackend(backend_config, allow_real_api=allow_real_api, dry_run=dry_run)
    prompt = _build_pretrained_prompt(plan)
    result = backend.generate(prompt)
    return {
        **eval_payload,
        "message": str(result.get("generated_subject", "")).strip(),
        "model_name": str(backend_config.get("model", "")),
        "generator_metadata": {
            "baseline": "pretrained_generation",
            "provider": str(backend_config.get("provider", "")),
            "status": result.get("status"),
            "real_api_called": bool(allow_real_api and str(backend_config.get("provider", "")) != "mock" and not dry_run),
            "usage": dict(result.get("usage", {})),
            "http_status": result.get("http_status"),
        },
    }


def _build_pretrained_prompt(plan) -> str:  # type: ignore[no-untyped-def]
    lines = [
        "Write one imperative subject line from the evidence terms below.",
        "Use only the listed files, symbols, and identifiers.",
        "Return only the subject line.",
        "",
        "Evidence terms:",
    ]
    payload = render_plan_to_eval_payload(plan)
    lines.append(", ".join(payload["evidence_terms"]))
    lines.append("")
    lines.append("Avoid unsupported claims about performance, security, crash prevention, or reliability.")
    return "\n".join(lines).strip() + "\n"
