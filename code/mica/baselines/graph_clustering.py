from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import PurePosixPath
from typing import Any


def build_evidence_similarity_graph(edit_units: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    unit_map = {str(unit.get("unit_id")): unit for unit in edit_units if unit.get("unit_id") is not None}
    identifier_weight = float(spec.get("identifier_weight", 0.8))
    same_file_weight = float(spec.get("same_file_weight", 1.0))
    same_dir_weight = float(spec.get("same_dir_weight", 0.4))
    same_role_weight = float(spec.get("same_role_weight", 0.2))
    edges: dict[tuple[str, str], float] = {}
    for left_id, right_id in combinations(unit_map, 2):
        left = unit_map[left_id]
        right = unit_map[right_id]
        left_ids = {str(item) for item in left.get("changed_identifiers", []) if item}
        right_ids = {str(item) for item in right.get("changed_identifiers", []) if item}
        left_path = str(left.get("file_path", ""))
        right_path = str(right.get("file_path", ""))
        same_file = 1.0 if left_path and left_path == right_path else 0.0
        same_dir = 1.0 if PurePosixPath(left_path).parent == PurePosixPath(right_path).parent and left_path and right_path else 0.0
        same_role = 1.0 if str(left.get("file_role", "")).lower() == str(right.get("file_role", "")).lower() else 0.0
        identifier_overlap = _jaccard(left_ids, right_ids)
        score = (
            same_file_weight * same_file
            + same_dir_weight * same_dir
            + same_role_weight * same_role
            + identifier_weight * identifier_overlap
        )
        edges[(left_id, right_id)] = score
    return {"nodes": list(unit_map), "edges": edges}


def cluster_graph_connected_components(graph: dict[str, Any], threshold: float) -> dict[str, list[str]]:
    nodes = [str(node) for node in graph.get("nodes", [])]
    parent = {node: node for node in nodes}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for (left, right), score in dict(graph.get("edges", {})).items():
        if float(score) >= threshold:
            union(str(left), str(right))

    groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        groups[find(node)].append(node)
    return {f"cluster_{index + 1}": sorted(unit_ids) for index, unit_ids in enumerate(groups.values())}


def cluster_graph_oracle_k(graph: dict[str, Any], k: int) -> dict[str, list[str]]:
    clusters = [[node] for node in graph.get("nodes", [])]
    edges = dict(graph.get("edges", {}))
    while len(clusters) > max(int(k), 1):
        best_pair = None
        best_score = float("-inf")
        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                score = _cluster_similarity(clusters[left_index], clusters[right_index], edges)
                if score > best_score:
                    best_score = score
                    best_pair = (left_index, right_index)
        if best_pair is None:
            break
        left_index, right_index = best_pair
        clusters[left_index].extend(clusters.pop(right_index))
    return {f"cluster_{index + 1}": sorted(unit_ids) for index, unit_ids in enumerate(clusters)}


def _cluster_similarity(left: list[str], right: list[str], edges: dict[tuple[str, str], float]) -> float:
    values = []
    for left_id in left:
        for right_id in right:
            key = (left_id, right_id) if (left_id, right_id) in edges else (right_id, left_id)
            if key in edges:
                values.append(float(edges[key]))
    return sum(values) / len(values) if values else 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)
