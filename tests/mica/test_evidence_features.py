from __future__ import annotations

from code.mica.data.schema import EditUnit
from code.mica.features.evidence_features import build_edit_unit_features, build_pairwise_features


def _unit(*, unit_id: str, file_path: str, patch_text: str, file_role: str, identifiers: list[str]) -> EditUnit:
    return EditUnit(
        unit_id=unit_id,
        hunk_id=f"{file_path}::hunk_0000",
        file_path=file_path,
        patch_text=patch_text,
        added_lines=["new_value = render(item)"],
        deleted_lines=["old_value = item"],
        context_lines=["def render(item):"],
        file_role=file_role,
        language="python",
        identifiers=identifiers,
        gold_intent_id=0,
    )


def test_evidence_features_and_pairwise_biases_cover_observable_signals() -> None:
    source_unit = _unit(
        unit_id="u0",
        file_path="src/render/config.py",
        patch_text="+ new_value = render(item)\n- old_value = item\n",
        file_role="source",
        identifiers=["render", "item", "config"],
    )
    test_unit = _unit(
        unit_id="u1",
        file_path="tests/test_render_config.py",
        patch_text="+ def test_render_config():\n+     assert render(item)\n",
        file_role="test",
        identifiers=["render", "item", "test_render_config"],
    )

    unit_features = build_edit_unit_features(source_unit, hunk_index=0)
    pair_features = build_pairwise_features(source_unit, test_unit)

    assert unit_features["language"] == "python"
    assert unit_features["changed_line_count"] == 2
    assert unit_features["is_test"] is False
    assert unit_features["is_config"] is True
    assert unit_features["path_tokens"][:2] == ["src", "render"]

    assert pair_features["same_file"] is False
    assert pair_features["same_directory"] is False
    assert pair_features["same_file_role"] is False
    assert pair_features["identifier_jaccard"] > 0.0
    assert pair_features["test_target_hint"] is True
