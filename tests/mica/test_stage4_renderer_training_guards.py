from __future__ import annotations

import json
from pathlib import Path

import pytest

from code.mica.io_utils import read_json, write_jsonl
from code.mica.runners.run_stage4_renderer_training import run_stage4_renderer_training


def _write_spec(path: Path, *, approved: bool = False, attribution_frozen: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "stage": "stage4_evidence_locked_renderer",
                "advisor_stage4_approved": approved,
                "advisor_stage4_trainable_renderer_approved": approved,
                "default_mode": "dry_run",
                "stage4_scope": "deterministic_evidence_locked_renderer",
                "trainable_renderer_main_result": False,
                "trainable_renderer_allowed_as_future_or_ablation": True,
                "attribution_frozen_required": attribution_frozen,
                "renderer_updates_attribution": False,
                "renderer_reads_only_plan_and_assigned_evidence": True,
                "raw_full_diff_forbidden_as_ungrounded_context": True,
                "retrieval_enabled": False,
                "verifier_enabled": False,
                "llm_api_enabled": False,
                "lambda_copy": 0.1,
            }
        ),
        encoding="utf-8",
    )


def _rows(include_raw_diff: bool = False) -> list[dict]:
    row = {
        "sample_id": "r1",
        "structured_intent_plan": {
            "sample_id": "r1",
            "intent_count": 1,
            "intents": [
                {
                    "intent_id": "I1",
                    "slot_id": "slot_1",
                    "slot_confidence": 0.9,
                    "subject": "update auth logic",
                    "evidence_units": [
                        {
                            "unit_id": "u1",
                            "file_path": "src/auth.py",
                            "changed_identifiers": ["auth"],
                            "file_role": "source",
                        }
                    ],
                }
            ],
        },
        "assigned_evidence": [{"file_path": "src/auth.py", "changed_identifiers": ["auth"]}],
        "target_message": "update auth logic",
        "source_kind": "synthetic",
    }
    if include_raw_diff:
        row["raw_full_diff"] = "forbidden"
    return [row]


def test_stage4_runner_rejects_train_without_advisor_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    dataset = tmp_path / "dataset.jsonl"
    _write_spec(spec, approved=False)
    write_jsonl(dataset, _rows())

    with pytest.raises(ValueError, match="advisor_stage4_approved=true"):
        run_stage4_renderer_training(
            stage4_spec_path=spec,
            renderer_dataset_jsonl=dataset,
            output_root=tmp_path / "out",
            train=True,
        )


def test_stage4_runner_requires_explicit_train_ablation_even_with_approval(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    dataset = tmp_path / "dataset.jsonl"
    _write_spec(spec, approved=True)
    write_jsonl(dataset, _rows())

    with pytest.raises(ValueError, match="train-ablation"):
        run_stage4_renderer_training(
            stage4_spec_path=spec,
            renderer_dataset_jsonl=dataset,
            output_root=tmp_path / "out_scope",
            train=True,
        )


def test_stage4_runner_requires_attribution_frozen(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    dataset = tmp_path / "dataset.jsonl"
    _write_spec(spec, attribution_frozen=False)
    write_jsonl(dataset, _rows())

    with pytest.raises(ValueError, match="attribution_frozen=true"):
        run_stage4_renderer_training(
            stage4_spec_path=spec,
            renderer_dataset_jsonl=dataset,
            output_root=tmp_path / "out",
            dry_run=True,
        )


def test_stage4_runner_forbids_raw_full_diff_and_stays_dry_run(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    forbidden = tmp_path / "dataset_forbidden.jsonl"
    allowed = tmp_path / "dataset_ok.jsonl"
    _write_spec(spec)
    write_jsonl(forbidden, _rows(include_raw_diff=True))
    write_jsonl(allowed, _rows())

    with pytest.raises(ValueError, match="raw full diff"):
        run_stage4_renderer_training(
            stage4_spec_path=spec,
            renderer_dataset_jsonl=forbidden,
            output_root=tmp_path / "out_fail",
            dry_run=True,
        )

    result = run_stage4_renderer_training(
        stage4_spec_path=spec,
        renderer_dataset_jsonl=allowed,
        output_root=tmp_path / "out_ok",
        dry_run=True,
    )
    saved = read_json(tmp_path / "out_ok" / "stage4_renderer_training_manifest.json")
    outputs = read_json(tmp_path / "out_ok" / "stage4_renderer_outputs.json")
    output_summary = read_json(tmp_path / "out_ok" / "stage4_renderer_output_summary.json")
    surface_probe = read_json(tmp_path / "out_ok" / "stage4_renderer_surface_probe.json")

    assert result["training_executed"] is False
    assert saved["attribution_updated"] is False
    assert saved["llm_api_enabled"] is False
    assert saved["metadata"]["experiment_manifest"]["runner_name"] == "run_stage4_renderer_training"
    assert saved["metadata"]["experiment_manifest"]["stage"] == "stage4"
    assert outputs["rows"][0]["subject"]
    assert outputs["rows"][0]["subject"] != "update auth logic"
    assert output_summary["messages_rendered"] == 1
    assert surface_probe["proxy_only"] is True


def test_stage4_runner_train_ablation_executes_and_writes_checkpoint(tmp_path) -> None:
    spec = tmp_path / "spec.json"
    dataset = tmp_path / "dataset.jsonl"
    _write_spec(spec, approved=True)
    write_jsonl(dataset, _rows())

    result = run_stage4_renderer_training(
        stage4_spec_path=spec,
        renderer_dataset_jsonl=dataset,
        output_root=tmp_path / "out_train",
        train=True,
        train_ablation=True,
    )

    manifest = read_json(tmp_path / "out_train" / "stage4_renderer_training_manifest.json")
    checkpoint = read_json(tmp_path / "out_train" / "stage4_renderer_reranker_checkpoint.json")
    metrics = read_json(tmp_path / "out_train" / "stage4_renderer_training_metrics.json")

    assert result["training_executed"] is True
    assert manifest["training_executed"] is True
    assert manifest["attribution_updated"] is False
    assert checkpoint["model_type"] == "candidate_reranker"
    assert "train_loss" in metrics
