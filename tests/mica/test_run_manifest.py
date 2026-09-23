from __future__ import annotations

import pytest

from code.mica.run_manifest import (
    assert_no_forbidden_training_flags,
    assert_renderer_does_not_update_attribution,
    assert_stage2_not_training_without_approval,
    build_run_manifest,
)


def test_build_dry_run_manifest_has_safe_defaults() -> None:
    manifest = build_run_manifest(
        stage="stage2_real_domain_count_calibration",
        mode="dry_run",
        output_root=None,
        flags={"advisor_approval_required": True},
    )

    assert manifest["training_enabled"] is False
    assert manifest["stage2_training_enabled"] is False
    assert manifest["thresholds_applied_to_pass_fail"] is False
    assert_no_forbidden_training_flags(manifest)


def test_threshold_pass_fail_flag_is_forbidden_in_non_execution_modes() -> None:
    manifest = build_run_manifest(
        stage="stage1_official_validation_dryrun",
        mode="dry_run",
        output_root=None,
        flags={"thresholds_applied_to_pass_fail": True},
    )

    with pytest.raises(ValueError, match="thresholds_applied_to_pass_fail"):
        assert_no_forbidden_training_flags(manifest)


def test_stage2_training_without_approval_raises() -> None:
    with pytest.raises(ValueError, match="advisor_stage2_approved=true"):
        assert_stage2_not_training_without_approval({"advisor_stage2_approved": False}, train_requested=True)


def test_renderer_frozen_guard_requires_attribution_freeze() -> None:
    with pytest.raises(ValueError, match="attribution_frozen_required"):
        assert_renderer_does_not_update_attribution({"attribution_frozen_required": False})

    assert_renderer_does_not_update_attribution(
        {
            "attribution_frozen_required": True,
            "renderer_reads_only_plan_and_assigned_evidence": True,
            "raw_full_diff_forbidden_as_ungrounded_context": True,
        }
    )

