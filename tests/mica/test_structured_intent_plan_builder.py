from __future__ import annotations

from code.mica.plan_builder import StructuredIntentPlanBuilder
from code.mica.schemas import AttributionPrediction, AttributionSlot, EditUnitRecord


def _unit(unit_id: str, *, role: str = "source", file_path: str = "src/auth.py") -> EditUnitRecord:
    return EditUnitRecord(
        unit_id=unit_id,
        file_path=file_path,
        hunk_id=f"h_{unit_id}",
        file_role=role,
        changed_identifiers=[unit_id],
        added_lines=[f"change_{unit_id}"],
    )


def _slot(slot_id: str, unit_ids: list[str]) -> AttributionSlot:
    return AttributionSlot(
        slot_id=slot_id,
        existence_prob=0.9,
        edit_unit_ids=unit_ids,
        hunk_ids=[f"h_{unit_id}" for unit_id in unit_ids],
        confidence=0.8,
        assignment_scores={unit_id: 0.9 for unit_id in unit_ids},
        diagnostics={},
    )


def test_builder_creates_single_intent_plan_for_k1_prediction() -> None:
    prediction = AttributionPrediction(
        sample_id="sample_k1",
        predicted_count=1,
        count_probs={"1": 0.95},
        active_slots=[_slot("slot_1", ["u1"])],
        all_slots=[_slot("slot_1", ["u1"])],
        unit_to_slot={"u1": "slot_1"},
        unit_assignment_scores={"u1": {"slot_1": 0.95}},
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(prediction=prediction, edit_units=[_unit("u1")])

    assert plan.sample_id == "sample_k1"
    assert plan.intent_count == 1
    assert len(plan.intents) == 1
    assert plan.degraded is False


def test_builder_creates_two_intents_for_k2_prediction() -> None:
    prediction = AttributionPrediction(
        sample_id="sample_k2",
        predicted_count=2,
        count_probs={"1": 0.1, "2": 0.9},
        active_slots=[_slot("slot_1", ["u1"]), _slot("slot_2", ["u2"])],
        all_slots=[_slot("slot_1", ["u1"]), _slot("slot_2", ["u2"])],
        unit_to_slot={"u1": "slot_1", "u2": "slot_2"},
        unit_assignment_scores={"u1": {"slot_1": 0.9}, "u2": {"slot_2": 0.9}},
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(prediction=prediction, edit_units=[_unit("u1"), _unit("u2", file_path="docs/api.md", role="doc")])

    assert plan.intent_count == 2
    assert len(plan.intents) == 2
    assert plan.is_multi_intent is True
    assert {intent.slot_id for intent in plan.intents} == {"slot_1", "slot_2"}


def test_builder_marks_degraded_when_active_slots_are_empty() -> None:
    prediction = AttributionPrediction(
        sample_id="empty_slots",
        predicted_count=2,
        count_probs={},
        active_slots=[],
        all_slots=[],
        unit_to_slot={},
        unit_assignment_scores={},
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(prediction=prediction, edit_units=[_unit("u1")])
    codes = {diagnostic.code for diagnostic in plan.diagnostics}
    assert plan.degraded is True
    assert "empty_active_slots" in codes


def test_builder_emits_diagnostic_for_count_active_slot_mismatch() -> None:
    prediction = AttributionPrediction(
        sample_id="mismatch",
        predicted_count=2,
        count_probs={"2": 0.8},
        active_slots=[_slot("slot_1", ["u1"])],
        all_slots=[_slot("slot_1", ["u1"])],
        unit_to_slot={"u1": "slot_1"},
        unit_assignment_scores={"u1": {"slot_1": 0.9}},
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(prediction=prediction, edit_units=[_unit("u1")])
    assert "k_hat_mismatch_active_slots" in {diagnostic.code for diagnostic in plan.diagnostics}


def test_builder_emits_assignment_to_unknown_slot_diagnostic() -> None:
    prediction = AttributionPrediction(
        sample_id="unknown_slot",
        predicted_count=1,
        count_probs={"1": 0.9},
        active_slots=[_slot("slot_1", ["u1"])],
        all_slots=[_slot("slot_1", ["u1"])],
        unit_to_slot={"u1": "slot_missing"},
        unit_assignment_scores={"u1": {"slot_missing": 0.9}},
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(prediction=prediction, edit_units=[_unit("u1")])
    assert "assignment_to_unknown_slot" in {diagnostic.code for diagnostic in plan.diagnostics}


def test_builder_detects_slot_collapse_without_requiring_subject_or_body() -> None:
    prediction = AttributionPrediction(
        sample_id="collapse",
        predicted_count=2,
        count_probs={"2": 0.9},
        active_slots=[_slot("slot_1", ["u1", "u2", "u3", "u4"]), _slot("slot_2", [])],
        all_slots=[_slot("slot_1", ["u1", "u2", "u3", "u4"]), _slot("slot_2", [])],
        unit_to_slot={"u1": "slot_1", "u2": "slot_1", "u3": "slot_1", "u4": "slot_1"},
        unit_assignment_scores={
            "u1": {"slot_1": 0.9},
            "u2": {"slot_1": 0.9},
            "u3": {"slot_1": 0.9},
            "u4": {"slot_1": 0.9},
        },
        source="predicted_plan",
        metadata={},
    )

    plan = StructuredIntentPlanBuilder().build(
        prediction=prediction,
        edit_units=[_unit("u1"), _unit("u2"), _unit("u3"), _unit("u4")],
    )
    assert "slot_collapse_detected" in {diagnostic.code for diagnostic in plan.diagnostics}
    assert all(intent.subject is None for intent in plan.intents)
    assert all(intent.body is None for intent in plan.intents)
