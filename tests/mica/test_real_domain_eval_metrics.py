from __future__ import annotations

from code.mica.eval.real_domain_detection import (
    auprc,
    auroc,
    balanced_accuracy,
    binary_classification_metrics,
    expected_calibration_error,
    hard_b_fpr,
    m_recall,
)


def test_binary_classification_metrics_compute_accuracy_precision_and_recall() -> None:
    result = binary_classification_metrics([0, 1, 1, 0], [0.2, 0.8, 0.6, 0.3])

    assert result["accuracy"] == 1.0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_expected_calibration_error_returns_bounded_value() -> None:
    result = expected_calibration_error([0, 1, 1, 0], [0.1, 0.9, 0.6, 0.4], n_bins=4)

    assert 0.0 <= result["ece"] <= 1.0


def test_hard_b_fpr_and_m_recall_are_available() -> None:
    assert hard_b_fpr([0, 0, 0], [0, 1, 0])["hard_b_fpr"] == (1 / 3)
    assert m_recall([1, 1, 0], [1, 0, 0])["m_recall"] == 0.5


def test_auroc_auprc_and_balanced_accuracy_are_available() -> None:
    y_true = [0, 0, 1, 1]
    y_score = [0.1, 0.3, 0.7, 0.9]
    y_pred = [0, 0, 1, 1]

    assert auroc(y_true, y_score)["auroc"] == 1.0
    assert auprc(y_true, y_score)["auprc"] == 1.0
    assert balanced_accuracy(y_true, y_pred)["balanced_accuracy"] == 1.0
