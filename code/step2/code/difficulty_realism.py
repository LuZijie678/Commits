#!/usr/bin/env python3
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
HUNK_HEADER_RE = re.compile(r"@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")
GENERIC_IDENTIFIERS = {
    "test",
    "tests",
    "config",
    "update",
    "fix",
    "refactor",
    "docs",
    "doc",
    "cache",
}

DEFAULT_DIFFICULTY_THRESHOLDS = {
    "tau_hunk_simple": 2,
    "tau_module_simple": 1,
    "tau_file_simple": 2,
    "tau_shared_file_low": 0,
    "tau_overlap_low": 0.12,
    "tau_overlap_medium": 0.25,
    "tau_dependency_low": 0.12,
    "tau_dependency_medium": 0.25,
    "tau_same_file_hunk_entangled": 2,
    "tau_topic_high": 0.75,
    "tau_realism_low": 0.5,
}

TRAINING_FOCUS_MAP = {
    "A": [
        "main intent identification",
        "basic evidence grounding",
        "diff-to-subject mapping",
    ],
    "B": [
        "main intent identification",
        "evidence selection",
        "supporting edit aggregation",
        "message compression",
    ],
    "C": [
        "intent count prediction",
        "edit-to-intent assignment",
        "intent ordering",
        "multi-intent message coverage",
    ],
    "D": [
        "fine-grained edit-to-intent alignment",
        "shared-file decomposition",
        "identifier-overlap disambiguation",
        "dependency-aware planning",
    ],
}

LEVEL_NAME_MAP = {
    "A": "single-intent simple",
    "B": "single-intent complex",
    "C": "multi-intent separable",
    "D": "multi-intent entangled",
}

STEP2_PIPELINE_OWNER = "step2_controllable_synthetic_construction"
STEP2_PIPELINE_ORDER = [
    "sample_construction",
    "difficulty_feature_extraction",
    "difficulty_level_assignment",
    "realism_feature_scoring",
    "joint_weight_metadata",
]
REALISM_WEIGHT_FORMULA = "sample_confidence * pair_quality_weight * rho * message_quality_weight"
ROUTE_SINGLE_INTENT = "route_1_single_intent"
ROUTE_MULTI_INTENT = "route_2_multi_intent"


def safe_strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def canonical_json_hash(payload: Any) -> str:
    import hashlib
    import json

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def nearest_rank_percentile(values: list[int | float], p: float) -> float:
    if not values:
        raise ValueError("empty values for percentile")
    sorted_values = sorted(values)
    rank = int(math.ceil(p * len(sorted_values)))
    rank = max(1, min(rank, len(sorted_values)))
    return float(sorted_values[rank - 1])


def classify_file_role(file_path: str) -> str:
    path = safe_strip(file_path).lower()
    if not path:
        return "other"
    parts = [part for part in path.split("/") if part]
    base = Path(path).name
    if "test" in base or any(part in {"test", "tests", "__tests__"} for part in parts):
        return "test"
    if base.endswith((".md", ".rst", ".txt", ".adoc")) or any(part in {"doc", "docs"} for part in parts):
        return "doc"
    if base.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties")) or "config" in parts:
        return "config"
    if any(part in {"build", "ci", "scripts"} for part in parts):
        return "build"
    if any(part in {"src", "lib", "app", "server", "client"} for part in parts):
        return "source"
    return "other"


def infer_module(file_path: str) -> str:
    path = safe_strip(file_path)
    if not path:
        return ""
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def tokenize_identifiers(text: str) -> set[str]:
    tokens = set()
    for token in IDENTIFIER_RE.findall(text):
        normalized = token.lower()
        if normalized in GENERIC_IDENTIFIERS:
            continue
        tokens.add(normalized)
    return tokens


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def parse_hunk_header_range(header: str) -> tuple[int, int]:
    match = HUNK_HEADER_RE.search(safe_strip(header))
    if not match:
        return (0, 0)
    start = int(match.group("new_start") or 0)
    count = int(match.group("new_count") or 1)
    return (start, max(count, 1))


def normalize_thresholds(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_DIFFICULTY_THRESHOLDS)
    if isinstance(config, dict):
        for key in DEFAULT_DIFFICULTY_THRESHOLDS:
            if key in config:
                cfg[key] = config[key]
    return cfg


def per_intent_file_paths(sample: dict[str, Any]) -> dict[int, set[str]]:
    mapping: dict[int, set[str]] = defaultdict(set)
    sources = sample.get("sources", []) or []
    for intent_id, source in enumerate(sources):
        for path in source.get("file_paths", []) or []:
            normalized = safe_strip(path)
            if normalized:
                mapping[intent_id].add(normalized)
    for unit in sample.get("edit_units", []) or []:
        file_path = safe_strip(unit.get("file_path"))
        intent_id = safe_int(unit.get("intent_id"), -1)
        if file_path and intent_id >= 0:
            mapping[intent_id].add(file_path)
    return mapping


def per_intent_modules(sample: dict[str, Any], file_paths_by_intent: dict[int, set[str]]) -> dict[int, set[str]]:
    mapping: dict[int, set[str]] = defaultdict(set)
    sources = sample.get("sources", []) or []
    for intent_id, source in enumerate(sources):
        modules = source.get("module_set", set()) or set()
        for module in modules:
            normalized = safe_strip(module)
            if normalized:
                mapping[intent_id].add(normalized)
        if not mapping[intent_id]:
            for path in file_paths_by_intent.get(intent_id, set()):
                module = infer_module(path)
                if module:
                    mapping[intent_id].add(module)
    return mapping


def per_intent_identifiers(sample: dict[str, Any], file_paths_by_intent: dict[int, set[str]]) -> dict[int, set[str]]:
    mapping: dict[int, set[str]] = defaultdict(set)
    sources = sample.get("sources", []) or []
    for intent_id, source in enumerate(sources):
        mapping[intent_id] |= tokenize_identifiers(safe_strip(source.get("subject")))
        mapping[intent_id] |= tokenize_identifiers(safe_strip(source.get("commit_message") or source.get("message")))
        for path in file_paths_by_intent.get(intent_id, set()):
            mapping[intent_id] |= tokenize_identifiers(path)
    return mapping


def compute_file_role_mix(file_paths: list[str]) -> dict[str, Any]:
    if not file_paths:
        return {"roles": {}, "distinct_role_count": 0, "dominant_role": "", "entropy": 0.0}
    counter = Counter(classify_file_role(path) for path in file_paths)
    total = sum(counter.values())
    entropy = 0.0
    for count in counter.values():
        p = count / total
        entropy -= p * math.log2(p)
    return {
        "roles": dict(counter),
        "distinct_role_count": len(counter),
        "dominant_role": counter.most_common(1)[0][0],
        "entropy": round(entropy, 6),
    }


def compute_main_topic_coherence(
    sample: dict[str, Any],
    *,
    identifiers_by_intent: dict[int, set[str]],
    modules_by_intent: dict[int, set[str]],
    file_paths_by_intent: dict[int, set[str]],
    role_mix: dict[str, Any],
) -> float:
    intent_count = safe_int(sample.get("intent_count"), len(sample.get("sources", [])) or 0)
    if intent_count <= 1:
        return 0.9
    source_subjects = [safe_strip(source.get("subject")) for source in sample.get("sources", [])]
    source_messages = [safe_strip(source.get("commit_message") or source.get("message")) for source in sample.get("sources", [])]
    combined_tokens = [tokenize_identifiers(f"{subject} {message}") for subject, message in zip(source_subjects, source_messages)]
    similarities: list[float] = []
    module_scores: list[float] = []
    id_scores: list[float] = []
    for left in range(intent_count):
        for right in range(left + 1, intent_count):
            similarities.append(jaccard(combined_tokens[left], combined_tokens[right]))
            module_scores.append(jaccard(modules_by_intent.get(left, set()), modules_by_intent.get(right, set())))
            id_scores.append(jaccard(identifiers_by_intent.get(left, set()), identifiers_by_intent.get(right, set())))
    similarity_score = sum(similarities) / len(similarities) if similarities else 0.0
    module_score = sum(module_scores) / len(module_scores) if module_scores else 0.0
    identifier_score = sum(id_scores) / len(id_scores) if id_scores else 0.0
    role_bonus = 0.2 if {"source", "test"} <= set((role_mix.get("roles") or {}).keys()) else 0.0
    if set((role_mix.get("roles") or {}).keys()) <= {"source"}:
        role_bonus += 0.1
    coherence = 0.45 * similarity_score + 0.25 * module_score + 0.20 * identifier_score + role_bonus
    return round(max(0.0, min(1.0, coherence)), 6)


def compute_pairwise_overlap_scores(identifiers_by_intent: dict[int, set[str]]) -> tuple[float, float, float]:
    keys = sorted(identifiers_by_intent.keys())
    scores: list[float] = []
    for left_index, left in enumerate(keys):
        for right in keys[left_index + 1 :]:
            scores.append(jaccard(identifiers_by_intent.get(left, set()), identifiers_by_intent.get(right, set())))
    if not scores:
        return (0.0, 0.0, 0.0)
    max_score = max(scores)
    avg_score = sum(scores) / len(scores)
    return (round(max_score, 6), round(avg_score, 6), round(max_score if len(scores) > 1 else scores[0], 6))


def compute_module_overlap_score(modules_by_intent: dict[int, set[str]]) -> float:
    keys = sorted(modules_by_intent.keys())
    scores: list[float] = []
    for left_index, left in enumerate(keys):
        for right in keys[left_index + 1 :]:
            scores.append(jaccard(modules_by_intent.get(left, set()), modules_by_intent.get(right, set())))
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def compute_shared_file_metrics(file_paths_by_intent: dict[int, set[str]], sample: dict[str, Any]) -> tuple[int, float, int]:
    file_to_intents: dict[str, set[int]] = defaultdict(set)
    for intent_id, paths in file_paths_by_intent.items():
        for path in paths:
            file_to_intents[path].add(intent_id)
    total_file_count = len(file_to_intents)
    shared_files = {path for path, intents in file_to_intents.items() if len(intents) >= 2}
    same_file_hunk_count = sum(
        1
        for unit in sample.get("edit_units", []) or []
        if safe_strip(unit.get("file_path")) in shared_files
    )
    ratio = (len(shared_files) / total_file_count) if total_file_count else 0.0
    return (len(shared_files), round(ratio, 6), same_file_hunk_count)


def compute_dependency_hint_score(
    sample: dict[str, Any],
    *,
    identifiers_by_intent: dict[int, set[str]],
    file_paths_by_intent: dict[int, set[str]],
    role_mix: dict[str, Any],
) -> float:
    keys = sorted(identifiers_by_intent.keys())
    scores: list[float] = []
    for left_index, left in enumerate(keys):
        for right in keys[left_index + 1 :]:
            overlap = jaccard(identifiers_by_intent.get(left, set()), identifiers_by_intent.get(right, set()))
            shared_path = bool(file_paths_by_intent.get(left, set()) & file_paths_by_intent.get(right, set()))
            source_test_pair = {"source", "test"} <= set((role_mix.get("roles") or {}).keys())
            score = 0.0
            if overlap >= 0.2:
                score += 0.4
            if shared_path:
                score += 0.3
            if source_test_pair and overlap > 0.0:
                score += 0.2
            scores.append(min(1.0, score))
    return round(max(scores), 6) if scores else 0.0


def compute_patch_conflict_risk(sample: dict[str, Any]) -> float:
    grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for unit in sample.get("edit_units", []) or []:
        file_path = safe_strip(unit.get("file_path"))
        if not file_path:
            continue
        start, count = parse_hunk_header_range(unit.get("header", ""))
        grouped[file_path].append((start, count))
    collisions = 0
    total_pairs = 0
    for ranges in grouped.values():
        for left_index, (left_start, left_count) in enumerate(ranges):
            left_end = left_start + max(left_count, 1)
            for right_start, right_count in ranges[left_index + 1 :]:
                right_end = right_start + max(right_count, 1)
                total_pairs += 1
                if max(left_start, right_start) <= min(left_end, right_end) + 3:
                    collisions += 1
    if total_pairs == 0:
        return 0.0
    return round(collisions / total_pairs, 6)


def compute_realism_features(sample: dict[str, Any], features: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], float, dict[str, Any], dict[str, Any]]:
    interleaving_enabled = safe_int(sample.get("intent_count"), 0) > 1
    block_sequence = list(sample.get("block_intent_sequence", []) or [])
    switches = safe_int(sample.get("block_switches"), 0)
    total_transitions = max(1, len(block_sequence) - 1)
    interleave_ratio = switches / total_transitions if total_transitions else 0.0
    shared_file_count = safe_int(features.get("shared_file_count"), 0)
    natural_interleave = 1.0 if shared_file_count == 0 else max(0.4, 1.0 - abs(interleave_ratio - 0.5))
    style_ok = 1.0
    subject = safe_strip(sample.get("synthetic_subject"))
    if "Change 1" in subject or "Intent 1" in subject:
        style_ok = 0.0
    s_structure = 1.0 if features.get("difficulty_level_candidate") else 0.0
    s_interleave = round(natural_interleave, 6)
    s_context = 1.0
    s_overlap = 1.0 if safe_float(features.get("identifier_overlap_score")) <= 0.75 else 0.5
    s_style = style_ok
    realism_score = round(s_structure * s_interleave * s_context * s_overlap * s_style, 6)

    perturbation_plan = {
        "interleaving": {
            "enabled": bool(interleaving_enabled),
            "strategy": "line_order_proxy" if interleaving_enabled else "not_applicable",
            "reason": "existing_block_order_from_materializer" if interleaving_enabled else "single_intent_or_no_interleave_needed",
        },
        "context_normalization": {
            "enabled": True,
            "context_window": "preserve_existing_diff_context",
            "header_policy": "preserve_git_diff_headers_without_source_labels",
            "reason": "main_pipeline_already_normalizes_diff_output",
        },
        "identifier_overlap_control": {
            "bucket": (
                "low"
                if safe_float(features.get("identifier_overlap_score")) < 0.12
                else "medium"
                if safe_float(features.get("identifier_overlap_score")) < 0.35
                else "high"
            ),
            "method": "sampling_only",
            "reason": "no_identifier_rewrite_allowed",
        },
        "style_normalization": {
            "enabled": True,
            "reason": "pipeline_forbids_explicit_change_labels_and_mechanical_joining",
        },
        "label_mapping_preserved": True,
    }
    perturbation_applied = {
        "interleaving": dict(perturbation_plan["interleaving"]),
        "context_normalization": dict(perturbation_plan["context_normalization"]),
        "identifier_overlap_control": dict(perturbation_plan["identifier_overlap_control"]),
        "style_normalization": dict(perturbation_plan["style_normalization"]),
        "label_mapping_preserved": True,
    }
    realism_features = {
        "s_structure": s_structure,
        "s_interleave": s_interleave,
        "s_context": s_context,
        "s_overlap": s_overlap,
        "s_style": s_style,
    }
    return realism_features, realism_score, perturbation_plan, perturbation_applied


def compute_difficulty_features(sample: dict[str, Any], config: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    thresholds = normalize_thresholds(config if isinstance(config, dict) else {})
    intent_count = safe_int(sample.get("intent_count"), len(sample.get("sources", [])) or 0)
    intent_cardinality = "single" if intent_count <= 1 else f"multi-{intent_count}"
    file_paths_by_intent = per_intent_file_paths(sample)
    modules_by_intent = per_intent_modules(sample, file_paths_by_intent)
    identifiers_by_intent = per_intent_identifiers(sample, file_paths_by_intent)

    all_file_paths = sorted({path for paths in file_paths_by_intent.values() for path in paths})
    role_mix = compute_file_role_mix(all_file_paths)
    shared_file_count, shared_file_ratio, same_file_hunk_count = compute_shared_file_metrics(file_paths_by_intent, sample)
    max_overlap, avg_overlap, identifier_overlap_score = compute_pairwise_overlap_scores(identifiers_by_intent)
    module_overlap_score = compute_module_overlap_score(modules_by_intent)
    dependency_hint_score = compute_dependency_hint_score(
        sample,
        identifiers_by_intent=identifiers_by_intent,
        file_paths_by_intent=file_paths_by_intent,
        role_mix=role_mix,
    )
    patch_conflict_risk = compute_patch_conflict_risk(sample)
    main_topic_coherence = compute_main_topic_coherence(
        sample,
        identifiers_by_intent=identifiers_by_intent,
        modules_by_intent=modules_by_intent,
        file_paths_by_intent=file_paths_by_intent,
        role_mix=role_mix,
    )

    total_file_count = len(all_file_paths) or safe_int(sample.get("merged_file_count"), 0)
    hunk_count = safe_int(sample.get("merged_hunk_count"), len(sample.get("edit_units", [])))
    module_count = len({module for modules in modules_by_intent.values() for module in modules})

    if intent_cardinality == "single":
        structure_pattern = "simple"
        if (
            total_file_count > thresholds["tau_file_simple"]
            or hunk_count > thresholds["tau_hunk_simple"]
            or module_count > thresholds["tau_module_simple"]
        ):
            structure_pattern = "complex"
    else:
        structure_pattern = "separable"
        if (
            shared_file_count >= 1
            and (
                identifier_overlap_score >= thresholds["tau_overlap_medium"]
                or dependency_hint_score >= thresholds["tau_dependency_medium"]
                or same_file_hunk_count >= thresholds["tau_same_file_hunk_entangled"]
            )
        ):
            structure_pattern = "entangled"

    features = {
        "intent_count": intent_count,
        "intent_cardinality": intent_cardinality,
        "structure_pattern": structure_pattern,
        "total_file_count": total_file_count,
        "hunk_count": hunk_count,
        "module_count": module_count,
        "file_role_mix": role_mix,
        "main_topic_coherence": main_topic_coherence,
        "shared_file_count": shared_file_count,
        "shared_file_ratio": shared_file_ratio,
        "same_file_hunk_count": same_file_hunk_count,
        "identifier_overlap_score": identifier_overlap_score,
        "max_pairwise_identifier_overlap": max_overlap,
        "avg_pairwise_identifier_overlap": avg_overlap,
        "module_overlap_score": module_overlap_score,
        "dependency_hint_score": dependency_hint_score,
        "patch_conflict_risk": patch_conflict_risk,
    }
    assignment_meta = {
        "threshold_source": "v1_default_thresholds",
        "feature_basis": "construction_units",
        "thresholds": thresholds,
    }
    return features, assignment_meta


def assign_difficulty_level(features: dict[str, Any], assignment_meta: dict[str, Any]) -> tuple[str, str]:
    intent_cardinality = features["intent_cardinality"]
    structure_pattern = features["structure_pattern"]
    level = "C"
    if intent_cardinality == "single":
        level = "A" if structure_pattern == "simple" else "B"
    elif structure_pattern == "entangled":
        level = "D"
    else:
        level = "C"
    assignment_meta["rule"] = f"{intent_cardinality}+{structure_pattern}->{level}"
    features["difficulty_level_candidate"] = level
    return level, LEVEL_NAME_MAP[level]


def annotate_sample_difficulty_and_realism(sample: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    features, assignment_meta = compute_difficulty_features(sample, config=config)
    difficulty_level, difficulty_name = assign_difficulty_level(features, assignment_meta)
    realism_features, realism_score, perturbation_plan, perturbation_applied = compute_realism_features(
        sample,
        features,
        config if isinstance(config, dict) else {},
    )

    sample["difficulty_level"] = difficulty_level
    sample["difficulty_name"] = difficulty_name
    sample["logical_intent_count"] = features["intent_count"]
    sample["intent_cardinality"] = features["intent_cardinality"]
    sample["structure_pattern"] = features["structure_pattern"]
    sample["construction_route"] = (
        ROUTE_SINGLE_INTENT if features["intent_cardinality"] == "single" else ROUTE_MULTI_INTENT
    )
    sample["difficulty_features"] = features
    assignment_meta["pipeline_owner"] = STEP2_PIPELINE_OWNER
    assignment_meta["pipeline_order"] = list(STEP2_PIPELINE_ORDER)
    sample["difficulty_assignment_meta"] = assignment_meta
    sample["training_focus"] = list(TRAINING_FOCUS_MAP[difficulty_level])
    sample["perturbation_plan"] = perturbation_plan
    sample["perturbation_applied"] = perturbation_applied
    sample["realism_features"] = realism_features
    sample["realism_score"] = realism_score
    sample["rho"] = realism_score
    sample["realism_weight_config"] = {
        "enabled": True,
        "owner_stage": STEP2_PIPELINE_OWNER,
        "rho_field": "rho",
        "realism_score_field": "realism_score",
        "weight_formula": REALISM_WEIGHT_FORMULA,
    }
    return sample


def annotate_samples_difficulty_and_realism(samples: list[dict[str, Any]], config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [annotate_sample_difficulty_and_realism(sample, config=config) for sample in samples]


def summarize_difficulty_realism(samples: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = normalize_thresholds(config if isinstance(config, dict) else {})
    level_counter = Counter(sample.get("difficulty_level", "unknown") for sample in samples)
    intent_cardinality_counter = Counter(sample.get("intent_cardinality", "") for sample in samples)
    structure_counter = Counter(sample.get("structure_pattern", "") for sample in samples)
    construction_route_counter = Counter(
        sample.get("construction_route", "")
        for sample in samples
        if safe_strip(sample.get("construction_route", ""))
    )
    realism_scores = [safe_float(sample.get("realism_score")) for sample in samples if sample.get("realism_score") is not None]
    rho_values = [safe_float(sample.get("rho")) for sample in samples if sample.get("rho") is not None]
    realism_weight_config = next(
        (
            dict(sample.get("realism_weight_config", {}) or {})
            for sample in samples
            if isinstance(sample.get("realism_weight_config"), dict) and sample.get("realism_weight_config")
        ),
        {},
    )

    def collect_feature(name: str) -> list[float]:
        values = []
        for sample in samples:
            payload = sample.get("difficulty_features", {}) or {}
            value = payload.get(name)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    return {
        "level_distribution": dict(level_counter),
        "difficulty_level_counts": dict(level_counter),
        "intent_cardinality_distribution": dict(intent_cardinality_counter),
        "intent_cardinality_counts": dict(intent_cardinality_counter),
        "structure_pattern_distribution": dict(structure_counter),
        "structure_pattern_counts": dict(structure_counter),
        "construction_route_distribution": dict(construction_route_counter),
        "pipeline_owner": STEP2_PIPELINE_OWNER,
        "pipeline_order": list(STEP2_PIPELINE_ORDER),
        "realism_weight_formula": REALISM_WEIGHT_FORMULA,
        "realism_weight_config": realism_weight_config,
        "feature_distributions": {
            "file_count": collect_feature("total_file_count"),
            "hunk_count": collect_feature("hunk_count"),
            "module_count": collect_feature("module_count"),
            "shared_file_count": collect_feature("shared_file_count"),
            "shared_file_ratio": collect_feature("shared_file_ratio"),
            "identifier_overlap_score": collect_feature("identifier_overlap_score"),
            "dependency_hint_score": collect_feature("dependency_hint_score"),
            "main_topic_coherence": collect_feature("main_topic_coherence"),
        },
        "realism_score_summary": {
            "mean": round(sum(realism_scores) / len(realism_scores), 6) if realism_scores else 0.0,
            "p50": round(float(nearest_rank_percentile(realism_scores, 0.5)), 6) if realism_scores else 0.0,
            "p90": round(float(nearest_rank_percentile(realism_scores, 0.9)), 6) if realism_scores else 0.0,
            "low_realism_count": sum(1 for score in realism_scores if score < thresholds["tau_realism_low"]),
            "tau_realism_low": thresholds["tau_realism_low"],
        },
        "rho_summary": {
            "mean": round(sum(rho_values) / len(rho_values), 6) if rho_values else 0.0,
            "p50": round(float(nearest_rank_percentile(rho_values, 0.5)), 6) if rho_values else 0.0,
            "p90": round(float(nearest_rank_percentile(rho_values, 0.9)), 6) if rho_values else 0.0,
        },
        "summary_fingerprint": canonical_json_hash(
            {
                "levels": dict(level_counter),
                "intent_cardinality": dict(intent_cardinality_counter),
                "structure": dict(structure_counter),
                "construction_route": dict(construction_route_counter),
                "realism_scores": realism_scores,
                "rho_values": rho_values,
            }
        ),
    }
