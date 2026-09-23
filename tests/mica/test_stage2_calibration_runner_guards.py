from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json
from code.mica.runners.run_stage2_calibration import main as stage2_main
from code.mica.runners.run_stage2_calibration import run_stage2_calibration
from code.mica.training.checkpointing import load_checkpoint, validate_checkpoint_payload


def _write_spec(path: Path, *, approved: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "stage": "stage2_real_domain_count_calibration",
                "advisor_stage2_approved": approved,
                "default_mode": "dry_run",
                "strict_replay_required": True,
                "hard_b_test_forbidden": True,
                "m_final_test_forbidden": True,
                "real_domain_split_test_forbidden": True,
                "real_domain_selective_test_forbidden": True,
                "m_weak_label_semantics": "censored_k_ge_2",
                "loss_weights": {
                    "lambda_replay": 0.5,
                    "lambda_hard": 0.5,
                    "lambda_M": 0.5,
                    "lambda_real": 0.0,
                    "lambda_cons": 0.0,
                },
                "hard_b_loss": {"rho": 0.1, "margin": 0.2, "eta": 0.05},
                "m_censored_loss": {"gamma_pb": 0.3},
                "consistency": {"enabled": False},
                "mixture_weights": {"strict_replay": 0.55, "hard_b": 0.30, "m_weak": 0.15},
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def _strict_replay_row(sample_id: str) -> dict:
    unit_id = f"{sample_id}_u1"
    return {
        "sample_id": sample_id,
        "gold_count": 1,
        "edit_units": [{"unit_id": unit_id, "file_path": "src/auth.py", "patch_text": "+ guard"}],
        "gold_unit_to_intent": {unit_id: "I1"},
    }


def _hard_b_row(sample_id: str) -> dict:
    unit_id = f"{sample_id}_u1"
    return {
        "sample_id": sample_id,
        "edit_units": [{"unit_id": unit_id, "file_path": "src/auth.py", "patch_text": "+ guard"}],
    }


def _m_weak_row(sample_id: str) -> dict:
    unit_id = f"{sample_id}_u1"
    return {
        "sample_id": sample_id,
        "edit_units": [{"unit_id": unit_id, "file_path": "src/cache.py", "patch_text": "+ cache"}],
    }


def test_stage2_runner_requires_explicit_dry_run_or_train(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    hard_b_train = tmp_path / "hb_train.json"
    hard_b_dev = tmp_path / "hb_dev.json"
    m_weak_train = tmp_path / "m_train.json"
    m_weak_dev = tmp_path / "m_dev.json"
    _write_spec(spec)
    for path in (replay, hard_b_train, hard_b_dev, m_weak_train, m_weak_dev):
        _write_manifest(path, [{"sample_id": path.stem}])

    with pytest.raises(ValueError, match="requires explicit --dry-run or guarded --train"):
        stage2_main(
            [
                "--stage2-spec",
                str(spec),
                "--strict-replay-manifest",
                str(replay),
                "--hard-b-train",
                str(hard_b_train),
                "--hard-b-dev",
                str(hard_b_dev),
                "--m-weak-train",
                str(m_weak_train),
                "--m-weak-dev",
                str(m_weak_dev),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_stage2_runner_rejects_train_without_advisor_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    hard_b_train = tmp_path / "hb_train.json"
    hard_b_dev = tmp_path / "hb_dev.json"
    m_weak_train = tmp_path / "m_train.json"
    m_weak_dev = tmp_path / "m_dev.json"
    _write_spec(spec, approved=False)
    for path in (replay, hard_b_train, hard_b_dev, m_weak_train, m_weak_dev):
        _write_manifest(path, [{"sample_id": path.stem}])

    with pytest.raises(ValueError, match="advisor_stage2_approved=true"):
        run_stage2_calibration(
            stage2_spec_path=spec,
            strict_replay_manifest=replay,
            hard_b_train_path=hard_b_train,
            hard_b_dev_path=hard_b_dev,
            m_weak_train_path=m_weak_train,
            m_weak_dev_path=m_weak_dev,
            output_root=tmp_path / "out",
            train=True,
        )


def test_stage2_runner_dry_run_stays_non_training_and_forbids_final_test(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    hard_b_train = tmp_path / "hb_train.json"
    hard_b_dev = tmp_path / "hb_dev.json"
    m_weak_train = tmp_path / "m_train.json"
    m_weak_dev = tmp_path / "m_dev.json"
    m_final_test = tmp_path / "m_final.json"
    _write_spec(spec)
    for path in (replay, hard_b_train, hard_b_dev, m_weak_train, m_weak_dev):
        _write_manifest(path, [{"sample_id": path.stem}])
    _write_manifest(m_final_test, [{"sample_id": "mf1"}])

    with pytest.raises(ValueError, match="m_final_test_forbidden"):
        run_stage2_calibration(
            stage2_spec_path=spec,
            strict_replay_manifest=replay,
            hard_b_train_path=hard_b_train,
            hard_b_dev_path=hard_b_dev,
            m_weak_train_path=m_weak_train,
            m_weak_dev_path=m_weak_dev,
            m_final_test_path=m_final_test,
            output_root=tmp_path / "out_fail",
            dry_run=True,
        )

    result = run_stage2_calibration(
        stage2_spec_path=spec,
        strict_replay_manifest=replay,
        hard_b_train_path=hard_b_train,
        hard_b_dev_path=hard_b_dev,
        m_weak_train_path=m_weak_train,
        m_weak_dev_path=m_weak_dev,
        output_root=tmp_path / "out_ok",
        dry_run=True,
    )
    saved = read_json(tmp_path / "out_ok" / "stage2_calibration_manifest.json")
    selective_artifact = read_json(tmp_path / "out_ok" / "stage2_selective_risk_calibration_artifact.json")
    selective_dev_rows = read_json(tmp_path / "out_ok" / "stage2_selective_risk_dev_rows.json")
    selective_metrics = read_json(tmp_path / "out_ok" / "stage2_selective_risk_metrics_artifact.json")
    asset_registry = read_json(tmp_path / "out_ok" / "stage2_runtime_asset_registry.json")
    asset_validation = read_json(tmp_path / "out_ok" / "stage2_asset_registry_validation.json")
    tradeoff_report = read_json(tmp_path / "out_ok" / "stage2_tradeoff_report.json")
    calibration_report = read_json(tmp_path / "out_ok" / "stage2_calibration_report.json")

    assert result["stage2_training_executed"] is False
    assert saved["m_final_test_used_for_training"] is False
    assert saved["hard_b_test_used_for_training"] is False
    assert saved["selective_risk_values_status"] == "values_to_be_populated_by_dev_calibration_script"
    assert selective_artifact["selection_split"] == "dev_only"
    assert selective_artifact["final_test_tuning"] == "forbidden"
    assert selective_artifact["threshold"]["status"] == "values_to_be_populated"
    assert selective_artifact["paper_readiness"] == "not_final_paper_ready_until_dev_calibration_artifact_is_frozen"
    assert selective_dev_rows["rows"][0]["split"] == "dev"
    assert selective_metrics["artifact_type"] == "stage2_selective_risk_dev_metrics"
    assert selective_metrics["selection_split"] == "dev_only"
    assert selective_metrics["final_test_tuning"] == "forbidden"
    assert selective_metrics["status"] == "values_to_be_populated_by_dev_calibration_script"
    assert asset_registry["registry_status"] == "runtime_paths_from_stage2_runner_args"
    assert asset_registry["assets"]["hard_b_dev"]["path"] == str(hard_b_dev)
    assert asset_validation["valid"] is True
    assert tradeoff_report["table_name"] == "stage2_tradeoff"
    assert calibration_report["table_name"] == "stage2_calibration"
    assert tradeoff_report["rows"][0]["status"] == "values_to_be_populated_by_dev_calibration_script"
    assert calibration_report["rows"][0]["paper_readiness"] == "not_final_paper_ready_until_populated"
    assert calibration_report["rows"][0]["final_test_tuning"] == "forbidden"


def test_stage2_runner_executes_guarded_train_path_when_approved(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    hard_b_train = tmp_path / "hb_train.json"
    hard_b_dev = tmp_path / "hb_dev.json"
    m_weak_train = tmp_path / "m_train.json"
    m_weak_dev = tmp_path / "m_dev.json"
    _write_spec(spec, approved=True)
    _write_manifest(replay, [_strict_replay_row("replay")])
    _write_manifest(hard_b_train, [_hard_b_row("hb_train")])
    _write_manifest(hard_b_dev, [_hard_b_row("hb_dev")])
    _write_manifest(m_weak_train, [_m_weak_row("m_train")])
    _write_manifest(m_weak_dev, [_m_weak_row("m_dev")])

    result = run_stage2_calibration(
        stage2_spec_path=spec,
        strict_replay_manifest=replay,
        hard_b_train_path=hard_b_train,
        hard_b_dev_path=hard_b_dev,
        m_weak_train_path=m_weak_train,
        m_weak_dev_path=m_weak_dev,
        output_root=tmp_path / "out_runtime",
        train=True,
    )

    assert result["stage2_training_executed"] is True
    assert result["trainer_backend_executed"] is True
    assert result["trainer_backend_type"] == "MicaModelBackendAdapter"
    assert result["toy_backend_used"] is False
    assert result["epoch"]["gradient_step_count"] > 0
    assert result["checkpoint_written"] is True
    assert result["checkpoint_valid"] is True
    checkpoint = load_checkpoint(tmp_path / "out_runtime" / "checkpoints" / "stage2_epoch_1.ckpt.json")
    assert validate_checkpoint_payload(checkpoint)["valid"] is True
    assert checkpoint["stage"] == "stage2"
    assert checkpoint["backend_state"]["backend_type"] == "MicaModelBackendAdapter"
    assert "tensor weights require full model checkpoint implementation" in checkpoint["backend_state"]["note"]


def test_stage2_runner_freezes_dev_selective_risk_artifact_when_scores_exist(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    replay = tmp_path / "replay.json"
    hard_b_train = tmp_path / "hb_train.json"
    hard_b_dev = tmp_path / "hb_dev.json"
    m_weak_train = tmp_path / "m_train.json"
    m_weak_dev = tmp_path / "m_dev.json"
    _write_spec(spec)
    spec_payload = json.loads(spec.read_text(encoding="utf-8"))
    spec_payload["selective_risk"] = {"target_coverage": 1.0}
    spec.write_text(json.dumps(spec_payload), encoding="utf-8")
    _write_manifest(replay, [_strict_replay_row("replay")])
    _write_manifest(hard_b_train, [_hard_b_row("hb_train")])
    _write_manifest(m_weak_train, [_m_weak_row("m_train")])
    risk_components = {
        "capacity_saturation": 0.1,
        "count_pb_js": 0.2,
        "assignment_entropy": 0.3,
        "residual_foreground_mass": 0.4,
        "low_slot_margin": 0.5,
    }
    hard_b_dev_row = {**_hard_b_row("hb_dev"), "split": "dev", "risk_score": 0.2, "risk_components": risk_components}
    m_weak_dev_row = {**_m_weak_row("m_dev"), "split": "dev", "risk_score": 0.4, "risk_components": risk_components}
    _write_manifest(hard_b_dev, [hard_b_dev_row])
    _write_manifest(m_weak_dev, [m_weak_dev_row])

    result = run_stage2_calibration(
        stage2_spec_path=spec,
        strict_replay_manifest=replay,
        hard_b_train_path=hard_b_train,
        hard_b_dev_path=hard_b_dev,
        m_weak_train_path=m_weak_train,
        m_weak_dev_path=m_weak_dev,
        output_root=tmp_path / "out_selective",
        dry_run=True,
    )
    selective_artifact = read_json(tmp_path / "out_selective" / "stage2_selective_risk_calibration_artifact.json")
    selective_dev_rows = read_json(tmp_path / "out_selective" / "stage2_selective_risk_dev_rows.json")
    selective_metrics = read_json(tmp_path / "out_selective" / "stage2_selective_risk_metrics_artifact.json")

    assert result["selective_risk_values_status"] == "populated_from_dev_only"
    assert result["selective_risk_threshold_status"] == "populated_from_dev_only"
    assert selective_artifact["dev_row_count"] == 2
    assert selective_artifact["dev_risk_score_count"] == 2
    assert selective_artifact["threshold"]["value"] == 0.4
    assert selective_artifact["paper_readiness"] == "protocol_defined"
    assert len(selective_dev_rows["rows"]) == 2
    assert selective_metrics["dev_row_count"] == 2
    assert selective_metrics["dev_risk_score_count"] == 2
    assert selective_metrics["mean_risk_score"] == pytest.approx(0.3)
    assert selective_metrics["paper_readiness"] == "protocol_defined"
