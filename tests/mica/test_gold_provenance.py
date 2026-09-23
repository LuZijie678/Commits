from __future__ import annotations

from code.mica.data.gold_provenance import filter_samples_for_l_align, sample_has_valid_gold_alignment_provenance
from code.mica.data.schema import EditUnit, MicaSample


def _unit(unit_id: str, *, provenance_status: str, source_atomic_commit_ids: list[str]) -> EditUnit:
    return EditUnit(
        unit_id=unit_id,
        hunk_id=f"h_{unit_id}",
        file_path="src/auth.py",
        patch_text="+ change",
        added_lines=["change"],
        deleted_lines=[],
        context_lines=[],
        file_role="source",
        language="python",
        identifiers=["auth"],
        gold_intent_id=0,
        provenance_status=provenance_status,
        source_atomic_commit_ids=source_atomic_commit_ids,
    )


def _sample(*, source_kind: str, units: list[EditUnit]) -> MicaSample:
    return MicaSample(
        sample_id="s1",
        repo="repo",
        split="train",
        k=1,
        is_multi_intent=False,
        diff_text="",
        edit_units=units,
        gold_count=1,
        gold_intent_ids=["intent_0"],
        gold_unit_to_intent={unit.unit_id: 0 for unit in units},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind=source_kind,
    )


def test_strict_unique_atomic_provenance_allows_l_align() -> None:
    sample = _sample(source_kind="strict_synthetic", units=[_unit("u1", provenance_status="strict_unique_atomic", source_atomic_commit_ids=["a1"])])

    assert sample_has_valid_gold_alignment_provenance(sample) is True


def test_mixed_or_weak_provenance_is_excluded_from_l_align() -> None:
    mixed = _sample(source_kind="strict_synthetic", units=[_unit("u1", provenance_status="mixed_atomic_sources", source_atomic_commit_ids=["a1", "a2"])])
    weak = _sample(source_kind="m_weak", units=[_unit("u2", provenance_status="strict_unique_atomic", source_atomic_commit_ids=["a1"])])

    kept, report = filter_samples_for_l_align([mixed, weak])

    assert kept == []
    assert report["skip_reason_counts"]["mixed_atomic_sources"] == 1
    assert report["skip_reason_counts"]["source_kind_does_not_provide_gold_alignment"] == 1
