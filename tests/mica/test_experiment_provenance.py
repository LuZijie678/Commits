from __future__ import annotations

from code.mica.experiment.provenance import capture_asset_provenance


def test_capture_asset_provenance_tracks_eval_only_and_missing_paths() -> None:
    provenance = capture_asset_provenance(
        {
            "assets": {
                "m_final_test": {"path": None, "eval_only": True},
                "hard_b_train": {"path": "/tmp/hard_b.jsonl", "eval_only": False},
            }
        }
    )

    assert provenance["asset_count"] == 2
    assert provenance["assets"]["m_final_test"]["eval_only"] is True
