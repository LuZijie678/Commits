from __future__ import annotations

from collections import Counter
from typing import Any

from code.mica.data.schema import EditUnit, MicaSample


VALID_ALIGN_PROVENANCE = {"strict_unique_atomic", "manual_adjudicated_real"}
INVALID_ALIGN_PROVENANCE = {
    "mixed_atomic_sources",
    "conflict_rewritten",
    "mapping_incomplete",
    "pseudo_label",
    "weak_label",
    "unknown",
}


def unit_has_valid_gold_alignment_provenance(unit: EditUnit) -> bool:
    return unit.provenance_status in VALID_ALIGN_PROVENANCE and len(unit.source_atomic_commit_ids) <= 1


def sample_has_valid_gold_alignment_provenance(sample: MicaSample) -> bool:
    if sample.source_kind in {"m_weak", "hard_b"}:
        return False
    foreground_units = [unit for unit in sample.edit_units if unit.gold_intent_id is not None]
    return bool(foreground_units) and all(unit_has_valid_gold_alignment_provenance(unit) for unit in foreground_units)


def filter_samples_for_l_align(samples: list[MicaSample]) -> tuple[list[MicaSample], dict[str, Any]]:
    kept: list[MicaSample] = []
    skipped: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()
    for sample in samples:
        if sample_has_valid_gold_alignment_provenance(sample):
            kept.append(sample)
            continue
        reason = _skip_reason(sample)
        skipped.append({"sample_id": sample.sample_id, "reason": reason})
        reason_counts[reason] += 1
    return kept, {
        "input_count": len(samples),
        "kept_count": len(kept),
        "skipped_count": len(skipped),
        "skip_reason_counts": dict(reason_counts),
        "skipped": skipped,
    }


def _skip_reason(sample: MicaSample) -> str:
    if sample.source_kind in {"m_weak", "hard_b"}:
        return "source_kind_does_not_provide_gold_alignment"
    foreground_units = [unit for unit in sample.edit_units if unit.gold_intent_id is not None]
    if not foreground_units:
        return "missing_gold_intent_assignment"
    statuses = {unit.provenance_status for unit in foreground_units}
    invalid = sorted(status for status in statuses if status in INVALID_ALIGN_PROVENANCE)
    if invalid:
        return invalid[0]
    if any(len(unit.source_atomic_commit_ids) > 1 for unit in foreground_units):
        return "mixed_atomic_sources"
    return "invalid_gold_alignment_provenance"
