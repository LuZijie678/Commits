from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from common import read_json, read_jsonl, rel_path, repo_path, safe_text, tokenize, utc_timestamp
from repo_identity import describe_repo_identity


ARTIFACT_MARKERS = ["change 1", "intent 1", "```", "\n- ", "\n* "]
MANUAL_REVIEW_FIELDS = [
    "sample_id",
    "data_category",
    "strategy",
    "generated_subject",
    "reference_subject",
    "manual_format_ok",
    "manual_faithful",
    "manual_complete",
    "manual_concise",
    "manual_oversegmentation",
    "manual_omission",
    "manual_hallucination",
    "manual_oracle_plan_copying",
    "manual_retrieval_example_reasonable",
    "manual_prompt_defect_detected",
    "manual_overall_accept",
    "manual_confidence",
    "manual_failure_category",
    "notes",
    "reviewer",
    "reviewed_at",
]


def build_review_bundle(
    *,
    output_root: Path | None = None,
    probe_result_json: Path | None = None,
    existing_manual_review_csv: Path | None = None,
    reports_root: Path = repo_path("reports"),
    report_timestamp: str | None = None,
    bundle_prefix: str = "real_api_probe_manual_review_bundle",
    form_prefix: str = "real_api_probe_manual_review_form",
    mock_only: bool = False,
    real_generation_pending: bool = False,
) -> dict[str, Any]:
    output_root = output_root or _latest_probe_output_root()
    if probe_result_json is None and not mock_only:
        probe_result_json = _latest_report_json("real_api_probe_result_*.json", reports_root)
    existing_manual_review_csv = existing_manual_review_csv or _existing_manual_review_csv(probe_result_json, reports_root)
    report_timestamp = report_timestamp or utc_timestamp()

    records = load_probe_review_records(output_root=output_root, probe_result_json=probe_result_json)
    bundle_path = reports_root / f"{bundle_prefix}_{report_timestamp}.md"
    form_path = reports_root / f"{form_prefix}_{report_timestamp}.csv"
    _write_bundle_markdown(
        bundle_path,
        records,
        output_root=output_root,
        probe_result_json=probe_result_json,
        existing_manual_review_csv=existing_manual_review_csv,
        mock_only=mock_only,
        real_generation_pending=real_generation_pending,
    )
    _write_review_form(form_path, records)
    return {
        "output_root": output_root,
        "probe_result_json": probe_result_json,
        "existing_manual_review_csv": existing_manual_review_csv,
        "bundle_path": bundle_path,
        "form_path": form_path,
        "record_count": len(records),
    }


def load_probe_review_records(*, output_root: Path, probe_result_json: Path | None) -> list[dict[str, Any]]:
    samples = {row["sample_id"]: row for row in read_jsonl(output_root / "dataset" / "canary_all.jsonl")}
    generations = _load_generation_rows(output_root)
    prompts = {(row["sample_id"], row["strategy"]): row for row in read_jsonl(output_root / "prompts_rendered" / "probe_prompts.jsonl")}
    retrieval_logs = {
        (safe_text(row.get("query_sample_id")), safe_text(row.get("generation_strategy"))): row
        for row in read_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl")
    }
    exemplars = {row["exemplar_id"]: row for row in read_jsonl(output_root / "exemplar_pool" / "exemplar_pool.jsonl")}
    exclusion_path = output_root / "exemplar_pool" / "exemplar_pool_exclusion_log.jsonl"
    exclusion_rows = read_jsonl(exclusion_path) if exclusion_path.exists() else []
    run_metadata = read_json(output_root / "run_metadata.json")
    probe_result = read_json(probe_result_json) if probe_result_json else {}
    records: list[dict[str, Any]] = []
    for generation in generations:
        sample = samples[generation["sample_id"]]
        sample_repo_info = describe_repo_identity(sample.get("repo"))
        prompt_row = prompts.get((generation["sample_id"], generation["strategy"]), {})
        retrieval = retrieval_logs.get((generation["sample_id"], generation["strategy"]))
        canonical_exclusions = [
            row
            for row in exclusion_rows
            if sample_repo_info["canonical"]
            and safe_text(row.get("candidate_repo_canonical")) == sample_repo_info["canonical"]
            and "pilot_repo_canonical" in (row.get("reasons") or [])
        ]
        records.append(
            {
                "sample": sample,
                "sample_repo_identity": {
                    "original": sample_repo_info["original"],
                    "canonical": safe_text(sample.get("repo_canonical")) or sample_repo_info["canonical"],
                    "parse_status": safe_text(sample.get("repo_identity_parse_status")) or sample_repo_info["parse_status"],
                },
                "generation": generation,
                "prompt": safe_text(prompt_row.get("prompt")),
                "prompt_metadata": {
                    "chars": len(str(prompt_row.get("prompt", ""))),
                    "estimated_tokens": max(1, len(str(prompt_row.get("prompt", ""))) // 4) if prompt_row else 0,
                    "thinking_mode": safe_text(generation.get("thinking_mode")) or safe_text(run_metadata.get("thinking_mode")),
                    "latency_ms": int(generation.get("latency_ms", 0) or 0),
                    "usage": generation.get("usage", {}),
                    "status": safe_text(generation.get("status")),
                },
                "retrieval": retrieval or {},
                "retrieved_exemplars": [exemplars[ex_id] for ex_id in generation.get("retrieved_exemplar_ids", []) if ex_id in exemplars],
                "canonical_repo_exclusions": canonical_exclusions,
                "oracle_plan": _oracle_plan(sample) if generation.get("strategy") == "G5" else None,
                "auto_format": _auto_format_checks(generation),
                "diff_excerpt": _diff_excerpt(safe_text(sample.get("diff_text"))),
                "probe_result_summary": {
                    "api_success_rate": probe_result.get("api_success_rate"),
                    "single_line_rate": probe_result.get("single_line_rate"),
                    "key_leakage_detected": probe_result.get("key_leakage_detected"),
                },
            }
        )
    return records


def _write_bundle_markdown(
    path: Path,
    records: list[dict[str, Any]],
    *,
    output_root: Path,
    probe_result_json: Path | None,
    existing_manual_review_csv: Path | None,
    mock_only: bool,
    real_generation_pending: bool,
) -> None:
    lines = [
        "# Real API Probe Manual Review Bundle",
        "",
        f"- Frozen output root: `{rel_path(output_root)}`",
        f"- Probe result JSON: `{rel_path(probe_result_json) if probe_result_json else 'not_applicable'}`",
        f"- Existing manual review CSV: `{rel_path(existing_manual_review_csv) if existing_manual_review_csv else 'not_found'}`",
        f"- Record count: `{len(records)}`",
        f"- mock_only: `{mock_only}`",
        f"- real_generation_pending: `{real_generation_pending}`",
        "",
        "## Review Instructions",
        "",
        "This bundle is for human review only. Do not treat automatic checks as human judgment.",
        "",
        "Common checks:",
        "- Is the output a single-line commit subject?",
        "- Is it faithful to the diff and original commit message?",
        "- Does it omit any major independent change?",
        "- Does it assert behavior, motive, or effect that the diff does not support?",
        "",
        "Category-specific focus:",
        "- `atomic_simple / G1`: check whether the output captures the single main change and does not over-promote supporting tests.",
        "- `hard_b / G1`: check whether complex but single-purpose edits stay compressed into one purpose without fake splitting.",
        "- `synthetic_multi / G4`: check whether both intents are covered and whether retrieval examples appear relevant.",
        "- `synthetic_multi / G5`: compare against G4 for completeness and faithfulness; check whether the model copies the oracle plan mechanically.",
        "- `M_real_multi / G4`: check whether the output over-infers unstated motivation or effect from the diff alone.",
        "",
        "Special attention:",
        "- For `Refactor ComponentBase internals and flatten Surface cell storage for ABI stability`, verify whether `for ABI stability` is supported by diff or original message evidence.",
        "",
    ]
    for index, record in enumerate(records, 1):
        sample = record["sample"]
        generation = record["generation"]
        retrieval = record["retrieval"]
        diff_excerpt = record["diff_excerpt"]
        lines.extend(
            [
                f"## Record {index}",
                "",
                f"- Sample ID: `{sample['sample_id']}`",
                f"- Category: `{sample['data_category']}`",
                f"- Strategy: `{generation['strategy']}`",
                f"- Repo: `{sample['repo']}`",
                f"- Repo canonical: `{record['sample_repo_identity']['canonical']}`",
                f"- Repo parse status: `{record['sample_repo_identity']['parse_status']}`",
                f"- SHA: `{sample['sha']}`",
                f"- Generated subject: `{generation['generated_subject']}`",
                f"- Reference subject: `{sample['subject_reference']}`",
                "",
                "### Original Commit Message",
                "",
                "```text",
                safe_text(sample.get("message_reference")) or "(empty)",
                "```",
                "",
                "### Prompt Metadata",
                "",
                f"- Prompt chars: `{record['prompt_metadata']['chars']}`",
                f"- Estimated prompt tokens: `{record['prompt_metadata']['estimated_tokens']}`",
                f"- Status: `{record['prompt_metadata']['status']}`",
                f"- Thinking mode: `{record['prompt_metadata']['thinking_mode']}`",
                f"- Latency ms: `{record['prompt_metadata']['latency_ms']}`",
                f"- Usage: `{record['prompt_metadata']['usage']}`",
                "",
                "### Automatic Format Checks",
                "",
                f"- Non-empty: `{record['auto_format']['non_empty']}`",
                f"- Single line: `{record['auto_format']['single_line']}`",
                f"- Subject length chars: `{record['auto_format']['subject_length_chars']}`",
                f"- Subject length tokens: `{record['auto_format']['subject_length_tokens']}`",
                f"- Artifact markers present: `{record['auto_format']['artifact_markers_present']}`",
                "",
                "### Diff Excerpt",
                "",
                f"- Excerpted: `{diff_excerpt['excerpted']}`",
                "```diff",
                diff_excerpt["text"],
                "```",
                "",
            ]
        )
        if generation["strategy"] in {"G4", "G5"}:
            lines.extend(
                [
                    "### Retrieval Exemplars",
                    "",
                    f"- Retrieved exemplar IDs: `{generation.get('retrieved_exemplar_ids', [])}`",
                    f"- Similarity scores: `{retrieval.get('similarity_scores', [])}`",
                    f"- Retrieval quality status: `{retrieval.get('retrieval_quality_status', 'not_available')}`",
                    f"- Low similarity warning: `{retrieval.get('low_similarity_warning', 'not_available')}`",
                    f"- Repo guard exclusion count: `{retrieval.get('repo_guard_exclusion_count', 'not_available')}`",
                    f"- Leakage checks: `{retrieval.get('leakage_checks', {})}`",
                    "",
                ]
            )
            if record["canonical_repo_exclusions"]:
                lines.extend(
                    [
                        "- Canonical repo exclusions from exemplar pool:",
                    ]
                )
                for candidate in record["canonical_repo_exclusions"]:
                    lines.append(
                        "  - "
                        f"{candidate.get('candidate_id')} | "
                        f"{candidate.get('candidate_repo_original')} -> {candidate.get('candidate_repo_canonical')} | "
                        f"{candidate.get('reasons')}"
                    )
                lines.append("")
            for exemplar, score in zip(record["retrieved_exemplars"], retrieval.get("similarity_scores", [])):
                exemplar_repo_info = describe_repo_identity(exemplar.get("repo"))
                lines.extend(
                    [
                        f"- Exemplar `{exemplar['exemplar_id']}`",
                        f"  - Repo/SHA: `{exemplar['repo']}` / `{exemplar['sha']}`",
                        f"  - Repo canonical: `{safe_text(exemplar.get('repo_canonical')) or exemplar_repo_info['canonical']}`",
                        f"  - Subject: `{exemplar['subject']}`",
                        f"  - Similarity score: `{score}`",
                        f"  - Diff summary: `{safe_text(exemplar.get('diff_summary'))}`",
                    ]
                )
            if retrieval.get("repo_guard_excluded_candidates"):
                lines.extend(
                    [
                        "",
                        "- Canonical repo exclusions:",
                    ]
                )
                for candidate in retrieval.get("repo_guard_excluded_candidates", []):
                    lines.append(
                        "  - "
                        f"{candidate.get('candidate_id')} | "
                        f"{candidate.get('candidate_repo_original')} -> {candidate.get('candidate_repo_canonical')} | "
                        f"{candidate.get('reason')}"
                    )
            lines.append("")
        if generation["strategy"] == "G5" and record["oracle_plan"]:
            oracle = record["oracle_plan"]
            lines.extend(
                [
                    "### Oracle Intent Plan",
                    "",
                    f"- Oracle intent count: `{oracle['intent_count']}`",
                    f"- Oracle intent subjects: `{oracle['intent_subjects']}`",
                    f"- Oracle edit-to-intent: `{oracle['edit_to_intent']}`",
                    f"- Supporting edit note: `{oracle['supporting_edit_note']}`",
                    "",
                ]
            )
        lines.extend(
            [
                "### Human Review Questions",
                "",
                *[f"- {question}" for question in _review_questions(sample["data_category"], generation["strategy"])],
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_review_form(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_REVIEW_FIELDS)
        writer.writeheader()
        for record in records:
            sample = record["sample"]
            generation = record["generation"]
            writer.writerow(
                {
                    "sample_id": sample["sample_id"],
                    "data_category": sample["data_category"],
                    "strategy": generation["strategy"],
                    "generated_subject": generation["generated_subject"],
                    "reference_subject": sample["subject_reference"],
                    "manual_format_ok": "",
                    "manual_faithful": "",
                    "manual_complete": "",
                    "manual_concise": "",
                    "manual_oversegmentation": "",
                    "manual_omission": "",
                    "manual_hallucination": "",
                    "manual_oracle_plan_copying": "" if generation["strategy"] == "G5" else "not_applicable",
                    "manual_retrieval_example_reasonable": "" if generation["strategy"] in {"G4", "G5"} else "not_applicable",
                    "manual_prompt_defect_detected": "",
                    "manual_overall_accept": "",
                    "manual_confidence": "",
                    "manual_failure_category": "",
                    "notes": "",
                    "reviewer": "",
                    "reviewed_at": "",
                }
            )


def _auto_format_checks(generation: dict[str, Any]) -> dict[str, Any]:
    text = safe_text(generation.get("generated_subject"))
    return {
        "non_empty": bool(text),
        "single_line": bool(text) and "\n" not in text,
        "subject_length_chars": len(text),
        "subject_length_tokens": len(tokenize(text)),
        "artifact_markers_present": any(marker in text.lower() for marker in ARTIFACT_MARKERS),
    }


def _load_generation_rows(output_root: Path) -> list[dict[str, Any]]:
    real_path = output_root / "generations" / "real" / "generation_outputs.jsonl"
    mock_path = output_root / "generations" / "mock" / "generation_outputs.jsonl"
    if real_path.exists() and real_path.stat().st_size > 0:
        return read_jsonl(real_path)
    return read_jsonl(mock_path)


def _oracle_plan(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent_count": int(sample.get("intent_count", 0) or 0),
        "intent_subjects": sample.get("intent_subjects") or [],
        "edit_to_intent": sample.get("edit_to_intent") or {},
        "supporting_edit_note": "Use the structure as evidence. Do not copy the plan mechanically.",
    }


def _diff_excerpt(diff_text: str, *, max_chars: int = 12000) -> dict[str, Any]:
    diff_text = safe_text(diff_text)
    if len(diff_text) <= max_chars:
        return {"text": diff_text, "excerpted": False}
    excerpt_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith(("diff --git ", "--- ", "+++ ", "@@ ", "+", "-")):
            excerpt_lines.append(line)
    excerpt = "\n".join(excerpt_lines)
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 24].rstrip() + "\n... [excerpt truncated]"
    return {"text": excerpt, "excerpted": True}


def _review_questions(category: str, strategy: str) -> list[str]:
    questions = [
        "Does the output match single-line commit subject format?",
        "Is it faithful to the diff and original message?",
        "Does it omit any major change?",
        "Does it hallucinate any unsupported behavior, motive, or effect?",
    ]
    if category == "atomic_simple":
        questions.extend(
            [
                "Does it accurately express one main change?",
                "Does it incorrectly elevate supporting test edits into the main goal?",
            ]
        )
    elif category == "hard_b":
        questions.extend(
            [
                "Does it keep this complex but single-purpose change compressed into one purpose?",
                "Does it over-segment supporting edits into fake multiple goals?",
            ]
        )
    elif category == "synthetic_multi" and strategy == "G4":
        questions.extend(
            [
                "Does it cover both independent intents?",
                "Does it omit the secondary but still independent intent?",
                "Do the retrieved examples appear relevant, or does the output mechanically copy them?",
            ]
        )
    elif category == "synthetic_multi" and strategy == "G5":
        questions.extend(
            [
                "Is it more complete than the G4 output for the same sample?",
                "Is it more faithful than the G4 output for the same sample?",
                "Does it mechanically copy the oracle plan?",
                "Does the oracle plan skew the emphasis away from the actual diff?",
            ]
        )
    elif category == "M_real_multi":
        questions.extend(
            [
                "Does it cover the real major goals visible in the diff?",
                "Does it infer an unsupported rationale, especially phrases like `for ABI stability`?",
            ]
        )
    return questions


def _latest_probe_output_root() -> Path:
    candidates = sorted(path for path in repo_path("outputs").glob("llm_generation_real_api_probe_*") if path.is_dir())
    if not candidates:
        raise FileNotFoundError("No llm_generation_real_api_probe_* output root found")
    return candidates[-1]


def _latest_report_json(pattern: str, reports_root: Path) -> Path:
    candidates = sorted(reports_root.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No report matched {pattern}")
    return candidates[-1]


def _existing_manual_review_csv(probe_result_json: Path | None, reports_root: Path) -> Path | None:
    if not probe_result_json:
        return None
    try:
        payload = json.loads(probe_result_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    manual_review_path = payload.get("manual_review_path")
    if manual_review_path:
        candidate = repo_path(manual_review_path)
        if candidate.exists():
            return candidate
    candidates = sorted(reports_root.glob("real_api_probe_manual_review_*.csv"))
    return candidates[-1] if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root")
    parser.add_argument("--probe-result-json")
    parser.add_argument("--existing-manual-review-csv")
    parser.add_argument("--reports-root", default="reports")
    parser.add_argument("--bundle-prefix", default="real_api_probe_manual_review_bundle")
    parser.add_argument("--form-prefix", default="real_api_probe_manual_review_form")
    parser.add_argument("--mock-only", action="store_true")
    parser.add_argument("--real-generation-pending", action="store_true")
    args = parser.parse_args()
    result = build_review_bundle(
        output_root=repo_path(args.output_root) if args.output_root else None,
        probe_result_json=repo_path(args.probe_result_json) if args.probe_result_json else None,
        existing_manual_review_csv=repo_path(args.existing_manual_review_csv) if args.existing_manual_review_csv else None,
        reports_root=repo_path(args.reports_root),
        bundle_prefix=args.bundle_prefix,
        form_prefix=args.form_prefix,
        mock_only=args.mock_only,
        real_generation_pending=args.real_generation_pending,
    )
    print(
        json.dumps(
            {
                "bundle_path": rel_path(result["bundle_path"]),
                "form_path": rel_path(result["form_path"]),
                "record_count": result["record_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
