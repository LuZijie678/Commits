from __future__ import annotations

from code.mica.experiment.provenance import capture_git_provenance
from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest, validate_runner_manifest_against_policy
from code.mica.io_utils import REPO_ROOT
from code.mica.runners.registry import get_runner_policy


def test_stage2_train_manifest_without_approval_fails_policy_validation() -> None:
    manifest = build_runner_experiment_manifest(
        runner_name="run_stage2_calibration",
        config_paths=["configs/mica/stage2_calibration_spec.json"],
        asset_registry_path="configs/mica/data_asset_registry.json",
        seed=42,
        mode="train",
        advisor_approval=False,
    )

    result = validate_runner_manifest_against_policy(manifest, get_runner_policy("run_stage2_calibration"))

    assert manifest["stage"] == "stage2"
    assert manifest["attribution_update_policy"] is False
    assert manifest["attribution_update_scope"] == "none_core_assignment_frozen"
    assert result["valid"] is False
    assert "advisor_approval_required" in result["errors"]


def test_stage3_manifest_defaults_to_core_assignment_frozen_policy() -> None:
    manifest = build_runner_experiment_manifest(
        runner_name="run_stage3_alignment_calibration",
        config_paths=["configs/mica/stage3_alignment_calibration_spec.json"],
        asset_registry_path="configs/mica/data_asset_registry.json",
        seed=42,
        mode="train",
        advisor_approval=True,
    )
    result = validate_runner_manifest_against_policy(manifest, get_runner_policy("run_stage3_alignment_calibration"))

    assert manifest["stage"] == "stage3"
    assert manifest["attribution_update_policy"] is False
    assert manifest["attribution_update_scope"] == "core_assignment_frozen_stage3_plus_adapter_separately_gated"
    assert result["valid"] is True


def test_stage4_manifest_cannot_update_attribution_and_eval_cannot_tune_final_test() -> None:
    stage4 = build_runner_experiment_manifest(
        runner_name="run_stage4_renderer_training",
        config_paths=["configs/mica/stage4_renderer_spec.json"],
        asset_registry_path="configs/mica/data_asset_registry.json",
        seed=None,
        mode="dry_run",
        advisor_approval=False,
    )
    stage4["attribution_update_policy"] = True
    stage4_result = validate_runner_manifest_against_policy(stage4, get_runner_policy("run_stage4_renderer_training"))

    eval_manifest = build_runner_experiment_manifest(
        runner_name="run_real_domain_detection_eval",
        config_paths=["configs/mica/eval_real_domain_spec.json"],
        asset_registry_path="configs/mica/data_asset_registry.json",
        seed=None,
        mode="dry_run",
        advisor_approval=False,
    )
    eval_manifest["final_test_usage"] = {"threshold_tuning": True}
    eval_result = validate_runner_manifest_against_policy(eval_manifest, get_runner_policy("run_real_domain_detection_eval"))

    assert stage4_result["valid"] is False
    assert "attribution_update_forbidden" in stage4_result["errors"]
    assert eval_result["valid"] is False
    assert "final_test_threshold_tuning_forbidden" in eval_result["errors"]


def test_runner_manifest_uses_mica_worktree_git_provenance_when_cwd_differs(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    manifest = build_runner_experiment_manifest(
        runner_name="run_alignment_eval",
        config_paths=["configs/mica/eval_alignment_spec.json"],
        asset_registry_path="configs/mica/data_asset_registry.json",
        seed=None,
        mode="dry_run",
        advisor_approval=False,
    )

    assert manifest["git_commit"] == capture_git_provenance(str(REPO_ROOT))["git_commit"]
