from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any


def run_no_slot_decoder_baseline(
    row: dict[str, Any],
    *,
    count_mode: str = "predicted_k",
) -> dict[str, Any]:
    edit_units = list(row.get("edit_units", []))
    unit_ids = [str(unit.get("unit_id")) for unit in edit_units if unit.get("unit_id") is not None]
    if not unit_ids:
        return {
            "predicted_count": 0,
            "unit_to_slot": {},
            "metadata": {"baseline": "no_slot_decoder", "uses_latent_slots": False, "diagnostics": ["empty_edit_units"]},
        }

    graph = build_similarity_graph(edit_units)
    target_k = _target_cluster_count(row, count_mode=count_mode, fallback=max(len(edit_units), 1))
    if count_mode == "gold_k":
        normalized = cluster_units_oracle_k(edit_units, graph, target_k=target_k)
    else:
        normalized = cluster_units_by_threshold(edit_units, graph, threshold=float(row.get("cluster_threshold", 0.8)))
        normalized = _normalize_cluster_count(normalized, edit_units, target_k)
    unit_to_slot = {
        unit_id: f"cluster_{cluster_index + 1}"
        for cluster_index, cluster in enumerate(normalized)
        for unit_id in cluster
    }
    return {
        "predicted_count": len(normalized),
        "unit_to_slot": unit_to_slot,
        "metadata": {
            "baseline": "no_slot_decoder",
            "uses_latent_slots": False,
            "count_mode": count_mode,
            "graph_edge_count": len(graph),
        },
    }


def build_similarity_graph(edit_units: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    unit_index = {str(unit.get("unit_id")): unit for unit in edit_units if unit.get("unit_id") is not None}
    graph: dict[tuple[str, str], float] = {}
    unit_ids = list(unit_index)
    for left_index, left_id in enumerate(unit_ids):
        for right_id in unit_ids[left_index + 1 :]:
            score = _pair_similarity(unit_index[left_id], unit_index[right_id])
            graph[(left_id, right_id)] = score
    return graph


def cluster_units_by_threshold(
    edit_units: list[dict[str, Any]],
    graph: dict[tuple[str, str], float],
    *,
    threshold: float = 0.8,
) -> list[list[str]]:
    unit_ids = [str(unit.get("unit_id")) for unit in edit_units if unit.get("unit_id") is not None]
    parent = {unit_id: unit_id for unit_id in unit_ids}

    def find(unit_id: str) -> str:
        while parent[unit_id] != unit_id:
            parent[unit_id] = parent[parent[unit_id]]
            unit_id = parent[unit_id]
        return unit_id

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for (left, right), score in graph.items():
        if score >= threshold:
            union(left, right)
    groups: dict[str, list[str]] = defaultdict(list)
    for unit_id in unit_ids:
        groups[find(unit_id)].append(unit_id)
    return list(groups.values())


def cluster_units_oracle_k(
    edit_units: list[dict[str, Any]],
    graph: dict[tuple[str, str], float],
    *,
    target_k: int,
) -> list[list[str]]:
    clusters = [[str(unit.get("unit_id"))] for unit in edit_units if unit.get("unit_id") is not None]
    while len(clusters) > max(target_k, 1):
        best_pair = None
        best_score = float("-inf")
        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                score = _cluster_similarity(clusters[left_index], clusters[right_index], graph)
                if score > best_score:
                    best_score = score
                    best_pair = (left_index, right_index)
        if best_pair is None:
            break
        left_index, right_index = best_pair
        clusters[left_index].extend(clusters.pop(right_index))
    return clusters


def _target_cluster_count(row: dict[str, Any], *, count_mode: str, fallback: int) -> int:
    if count_mode == "gold_k":
        return max(int(row.get("gold_count", fallback) or fallback), 1)
    return max(int(row.get("predicted_count", row.get("gold_count", fallback)) or fallback), 1)


def _normalize_cluster_count(clusters: list[list[str]], edit_units: list[dict[str, Any]], target_k: int) -> list[list[str]]:
    runtime = [list(cluster) for cluster in clusters if cluster]
    if not runtime:
        return []
    while len(runtime) > target_k:
        smallest = min(range(len(runtime)), key=lambda index: len(runtime[index]))
        recipient = 0 if smallest != 0 else 1
        runtime[recipient].extend(runtime.pop(smallest))
    while len(runtime) < target_k:
        largest = max(range(len(runtime)), key=lambda index: len(runtime[index]))
        if len(runtime[largest]) <= 1:
            break
        split_off = runtime[largest].pop()
        runtime.append([split_off])
    return runtime


def _pair_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_path = str(left.get("file_path", ""))
    right_path = str(right.get("file_path", ""))
    left_parent = PurePosixPath(left_path).parent.as_posix()
    right_parent = PurePosixPath(right_path).parent.as_posix()
    left_identifiers = {str(item) for item in left.get("changed_identifiers", []) if item}
    right_identifiers = {str(item) for item in right.get("changed_identifiers", []) if item}
    same_file = float(left_path == right_path and left_path != "")
    same_directory = float(left_parent == right_parent and left_parent not in {"", "."})
    same_role = float(str(left.get("file_role", "")).lower() == str(right.get("file_role", "")).lower())
    identifier_jaccard = _jaccard(left_identifiers, right_identifiers)
    role_bridge = 0.25 if {"source", "test"} == {str(left.get("file_role", "")).lower(), str(right.get("file_role", "")).lower()} else 0.0
    return same_file + 0.4 * same_directory + 0.8 * identifier_jaccard + 0.2 * same_role + role_bridge


def _cluster_similarity(left_cluster: list[str], right_cluster: list[str], graph: dict[tuple[str, str], float]) -> float:
    scores = []
    for left in left_cluster:
        for right in right_cluster:
            key = (left, right) if (left, right) in graph else (right, left)
            if key in graph:
                scores.append(graph[key])
    return sum(scores) / len(scores) if scores else 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)
