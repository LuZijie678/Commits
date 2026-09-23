from __future__ import annotations

import torch

from code.mica.data.schema import EditUnit, MicaSample
from code.mica.train.eval_stage1_sanity import compute_sample_alignment_metrics


def _unit(*, unit_id: str, file_path: str, gold_intent_id: int | None) -> EditUnit:
    return EditUnit(
        unit_id=unit_id,
        hunk_id=f"{file_path}::{unit_id}",
        file_path=file_path,
        patch_text="@@ -1 +1 @@\n-old\n+new",
        added_lines=["new"],
        deleted_lines=["old"],
        context_lines=[],
        file_role="source" if "src/" in file_path else "test",
        language="python",
        identifiers=["run"],
        gold_intent_id=gold_intent_id,
    )


def _sample() -> MicaSample:
    return MicaSample(
        sample_id="synthetic::direct_metrics",
        repo="acme/demo",
        split="dev",
        k=2,
        is_multi_intent=True,
        diff_text="diff --git a/src/main.py b/src/main.py",
        edit_units=[
            _unit(unit_id="u0", file_path="src/main.py", gold_intent_id=0),
            _unit(unit_id="u1", file_path="src/helper.py", gold_intent_id=0),
            _unit(unit_id="u2", file_path="tests/test_main.py", gold_intent_id=1),
            _unit(unit_id="u3", file_path="tests/test_helper.py", gold_intent_id=1),
        ],
        gold_count=2,
        gold_intent_ids=["intent_0", "intent_1"],
        gold_unit_to_intent={"u0": 0, "u1": 0, "u2": 1, "u3": 1},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind="synthetic_k2",
    )


def test_direct_unit_and_macro_f1_metrics_are_computed() -> None:
    sample = _sample()
    gold_masks = torch.tensor(
        [[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]],
        dtype=torch.float32,
    )
    unit_mask = torch.tensor([True, True, True, True])
    assignment_probs = torch.tensor(
        [
            [0.95, 0.90, 0.05, 0.10],
            [0.05, 0.10, 0.95, 0.90],
            [0.00, 0.00, 0.00, 0.00],
            [0.00, 0.00, 0.00, 0.00],
        ],
        dtype=torch.float32,
    )
    slot_exist_probs = torch.tensor([0.95, 0.90, 0.05, 0.01], dtype=torch.float32)

    metrics = compute_sample_alignment_metrics(
        sample=sample,
        gold_masks=gold_masks,
        unit_mask=unit_mask,
        assignment_probs=assignment_probs,
        slot_exist_probs=slot_exist_probs,
        gold_count=2,
        predicted_count=2,
        seed=42,
    )

    assert metrics["unit_accuracy_hungarian"] == 1.0
    assert metrics["macro_intent_f1_hungarian"] == 1.0
    assert metrics["micro_intent_f1_hungarian"] == 1.0
    assert metrics["second_slot_gold_recall"] == 1.0
    assert metrics["k2_split_recall"] == 1.0


def test_second_slot_recall_and_nonprimary_fraction_detect_all_one_collapse() -> None:
    sample = _sample()
    gold_masks = torch.tensor(
        [[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0]],
        dtype=torch.float32,
    )
    unit_mask = torch.tensor([True, True, True, True])
    assignment_probs = torch.tensor(
        [
            [0.99, 0.98, 0.97, 0.96],
            [0.01, 0.02, 0.03, 0.04],
            [0.00, 0.00, 0.00, 0.00],
            [0.00, 0.00, 0.00, 0.00],
        ],
        dtype=torch.float32,
    )
    slot_exist_probs = torch.tensor([0.99, 0.60, 0.01, 0.01], dtype=torch.float32)

    metrics = compute_sample_alignment_metrics(
        sample=sample,
        gold_masks=gold_masks,
        unit_mask=unit_mask,
        assignment_probs=assignment_probs,
        slot_exist_probs=slot_exist_probs,
        gold_count=2,
        predicted_count=2,
        seed=7,
    )

    assert metrics["second_slot_gold_recall"] == 0.0
    assert metrics["assignment_top1_nonprimary_fraction"] == 0.0
    assert metrics["foreground_slot_usage_count"] == 1
