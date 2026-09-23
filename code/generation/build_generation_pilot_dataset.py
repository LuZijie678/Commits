from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from common import (
    diff_fingerprint,
    read_csv,
    read_jsonl,
    normalize_subject,
    rel_path,
    repo_path,
    safe_text,
    sample_stratified_by_repo,
    stable_hash,
    utc_timestamp,
    write_json,
    write_jsonl,
)
from repo_identity import attach_repo_identity, describe_repo_identity


DEFAULT_SOURCE_ROOT = "outputs/step3_balanced_diagnostic_readiness_20260604T014128Z"
DEFAULT_PREBUILT_GENERATION_SOURCE_ROOT = "outputs/llm_generation_pilot_20260609T045027Z"


def _from_step3_row(row: dict[str, Any], category: str) -> dict[str, Any]:
    source_shas = list(row.get("source_shas") or [])
    sha = source_shas[0] if source_shas else safe_text(row.get("sha"))
    intent_count = int(row.get("logical_intent_count", row.get("k", 1)) or 1)
    sample_id = safe_text(row.get("sample_uid")) or safe_text(row.get("sample_id")) or f"{category}:{sha}"
    repo_info = describe_repo_identity(row.get("repo"))
    return {
        "sample_id": f"{category}:{stable_hash(sample_id)}",
        "repo": repo_info["original"],
        "repo_canonical": repo_info["canonical"],
        "repo_identity_parse_status": repo_info["parse_status"],
        "sha": sha,
        "data_category": category,
        "subject_reference": safe_text(row.get("message_text")).splitlines()[0] if safe_text(row.get("message_text")) else "",
        "message_reference": safe_text(row.get("message_text")),
        "diff_text": safe_text(row.get("diff_text")),
        "intent_count": intent_count,
        "intent_subjects": row.get("intent_subjects") or [],
        "intent_types": row.get("intent_types") or [],
        "edit_to_intent": row.get("edit_to_intent") or {},
        "structure_supervision_level": "hunk_level" if row.get("edit_to_intent") else "commit_level",
        "source_shas": source_shas or ([sha] if sha else []),
        "split": "pilot_test",
        "source_path": "",
        "diff_fingerprint": diff_fingerprint(safe_text(row.get("diff_text"))),
        "normalized_subject": normalize_subject(safe_text(row.get("message_text")).splitlines()[0] if safe_text(row.get("message_text")) else ""),
    }


def _from_csv_row(row: dict[str, str], category: str, *, intent_count: int, supervision: str) -> dict[str, Any]:
    subject = safe_text(row.get("subject")) or safe_text(row.get("commit_message")).splitlines()[0]
    message = safe_text(row.get("commit_message")) or subject
    diff_text = safe_text(row.get("git_diff"))
    sha = safe_text(row.get("sha"))
    intent_summaries = safe_text(row.get("llm_intent_summaries"))
    repo_info = describe_repo_identity(row.get("repo"))
    return {
        "sample_id": f"{category}:{stable_hash(safe_text(row.get('repo')) + ':' + sha)}",
        "repo": repo_info["original"],
        "repo_canonical": repo_info["canonical"],
        "repo_identity_parse_status": repo_info["parse_status"],
        "sha": sha,
        "data_category": category,
        "subject_reference": subject,
        "message_reference": message,
        "diff_text": diff_text,
        "intent_count": intent_count,
        "intent_subjects": [item.strip() for item in intent_summaries.split("|") if item.strip()],
        "intent_types": [],
        "edit_to_intent": {},
        "structure_supervision_level": supervision,
        "source_shas": [sha] if sha else [],
        "split": "pilot_test",
        "source_path": "",
        "diff_fingerprint": diff_fingerprint(diff_text),
        "normalized_subject": normalize_subject(subject),
    }


def _load_prebuilt_generation_candidates(prebuilt_root: Path) -> dict[str, list[dict[str, Any]]]:
    mapping = {
        "atomic_simple": "pilot_atomic_simple.jsonl",
        "hard_b": "pilot_hard_b.jsonl",
        "synthetic_multi": "pilot_synthetic_multi.jsonl",
        "M_real_multi": "pilot_M_real_multi.jsonl",
    }
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for category, filename in mapping.items():
        rows = [deepcopy(row) for row in read_jsonl(prebuilt_root / "dataset" / filename)]
        enriched_rows: list[dict[str, Any]] = []
        for row in rows:
            row = attach_repo_identity(row)
            row["data_category"] = category
            row["source_path"] = safe_text(row.get("source_path")) or rel_path(prebuilt_root)
            enriched_rows.append(row)
        rows_by_category[category] = enriched_rows
    return rows_by_category


def resolve_candidate_rows(data_sources: dict[str, Any] | None = None) -> tuple[dict[str, list[dict[str, Any]]], str]:
    data_sources = data_sources or {}
    prebuilt_root = repo_path(data_sources.get("prebuilt_generation_source_root", DEFAULT_PREBUILT_GENERATION_SOURCE_ROOT))
    if (prebuilt_root / "dataset" / "pilot_all.jsonl").exists():
        return _load_prebuilt_generation_candidates(prebuilt_root), rel_path(prebuilt_root)

    source_root = repo_path(data_sources.get("step3_source_root", DEFAULT_SOURCE_ROOT))
    hard_b_csv = data_sources.get("hard_b_csv") or "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv"
    m_csv = data_sources.get("m_csv") or "datasets/m_verified/canonical/usable_m_with_real_diff.csv"
    strict_test = read_jsonl(source_root / "strict" / "step3_bootstrap_test.jsonl")
    atomic = [_from_step3_row(row, "atomic_simple") for row in strict_test if int(row.get("k", 0) or 0) == 1]
    synthetic = [_from_step3_row(row, "synthetic_multi") for row in strict_test if int(row.get("k", 0) or 0) >= 2]

    hard_b_rows = [
        _from_csv_row(row, "hard_b", intent_count=1, supervision="commit_level")
        for row in read_csv(hard_b_csv)
        if safe_text(row.get("git_diff"))
    ]
    m_rows = [
        _from_csv_row(
            row,
            "M_real_multi",
            intent_count=max(2, int(float(row.get("llm_intent_count_estimate") or 2))),
            supervision="commit_level",
        )
        for row in read_csv(m_csv)
        if safe_text(row.get("git_diff"))
    ]
    return {
        "atomic_simple": atomic,
        "hard_b": hard_b_rows,
        "synthetic_multi": synthetic,
        "M_real_multi": m_rows,
    }, rel_path(source_root)


def _leakage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, dict[str, set[str]]] = {
        "repo_canonical": {},
        "source_sha": {},
        "diff_fingerprint": {},
        "subject_reference": {},
    }
    for row in rows:
        category = safe_text(row["data_category"])
        entries = {
            "repo_canonical": [safe_text(row.get("repo_canonical")) or describe_repo_identity(row.get("repo"))["canonical"]],
            "source_sha": list(row.get("source_shas") or []),
            "diff_fingerprint": [safe_text(row.get("diff_fingerprint"))],
            "subject_reference": [safe_text(row.get("normalized_subject")) or normalize_subject(safe_text(row.get("subject_reference")))],
        }
        for key, values in entries.items():
            for value in values:
                if not value:
                    continue
                by_key[key].setdefault(value, set()).add(category)
    overlaps: dict[str, list[dict[str, Any]]] = {}
    for key, mapping in by_key.items():
        overlaps[key] = [
            {"value": value, "categories": sorted(categories)}
            for value, categories in mapping.items()
            if len(categories) > 1
        ]
    return {
        "passed": all(len(items) == 0 for key, items in overlaps.items() if key != "repo_canonical"),
        "policy": "selected pilot rows must not share source SHA, exact diff fingerprint, or exact normalized subject; canonical repo overlap is tracked as a diagnostic",
        "overlaps": overlaps,
    }


def build_pilot_dataset(config: dict[str, Any], output_root: Path | None = None) -> dict[str, Any]:
    data_sources = config.get("data_sources", {})
    sizes = config.get("pilot_sample_size", {})
    seed = int(config.get("random_seed", 42))
    output_root = output_root or repo_path(config.get("output_root") or f"outputs/llm_generation_pilot_{utc_timestamp()}")
    dataset_dir = output_root / "dataset"

    candidates, source_root_label = resolve_candidate_rows(data_sources)
    selected_by_category: dict[str, list[dict[str, Any]]] = {}
    shortfalls: dict[str, dict[str, int]] = {}
    for category, rows in candidates.items():
        target = int(sizes.get(category, 100))
        selected = sample_stratified_by_repo(rows, min(target, len(rows)), seed + int(stable_hash(category, 8), 16) % 997)
        for row in selected:
            if not safe_text(row.get("source_path")):
                row["source_path"] = source_root_label if category in {"atomic_simple", "synthetic_multi"} else (
                    rel_path(data_sources.get("hard_b_csv") or "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv")
                    if category == "hard_b"
                    else rel_path(data_sources.get("m_csv") or "datasets/m_verified/canonical/usable_m_with_real_diff.csv")
                )
        selected_by_category[category] = selected
        if len(selected) < target:
            shortfalls[category] = {"requested": target, "available": len(rows), "selected": len(selected)}
        write_jsonl(dataset_dir / f"pilot_{category}.jsonl", selected)

    all_rows = [row for category in ["atomic_simple", "hard_b", "synthetic_multi", "M_real_multi"] for row in selected_by_category[category]]
    leakage = _leakage_report(all_rows)
    write_jsonl(dataset_dir / "pilot_all.jsonl", all_rows)
    manifest = {
        "schema_version": "llm_generation_pilot_dataset_v1",
        "source_root": source_root_label,
        "output_root": rel_path(output_root),
        "seed": seed,
        "requested_sizes": sizes,
        "selected_counts": {key: len(value) for key, value in selected_by_category.items()},
        "shortfalls": shortfalls,
        "leakage_passed": leakage["passed"],
        "data_categories": {
            "atomic_simple": "simple single-intent real commits from strict Step3 test",
            "hard_b": "complex single-intent real commits",
            "synthetic_multi": "Step2 synthetic multi-intent commits with structure labels",
            "M_real_multi": "real multi-intent commits with commit-level labels",
        },
    }
    write_json(dataset_dir / "pilot_dataset_manifest.json", manifest)
    write_json(dataset_dir / "pilot_leakage_report.json", leakage)
    return {"output_root": output_root, "manifest": manifest, "leakage": leakage, "rows": all_rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_pilot.mock.json")
    parser.add_argument("--output-root")
    args = parser.parse_args()
    config = __import__("json").loads(repo_path(args.config).read_text(encoding="utf-8"))
    result = build_pilot_dataset(config, repo_path(args.output_root) if args.output_root else None)
    print(f"wrote {result['manifest']['selected_counts']} to {rel_path(result['output_root'])}")


if __name__ == "__main__":
    main()
