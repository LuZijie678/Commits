#!/usr/bin/env python3
"""Label M-candidate batches with an OpenAI-compatible chat completion API."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

REAL_DIFF_MARKER = "diff --git "
DEFAULT_API_KEY_FILE = Path(__file__).resolve().parents[4] / ".llm_api_key"

OUTPUT_FIELDS = [
    "repo",
    "sha",
    "commit_url",
    "language",
    "commit_date",
    "subject",
    "commit_message",
    "candidate_layer",
    "m_candidate_score",
    "m_candidate_reasons",
    "llm_label",
    "llm_is_multi_intent",
    "llm_reason",
    "llm_intent_count_estimate",
    "llm_intent_summaries",
    "llm_evidence_from_message",
    "llm_evidence_from_diff",
    "llm_uncertainty",
    "llm_model",
    "llm_created_at_utc",
    "llm_error",
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
]

SYSTEM_PROMPT = """You label code commits into exactly one class:
- A: single intent, relatively focused / narrow.
- B: single intent, but broader / more complex implementation scope.
- M: multiple independent intents in one commit.
- U: uncertain from the available evidence.

Return JSON only with keys:
label, reason, uncertainty, intent_count_estimate, intent_summaries, evidence_from_message, evidence_from_diff

Rules:
- Use M only when there are at least two meaningfully independent purposes.
- Multiple files, tests, cleanup, or review fixes alone do not imply M.
- If the commit has one coherent main purpose with broad implementation, prefer B.
- intent_summaries must be a JSON array of short strings.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_csv_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def append_jsonl_row(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_output_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    keys: set[tuple[str, str]] = set()
    for row in read_csv(path):
        repo = str(row.get("repo") or "")
        sha = str(row.get("sha") or "")
        if repo and sha:
            keys.add((repo, sha))
    return keys


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return str(row.get("repo") or ""), str(row.get("sha") or "")


def has_real_diff(text: str) -> bool:
    return REAL_DIFF_MARKER in (text or "")


def normalize_intent_summaries(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]
    return []


def extract_json_object(raw: str) -> dict:
    text = raw.strip()
    fenced_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    candidates = fenced_matches + [text]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        source = candidate.strip()
        if not source:
            continue
        start = 0
        while True:
            brace = source.find("{", start)
            if brace < 0:
                break
            try:
                parsed, _ = decoder.raw_decode(source[brace:])
            except json.JSONDecodeError:
                start = brace + 1
                continue
            if isinstance(parsed, dict):
                return parsed
            start = brace + 1
    raise ValueError("no_json_object_found")


def parse_label_response(raw: str) -> dict[str, object]:
    parsed = extract_json_object(raw)
    label = str(parsed.get("label") or parsed.get("final_label") or "").strip().upper()
    if label not in {"A", "B", "M", "U"}:
        if parsed.get("is_multi_intent") is True:
            label = "M"
        else:
            raise ValueError(f"unsupported_label: {label or '<empty>'}")
    intent_count = parsed.get("intent_count_estimate")
    if intent_count in ("", None):
        intent_count = 2 if label == "M" else 1 if label in {"A", "B"} else 0
    try:
        intent_count_int = int(intent_count)
    except (TypeError, ValueError):
        intent_count_int = 2 if label == "M" else 1 if label in {"A", "B"} else 0
    return {
        "label": label,
        "reason": str(parsed.get("reason") or "").strip(),
        "uncertainty": str(parsed.get("uncertainty") or "medium").strip().lower(),
        "intent_count_estimate": intent_count_int,
        "intent_summaries": normalize_intent_summaries(parsed.get("intent_summaries")),
        "evidence_from_message": str(parsed.get("evidence_from_message") or "").strip(),
        "evidence_from_diff": str(parsed.get("evidence_from_diff") or "").strip(),
    }


def evidence_mode_for(row: dict[str, str]) -> str:
    if row.get("_evidence_mode"):
        return str(row["_evidence_mode"])
    if row.get("evidence_mode"):
        return str(row["evidence_mode"])
    if row.get("diff_status") == "ok" or has_real_diff(str(row.get("git_diff") or "")):
        return "diff"
    return "unknown"


def needs_diff_verify(row: dict[str, str], evidence_mode: str) -> str:
    if evidence_mode in {"diff", "diff_or_diff_preferred"}:
        return "0"
    if row.get("diff_status") == "ok" and has_real_diff(str(row.get("git_diff") or "")):
        return "0"
    return "1"


def build_labeled_row(
    source_row: dict[str, str],
    label_result: dict[str, object],
    *,
    model_name: str,
    created_at_utc: str,
    source_file: str,
) -> dict[str, str]:
    evidence_mode = evidence_mode_for(source_row)
    label = str(label_result.get("label") or "").upper()
    intent_summaries = normalize_intent_summaries(label_result.get("intent_summaries"))
    row = {
        "repo": str(source_row.get("repo") or ""),
        "sha": str(source_row.get("sha") or "").lower(),
        "commit_url": str(source_row.get("commit_url") or ""),
        "language": str(source_row.get("language") or ""),
        "commit_date": str(source_row.get("commit_date") or ""),
        "subject": str(source_row.get("subject") or ""),
        "commit_message": str(source_row.get("commit_message") or ""),
        "candidate_layer": str(source_row.get("candidate_layer") or ""),
        "m_candidate_score": str(source_row.get("m_candidate_score") or ""),
        "m_candidate_reasons": str(source_row.get("m_candidate_reasons") or ""),
        "llm_label": label,
        "llm_is_multi_intent": "True" if label == "M" else "False",
        "llm_reason": str(label_result.get("reason") or ""),
        "llm_intent_count_estimate": str(label_result.get("intent_count_estimate") or ""),
        "llm_intent_summaries": "; ".join(intent_summaries),
        "llm_evidence_from_message": str(label_result.get("evidence_from_message") or source_row.get("subject") or ""),
        "llm_evidence_from_diff": str(label_result.get("evidence_from_diff") or source_row.get("shortstat") or ""),
        "llm_uncertainty": str(label_result.get("uncertainty") or ""),
        "llm_model": model_name,
        "llm_created_at_utc": created_at_utc,
        "llm_error": str(label_result.get("error") or ""),
        "_source_file": source_file,
        "_evidence_mode": evidence_mode,
        "_needs_diff_verify": needs_diff_verify(source_row, evidence_mode),
    }
    return {field: row.get(field, "") for field in OUTPUT_FIELDS}


def compact_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n\n[... truncated {omitted} chars ...]\n\n" + text[-tail:]


def build_user_prompt(row: dict[str, str], diff_max_chars: int) -> str:
    diff = compact_text(str(row.get("git_diff") or ""), diff_max_chars)
    changed_files = compact_text(str(row.get("changed_files") or ""), 4000)
    shortstat = str(row.get("shortstat") or "")
    return (
        "Classify this commit.\n\n"
        f"repo: {row.get('repo', '')}\n"
        f"sha: {row.get('sha', '')}\n"
        f"subject: {row.get('subject', '')}\n"
        f"commit_message:\n{row.get('commit_message', '')}\n\n"
        f"candidate_score: {row.get('m_candidate_score', '')}\n"
        f"candidate_reasons: {row.get('m_candidate_reasons', '')}\n"
        f"shortstat: {shortstat}\n"
        f"changed_files:\n{changed_files}\n\n"
        f"git_diff:\n{diff}\n"
    )


def response_text(payload: dict) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            if parts:
                return "\n".join(parts)
    raise ValueError("missing_chat_completion_text")


def ensure_api_key(args: argparse.Namespace) -> str:
    path = Path(args.api_key_file)
    if not path.exists():
        raise RuntimeError(f"missing_api_key_file: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"empty_api_key_file: {path}")
    return token


def post_json(url: str, body: dict, api_key: str, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "multi-intent-research-labeler",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def label_with_model(row: dict[str, str], args: argparse.Namespace, api_key: str) -> dict[str, str]:
    prompt = build_user_prompt(row, args.diff_max_chars)
    body = {
        "model": args.model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    last_error = ""
    for attempt in range(1, args.attempts + 1):
        try:
            payload = post_json(args.endpoint, body, api_key, args.timeout)
            parsed = parse_label_response(response_text(payload))
            return build_labeled_row(
                row,
                parsed,
                model_name=args.model,
                created_at_utc=utc_now(),
                source_file=str(args.output_csv),
            )
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < args.attempts:
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(last_error or "label_request_failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label remote-diff M candidate batches with an LLM.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--endpoint", default="https://api.openai.com/v1/chat/completions")
    parser.add_argument("--api-key-file", type=Path, default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--diff-max-chars", type=int, default=16000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = ensure_api_key(args)
    rows = read_csv(args.input_csv)
    if args.limit > 0:
        rows = rows[: args.limit]
    existing_rows = read_csv(args.output_csv) if args.resume and args.output_csv.exists() else []
    output_keys = load_output_keys(args.output_csv) if args.resume else set()

    pending: list[tuple[int, dict[str, str]]] = []
    seen_keys = set(output_keys)
    resume_skipped = 0
    dedupe_skipped = 0
    for index, row in enumerate(rows):
        key = row_key(row)
        if not key[0] or not key[1]:
            continue
        if key in output_keys:
            resume_skipped += 1
            continue
        if key in seen_keys:
            dedupe_skipped += 1
            continue
        pending.append((index, row))
        seen_keys.add(key)

    results_by_index: dict[int, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    completed = 0

    def record_result(index: int, labeled_row: dict[str, str]) -> None:
        nonlocal completed
        results_by_index[index] = labeled_row
        completed += 1
        append_csv_row(args.output_csv, labeled_row)
        append_jsonl_row(args.output_jsonl, labeled_row)
        if completed % 10 == 0:
            print(
                f"labeled={completed} pending={len(pending) - completed} resume_skipped={resume_skipped} dedupe_skipped={dedupe_skipped}",
                flush=True,
            )

    if int(args.workers) <= 1:
        for index, row in pending:
            try:
                record_result(index, label_with_model(row, args, api_key))
            except RuntimeError as exc:
                errors.append({"repo": row.get("repo", ""), "sha": row.get("sha", ""), "error": str(exc)})
    else:
        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
            future_to_meta = {
                executor.submit(label_with_model, row, args, api_key): (index, row)
                for index, row in pending
            }
            for future in as_completed(future_to_meta):
                index, row = future_to_meta[future]
                try:
                    labeled_row = future.result()
                except RuntimeError as exc:
                    errors.append({"repo": row.get("repo", ""), "sha": row.get("sha", ""), "error": str(exc)})
                    continue
                record_result(index, labeled_row)

    ordered_new_rows = [results_by_index[index] for index, _ in pending if index in results_by_index]
    summary = {
        "created_at_utc": utc_now(),
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
        "output_jsonl": str(args.output_jsonl),
        "model": args.model,
        "endpoint": args.endpoint,
        "workers": int(args.workers),
        "selected": len(rows),
        "resume_skipped": resume_skipped,
        "dedupe_skipped": dedupe_skipped,
        "labeled_new_rows": len(ordered_new_rows),
        "output_total_rows": len(existing_rows) + len(ordered_new_rows),
        "errors": errors[:100],
        "error_count": len(errors),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
