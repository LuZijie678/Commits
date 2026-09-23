from __future__ import annotations

import torch

from code.mica.stages.stage2_real_calibration import build_stage2_freeze_plan
from code.mica.training.backend import ToyAttributionBackend
from code.mica.training.batch_adapters import adapt_hard_b_batch, adapt_m_weak_batch, adapt_strict_replay_batch
from code.mica.training.checkpointing import build_checkpoint_payload, load_checkpoint, save_checkpoint, validate_checkpoint_payload
from code.mica.training.loop_engine import run_train_epoch


def _spec() -> dict:
    return {
        "loss_weights": {
            "lambda_align": 1.0,
            "lambda_count": 0.5,
            "lambda_exist": 0.5,
        },
        "hard_b_loss": {"rho": 0.1, "margin": 0.2, "eta": 0.05},
        "m_censored_loss": {"gamma_pb": 0.3},
        "consistency": {"enabled": False},
        "gradient_clip_norm": 1.0,
    }


def test_toy_backend_forward_returns_trainable_outputs() -> None:
    backend = ToyAttributionBackend(kmax=4)
    batch = adapt_strict_replay_batch(
        {
            "sample_id": "s1",
            "gold_count": 2,
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/a.py", "patch_text": "+ token", "changed_identifiers": ["token"]},
                {"unit_id": "u2", "file_path": "tests/a_test.py", "patch_text": "+ test", "changed_identifiers": ["test"]},
            ],
        }
    )

    outputs = backend.forward(batch)

    assert outputs.count_probs.shape[-1] == 4
    assert outputs.pb_count_probs.shape[-1] == 4
    assert outputs.slot_exist_probs.shape[-1] == 4
    assert set(outputs.assignments) == {"u1", "u2"}
    assert any(param.requires_grad for param in backend.trainable_parameters())


def test_stage2_train_epoch_updates_toy_backend_parameters() -> None:
    backend = ToyAttributionBackend(kmax=4)
    optimizer = torch.optim.SGD(backend.trainable_parameters(), lr=0.1)
    before = [param.detach().clone() for param in backend.trainable_parameters()]
    batches = [
        adapt_strict_replay_batch(
            {
                "sample_id": "s1",
                "gold_count": 2,
                "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
                "edit_units": [
                    {"unit_id": "u1", "file_path": "src/a.py", "patch_text": "+ token", "changed_identifiers": ["token"]},
                    {"unit_id": "u2", "file_path": "tests/a_test.py", "patch_text": "+ test", "changed_identifiers": ["test"]},
                ],
            }
        ),
        adapt_hard_b_batch(
            {
                "sample_id": "hb1",
                "edit_units": [
                    {"unit_id": "u3", "file_path": "src/config.py", "patch_text": "+ config", "changed_identifiers": ["config"]},
                ],
            }
        ),
        adapt_m_weak_batch(
            {
                "sample_id": "mw1",
                "edit_units": [
                    {"unit_id": "u4", "file_path": "src/auth.py", "patch_text": "+ auth", "changed_identifiers": ["auth"]},
                    {"unit_id": "u5", "file_path": "docs/auth.md", "patch_text": "+ docs", "changed_identifiers": ["auth"]},
                ],
            }
        ),
    ]

    epoch = run_train_epoch(backend, batches, stage="stage2", spec=_spec(), optimizer=optimizer)
    after = [param.detach().clone() for param in backend.trainable_parameters()]

    assert epoch.step_count == 3
    assert epoch.nan_step_count == 0
    assert any(not torch.equal(left, right) for left, right in zip(before, after))


def test_stage2_freeze_plan_and_checkpoint_contract_work_with_tmp_path(tmp_path) -> None:
    backend = ToyAttributionBackend(kmax=4)
    freeze_plan = build_stage2_freeze_plan(
        {
            "freeze_strategy": {
                "first_half": {"renderer_lr": 0.0},
                "second_half": {"renderer_lr": 0.0},
            }
        },
        phase="first_half",
    )
    applied = backend.apply_freeze_plan(freeze_plan)
    payload = build_checkpoint_payload(
        stage="stage2",
        spec_snapshot={"stage": "stage2"},
        asset_registry_snapshot={"assets": {"m_final_test": {"forbidden_for_training": True}}},
        seed=42,
        epoch=1,
        metrics={"mean_loss": 1.0},
        trainable_components=freeze_plan.trainable_components,
        frozen_components=freeze_plan.frozen_components,
        forbidden_assets_not_used=["m_final_test", "hard_b_test"],
        backend_state={"toy": True},
    )
    checkpoint = tmp_path / "toy_stage2.ckpt.json"
    save_checkpoint(checkpoint, payload)
    loaded = load_checkpoint(checkpoint)

    assert applied["renderer_trainable"] is False
    assert validate_checkpoint_payload(loaded)["valid"] is True
    assert loaded["forbidden_assets_not_used"] == ["m_final_test", "hard_b_test"]
