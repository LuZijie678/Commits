from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from code.mica.io_utils import read_json, read_jsonl
from code.mica.stage1_v2.leakage import audit_stage1_v2_leakage, fingerprint_text


DEFAULT_CONNECTIVITY_KEYS = (
    "atomic_family_id",
    "construction_group",
    "normalized_diff_hash",
    "pr_id",
    "repository_mirror_id",
    "cherry_pick_fingerprint",
    "backport_fingerprint",
    "revert_fingerprint",
)


def load_candidate_rows(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".jsonl":
        return [canonicalize_candidate_row(row) for row in read_jsonl(target)]
    if suffix == ".json":
        payload = read_json(target)
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return [canonicalize_candidate_row(row) for row in payload["rows"] if isinstance(row, dict)]
        if isinstance(payload, list):
            return [canonicalize_candidate_row(row) for row in payload if isinstance(row, dict)]
        raise ValueError(f"Unsupported JSON candidate structure: {target}")
    if suffix == ".csv":
        with target.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [canonicalize_candidate_row(dict(row)) for row in reader]
    raise ValueError(f"Unsupported candidate file type: {target}")


def canonicalize_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    sample_id = str(
        payload.get("sample_id")
        or payload.get("synthetic_id")
        or payload.get("commit_id")
        or payload.get("sha")
        or "missing_sample_id"
    )
    repo = str(payload.get("repo") or payload.get("repository") or "")
    sources = _normalize_source_atomic_commit_ids(payload)
    construction_group = str(
        payload.get("construction_group")
        or payload.get("construction_type")
        or payload.get("construction_route")
        or sample_id
    )
    normalized_diff_hash = str(payload.get("normalized_diff_hash") or _compute_normalized_diff_hash(payload))
    edit_unit_fingerprint = str(payload.get("edit_unit_fingerprint") or _compute_edit_unit_fingerprint(payload))
    pr_id = payload.get("pr_id")
    if pr_id in (None, ""):
        pr_id = payload.get("pull_request_id")
    repository_mirror_id = str(payload.get("repository_mirror_id") or repo or "")
    canonical = {
        **payload,
        "sample_id": sample_id,
        "repo": repo,
        "repository": repo,
        "source_atomic_commit_ids": sources,
        "construction_group": construction_group,
        "normalized_diff_hash": normalized_diff_hash,
        "edit_unit_fingerprint": edit_unit_fingerprint,
        "pr_id": str(pr_id) if pr_id not in (None, "") else None,
        "repository_mirror_id": repository_mirror_id or None,
        "cherry_pick_fingerprint": _normalize_optional_string(payload.get("cherry_pick_fingerprint")),
        "backport_fingerprint": _normalize_optional_string(payload.get("backport_fingerprint")),
        "revert_fingerprint": _normalize_optional_string(payload.get("revert_fingerprint")),
    }
    return canonical


def assign_atomic_family_and_split_components(
    rows: list[dict[str, Any]],
    *,
    connectivity_keys: tuple[str, ...] = DEFAULT_CONNECTIVITY_KEYS,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    canonical_rows = [canonicalize_candidate_row(row) for row in rows]
    atomic_components = _connected_components(canonical_rows, ("source_atomic_commit_ids",))
    rows_with_family: list[dict[str, Any]] = []
    for component_rows in atomic_components:
        family_sources = sorted(
            {
                source_id
                for row in component_rows
                for source_id in _normalize_source_atomic_commit_ids(row)
            }
        )
        family_key = "|".join(family_sources) if family_sources else "|".join(sorted(str(row["sample_id"]) for row in component_rows))
        atomic_family_id = f"af_{hashlib.sha1(family_key.encode('utf-8')).hexdigest()[:16]}"
        for row in component_rows:
            rows_with_family.append({**row, "atomic_family_id": atomic_family_id})
    split_components = _connected_components(rows_with_family, connectivity_keys)
    enriched: list[dict[str, Any]] = []
    for component_rows in split_components:
        split_key = "|".join(sorted(str(row["sample_id"]) for row in component_rows))
        split_component_id = f"sc_{hashlib.sha1(split_key.encode('utf-8')).hexdigest()[:16]}"
        for row in component_rows:
            enriched.append({**row, "split_component_id": split_component_id})
    return sorted(enriched, key=lambda row: str(row.get("sample_id") or ""))


def build_family_safe_synthetic_split(
    rows: list[dict[str, Any]],
    *,
    split_ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
    split_seed: int = 42,
) -> dict[str, Any]:
    if len(split_ratios) != 3:
        raise ValueError("split_ratios must contain train/dev/control_test ratios.")
    enriched_rows = assign_atomic_family_and_split_components(rows)
    groups = _group_by_key(enriched_rows, "split_component_id")
    ordered_groups = sorted(groups.items(), key=lambda item: _stable_rank(f"{split_seed}:{item[0]}"))
    total_count = sum(len(group_rows) for _, group_rows in ordered_groups)
    targets = {
        "train": int(round(total_count * split_ratios[0])),
        "dev": int(round(total_count * split_ratios[1])),
    }
    targets["synthetic_control_test"] = max(total_count - targets["train"] - targets["dev"], 0)
    rows_by_split = {"train": [], "dev": [], "synthetic_control_test": []}
    remaining = list(ordered_groups)
    for split_name in ("train", "dev", "synthetic_control_test"):
        target = targets[split_name]
        chosen, remaining = _choose_groups(remaining, target, split_seed=split_seed, split_name=split_name)
        rows_by_split[split_name] = [dict(row, split=split_name) for _group_id, group_rows in chosen for row in group_rows]
    leakage_report = audit_stage1_v2_leakage(rows_by_split)
    return {
        "schema_version": "mica-stage1-v2-family-split-v1",
        "split_seed": int(split_seed),
        "split_ratios": {
            "train": float(split_ratios[0]),
            "dev": float(split_ratios[1]),
            "synthetic_control_test": float(split_ratios[2]),
        },
        "family_map": build_atomic_family_map(enriched_rows),
        "rows_by_split": rows_by_split,
        "split_summary": build_split_summary(rows_by_split),
        "leakage_report": leakage_report,
    }


def build_atomic_family_map(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_by_key(rows, "atomic_family_id")
    payload: list[dict[str, Any]] = []
    for atomic_family_id, family_rows in sorted(grouped.items()):
        payload.append(
            {
                "atomic_family_id": atomic_family_id,
                "sample_count": len(family_rows),
                "sample_ids": sorted(str(row.get("sample_id")) for row in family_rows),
                "source_atomic_commit_ids": sorted(
                    {
                        source_id
                        for row in family_rows
                        for source_id in _normalize_source_atomic_commit_ids(row)
                    }
                ),
                "split_component_ids": sorted({str(row.get("split_component_id")) for row in family_rows}),
            }
        )
    return payload


def build_split_summary(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for split_name, rows in sorted(rows_by_split.items()):
        summary[split_name] = {
            "record_count": len(rows),
            "repository_count": len({str(row.get("repo") or row.get("repository") or "") for row in rows}),
            "atomic_family_count": len({str(row.get("atomic_family_id") or "") for row in rows if row.get("atomic_family_id")}),
            "construction_group_count": len({str(row.get("construction_group") or "") for row in rows if row.get("construction_group")}),
            "source_type_distribution": _distribution(rows, "source_type"),
            "cardinality_label_distribution": _distribution(rows, "cardinality_label_type"),
        }
    return summary


def _connected_components(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[list[dict[str, Any]]]:
    by_sample_id = {str(row["sample_id"]): row for row in rows}
    parent = {sample_id: sample_id for sample_id in by_sample_id}

    def find(sample_id: str) -> str:
        while parent[sample_id] != sample_id:
            parent[sample_id] = parent[parent[sample_id]]
            sample_id = parent[sample_id]
        return sample_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for key in keys:
        value_to_sample_ids: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            values = _values_for_key(row, key)
            for value in values:
                if value:
                    value_to_sample_ids[value].append(str(row["sample_id"]))
        for sample_ids in value_to_sample_ids.values():
            first = sample_ids[0]
            for sample_id in sample_ids[1:]:
                union(first, sample_id)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample_id, row in by_sample_id.items():
        grouped[find(sample_id)].append(row)
    return list(grouped.values())


def _values_for_key(row: dict[str, Any], key: str) -> list[str]:
    if key == "source_atomic_commit_ids":
        return _normalize_source_atomic_commit_ids(row)
    value = row.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if value in (None, ""):
        return []
    return [str(value)]


def _choose_groups(
    groups: list[tuple[str, list[dict[str, Any]]]],
    target_count: int,
    *,
    split_seed: int,
    split_name: str,
) -> tuple[list[tuple[str, list[dict[str, Any]]]], list[tuple[str, list[dict[str, Any]]]]]:
    chosen: list[tuple[str, list[dict[str, Any]]]] = []
    pool = list(groups)
    current = 0
    while pool and current < target_count:
        need = target_count - current
        fitting = [item for item in pool if len(item[1]) <= need]
        if fitting:
            fitting.sort(key=lambda item: (-len(item[1]), _stable_rank(f"{split_seed}:{split_name}:{item[0]}")))
            candidate = fitting[0]
        else:
            pool.sort(key=lambda item: (len(item[1]), _stable_rank(f"{split_seed}:{split_name}:{item[0]}")))
            candidate = pool[0]
        pool.remove(candidate)
        chosen.append(candidate)
        current += len(candidate[1])
    return chosen, pool


def _group_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or row.get("sample_id"))].append(dict(row))
    return grouped


def _distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get(field) or "unknown")] += 1
    return dict(sorted(counts.items()))


def _stable_rank(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _normalize_source_atomic_commit_ids(row: dict[str, Any]) -> list[str]:
    explicit = row.get("source_atomic_commit_ids")
    if isinstance(explicit, list):
        return sorted({str(item) for item in explicit if str(item or "").strip()})
    if explicit not in (None, ""):
        return sorted({item for item in str(explicit).split("|") if item})
    sources = list(row.get("sources", []) or [])
    normalized: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        repo = str(source.get("repo") or row.get("repo") or row.get("repository") or "")
        sha = str(source.get("sha") or "")
        if repo and sha:
            normalized.add(f"{repo}@{sha}")
        elif sha:
            normalized.add(sha)
    repo = str(row.get("repo") or row.get("repository") or "")
    sha = str(row.get("sha") or row.get("commit_id") or "")
    if not normalized and sha:
        normalized.add(f"{repo}@{sha}" if repo else sha)
    return sorted(normalized)


def _compute_normalized_diff_hash(row: dict[str, Any]) -> str:
    diff_text = str(row.get("synthetic_diff") or row.get("git_diff") or row.get("diff_text") or "").strip()
    normalized = "\n".join(line.rstrip() for line in diff_text.splitlines() if line.strip())
    return fingerprint_text(normalized or row.get("sample_id"))


def _compute_edit_unit_fingerprint(row: dict[str, Any]) -> str:
    edit_units = list(row.get("edit_units", []) or [])
    if edit_units:
        tokens: list[str] = []
        for unit in edit_units:
            if isinstance(unit, dict):
                tokens.append(str(unit.get("file_path") or ""))
                tokens.extend(str(item) for item in list(unit.get("changed_identifiers", []) or []))
        if tokens:
            return fingerprint_text("|".join(tokens))
    return _compute_normalized_diff_hash(row)


def _normalize_optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
