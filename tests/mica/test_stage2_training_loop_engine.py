from __future__ import annotations

import torch

from code.mica.training.backend import ToyAttributionBackend
from code.mica.training.batch_adapters import adapt_strict_replay_batch
from code.mica.training.loop_engine import run_eval_epoch, run_train_epoch


def _batch(weight: float = 1.0):
    row = {
        "sample_id": "s1",
        "gold_count": 2,
        "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
        "sample_weight": weight,
        "edit_units": [
            {"unit_id": "u1", "file_path": "src/auth.py", "patch_text": "+ auth", "changed_identifiers": ["auth"]},
            {"unit_id": "u2", "file_path": "tests/auth_test.py", "patch_text": "+ test", "changed_identifiers": ["auth"]},
        ],
    }
    return adapt_strict_replay_batch(row)


def test_loop_engine_supports_train_and_eval_epoch() -> None:
    backend = ToyAttributionBackend(kmax=4)
    optimizer = torch.optim.Adam(backend.trainable_parameters(), lr=0.05)
    spec = {"loss_weights": {"lambda_align": 1.0, "lambda_count": 0.5, "lambda_exist": 0.5}, "gradient_clip_norm": 1.0}

    train_epoch = run_train_epoch(backend, [_batch(weight=1.0), _batch(weight=0.5)], stage="stage2", spec=spec, optimizer=optimizer)
    eval_epoch = run_eval_epoch(backend, [_batch(weight=1.0)], stage="stage2", spec=spec)

    assert train_epoch.step_count == 2
    assert train_epoch.gradient_step_count == 2
    assert eval_epoch.step_count == 1
    assert eval_epoch.gradient_step_count == 0
    assert "loss_name_histogram" in train_epoch.diagnostics
