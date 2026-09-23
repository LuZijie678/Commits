# MICA Stage 1 Attribution Debug

- oracle_predicted_k_exactly_equal: true
- oracle_predicted_k_label_diff_count: 0
- oracle_predicted_k_f1_diff_count: 0
- trivial_baseline_definition: all edits assigned to one cluster; pairwise F1 computed against gold intent grouping
- alignment_pairwise_f1_model_oracle_k: 0.828663
- alignment_pairwise_f1_model_predicted_k: 0.828663
- alignment_pairwise_f1_all_one_cluster: 0.828663
- alignment_pairwise_f1_file_path_baseline: 0.741603
- alignment_pairwise_f1_random_gold_k_mean: 0.711659
- unit_accuracy_hungarian: 0.825796
- macro_intent_f1_hungarian: 0.695981
- k2_split_recall: 0.000000
- second_slot_gold_recall: 0.000000
- second_slot_assignment_mass: 0.165567
- effective_slot_count_mean: 1.560547
- assignment_top1_nonprimary_fraction: 0.000000
- attribution_gain: false
- padding_excluded_from_metrics: true
- padding_excluded_from_loss: true
- k2_avg_edit_unit_count: 8.880000
- k2_singleton_intent_fraction: 0.000000
- gradient_norm_assignment_head: 4.183192
- gradient_norm_slot_queries: 3.908864
- gradient_norm_encoder: 0.997855
- perfect_align_loss: 0.153327
- all_one_align_loss: 2.321690
- perfect_beats_all_one: true

## Assignment Top-1 Slot Distribution

- slot_1: 297

## Slot Usage Histogram

- slot_0: 26
- slot_1: 49

## Matched Slot Existence

- mean: 0.719017
- p50: 0.843507
- p90: 0.962222

## Unmatched Slot Existence

- mean: 0.078128
- p50: 0.001599
- p90: 0.323232
