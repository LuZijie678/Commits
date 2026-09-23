from __future__ import annotations

import json

from code.mica.schemas import (
    AttributionPrediction,
    AttributionSlot,
    DegradationDiagnostic,
    EditUnitRecord,
    StageRunManifest,
    StructuredIntent,
    StructuredIntentPlan,
)


def test_schema_roundtrip_preserves_identity_and_metadata() -> None:
    unit = EditUnitRecord(
        unit_id="u1",
        file_path="src/auth.py",
        hunk_id="h1",
        old_span=(1, 2),
        new_span=(1, 3),
        patch_text="@@ -1 +1 @@",
        added_lines=["token = refresh(token)"],
        deleted_lines=["token = token"],
        context_lines=["def run():"],
        changed_identifiers=["token", "refresh"],
        file_role="source",
        language="python",
        source_sha="abc123",
        gold_intent_id="I1",
        metadata={"custom": {"flag": True}},
    )
    slot = AttributionSlot(
        slot_id="slot_1",
        existence_prob=0.9,
        edit_unit_ids=["u1"],
        hunk_ids=["h1"],
        confidence=0.8,
        assignment_scores={"u1": 0.9},
        diagnostics={"note": "ok"},
    )
    intent = StructuredIntent(
        intent_id="intent_1",
        slot_id="slot_1",
        edit_unit_ids=["u1"],
        hunk_ids=["h1"],
        evidence_units=[unit],
        confidence=0.8,
        type=None,
        scope=None,
        subject=None,
        body=None,
        core_units=["u1"],
        support_units=[],
        auxiliary_units=[],
        diagnostics={"role_source": "heuristic"},
    )
    plan = StructuredIntentPlan(
        sample_id="sample_1",
        intent_count=1,
        is_multi_intent=False,
        intents=[intent],
        rendering_status="ready",
        degraded=False,
        diagnostics=[DegradationDiagnostic(code="ok", severity="info", message="ready", metadata={"n": 1})],
        metadata={"source": "test"},
    )
    prediction = AttributionPrediction(
        sample_id="sample_1",
        predicted_count=1,
        count_probs={"1": 0.9, "2": 0.1},
        active_slots=[slot],
        all_slots=[slot],
        unit_to_slot={"u1": "slot_1"},
        unit_assignment_scores={"u1": {"slot_1": 0.9}},
        source="predicted_plan",
        metadata={"debug": {"seed": 42}},
    )
    manifest = StageRunManifest(
        run_id="run_1",
        stage="stage1",
        protocol_spec_path="configs/mica/stage1_protocol_spec.json",
        manifest_path="outputs/manifest.json",
        prediction_path="outputs/predictions.jsonl",
        output_root="outputs/run_1",
        created_at="2026-06-18T00:00:00Z",
        stage2_allowed=False,
        metadata={"plan": plan.to_dict(), "prediction": prediction.to_dict()},
    )

    reloaded = StageRunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert reloaded.run_id == "run_1"
    assert reloaded.stage2_allowed is False
    assert reloaded.metadata["prediction"]["sample_id"] == "sample_1"
    assert reloaded.metadata["plan"]["intents"][0]["evidence_units"][0]["unit_id"] == "u1"


def test_optional_fields_and_unknown_metadata_are_preserved() -> None:
    payload = {
        "unit_id": "u2",
        "added_lines": [],
        "deleted_lines": [],
        "context_lines": [],
        "changed_identifiers": [],
        "metadata": {"unknown_blob": {"alpha": 1}},
    }
    unit = EditUnitRecord.from_dict(payload)
    assert unit.unit_id == "u2"
    assert unit.file_path is None
    assert unit.metadata["unknown_blob"]["alpha"] == 1
    assert unit.to_dict()["metadata"]["unknown_blob"]["alpha"] == 1


def test_json_roundtrip_preserves_sample_id_and_unit_id() -> None:
    plan = StructuredIntentPlan(
        sample_id="sample_roundtrip",
        intent_count=0,
        is_multi_intent=False,
        intents=[],
        rendering_status="degraded",
        degraded=True,
        diagnostics=[],
        metadata={"units": [EditUnitRecord(unit_id="u9").to_dict()]},
    )

    restored = StructuredIntentPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert restored.sample_id == "sample_roundtrip"
    assert restored.metadata["units"][0]["unit_id"] == "u9"
