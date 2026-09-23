from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from build_generation_pilot_dataset import (
    DEFAULT_PREBUILT_GENERATION_SOURCE_ROOT,
    DEFAULT_SOURCE_ROOT,
    _from_csv_row,
    _from_step3_row,
)
from common import diff_fingerprint, read_csv, read_jsonl, rel_path, repo_path, safe_text, stable_hash, type_signature, write_json, write_jsonl
from common import normalize_subject
from repo_identity import attach_repo_identity, describe_repo_identity


def build_exemplar_pool(config: dict[str, Any], output_root: Path) -> dict[str, Any]:
    data_sources = config.get("data_sources", {})
    source_root = repo_path(data_sources.get("step3_source_root", DEFAULT_SOURCE_ROOT))
    prebuilt_root = repo_path(data_sources.get("prebuilt_generation_source_root", DEFAULT_PREBUILT_GENERATION_SOURCE_ROOT))
    pilot_rows = read_jsonl(output_root / "dataset" / "pilot_all.jsonl")
    blocked_repos = {
        safe_text(row.get("repo_canonical")) or describe_repo_identity(row.get("repo"))["canonical"]
        for row in pilot_rows
        if safe_text(row.get("repo_canonical")) or safe_text(row.get("repo"))
    }
    blocked_shas = {sha for row in pilot_rows for sha in (row.get("source_shas") or []) if sha}
    blocked_fps = {safe_text(row.get("diff_fingerprint")) for row in pilot_rows if safe_text(row.get("diff_fingerprint"))}
    blocked_subjects = {safe_text(row.get("normalized_subject")) or normalize_subject(safe_text(row.get("subject_reference"))) for row in pilot_rows}

    candidates: list[dict[str, Any]] = []
    if (prebuilt_root / "exemplar_pool" / "exemplar_pool.jsonl").exists():
        for row in read_jsonl(prebuilt_root / "exemplar_pool" / "exemplar_pool.jsonl"):
            candidates.append(attach_repo_identity(dict(row)))
        source_root_label = rel_path(prebuilt_root)
    else:
        for split in ["train", "dev"]:
            for row in read_jsonl(source_root / "strict" / f"step3_bootstrap_{split}.jsonl"):
                candidates.append(_from_step3_row(row, "atomic_simple" if int(row.get("k", 0) or 0) == 1 else "synthetic_multi"))
        hard_b_train = source_root / "hard_b_train.jsonl"
        if hard_b_train.exists():
            for row in read_jsonl(hard_b_train):
                candidates.append(_from_step3_row(row, "hard_b"))
        else:
            hard_b_csv = data_sources.get("hard_b_csv") or "datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv"
            for row in read_csv(hard_b_csv):
                candidates.append(_from_csv_row(row, "hard_b", intent_count=1, supervision="commit_level"))
        source_root_label = rel_path(source_root)

    pool: list[dict[str, Any]] = []
    filter_reasons: dict[str, int] = {}
    exclusion_rows: list[dict[str, Any]] = []
    for row in candidates:
        diff_text = safe_text(row.get("diff_text"))
        row_fp = safe_text(row.get("diff_fingerprint")) or diff_fingerprint(diff_text)
        row_subject = safe_text(row.get("subject_reference")) or safe_text(row.get("subject"))
        row_subject_norm = safe_text(row.get("normalized_subject")) or normalize_subject(row_subject)
        repo_info = describe_repo_identity(row.get("repo"))
        reasons: list[str] = []
        if repo_info["canonical"] in blocked_repos:
            reasons.append("same_repo_canonical")
        if any(sha in blocked_shas for sha in (row.get("source_shas") or [])):
            reasons.append("pilot_source_sha")
        if row_fp in blocked_fps:
            reasons.append("pilot_diff_fingerprint")
        if row_subject_norm and row_subject_norm in blocked_subjects:
            reasons.append("pilot_normalized_subject")
        if reasons:
            for reason in reasons:
                filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
            exclusion_rows.append(
                {
                    "candidate_id": safe_text(row.get("exemplar_id")) or f"ex:{stable_hash(row['sample_id'])}",
                    "candidate_repo_original": repo_info["original"],
                    "candidate_repo_canonical": repo_info["canonical"],
                    "candidate_repo_parse_status": repo_info["parse_status"],
                    "candidate_sha": safe_text(row.get("sha")),
                    "candidate_sample_id": safe_text(row.get("sample_id")),
                    "candidate_data_category": safe_text(row.get("data_category")),
                    "reasons": reasons,
                }
            )
            continue
        subject = row_subject
        exemplar_id = safe_text(row.get("exemplar_id")) or f"ex:{stable_hash(row['sample_id'])}"
        pool.append(
            {
                "exemplar_id": exemplar_id,
                "repo": repo_info["original"],
                "repo_canonical": repo_info["canonical"],
                "repo_identity_parse_status": repo_info["parse_status"],
                "sha": safe_text(row.get("sha")),
                "data_category": safe_text(row.get("data_category")),
                "type_signature": type_signature(row),
                "subject": subject,
                "diff_summary": "\n".join(diff_text.splitlines()[:12]),
                "diff_text": diff_text,
                "diff_fingerprint": row_fp,
                "normalized_subject": row_subject_norm,
                "embedding_text": f"{subject}\n{diff_text[:4000]}",
                "intent_subjects": row.get("intent_subjects") or [],
                "intent_count": row.get("intent_count"),
            }
        )
    pool.sort(key=lambda item: item["exemplar_id"])
    out_dir = output_root / "exemplar_pool"
    write_jsonl(out_dir / "exemplar_pool.jsonl", pool)
    write_jsonl(out_dir / "exemplar_pool_exclusion_log.jsonl", exclusion_rows)
    manifest = {
        "schema_version": "llm_generation_exemplar_pool_v1",
        "source_root": source_root_label,
        "pool_count": len(pool),
        "exclusion_count": len(exclusion_rows),
        "filter_reasons": filter_reasons,
        "pilot_sample_count": len(pilot_rows),
        "leakage_policy": "exclude pilot canonical repos, source SHAs, exact diff fingerprints, and exact normalized subjects",
    }
    write_json(out_dir / "exemplar_pool_manifest.json", manifest)
    return {"pool": pool, "manifest": manifest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/llm_generation_pilot.mock.json")
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    import json

    config = json.loads(repo_path(args.config).read_text(encoding="utf-8"))
    result = build_exemplar_pool(config, repo_path(args.output_root))
    print(f"wrote {result['manifest']['pool_count']} exemplars")


if __name__ == "__main__":
    main()
