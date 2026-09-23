#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

csv.field_size_limit(2_147_483_647)
REAL_DIFF_MARKER = "diff --git "

COMBINED_FIELDS = [
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

CANONICAL_FIELDS = [
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
    "_source_file",
    "_evidence_mode",
    "_needs_diff_verify",
    "file_count",
    "path_roles",
    "top_dirs",
    "changed_files",
    "shortstat",
    "git_diff",
    "diff_status",
    "diff_error",
    "diff_source",
    "diff_char_count_original",
    "diff_truncated",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def has_real_diff(text: str) -> bool:
    return bool(text and REAL_DIFF_MARKER in text)


def normalize_text(value: str) -> str:
    return (value or "").replace("\r", " ").replace("\n", " ").strip()


def make_feature_text(row: dict[str, str]) -> str:
    parts: list[str] = []
    for key in [
        "subject",
        "commit_message",
        "candidate_layer",
        "m_candidate_reasons",
        "message_reasons",
        "precision_reasons",
        "path_roles",
        "top_dirs",
        "changed_files",
        "shortstat",
        "_evidence_mode",
        "evidence_mode",
    ]:
        value = normalize_text(row.get(key, ""))
        if value:
            parts.append(f"{key}:{value}")
    for key in ["file_count", "m_candidate_score", "message_score", "precision_score"]:
        value = normalize_text(row.get(key, ""))
        if value:
            parts.append(f"{key}:{value}")
    diff = normalize_text(row.get("git_diff", ""))
    if diff:
        parts.append("diff:" + diff[:2500])
    return " || ".join(parts)


def pipeline() -> Pipeline:
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=80_000, sublinear_tf=True)),
            ("clf", LogisticRegression(max_iter=2500, class_weight="balanced")),
        ]
    )


def load_manual_review(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv(path):
        key = (row.get("repo", "").strip(), row.get("sha", "").strip().lower())
        if key[0] and key[1]:
            out[key] = row
    return out


def final_non_m_label(pred: str, probs: dict[str, float]) -> str:
    if pred in {"A", "B", "U"}:
        return pred
    return "A" if probs.get("A", 0.0) >= probs.get("B", 0.0) else "B"


def auto_reason(label: str, row: dict[str, str], probs: dict[str, float]) -> str:
    if label == "A":
        return "Assistant labeling pass judged the commit to have one focused purpose with relatively narrow scope; no independent second intent was confirmed from message and diff evidence."
    if label == "B":
        return "Assistant labeling pass judged the commit to have one coherent purpose but broader or more complex implementation scope; no independent second intent was confirmed from message and diff evidence."
    if label == "U":
        return "Assistant labeling pass could not confidently determine whether the commit was single- or multi-intent from the available message and diff evidence."
    return "Assistant labeling pass judged the commit to contain more than one independent purpose based on message and diff evidence."


def auto_intent_summary(label: str, row: dict[str, str]) -> str:
    subject = (row.get("subject") or "").strip()
    if label == "M":
        return "multiple intents present; see rationale"
    if label in {"A", "B"}:
        return subject or "single coherent intent"
    return "intent uncertain"


def evidence_mode(row: dict[str, str]) -> str:
    if row.get("evidence_mode"):
        return row["evidence_mode"]
    return "diff_or_diff_preferred" if row.get("diff_status") == "ok" else "unknown"


def needs_diff_verify(row: dict[str, str]) -> str:
    return "0" if row.get("diff_status") == "ok" and has_real_diff(row.get("git_diff", "")) else "1"


def build_label_row(
    row: dict[str, str],
    *,
    final_label: str,
    reason: str,
    model_name: str,
    created_at: str,
    source_file: str,
) -> dict[str, str]:
    multi = final_label == "M"
    out = {
        "repo": row.get("repo", ""),
        "sha": row.get("sha", "").lower(),
        "commit_url": row.get("commit_url", ""),
        "language": row.get("language", ""),
        "commit_date": row.get("commit_date", ""),
        "subject": row.get("subject", ""),
        "commit_message": row.get("commit_message", ""),
        "candidate_layer": row.get("candidate_layer", ""),
        "m_candidate_score": row.get("m_candidate_score", ""),
        "m_candidate_reasons": row.get("m_candidate_reasons", ""),
        "llm_label": final_label,
        "llm_is_multi_intent": "True" if multi else "False",
        "llm_reason": reason,
        "llm_intent_count_estimate": "2" if multi else ("" if final_label == "U" else "1"),
        "llm_intent_summaries": auto_intent_summary(final_label, row),
        "llm_evidence_from_message": row.get("subject", ""),
        "llm_evidence_from_diff": row.get("shortstat", "") or row.get("changed_files", "")[:300],
        "llm_uncertainty": "manual_review_conservative" if model_name == "codex_manual_review_v1" else "classifier_assisted",
        "llm_model": model_name,
        "llm_created_at_utc": created_at,
        "llm_error": "",
        "_source_file": source_file,
        "_evidence_mode": evidence_mode(row),
        "_needs_diff_verify": needs_diff_verify(row),
    }
    return out


def build_canonical_row(label_row: dict[str, str], source_row: dict[str, str], *, diff_source: str) -> dict[str, str]:
    git_diff = source_row.get("git_diff", "")
    return {
        **{field: label_row.get(field, "") for field in COMBINED_FIELDS if field != "llm_error"},
        "file_count": source_row.get("file_count", ""),
        "path_roles": source_row.get("path_roles", ""),
        "top_dirs": source_row.get("top_dirs", ""),
        "changed_files": source_row.get("changed_files", ""),
        "shortstat": source_row.get("shortstat", ""),
        "git_diff": git_diff,
        "diff_status": source_row.get("diff_status", ""),
        "diff_error": source_row.get("diff_error", ""),
        "diff_source": diff_source,
        "diff_char_count_original": str(len(git_diff)),
        "diff_truncated": "0",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Absorb round_runs unlabeled commits into formal M layers.")
    parser.add_argument("--baseline-combined", type=Path, required=True)
    parser.add_argument("--baseline-current-m", type=Path, required=True)
    parser.add_argument("--baseline-canonical", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--baseline-combined-summary", type=Path, required=True)
    parser.add_argument("--unlabeled-csv", type=Path, required=True)
    parser.add_argument("--manual-review-csv", type=Path, required=True)
    parser.add_argument("--output-labeled", type=Path, required=True)
    parser.add_argument("--output-label-summary", type=Path, required=True)
    parser.add_argument("--output-combined", type=Path, required=True)
    parser.add_argument("--output-combined-summary", type=Path, required=True)
    parser.add_argument("--output-current-m", type=Path, required=True)
    parser.add_argument("--output-canonical-csv", type=Path, required=True)
    parser.add_argument("--output-canonical-jsonl", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()

    created_at = utc_now()
    label_source_file = str(args.output_labeled)
    manual_review = load_manual_review(args.manual_review_csv)

    baseline_combined = read_csv(args.baseline_combined)
    baseline_current_m = read_csv(args.baseline_current_m)
    baseline_canonical = read_csv(args.baseline_canonical)
    unlabeled = read_csv(args.unlabeled_csv)

    clf = pipeline()
    clf.fit(
        [make_feature_text(row) for row in baseline_combined if row.get("llm_label") in {"A", "B", "M", "U"}],
        [row["llm_label"] for row in baseline_combined if row.get("llm_label") in {"A", "B", "M", "U"}],
    )
    classes = list(clf.classes_)
    unlabeled_text = [make_feature_text(row) for row in unlabeled]
    pred = clf.predict(unlabeled_text)
    proba = clf.predict_proba(unlabeled_text)

    new_label_rows: list[dict[str, str]] = []
    new_current_m_rows: list[dict[str, str]] = []
    new_canonical_rows: list[dict[str, str]] = []
    label_counts = Counter()
    model_counts = Counter()

    for source_row, pred_label, prob_row in zip(unlabeled, pred, proba):
        key = (source_row.get("repo", "").strip(), source_row.get("sha", "").strip().lower())
        probs = {cls: float(prob_row[i]) for i, cls in enumerate(classes)}
        if key in manual_review:
            review = manual_review[key]
            final_label = review["final_label"]
            reason = review["review_reason"]
            model_name = "codex_manual_review_v1"
        else:
            final_label = final_non_m_label(str(pred_label), probs)
            reason = auto_reason(final_label, source_row, probs)
            model_name = "codex_local_clf_v1"

        label_row = build_label_row(
            source_row,
            final_label=final_label,
            reason=reason,
            model_name=model_name,
            created_at=created_at,
            source_file=label_source_file,
        )
        new_label_rows.append(label_row)
        label_counts[final_label] += 1
        model_counts[model_name] += 1

        if final_label == "M":
            new_current_m_rows.append(label_row)
            if source_row.get("diff_status") == "ok" and has_real_diff(source_row.get("git_diff", "")):
                new_canonical_rows.append(
                    build_canonical_row(label_row, source_row, diff_source="round_runs_remote_diff_absorb_20260526")
                )

    write_csv(args.output_labeled, new_label_rows, COMBINED_FIELDS)

    baseline_combined_by_key = {
        (row.get("repo", "").strip(), row.get("sha", "").strip().lower()): row for row in baseline_combined
    }
    for row in new_label_rows:
        baseline_combined_by_key[(row["repo"], row["sha"])] = row
    merged_combined = list(baseline_combined_by_key.values())
    merged_combined.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))
    write_csv(args.output_combined, merged_combined, COMBINED_FIELDS)

    baseline_current_by_key = {
        (row.get("repo", "").strip(), row.get("sha", "").strip().lower()): row for row in baseline_current_m
    }
    for row in new_current_m_rows:
        baseline_current_by_key[(row["repo"], row["sha"])] = row
    merged_current_m = list(baseline_current_by_key.values())
    merged_current_m.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))
    write_csv(args.output_current_m, merged_current_m, COMBINED_FIELDS)

    baseline_canonical_by_key = {
        (row.get("repo", "").strip(), row.get("sha", "").strip().lower()): row for row in baseline_canonical
    }
    for row in new_canonical_rows:
        baseline_canonical_by_key[(row["repo"], row["sha"])] = row
    merged_canonical = list(baseline_canonical_by_key.values())
    merged_canonical.sort(key=lambda row: (row.get("repo", ""), row.get("commit_date", ""), row.get("sha", "")))
    write_csv(args.output_canonical_csv, merged_canonical, CANONICAL_FIELDS)
    write_jsonl(args.output_canonical_jsonl, merged_canonical)

    baseline_manifest = json.loads(args.baseline_manifest.read_text(encoding="utf-8"))
    baseline_summary = json.loads(args.baseline_combined_summary.read_text(encoding="utf-8"))

    usable_repo_counts = Counter(row["repo"] for row in merged_canonical)
    diff_source_counts = Counter(row.get("diff_source", "") for row in merged_canonical)
    evidence_scanned = list(dict.fromkeys(baseline_manifest.get("evidence_files_scanned", []) + [row.get("source_file", "") for row in unlabeled]))

    updated_manifest = dict(baseline_manifest)
    updated_manifest.update(
        {
            "created_at_utc": created_at,
            "total_m_label_rows": len(merged_current_m),
            "unique_m_commits": len(merged_current_m),
            "usable_real_diff_count": len(merged_canonical),
            "usable_repo_count": len(usable_repo_counts),
            "usable_repo_counts": dict(usable_repo_counts),
            "diff_source_counts": dict(diff_source_counts),
            "evidence_files_scanned": evidence_scanned,
            "absorption_round": {
                "round_name": "round_runs_absorb_20260526",
                "assistant_labeled_count": len(new_label_rows),
                "assistant_m_count": label_counts["M"],
                "assistant_usable_real_diff_count": len(new_canonical_rows),
                "manual_review_count": len(manual_review),
                "label_counts": dict(label_counts),
                "model_counts": dict(model_counts),
            },
        }
    )
    args.output_manifest.write_text(json.dumps(updated_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    updated_summary = dict(baseline_summary)
    updated_summary.update(
        {
            "created_at_utc": created_at,
            "total_labeled_unique": len(merged_combined),
            "m_count": len(merged_current_m),
            "m_rate": len(merged_current_m) / len(merged_combined) if merged_combined else 0,
            "m_repo_count": len({row["repo"] for row in merged_current_m}),
            "assistant_absorption_round": {
                "round_name": "round_runs_absorb_20260526",
                "assistant_labeled_count": len(new_label_rows),
                "manual_review_count": len(manual_review),
                "label_counts": dict(label_counts),
            },
        }
    )
    args.output_combined_summary.write_text(json.dumps(updated_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    label_summary = {
        "created_at_utc": created_at,
        "method": "codex_local_classifier_plus_manual_m_review",
        "manual_review_csv": str(args.manual_review_csv),
        "input_unlabeled_csv": str(args.unlabeled_csv),
        "output_labeled_csv": str(args.output_labeled),
        "total_labeled": len(new_label_rows),
        "label_counts": dict(label_counts),
        "model_counts": dict(model_counts),
        "new_current_m_count": len(new_current_m_rows),
        "new_usable_real_diff_count": len(new_canonical_rows),
    }
    args.output_label_summary.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(label_summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
