from __future__ import annotations

import json

from code.mica.config_loader import compute_config_family_hash, load_all_stage_configs, load_mica_config, validate_config_family
from code.mica.io_utils import REPO_ROOT


def test_load_single_config_and_hash_family(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stage": "stage1", "advisor_stage1_validation_approved": False}), encoding="utf-8")

    loaded = load_mica_config(str(path))
    digest = compute_config_family_hash({"single": loaded})

    assert loaded["stage"] == "stage1"
    assert len(digest) == 64


def test_validate_config_family_enforces_final_test_and_loss_guards() -> None:
    configs = load_all_stage_configs("configs/mica")
    result = validate_config_family(configs)

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["summary"]["stage2_consistency_default_enabled"] is False


def test_load_all_stage_configs_resolves_repo_relative_root_outside_worktree(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    configs = load_all_stage_configs("configs/mica")

    assert "stage1_protocol_spec" in configs
    assert "stage2_calibration_spec" in configs
    assert REPO_ROOT.name in str(REPO_ROOT)
