from __future__ import annotations

from code.mica.eval.consumer_records import HumanPilotBlindMappingRecord, HumanPilotCandidateRecord
from code.mica.io_utils import read_jsonl
from code.mica.eval.export_human_pilot import export_human_pilot_package


def _system_record(sample_id: str, *, system_name: str, plan_source: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "commit_id": sample_id,
        "plan_source": plan_source,
        "message": {
            "subject": f"update {system_name} token validation",
            "body": ["- update auth docs"],
        },
        "verification": {"slot_coverage": {"intent_coverage_rate": 1.0}},
        "fallback": {"fallback_level": 0},
        "internal_confidence": 0.91,
        "slot_ids": ["slot_1"],
    }


def test_export_human_pilot_blinds_system_labels_and_writes_mapping(tmp_path) -> None:
    annotator_output = tmp_path / "annotator.jsonl"
    mapping_output = tmp_path / "mapping.jsonl"

    export_human_pilot_package(
        system_runs=[
            {"system_name": "predicted_system", "plan_source": "predicted", "records": [_system_record("s1", system_name="pred", plan_source="predicted")]},
            {"system_name": "oracle_system", "plan_source": "oracle", "records": [_system_record("s1", system_name="oracle", plan_source="oracle")]},
        ],
        evidence_display_records=[{"sample_id": "s1", "evidence_display": {"files": ["src/auth/token.py"]}}],
        annotator_output_jsonl=annotator_output,
        mapping_output_jsonl=mapping_output,
        seed=7,
    )

    annotator_rows = read_jsonl(annotator_output)
    mapping_rows = read_jsonl(mapping_output)

    assert len(annotator_rows) == 2
    assert len(mapping_rows) == 2
    assert "system_name" not in annotator_rows[0]
    assert "plan_source" not in annotator_rows[0]
    assert "slot_ids" not in annotator_rows[0]
    assert "internal_confidence" not in annotator_rows[0]
    assert mapping_rows[0]["original_system_name"] in {"predicted_system", "oracle_system"}


def test_export_human_pilot_seed_is_reproducible_and_changes_order(tmp_path) -> None:
    first_rows = tmp_path / "first.jsonl"
    first_map = tmp_path / "first_map.jsonl"
    second_rows = tmp_path / "second.jsonl"
    second_map = tmp_path / "second_map.jsonl"
    third_rows = tmp_path / "third.jsonl"
    third_map = tmp_path / "third_map.jsonl"
    system_runs = [
        {"system_name": "a", "plan_source": "predicted", "records": [_system_record("s1", system_name="a", plan_source="predicted")]},
        {"system_name": "b", "plan_source": "oracle", "records": [_system_record("s1", system_name="b", plan_source="oracle")]},
    ]
    evidence = [{"sample_id": "s1", "evidence_display": {"files": ["src/auth/token.py"]}}]

    export_human_pilot_package(system_runs=system_runs, evidence_display_records=evidence, annotator_output_jsonl=first_rows, mapping_output_jsonl=first_map, seed=13)
    export_human_pilot_package(system_runs=system_runs, evidence_display_records=evidence, annotator_output_jsonl=second_rows, mapping_output_jsonl=second_map, seed=13)
    export_human_pilot_package(system_runs=system_runs, evidence_display_records=evidence, annotator_output_jsonl=third_rows, mapping_output_jsonl=third_map, seed=21)

    assert read_jsonl(first_rows) == read_jsonl(second_rows)
    assert read_jsonl(first_rows) != read_jsonl(third_rows)


def test_export_human_pilot_protects_existing_outputs(tmp_path) -> None:
    annotator_output = tmp_path / "annotator.jsonl"
    mapping_output = tmp_path / "mapping.jsonl"
    annotator_output.write_text("exists\n", encoding="utf-8")

    try:
        export_human_pilot_package(
            system_runs=[{"system_name": "predicted", "plan_source": "predicted", "records": [_system_record("s1", system_name="pred", plan_source="predicted")]}],
            evidence_display_records=[{"sample_id": "s1", "evidence_display": {"files": ["src/auth/token.py"]}}],
            annotator_output_jsonl=annotator_output,
            mapping_output_jsonl=mapping_output,
            seed=5,
        )
    except FileExistsError as exc:
        assert "annotator.jsonl" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_export_human_pilot_round_trip_records(tmp_path) -> None:
    annotator_output = tmp_path / "annotator.jsonl"
    mapping_output = tmp_path / "mapping.jsonl"
    export_human_pilot_package(
        system_runs=[{"system_name": "predicted", "plan_source": "predicted", "records": [_system_record("s1", system_name="pred", plan_source="predicted")]}],
        evidence_display_records=[{"sample_id": "s1", "evidence_display": {"files": ["src/auth/token.py"]}}],
        annotator_output_jsonl=annotator_output,
        mapping_output_jsonl=mapping_output,
        seed=11,
    )

    candidate = HumanPilotCandidateRecord.from_dict(read_jsonl(annotator_output)[0])
    mapping = HumanPilotBlindMappingRecord.from_dict(read_jsonl(mapping_output)[0])

    assert HumanPilotCandidateRecord.from_dict(candidate.to_dict()).to_dict() == candidate.to_dict()
    assert HumanPilotBlindMappingRecord.from_dict(mapping.to_dict()).to_dict() == mapping.to_dict()
