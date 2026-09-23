from __future__ import annotations

import torch

from code.mica.data.schema import EditUnit, MicaSample
from code.mica.train.eval_stage1_sanity import (
    compute_sample_alignment_metrics,
    random_gold_k_baseline_labels,
)


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
        sample_id="synthetic::alignment",
        repo="acme/demo",
        split="dev",
        k=2,
        is_multi_intent=True,
        diff_text="diff --git a/src/main.py b/src/main.py",
        edit_units=[
            _unit(unit_id="u0", file_path="src/main.py", gold_intent_id=0),
            _unit(unit_id="u1", file_path="src/helper.py", gold_intent_id=0),
            _unit(unit_id="u2", file_path="tests/test_main.py", gold_intent_id=1),
        ],
        gold_count=2,
        gold_intent_ids=["intent_0", "intent_1"],
        gold_unit_to_intent={"u0": 0, "u1": 0, "u2": 1},
        intent_types=None,
        intent_subjects=None,
        sample_weight=1.0,
        source_kind="synthetic_k2",
    )


def test_oracle_and_predicted_alignment_metrics_use_different_k_sources() -> None:
    sample = _sample()
    gold_masks = torch.tensor([[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], dtype=torch.float32)
    unit_mask = torch.tensor([True, True, True, False])
    assignment_probs = torch.tensor(
        [
            [0.90, 0.90, 0.05, 0.90],
            [0.05, 0.05, 0.90, 0.05],
            [0.05, 0.05, 0.05, 0.05],
            [0.00, 0.00, 0.00, 0.00],
        ],
        dtype=torch.float32,
    )
    slot_exist_probs = torch.tensor([0.90, 0.80, 0.05, 0.01], dtype=torch.float32)

    metrics = compute_sample_alignment_metrics(
        sample=sample,
        gold_masks=gold_masks,
        unit_mask=unit_mask,
        assignment_probs=assignment_probs,
        slot_exist_probs=slot_exist_probs,
        gold_count=2,
        predicted_count=1,
        seed=7,
    )

    assert metrics["oracle_k_alignment_pairwise_f1"] == 1.0
    assert metrics["predicted_k_alignment_pairwise_f1"] < metrics["oracle_k_alignment_pairwise_f1"]
    assert metrics["alignment_pairwise_f1_all_one_cluster"] == 0.5


def test_alignment_baselines_are_reproducible_and_padding_agnostic() -> None:
    sample = _sample()
    gold_masks = torch.tensor([[1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]], dtype=torch.float32)
    unit_mask = torch.tensor([True, True, True, False])
    assignment_probs = torch.tensor(
        [
            [0.70, 0.70, 0.30, 0.99],
            [0.30, 0.30, 0.70, 0.01],
            [0.00, 0.00, 0.00, 0.00],
            [0.00, 0.00, 0.00, 0.00],
        ],
        dtype=torch.float32,
    )
    slot_exist_probs = torch.tensor([0.80, 0.75, 0.05, 0.01], dtype=torch.float32)

    metrics = compute_sample_alignment_metrics(
        sample=sample,
        gold_masks=gold_masks,
        unit_mask=unit_mask,
        assignment_probs=assignment_probs,
        slot_exist_probs=slot_exist_probs,
        gold_count=2,
        predicted_count=2,
        seed=11,
    )

    assert metrics["gold_mask_nonempty"] is True
    assert metrics["gold_mask_mutually_exclusive"] is True
    assert metrics["gold_mask_covers_active_units"] is True
    assert metrics["alignment_pairwise_f1_file_path_baseline"] == 0.0
    assert metrics["alignment_pairwise_f1_random_gold_k_mean"] == metrics["alignment_pairwise_f1_random_gold_k_mean"]

    first = random_gold_k_baseline_labels(active_unit_count=3, gold_count=2, seed=11)
    second = random_gold_k_baseline_labels(active_unit_count=3, gold_count=2, seed=11)
    assert first == second
