from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.mica.experiment.manifest_versioning import build_runner_experiment_manifest
from code.mica.data.renderer_dataset import build_renderer_training_samples, summarize_renderer_dataset, validate_renderer_dataset_rows
from code.mica.config_validation import validate_stage4_spec
from code.mica.io_utils import read_json, read_jsonl, write_json
from code.mica.losses.renderer_losses import entity_copy_loss, renderer_surface_distance
from code.mica.renderers.deterministic import DeterministicRenderer, summarize_rendered_messages
from code.mica.renderers.trainable_reranker import train_candidate_reranker
from code.mica.run_manifest import assert_no_forbidden_training_flags, assert_renderer_does_not_update_attribution, build_run_manifest
from code.mica.schemas import StructuredIntentPlan
from code.mica.stages.stage4_renderer_training import prepare_stage4_renderer_training


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 4 deterministic evidence-locked renderer runner.")
    parser.add_argument("--stage4-spec", required=True)
    parser.add_argument("--renderer-dataset-jsonl", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--train-ablation", action="store_true")
    return parser


def run_stage4_renderer_training(
    *,
    stage4_spec_path: str | Path,
    renderer_dataset_jsonl: str | Path,
    output_root: str | Path,
    dry_run: bool = False,
    train: bool = False,
    train_ablation: bool = False,
) -> dict[str, Any]:
    if not dry_run and not train:
        raise ValueError("Stage 4 renderer runner requires explicit --dry-run or guarded --train.")

    spec = read_json(stage4_spec_path)
    spec_validation = validate_stage4_spec(spec)
    if spec_validation["errors"]:
        raise ValueError("; ".join(spec_validation["errors"]))
    if train and not bool(spec.get("advisor_stage4_approved", False)):
        raise ValueError("Stage 4 training requires advisor_stage4_approved=true in the stage4 spec.")
    if train and not bool(spec.get("advisor_stage4_trainable_renderer_approved", False)):
        raise ValueError("Stage 4 trainable renderer ablation requires advisor_stage4_trainable_renderer_approved=true in the stage4 spec.")
    if train and not train_ablation:
        raise ValueError("Stage 4 default scope is deterministic rendering; trainable renderer requires explicit --train-ablation.")
    assert_renderer_does_not_update_attribution(spec)
    experiment_manifest = build_runner_experiment_manifest(
        runner_name="run_stage4_renderer_training",
        config_paths=[str(stage4_spec_path)],
        asset_registry_path=None,
        seed=int(spec.get("seed", 0) or 0),
        mode="train" if train else "dry_run",
        advisor_approval=bool(spec.get("advisor_stage4_approved", False)),
    )

    rows = read_jsonl(renderer_dataset_jsonl)
    if bool(spec.get("raw_full_diff_forbidden_as_ungrounded_context", True)) and any(
        row.get("raw_full_diff") not in {None, ""} for row in rows
    ):
        raise ValueError("Stage 4 renderer dry-run forbids raw full diff as ungrounded context.")

    stage_summary = prepare_stage4_renderer_training(spec, rows)
    samples = build_renderer_training_samples(rows)
    copy_probe = entity_copy_loss(samples[0]["target_message"], samples[0]["evidence_terms"], lambda_copy=float(spec.get("lambda_copy", 0.1))) if samples else {"loss_total": 0.0}
    if train:
        checkpoint_payload, rendered_messages, training_metrics = train_candidate_reranker(rows=rows, spec=spec)
        renderer_summary = summarize_rendered_messages(rendered_messages)
        surface_probe = (
            renderer_surface_distance(rendered_messages[0].subject, samples[0]["target_message"])
            if rendered_messages
            else {"surface_distance": 0.0, "loss_total": 0.0, "proxy_only": True, "training_executed": True}
        )
    else:
        renderer = DeterministicRenderer()
        rendered_messages = [renderer.render(StructuredIntentPlan.from_dict(sample["structured_intent_plan"])) for sample in samples]
        renderer_summary = summarize_rendered_messages(rendered_messages)
        surface_probe = (
            renderer_surface_distance(rendered_messages[0].subject, samples[0]["target_message"])
            if rendered_messages
            else {"surface_distance": 0.0, "loss_total": 0.0, "proxy_only": True, "training_executed": False}
        )
        checkpoint_payload = None
        training_metrics = None
    manifest = build_run_manifest(
        stage="stage4_evidence_locked_renderer",
        mode="dry_run" if dry_run else "train",
        output_root=str(output_root),
        flags={
            "dry_run": bool(dry_run),
            "training_executed": bool(train),
            "advisor_approval_required": True,
            "attribution_updated": False,
            "stage4_training_enabled": bool(train),
            "stage4_scope": spec.get("stage4_scope", "unknown"),
            "trainable_renderer_main_result": bool(spec.get("trainable_renderer_main_result", False)),
            "llm_api_enabled": bool(spec.get("llm_api_enabled", False)),
            "retrieval_enabled": bool(spec.get("retrieval_enabled", False)),
            "verifier_enabled": bool(spec.get("verifier_enabled", False)),
            "metadata": {"spec_validation": spec_validation, "experiment_manifest": experiment_manifest},
        },
        inputs={
            "stage4_spec": stage4_spec_path,
            "renderer_dataset_jsonl": renderer_dataset_jsonl,
        },
    )
    assert_no_forbidden_training_flags(manifest)
    output_root_path = Path(output_root)
    write_json(output_root_path / "stage4_renderer_training_manifest.json", manifest)
    write_json(output_root_path / "stage4_renderer_dataset_validation.json", validate_renderer_dataset_rows(rows))
    write_json(output_root_path / "stage4_renderer_dataset_summary.json", summarize_renderer_dataset(rows))
    write_json(output_root_path / "stage4_renderer_stage_summary.json", stage_summary)
    write_json(output_root_path / "stage4_renderer_surface_probe.json", surface_probe)
    write_json(output_root_path / "stage4_renderer_copy_probe.json", copy_probe)
    write_json(output_root_path / "stage4_renderer_outputs.json", {"rows": [row.to_dict() for row in rendered_messages]})
    write_json(output_root_path / "stage4_renderer_output_summary.json", renderer_summary)
    if checkpoint_payload is not None:
        write_json(output_root_path / "stage4_renderer_reranker_checkpoint.json", checkpoint_payload)
    if training_metrics is not None:
        write_json(output_root_path / "stage4_renderer_training_metrics.json", training_metrics)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_stage4_renderer_training(
        stage4_spec_path=args.stage4_spec,
        renderer_dataset_jsonl=args.renderer_dataset_jsonl,
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        train=bool(args.train),
        train_ablation=bool(args.train_ablation),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
