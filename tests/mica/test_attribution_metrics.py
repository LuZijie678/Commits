from __future__ import annotations

from code.mica.eval.attribution_metrics import (
    adjusted_rand_index,
    aggregate_attribution_metrics,
    bcubed_f1,
    build_primary_alignment_maps,
    count_metrics,
    diagnostic_histogram,
    hunk_micro_f1,
    normalized_mutual_info,
    over_under_split_metrics,
    pairwise_f1_from_assignments,
    slot_collapse_metrics,
    unit_accuracy_hungarian,
)


def test_pairwise_f1_is_perfect_for_matching_assignments() -> None:
    gold = {"u1": "i1", "u2": "i1", "u3": "i2"}
    pred = {"u1": "s1", "u2": "s1", "u3": "s2"}

    result = pairwise_f1_from_assignments(gold, pred)
    assert result["pairwise_f1"] == 1.0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_pairwise_f1_has_reasonable_value_for_all_one() -> None:
    gold = {"u1": "i1", "u2": "i1", "u3": "i2"}
    pred = {"u1": "s1", "u2": "s1", "u3": "s1"}

    result = pairwise_f1_from_assignments(gold, pred)
    assert result["pairwise_f1"] == 0.5
    assert result["precision"] == 1.0 / 3.0
    assert result["recall"] == 1.0


def test_primary_alignment_maps_exclude_ambiguous_units_from_metric_denominators() -> None:
    row = {
        "gold_unit_to_intent": {"u1": "i1", "u2": "i1", "u3": "i2", "u4": "i3"},
        "pred_unit_to_slot": {"u1": "s1", "u2": "s1", "u3": "s2", "u4": "s3"},
        "oracle_unit_to_slot": {"u1": "o1", "u2": "o1", "u3": "o2", "u4": "o3"},
        "gold_hunk_to_intent": {"h1": "i1", "h2": "i2"},
        "pred_hunk_to_slot": {"h1": "s1", "h2": "s2"},
        "uncertain_units": ["u3"],
        "shared_support_units": ["u4"],
        "mixed_units": ["h2"],
    }

    maps = build_primary_alignment_maps(row)

    assert maps["gold_unit_to_intent"] == {"u1": "i1", "u2": "i1"}
    assert maps["pred_unit_to_slot"] == {"u1": "s1", "u2": "s1"}
    assert maps["gold_hunk_to_intent"] == {"h1": "i1"}
    assert maps["excluded_alignment_unit_count"] == 3
    assert maps["alignment_mask_protocol"] == "foreground_only_excludes_uncertain_shared_support_mixed"


def test_unit_accuracy_hungarian_is_invariant_to_slot_permutation() -> None:
    gold = {"u1": "i1", "u2": "i1", "u3": "i2"}
    pred = {"u1": "s2", "u2": "s2", "u3": "s1"}

    result = unit_accuracy_hungarian(gold, pred)
    assert result["unit_accuracy"] == 1.0


def test_count_metrics_and_over_under_split_metrics() -> None:
    count_result = count_metrics([1, 2, 2], [1, 1, 3])
    split_result = over_under_split_metrics([1, 2, 2], [1, 1, 3])

    assert count_result["count_accuracy"] == 1.0 / 3.0
    assert count_result["count_mae"] == 2.0 / 3.0
    assert split_result["under_split_rate_on_k2"] == 0.5
    assert split_result["over_split_rate_on_k1"] == 0.0


def test_slot_collapse_metrics_and_histogram() -> None:
    rows = [
        {"sample_id": "s1", "predicted_count": 2, "unit_to_slot": {"u1": "s1", "u2": "s1", "u3": "s1", "u4": "s2"}},
        {"sample_id": "s2", "predicted_count": 2, "unit_to_slot": {"u1": "s1", "u2": "s1", "u3": "s1", "u4": "s1"}},
    ]
    metrics = slot_collapse_metrics(rows)
    histogram = diagnostic_histogram([{"diagnostics": [{"code": "a"}, {"code": "a"}, {"code": "b"}]}])

    assert metrics["slot_collapse_count"] == 1
    assert metrics["slot_collapse_rate"] == 0.5
    assert histogram["a"] == 2
    assert histogram["b"] == 1


def test_empty_input_returns_diagnostics() -> None:
    result = pairwise_f1_from_assignments({}, {})
    assert result["degraded"] is True
    assert "insufficient_unit_pairs" in result["diagnostics"]


def test_clustering_metrics_are_perfect_for_matching_partition() -> None:
    gold = ["i1", "i1", "i2", "i2"]
    pred = ["s2", "s2", "s1", "s1"]

    ari = adjusted_rand_index(gold, pred)
    nmi = normalized_mutual_info(gold, pred)
    bcubed = bcubed_f1(gold, pred)

    assert ari["ari"] == 1.0
    assert nmi["nmi"] == 1.0
    assert bcubed["bcubed_f1"] == 1.0


def test_clustering_metrics_handle_all_one_and_single_unit_cases() -> None:
    all_one = bcubed_f1(["i1", "i1", "i2"], ["s1", "s1", "s1"])
    single = adjusted_rand_index(["i1"], ["s1"])

    assert 0.0 <= all_one["bcubed_f1"] <= 1.0
    assert single["degraded"] is True
    assert "insufficient_items" in single["diagnostics"]


def test_hunk_micro_f1_supports_perfect_partial_and_empty_inputs() -> None:
    perfect = hunk_micro_f1({"h1": "i1", "h2": "i2"}, {"h1": "s2", "h2": "s1"})
    partial = hunk_micro_f1({"h1": "i1", "h2": "i2"}, {"h1": "s1", "h2": "s1"})
    empty = hunk_micro_f1({}, {})

    assert perfect["hunk_micro_f1"] == 1.0
    assert 0.0 <= partial["hunk_micro_f1"] < 1.0
    assert empty["degraded"] is True


def test_aggregate_metrics_ignore_missing_values_and_average_available_ones() -> None:
    aggregate = aggregate_attribution_metrics(
        [
            {"pairwise_f1": 1.0, "ari": 1.0, "diagnostics": []},
            {"pairwise_f1": 0.5, "ari": 0.0, "diagnostics": ["x"]},
            {"diagnostics": ["y"]},
        ]
    )

    assert aggregate["sample_count"] == 3
    assert aggregate["mean_pairwise_f1"] == 0.75
    assert aggregate["mean_ari"] == 0.5
    assert aggregate["diagnostic_histogram"]["x"] == 1
    assert aggregate["diagnostic_histogram"]["y"] == 1
