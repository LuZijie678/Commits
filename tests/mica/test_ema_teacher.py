from __future__ import annotations

import torch

from code.mica.training.backend import ToyAttributionBackend
from code.mica.training.ema_teacher import EMATeacher
from code.mica.training.trainer_types import TrainBatch


def _batch() -> TrainBatch:
    return TrainBatch(
        sample_ids=["s1"],
        source_kind="strict_replay",
        edit_units=[{"unit_id": "u1", "file_path": "src/a.py", "changed_identifiers": ["token"]}],
        gold_count=1,
        gold_unit_to_intent={"u1": "i1"},
    )


def test_ema_teacher_updates_and_forwards_without_grad() -> None:
    student = ToyAttributionBackend(kmax=2)
    teacher = EMATeacher(student, decay=0.5)

    before = teacher.state_dict()
    with torch.no_grad():
        for parameter in student.parameters():
            parameter.add_(1.0)
    teacher.update(student)
    after = teacher.state_dict()
    outputs = teacher.forward(_batch())

    assert any(not torch.equal(before[key], after[key]) for key in before)
    assert outputs.count_probs is not None

