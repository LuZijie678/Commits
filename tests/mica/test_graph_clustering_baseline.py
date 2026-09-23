from __future__ import annotations

from code.mica.baselines.graph_clustering import (
    build_evidence_similarity_graph,
    cluster_graph_connected_components,
    cluster_graph_oracle_k,
)


def test_graph_clustering_uses_identifier_similarity() -> None:
    units = [
        {"unit_id": "u1", "file_path": "src/auth.py", "file_role": "source", "changed_identifiers": ["token", "auth"]},
        {"unit_id": "u2", "file_path": "src/auth.py", "file_role": "source", "changed_identifiers": ["token", "session"]},
        {"unit_id": "u3", "file_path": "tests/test_auth.py", "file_role": "test", "changed_identifiers": ["assert"]},
    ]
    graph = build_evidence_similarity_graph(units, {"identifier_weight": 1.0})
    threshold_clusters = cluster_graph_connected_components(graph, threshold=0.6)
    oracle_clusters = cluster_graph_oracle_k(graph, k=2)

    assert any({"u1", "u2"} <= set(cluster) for cluster in threshold_clusters.values())
    assert len(oracle_clusters) == 2
