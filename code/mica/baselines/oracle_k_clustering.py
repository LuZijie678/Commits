from __future__ import annotations

from typing import Any

from code.mica.baselines.graph_clustering import build_evidence_similarity_graph, cluster_graph_oracle_k


def run_oracle_k_clustering_baseline(row: dict[str, Any], *, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    edit_units = list(row.get("edit_units", []))
    gold_k = max(int(row.get("gold_count", 1) or 1), 1)
    graph = build_evidence_similarity_graph(edit_units, spec or {})
    clusters = cluster_graph_oracle_k(graph, gold_k)
    unit_to_slot = {unit_id: cluster_id for cluster_id, unit_ids in clusters.items() for unit_id in unit_ids}
    return {
        "predicted_count": len(clusters),
        "unit_to_slot": unit_to_slot,
        "metadata": {
            "baseline": "oracle_k_clustering",
            "uses_gold_count_only": True,
        },
    }
