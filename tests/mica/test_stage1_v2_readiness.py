from __future__ import annotations

import copy

from code.mica.stage1_v2.protocol import build_default_stage1_v2_protocol_spec
from code.mica.stage1_v2.readiness import build_null_background_preflight, build_stage1_v2_readiness


def _asset(name: str, *, status: str, path: str | None = None, artifact_id: str | None = None, required_for: list[str]) -> dict[str, object]:
    return {
        "path": path,
        "artifact_id": artifact_id,
        "status": status,
        "schema_version": "mica-stage1-v2-family-split-v1",
        "source_pool": "fixture",
        "split": "test",
        "record_count": 1 if path else None,
        "checksum": "abc123" if path else None,
        "created_by": "unit_test",
        "created_at": "2026-07-24T00:00:00+00:00",
        "leakage_group_key": "split_component_id",
        "required_for": required_for,
    }


def _registry_with_pending_assets() -> dict[str, object]:
    return {
        "schema_version": "mica-data-asset-registry-v2",
        "registry_status": "assets_pending",
        "assets": {
            "stage1_v2_synthetic_train": _asset("stage1_v2_synthetic_train", status="pending_generation", required_for=["stage1_v2_synthetic_split"]),
            "stage1_v2_synthetic_dev": _asset("stage1_v2_synthetic_dev", status="pending_generation", required_for=["stage1_v2_synthetic_split"]),
            "stage1_v2_synthetic_control_test": _asset("stage1_v2_synthetic_control_test", status="pending_generation", required_for=["stage1_v2_synthetic_split"]),
            "stage1_v2_real_count_asset": _asset("stage1_v2_real_count_asset", status="pending_generation", required_for=["stage1_v2_real_count"]),
            "stage1_v2_real_adjudicated_test": _asset("stage1_v2_real_adjudicated_test", status="pending_generation", required_for=["stage1_v2_real_adjudicated"]),
        },
        "legacy_blocklist": {
            "stage1_v1_checkpoint_artifact_ids": ["stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42"],
            "stage1_v1_result_records": ["configs/mica/official_results/stage1_official_validation_20260723T091921Z.json"],
        },
    }


def test_null_slot_disabled_blocks_readiness() -> None:
    spec = build_default_stage1_v2_protocol_spec()
    spec["model_requirements"]["use_null_slot"] = False

    readiness = build_stage1_v2_readiness(
        protocol_spec=spec,
        asset_registry=_registry_with_pending_assets(),
        official_test_unexposed=False,
    )

    assert readiness["protocol_frozen"] is False
    assert readiness["formal_ready"] is False


def test_background_evidence_missing_blocks_readiness() -> None:
    spec = build_default_stage1_v2_protocol_spec()
    null_report = build_null_background_preflight(
        spec,
        [
            {
                "split_candidate": "dev",
                "candidate_tags": ["background_heavy"],
                "adjudicated_annotation": {
                    "unit_labels": {
                        "u1": {"label": "foreground", "intent_id": "intent_1"},
                    }
                },
            }
        ],
    )

    assert null_report["assets_ready"] is False


def test_baseline_matrix_missing_blocks_readiness() -> None:
    readiness = build_stage1_v2_readiness(
        protocol_spec=build_default_stage1_v2_protocol_spec(),
        asset_registry=_registry_with_pending_assets(),
        baseline_matrix_report={"matrix_defined": False, "runner_interface_defined": False, "all_required_baselines_declared": False},
        anti_shortcut_report={"probe_plan_defined": True, "masking_support_defined": True, "all_required_probes_declared": True},
        official_test_unexposed=False,
    )

    assert readiness["baseline_matrix_ready"] is False
    assert readiness["stage2_entry_allowed"] is False


def test_anti_shortcut_missing_blocks_readiness() -> None:
    readiness = build_stage1_v2_readiness(
        protocol_spec=build_default_stage1_v2_protocol_spec(),
        asset_registry=_registry_with_pending_assets(),
        baseline_matrix_report={"matrix_defined": True, "runner_interface_defined": True, "all_required_baselines_declared": True},
        anti_shortcut_report={"probe_plan_defined": False, "masking_support_defined": False, "all_required_probes_declared": False},
        official_test_unexposed=False,
    )

    assert readiness["anti_shortcut_ready"] is False
    assert readiness["stage2_entry_allowed"] is False


def test_stage1_v1_artifact_reuse_is_rejected() -> None:
    registry = _registry_with_pending_assets()
    registry["assets"]["stage1_v2_real_count_asset"] = {
        **registry["assets"]["stage1_v2_real_count_asset"],
        "status": "frozen",
        "artifact_id": "stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42",
    }

    readiness = build_stage1_v2_readiness(
        protocol_spec=build_default_stage1_v2_protocol_spec(),
        asset_registry=registry,
        official_test_unexposed=False,
    )

    assert readiness["legacy_stage1_v1_isolation_passed"] is False
    assert readiness["formal_ready"] is False


def test_incomplete_assets_keep_stage2_entry_blocked() -> None:
    readiness = build_stage1_v2_readiness(
        protocol_spec=build_default_stage1_v2_protocol_spec(),
        asset_registry=_registry_with_pending_assets(),
        official_test_unexposed=False,
    )

    assert readiness["formal_ready"] is False
    assert readiness["stage2_entry_allowed"] is False
