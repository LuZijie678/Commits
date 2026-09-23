# MICA Stage 1 Curriculum Sanity Result

- training_run: true
- sanity_only: true
- synthetic_source: local_runtime_only
- synthetic_source_committed: false
- original_tiny_subset_degenerate: true
- nondegenerate_k2_candidate_count: 3276
- file_path_baseline_mean_full_synthetic: 0.764746
- file_path_baseline_p50_full_synthetic: 1.000000
- file_path_baseline_p90_full_synthetic: 1.000000
- singleton_intent_fraction_full_synthetic: 0.684642
- assignment_overfit_any_passed: true
- assignment_overfit_passed_settings: B_50_k2_only, C_50_k2_plus_50_k1
- loss_correctness_probe_perfect_beats_all_one: true
- loss_correctness_probe_align_loss_margin_perfect_vs_all_one: 2.168363
- easy_rerun_with_direct_metrics: true
- medium_rerun_after_overfit_passed: true

## Easy

- sanity_status: failed
- train_loss_first_epoch: 2.534761
- train_loss_last_epoch: 1.363554
- dev_loss: 1.679062
- count_accuracy: 0.640000
- binary_multi_accuracy: 0.640000
- over_split_rate_on_k1: 0.240000
- under_split_rate_on_k2: 0.480000
- slot_collapse_rate: 0.520000
- assignment_entropy: 0.749128
- alignment_pairwise_f1_all_one_cluster: 0.615833
- alignment_pairwise_f1_file_path_baseline: 0.960000
- alignment_pairwise_f1_random_gold_k_mean: 0.878170
- alignment_pairwise_f1_model_oracle_k: 0.615833
- alignment_pairwise_f1_model_predicted_k: 0.615833
- unit_accuracy_hungarian: 0.788778
- hunk_accuracy_hungarian: 0.788778
- macro_intent_f1_hungarian: 0.681539
- micro_intent_f1_hungarian: 0.788778
- per_intent_recall_mean: 0.750000
- per_intent_precision_mean: 0.644389
- k2_split_recall: 0.000000
- second_slot_gold_recall: 0.000000
- second_slot_assignment_mass: 0.161922
- foreground_slot_usage_count: 1.000000
- effective_slot_count_mean: 1.526840
- assignment_top1_nonprimary_fraction: 0.000000
- all_one_unit_accuracy: 0.788778
- file_path_unit_accuracy: 0.980000
- random_gold_k_unit_accuracy_mean: 0.949278
- all_one_macro_intent_f1: 0.681539
- file_path_macro_intent_f1: 0.986667
- random_gold_k_macro_intent_f1_mean: 0.946988
- alignment_gain_over_all_one: 0.000000
- alignment_gain_over_file_path: -0.344167
- alignment_gain_over_random_gold_k: -0.262337
- attribution_gain: false
- direct_unit_gain_over_all_one: 0.000000
- direct_macro_f1_gain_over_all_one: 0.000000

### Notes

- alignment_not_above_all_one
- direct_unit_accuracy_equals_all_one
- direct_macro_f1_equals_all_one
- k2_split_recall_zero
- slot_collapse_rate_above_easy_threshold

## Medium

- sanity_status: failed
- train_loss_first_epoch: 2.476070
- train_loss_last_epoch: 1.396843
- dev_loss: 1.529747
- count_accuracy: 0.700000
- binary_multi_accuracy: 0.700000
- over_split_rate_on_k1: 0.120000
- under_split_rate_on_k2: 0.480000
- slot_collapse_rate: 0.560000
- assignment_entropy: 0.811402
- alignment_pairwise_f1_all_one_cluster: 0.828663
- alignment_pairwise_f1_file_path_baseline: 0.741603
- alignment_pairwise_f1_random_gold_k_mean: 0.721870
- alignment_pairwise_f1_model_oracle_k: 0.828663
- alignment_pairwise_f1_model_predicted_k: 0.828663
- unit_accuracy_hungarian: 0.825796
- hunk_accuracy_hungarian: 0.825796
- macro_intent_f1_hungarian: 0.695981
- micro_intent_f1_hungarian: 0.825796
- per_intent_recall_mean: 0.750000
- per_intent_precision_mean: 0.662898
- k2_split_recall: 0.000000
- second_slot_gold_recall: 0.000000
- second_slot_assignment_mass: 0.165567
- foreground_slot_usage_count: 1.000000
- effective_slot_count_mean: 1.560547
- assignment_top1_nonprimary_fraction: 0.000000
- all_one_unit_accuracy: 0.825796
- file_path_unit_accuracy: 0.804333
- random_gold_k_unit_accuracy_mean: 0.814872
- all_one_macro_intent_f1: 0.695981
- file_path_macro_intent_f1: 0.878974
- random_gold_k_macro_intent_f1_mean: 0.807146
- alignment_gain_over_all_one: 0.000000
- alignment_gain_over_file_path: 0.087060
- alignment_gain_over_random_gold_k: 0.106792
- attribution_gain: false
- direct_unit_gain_over_all_one: 0.000000
- direct_macro_f1_gain_over_all_one: 0.000000

### Notes

- alignment_not_above_all_one
- direct_unit_accuracy_equals_all_one
- direct_macro_f1_equals_all_one
- k2_split_recall_zero
- second_slot_gold_recall_zero
- slot_collapse_rate_above_medium_threshold

## Next Recommended Action

- do not freeze formal Stage 1 protocol yet; assignment overfit shows the Stage 1 objective is learnable, but medium sanity still matches the all-one baseline on both pairwise and direct attribution metrics, so the next step should inspect assignment head / slot competition behavior rather than add Stage 2 data.
