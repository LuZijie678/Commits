from __future__ import annotations

import math
from collections import Counter
from typing import Any

import torch

from code.mica.data.collate import collate_mica_samples
from code.mica.data.schema import MicaSample
from code.mica.losses.dice_bce import dice_bce_cost
from code.mica.losses.hungarian_matching import solve_slot_matching
from code.mica.losses.mica_losses import compute_stage1_losses
from code.mica.models.mica_model import MicaModel


def _batched(samples: list[MicaSample], batch_size: int) -> list[list[MicaSample]]:
    return [samples[index : index + batch_size] for index in range(0, len(samples), batch_size)]


def _masked_binary_entropy(probs: torch.Tensor, mask: torch.Tensor) -> float:
    clipped = probs.clamp(1e-6, 1 - 1e-6)
    entropy = -(clipped * clipped.log() + (1 - clipped) * (1 - clipped).log())
    masked = entropy * mask.unsqueeze(0).to(entropy.dtype)
    denom = mask.sum().clamp_min(1).item()
    return float(masked.sum().item() / denom)


def _select_slot_indices(slot_exist_probs: torch.Tensor, requested_k: int) -> list[int]:
    k_select = max(1, min(requested_k, slot_exist_probs.numel()))
    return torch.topk(slot_exist_probs, k=k_select).indices.tolist()


def _labels_from_gold_masks(gold_masks: torch.Tensor, unit_mask: torch.Tensor) -> list[int]:
    labels: list[int] = []
    active_units = int(unit_mask.sum().item())
    for unit_index in range(active_units):
        column = gold_masks[:, unit_index]
        if column.sum().item() <= 0:
            labels.append(0)
        else:
            labels.append(int(column.argmax().item()))
    return labels


def _labels_from_prediction(
    assignment_probs: torch.Tensor,
    slot_exist_probs: torch.Tensor,
    unit_mask: torch.Tensor,
    requested_k: int,
) -> list[int]:
    selected_slots = _select_slot_indices(slot_exist_probs, requested_k)
    active_units = int(unit_mask.sum().item())
    labels: list[int] = []
    for unit_index in range(active_units):
        slot_scores = assignment_probs[selected_slots, unit_index]
        labels.append(int(slot_scores.argmax().item()))
    return labels


def _labels_from_file_path(sample: MicaSample, unit_mask: torch.Tensor) -> list[int]:
    active_units = int(unit_mask.sum().item())
    label_by_path: dict[str, int] = {}
    labels: list[int] = []
    for unit in sample.edit_units[:active_units]:
        if unit.file_path not in label_by_path:
            label_by_path[unit.file_path] = len(label_by_path)
        labels.append(label_by_path[unit.file_path])
    return labels


def all_one_cluster_labels(active_unit_count: int) -> list[int]:
    return [0 for _ in range(active_unit_count)]


def _cluster_masks_from_labels(labels: list[int], *, min_cluster_count: int) -> tuple[torch.Tensor, list[int | None]]:
    unique_labels = sorted(set(labels))
    cluster_labels: list[int | None] = list(unique_labels)
    masks: list[torch.Tensor] = []
    for label in unique_labels:
        masks.append(torch.tensor([1.0 if value == label else 0.0 for value in labels], dtype=torch.float32))
    while len(masks) < min_cluster_count:
        masks.append(torch.zeros(len(labels), dtype=torch.float32))
        cluster_labels.append(None)
    return torch.stack(masks), cluster_labels


def _cluster_direct_metrics(
    *,
    pred_labels: list[int],
    gold_labels: list[int],
    gold_count: int,
) -> dict[str, Any]:
    gold_masks = torch.stack(
        [
            torch.tensor([1.0 if label == gold_index else 0.0 for label in gold_labels], dtype=torch.float32)
            for gold_index in range(gold_count)
        ]
    )
    pred_masks, cluster_labels = _cluster_masks_from_labels(pred_labels, min_cluster_count=gold_count)
    cost_matrix = torch.stack(
        [
            torch.stack(
                [
                    dice_bce_cost(pred_masks[predicted_index], gold_masks[gold_index])
                    for predicted_index in range(pred_masks.size(0))
                ]
            )
            for gold_index in range(gold_count)
        ]
    )
    matching = solve_slot_matching(cost_matrix)
    raw_label_to_gold: dict[int, int] = {}
    for gold_index, predicted_cluster_index in matching.matched_pairs:
        raw_label = cluster_labels[predicted_cluster_index]
        if raw_label is not None:
            raw_label_to_gold[int(raw_label)] = int(gold_index)

    mapped_pred = [raw_label_to_gold.get(int(label), -1) for label in pred_labels]
    unit_correct = sum(int(pred == gold) for pred, gold in zip(mapped_pred, gold_labels))
    unit_accuracy = unit_correct / max(len(gold_labels), 1)

    per_intent_precision: list[float] = []
    per_intent_recall: list[float] = []
    per_intent_f1: list[float] = []
    total_tp = 0
    total_fp = 0
    total_fn = 0
    for gold_index in range(gold_count):
        tp = sum(int(pred == gold_index and gold == gold_index) for pred, gold in zip(mapped_pred, gold_labels))
        fp = sum(int(pred == gold_index and gold != gold_index) for pred, gold in zip(mapped_pred, gold_labels))
        fn = sum(int(pred != gold_index and gold == gold_index) for pred, gold in zip(mapped_pred, gold_labels))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 0.0 if (2 * tp + fp + fn) == 0 else float((2 * tp) / (2 * tp + fp + fn))
        per_intent_precision.append(float(precision))
        per_intent_recall.append(float(recall))
        per_intent_f1.append(float(f1))
        total_tp += tp
        total_fp += fp
        total_fn += fn
    micro_f1 = 0.0 if (2 * total_tp + total_fp + total_fn) == 0 else float((2 * total_tp) / (2 * total_tp + total_fp + total_fn))

    return {
        "mapped_predicted_labels": mapped_pred,
        "unit_accuracy_hungarian": float(unit_accuracy),
        "hunk_accuracy_hungarian": float(unit_accuracy),
        "macro_intent_f1_hungarian": float(sum(per_intent_f1) / max(len(per_intent_f1), 1)),
        "micro_intent_f1_hungarian": float(micro_f1),
        "per_intent_recall_mean": float(sum(per_intent_recall) / max(len(per_intent_recall), 1)),
        "per_intent_precision_mean": float(sum(per_intent_precision) / max(len(per_intent_precision), 1)),
        "hungarian_cost_matrix": cost_matrix,
        "hungarian_matching": matching,
    }


def random_gold_k_baseline_labels(*, active_unit_count: int, gold_count: int, seed: int) -> list[int]:
    if active_unit_count <= 0:
        return []
    requested_k = max(1, min(gold_count, active_unit_count))
    labels = [index % requested_k for index in range(active_unit_count)]
    generator = torch.Generator().manual_seed(seed)
    permutation = torch.randperm(active_unit_count, generator=generator).tolist()
    shuffled = [0 for _ in range(active_unit_count)]
    for source_index, target_index in enumerate(permutation):
        shuffled[target_index] = labels[source_index]
    return shuffled


def _pairwise_f1(pred_labels: list[int], gold_labels: list[int]) -> float:
    pair_count = 0
    tp = 0
    fp = 0
    fn = 0
    for left_index in range(len(gold_labels)):
        for right_index in range(left_index + 1, len(gold_labels)):
            pair_count += 1
            pred_same = pred_labels[left_index] == pred_labels[right_index]
            gold_same = gold_labels[left_index] == gold_labels[right_index]
            if pred_same and gold_same:
                tp += 1
            elif pred_same and not gold_same:
                fp += 1
            elif not pred_same and gold_same:
                fn += 1
    if pair_count == 0:
        return 1.0
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    denom = 2 * tp + fp + fn
    return 0.0 if denom == 0 else float((2 * tp) / denom)


def _trivial_single_cluster_f1(gold_labels: list[int]) -> float:
    return _pairwise_f1([0 for _ in gold_labels], gold_labels)


def _slot_collapse_rate_for_sample(pred_labels: list[int], predicted_count: int, gold_count: int) -> float:
    if len(pred_labels) <= 1:
        return 0.0
    dominant = Counter(pred_labels).most_common(1)[0][1] / len(pred_labels)
    nonempty_slots = len(set(pred_labels))
    unreasonable = predicted_count != gold_count or nonempty_slots < min(gold_count, 2)
    return 1.0 if dominant >= 0.8 and unreasonable else 0.0


def compute_sample_alignment_metrics(
    *,
    sample: MicaSample,
    gold_masks: torch.Tensor,
    unit_mask: torch.Tensor,
    assignment_probs: torch.Tensor,
    slot_exist_probs: torch.Tensor,
    gold_count: int,
    predicted_count: int,
    seed: int,
    random_trials: int = 16,
) -> dict[str, Any]:
    active_units = int(unit_mask.sum().item())
    active_gold_masks = gold_masks[:, :active_units]
    gold_labels = _labels_from_gold_masks(gold_masks, unit_mask)
    oracle_labels = _labels_from_prediction(assignment_probs, slot_exist_probs, unit_mask, gold_count)
    predicted_labels = _labels_from_prediction(
        assignment_probs,
        slot_exist_probs,
        unit_mask,
        max(1, predicted_count),
    )
    file_path_labels = _labels_from_file_path(sample, unit_mask)
    top1_slots = assignment_probs[:, :active_units].argmax(dim=0).tolist() if active_units else []
    slot_mass = assignment_probs[:, :active_units].sum(dim=-1) if active_units else torch.zeros(assignment_probs.size(0))
    if top1_slots:
        top1_slot_counts = Counter(top1_slots)
        primary_slot = int(sorted(top1_slot_counts.items(), key=lambda item: (-item[1], item[0]))[0][0])
    else:
        primary_slot = int(slot_mass.argmax().item()) if active_units else 0
    normalized_slot_mass = slot_mass / slot_mass.sum().clamp_min(1e-6) if active_units else slot_mass
    entropy = 0.0
    if active_units:
        positive_mass = normalized_slot_mass[normalized_slot_mass > 0]
        entropy = float((-(positive_mass * positive_mass.log()).sum()).item())
    effective_slot_count = float(math.exp(entropy)) if active_units else 0.0
    assignment_top1_nonprimary_fraction = (
        sum(int(slot != primary_slot) for slot in top1_slots) / max(len(top1_slots), 1)
        if top1_slots
        else 0.0
    )
    second_slot_assignment_mass = (
        float((slot_mass.sum() - slot_mass.max()).item() / max(float(slot_mass.sum().item()), 1e-6))
        if active_units
        else 0.0
    )
    foreground_slot_usage_count = len(set(top1_slots)) if top1_slots else 0

    model_direct = _cluster_direct_metrics(pred_labels=top1_slots, gold_labels=gold_labels, gold_count=gold_count)
    all_one_direct = _cluster_direct_metrics(
        pred_labels=all_one_cluster_labels(active_units),
        gold_labels=gold_labels,
        gold_count=gold_count,
    )
    file_path_direct = _cluster_direct_metrics(
        pred_labels=file_path_labels,
        gold_labels=gold_labels,
        gold_count=gold_count,
    )
    random_scores = [
        _pairwise_f1(random_gold_k_baseline_labels(active_unit_count=active_units, gold_count=gold_count, seed=seed + offset), gold_labels)
        for offset in range(random_trials)
    ]
    random_direct_scores = [
        _cluster_direct_metrics(
            pred_labels=random_gold_k_baseline_labels(active_unit_count=active_units, gold_count=gold_count, seed=seed + offset),
            gold_labels=gold_labels,
            gold_count=gold_count,
        )
        for offset in range(random_trials)
    ]
    active_cover = active_gold_masks.sum(dim=0) if active_units else torch.zeros(0, dtype=gold_masks.dtype)
    gold_intent_sizes = Counter(gold_labels)
    secondary_gold_intent = None
    if gold_count == 2 and gold_intent_sizes:
        secondary_gold_intent = sorted(gold_intent_sizes.items(), key=lambda item: (item[1], -item[0]))[0][0]
    secondary_indices = [index for index, label in enumerate(gold_labels) if label == secondary_gold_intent] if secondary_gold_intent is not None else []
    second_slot_gold_recall = (
        sum(int(top1_slots[index] != primary_slot) for index in secondary_indices) / max(len(secondary_indices), 1)
        if secondary_indices
        else 0.0
    )
    k2_split_recall = 0.0
    if gold_count == 2 and active_units:
        gold0_slots = {top1_slots[index] for index, label in enumerate(gold_labels) if label == 0}
        gold1_slots = {top1_slots[index] for index, label in enumerate(gold_labels) if label == 1}
        k2_split_recall = 1.0 if any(left != right for left in gold0_slots for right in gold1_slots) else 0.0
    return {
        "gold_labels": gold_labels,
        "oracle_labels": oracle_labels,
        "predicted_labels": predicted_labels,
        "top1_slots": top1_slots,
        "gold_mask_sizes": [int(row.sum().item()) for row in active_gold_masks],
        "gold_mask_nonempty": bool(active_gold_masks.size(0) > 0 and (active_gold_masks.sum(dim=1) > 0).all().item()),
        "gold_mask_mutually_exclusive": bool(((active_gold_masks.sum(dim=0) <= 1.0).all().item()) if active_units else True),
        "gold_mask_covers_active_units": bool(((active_cover > 0).all().item()) if active_units else True),
        "oracle_k_alignment_pairwise_f1": _pairwise_f1(oracle_labels, gold_labels),
        "predicted_k_alignment_pairwise_f1": _pairwise_f1(predicted_labels, gold_labels),
        "alignment_pairwise_f1_all_one_cluster": _trivial_single_cluster_f1(gold_labels),
        "alignment_pairwise_f1_file_path_baseline": _pairwise_f1(file_path_labels, gold_labels),
        "alignment_pairwise_f1_random_gold_k_mean": float(sum(random_scores) / max(len(random_scores), 1)),
        "unit_accuracy_hungarian": model_direct["unit_accuracy_hungarian"],
        "hunk_accuracy_hungarian": model_direct["hunk_accuracy_hungarian"],
        "macro_intent_f1_hungarian": model_direct["macro_intent_f1_hungarian"],
        "micro_intent_f1_hungarian": model_direct["micro_intent_f1_hungarian"],
        "per_intent_recall_mean": model_direct["per_intent_recall_mean"],
        "per_intent_precision_mean": model_direct["per_intent_precision_mean"],
        "k2_split_recall": float(k2_split_recall),
        "second_slot_gold_recall": float(second_slot_gold_recall),
        "second_slot_assignment_mass": float(second_slot_assignment_mass),
        "foreground_slot_usage_count": int(foreground_slot_usage_count),
        "effective_slot_count_mean": float(effective_slot_count),
        "assignment_top1_nonprimary_fraction": float(assignment_top1_nonprimary_fraction),
        "all_one_unit_accuracy": all_one_direct["unit_accuracy_hungarian"],
        "file_path_unit_accuracy": file_path_direct["unit_accuracy_hungarian"],
        "random_gold_k_unit_accuracy_mean": float(
            sum(item["unit_accuracy_hungarian"] for item in random_direct_scores) / max(len(random_direct_scores), 1)
        ),
        "all_one_macro_intent_f1": all_one_direct["macro_intent_f1_hungarian"],
        "file_path_macro_intent_f1": file_path_direct["macro_intent_f1_hungarian"],
        "random_gold_k_macro_intent_f1_mean": float(
            sum(item["macro_intent_f1_hungarian"] for item in random_direct_scores) / max(len(random_direct_scores), 1)
        ),
        "hungarian_cost_matrix": model_direct["hungarian_cost_matrix"],
        "hungarian_matching": model_direct["hungarian_matching"],
    }


def evaluate_model(model: MicaModel, samples: list[MicaSample], *, batch_size: int, device: str) -> dict[str, Any]:
    model.eval()
    total_loss = 0.0
    total_batches = 0
    correct_count = 0
    total_count = 0
    correct_multi = 0
    total_multi = 0
    k1_total = 0
    k1_over_split = 0
    k2_total = 0
    k2_under_split = 0
    slot_collapse_sum = 0.0
    assignment_entropy_sum = 0.0
    oracle_f1_sum = 0.0
    predicted_f1_sum = 0.0
    trivial_f1_sum = 0.0
    file_path_f1_sum = 0.0
    random_gold_k_f1_sum = 0.0
    unit_accuracy_sum = 0.0
    hunk_accuracy_sum = 0.0
    macro_intent_f1_sum = 0.0
    micro_intent_f1_sum = 0.0
    per_intent_recall_sum = 0.0
    per_intent_precision_sum = 0.0
    k2_split_recall_sum = 0.0
    k2_metric_count = 0
    second_slot_gold_recall_sum = 0.0
    second_slot_assignment_mass_sum = 0.0
    foreground_slot_usage_count_sum = 0.0
    effective_slot_count_sum = 0.0
    assignment_top1_nonprimary_fraction_sum = 0.0
    all_one_unit_accuracy_sum = 0.0
    file_path_unit_accuracy_sum = 0.0
    random_gold_k_unit_accuracy_sum = 0.0
    all_one_macro_f1_sum = 0.0
    file_path_macro_f1_sum = 0.0
    random_gold_k_macro_f1_sum = 0.0
    predicted_count_values: list[int] = []
    gold_count_values: list[int] = []
    dev_predictions: list[dict[str, Any]] = []
    assignment_top1_slot_counter: Counter[int] = Counter()

    with torch.no_grad():
        for batch_samples in _batched(samples, batch_size):
            batch = collate_mica_samples(batch_samples)
            tensor_batch = {
                key: value.to(device) if isinstance(value, torch.Tensor) else value
                for key, value in batch.items()
            }
            output = model(tensor_batch)
            losses = compute_stage1_losses(output, tensor_batch)
            total_loss += float(losses["loss_main"].item())
            total_batches += 1

            predicted_counts = output.count_probs.argmax(dim=-1).cpu() + 1
            gold_counts = tensor_batch["gold_counts"].cpu()
            correct_count += int((predicted_counts == gold_counts).sum().item())
            total_count += int(gold_counts.numel())
            correct_multi += int(((predicted_counts > 1) == (gold_counts > 1)).sum().item())
            total_multi += int(gold_counts.numel())

            for sample_offset, sample in enumerate(batch_samples):
                gold_count = int(gold_counts[sample_offset].item())
                predicted_count = int(predicted_counts[sample_offset].item())
                predicted_count_clamped = max(1, predicted_count)
                predicted_count_values.append(predicted_count)
                gold_count_values.append(gold_count)
                if gold_count == 1:
                    k1_total += 1
                    if predicted_count >= 2:
                        k1_over_split += 1
                if gold_count == 2:
                    k2_total += 1
                    if predicted_count <= 1:
                        k2_under_split += 1

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
                    predicted_count=predicted_count_clamped,
                    seed=sample_offset + total_count * 17,
                )
                assignment_top1_slot_counter.update(int(slot_index) for slot_index in sample_metrics["top1_slots"])
                assignment_entropy_sum += _masked_binary_entropy(assignment_probs, unit_mask)
                oracle_f1 = float(sample_metrics["oracle_k_alignment_pairwise_f1"])
                predicted_f1 = float(sample_metrics["predicted_k_alignment_pairwise_f1"])
                trivial_f1 = float(sample_metrics["alignment_pairwise_f1_all_one_cluster"])
                file_path_f1 = float(sample_metrics["alignment_pairwise_f1_file_path_baseline"])
                random_gold_k_f1 = float(sample_metrics["alignment_pairwise_f1_random_gold_k_mean"])
                oracle_f1_sum += oracle_f1
                predicted_f1_sum += predicted_f1
                trivial_f1_sum += trivial_f1
                file_path_f1_sum += file_path_f1
                random_gold_k_f1_sum += random_gold_k_f1
                unit_accuracy_sum += float(sample_metrics["unit_accuracy_hungarian"])
                hunk_accuracy_sum += float(sample_metrics["hunk_accuracy_hungarian"])
                macro_intent_f1_sum += float(sample_metrics["macro_intent_f1_hungarian"])
                micro_intent_f1_sum += float(sample_metrics["micro_intent_f1_hungarian"])
                per_intent_recall_sum += float(sample_metrics["per_intent_recall_mean"])
                per_intent_precision_sum += float(sample_metrics["per_intent_precision_mean"])
                foreground_slot_usage_count_sum += float(sample_metrics["foreground_slot_usage_count"])
                effective_slot_count_sum += float(sample_metrics["effective_slot_count_mean"])
                assignment_top1_nonprimary_fraction_sum += float(sample_metrics["assignment_top1_nonprimary_fraction"])
                all_one_unit_accuracy_sum += float(sample_metrics["all_one_unit_accuracy"])
                file_path_unit_accuracy_sum += float(sample_metrics["file_path_unit_accuracy"])
                random_gold_k_unit_accuracy_sum += float(sample_metrics["random_gold_k_unit_accuracy_mean"])
                all_one_macro_f1_sum += float(sample_metrics["all_one_macro_intent_f1"])
                file_path_macro_f1_sum += float(sample_metrics["file_path_macro_intent_f1"])
                random_gold_k_macro_f1_sum += float(sample_metrics["random_gold_k_macro_intent_f1_mean"])
                if gold_count == 2:
                    k2_metric_count += 1
                    k2_split_recall_sum += float(sample_metrics["k2_split_recall"])
                    second_slot_gold_recall_sum += float(sample_metrics["second_slot_gold_recall"])
                    second_slot_assignment_mass_sum += float(sample_metrics["second_slot_assignment_mass"])
                slot_collapse_sum += _slot_collapse_rate_for_sample(
                    sample_metrics["predicted_labels"],
                    predicted_count,
                    gold_count,
                )

                if len(dev_predictions) < 20:
                    dev_predictions.append(
                        {
                            "sample_id": sample.sample_id,
                            "source_kind": sample.source_kind,
                            "gold_count": gold_count,
                            "predicted_count": predicted_count,
                            "predicted_count_clamped": predicted_count_clamped,
                            "edit_unit_count": len(sample.edit_units),
                            "oracle_k_alignment_pairwise_f1": oracle_f1,
                            "predicted_k_alignment_pairwise_f1": predicted_f1,
                            "alignment_pairwise_f1_all_one_cluster": trivial_f1,
                            "alignment_pairwise_f1_file_path_baseline": file_path_f1,
                            "alignment_pairwise_f1_random_gold_k_mean": random_gold_k_f1,
                            "unit_accuracy_hungarian": float(sample_metrics["unit_accuracy_hungarian"]),
                            "macro_intent_f1_hungarian": float(sample_metrics["macro_intent_f1_hungarian"]),
                            "second_slot_gold_recall": float(sample_metrics["second_slot_gold_recall"]),
                            "k2_split_recall": float(sample_metrics["k2_split_recall"]),
                            "gold_mask_sizes": sample_metrics["gold_mask_sizes"],
                            "gold_mask_nonempty": sample_metrics["gold_mask_nonempty"],
                            "gold_mask_mutually_exclusive": sample_metrics["gold_mask_mutually_exclusive"],
                            "gold_mask_covers_active_units": sample_metrics["gold_mask_covers_active_units"],
                        }
                    )

    sample_count = max(total_count, 1)
    count_baseline = 0.0
    if gold_count_values:
        gold_distribution = Counter(gold_count_values)
        count_baseline = max(gold_distribution.values()) / len(gold_count_values)
    return {
        "dev_loss": total_loss / max(total_batches, 1),
        "count_accuracy": correct_count / sample_count,
        "binary_multi_accuracy": correct_multi / max(total_multi, 1),
        "over_split_rate_on_k1": k1_over_split / max(k1_total, 1),
        "under_split_rate_on_k2": k2_under_split / max(k2_total, 1),
        "slot_collapse_rate": slot_collapse_sum / sample_count,
        "assignment_entropy": assignment_entropy_sum / sample_count,
        "oracle_k_alignment_pairwise_f1": oracle_f1_sum / sample_count,
        "predicted_k_alignment_pairwise_f1": predicted_f1_sum / sample_count,
        "alignment_pairwise_f1_model_oracle_k": oracle_f1_sum / sample_count,
        "alignment_pairwise_f1_model_predicted_k": predicted_f1_sum / sample_count,
        "trivial_pairwise_f1_baseline": trivial_f1_sum / sample_count,
        "alignment_pairwise_f1_all_one_cluster": trivial_f1_sum / sample_count,
        "alignment_pairwise_f1_file_path_baseline": file_path_f1_sum / sample_count,
        "alignment_pairwise_f1_random_gold_k_mean": random_gold_k_f1_sum / sample_count,
        "alignment_gain_over_all_one": (oracle_f1_sum - trivial_f1_sum) / sample_count,
        "alignment_gain_over_file_path": (oracle_f1_sum - file_path_f1_sum) / sample_count,
        "alignment_gain_over_random_gold_k": (oracle_f1_sum - random_gold_k_f1_sum) / sample_count,
        "attribution_gain": (oracle_f1_sum / sample_count) > (trivial_f1_sum / sample_count),
        "unit_accuracy_hungarian": unit_accuracy_sum / sample_count,
        "hunk_accuracy_hungarian": hunk_accuracy_sum / sample_count,
        "macro_intent_f1_hungarian": macro_intent_f1_sum / sample_count,
        "micro_intent_f1_hungarian": micro_intent_f1_sum / sample_count,
        "per_intent_recall_mean": per_intent_recall_sum / sample_count,
        "per_intent_precision_mean": per_intent_precision_sum / sample_count,
        "k2_split_recall": k2_split_recall_sum / max(k2_metric_count, 1),
        "second_slot_gold_recall": second_slot_gold_recall_sum / max(k2_metric_count, 1),
        "second_slot_assignment_mass": second_slot_assignment_mass_sum / max(k2_metric_count, 1),
        "foreground_slot_usage_count": foreground_slot_usage_count_sum / sample_count,
        "effective_slot_count_mean": effective_slot_count_sum / sample_count,
        "assignment_top1_nonprimary_fraction": assignment_top1_nonprimary_fraction_sum / sample_count,
        "all_one_unit_accuracy": all_one_unit_accuracy_sum / sample_count,
        "unit_accuracy_gain_over_all_one": (unit_accuracy_sum - all_one_unit_accuracy_sum) / sample_count,
        "file_path_unit_accuracy": file_path_unit_accuracy_sum / sample_count,
        "random_gold_k_unit_accuracy_mean": random_gold_k_unit_accuracy_sum / sample_count,
        "all_one_macro_intent_f1": all_one_macro_f1_sum / sample_count,
        "macro_intent_f1_gain_over_all_one": (macro_intent_f1_sum - all_one_macro_f1_sum) / sample_count,
        "file_path_macro_intent_f1": file_path_macro_f1_sum / sample_count,
        "random_gold_k_macro_intent_f1_mean": random_gold_k_macro_f1_sum / sample_count,
        "count_majority_baseline": count_baseline,
        "all_same_count_prediction": len(set(predicted_count_values)) <= 1 if predicted_count_values else True,
        "predicted_count_distribution": dict(sorted(Counter(predicted_count_values).items())),
        "assignment_top1_slot_distribution": dict(sorted(assignment_top1_slot_counter.items())),
        "dev_predictions": dev_predictions,
    }


def decide_sanity_status(summary: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    train_first = float(summary["train_loss_first_epoch"])
    train_last = float(summary["train_loss_last_epoch"])
    dev_loss = float(summary["dev_loss"])
    count_accuracy = float(summary["count_accuracy"])
    count_baseline = float(summary["count_majority_baseline"])
    oracle_f1 = float(summary["oracle_k_alignment_pairwise_f1"])
    predicted_f1 = float(summary["predicted_k_alignment_pairwise_f1"])
    all_one_f1 = float(summary["alignment_pairwise_f1_all_one_cluster"])
    random_gold_k_f1 = float(summary["alignment_pairwise_f1_random_gold_k_mean"])
    slot_collapse_rate = float(summary["slot_collapse_rate"])
    over_split_rate = float(summary["over_split_rate_on_k1"])
    train_sample_count = int(summary["train_sample_count"])
    dev_sample_count = int(summary["dev_sample_count"])

    if any(math.isnan(value) or math.isinf(value) for value in [train_first, train_last, dev_loss, predicted_f1, oracle_f1]):
        return "failed", ["loss_or_metric_nan"]
    if summary.get("all_same_count_prediction"):
        return "failed", ["all_samples_predicted_same_count"]
    if predicted_f1 <= 1e-6:
        return "failed", ["predicted_alignment_pairwise_f1_near_zero"]
    if oracle_f1 <= 1e-6:
        return "failed", ["oracle_alignment_pairwise_f1_near_zero"]
    if slot_collapse_rate >= 0.95:
        return "failed", ["slot_collapse_detected"]
    if train_sample_count < 8 or dev_sample_count < 4:
        return "failed", ["insufficient_sanity_samples"]

    if train_last >= train_first:
        notes.append("train_loss_did_not_decrease")
    if count_accuracy <= count_baseline:
        notes.append("count_accuracy_not_above_majority_baseline")
    if oracle_f1 <= all_one_f1 + 0.05:
        notes.append("oracle_alignment_not_above_all_one_baseline_margin")
    if oracle_f1 <= random_gold_k_f1 + 0.05:
        notes.append("oracle_alignment_not_above_random_gold_k_baseline_margin")
    if predicted_f1 <= all_one_f1:
        notes.append("predicted_alignment_not_above_all_one_baseline")
    if slot_collapse_rate > 0.40:
        notes.append("slot_collapse_rate_high")
    if over_split_rate > 0.45:
        notes.append("over_split_rate_on_k1_high")

    passed = (
        train_last < train_first
        and count_accuracy >= 0.60
        and oracle_f1 > all_one_f1 + 0.05
        and oracle_f1 > random_gold_k_f1 + 0.05
        and slot_collapse_rate <= 0.40
        and over_split_rate <= 0.45
    )
    if passed:
        return "passed", []

    if (
        "oracle_alignment_not_above_all_one_baseline_margin" in notes
        or "oracle_alignment_not_above_random_gold_k_baseline_margin" in notes
    ):
        notes.append("attribution_metric_fixed_but_model_not_yet_above_baseline")
    return "inconclusive", notes


__all__ = [
    "compute_sample_alignment_metrics",
    "decide_sanity_status",
    "evaluate_model",
    "random_gold_k_baseline_labels",
]
