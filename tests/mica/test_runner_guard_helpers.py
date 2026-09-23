from __future__ import annotations

import pytest

from code.mica.run_manifest import assert_no_forbidden_training_flags, build_run_manifest


def test_smoke_mode_manifest_stays_non_executing() -> None:
    manifest = build_run_manifest(
        stage="downstream_offline_smoke",
        mode="smoke_only",
        output_root=None,
        flags={"advisor_approval_required": False},
    )

    assert manifest["training_enabled"] is False
    assert manifest["api_calls_enabled"] is False
    assert_no_forbidden_training_flags(manifest)


def test_dry_run_manifest_rejects_training_flags() -> None:
    manifest = build_run_manifest(
        stage="stage4_evidence_locked_renderer",
        mode="dry_run",
        output_root=None,
        flags={"training_enabled": True},
    )

    with pytest.raises(ValueError, match="training_enabled"):
        assert_no_forbidden_training_flags(manifest)

