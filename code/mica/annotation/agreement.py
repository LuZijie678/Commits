from __future__ import annotations

from collections import defaultdict
from typing import Any

from code.mica.annotation.real_alignment_schema import annotation_to_gold_maps, normalize_alignment_annotation
from code.mica.eval.attribution_metrics import adjusted_rand_index, normalized_mutual_info, pairwise_f1_from_assignments


def pairwise_agreement_between_annotators(row_a: dict[str, Any], row_b: dict[str, Any]) -> dict[str, Any]:
    left = normalize_alignment_annotation(row_a)
    right = normalize_alignment_annotation(row_b)
    left_map = annotation_to_gold_maps(left)["gold_unit_to_intent"]
    right_map = annotation_to_gold_maps(right)["gold_unit_to_intent"]
    shared_units = sorted(set(left_map) & set(right_map))
    left_labels = [left_map[unit_id] for unit_id in shared_units]
    right_labels = [right_map[unit_id] for unit_id in shared_units]
    return {
        "sample_id": left["sample_id"],
        "annotator_pair": [left["annotator_id"], right["annotator_id"]],
        "count_match": left["intent_count"] == right["intent_count"],
        **pairwise_f1_from_assignments(left_map, right_map),
        **adjusted_rand_index(left_labels, right_labels),
        **normalized_mutual_info(left_labels, right_labels),
    }


def count_agreement(rows_by_sample: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    values = []
    for sample_rows in rows_by_sample.values():
        if len(sample_rows) < 2:
            continue
        baseline = int(normalize_alignment_annotation(sample_rows[0])["intent_count"])
        values.append(all(int(normalize_alignment_annotation(row)["intent_count"]) == baseline for row in sample_rows[1:]))
    return {"count_agreement_rate": (sum(values) / len(values)) if values else 0.0}


def ari_agreement(rows_by_sample: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return _aggregate_pair_metric(rows_by_sample, "ari")


def nmi_agreement(rows_by_sample: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return _aggregate_pair_metric(rows_by_sample, "nmi")


def pairwise_f1_agreement(rows_by_sample: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return _aggregate_pair_metric(rows_by_sample, "pairwise_f1")


def summarize_double_annotation_agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        normalized = normalize_alignment_annotation(row)
        rows_by_sample[normalized["sample_id"]].append(normalized)
    double_rows = {sample_id: sample_rows for sample_id, sample_rows in rows_by_sample.items() if len(sample_rows) >= 2}
    count_summary = count_agreement(double_rows)
    pair_summary = pairwise_f1_agreement(double_rows)
    ari_summary = ari_agreement(double_rows)
    nmi_summary = nmi_agreement(double_rows)
    return {
        "double_annotated_sample_count": len(double_rows),
        **count_summary,
        **pair_summary,
        **ari_summary,
        **nmi_summary,
    }


def _aggregate_pair_metric(rows_by_sample: dict[str, list[dict[str, Any]]], key: str) -> dict[str, Any]:
    values = []
    for sample_rows in rows_by_sample.values():
        if len(sample_rows) < 2:
            continue
        result = pairwise_agreement_between_annotators(sample_rows[0], sample_rows[1])
        values.append(float(result.get(key, 0.0)))
    metric_name = {
        "pairwise_f1": "mean_pairwise_f1",
        "ari": "mean_ari",
        "nmi": "mean_nmi",
    }[key]
    return {metric_name: (sum(values) / len(values)) if values else 0.0}
