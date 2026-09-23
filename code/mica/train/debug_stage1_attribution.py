from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.mica.data.collate import collate_mica_samples
from code.mica.losses.dice_bce import dice_bce_cost
from code.mica.losses.hungarian_matching import solve_slot_matching
from code.mica.runners.export_stage1_predictions import build_backend_snapshot_rows_from_samples
from code.mica.training.backend import MicaModelBackendAdapter
from code.mica.training.trainer_types import TrainBatch
from code.mica.train.eval_stage1_sanity import (
    _masked_binary_entropy,
    compute_sample_alignment_metrics,
)
from code.mica.train.probe_assignment_loss_correctness import run_assignment_loss_correctness_probe
from code.mica.train.train_stage1_sanity import (
    fit_stage1_sanity_model,
    load_config,
    prepare_stage1_sanity_run,
)
from code.mica.io_utils import write_jsonl


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICA Stage 1 Attribution Debug",
        "",
        f"- oracle_predicted_k_exactly_equal: {str(payload['oracle_predicted_k_exactly_equal']).lower()}",
        f"- oracle_predicted_k_label_diff_count: {payload['oracle_predicted_k_label_diff_count']}",
        f"- oracle_predicted_k_f1_diff_count: {payload['oracle_predicted_k_f1_diff_count']}",
        f"- trivial_baseline_definition: {payload['trivial_baseline_definition']}",
        f"- alignment_pairwise_f1_model_oracle_k: {payload['alignment_pairwise_f1_model_oracle_k']:.6f}",
        f"- alignment_pairwise_f1_model_predicted_k: {payload['alignment_pairwise_f1_model_predicted_k']:.6f}",
        f"- alignment_pairwise_f1_all_one_cluster: {payload['alignment_pairwise_f1_all_one_cluster']:.6f}",
        f"- alignment_pairwise_f1_file_path_baseline: {payload['alignment_pairwise_f1_file_path_baseline']:.6f}",
        f"- alignment_pairwise_f1_random_gold_k_mean: {payload['alignment_pairwise_f1_random_gold_k_mean']:.6f}",
        f"- unit_accuracy_hungarian: {payload['unit_accuracy_hungarian']:.6f}",
        f"- macro_intent_f1_hungarian: {payload['macro_intent_f1_hungarian']:.6f}",
        f"- k2_split_recall: {payload['k2_split_recall']:.6f}",
        f"- second_slot_gold_recall: {payload['second_slot_gold_recall']:.6f}",
        f"- second_slot_assignment_mass: {payload['second_slot_assignment_mass']:.6f}",
        f"- effective_slot_count_mean: {payload['effective_slot_count_mean']:.6f}",
        f"- assignment_top1_nonprimary_fraction: {payload['assignment_top1_nonprimary_fraction']:.6f}",
        f"- attribution_gain: {str(payload['attribution_gain']).lower()}",
        f"- padding_excluded_from_metrics: {str(payload['padding_excluded_from_metrics']).lower()}",
        f"- padding_excluded_from_loss: {str(payload['padding_excluded_from_loss']).lower()}",
        f"- k2_avg_edit_unit_count: {payload['k2_avg_edit_unit_count']:.6f}",
        f"- k2_singleton_intent_fraction: {payload['k2_singleton_intent_fraction']:.6f}",
        f"- gradient_norm_assignment_head: {payload['gradient_norm_assignment_head']:.6f}",
        f"- gradient_norm_slot_queries: {payload['gradient_norm_slot_queries']:.6f}",
        f"- gradient_norm_encoder: {payload['gradient_norm_encoder']:.6f}",
        f"- perfect_align_loss: {payload['loss_correctness_probe']['perfect_align_loss']:.6f}",
        f"- all_one_align_loss: {payload['loss_correctness_probe']['all_one_align_loss']:.6f}",
        f"- perfect_beats_all_one: {str(payload['loss_correctness_probe']['perfect_beats_all_one']).lower()}",
        "",
        "## Assignment Top-1 Slot Distribution",
        "",
    ]
    for slot_index, count in payload["assignment_top1_slot_distribution"].items():
        lines.append(f"- slot_{slot_index}: {count}")
    lines.extend(
        [
            "",
            "## Slot Usage Histogram",
            "",
        ]
    )
    for slot_index, count in payload["slot_usage_histogram"].items():
        lines.append(f"- slot_{slot_index}: {count}")
    lines.extend(
        [
            "",
            "## Matched Slot Existence",
            "",
            f"- mean: {payload['matched_slot_existence_mean']:.6f}",
            f"- p50: {payload['matched_slot_existence_p50']:.6f}",
            f"- p90: {payload['matched_slot_existence_p90']:.6f}",
            "",
            "## Unmatched Slot Existence",
            "",
            f"- mean: {payload['unmatched_slot_existence_mean']:.6f}",
            f"- p50: {payload['unmatched_slot_existence_p50']:.6f}",
            f"- p90: {payload['unmatched_slot_existence_p90']:.6f}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_backend_snapshot_rows_from_debug_batch(
    *,
    batch_samples: list[Any],
    tensor_batch: dict[str, Any],
    backend: Any,
    source: str = "mica_stage1_debug_backend_export",
) -> list[dict[str, Any]]:
    return build_backend_snapshot_rows_from_samples(
        batch_samples=batch_samples,
        tensor_batch=tensor_batch,
        backend=backend,
        source=source,
    )


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _cosine_similarity(left: torch.Tensor, right: torch.Tensor) -> float:
    if left.numel() == 0 or right.numel() == 0:
        return 0.0
    return float(F.cosine_similarity(left.unsqueeze(0), right.unsqueeze(0), dim=-1).item())


def _build_debug_train_batch(*, sample: Any, tensor_batch: dict[str, Any]) -> TrainBatch:
    edit_units = [_debug_edit_unit_to_record(unit) for unit in list(getattr(sample, "edit_units", []))]
    return TrainBatch(
        sample_ids=[str(getattr(sample, "sample_id"))],
        source_kind=str(getattr(sample, "source_kind", "debug_sample")),
        edit_units=edit_units,
        metadata={
            "commit_id": str(getattr(sample, "sample_id")),
            "tensor_batch": tensor_batch,
        },
    )


def _debug_edit_unit_to_record(unit: Any) -> dict[str, Any]:
    return {
        "unit_id": str(getattr(unit, "unit_id")),
        "hunk_id": str(getattr(unit, "hunk_id", getattr(unit, "unit_id"))),
        "file_path": str(getattr(unit, "file_path")),
        "file_role": str(getattr(unit, "file_role", "source")),
        "language": getattr(unit, "language", None),
        "patch_text": str(getattr(unit, "patch_text", "")),
        "added_lines": list(getattr(unit, "added_lines", [])),
        "deleted_lines": list(getattr(unit, "deleted_lines", [])),
        "changed_identifiers": list(getattr(unit, "identifiers", [])),
        "metadata": {
            "enclosing_symbol_name": getattr(unit, "enclosing_symbol_name", None),
            "enclosing_symbol_type": getattr(unit, "enclosing_symbol_type", None),
            "enclosing_symbol_signature": getattr(unit, "enclosing_symbol_signature", None),
            "enclosing_symbol_resolution_status": getattr(unit, "enclosing_symbol_resolution_status", None),
        },
    }


def _slice_tensor_batch_for_sample(
    *,
    tensor_batch: dict[str, Any],
    sample_offset: int,
    batch_size: int,
) -> dict[str, Any]:
    sliced: dict[str, Any] = {}
    for key, value in tensor_batch.items():
        if isinstance(value, torch.Tensor) and value.size(0) == batch_size:
            sliced[key] = value[sample_offset : sample_offset + 1]
        else:
            sliced[key] = value
    return sliced


def run_stage1_attribution_debug(
    *,
    config_path: str,
    cli_synthetic_jsonl: str | None = None,
    cli_atomic_csv: str | None = None,
    cli_output_root: str | None = None,
    cli_manifest_json: str | None = None,
    cli_curriculum_level: str | None = None,
    cli_backend_snapshot_jsonl: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    prepared = prepare_stage1_sanity_run(
        config,
        cli_synthetic_jsonl=cli_synthetic_jsonl,
        cli_atomic_csv=cli_atomic_csv,
        cli_output_root=cli_output_root,
        cli_manifest_json=cli_manifest_json,
        cli_curriculum_level=cli_curriculum_level,
    )
    merged = prepared["config"]
    dev_samples = prepared["dev_samples"]
    model, _epoch_train_losses, training_log_rows = fit_stage1_sanity_model(merged, prepared["train_samples"])
    device = str(merged["device"])
    model.eval()
    debug_backend = MicaModelBackendAdapter(model) if cli_backend_snapshot_jsonl else None
    debug_snapshot_rows: list[dict[str, Any]] = []

    oracle_label_diff_count = 0
    oracle_f1_diff_count = 0
    oracle_f1_sum = 0.0
    predicted_f1_sum = 0.0
    all_one_f1_sum = 0.0
    file_path_f1_sum = 0.0
    random_gold_k_f1_sum = 0.0
    assignment_top1_slot_distribution: Counter[int] = Counter()
    slot_usage_histogram: Counter[int] = Counter()
    slot_mass_totals = torch.zeros(int(merged["Kmax"]), dtype=torch.float64)
    slot_mass_sample_count = 0
    slot_pair_cosines: list[float] = []
    entropy_by_k: dict[int, list[float]] = defaultdict(list)
    matched_slot_existences: list[float] = []
    unmatched_slot_existences: list[float] = []
    unit_accuracy_sum = 0.0
    macro_intent_f1_sum = 0.0
    micro_intent_f1_sum = 0.0
    per_intent_recall_sum = 0.0
    per_intent_precision_sum = 0.0
    k2_split_recall_sum = 0.0
    second_slot_gold_recall_sum = 0.0
    second_slot_assignment_mass_sum = 0.0
    foreground_slot_usage_count_sum = 0.0
    effective_slot_count_sum = 0.0
    assignment_top1_nonprimary_fraction_sum = 0.0
    assignment_logits_sum_by_slot = torch.zeros(int(merged["Kmax"]), dtype=torch.float64)
    assignment_logits_sq_sum_by_slot = torch.zeros(int(merged["Kmax"]), dtype=torch.float64)
    assignment_logits_count_by_slot = torch.zeros(int(merged["Kmax"]), dtype=torch.float64)
    assignment_logits_margins: list[float] = []
    k2_edit_unit_counts: list[int] = []
    k2_singleton_count = 0
    k2_sample_count = 0
    gold_mask_size_rows: list[dict[str, Any]] = []
    gold_mask_empty_count = 0
    gold_mask_nonexclusive_count = 0
    gold_mask_uncovered_count = 0
    padding_excluded_from_metrics = True
    padding_excluded_from_loss = True
    example_cost_matrix: list[list[float]] | None = None
    example_matching: list[tuple[int, int]] | None = None

    batch_size = int(merged["batch_size"])
    with torch.no_grad():
        for batch_start in range(0, len(dev_samples), batch_size):
            batch_samples = dev_samples[batch_start : batch_start + batch_size]
            batch = collate_mica_samples(batch_samples)
            tensor_batch = {
                key: value.to(device) if isinstance(value, torch.Tensor) else value
                for key, value in batch.items()
            }
            output = model(tensor_batch)
            if debug_backend is not None:
                debug_snapshot_rows.extend(
                    build_backend_snapshot_rows_from_debug_batch(
                        batch_samples=batch_samples,
                        tensor_batch=tensor_batch,
                        backend=debug_backend,
                    )
                )
            unit_embeddings = model.encoder(
                tensor_batch["text_features"],
                tensor_batch["dense_features"],
            ).cpu()

            for sample_offset, sample in enumerate(batch_samples):
                gold_count = int(tensor_batch["gold_counts"][sample_offset].item())
                predicted_count = int(output.count_probs[sample_offset].argmax(dim=-1).item()) + 1
                unit_mask = tensor_batch["unit_mask"][sample_offset].cpu()
                gold_masks = tensor_batch["gold_assignment_masks"][sample_offset].cpu()
                assignment_probs = output.assignment_probs[sample_offset].cpu()
                slot_exist_probs = output.slot_exist_probs[sample_offset].cpu()
                sample_metrics = compute_sample_alignment_metrics(
                    sample=sample,
                    gold_masks=gold_masks,
                    unit_mask=unit_mask,
                    assignment_probs=assignment_probs,
                    slot_exist_probs=slot_exist_probs,
                    gold_count=gold_count,
                    predicted_count=predicted_count,
                    seed=batch_start + sample_offset,
                )

                if sample_metrics["oracle_labels"] != sample_metrics["predicted_labels"]:
                    oracle_label_diff_count += 1
                if abs(
                    float(sample_metrics["oracle_k_alignment_pairwise_f1"])
                    - float(sample_metrics["predicted_k_alignment_pairwise_f1"])
                ) > 1e-9:
                    oracle_f1_diff_count += 1

                oracle_f1_sum += float(sample_metrics["oracle_k_alignment_pairwise_f1"])
                predicted_f1_sum += float(sample_metrics["predicted_k_alignment_pairwise_f1"])
                all_one_f1_sum += float(sample_metrics["alignment_pairwise_f1_all_one_cluster"])
                file_path_f1_sum += float(sample_metrics["alignment_pairwise_f1_file_path_baseline"])
                random_gold_k_f1_sum += float(sample_metrics["alignment_pairwise_f1_random_gold_k_mean"])
                unit_accuracy_sum += float(sample_metrics["unit_accuracy_hungarian"])
                macro_intent_f1_sum += float(sample_metrics["macro_intent_f1_hungarian"])
                micro_intent_f1_sum += float(sample_metrics["micro_intent_f1_hungarian"])
                per_intent_recall_sum += float(sample_metrics["per_intent_recall_mean"])
                per_intent_precision_sum += float(sample_metrics["per_intent_precision_mean"])
                foreground_slot_usage_count_sum += float(sample_metrics["foreground_slot_usage_count"])
                effective_slot_count_sum += float(sample_metrics["effective_slot_count_mean"])
                assignment_top1_nonprimary_fraction_sum += float(sample_metrics["assignment_top1_nonprimary_fraction"])

                if gold_count == 2:
                    gold_mask_size_rows.append(
                        {
                            "sample_id": sample.sample_id,
                            "gold_count": gold_count,
                            "mask_sizes": sample_metrics["gold_mask_sizes"],
                        }
                    )
                if not sample_metrics["gold_mask_nonempty"]:
                    gold_mask_empty_count += 1
                if not sample_metrics["gold_mask_mutually_exclusive"]:
                    gold_mask_nonexclusive_count += 1
                if not sample_metrics["gold_mask_covers_active_units"]:
                    gold_mask_uncovered_count += 1

                active_units = int(unit_mask.sum().item())
                if len(sample_metrics["gold_labels"]) != active_units:
                    padding_excluded_from_metrics = False

                if active_units < gold_masks.size(-1):
                    active_cost = torch.stack(
                        [
                            torch.stack(
                                [
                                    dice_bce_cost(assignment_probs[pred_index, :active_units], gold_masks[gold_index, :active_units])
                                    for pred_index in range(assignment_probs.size(0))
                                ]
                            )
                            for gold_index in range(gold_count)
                        ]
                    )
                    current_cost = torch.stack(
                        [
                            torch.stack(
                                [
                                    dice_bce_cost(assignment_probs[pred_index, unit_mask], gold_masks[gold_index, unit_mask])
                                    for pred_index in range(assignment_probs.size(0))
                                ]
                            )
                            for gold_index in range(gold_count)
                        ]
                    )
                    if not torch.allclose(active_cost, current_cost, atol=1e-6):
                        padding_excluded_from_loss = False

                top1_slots = assignment_probs[:, :active_units].argmax(dim=0).tolist()
                assignment_top1_slot_distribution.update(int(slot) for slot in top1_slots)
                selected_slots = torch.topk(slot_exist_probs, k=max(1, min(gold_count, slot_exist_probs.numel()))).indices.tolist()
                slot_usage_histogram.update(int(slot) for slot in selected_slots)

                slot_mass = assignment_probs[:, :active_units].sum(dim=-1).to(dtype=torch.float64)
                slot_mass_totals += slot_mass
                slot_mass_sample_count += 1

                for left_index in range(assignment_probs.size(0)):
                    for right_index in range(left_index + 1, assignment_probs.size(0)):
                        slot_pair_cosines.append(
                            _cosine_similarity(
                                assignment_probs[left_index, :active_units],
                                assignment_probs[right_index, :active_units],
                            )
                        )

                entropy_by_k[gold_count].append(_masked_binary_entropy(assignment_probs, unit_mask))

                cost_matrix = torch.stack(
                    [
                        torch.stack(
                            [
                                dice_bce_cost(assignment_probs[predicted_index, unit_mask], gold_masks[gold_index, unit_mask])
                                for predicted_index in range(assignment_probs.size(0))
                            ]
                        )
                        for gold_index in range(gold_count)
                    ]
                )
                matching = solve_slot_matching(cost_matrix)
                for _, predicted_index in matching.matched_pairs:
                    matched_slot_existences.append(float(slot_exist_probs[predicted_index].item()))
                for predicted_index in matching.unmatched_predicted:
                    unmatched_slot_existences.append(float(slot_exist_probs[predicted_index].item()))

                if example_cost_matrix is None and gold_count == 2:
                    example_cost_matrix = [[round(float(value), 6) for value in row] for row in cost_matrix.tolist()]
                    example_matching = list(matching.matched_pairs)

                if gold_count == 2:
                    k2_sample_count += 1
                    k2_edit_unit_counts.append(active_units)
                    if any(size == 1 for size in sample_metrics["gold_mask_sizes"]):
                        k2_singleton_count += 1
                    k2_split_recall_sum += float(sample_metrics["k2_split_recall"])
                    second_slot_gold_recall_sum += float(sample_metrics["second_slot_gold_recall"])
                    second_slot_assignment_mass_sum += float(sample_metrics["second_slot_assignment_mass"])

                assignment_logits = output.assignment_logits[sample_offset].cpu()
                for slot_index in range(assignment_logits.size(0)):
                    active_logits = assignment_logits[slot_index, :active_units]
                    if active_logits.numel() == 0:
                        continue
                    assignment_logits_sum_by_slot[slot_index] += active_logits.sum().item()
                    assignment_logits_sq_sum_by_slot[slot_index] += (active_logits * active_logits).sum().item()
                    assignment_logits_count_by_slot[slot_index] += active_logits.numel()
                if active_units:
                    top2 = torch.topk(assignment_logits[:, :active_units].transpose(0, 1), k=min(2, assignment_logits.size(0)), dim=-1).values
                    if top2.size(-1) >= 2:
                        assignment_logits_margins.extend((top2[:, 0] - top2[:, 1]).tolist())

    sample_count = max(len(dev_samples), 1)
    slot_mass_means = (slot_mass_totals / max(slot_mass_sample_count, 1)).tolist()
    slot_queries = model.slot_decoder.slot_queries.detach().cpu()
    slot_query_norms = [float(vector.norm().item()) for vector in slot_queries]
    slot_query_pairwise_cosine: list[float] = []
    for left_index in range(slot_queries.size(0)):
        for right_index in range(left_index + 1, slot_queries.size(0)):
            slot_query_pairwise_cosine.append(_cosine_similarity(slot_queries[left_index], slot_queries[right_index]))
    assignment_logits_mean_by_slot = []
    assignment_logits_std_by_slot = []
    for slot_index in range(int(merged["Kmax"])):
        count = assignment_logits_count_by_slot[slot_index].item()
        if count <= 0:
            assignment_logits_mean_by_slot.append(0.0)
            assignment_logits_std_by_slot.append(0.0)
            continue
        mean_value = assignment_logits_sum_by_slot[slot_index].item() / count
        variance = max((assignment_logits_sq_sum_by_slot[slot_index].item() / count) - (mean_value ** 2), 0.0)
        assignment_logits_mean_by_slot.append(float(mean_value))
        assignment_logits_std_by_slot.append(float(variance ** 0.5))
    result = {
        "training_run": True,
        "sanity_only": True,
        "oracle_predicted_k_exactly_equal": oracle_label_diff_count == 0 and oracle_f1_diff_count == 0,
        "oracle_predicted_k_label_diff_count": oracle_label_diff_count,
        "oracle_predicted_k_f1_diff_count": oracle_f1_diff_count,
        "trivial_baseline_definition": "all edits assigned to one cluster; pairwise F1 computed against gold intent grouping",
        "alignment_pairwise_f1_model_oracle_k": oracle_f1_sum / sample_count,
        "alignment_pairwise_f1_model_predicted_k": predicted_f1_sum / sample_count,
        "alignment_pairwise_f1_all_one_cluster": all_one_f1_sum / sample_count,
        "alignment_pairwise_f1_file_path_baseline": file_path_f1_sum / sample_count,
        "alignment_pairwise_f1_random_gold_k_mean": random_gold_k_f1_sum / sample_count,
        "unit_accuracy_hungarian": unit_accuracy_sum / sample_count,
        "macro_intent_f1_hungarian": macro_intent_f1_sum / sample_count,
        "micro_intent_f1_hungarian": micro_intent_f1_sum / sample_count,
        "per_intent_recall_mean": per_intent_recall_sum / sample_count,
        "per_intent_precision_mean": per_intent_precision_sum / sample_count,
        "k2_split_recall": k2_split_recall_sum / max(k2_sample_count, 1),
        "second_slot_gold_recall": second_slot_gold_recall_sum / max(k2_sample_count, 1),
        "second_slot_assignment_mass": second_slot_assignment_mass_sum / max(k2_sample_count, 1),
        "foreground_slot_usage_count": foreground_slot_usage_count_sum / sample_count,
        "effective_slot_count_mean": effective_slot_count_sum / sample_count,
        "assignment_top1_nonprimary_fraction": assignment_top1_nonprimary_fraction_sum / sample_count,
        "alignment_gain_over_all_one": (oracle_f1_sum - all_one_f1_sum) / sample_count,
        "alignment_gain_over_file_path": (oracle_f1_sum - file_path_f1_sum) / sample_count,
        "alignment_gain_over_random_gold_k": (oracle_f1_sum - random_gold_k_f1_sum) / sample_count,
        "attribution_gain": (oracle_f1_sum / sample_count) > (all_one_f1_sum / sample_count),
        "gold_mask_sizes_k2": gold_mask_size_rows,
        "k2_dev_sample_count": k2_sample_count,
        "gold_mask_empty_count": gold_mask_empty_count,
        "gold_mask_nonexclusive_count": gold_mask_nonexclusive_count,
        "gold_mask_uncovered_count": gold_mask_uncovered_count,
        "padding_excluded_from_metrics": padding_excluded_from_metrics,
        "padding_excluded_from_loss": padding_excluded_from_loss,
        "k2_avg_edit_unit_count": float(sum(k2_edit_unit_counts) / max(len(k2_edit_unit_counts), 1)),
        "k2_singleton_intent_fraction": k2_singleton_count / max(k2_sample_count, 1),
        "assignment_top1_slot_distribution": dict(sorted(assignment_top1_slot_distribution.items())),
        "average_assignment_mass_per_slot": [float(value) for value in slot_mass_means],
        "slot_usage_histogram": dict(sorted(slot_usage_histogram.items())),
        "slot_pair_cosine_similarity_mean": float(sum(slot_pair_cosines) / max(len(slot_pair_cosines), 1)),
        "slot_query_norms": slot_query_norms,
        "slot_query_pairwise_cosine": slot_query_pairwise_cosine,
        "assignment_logits_mean_by_slot": assignment_logits_mean_by_slot,
        "assignment_logits_std_by_slot": assignment_logits_std_by_slot,
        "assignment_logits_margin_top1_top2": float(sum(assignment_logits_margins) / max(len(assignment_logits_margins), 1)),
        "gradient_norm_assignment_head": float(training_log_rows[-1]["assignment_head_grad_norm"]) if training_log_rows else 0.0,
        "gradient_norm_slot_queries": float(training_log_rows[-1]["slot_query_grad_norm"]) if training_log_rows else 0.0,
        "gradient_norm_encoder": float(training_log_rows[-1]["encoder_grad_norm"]) if training_log_rows else 0.0,
        "training_gradients_by_epoch": training_log_rows,
        "loss_correctness_probe": run_assignment_loss_correctness_probe(),
        "assignment_entropy_by_k": {str(key): float(sum(values) / max(len(values), 1)) for key, values in sorted(entropy_by_k.items())},
        "matched_slot_existence_mean": float(sum(matched_slot_existences) / max(len(matched_slot_existences), 1)),
        "matched_slot_existence_p50": _quantile(matched_slot_existences, 0.5),
        "matched_slot_existence_p90": _quantile(matched_slot_existences, 0.9),
        "unmatched_slot_existence_mean": float(sum(unmatched_slot_existences) / max(len(unmatched_slot_existences), 1)),
        "unmatched_slot_existence_p50": _quantile(unmatched_slot_existences, 0.5),
        "unmatched_slot_existence_p90": _quantile(unmatched_slot_existences, 0.9),
        "hungarian_cost_matrix_example": example_cost_matrix,
        "hungarian_matching_example": example_matching,
    }
    reports_root = ROOT / "reports"
    _write_json(reports_root / "mica_stage1_attribution_debug.json", result)
    _write_markdown(reports_root / "mica_stage1_attribution_debug.md", result)
    if cli_backend_snapshot_jsonl:
        write_jsonl(cli_backend_snapshot_jsonl, debug_snapshot_rows)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MICA Stage 1 attribution debug diagnostics.")
    parser.add_argument("--config", default="code/mica/configs/mica_stage1_sanity.yaml")
    parser.add_argument("--synthetic-jsonl")
    parser.add_argument("--atomic-csv")
    parser.add_argument("--output-root")
    parser.add_argument("--backend-snapshot-jsonl")
    parser.add_argument("--manifest-json")
    parser.add_argument("--curriculum-level", choices=["easy", "medium", "hard"])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run_stage1_attribution_debug(
        config_path=args.config,
        cli_synthetic_jsonl=args.synthetic_jsonl,
        cli_atomic_csv=args.atomic_csv,
        cli_output_root=args.output_root,
        cli_backend_snapshot_jsonl=args.backend_snapshot_jsonl,
        cli_manifest_json=args.manifest_json,
        cli_curriculum_level=args.curriculum_level,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
