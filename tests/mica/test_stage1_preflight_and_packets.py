from __future__ import annotations

import json
from pathlib import Path

from code.mica.data.asset_registry import register_local_materialization
from code.mica.data.collate import DENSE_FEATURE_NAMES, TEXT_VECTOR_DIM
from code.mica.io_utils import read_json
from code.mica.models.mica_model import MicaModel
from code.mica.runners.run_stage1_generate_approval_packets import run_stage1_generate_approval_packets
from code.mica.runners.run_stage1_official_preflight import run_stage1_official_preflight
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.checkpointing import build_model_checkpoint_payload, save_checkpoint


def _write_formal_asset(path: Path, *, asset_name: str, split: str, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-formal-asset-manifest-v1",
                "asset_name": asset_name,
                "split": split,
                "formal_ready": True,
                "summary": {
                    "record_count": len(rows),
                    "repo_count": len({row.get("repo") for row in rows}),
                    "duplicate_count": 0,
                    "leakage_group_overlap_count": 0,
                },
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def _write_registry(
    path: Path,
    *,
    dev_manifest: Path,
    final_manifest: Path,
    checkpoint_hash: str,
    checkpoint_status: str = "candidate_validated",
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mica-data-asset-registry-v2",
                "registry_status": "formal_assets_populated",
                "assets": {
                    "stage1_official_validation_dev": {
                        "path": str(dev_manifest),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "combined_stage1_dev_assets",
                        "split": "dev",
                        "record_count": 2,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "allowed_stages": ["stage1_candidate_validation", "stage1_threshold_selection"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                    "stage1_official_final_test": {
                        "path": str(final_manifest),
                        "status": "frozen",
                        "schema_version": "mica-formal-asset-manifest-v1",
                        "source_pool": "combined_stage1_test_assets",
                        "split": "test",
                        "record_count": 2,
                        "checksum": "placeholder",
                        "created_by": "unit_test",
                        "leakage_group_key": "leakage_group",
                        "required_for": ["stage1_validation_execute"],
                        "allowed_stages": ["stage1_validation_execute", "final_eval"],
                        "forbidden_stages": ["stage1_threshold_selection", "stage1_candidate_validation", "tuning"],
                        "eval_only": True,
                    },
                    "stage1_checkpoint_input": {
                        "path": None,
                        "artifact_id": "stage1_candidate_clean",
                        "status": checkpoint_status,
                        "schema_version": "mica-checkpoint-v2",
                        "source_pool": "stage1_formal_training_runtime",
                        "split": "n/a",
                        "record_count": 1,
                        "sha256": checkpoint_hash,
                        "checksum": checkpoint_hash,
                        "created_by": "unit_test",
                        "leakage_group_key": "n/a",
                        "required_for": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                        "allowed_stages": ["stage1_threshold_selection", "stage1_candidate_validation", "stage1_validation_execute"],
                        "forbidden_stages": [],
                        "eval_only": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _write_stage0_readiness(path: Path, *, formal_ready: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "formal_ready": formal_ready,
                "thresholds_approved": formal_ready,
                "Kmax_protocol_frozen": formal_ready,
                "official_final_test_unexposed": formal_ready,
            }
        ),
        encoding="utf-8",
    )


def _write_checkpoint(path: Path, *, dirty: bool = False) -> str:
    backend = MicaModelBackendAdapter(
        MicaModel(
            text_vector_dim=TEXT_VECTOR_DIM,
            dense_feature_dim=len(DENSE_FEATURE_NAMES),
            hidden_dim=16,
            kmax=4,
            use_null_slot=True,
            use_pairwise_bias=True,
            assignment_temperature=0.7,
            count_pb_coupling_strength=0.0,
        )
    )
    payload = build_model_checkpoint_payload(
        stage="stage1",
        backend=backend,
        optimizer_state={"lr": 1e-3},
        scheduler_state={"step": 1},
        model_config={
            "text_vector_dim": TEXT_VECTOR_DIM,
            "dense_feature_dim": len(DENSE_FEATURE_NAMES),
            "hidden_dim": 16,
            "kmax": 4,
            "use_null_slot": True,
            "use_pairwise_bias": True,
            "assignment_temperature": 0.7,
            "count_pb_coupling_strength": 0.0,
        },
        training_state={"epoch": 1, "global_step": 1, "seed": 7},
        threshold_version="candidate_v1",
        data_manifest_hashes={"stage1_train": "abc", "stage1_dev": "def"},
        git_commit="deadbeef",
        git_provenance={"git_commit": "deadbeef", "dirty": dirty, "scope": "repo_filtered"},
        environment={"python_version": "3.11.0", "platform": "unit-test"},
    )
    save_checkpoint(path, payload)
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_threshold_spec(path: Path, *, status: str, checkpoint_hash: str, dev_manifest_hash: str) -> None:
    path.write_text(
        json.dumps(
            {
                "threshold_status": status,
                "approved_threshold_version": "frozen_dev_thresholds_v1" if status == "frozen_dev_thresholds_v1" else None,
                "candidate_threshold_version": "stage1_dev_candidate_deadbeef",
                "selected_checkpoint_hash": checkpoint_hash,
                "selected_dev_manifest_hash": dev_manifest_hash,
                "selection_criterion": "stage1_dev_metric_gate",
                "selected_operating_point": "stage1_dev_metric_gate_v1",
                "count_accuracy_min": 0.55,
            }
        ),
        encoding="utf-8",
    )


def _write_threshold_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "selection_split": "dev_only",
                "selection_criterion": "stage1_dev_metric_gate",
                "selected_operating_point": "stage1_dev_metric_gate_v1",
            }
        ),
        encoding="utf-8",
    )


def _write_kmax_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "kmax": 4,
                "selected_Kmax": {"value": 4, "status": "implementation_default_not_final_boundary"},
                "coverage_curve_train_dev": [
                    {"candidate_kmax": 1, "coverage_at_kmax": 0.3},
                    {"candidate_kmax": 2, "coverage_at_kmax": 0.7},
                    {"candidate_kmax": 3, "coverage_at_kmax": 0.9},
                    {"candidate_kmax": 4, "coverage_at_kmax": 1.0},
                ],
                "repository_cluster_bootstrap_ci": {"mean": 1.0, "lower": 0.95, "upper": 1.0},
                "train_dev_count_distribution": {"k=1": 10, "k=2": 8, "k=3": 2, "k=4": 1, "k>4": 0},
                "source_manifest_hashes": {"stage1_official_validation_dev": "devhash"},
            }
        ),
        encoding="utf-8",
    )


def test_generate_stage1_approval_packets_stays_pending_and_marks_pretest_amendment(tmp_path: Path) -> None:
    dev_manifest = tmp_path / "stage1_dev.json"
    final_manifest = tmp_path / "stage1_final.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    checkpoint_hash = _write_checkpoint(checkpoint, dirty=False)
    register_local_materialization(
        registry_path=tmp_path / "data_asset_materializations.local.json",
        artifact_id="stage1_candidate_clean",
        path=checkpoint,
        sha256=checkpoint_hash,
        created_by="unit_test",
        git_commit="deadbeef",
    )
    _write_formal_asset(
        dev_manifest,
        asset_name="stage1_official_validation_dev",
        split="dev",
        rows=[
            {"sample_id": "dev1", "split": "dev", "repo": "acme/a", "leakage_group": "dev1"},
            {"sample_id": "dev2", "split": "dev", "repo": "acme/b", "leakage_group": "dev2"},
        ],
    )
    _write_formal_asset(
        final_manifest,
        asset_name="stage1_official_final_test",
        split="test",
        rows=[
            {"sample_id": "test1", "split": "test", "repo": "acme/c", "leakage_group": "test1"},
            {"sample_id": "test2", "split": "test", "repo": "acme/d", "leakage_group": "test2"},
        ],
    )
    registry = tmp_path / "registry.json"
    _write_registry(registry, dev_manifest=dev_manifest, final_manifest=final_manifest, checkpoint_hash=checkpoint_hash)
    threshold_spec = tmp_path / "thresholds.json"
    threshold_report = tmp_path / "threshold_report.json"
    kmax_report = tmp_path / "kmax_report.json"
    _write_threshold_spec(
        threshold_spec,
        status="candidate_selected_pending_approval",
        checkpoint_hash=checkpoint_hash,
        dev_manifest_hash="devhash",
    )
    _write_threshold_report(threshold_report)
    _write_kmax_report(kmax_report)

    result = run_stage1_generate_approval_packets(
        asset_registry_path=registry,
        threshold_spec_path=threshold_spec,
        threshold_report_path=threshold_report,
        kmax_report_path=kmax_report,
        output_root=tmp_path / "approval_packets",
        proposed_tau=0.95,
        overwrite=False,
    )

    split_audit = read_json(result["split_audit"])
    threshold_packet = read_json(result["threshold_packet"])
    kmax_packet = read_json(result["kmax_packet"])

    assert split_audit["conclusion"] == "dev_only_unexposed_final_test"
    assert threshold_packet["status"] == "pending_human_approval"
    assert threshold_packet["official_final_test_not_used"] is True
    assert kmax_packet["status"] == "pending_human_approval"
    assert kmax_packet["amendment_type"] == "pre_test_protocol_amendment"
    assert kmax_packet["predeclared"] is False


def test_stage1_official_preflight_blocks_pending_approvals_and_dirty_checkpoint(tmp_path: Path, monkeypatch) -> None:
    dev_manifest = tmp_path / "stage1_dev.json"
    final_manifest = tmp_path / "stage1_final.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    checkpoint_hash = _write_checkpoint(checkpoint, dirty=True)
    register_local_materialization(
        registry_path=tmp_path / "data_asset_materializations.local.json",
        artifact_id="stage1_candidate_clean",
        path=checkpoint,
        sha256=checkpoint_hash,
        created_by="unit_test",
        git_commit="deadbeef",
    )
    _write_formal_asset(dev_manifest, asset_name="stage1_official_validation_dev", split="dev", rows=[])
    _write_formal_asset(final_manifest, asset_name="stage1_official_final_test", split="test", rows=[])
    registry = tmp_path / "registry.json"
    _write_registry(registry, dev_manifest=dev_manifest, final_manifest=final_manifest, checkpoint_hash=checkpoint_hash)
    stage0_readiness = tmp_path / "stage0_readiness.json"
    _write_stage0_readiness(stage0_readiness, formal_ready=False)
    threshold_spec = tmp_path / "thresholds.json"
    threshold_report = tmp_path / "threshold_report.json"
    kmax_report = tmp_path / "kmax_report.json"
    _write_threshold_spec(
        threshold_spec,
        status="candidate_selected_pending_approval",
        checkpoint_hash=checkpoint_hash,
        dev_manifest_hash="devhash",
    )
    _write_threshold_report(threshold_report)
    _write_kmax_report(kmax_report)
    packets = run_stage1_generate_approval_packets(
        asset_registry_path=registry,
        threshold_spec_path=threshold_spec,
        threshold_report_path=threshold_report,
        kmax_report_path=kmax_report,
        output_root=tmp_path / "approval_packets",
        proposed_tau=0.95,
        overwrite=False,
    )
    monkeypatch.setattr(
        "code.mica.runners.run_stage1_official_preflight.capture_git_provenance",
        lambda _root: {"git_commit": "deadbeef", "dirty": False},
    )

    report = run_stage1_official_preflight(
        asset_registry_path=registry,
        metric_thresholds_path=threshold_spec,
        threshold_approval_packet_path=packets["threshold_packet"],
        kmax_decision_packet_path=packets["kmax_packet"],
        stage0_readiness_path=stage0_readiness,
        planned_output_root=tmp_path / "planned_official_output",
        output_report=tmp_path / "preflight.json",
        overwrite=False,
    )

    assert report["status"] == "blocked"
    assert report["gates"]["clean_commit_checkpoint_provenance"] is False
    assert report["gates"]["thresholds_approved"] is False
    assert report["gates"]["kmax_approved"] is False


def test_stage1_official_preflight_passes_when_all_gates_are_satisfied(tmp_path: Path, monkeypatch) -> None:
    dev_manifest = tmp_path / "stage1_dev.json"
    final_manifest = tmp_path / "stage1_final.json"
    checkpoint = tmp_path / "stage1.ckpt.pt"
    checkpoint_hash = _write_checkpoint(checkpoint, dirty=False)
    register_local_materialization(
        registry_path=tmp_path / "data_asset_materializations.local.json",
        artifact_id="stage1_candidate_clean",
        path=checkpoint,
        sha256=checkpoint_hash,
        created_by="unit_test",
        git_commit="deadbeef",
    )
    _write_formal_asset(
        dev_manifest,
        asset_name="stage1_official_validation_dev",
        split="dev",
        rows=[{"sample_id": "dev1", "split": "dev", "repo": "acme/a", "leakage_group": "dev1"}],
    )
    _write_formal_asset(
        final_manifest,
        asset_name="stage1_official_final_test",
        split="test",
        rows=[{"sample_id": "test1", "split": "test", "repo": "acme/b", "leakage_group": "test1"}],
    )
    registry = tmp_path / "registry.json"
    _write_registry(
        registry,
        dev_manifest=dev_manifest,
        final_manifest=final_manifest,
        checkpoint_hash=checkpoint_hash,
        checkpoint_status="frozen",
    )
    stage0_readiness = tmp_path / "stage0_readiness.json"
    _write_stage0_readiness(stage0_readiness, formal_ready=True)
    threshold_spec = tmp_path / "thresholds.json"
    _write_threshold_spec(
        threshold_spec,
        status="frozen_dev_thresholds_v1",
        checkpoint_hash=checkpoint_hash,
        dev_manifest_hash="devhash",
    )
    threshold_packet = tmp_path / "threshold_packet.json"
    kmax_packet = tmp_path / "kmax_packet.json"
    threshold_packet.write_text(
        json.dumps(
            {
                "status": "approved",
                "checkpoint_hash": checkpoint_hash,
                "approved_threshold_version": "frozen_dev_thresholds_v1",
            }
        ),
        encoding="utf-8",
    )
    kmax_packet.write_text(json.dumps({"status": "approved", "decision_version": "stage1-kmax-v1"}), encoding="utf-8")
    monkeypatch.setattr(
        "code.mica.runners.run_stage1_official_preflight.capture_git_provenance",
        lambda _root: {"git_commit": "deadbeef", "dirty": False},
    )

    report = run_stage1_official_preflight(
        asset_registry_path=registry,
        metric_thresholds_path=threshold_spec,
        threshold_approval_packet_path=threshold_packet,
        kmax_decision_packet_path=kmax_packet,
        stage0_readiness_path=stage0_readiness,
        planned_output_root=tmp_path / "planned_official_output",
        output_report=tmp_path / "preflight.json",
        overwrite=False,
    )

    assert report["status"] == "ready"
    assert all(report["gates"].values()) is True
