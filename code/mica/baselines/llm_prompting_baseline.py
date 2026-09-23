from __future__ import annotations

from typing import Any

from code.mica.consumers.evidence_summarizer import DeterministicEvidenceSummarizer
from code.mica.consumers.plan_schema import StructuredIntentPlan as ConsumerStructuredIntentPlan
from code.mica.consumers.plan_schema import adapt_from_legacy_plan
from code.mica.llm_backend_config import validate_llm_backend_config
from code.mica.schemas import StructuredIntentPlan as LegacyStructuredIntentPlan


def build_llm_prompting_manifest(*, task_type: str, sample: dict[str, Any]) -> dict[str, Any]:
    prompt = _build_prompt(task_type=task_type, sample=sample)
    return {
        "task_type": task_type,
        "sample_id": sample.get("sample_id"),
        "prompt": prompt,
        "api_execution_enabled": False,
        "requires_manual_or_external_execution": True,
    }


def _build_prompt(*, task_type: str, sample: dict[str, Any]) -> str:
    if task_type == "alignment":
        return f"Group the edit units for sample {sample.get('sample_id')} into intents without inventing unsupported evidence."
    if task_type == "message":
        return f"Write a grounded commit message for sample {sample.get('sample_id')} using only assigned evidence."
    return f"Predict the count or binary multi-intent label for sample {sample.get('sample_id')}."


def coerce_structured_plan(plan_payload: dict[str, Any] | ConsumerStructuredIntentPlan | LegacyStructuredIntentPlan) -> ConsumerStructuredIntentPlan:
    if isinstance(plan_payload, ConsumerStructuredIntentPlan):
        return plan_payload
    if isinstance(plan_payload, LegacyStructuredIntentPlan):
        return adapt_from_legacy_plan(plan_payload)
    if "decision" in plan_payload:
        return ConsumerStructuredIntentPlan.from_dict(plan_payload)
    return adapt_from_legacy_plan(plan_payload)


def render_mock_message_from_plan(
    plan_payload: dict[str, Any] | ConsumerStructuredIntentPlan | LegacyStructuredIntentPlan,
    *,
    style: str,
) -> str:
    plan = coerce_structured_plan(plan_payload)
    summaries = [DeterministicEvidenceSummarizer().summarize(intent) for intent in plan.intents]
    if not summaries:
        return ""
    first = summaries[0]
    if style == "pretrained_generation":
        return f"{first.operation} {first.scope or first.target}".strip()
    return f"{first.operation} {first.target}".strip()


def render_plan_to_eval_payload(
    plan_payload: dict[str, Any] | ConsumerStructuredIntentPlan | LegacyStructuredIntentPlan,
) -> dict[str, Any]:
    plan = coerce_structured_plan(plan_payload)
    summaries = [DeterministicEvidenceSummarizer().summarize(intent) for intent in plan.intents]
    evidence_terms: list[str] = []
    simplified_intents: list[dict[str, Any]] = []
    for summary in summaries:
        simplified_intents.append(
            {
                "subject": f"{summary.operation} {summary.target}".strip(),
                "type": summary.operation,
                "scope": summary.scope,
                "body": "; ".join(summary.supporting_changes),
            }
        )
        evidence_terms.extend(summary.evidence_entities)
        evidence_terms.extend(summary.evidence_unit_ids)
    deduped_terms = []
    seen: set[str] = set()
    for term in evidence_terms:
        normalized = str(term).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped_terms.append(normalized)
    return {
        "sample_id": plan.sample_id,
        "commit_id": plan.commit_id,
        "structured_intent_plan": {"intents": simplified_intents, "source": plan.metadata.get("plan_source", "predicted_plan")},
        "evidence_terms": deduped_terms,
        "plan_source": str(plan.metadata.get("plan_source", "predicted")),
        "proxy_not_human_eval": True,
    }


def run_llm_prompting_baseline(
    plan_payload: dict[str, Any] | ConsumerStructuredIntentPlan | LegacyStructuredIntentPlan,
    *,
    backend_config: dict[str, Any],
    allow_real_api: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = coerce_structured_plan(plan_payload)
    eval_payload = render_plan_to_eval_payload(plan)
    provider = str(backend_config.get("provider", "mock")).strip().lower()
    if provider == "mock":
        return {
            **eval_payload,
            "message": render_mock_message_from_plan(plan, style="llm_prompting"),
            "model_name": str(backend_config.get("model", "mock-model")),
            "generator_metadata": {
                "baseline": "llm_prompting",
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
    prompt = _build_message_prompt(plan)
    result = backend.generate(prompt)
    return {
        **eval_payload,
        "message": str(result.get("generated_subject", "")).strip(),
        "model_name": str(backend_config.get("model", "")),
        "generator_metadata": {
            "baseline": "llm_prompting",
            "provider": provider,
            "status": result.get("status"),
            "real_api_called": bool(allow_real_api and provider != "mock" and not dry_run),
            "usage": dict(result.get("usage", {})),
            "http_status": result.get("http_status"),
        },
    }


def _build_message_prompt(plan: ConsumerStructuredIntentPlan) -> str:
    summaries = [DeterministicEvidenceSummarizer().summarize(intent) for intent in plan.intents]
    lines = [
        "Write one imperative subject line using only the structured plan below.",
        "Do not use any raw diff, commit message, PR title, issue text, gold label, or synthetic metadata.",
        "Do not claim performance, security, crash prevention, reliability, or breaking change unless directly supported.",
        "Return only the subject line.",
        "",
        "Structured intents:",
    ]
    for index, summary in enumerate(summaries, 1):
        lines.append(f"{index}. operation: {summary.operation}")
        lines.append(f"   target: {summary.target}")
        lines.append(f"   scope: {summary.scope}")
        if summary.supporting_changes:
            lines.append(f"   supporting changes: {'; '.join(summary.supporting_changes[:3])}")
        if summary.evidence_entities:
            lines.append(f"   evidence entities: {', '.join(summary.evidence_entities[:8])}")
    return "\n".join(lines).strip() + "\n"
