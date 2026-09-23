from __future__ import annotations

from code.mica.baselines.no_slot_decoder import build_similarity_graph, cluster_units_oracle_k, run_no_slot_decoder_baseline


def test_no_slot_decoder_baseline_clusters_without_latent_slots() -> None:
    row = {
        "sample_id": "s1",
        "predicted_count": 2,
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/auth.py", "changed_identifiers": ["token", "auth"]},
            {"unit_id": "u2", "file_path": "src/auth_helper.py", "changed_identifiers": ["token"]},
            {"unit_id": "u3", "file_path": "docs/auth.md", "changed_identifiers": ["docs"]},
        ],
    }

    result = run_no_slot_decoder_baseline(row, count_mode="predicted_k")

    assert result["metadata"]["baseline"] == "no_slot_decoder"
    assert result["metadata"]["uses_latent_slots"] is False
    assert set(result["unit_to_slot"]) == {"u1", "u2", "u3"}
    assert result["predicted_count"] >= 1


def test_no_slot_decoder_oracle_k_uses_identifier_overlap_graph() -> None:
    edit_units = [
        {"unit_id": "u1", "file_path": "src/auth.py", "changed_identifiers": ["token", "auth"], "file_role": "source"},
        {"unit_id": "u2", "file_path": "src/auth_service.py", "changed_identifiers": ["token", "auth"], "file_role": "source"},
        {"unit_id": "u3", "file_path": "docs/cache.md", "changed_identifiers": ["cache"], "file_role": "doc"},
    ]
    graph = build_similarity_graph(edit_units)
    clusters = cluster_units_oracle_k(edit_units, graph, target_k=2)

    assert any(set(cluster) == {"u1", "u2"} for cluster in clusters)
