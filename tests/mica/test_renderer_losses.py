from __future__ import annotations

from code.mica.losses.renderer_losses import entity_copy_loss, renderer_surface_distance


def test_renderer_surface_distance_is_zero_for_exact_match() -> None:
    result = renderer_surface_distance("update auth logic", "update auth logic")

    assert float(result["loss_total"]) == 0.0
    assert result["proxy_only"] is True
    assert result["training_executed"] is False


def test_entity_copy_loss_penalizes_missing_evidence_entities() -> None:
    result = entity_copy_loss("update auth logic", ["auth", "token"], lambda_copy=0.1)

    assert float(result["loss_total"]) > 0.0
    assert result["proxy_only"] is True
    assert result["entity_copy_coverage"] == 0.5
