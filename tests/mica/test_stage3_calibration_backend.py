from __future__ import annotations

import torch

from code.mica.stages.stage3_real_alignment_calibration import build_stage3_freeze_plan
from code.mica.models.mica_model import MicaModel
from code.mica.training.backend import MicaModelBackendAdapter, ToyAttributionBackend
from code.mica.training.batch_adapters import adapt_real_alignment_batch, adapt_strict_replay_batch
from code.mica.training.loop_engine import run_train_epoch


def _stage3_spec() -> dict:
    return {
        "freeze_base_encoder": True,
        "trainable_components": ["slot_decoder_adapter", "count_head", "existence_head", "thresholds"],
        "loss_weights": {
            "lambda_align_real": 1.0,
            "lambda_count_real": 0.5,
            "lambda_exist": 0.3,
            "lambda_replay": 0.3,
        },
        "gradient_clip_norm": 1.0,
    }


def test_stage3_backend_train_epoch_supports_real_alignment_and_replay() -> None:
    backend = ToyAttributionBackend(kmax=4)
    optimizer = torch.optim.SGD(backend.trainable_parameters(), lr=0.05)
    batches = [
        adapt_real_alignment_batch(
            {
                "sample_id": "ra1",
                "gold_count": 2,
                "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
                "edit_units": [
                    {"unit_id": "u1", "file_path": "src/auth.py", "patch_text": "+ auth", "changed_identifiers": ["auth"]},
                    {"unit_id": "u2", "file_path": "src/cache.py", "patch_text": "+ cache", "changed_identifiers": ["cache"]},
                ],
            }
        ),
        adapt_strict_replay_batch(
            {
                "sample_id": "sr1",
                "gold_count": 1,
                "gold_unit_to_intent": {"u3": "i1"},
                "edit_units": [{"unit_id": "u3", "file_path": "tests/auth_test.py", "patch_text": "+ test", "changed_identifiers": ["auth"]}],
            }
        ),
    ]

    epoch = run_train_epoch(backend, batches, stage="stage3", spec=_stage3_spec(), optimizer=optimizer)

    assert epoch.step_count == 2
    assert epoch.gradient_step_count == 2
    assert epoch.nan_step_count == 0


def test_stage3_freeze_plan_can_be_applied_to_toy_backend() -> None:
    backend = ToyAttributionBackend(kmax=4)
    freeze_plan = build_stage3_freeze_plan(_stage3_spec())
    applied = backend.apply_freeze_plan(freeze_plan)

    assert applied["freeze_base_encoder"] is True
    assert "base_encoder" in applied["frozen_components"]


def test_stage3_plus_freeze_plan_exposes_trainable_low_rank_adapter() -> None:
    backend = ToyAttributionBackend(kmax=4)
    spec = {**_stage3_spec(), "stage3_plus": {"enabled": True, "lambda_drift": 0.1}}
    freeze_plan = build_stage3_freeze_plan(spec)
    applied = backend.apply_freeze_plan(freeze_plan)
    trainable = backend.trainable_parameters()

    assert "low_rank_assignment_adapter" in applied["trainable_components"]
    assert trainable
    assert any(parameter is backend.low_rank_adapter_scale for parameter in trainable)


def test_backend_outputs_include_selective_risk_diagnostics() -> None:
    backend = ToyAttributionBackend(kmax=4)
    batch = adapt_real_alignment_batch(
        {
            "sample_id": "ra-risk",
            "gold_count": 2,
            "gold_unit_to_intent": {"u1": "i1", "u2": "i2"},
            "edit_units": [
                {"unit_id": "u1", "file_path": "src/auth.py", "file_role": "source", "patch_text": "+ auth"},
                {"unit_id": "u2", "file_path": "package-lock.json", "file_role": "lockfile", "patch_text": "+ lock"},
            ],
        }
    )

    outputs = backend.forward(batch)

    assert "selective_risk_score" in outputs.diagnostics
    assert "capacity_saturation" in outputs.diagnostics["selective_risk_components"]
    assert outputs.diagnostics["selective_risk_protocol"]["final_test_tuning"] == "forbidden"
    assert outputs.diagnostics["release_decision"] == "coverage_risk_curve_only"
    assert outputs.diagnostics["release_protocol"]["threshold_state"] == "values_to_be_populated_by_dev_calibration_script"


def test_backend_outputs_include_selective_release_decision_schema() -> None:
    backend = ToyAttributionBackend(kmax=4)
    batch = adapt_real_alignment_batch(
        {
            "sample_id": "ra-release",
            "gold_count": 1,
            "gold_unit_to_intent": {"u1": "i1"},
            "edit_units": [{"unit_id": "u1", "file_path": "src/auth.py", "file_role": "source", "patch_text": "+ auth"}],
        }
    )
    batch.metadata["selective_risk_threshold"] = -1.0
    batch.metadata["overflow_evidence"] = ["capacity_saturation"]
    batch.metadata["overflow_labels_available"] = False

    outputs = backend.forward(batch)

    assert outputs.diagnostics["release_decision"] == "abstain"
    assert outputs.diagnostics["release_covered"] is False
    assert outputs.diagnostics["overflow_evidence"] == ["capacity_saturation"]
    assert outputs.diagnostics["release_protocol"]["decision_schema"] == "decompose_abstain_overflow"
    assert outputs.diagnostics["release_protocol"]["mvp_reject_option"] == "selective_abstention"


def test_mica_model_backend_adapter_exposes_calibration_parameter_groups() -> None:
    model = MicaModel(text_vector_dim=16, dense_feature_dim=9, hidden_dim=12, kmax=4)
    backend = MicaModelBackendAdapter(model)
    core_freeze = build_stage3_freeze_plan(_stage3_spec())
    applied_core = backend.apply_freeze_plan(core_freeze)
    core_trainable = backend.trainable_parameters()

    assert "count_temperature" in applied_core["trainable_components"]
    assert any(parameter is model.count_temperature_log for parameter in core_trainable)
    assert any(parameter is model.existence_temperature_log for parameter in core_trainable)

    plus_spec = {**_stage3_spec(), "stage3_plus": {"enabled": True, "lambda_drift": 0.1}}
    plus_freeze = build_stage3_freeze_plan(plus_spec)
    applied_plus = backend.apply_freeze_plan(plus_freeze)
    plus_trainable = backend.trainable_parameters()

    assert "low_rank_assignment_adapter" in applied_plus["trainable_components"]
    assert any(parameter is model.slot_decoder.low_rank_adapter_scale for parameter in plus_trainable)
