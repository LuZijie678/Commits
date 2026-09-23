from __future__ import annotations

import copy
import json
from pathlib import Path

from code.mica.config_loader import load_all_stage_configs, validate_config_family
from code.mica.config_validation import validate_stage2_spec
from code.mica.stages.stage2_real_calibration import build_stage2_training_plan
from code.mica.stages.stage3_real_alignment_calibration import build_stage3_calibration_plan


def test_stage1_and_stage2_configs_expose_core_method_controls() -> None:
    configs = load_all_stage_configs("configs/mica")
    stage1 = configs["stage1_protocol_spec"]
    stage2 = configs["stage2_calibration_spec"]
    relation = configs["evidence_relation_spec"]

    assert "null_slot" in stage1
    assert "dual_cardinality" in stage1
    assert "assignment_schedule" in stage1
    assert "evidence_graph" in stage1
    assert stage2["consistency"]["enabled"] is False
    assert "gold_same_intent" not in json.dumps(relation, ensure_ascii=False)


def test_config_validation_detects_forbidden_lmulti_and_generation_losses(tmp_path) -> None:
    configs = load_all_stage_configs("configs/mica")
    stage2 = copy.deepcopy(configs["stage2_calibration_spec"])
    stage2["loss_weights"]["lambda_multi"] = 0.5
    stage2["loss_weights"]["lambda_gen"] = 1.0

    result = validate_stage2_spec(stage2)

    assert result["valid"] is False
    assert any("L_multi" in error for error in result["errors"])
    assert any("L_gen" in error for error in result["errors"])


def test_stage2_stage3_plan_metadata_surface_core_method_status() -> None:
    stage2 = load_all_stage_configs("configs/mica")["stage2_calibration_spec"]
    stage3 = load_all_stage_configs("configs/mica")["stage3_alignment_calibration_spec"]

    stage2_plan = build_stage2_training_plan(stage2, {"dataset_roles": {"strict_replay": 10}})
    stage3_plan = build_stage3_calibration_plan(stage3, {"row_count": 10})

    assert "core_method_config" in stage2_plan.metadata
    assert stage2_plan.metadata["core_method_config"]["consistency_enabled"] is False
    assert "core_method_config" in stage3_plan.metadata

