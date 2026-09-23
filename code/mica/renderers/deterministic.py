from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from code.mica.consumers.pipeline import ConsumerPipeline
from code.mica.io_utils import read_jsonl, write_json, write_jsonl
from code.mica.schemas import DegradationDiagnostic, StructuredIntentPlan


@dataclass(slots=True)
class RenderedMessage:
    sample_id: str
    subject: str
    body: str
    bullets: list[str] = field(default_factory=list)
    degraded: bool = False
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    used_fallback_subject: bool = False
    status: str = "success"
    covered_slot_ids: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "subject": self.subject,
            "body": self.body,
            "bullets": list(self.bullets),
            "degraded": self.degraded,
            "diagnostics": list(self.diagnostics),
            "used_fallback_subject": self.used_fallback_subject,
            "status": self.status,
            "covered_slot_ids": list(self.covered_slot_ids),
            "verification": dict(self.verification),
            "fallback": dict(self.fallback),
        }


class DeterministicRenderer:
    def __init__(self, *, pipeline: ConsumerPipeline | None = None) -> None:
        self.pipeline = pipeline or ConsumerPipeline()

    def render(self, plan: StructuredIntentPlan, *, mode: str = "predicted_plan") -> RenderedMessage:
        diagnostics = [item.to_dict() if isinstance(item, DegradationDiagnostic) else dict(item) for item in plan.diagnostics]
        diagnostics.append({"code": "renderer_mode", "severity": "info", "message": mode, "metadata": {}})
        if plan.degraded and not plan.intents:
            diagnostics.append(
                {
                    "code": "legacy_degraded_empty_plan_fallback",
                    "severity": "warning",
                    "message": "Legacy degraded plan had no intents; renderer used conservative fallback.",
                    "metadata": {},
                }
            )
            return RenderedMessage(
                sample_id=plan.sample_id,
                subject="update related changes",
                body="",
                bullets=[],
                degraded=True,
                diagnostics=diagnostics,
                used_fallback_subject=True,
                status="invalid_plan",
                covered_slot_ids=[],
                verification={},
                fallback={"fallback_used": True, "fallback_level": "legacy_empty_plan"},
            )
        consumer_result = self.pipeline.generate(structured_plan=plan, mode="deterministic", verify=True)
        diagnostics.append(
            {
                "code": "consumer_pipeline_status",
                "severity": "info" if consumer_result.status == "success" else "warning",
                "message": "Consumer pipeline status for deterministic renderer.",
                "metadata": {"status": consumer_result.status, "errors": list(consumer_result.errors)},
            }
        )
        if consumer_result.status != "success" or consumer_result.message is None:
            diagnostics.append(
                {
                    "code": "consumer_pipeline_rejected",
                    "severity": "warning",
                    "message": "Deterministic renderer did not emit a normal commit message.",
                    "metadata": {"fallback": consumer_result.fallback, "verification": consumer_result.verification},
                }
            )
            return RenderedMessage(
                sample_id=plan.sample_id,
                subject="",
                body="",
                bullets=[],
                degraded=True,
                diagnostics=diagnostics,
                used_fallback_subject=False,
                status=consumer_result.status,
                covered_slot_ids=[],
                verification=consumer_result.verification,
                fallback=consumer_result.fallback,
            )
        message = consumer_result.message
        used_fallback = bool(consumer_result.fallback.get("fallback_used")) or any(
            summary.fallback_reason for summary in consumer_result.summaries
        )
        diagnostics.append(
            {
                "code": "consumer_pipeline_verification",
                "severity": "info",
                "message": "Verification diagnostics for deterministic renderer output.",
                "metadata": consumer_result.verification,
            }
        )
        if used_fallback:
            diagnostics.append(
                {
                    "code": "fallback_subject_used",
                    "severity": "info",
                    "message": "Renderer used a conservative fallback subject.",
                    "metadata": consumer_result.fallback,
                }
            )
        return RenderedMessage(
            sample_id=plan.sample_id,
            subject=message.subject,
            body="\n".join(message.body),
            bullets=(
                [line[2:] if line.startswith("- ") else line for line in message.body]
                if message.body
                else [
                    f"{summary.operation} {summary.target}".strip()
                    for summary in consumer_result.summaries
                    if len(consumer_result.summaries) > 1
                ]
            ),
            degraded=plan.degraded or used_fallback,
            diagnostics=diagnostics,
            used_fallback_subject=used_fallback,
            status=consumer_result.status,
            covered_slot_ids=list(message.covered_slot_ids),
            verification=consumer_result.verification,
            fallback=consumer_result.fallback,
        )

    def render_plan(self, plan: StructuredIntentPlan, *, mode: str = "predicted_plan") -> RenderedMessage:
        return self.render(plan, mode=mode)


def render_plan(plan: StructuredIntentPlan, *, mode: str = "predicted_plan", renderer: DeterministicRenderer | None = None) -> RenderedMessage:
    active_renderer = renderer or DeterministicRenderer()
    return active_renderer.render(plan, mode=mode)


def render_plans_from_jsonl(
    *,
    plan_jsonl: str | Any,
    output_jsonl: str | Any,
    mode: str = "predicted_plan",
    summary_json_path: str | Any | None = None,
    summary_md_path: str | Any | None = None,
    renderer: DeterministicRenderer | None = None,
) -> dict[str, Any]:
    rows = read_jsonl(plan_jsonl)
    active_renderer = renderer or DeterministicRenderer()
    rendered_rows = [active_renderer.render(StructuredIntentPlan.from_dict(row), mode=mode) for row in rows]
    write_jsonl(output_jsonl, [row.to_dict() for row in rendered_rows])
    summary = summarize_rendered_messages(rendered_rows)
    if summary_json_path is not None:
        write_json(summary_json_path, summary)
    if summary_md_path is not None:
        _write_renderer_summary_markdown(summary_md_path, summary)
    return summary


def summarize_rendered_messages(rendered_rows: list[RenderedMessage]) -> dict[str, Any]:
    diagnostic_histogram: Counter[str] = Counter()
    degraded_message_count = 0
    fallback_subject_count = 0
    bullet_count = 0
    rejected_message_count = 0

    for row in rendered_rows:
        if row.degraded:
            degraded_message_count += 1
        if row.used_fallback_subject:
            fallback_subject_count += 1
        if row.status != "success":
            rejected_message_count += 1
        bullet_count += len(row.bullets)
        for diagnostic in row.diagnostics:
            code = str(diagnostic.get("code"))
            diagnostic_histogram[code] += 1

    total_plans = len(rendered_rows)
    return {
        "total_plans": total_plans,
        "messages_rendered": total_plans,
        "degraded_message_count": degraded_message_count,
        "degraded_message_rate": (degraded_message_count / total_plans) if total_plans else 0.0,
        "fallback_subject_count": fallback_subject_count,
        "fallback_subject_rate": (fallback_subject_count / total_plans) if total_plans else 0.0,
        "rejected_message_count": rejected_message_count,
        "avg_bullet_count": (bullet_count / total_plans) if total_plans else 0.0,
        "diagnostic_histogram": dict(diagnostic_histogram),
    }


def _write_renderer_summary_markdown(path: str | Any, summary: dict[str, Any]) -> None:
    from pathlib import Path

    lines = [
        "# Deterministic Renderer Summary",
        "",
        f"- `total_plans`: {summary['total_plans']}",
        f"- `messages_rendered`: {summary['messages_rendered']}",
        f"- `degraded_message_count`: {summary['degraded_message_count']}",
        f"- `degraded_message_rate`: {summary['degraded_message_rate']:.6f}",
        f"- `fallback_subject_count`: {summary['fallback_subject_count']}",
        f"- `fallback_subject_rate`: {summary['fallback_subject_rate']:.6f}",
        f"- `rejected_message_count`: {summary['rejected_message_count']}",
        f"- `avg_bullet_count`: {summary['avg_bullet_count']:.6f}",
        "",
        "## Diagnostic Histogram",
        "",
    ]
    for code, count in sorted(summary["diagnostic_histogram"].items()):
        lines.append(f"- `{code}`: {count}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
