from __future__ import annotations

from code.mica.eval.message_utility import compute_entity_coverage_loss_or_score


def test_entity_coverage_score_tracks_required_terms() -> None:
    result = compute_entity_coverage_loss_or_score(
        "update auth token tests",
        {"auth", "token", "tests"},
        required_terms={"auth", "token"},
    )

    assert result["required_term_coverage"] == 1.0
    assert result["loss_or_penalty"] == 0.0

