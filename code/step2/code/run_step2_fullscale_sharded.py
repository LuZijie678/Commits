from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

try:
    import construct_simple_two_intent as step2
except ModuleNotFoundError:  # pragma: no cover - import fallback for direct spec loading in tests
    STEP2_MAIN_PATH = Path(__file__).resolve().with_name("construct_simple_two_intent.py")
    STEP2_SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", STEP2_MAIN_PATH)
    step2 = importlib.util.module_from_spec(STEP2_SPEC)
    assert STEP2_SPEC and STEP2_SPEC.loader
    STEP2_SPEC.loader.exec_module(step2)


FULLSCALE_PLAN_VERSION = "step2_fullscale_sharded_v1"
UNBOUNDED_CAP = 10**9
DEFAULT_API_PING_MAX_ATTEMPTS = 3
DEFAULT_API_PING_RETRY_SLEEP_SEC = 2.0
DEFAULT_MAX_PARALLEL_SHARDS = 4
RuntimeProgressCallback = Callable[[int, str, dict[str, Any], dict[str, Any] | None], None]


def default_output_root() -> str:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"outputs/step2_fullscale_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan and run Step2 full-scale sharded generation on top of the current Step1 source pool."
    )
    parser.add_argument(
        "--config",
        default="configs/step2_fullscale_config.json",
        help="Step2 config used as the baseline for full-scale planning and shard execution.",
    )
    parser.add_argument(
        "--generation-config",
        default="",
        help="Optional Step2 config used only for shard generation runtime. Defaults to --config.",
    )
    parser.add_argument(
        "--output-root",
        default=default_output_root(),
        help="Root directory for the full-scale plan, shard outputs, and aggregate artifacts.",
    )
    parser.add_argument("--shard-size", type=int, default=100, help="Number of selected pairs per shard.")
    parser.add_argument(
        "--selection-target-count",
        type=int,
        default=0,
        help="Optional selected pair cap. 0 means no target-count cap during selection.",
    )
    parser.add_argument(
        "--selection-repo-cap",
        type=int,
        default=0,
        help="Optional repo cap for selection. 0 means no repo cap during selection.",
    )
    parser.add_argument(
        "--selection-type-pair-cap",
        type=int,
        default=0,
        help="Optional type-pair cap for selection. 0 means no type-pair cap during selection.",
    )
    parser.add_argument("--plan-only", action="store_true", help="Only materialize the primary full-scale plan and shard files.")
    parser.add_argument("--resume", action="store_true", help="Reuse completed shard outputs when run_metadata.json exists.")
    parser.add_argument("--keep-going", action="store_true", help="Continue after shard failures and aggregate successful shards.")
    parser.add_argument(
        "--disable-message-gate-for-shards",
        dest="disable_message_gate_for_shards",
        action="store_true",
        help="Debug only: force-disable the message gate during shard execution.",
    )
    parser.add_argument("--keep-message-gate", dest="disable_message_gate_for_shards", action="store_false", help=argparse.SUPPRESS)
    parser.set_defaults(disable_message_gate_for_shards=False)
    parser.add_argument(
        "--shard-min-target-ratio",
        type=float,
        default=0.0,
        help="Per-shard target gate ratio. Use 0.0 for full-scale harvest runs.",
    )
    parser.add_argument(
        "--disable-api-ping-before-each-shard",
        dest="api_ping_before_each_shard",
        action="store_false",
        help="Skip the lightweight DeepSeek API ping before each shard.",
    )
    parser.set_defaults(api_ping_before_each_shard=True)
    parser.add_argument(
        "--max-parallel-shards",
        type=int,
        default=DEFAULT_MAX_PARALLEL_SHARDS,
        help="Maximum shard workers to run concurrently.",
    )
    args = parser.parse_args()
    if args.shard_size <= 0:
        parser.error("`--shard-size` must be a positive integer.")
    if not 0.0 <= args.shard_min_target_ratio <= 1.0:
        parser.error("`--shard-min-target-ratio` must be in [0, 1].")
    if args.max_parallel_shards <= 0:
        parser.error("`--max-parallel-shards` must be a positive integer.")
    for name in ("selection_target_count", "selection_repo_cap", "selection_type_pair_cap"):
        if getattr(args, name) < 0:
            parser.error(f"`--{name.replace('_', '-')}` must be >= 0.")
    return args


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def safe_print(*args: Any, **kwargs: Any) -> None:
    try:
        print(*args, **kwargs)
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


def log_event(message: str) -> None:
    safe_print(message, flush=True)


def effective_cap(value: int) -> int:
    return value if value > 0 else UNBOUNDED_CAP


def legacy_guard_threshold(planning_args: argparse.Namespace) -> float:
    return float(getattr(planning_args, "selection_min_pair_quality_weight", 0.0))


def load_planning_args(config_path: Path) -> argparse.Namespace:
    return step2.parse_args(
        [
            "--config",
            str(config_path),
            "--preflight",
            "--run-purpose",
            "debug",
            "--skip-message-stage",
            "--disable-message-gate",
        ]
    )


def clone_repo_pairs(repo_pairs: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {repo: list(items) for repo, items in repo_pairs.items()}


def build_primary_plan(
    planning_args: argparse.Namespace,
    *,
    selection_target_count: int,
    selection_repo_cap: int,
    selection_type_pair_cap: int,
) -> dict[str, Any]:
    source_path = Path(planning_args.source_csv)
    if not source_path.exists() or not source_path.is_file():
        raise RuntimeError(f"Full-scale source CSV not found: {source_path}")

    source_rows = step2.load_csv(source_path)
    pool, pool_stats = step2.build_source_pool_from_minimal(source_rows, manual_label=planning_args.manual_label)
    repo_pairs, precheck_stats = step2.build_groups(
        pool,
        intent_k=planning_args.intent_k,
        max_merged_files=planning_args.max_merged_files,
        max_merged_lines=planning_args.max_merged_lines,
        prefer_module_overlap=planning_args.prefer_module_overlap,
        require_module_overlap=planning_args.require_module_overlap,
        group_combo_attempt_cap_per_repo=planning_args.group_combo_attempt_cap_per_repo,
        group_candidate_cap_per_repo=planning_args.group_candidate_cap_per_repo,
        seed=planning_args.seed,
        allow_entangled_candidates=bool(getattr(planning_args, "allow_entangled_candidates", False)),
        max_shared_files_per_group=int(getattr(planning_args, "max_shared_files_per_group", 0)),
        selection_quality_priority=step2.safe_strip(getattr(planning_args, "selection_quality_priority", "legacy_guarded")),
        selection_quality_config=planning_args,
    )
    pair_pool_size = sum(len(items) for items in repo_pairs.values())
    selected_pairs = step2.select_pairs(
        clone_repo_pairs(repo_pairs),
        target_count=selection_target_count,
        repo_cap=selection_repo_cap,
        type_pair_cap=selection_type_pair_cap,
        require_different_type=bool(planning_args.require_different_type),
        seed=planning_args.seed,
        selection_quality_priority=step2.safe_strip(getattr(planning_args, "selection_quality_priority", "legacy_guarded")),
        selection_min_pair_quality_weight=float(getattr(planning_args, "selection_min_pair_quality_weight", 0.0)),
    )

    covered_shas = {
        step2.safe_strip(member.get("sha"))
        for pair in selected_pairs
        for member in pair.get("members", [])
        if step2.safe_strip(member.get("sha"))
    }
    uncovered_rows = [
        row
        for row in sorted(pool, key=lambda item: (item["repo"], item["sha"]))
        if step2.safe_strip(row.get("sha")) not in covered_shas
    ]
    uncovered_by_type = Counter(row["type"] for row in uncovered_rows)
    uncovered_by_repo = Counter(row["repo"] for row in uncovered_rows)

    raw_diff_counts = Counter()
    raw_any_counts = Counter()
    kept_diff_counts = Counter()
    low_quality_filtered_diff_counts = Counter()
    same_type_only_counts = Counter()

    for repo, pairs in repo_pairs.items():
        for pair in pairs:
            member_shas = [
                step2.safe_strip(member.get("sha"))
                for member in pair.get("members", [])
                if step2.safe_strip(member.get("sha"))
            ]
            different_type = bool(pair.get("different_type", False))
            status = step2.safe_strip(pair.get("precheck_status")) or "pass"
            weight = float(pair.get("pair_quality_weight", 1.0) or 0.0)
            guard_kept = different_type and (status == "skip" or weight > legacy_guard_threshold(planning_args))
            guard_filtered_low_quality = different_type and status != "skip" and weight <= legacy_guard_threshold(planning_args)
            for sha in member_shas:
                raw_any_counts[sha] += 1
                if different_type:
                    raw_diff_counts[sha] += 1
                    if guard_kept:
                        kept_diff_counts[sha] += 1
                    if guard_filtered_low_quality:
                        low_quality_filtered_diff_counts[sha] += 1
                else:
                    same_type_only_counts[sha] += 1

    no_eligible_diff_pair_rows: list[dict[str, Any]] = []
    filtered_by_legacy_guarded_rows: list[dict[str, Any]] = []
    for row in uncovered_rows:
        sha = row["sha"]
        if raw_diff_counts[sha] == 0:
            no_eligible_diff_pair_rows.append(row)
        elif kept_diff_counts[sha] == 0:
            enriched = dict(row)
            enriched["_raw_diff_pairs"] = int(raw_diff_counts[sha])
            enriched["_low_quality_filtered_diff_pairs"] = int(low_quality_filtered_diff_counts[sha])
            filtered_by_legacy_guarded_rows.append(enriched)

    return {
        "source_path": source_path,
        "pool": pool,
        "pool_stats": pool_stats,
        "precheck_stats": precheck_stats,
        "pair_pool_size_after_group_constraints": pair_pool_size,
        "selected_pairs": selected_pairs,
        "covered_shas": covered_shas,
        "uncovered_rows": uncovered_rows,
        "uncovered_by_type": dict(uncovered_by_type),
        "top_uncovered_repos": uncovered_by_repo.most_common(20),
        "uncovered_category_1_rows": no_eligible_diff_pair_rows,
        "uncovered_category_2_rows": filtered_by_legacy_guarded_rows,
        "uncovered_category_1_breakdown": {
            "no_raw_pair_at_all": sum(1 for row in no_eligible_diff_pair_rows if raw_any_counts[row["sha"]] == 0),
            "has_only_same_type_raw_pairs": sum(1 for row in no_eligible_diff_pair_rows if raw_any_counts[row["sha"]] > 0),
        },
        "uncovered_category_1_raw_any_counts": {row["sha"]: int(raw_any_counts[row["sha"]]) for row in no_eligible_diff_pair_rows},
        "uncovered_category_1_same_type_only_counts": {row["sha"]: int(same_type_only_counts[row["sha"]]) for row in no_eligible_diff_pair_rows},
    }


def build_uncovered_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        payload_rows.append(
            {
                "repo": row["repo"],
                "sha": row["sha"],
                "type": row["type"],
                "subject": row["subject"],
                "source_confidence": row.get("source_confidence", 1.0),
                "selection_strategy": row.get("selection_strategy", ""),
                "selection_reason": row.get("selection_reason", ""),
                "conservative_tier": row.get("conservative_tier", "A"),
                "uncovered_reason": "not_selected_under_current_group_constraints",
            }
        )
    return payload_rows


def build_uncovered_category_1_csv_rows(
    rows: list[dict[str, Any]],
    raw_any_counts: dict[str, int],
    same_type_only_counts: dict[str, int],
) -> list[dict[str, Any]]:
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        sha = row["sha"]
        payload_rows.append(
            {
                "repo": row["repo"],
                "sha": sha,
                "type": row["type"],
                "subject": row["subject"],
                "source_confidence": row.get("source_confidence", 1.0),
                "selection_strategy": row.get("selection_strategy", ""),
                "selection_reason": row.get("selection_reason", ""),
                "conservative_tier": row.get("conservative_tier", "A"),
                "raw_any_pairs": int(raw_any_counts.get(sha, 0)),
                "same_type_raw_pairs": int(same_type_only_counts.get(sha, 0)),
                "uncovered_reason": (
                    "has_only_same_type_raw_pairs"
                    if int(raw_any_counts.get(sha, 0)) > 0
                    else "no_raw_pair_at_all"
                ),
            }
        )
    return payload_rows


def build_uncovered_category_2_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        payload_rows.append(
            {
                "repo": row["repo"],
                "sha": row["sha"],
                "type": row["type"],
                "subject": row["subject"],
                "source_confidence": row.get("source_confidence", 1.0),
                "selection_strategy": row.get("selection_strategy", ""),
                "selection_reason": row.get("selection_reason", ""),
                "conservative_tier": row.get("conservative_tier", "A"),
                "raw_diff_pairs": int(row.get("_raw_diff_pairs", 0)),
                "low_quality_filtered_diff_pairs": int(row.get("_low_quality_filtered_diff_pairs", 0)),
                "uncovered_reason": "has_raw_diff_pair_but_filtered_by_legacy_guarded",
            }
        )
    return payload_rows


def materialize_fullscale_plan(
    output_root: Path,
    config_path: Path,
    generation_config_path: Path,
    planning_args: argparse.Namespace,
    plan_payload: dict[str, Any],
    shard_size: int,
    *,
    selection_target_count: int,
    selection_repo_cap: int,
    selection_type_pair_cap: int,
) -> dict[str, Any]:
    plan_dir = output_root / "plan"
    shards_dir = plan_dir / "shards"
    primary_plan_path = plan_dir / "selected_pairs_primary.jsonl"
    uncovered_csv_path = plan_dir / "uncovered_sources.csv"
    uncovered_category_1_csv_path = plan_dir / "uncovered_sources_category1_no_eligible_diff_pair.csv"
    uncovered_category_2_csv_path = plan_dir / "uncovered_sources_category2_filtered_by_legacy_guarded.csv"
    primary_manifest_path = plan_dir / "selected_pairs_primary_manifest.json"

    selected_pairs = plan_payload["selected_pairs"]
    step2.write_selected_pairs_plan_jsonl(primary_plan_path, selected_pairs)
    write_csv(
        uncovered_csv_path,
        [
            "repo",
            "sha",
            "type",
            "subject",
            "source_confidence",
            "selection_strategy",
            "selection_reason",
            "conservative_tier",
            "uncovered_reason",
        ],
        build_uncovered_csv_rows(plan_payload["uncovered_rows"]),
    )
    write_csv(
        uncovered_category_1_csv_path,
        [
            "repo",
            "sha",
            "type",
            "subject",
            "source_confidence",
            "selection_strategy",
            "selection_reason",
            "conservative_tier",
            "raw_any_pairs",
            "same_type_raw_pairs",
            "uncovered_reason",
        ],
        build_uncovered_category_1_csv_rows(
            plan_payload["uncovered_category_1_rows"],
            plan_payload["uncovered_category_1_raw_any_counts"],
            plan_payload["uncovered_category_1_same_type_only_counts"],
        ),
    )
    write_csv(
        uncovered_category_2_csv_path,
        [
            "repo",
            "sha",
            "type",
            "subject",
            "source_confidence",
            "selection_strategy",
            "selection_reason",
            "conservative_tier",
            "raw_diff_pairs",
            "low_quality_filtered_diff_pairs",
            "uncovered_reason",
        ],
        build_uncovered_category_2_csv_rows(plan_payload["uncovered_category_2_rows"]),
    )

    shard_records: list[dict[str, Any]] = []
    for shard_index, start in enumerate(range(0, len(selected_pairs), shard_size), start=1):
        shard_pairs = selected_pairs[start : start + shard_size]
        shard_id = f"shard_{shard_index:04d}"
        shard_plan_path = shards_dir / f"{shard_id}_pairs.jsonl"
        shard_manifest_path = shards_dir / f"{shard_id}_manifest.json"
        run_dir = output_root / "shards" / shard_id
        sample_id_offset = start
        step2.write_selected_pairs_plan_jsonl(shard_plan_path, shard_pairs)
        shard_manifest = {
            "plan_version": FULLSCALE_PLAN_VERSION,
            "plan_stage": "primary_strict",
            "created_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "config_path": str(config_path),
            "generation_config_path": str(generation_config_path),
            "source_csv": str(plan_payload["source_path"]),
            "selected_pairs_jsonl": str(shard_plan_path),
            "selected_pair_count": len(shard_pairs),
            "pair_rank_start": start + 1,
            "pair_rank_end": start + len(shard_pairs),
            "sample_id_offset": sample_id_offset,
            "shard_id": shard_id,
            "shard_index": shard_index,
            "shard_size": shard_size,
            "progress_flush_every": int(getattr(planning_args, "progress_flush_every", 0)),
            "intent_k": int(planning_args.intent_k),
            "output_dir": str(run_dir),
            "pair_pool_size_after_group_constraints": int(plan_payload["pair_pool_size_after_group_constraints"]),
            "precheck_stats": dict(plan_payload["precheck_stats"]),
            "selection_policy": {
                "require_different_type": bool(planning_args.require_different_type),
                "selection_quality_priority": step2.safe_strip(getattr(planning_args, "selection_quality_priority", "legacy_guarded")),
                "selection_min_pair_quality_weight": float(getattr(planning_args, "selection_min_pair_quality_weight", 0.0)),
                "selection_target_count": int(selection_target_count),
                "selection_repo_cap": int(selection_repo_cap),
                "selection_type_pair_cap": int(selection_type_pair_cap),
            },
        }
        write_json(shard_manifest_path, shard_manifest)
        shard_records.append(
            {
                "shard_id": shard_id,
                "shard_index": shard_index,
                "selected_pair_count": len(shard_pairs),
                "sample_id_offset": sample_id_offset,
                "pair_rank_start": start + 1,
                "pair_rank_end": start + len(shard_pairs),
                "selected_pairs_jsonl": str(shard_plan_path),
                "selected_pairs_manifest": str(shard_manifest_path),
                "output_dir": str(run_dir),
                "progress_flush_every": int(getattr(planning_args, "progress_flush_every", 0)),
                "intent_k": int(planning_args.intent_k),
            }
        )

    primary_manifest = {
        "plan_version": FULLSCALE_PLAN_VERSION,
        "plan_stage": "primary_strict",
        "created_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "config_path": str(config_path),
        "generation_config_path": str(generation_config_path),
        "source_csv": str(plan_payload["source_path"]),
        "source_pool_size": int(plan_payload["pool_stats"]["a_tier_rows"]),
        "pool_repo_count": int(plan_payload["pool_stats"]["repo_count"]),
        "pool_type_count": int(plan_payload["pool_stats"]["type_count"]),
        "pair_pool_size_after_group_constraints": int(plan_payload["pair_pool_size_after_group_constraints"]),
        "selected_pair_count": len(selected_pairs),
        "source_coverage_count": len(plan_payload["covered_shas"]),
        "source_coverage_rate": round(
            len(plan_payload["covered_shas"]) / int(plan_payload["pool_stats"]["a_tier_rows"]),
            6,
        ) if int(plan_payload["pool_stats"]["a_tier_rows"]) else 0.0,
        "uncovered_source_count": len(plan_payload["uncovered_rows"]),
        "uncovered_source_rate": round(
            len(plan_payload["uncovered_rows"]) / int(plan_payload["pool_stats"]["a_tier_rows"]),
            6,
        ) if int(plan_payload["pool_stats"]["a_tier_rows"]) else 0.0,
        "uncovered_category_breakdown": {
            "category_1_no_eligible_diff_pair_count": len(plan_payload["uncovered_category_1_rows"]),
            "category_2_filtered_by_legacy_guarded_count": len(plan_payload["uncovered_category_2_rows"]),
            "category_1_breakdown": dict(plan_payload["uncovered_category_1_breakdown"]),
        },
        "uncovered_by_type": dict(plan_payload["uncovered_by_type"]),
        "top_uncovered_repos": list(plan_payload["top_uncovered_repos"]),
        "precheck_stats": dict(plan_payload["precheck_stats"]),
        "selection_policy": {
            "require_different_type": bool(planning_args.require_different_type),
            "selection_quality_priority": step2.safe_strip(getattr(planning_args, "selection_quality_priority", "legacy_guarded")),
            "selection_min_pair_quality_weight": float(getattr(planning_args, "selection_min_pair_quality_weight", 0.0)),
            "selection_target_count": int(selection_target_count),
            "selection_repo_cap": int(selection_repo_cap),
            "selection_type_pair_cap": int(selection_type_pair_cap),
            "module_overlap_policy": planning_args.module_overlap_policy,
            "allow_entangled_candidates": bool(getattr(planning_args, "allow_entangled_candidates", False)),
            "max_shared_files_per_group": int(getattr(planning_args, "max_shared_files_per_group", 0)),
            "max_merged_files": int(planning_args.max_merged_files),
            "max_merged_lines": int(planning_args.max_merged_lines),
            "group_combo_attempt_cap_per_repo": int(planning_args.group_combo_attempt_cap_per_repo),
            "group_candidate_cap_per_repo": int(planning_args.group_candidate_cap_per_repo),
        },
        "shard_size": shard_size,
        "shard_count": len(shard_records),
        "paths": {
            "selected_pairs_primary_jsonl": str(primary_plan_path),
            "selected_pairs_primary_manifest": str(primary_manifest_path),
            "uncovered_sources_csv": str(uncovered_csv_path),
            "uncovered_sources_category1_csv": str(uncovered_category_1_csv_path),
            "uncovered_sources_category2_csv": str(uncovered_category_2_csv_path),
        },
        "shards": shard_records,
    }
    write_json(primary_manifest_path, primary_manifest)
    return primary_manifest


def load_existing_shard_result(shard_record: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(shard_record["output_dir"])
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise RuntimeError(f"Shard output missing run_metadata.json: {run_dir}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    run_stats = dict(metadata.get("run_stats", {}) or {})
    message_metrics = dict(run_stats.get("message_metrics", {}) or {})
    return {
        "shard_id": shard_record["shard_id"],
        "shard_index": int(shard_record["shard_index"]),
        "output_dir": str(run_dir),
        "status": "reused",
        "selected_pair_count": int(shard_record["selected_pair_count"]),
        "generated_count": int(run_stats.get("generated_samples", 0)),
        "step3_ready_count": int(run_stats.get("step3_ready_count", 0)),
        "target_gate_passed": bool(run_stats.get("target_gate_passed", False)),
        "message_pass_rate": float(message_metrics.get("message_pass_rate", 0.0)),
        "message_reject_rate": float(message_metrics.get("message_reject_rate", 0.0)),
        "api_ping_attempted": False,
        "api_ping_ok": None,
        "api_ping_attempt_count": 0,
        "api_ping_warning": "",
    }


def should_ping_api_before_shard(shard_args: argparse.Namespace, api_ping_before_each_shard: bool) -> bool:
    return bool(
        api_ping_before_each_shard
        and getattr(shard_args, "generator_provider", "") == "deepseek_api"
        and getattr(shard_args, "generator_mode", "api") != "mock"
    )


def run_shard_api_ping(
    shard_args: argparse.Namespace,
    *,
    shard_id: str,
    max_attempts: int = DEFAULT_API_PING_MAX_ATTEMPTS,
    retry_sleep_sec: float = DEFAULT_API_PING_RETRY_SLEEP_SEC,
) -> dict[str, Any]:
    attempts = max(1, int(max_attempts))
    last_error_type = ""
    last_preview = ""
    for attempt in range(1, attempts + 1):
        ping = step2.run_generator_preflight_ping(shard_args)
        if bool(ping.get("ok", False)):
            return {
                "attempted": True,
                "ok": True,
                "attempt_count": attempt,
                "warning": "",
                "error_type": "",
                "raw_response_preview": "",
            }
        last_error_type = step2.safe_strip(ping.get("error_type", "")) or "unknown"
        last_preview = step2.safe_strip(ping.get("raw_response_preview", ""))
        detail = last_error_type
        if last_preview:
            detail += f" ({last_preview})"
        if attempt < attempts:
            log_event(
                f"[warn] {shard_id} api ping failed on attempt {attempt}/{attempts}: {detail}; retrying"
            )
            time.sleep(retry_sleep_sec)
    warning = last_error_type
    if last_preview:
        warning += f" ({last_preview})"
    return {
        "attempted": True,
        "ok": False,
        "attempt_count": attempts,
        "warning": warning or "unknown",
        "error_type": last_error_type or "unknown",
        "raw_response_preview": last_preview,
    }


def run_one_shard(
    generation_config_path: Path,
    shard_record: dict[str, Any],
    *,
    disable_message_gate_for_shards: bool,
    shard_min_target_ratio: float,
    api_ping_before_each_shard: bool,
    resume: bool,
    prepared_context: dict[str, Any] | None,
) -> dict[str, Any]:
    run_dir = Path(shard_record["output_dir"])
    metadata_path = run_dir / "run_metadata.json"
    if resume and metadata_path.exists():
        return load_existing_shard_result(shard_record)

    argv = [
        "--config",
        str(generation_config_path),
        "--output-dir",
        str(run_dir),
        "--intent-k",
        str(int(shard_record["intent_k"])),
        "--target-count",
        str(int(shard_record["selected_pair_count"])),
        "--min-target-ratio",
        str(float(shard_min_target_ratio)),
        "--selected-pairs-jsonl",
        str(shard_record["selected_pairs_jsonl"]),
        "--selected-pairs-manifest",
        str(shard_record["selected_pairs_manifest"]),
        "--sample-id-offset",
        str(int(shard_record["sample_id_offset"])),
        "--progress-flush-every",
        str(int(shard_record.get("progress_flush_every", 0))),
        "--k-sweep-max",
        str(int(shard_record["intent_k"])),
    ]
    if disable_message_gate_for_shards:
        argv.append("--disable-message-gate")

    shard_args = step2.parse_args(argv)
    ping_result = {
        "attempted": False,
        "ok": None,
        "attempt_count": 0,
        "warning": "",
    }
    if should_ping_api_before_shard(shard_args, api_ping_before_each_shard):
        ping_result = run_shard_api_ping(shard_args, shard_id=str(shard_record["shard_id"]))
        if not bool(ping_result.get("ok", False)):
            error_type = step2.safe_strip(ping_result.get("error_type", "")) or "unknown"
            warning = step2.safe_strip(ping_result.get("warning", ""))
            log_event(
                f"[warn] {shard_record['shard_id']} api ping failed after "
                f"{ping_result['attempt_count']} attempts; stop shard run: {warning or error_type}"
            )
            return {
                "shard_id": shard_record["shard_id"],
                "shard_index": int(shard_record["shard_index"]),
                "output_dir": str(run_dir),
                "status": "failed",
                "selected_pair_count": int(shard_record["selected_pair_count"]),
                "generated_count": 0,
                "step3_ready_count": 0,
                "target_gate_passed": False,
                "message_pass_rate": 0.0,
                "message_reject_rate": 0.0,
                "api_ping_attempted": bool(ping_result.get("attempted", False)),
                "api_ping_ok": ping_result.get("ok"),
                "api_ping_attempt_count": int(ping_result.get("attempt_count", 0)),
                "api_ping_warning": warning,
                "error": f"api_ping_{error_type}",
            }
    result = step2.run_single(shard_args, enforce_gates=False, prepared_context=prepared_context)
    message_metrics = dict(result.get("message_metrics", {}) or {})
    return {
        "shard_id": shard_record["shard_id"],
        "shard_index": int(shard_record["shard_index"]),
        "output_dir": str(run_dir),
        "status": "completed",
        "selected_pair_count": int(shard_record["selected_pair_count"]),
        "generated_count": int(result.get("generated_count", 0)),
        "step3_ready_count": int(result.get("step3_ready_count", 0)),
        "target_gate_passed": bool(result.get("target_gate_passed", False)),
        "message_pass_rate": float(message_metrics.get("message_pass_rate", 0.0)),
        "message_reject_rate": float(message_metrics.get("message_reject_rate", 0.0)),
        "api_ping_attempted": bool(ping_result.get("attempted", False)),
        "api_ping_ok": ping_result.get("ok"),
        "api_ping_attempt_count": int(ping_result.get("attempt_count", 0)),
        "api_ping_warning": step2.safe_strip(ping_result.get("warning", "")),
    }


def write_runtime_state(
    output_root: Path,
    primary_manifest: dict[str, Any],
    shard_results: list[dict[str, Any]],
    *,
    active_shard_ids: list[str] | None = None,
    worker_states: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    aggregate_dir = output_root / "aggregate"
    active_shard_ids = [step2.safe_strip(item) for item in (active_shard_ids or []) if step2.safe_strip(item)]
    worker_states = [dict(item) for item in (worker_states or [])]
    successful = [item for item in shard_results if item.get("status") in {"completed", "reused"}]
    failed = [item for item in shard_results if item.get("status") == "failed"]
    successful_sorted = sorted(successful, key=lambda item: int(item.get("shard_index", 0)))
    failed_sorted = sorted(failed, key=lambda item: int(item.get("shard_index", 0)))
    completed_ids = {step2.safe_strip(item.get("shard_id")) for item in successful_sorted}
    failed_ids = {step2.safe_strip(item.get("shard_id")) for item in failed_sorted}
    running_ids = [shard_id for shard_id in active_shard_ids if shard_id not in completed_ids and shard_id not in failed_ids]
    pending_ids = [
        step2.safe_strip(shard_record.get("shard_id"))
        for shard_record in primary_manifest.get("shards", [])
        if step2.safe_strip(shard_record.get("shard_id"))
        and step2.safe_strip(shard_record.get("shard_id")) not in completed_ids
        and step2.safe_strip(shard_record.get("shard_id")) not in failed_ids
        and step2.safe_strip(shard_record.get("shard_id")) not in running_ids
    ]
    payload = {
        "plan_version": FULLSCALE_PLAN_VERSION,
        "updated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "output_root": str(output_root),
        "primary_plan_manifest": primary_manifest["paths"]["selected_pairs_primary_manifest"],
        "shard_count": int(primary_manifest["shard_count"]),
        "processed_shard_count": len(shard_results),
        "completed_shard_count": len(successful_sorted),
        "failed_shard_count": len(failed_sorted),
        "generated_count_so_far": int(sum(int(item.get("generated_count", 0)) for item in successful_sorted)),
        "step3_ready_count_so_far": int(sum(int(item.get("step3_ready_count", 0)) for item in successful_sorted)),
        "running_shards": running_ids,
        "pending_shards": pending_ids,
        "completed_shards": successful_sorted,
        "failed_shards": failed_sorted,
        "worker_states": worker_states,
    }
    write_json(aggregate_dir / "runtime_state.json", payload)
    return payload


def partition_shard_records(shard_records: list[dict[str, Any]], max_workers: int) -> list[list[dict[str, Any]]]:
    if not shard_records:
        return []
    worker_count = max(1, min(int(max_workers), len(shard_records)))
    chunk_size = (len(shard_records) + worker_count - 1) // worker_count
    return [shard_records[index : index + chunk_size] for index in range(0, len(shard_records), chunk_size)]


def run_shard_batch(
    worker_id: int,
    generation_config_path: Path,
    shard_records: list[dict[str, Any]],
    *,
    disable_message_gate_for_shards: bool,
    shard_min_target_ratio: float,
    api_ping_before_each_shard: bool,
    resume: bool,
    keep_going: bool = False,
    progress_callback: RuntimeProgressCallback | None = None,
) -> list[dict[str, Any]]:
    if not shard_records:
        return []

    worker_context_dir = Path(shard_records[0]["output_dir"]).parent / f"_worker_{worker_id:02d}_ctx"
    try:
        prepared_context = step2.prepare_run_context(generation_config_path, output_dir=worker_context_dir)
    except Exception as exc:
        failure_results: list[dict[str, Any]] = []
        for shard_record in shard_records:
            failure = {
                "shard_id": shard_record["shard_id"],
                "shard_index": int(shard_record["shard_index"]),
                "output_dir": str(shard_record["output_dir"]),
                "status": "failed",
                "selected_pair_count": int(shard_record["selected_pair_count"]),
                "error": f"prepare_run_context_failed: {exc}",
            }
            failure_results.append(failure)
            if progress_callback is not None:
                progress_callback(worker_id, "done", shard_record, failure)
        return failure_results

    results: list[dict[str, Any]] = []
    for shard_record in shard_records:
        if progress_callback is not None:
            progress_callback(worker_id, "start", shard_record, None)
        try:
            result = run_one_shard(
                generation_config_path,
                shard_record,
                disable_message_gate_for_shards=disable_message_gate_for_shards,
                shard_min_target_ratio=shard_min_target_ratio,
                api_ping_before_each_shard=api_ping_before_each_shard,
                resume=resume,
                prepared_context=prepared_context,
            )
        except Exception as exc:
            result = {
                "shard_id": shard_record["shard_id"],
                "shard_index": int(shard_record["shard_index"]),
                "output_dir": str(shard_record["output_dir"]),
                "status": "failed",
                "selected_pair_count": int(shard_record["selected_pair_count"]),
                "error": str(exc),
            }
            results.append(result)
            if progress_callback is not None:
                progress_callback(worker_id, "done", shard_record, result)
            if not keep_going:
                break
            continue
        results.append(result)
        if progress_callback is not None:
            progress_callback(worker_id, "done", shard_record, result)
    return results


def merge_jsonl_files(input_paths: list[Path], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line_count = 0
    with output_path.open("w", encoding="utf-8") as destination:
        for path in input_paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    destination.write(line if line.endswith("\n") else line + "\n")
                    line_count += 1
    return line_count


def aggregate_results(output_root: Path, primary_manifest: dict[str, Any], shard_results: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate_dir = output_root / "aggregate"
    successful = [item for item in shard_results if item.get("status") in {"completed", "reused"}]
    failed = [item for item in shard_results if item.get("status") == "failed"]
    successful_sorted = sorted(successful, key=lambda item: int(item["shard_index"]))
    all_samples_paths = [Path(item["output_dir"]) / "synthetic_samples.jsonl" for item in successful_sorted]
    step3_ready_paths = [Path(item["output_dir"]) / "synthetic_samples_step3_ready.jsonl" for item in successful_sorted]
    precheck_paths = [Path(item["output_dir"]) / "synthetic_samples_precheck_rejected.jsonl" for item in successful_sorted]

    aggregate_all_samples = aggregate_dir / "synthetic_samples.jsonl"
    aggregate_step3_ready = aggregate_dir / "synthetic_samples_step3_ready.jsonl"
    aggregate_precheck = aggregate_dir / "synthetic_samples_precheck_rejected.jsonl"

    merged_generated = merge_jsonl_files(all_samples_paths, aggregate_all_samples)
    merged_step3_ready = merge_jsonl_files(step3_ready_paths, aggregate_step3_ready)
    merged_precheck = merge_jsonl_files(precheck_paths, aggregate_precheck)

    summary = {
        "plan_version": FULLSCALE_PLAN_VERSION,
        "created_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "output_root": str(output_root),
        "primary_plan_manifest": primary_manifest["paths"]["selected_pairs_primary_manifest"],
        "source_pool_size": int(primary_manifest["source_pool_size"]),
        "primary_selected_pair_count": int(primary_manifest["selected_pair_count"]),
        "primary_source_coverage_count": int(primary_manifest["source_coverage_count"]),
        "primary_uncovered_source_count": int(primary_manifest["uncovered_source_count"]),
        "shard_count": int(primary_manifest["shard_count"]),
        "successful_shard_count": len(successful_sorted),
        "failed_shard_count": len(failed),
        "generated_count_merged": int(merged_generated),
        "step3_ready_count_merged": int(merged_step3_ready),
        "precheck_rejected_count_merged": int(merged_precheck),
        "step3_ready_rate_over_generated": round(merged_step3_ready / merged_generated, 6) if merged_generated else 0.0,
        "aggregate_paths": {
            "synthetic_samples_jsonl": str(aggregate_all_samples),
            "synthetic_samples_step3_ready_jsonl": str(aggregate_step3_ready),
            "synthetic_samples_precheck_rejected_jsonl": str(aggregate_precheck),
        },
        "successful_shards": successful_sorted,
        "failed_shards": failed,
    }
    write_json(aggregate_dir / "fullscale_summary.json", summary)
    lines = [
        "# Step2 Full-Scale Summary",
        "",
        f"- Source pool size: `{summary['source_pool_size']}`",
        f"- Primary selected pair count: `{summary['primary_selected_pair_count']}`",
        f"- Primary source coverage: `{summary['primary_source_coverage_count']}`",
        f"- Primary uncovered sources: `{summary['primary_uncovered_source_count']}`",
        f"- Shards: `{summary['successful_shard_count']}/{summary['shard_count']}` successful",
        f"- Generated samples merged: `{summary['generated_count_merged']}`",
        f"- Step3-ready samples merged: `{summary['step3_ready_count_merged']}`",
        f"- Step3-ready rate over generated: `{summary['step3_ready_rate_over_generated']:.6f}`",
        "",
        "## Failed Shards",
    ]
    if failed:
        for item in failed:
            lines.append(f"- `{item['shard_id']}`: `{item.get('error', 'unknown_error')}`")
    else:
        lines.append("- none")
    (aggregate_dir / "fullscale_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    generation_config_path = Path(args.generation_config) if args.generation_config else config_path
    planning_args = load_planning_args(config_path)
    output_root = Path(args.output_root)
    selection_target_count = effective_cap(int(args.selection_target_count))
    selection_repo_cap = effective_cap(int(args.selection_repo_cap))
    selection_type_pair_cap = effective_cap(int(args.selection_type_pair_cap))

    plan_payload = build_primary_plan(
        planning_args,
        selection_target_count=selection_target_count,
        selection_repo_cap=selection_repo_cap,
        selection_type_pair_cap=selection_type_pair_cap,
    )
    primary_manifest = materialize_fullscale_plan(
        output_root,
        config_path,
        generation_config_path,
        planning_args,
        plan_payload,
        int(args.shard_size),
        selection_target_count=selection_target_count,
        selection_repo_cap=selection_repo_cap,
        selection_type_pair_cap=selection_type_pair_cap,
    )
    if args.plan_only:
        safe_print(output_root)
        return

    shard_batches = partition_shard_records(primary_manifest["shards"], int(args.max_parallel_shards))
    worker_states = [
        {
            "worker_id": worker_id,
            "status": "idle",
            "shard_id": "",
            "planned_shard_count": len(batch),
            "completed_shard_count": 0,
        }
        for worker_id, batch in enumerate(shard_batches)
    ]
    shard_results_by_id: dict[str, dict[str, Any]] = {}
    state_lock = threading.Lock()

    def sorted_results() -> list[dict[str, Any]]:
        return sorted(shard_results_by_id.values(), key=lambda item: int(item.get("shard_index", 0)))

    def current_active_shards() -> list[str]:
        return [
            step2.safe_strip(state.get("shard_id"))
            for state in worker_states
            if step2.safe_strip(state.get("shard_id"))
        ]

    def progress_callback(
        worker_id: int,
        event: str,
        shard_record: dict[str, Any],
        result: dict[str, Any] | None,
    ) -> None:
        with state_lock:
            state = worker_states[worker_id]
            if event == "start":
                state["status"] = "running"
                state["shard_id"] = shard_record["shard_id"]
            elif event == "done":
                state["completed_shard_count"] = int(state.get("completed_shard_count", 0)) + 1
                state["last_result_status"] = step2.safe_strip((result or {}).get("status", ""))
                if result is not None:
                    shard_results_by_id[result["shard_id"]] = result
                state["shard_id"] = ""
                state["status"] = "completed" if state["completed_shard_count"] >= state["planned_shard_count"] else "idle"
            write_runtime_state(
                output_root,
                primary_manifest,
                sorted_results(),
                active_shard_ids=current_active_shards(),
                worker_states=worker_states,
            )

    write_runtime_state(output_root, primary_manifest, [], active_shard_ids=[], worker_states=worker_states)

    with ThreadPoolExecutor(max_workers=max(1, len(shard_batches))) as executor:
        future_to_worker = {
            executor.submit(
                run_shard_batch,
                worker_id,
                generation_config_path,
                batch,
                disable_message_gate_for_shards=bool(args.disable_message_gate_for_shards),
                shard_min_target_ratio=float(args.shard_min_target_ratio),
                api_ping_before_each_shard=bool(args.api_ping_before_each_shard),
                resume=bool(args.resume),
                keep_going=bool(args.keep_going),
                progress_callback=progress_callback,
            ): worker_id
            for worker_id, batch in enumerate(shard_batches)
            if batch
        }
        for future in as_completed(future_to_worker):
            worker_id = future_to_worker[future]
            batch_results = future.result()
            with state_lock:
                for result in batch_results:
                    shard_results_by_id[result["shard_id"]] = result
                worker_states[worker_id]["status"] = "completed"
                worker_states[worker_id]["shard_id"] = ""
                worker_states[worker_id]["completed_shard_count"] = int(worker_states[worker_id]["planned_shard_count"])
                write_runtime_state(
                    output_root,
                    primary_manifest,
                    sorted_results(),
                    active_shard_ids=current_active_shards(),
                    worker_states=worker_states,
                )

    shard_results = sorted_results()
    summary = aggregate_results(output_root, primary_manifest, shard_results)
    if not args.keep_going and summary["failed_shard_count"] > 0:
        failed_preview = ", ".join(item["shard_id"] for item in summary["failed_shards"][:5])
        raise RuntimeError(f"Full-scale shard execution failed: {failed_preview}")
    safe_print(output_root)


if __name__ == "__main__":
    main()
