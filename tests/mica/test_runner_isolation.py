from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.runners.run_official_stage1_validation import main as stage1_validation_main
from code.mica.runners.run_official_stage1_validation import run_official_stage1_validation


def _write_protocol_spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_status": "candidate_frozen",
                "stage": "stage1",
                "candidate_schedule": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "schedule": {
                    "epochs": 15,
                    "mixed_from_epoch": 1,
                    "lambda_align": 1.0,
                    "lambda_count": 0.5,
                    "lambda_exist": 0.5,
                    "replay": False,
                    "staged_warmup": False,
                    "stage2_loss": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_thresholds(path: Path) -> None:
    path.write_text(json.dumps({"threshold_status": "candidate"}), encoding="utf-8")


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schedule_candidate": "naive_balanced_mixed_large_scale",
                "stage2_allowed": False,
                "counts": {"train": {"total": 2000}},
            }
        ),
        encoding="utf-8",
    )


def test_official_validation_runner_requires_manifest_arg(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    with pytest.raises(SystemExit):
        stage1_validation_main(
            [
                "--protocol-spec",
                str(spec),
                "--metric-thresholds",
                str(thresholds),
                "--output-root",
                str(tmp_path / "out"),
                "--dry-run",
            ]
        )


def test_official_validation_runner_requires_dry_run_or_validate_only(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    with pytest.raises(ValueError):
        stage1_validation_main(
            [
                "--protocol-spec",
                str(spec),
                "--metric-thresholds",
                str(thresholds),
                "--manifest",
                str(manifest),
                "--output-root",
                str(tmp_path / "out"),
            ]
        )


def test_official_validation_dry_run_does_not_train_or_read_stage2_sources(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    result = run_official_stage1_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["training_invoked"] is False
    assert result["forbidden_sources_checked"]["hard_b"] is False
    assert result["forbidden_sources_checked"]["M_weak"] is False
    assert result["forbidden_sources_checked"]["RealDomainSplit"] is False
    assert result["forbidden_sources_checked"]["RealDomainSelective"] is False


def test_generation_pilot_does_not_import_code_mica() -> None:
    pilot_path = Path("code/generation/run_generation_pilot.py")
    text = pilot_path.read_text(encoding="utf-8")
    assert "code.mica" not in text


def test_new_runner_writes_only_to_output_root_by_default(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    run_official_stage1_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    assert (tmp_path / "out" / "stage1_official_validation_readiness.json").exists()
    assert not (tmp_path / "reports").exists()


def test_legacy_official_validation_wrapper_is_deprecated_and_points_to_canonical_runner(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    thresholds = tmp_path / "thresholds.json"
    manifest = tmp_path / "manifest.json"
    _write_protocol_spec(spec)
    _write_thresholds(thresholds)
    _write_manifest(manifest)

    result = run_official_stage1_validation(
        protocol_spec_path=spec,
        metric_thresholds_path=thresholds,
        manifest_path=manifest,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    assert result["official_validation_executed"] is False
    assert result["deprecated"] is True
    assert result["runner_role"] == "readiness_wrapper_only"
    assert result["canonical_formal_runner"] == "code/mica/runners/run_stage1_official_validation.py"
