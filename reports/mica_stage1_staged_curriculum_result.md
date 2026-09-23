# MICA Stage 1 Staged Curriculum Result

- training_run: true
- sanity_only: true
- manifest_rebuilt: false
- manifest_runtime_only: true
- staged_schedule_fix_found: true

## Motivation

The model can overfit assignment, but normal medium Stage 1 training collapses to one foreground slot. This suggests a slot-competition/training-schedule failure rather than an unlearnable assignment head.

## T0_k2_only_reference

- schedule_description: K2-only attribution upper reference; not a final mixed Stage 1 protocol.
- epochs: 10
- train_loss_first_epoch: 2.060087
- train_loss_last_epoch: 0.840835
- count_accuracy_mixed: 0.500000
- count_accuracy_k2_only: 1.000000
- unit_accuracy_hungarian_mixed: 0.822283
- unit_accuracy_hungarian_k2_only: 0.755837
- k2_split_recall_mixed: 0.920000
- k2_split_recall_k2_only: 0.920000
- second_slot_gold_recall_mixed: 0.430000
- second_slot_gold_recall_k2_only: 0.430000
- slot_collapse_rate_mixed: 0.180000
- slot_collapse_rate_k2_only: 0.080000
- unit_accuracy_gain_over_all_one_mixed: -0.003513
- macro_f1_gain_over_all_one_mixed: 0.118899
- staged_schedule_fix: false

## T1_long_k2_specialization_then_gentle_k1_reintroduction

- schedule_description: Long k2-only specialization, then 3:1 and 1:1 reintroduction with gentle coupling.
- epochs: 15
- train_loss_first_epoch: 1.972532
- train_loss_last_epoch: 0.590362
- count_accuracy_mixed: 0.860000
- count_accuracy_k2_only: 0.960000
- unit_accuracy_hungarian_mixed: 0.871886
- unit_accuracy_hungarian_k2_only: 0.807106
- k2_split_recall_mixed: 0.720000
- k2_split_recall_k2_only: 0.720000
- second_slot_gold_recall_mixed: 0.383333
- second_slot_gold_recall_k2_only: 0.383333
- slot_collapse_rate_mixed: 0.200000
- slot_collapse_rate_k2_only: 0.280000
- unit_accuracy_gain_over_all_one_mixed: 0.046090
- macro_f1_gain_over_all_one_mixed: 0.140985
- staged_schedule_fix: false

## T2_k2_specialization_with_replay_protected_mixed_training

- schedule_description: K2-only specialization followed by mixed training with fixed k2 replay batches.
- epochs: 15
- train_loss_first_epoch: 2.124621
- train_loss_last_epoch: 0.715883
- count_accuracy_mixed: 0.780000
- count_accuracy_k2_only: 0.960000
- unit_accuracy_hungarian_mixed: 0.869570
- unit_accuracy_hungarian_k2_only: 0.820251
- k2_split_recall_mixed: 0.920000
- k2_split_recall_k2_only: 0.920000
- second_slot_gold_recall_mixed: 0.486667
- second_slot_gold_recall_k2_only: 0.486667
- slot_collapse_rate_mixed: 0.120000
- slot_collapse_rate_k2_only: 0.080000
- unit_accuracy_gain_over_all_one_mixed: 0.043773
- macro_f1_gain_over_all_one_mixed: 0.162103
- staged_schedule_fix: true

## T3_align_preserving_mixed_training

- schedule_description: Align-only k2 warmup, then mixed training with gradual count/exist warmup.
- epochs: 15
- train_loss_first_epoch: 1.474619
- train_loss_last_epoch: 0.451329
- count_accuracy_mixed: 0.700000
- count_accuracy_k2_only: 0.880000
- unit_accuracy_hungarian_mixed: 0.859725
- unit_accuracy_hungarian_k2_only: 0.799449
- k2_split_recall_mixed: 0.680000
- k2_split_recall_k2_only: 0.680000
- second_slot_gold_recall_mixed: 0.293333
- second_slot_gold_recall_k2_only: 0.293333
- slot_collapse_rate_mixed: 0.220000
- slot_collapse_rate_k2_only: 0.320000
- unit_accuracy_gain_over_all_one_mixed: 0.033928
- macro_f1_gain_over_all_one_mixed: 0.124764
- staged_schedule_fix: false

## T4_freeze_slot_queries_after_k2_specialization

- schedule_description: Freeze slot queries during mixed reintroduction to protect specialized foreground slots.
- epochs: 15
- train_loss_first_epoch: 2.076974
- train_loss_last_epoch: 0.479661
- count_accuracy_mixed: 0.760000
- count_accuracy_k2_only: 0.920000
- unit_accuracy_hungarian_mixed: 0.840696
- unit_accuracy_hungarian_k2_only: 0.764726
- k2_split_recall_mixed: 0.680000
- k2_split_recall_k2_only: 0.680000
- second_slot_gold_recall_mixed: 0.280000
- second_slot_gold_recall_k2_only: 0.280000
- slot_collapse_rate_mixed: 0.200000
- slot_collapse_rate_k2_only: 0.320000
- unit_accuracy_gain_over_all_one_mixed: 0.014900
- macro_f1_gain_over_all_one_mixed: 0.106570
- staged_schedule_fix: false

## T5_disable_deterministic_coupling_during_reintroduction

- schedule_description: Disable deterministic coupling during mixed k1 reintroduction.
- epochs: 15
- train_loss_first_epoch: 2.054674
- train_loss_last_epoch: 1.143358
- count_accuracy_mixed: 0.900000
- count_accuracy_k2_only: 1.000000
- unit_accuracy_hungarian_mixed: 0.848518
- unit_accuracy_hungarian_k2_only: 0.754654
- k2_split_recall_mixed: 0.840000
- k2_split_recall_k2_only: 0.840000
- second_slot_gold_recall_mixed: 0.320000
- second_slot_gold_recall_k2_only: 0.320000
- slot_collapse_rate_mixed: 0.120000
- slot_collapse_rate_k2_only: 0.160000
- unit_accuracy_gain_over_all_one_mixed: 0.022721
- macro_f1_gain_over_all_one_mixed: 0.133189
- staged_schedule_fix: false

## Ranking

- best_by_mixed_second_slot_gold_recall: T2_k2_specialization_with_replay_protected_mixed_training
- best_by_mixed_k2_split_recall: T2_k2_specialization_with_replay_protected_mixed_training
- best_by_mixed_unit_accuracy_gain: T1_long_k2_specialization_then_gentle_k1_reintroduction
- best_by_lowest_mixed_slot_collapse: T2_k2_specialization_with_replay_protected_mixed_training
- best_balanced_stage1_schedule: T2_k2_specialization_with_replay_protected_mixed_training

## Cause Analysis

- q1_k1_k2_mixing_suppresses_early_slot_specialization: true
- q2_count_existence_losses_suppress_alignment: false
- q3_deterministic_coupling_aggravates_collapse: false
- q4_epochs_too_few: false
- q5_k2_split_signal_too_weak: false
- q6_minimal_viable_stage1_schedule: T2_k2_specialization_with_replay_protected_mixed_training

staged Stage 1 protocol is viable; next step should freeze formal Stage 1 schedule and rerun with larger sample.

