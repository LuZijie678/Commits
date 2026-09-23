# MICA Stage 1 Slot Competition Ablation Result

- training_run: true
- sanity_only: true
- manifest_rebuilt: false
- manifest_runtime_only: true
- slot_competition_fix_found: true

## Problem Statement

The model can overfit assignment, but normal medium Stage 1 training collapses to one foreground slot. This suggests a slot-competition/training-schedule failure rather than an unlearnable assignment head.

## S0_current_normal_medium

- schedule_description: Current normal medium baseline with mixed k1/k2 training and current coupling.
- epochs: 3
- train_loss_first_epoch: 2.476070
- train_loss_last_epoch: 1.396843
- dev_loss: 1.529747
- count_accuracy: 0.700000
- over_split_rate_on_k1: 0.120000
- under_split_rate_on_k2: 0.480000
- unit_accuracy_hungarian: 0.825796
- macro_intent_f1_hungarian: 0.695981
- k2_split_recall: 0.000000
- second_slot_gold_recall: 0.000000
- second_slot_assignment_mass: 0.165567
- slot_collapse_rate: 0.560000
- alignment_gain_over_all_one: 0.000000
- unit_accuracy_gain_over_all_one: 0.000000
- macro_f1_gain_over_all_one: 0.000000
- slot_competition_fix: false

## S1_longer_training

- schedule_description: Longer mixed training to test whether 3 epochs are insufficient.
- epochs: 10
- train_loss_first_epoch: 2.638706
- train_loss_last_epoch: 0.547627
- dev_loss: 0.940374
- count_accuracy: 0.940000
- over_split_rate_on_k1: 0.120000
- under_split_rate_on_k2: 0.000000
- unit_accuracy_hungarian: 0.877616
- macro_intent_f1_hungarian: 0.820648
- k2_split_recall: 0.680000
- second_slot_gold_recall: 0.290000
- second_slot_assignment_mass: 0.245803
- slot_collapse_rate: 0.220000
- alignment_gain_over_all_one: 0.005816
- unit_accuracy_gain_over_all_one: 0.051820
- macro_f1_gain_over_all_one: 0.124667
- slot_competition_fix: false

## S2_align_dominant

- schedule_description: Reduce count/existence pressure while keeping mixed training and current coupling.
- epochs: 10
- train_loss_first_epoch: 1.659725
- train_loss_last_epoch: 0.390555
- dev_loss: 0.873879
- count_accuracy: 0.900000
- over_split_rate_on_k1: 0.200000
- under_split_rate_on_k2: 0.000000
- unit_accuracy_hungarian: 0.910363
- macro_intent_f1_hungarian: 0.876080
- k2_split_recall: 0.880000
- second_slot_gold_recall: 0.330000
- second_slot_assignment_mass: 0.252039
- slot_collapse_rate: 0.160000
- alignment_gain_over_all_one: 0.048346
- unit_accuracy_gain_over_all_one: 0.084567
- macro_f1_gain_over_all_one: 0.180099
- slot_competition_fix: false

## S3_align_only_warmup_then_full

- schedule_description: Warm up assignment with align-only epochs, then enable count/existence calibration.
- epochs: 10
- train_loss_first_epoch: 1.429889
- train_loss_last_epoch: 0.557137
- dev_loss: 0.753883
- count_accuracy: 0.920000
- over_split_rate_on_k1: 0.120000
- under_split_rate_on_k2: 0.040000
- unit_accuracy_hungarian: 0.889665
- macro_intent_f1_hungarian: 0.855497
- k2_split_recall: 0.880000
- second_slot_gold_recall: 0.256667
- second_slot_assignment_mass: 0.284463
- slot_collapse_rate: 0.100000
- alignment_gain_over_all_one: 0.028701
- unit_accuracy_gain_over_all_one: 0.063869
- macro_f1_gain_over_all_one: 0.159516
- slot_competition_fix: false

## S4_k2_focused_warmup_then_mixed

- schedule_description: Warm up on medium k2 only, then switch to mixed k1/k2 training.
- epochs: 10
- train_loss_first_epoch: 2.077019
- train_loss_last_epoch: 1.116468
- dev_loss: 1.185632
- count_accuracy: 0.880000
- over_split_rate_on_k1: 0.200000
- under_split_rate_on_k2: 0.040000
- unit_accuracy_hungarian: 0.825796
- macro_intent_f1_hungarian: 0.695981
- k2_split_recall: 0.000000
- second_slot_gold_recall: 0.000000
- second_slot_assignment_mass: 0.256590
- slot_collapse_rate: 0.600000
- alignment_gain_over_all_one: 0.000000
- unit_accuracy_gain_over_all_one: 0.000000
- macro_f1_gain_over_all_one: 0.000000
- slot_competition_fix: false

## S5_disable_deterministic_coupling

- schedule_description: Keep mixed training but disable deterministic assignment-mass and pb-prior coupling.
- epochs: 10
- train_loss_first_epoch: 2.730049
- train_loss_last_epoch: 1.132833
- dev_loss: 1.197265
- count_accuracy: 0.880000
- over_split_rate_on_k1: 0.200000
- under_split_rate_on_k2: 0.040000
- unit_accuracy_hungarian: 0.844246
- macro_intent_f1_hungarian: 0.751307
- k2_split_recall: 0.360000
- second_slot_gold_recall: 0.170000
- second_slot_assignment_mass: 0.271122
- slot_collapse_rate: 0.420000
- alignment_gain_over_all_one: 0.006593
- unit_accuracy_gain_over_all_one: 0.018449
- macro_f1_gain_over_all_one: 0.055326
- slot_competition_fix: false

## S6_k2_only_generalization

- schedule_description: Train and evaluate on medium k2 only to isolate k1 mixing pressure.
- epochs: 10
- train_loss_first_epoch: 2.051179
- train_loss_last_epoch: 0.940564
- dev_loss: 0.796277
- count_accuracy: 1.000000
- over_split_rate_on_k1: 0.000000
- under_split_rate_on_k2: 0.000000
- unit_accuracy_hungarian: 0.781662
- macro_intent_f1_hungarian: 0.710928
- k2_split_recall: 0.880000
- second_slot_gold_recall: 0.423333
- second_slot_assignment_mass: 0.332672
- slot_collapse_rate: 0.120000
- alignment_gain_over_all_one: 0.032872
- unit_accuracy_gain_over_all_one: 0.130069
- macro_f1_gain_over_all_one: 0.318966
- slot_competition_fix: true

## Ranking

- best_by_k2_split_recall: S6_k2_only_generalization
- best_by_second_slot_gold_recall: S6_k2_only_generalization
- best_by_unit_accuracy_gain: S6_k2_only_generalization
- best_by_lowest_slot_collapse: S3_align_only_warmup_then_full
- best_balanced_setting: S6_k2_only_generalization

## Cause Analysis

- q1_k1_k2_mixed_training_causes_collapse: true
- q2_count_existence_loss_suppresses_alignment: false
- q3_deterministic_coupling_contributed_to_collapse: false
- q4_epochs_too_few: false
- q5_k2_split_signal_too_weak: false
- q6_minimal_viable_stage1_schedule: S6_k2_only_generalization

k1/k2 mixing suppresses early slot specialization; need k2-focused or align-only warmup before mixed training.

