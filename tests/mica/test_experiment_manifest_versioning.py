from __future__ import annotations

from code.mica.experiment.manifest_versioning import (
    build_experiment_manifest,
    compute_manifest_hash,
    validate_experiment_manifest,
)


def test_experiment_manifest_versioning_records_required_fields() -> None:
    manifest = build_experiment_manifest(
        stage="stage2",
        protocol_version="v1",
        config_hash="cfg",
        asset_registry_hash="assets",
        git_commit="abc123",
        dirty=False,
        seed=42,
        advisor_approval_status="pending",
    )

    assert validate_experiment_manifest(manifest)["valid"] is True
    assert compute_manifest_hash(manifest)
