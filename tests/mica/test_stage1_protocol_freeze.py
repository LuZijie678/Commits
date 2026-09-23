from __future__ import annotations

from pathlib import Path

from code.mica.data.build_stage1_formal_manifest import build_protocol_freeze_checkpoint


def test_protocol_freeze_checkpoint_marks_stage2_disallowed(tmp_path: Path) -> None:
    manifest_summary = {
        "formal_manifest_status": "frozen_runtime_manifest_created",
        "runtime_manifest_path": "outputs/mica_stage1_formal_manifest_20260615T000000Z/stage1_formal_manifest.json",
        "runtime_manifest_not_committed": True,
        "schedule_candidate": "naive_balanced_mixed_large_scale",
        "stage2_allowed": False,
        "formal_manifest_downgraded": False,
        "counts": {
            "train": {"atomic_k1": 1000, "synthetic_k2": 1000, "total": 2000},
            "dev": {"atomic_k1": 250, "synthetic_k2": 250, "total": 500},
            "test": {"atomic_k1": 250, "synthetic_k2": 250, "total": 500},
        },
        "leakage_checks": {
            "sample_id_overlap_count": 0,
            "sha_overlap_checks": {"available": True, "hard_overlap_count": 0},
            "repo_overlap_allowed_for_stage1_synthetic": True,
        },
    }

    checkpoint = build_protocol_freeze_checkpoint(manifest_summary=manifest_summary, reports_root=tmp_path)

    assert checkpoint["protocol_status"] == "candidate_frozen"
    assert checkpoint["candidate_schedule"] == "naive_balanced_mixed_large_scale"
    assert checkpoint["formal_manifest_status"] == "frozen_runtime_manifest_created"
    assert checkpoint["stage2_allowed"] is False
    assert checkpoint["next_action"] == "run_official_stage1_validation"
    assert checkpoint["runtime_manifest_not_committed"] is True
    assert "hard_b" in checkpoint["explicitly_not_included"]
    assert "Stage 2" in checkpoint["explicitly_not_included"]

    freeze_json = (tmp_path / "mica_stage1_protocol_freeze.json").read_text(encoding="utf-8")
    freeze_md = (tmp_path / "mica_stage1_protocol_freeze.md").read_text(encoding="utf-8")
    assert "diff --git" not in freeze_json
    assert "diff --git" not in freeze_md


def test_protocol_docs_exist_and_state_stage1_boundaries() -> None:
    protocol_path = Path("docs/mica-stage1-formal-protocol.md")
    plan_path = Path("docs/mica-v3-attribution-mvp-plan.md")

    if not protocol_path.exists():
        raise AssertionError("formal protocol document is required")

    protocol = protocol_path.read_text(encoding="utf-8")
    plan = plan_path.read_text(encoding="utf-8")

    assert "larger-scale naive_balanced_mixed" in protocol
    assert "Stage 2" in protocol
    assert "hard_b" in protocol
    assert "T2" in plan
    assert "pass_rate = 1.0" in plan
