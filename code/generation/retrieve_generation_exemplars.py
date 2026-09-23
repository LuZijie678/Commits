from __future__ import annotations

import argparse
import statistics
import random
from pathlib import Path
from typing import Any

from common import normalize_subject, read_jsonl, repo_path, safe_text, tfidf_cosine, type_signature, write_jsonl
from repo_identity import describe_repo_identity


def retrieve_for_sample(
    sample: dict[str, Any],
    pool: list[dict[str, Any]],
    *,
    strategy: str,
    k: int,
    seed: int,
    low_similarity_threshold: float = 0.10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed + sum(ord(ch) for ch in safe_text(sample.get("sample_id")) + strategy))
    sample_fingerprint = safe_text(sample.get("diff_fingerprint"))
    sample_subject_norm = safe_text(sample.get("normalized_subject")) or normalize_subject(safe_text(sample.get("subject_reference")))
    sample_repo_info = describe_repo_identity(sample.get("repo"))
    sample_repo_original = sample_repo_info["original"]
    sample_repo_canonical = safe_text(sample.get("repo_canonical")) or sample_repo_info["canonical"]
    sample_source_shas = set(sample.get("source_shas") or [sample.get("sha")])
    filtered: list[dict[str, Any]] = []
    filter_reasons: dict[str, int] = {}
    repo_guard_excluded_candidates: list[dict[str, Any]] = []
    for ex in pool:
        ex_repo_info = describe_repo_identity(ex.get("repo"))
        ex_repo_original = ex_repo_info["original"]
        ex_repo_canonical = safe_text(ex.get("repo_canonical")) or ex_repo_info["canonical"]
        ex_subject_norm = safe_text(ex.get("normalized_subject")) or normalize_subject(safe_text(ex.get("subject")))
        reasons: list[str] = []
        if ex_repo_canonical and sample_repo_canonical and ex_repo_canonical == sample_repo_canonical:
            reasons.append("same_repo_canonical")
            repo_guard_excluded_candidates.append(
                {
                    "candidate_id": safe_text(ex.get("exemplar_id")),
                    "candidate_repo_original": ex_repo_original,
                    "candidate_repo_canonical": ex_repo_canonical,
                    "reason": "same_repo_canonical",
                }
            )
        if safe_text(ex.get("sha")) in sample_source_shas:
            reasons.append("source_sha_overlap")
        if sample_fingerprint and safe_text(ex.get("diff_fingerprint")) == sample_fingerprint:
            reasons.append("diff_fingerprint_overlap")
        if sample_subject_norm and ex_subject_norm == sample_subject_norm:
            reasons.append("normalized_subject_overlap")
        if reasons:
            for reason in reasons:
                filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
            continue
        enriched = dict(ex)
        enriched["repo_canonical"] = ex_repo_canonical
        enriched["repo_identity_parse_status"] = safe_text(ex.get("repo_identity_parse_status")) or ex_repo_info["parse_status"]
        filtered.append(enriched)
    fallback_reason = ""
    if strategy == "random":
        rng.shuffle(filtered)
        chosen = filtered[:k]
        scores = [0.0 for _ in chosen]
    elif strategy == "type_matched":
        signature = type_signature(sample)
        matched = [ex for ex in filtered if safe_text(ex.get("type_signature")) == signature]
        if len(matched) < k:
            fallback_reason = "insufficient_type_matched_exemplars"
            matched = matched + [ex for ex in filtered if ex not in matched]
        rng.shuffle(matched)
        chosen = matched[:k]
        scores = [1.0 if safe_text(ex.get("type_signature")) == signature else 0.0 for ex in chosen]
    elif strategy == "retrieval":
        query = f"{sample.get('subject_reference','')}\n{sample.get('diff_text','')[:4000]}"
        scores_all = tfidf_cosine(query, [safe_text(ex.get("embedding_text")) for ex in filtered])
        ranked = sorted(zip(filtered, scores_all), key=lambda pair: (-pair[1], safe_text(pair[0].get("exemplar_id"))))
        chosen = [ex for ex, _ in ranked[:k]]
        scores = [score for _, score in ranked[:k]]
        if not chosen:
            fallback_reason = "empty_retrieval_pool"
    else:
        raise ValueError(f"unknown retrieval strategy: {strategy}")
    same_repo_original_string = any(safe_text(ex.get("repo")) == sample_repo_original for ex in chosen)
    same_repo_canonical = any(safe_text(ex.get("repo_canonical")) == sample_repo_canonical for ex in chosen if sample_repo_canonical)
    source_sha_overlap = any(safe_text(ex.get("sha")) in sample_source_shas for ex in chosen)
    diff_fingerprint_overlap = bool(sample_fingerprint) and any(safe_text(ex.get("diff_fingerprint")) == sample_fingerprint for ex in chosen)
    normalized_subject_overlap = bool(sample_subject_norm) and any(
        (safe_text(ex.get("normalized_subject")) or normalize_subject(safe_text(ex.get("subject")))) == sample_subject_norm
        for ex in chosen
    )
    quality = _retrieval_quality(
        strategy=strategy,
        requested_k=k,
        scores=scores,
        low_similarity_threshold=low_similarity_threshold,
    )
    log = {
        "query_sample_id": sample.get("sample_id"),
        "strategy": strategy,
        "requested_k": k,
        "returned_k": len(chosen),
        "query_repo_original": sample_repo_original,
        "query_repo_canonical": sample_repo_canonical,
        "retrieved_exemplar_ids": [ex.get("exemplar_id") for ex in chosen],
        "retrieved_repo_original": [safe_text(ex.get("repo")) for ex in chosen],
        "retrieved_repo_canonical": [safe_text(ex.get("repo_canonical")) for ex in chosen],
        "similarity_scores": scores,
        "similarity_top1": quality["similarity_top1"],
        "similarity_min": quality["similarity_min"],
        "similarity_mean": quality["similarity_mean"],
        "similarity_p50": quality["similarity_p50"],
        "low_similarity_threshold": quality["low_similarity_threshold"],
        "low_similarity_count": quality["low_similarity_count"],
        "low_similarity_ratio": quality["low_similarity_ratio"],
        "low_similarity_warning": quality["low_similarity_warning"],
        "retrieval_quality_status": quality["retrieval_quality_status"],
        "filter_reasons": filter_reasons,
        "fallback_reason": fallback_reason,
        "same_repo_original_string": same_repo_original_string,
        "same_repo_canonical": same_repo_canonical,
        "repo_identity_parse_status": {
            "query": sample_repo_info["parse_status"],
            "retrieved": [safe_text(ex.get("repo_identity_parse_status")) or describe_repo_identity(ex.get("repo"))["parse_status"] for ex in chosen],
        },
        "repo_guard_applied": True,
        "repo_guard_exclusion_count": len(repo_guard_excluded_candidates),
        "repo_guard_excluded_candidates": repo_guard_excluded_candidates,
        "leakage_checks": {
            "same_repo": same_repo_canonical,
            "same_repo_original_string": same_repo_original_string,
            "same_repo_canonical": same_repo_canonical,
            "source_sha_overlap": source_sha_overlap,
            "diff_fingerprint_overlap": diff_fingerprint_overlap,
            "normalized_subject_overlap": normalized_subject_overlap,
        },
    }
    return chosen, log


def build_retrieval_logs(output_root: Path, *, k: int = 3, seed: int = 42) -> list[dict[str, Any]]:
    samples = read_jsonl(output_root / "dataset" / "pilot_all.jsonl")
    pool = read_jsonl(output_root / "exemplar_pool" / "exemplar_pool.jsonl")
    logs: list[dict[str, Any]] = []
    for sample in samples:
        for strategy in ["random", "type_matched", "retrieval"]:
            _, log = retrieve_for_sample(sample, pool, strategy=strategy, k=k, seed=seed)
            logs.append(log)
    write_jsonl(output_root / "retrieval_logs" / "retrieval_logs.jsonl", logs)
    return logs


def _retrieval_quality(*, strategy: str, requested_k: int, scores: list[float], low_similarity_threshold: float) -> dict[str, Any]:
    if strategy != "retrieval":
        return {
            "similarity_top1": scores[0] if scores else "not_applicable",
            "similarity_min": min(scores) if scores else "not_applicable",
            "similarity_mean": statistics.mean(scores) if scores else "not_applicable",
            "similarity_p50": statistics.median(scores) if scores else "not_applicable",
            "low_similarity_threshold": low_similarity_threshold,
            "low_similarity_count": 0,
            "low_similarity_ratio": 0.0,
            "low_similarity_warning": False,
            "retrieval_quality_status": "not_similarity_ranked_strategy",
        }
    low_similarity_count = sum(1 for score in scores if score < low_similarity_threshold)
    returned_k = len(scores)
    low_similarity_warning = low_similarity_count > 0
    if returned_k < requested_k:
        status = "insufficient_exemplars"
    elif scores and all(score < low_similarity_threshold for score in scores):
        status = "all_low_similarity"
    else:
        status = "usable_with_diagnostics"
    return {
        "similarity_top1": scores[0] if scores else "not_applicable",
        "similarity_min": min(scores) if scores else "not_applicable",
        "similarity_mean": statistics.mean(scores) if scores else "not_applicable",
        "similarity_p50": statistics.median(scores) if scores else "not_applicable",
        "low_similarity_threshold": low_similarity_threshold,
        "low_similarity_count": low_similarity_count,
        "low_similarity_ratio": (low_similarity_count / returned_k) if returned_k else 0.0,
        "low_similarity_warning": low_similarity_warning,
        "retrieval_quality_status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logs = build_retrieval_logs(repo_path(args.output_root), k=args.k, seed=args.seed)
    print(f"wrote {len(logs)} retrieval logs")


if __name__ == "__main__":
    main()
