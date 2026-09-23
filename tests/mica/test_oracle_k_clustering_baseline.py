from __future__ import annotations

from code.mica.baselines.oracle_k_clustering import run_oracle_k_clustering_baseline


def test_oracle_k_clustering_baseline_produces_requested_cluster_count() -> None:
    row = {
        "gold_count": 2,
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/a.py", "changed_identifiers": ["auth"]},
            {"unit_id": "u2", "file_path": "src/a.py", "changed_identifiers": ["auth"]},
            {"unit_id": "u3", "file_path": "src/b.py", "changed_identifiers": ["cache"]},
        ],
    }

    result = run_oracle_k_clustering_baseline(row)

    assert result["predicted_count"] == 2
    assert set(result["unit_to_slot"]) == {"u1", "u2", "u3"}
