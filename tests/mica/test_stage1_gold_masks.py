from __future__ import annotations

from code.mica.data.collate import collate_mica_samples
from code.mica.data.schema import EditUnit, MicaSample


def _unit(*, unit_id: str, file_path: str, gold_intent_id: int | None) -> EditUnit:
    return EditUnit(
        unit_id=unit_id,
        hunk_id=f"{file_path}::{unit_id}",
        file_path=file_path,
        patch_text="@@ -1 +1 @@\n-old\n+new",
        added_lines=["new"],
        deleted_lines=["old"],
        context_lines=[],
        file_role="source",
        language="python",
        identifiers=["value"],
        gold_intent_id=gold_intent_id,
    )


def test_atomic_k1_gold_mask_assigns_all_units_to_intent_zero() -> None:
    sample = MicaSample(
        sample_id="atomic::demo",
        repo="acme/demo",
        split="train",
        k=1,
        is_multi_intent=False,
        diff_text="diff --git a/src/main.py b/src/main.py",
        edit_units=[
            _unit(unit_id="u0", file_path="src/main.py", gold_intent_id=0),
            _unit(unit_id="u1", file_path="src/helper.py", gold_intent_id=0),
        ],
        gold_count=1,
        gold_intent_ids=["intent_0"],
        gold_unit_to_intent={"u0": 0, "u1": 0},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind="atomic_k1",
    )

    batch = collate_mica_samples([sample])

    assert batch["gold_assignment_masks"][0].shape == (1, 2)
    assert batch["gold_assignment_masks"][0][0].tolist() == [1.0, 1.0]


def test_synthetic_k2_gold_masks_are_nonempty_and_disjoint() -> None:
    sample = MicaSample(
        sample_id="synthetic::demo",
        repo="acme/demo",
        split="train",
        k=2,
        is_multi_intent=True,
        diff_text="diff --git a/src/main.py b/src/main.py",
        edit_units=[
            _unit(unit_id="u0", file_path="src/main.py", gold_intent_id=0),
            _unit(unit_id="u1", file_path="tests/test_main.py", gold_intent_id=1),
            _unit(unit_id="u2", file_path="src/main.py", gold_intent_id=0),
        ],
        gold_count=2,
        gold_intent_ids=["intent_0", "intent_1"],
        gold_unit_to_intent={"u0": 0, "u1": 1, "u2": 0},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind="synthetic_k2",
    )

    batch = collate_mica_samples([sample])
    gold_masks = batch["gold_assignment_masks"][0]

    assert gold_masks.shape == (2, 3)
    assert gold_masks[0].sum().item() > 0
    assert gold_masks[1].sum().item() > 0
    assert ((gold_masks[0] + gold_masks[1]) <= 1.0).all()

