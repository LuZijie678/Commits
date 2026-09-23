# MICA Stage 1 Assignment Overfit Result

- training_run: true
- uses_only_stage1_sources: true
- uses_hard_b_or_m: false

## A_20_k2_only

- overfit_passed: false
- align_only: false
- train_sample_count: 20
- k1_count: 0
- k2_count: 20
- train_loss_first_epoch: 3.138133
- train_loss_last_epoch: 0.647010
- count_accuracy_train: 1.000000
- unit_accuracy_hungarian_train: 0.927778
- macro_intent_f1_hungarian_train: 0.894156
- k2_split_recall_train: 0.900000
- second_slot_gold_recall_train: 0.654167
- second_slot_assignment_mass_train: 0.370232
- effective_slot_count_mean_train: 1.907005
- slot_collapse_rate_train: 0.100000
- assignment_entropy_train: 0.812460

## B_50_k2_only

- overfit_passed: true
- align_only: false
- train_sample_count: 50
- k1_count: 0
- k2_count: 50
- train_loss_first_epoch: 3.070192
- train_loss_last_epoch: 0.398684
- count_accuracy_train: 1.000000
- unit_accuracy_hungarian_train: 0.940010
- macro_intent_f1_hungarian_train: 0.912253
- k2_split_recall_train: 0.940000
- second_slot_gold_recall_train: 0.739048
- second_slot_assignment_mass_train: 0.288210
- effective_slot_count_mean_train: 1.758772
- slot_collapse_rate_train: 0.060000
- assignment_entropy_train: 0.279237

## C_50_k2_plus_50_k1

- overfit_passed: true
- align_only: false
- train_sample_count: 100
- k1_count: 50
- k2_count: 50
- train_loss_first_epoch: 2.618889
- train_loss_last_epoch: 0.033244
- count_accuracy_train: 1.000000
- unit_accuracy_hungarian_train: 0.993333
- macro_intent_f1_hungarian_train: 0.991055
- k2_split_recall_train: 1.000000
- second_slot_gold_recall_train: 0.860000
- second_slot_assignment_mass_train: 0.363281
- effective_slot_count_mean_train: 1.439765
- slot_collapse_rate_train: 0.000000
- assignment_entropy_train: 0.026965

## D_20_k2_align_only

- overfit_passed: false
- align_only: true
- train_sample_count: 20
- k1_count: 0
- k2_count: 20
- train_loss_first_epoch: 1.499476
- train_loss_last_epoch: 0.013056
- count_accuracy_train: 0.000000
- unit_accuracy_hungarian_train: 1.000000
- macro_intent_f1_hungarian_train: 1.000000
- k2_split_recall_train: 1.000000
- second_slot_gold_recall_train: 0.850000
- second_slot_assignment_mass_train: 0.388579
- effective_slot_count_mean_train: 1.918178
- slot_collapse_rate_train: 1.000000
- assignment_entropy_train: 0.042601

