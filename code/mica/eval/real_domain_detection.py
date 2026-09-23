from __future__ import annotations

from typing import Iterable


def auroc(y_true: Iterable[int], y_score: Iterable[float]) -> dict[str, float]:
    gold = [int(value) for value in y_true]
    scores = [float(value) for value in y_score]
    positives = [score for truth, score in zip(gold, scores) if truth == 1]
    negatives = [score for truth, score in zip(gold, scores) if truth == 0]
    if not positives or not negatives:
        return {"auroc": 0.0}
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return {"auroc": wins / (len(positives) * len(negatives))}


def auprc(y_true: Iterable[int], y_score: Iterable[float]) -> dict[str, float]:
    pairs = sorted(((float(score), int(truth)) for truth, score in zip(y_true, y_score)), reverse=True)
    positives = sum(truth for _, truth in pairs)
    if not pairs or positives == 0:
        return {"auprc": 0.0}
    tp = fp = 0
    previous_recall = 0.0
    area = 0.0
    for score, truth in pairs:
        if truth == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / positives
        area += precision * max(recall - previous_recall, 0.0)
        previous_recall = recall
    return {"auprc": area}


def balanced_accuracy(y_true: Iterable[int], y_pred: Iterable[float | int]) -> dict[str, float]:
    gold = [int(value) for value in y_true]
    pred = [1 if float(value) >= 0.5 else 0 for value in y_pred]
    positives = [(truth, guess) for truth, guess in zip(gold, pred) if truth == 1]
    negatives = [(truth, guess) for truth, guess in zip(gold, pred) if truth == 0]
    tpr = (sum(1 for _, guess in positives if guess == 1) / len(positives)) if positives else 0.0
    tnr = (sum(1 for _, guess in negatives if guess == 0) / len(negatives)) if negatives else 0.0
    return {"balanced_accuracy": (tpr + tnr) / 2.0}


def binary_classification_metrics(y_true: Iterable[int], y_score_or_pred: Iterable[float | int]) -> dict[str, float]:
    gold = [int(value) for value in y_true]
    scores = [float(value) for value in y_score_or_pred]
    preds = [1 if value >= 0.5 else 0 for value in scores]
    if not gold:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = sum(1 for truth, pred in zip(gold, preds) if truth == 1 and pred == 1)
    tn = sum(1 for truth, pred in zip(gold, preds) if truth == 0 and pred == 0)
    fp = sum(1 for truth, pred in zip(gold, preds) if truth == 0 and pred == 1)
    fn = sum(1 for truth, pred in zip(gold, preds) if truth == 1 and pred == 0)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(gold)
    return {"accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1}


def expected_calibration_error(y_true: Iterable[int], y_prob: Iterable[float], n_bins: int = 10) -> dict[str, float]:
    gold = [int(value) for value in y_true]
    probs = [float(value) for value in y_prob]
    if not gold:
        return {"ece": 0.0, "n_bins": float(n_bins)}
    bin_stats = []
    for bin_index in range(max(n_bins, 1)):
        lower = bin_index / n_bins
        upper = (bin_index + 1) / n_bins
        indices = [i for i, prob in enumerate(probs) if lower <= prob <= upper or (bin_index == n_bins - 1 and prob == 1.0)]
        if not indices:
            continue
        avg_prob = sum(probs[i] for i in indices) / len(indices)
        avg_acc = sum(gold[i] for i in indices) / len(indices)
        bin_stats.append((len(indices) / len(gold)) * abs(avg_acc - avg_prob))
    return {"ece": sum(bin_stats), "n_bins": float(n_bins)}


def hard_b_fpr(hard_b_labels: Iterable[int], preds: Iterable[float | int]) -> dict[str, float]:
    gold = [int(value) for value in hard_b_labels]
    pred_labels = [1 if float(value) >= 0.5 else 0 for value in preds]
    negatives = [pred for truth, pred in zip(gold, pred_labels) if truth == 0]
    fpr = (sum(negatives) / len(negatives)) if negatives else 0.0
    return {"hard_b_fpr": fpr}


def m_recall(m_labels: Iterable[int], preds: Iterable[float | int]) -> dict[str, float]:
    gold = [int(value) for value in m_labels]
    pred_labels = [1 if float(value) >= 0.5 else 0 for value in preds]
    positives = [(truth, pred) for truth, pred in zip(gold, pred_labels) if truth == 1]
    recalled = sum(1 for _, pred in positives if pred == 1)
    recall = (recalled / len(positives)) if positives else 0.0
    return {"m_recall": recall}


def coverage(covered: Iterable[bool | int]) -> dict[str, float]:
    decisions = [bool(value) for value in covered]
    if not decisions:
        return {"coverage": 0.0}
    return {"coverage": sum(1 for value in decisions if value) / len(decisions)}


def risk_at_coverage(covered: Iterable[bool | int], risks: Iterable[float]) -> dict[str, float]:
    pairs = [(bool(is_covered), float(risk)) for is_covered, risk in zip(covered, risks)]
    selected = [risk for is_covered, risk in pairs if is_covered]
    if not selected:
        return {"risk_at_coverage": 0.0}
    return {"risk_at_coverage": sum(selected) / len(selected)}


def aurc(in_scope: Iterable[int], risk_scores: Iterable[float]) -> dict[str, float]:
    labels = [int(value) for value in in_scope]
    risks = [float(value) for value in risk_scores]
    if not labels:
        return {"aurc": 0.0}
    pairs = sorted(zip(risks, labels), key=lambda item: item[0])
    retained_errors = 0
    area = 0.0
    for index, (_, label) in enumerate(pairs, start=1):
        if label == 0:
            retained_errors += 1
        area += retained_errors / index
    return {"aurc": area / len(pairs)}


def abstention_precision(abstained: Iterable[bool | int], in_scope: Iterable[int]) -> dict[str, float]:
    pairs = [(bool(rejected), int(label)) for rejected, label in zip(abstained, in_scope)]
    abstentions = [label for rejected, label in pairs if rejected]
    if not abstentions:
        return {"abstention_precision": 0.0}
    correct_rejects = sum(1 for label in abstentions if label == 0)
    return {"abstention_precision": correct_rejects / len(abstentions)}


def false_abstention_on_in_scope(abstained: Iterable[bool | int], in_scope: Iterable[int]) -> dict[str, float]:
    pairs = [(bool(rejected), int(label)) for rejected, label in zip(abstained, in_scope)]
    positives = [rejected for rejected, label in pairs if label == 1]
    if not positives:
        return {"false_abstention_on_in_scope": 0.0}
    return {"false_abstention_on_in_scope": sum(1 for rejected in positives if rejected) / len(positives)}


def missed_overflow_rate(abstained: Iterable[bool | int], in_scope: Iterable[int]) -> dict[str, float]:
    pairs = [(bool(rejected), int(label)) for rejected, label in zip(abstained, in_scope)]
    overflow = [rejected for rejected, label in pairs if label == 0]
    if not overflow:
        return {"missed_overflow_rate": 0.0}
    return {"missed_overflow_rate": sum(1 for rejected in overflow if not rejected) / len(overflow)}


def forced_decomposition_error(covered: Iterable[bool | int], in_scope: Iterable[int]) -> dict[str, float]:
    pairs = [(bool(is_covered), int(label)) for is_covered, label in zip(covered, in_scope)]
    overflow = [is_covered for is_covered, label in pairs if label == 0]
    if not overflow:
        return {"forced_decomposition_error": 0.0}
    return {"forced_decomposition_error": sum(1 for is_covered in overflow if is_covered) / len(overflow)}


def selective_metrics(
    *,
    in_scope: Iterable[int],
    risk_scores: Iterable[float],
    covered: Iterable[bool | int],
    abstained: Iterable[bool | int],
) -> dict[str, float]:
    labels = [int(value) for value in in_scope]
    risks = [float(value) for value in risk_scores]
    covered_flags = [bool(value) for value in covered]
    abstained_flags = [bool(value) for value in abstained]
    return {
        **coverage(covered_flags),
        **risk_at_coverage(covered_flags, risks),
        **aurc(labels, risks),
        **abstention_precision(abstained_flags, labels),
        **false_abstention_on_in_scope(abstained_flags, labels),
        **missed_overflow_rate(abstained_flags, labels),
        **forced_decomposition_error(covered_flags, labels),
    }
