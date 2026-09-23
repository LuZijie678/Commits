# MICA Stage 1 T2 Scale-up Result

- training_run: true
- sanity_only: true
- t2_scaleup_validated: false
- uses_only_stage1_sources: true
- uses_forbidden_stage2_sources: false

## Data Audits

### scale_a_sanity_reference

- k1_train: 100
- k2_train: 100
- k1_dev: 25
- k2_dev: 25
- k2_candidate_count_available: 3599
- fallback_applied: false
- fallback_reason: []
- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.557291
- random_gold_k_baseline_mean: 0.434666
- avg_edit_units: 5.936000
- p50_edit_units: 7.000000
- p90_edit_units: 14.600000
- scale_c_downgraded: false
- downgrade_reason: None

### scale_b_medium

- k1_train: 300
- k2_train: 300
- k1_dev: 75
- k2_dev: 75
- k2_candidate_count_available: 3599
- fallback_applied: false
- fallback_reason: []
- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.591061
- random_gold_k_baseline_mean: 0.435007
- avg_edit_units: 6.658667
- p50_edit_units: 7.000000
- p90_edit_units: 14.600000
- scale_c_downgraded: false
- downgrade_reason: None

### scale_c_larger

- k1_train: 500
- k2_train: 500
- k1_dev: 125
- k2_dev: 125
- k2_candidate_count_available: 3599
- fallback_applied: false
- fallback_reason: []
- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.585332
- random_gold_k_baseline_mean: 0.433762
- avg_edit_units: 6.408800
- p50_edit_units: 7.000000
- p90_edit_units: 14.000000
- scale_c_downgraded: true
- downgrade_reason: cpu validation cost; retained allowed 500/500/125/125 Scale C fallback

## Results

### scale_a_sanity_reference / naive_balanced_mixed

- epochs: 15
- train_sample_count: 200
- dev_sample_count: 50
- train_loss_first_epoch: 2.440606
- train_loss_last_epoch: 0.210140
- dev_loss_mixed: 1.066925
- dev_loss_k2_only: 1.262189
- count_accuracy_mixed: 0.880000
- over_split_rate_on_k1_mixed: 0.160000
- k2_split_recall_mixed: 0.680000
- second_slot_gold_recall_mixed: 0.245333
- unit_accuracy_gain_over_all_one_mixed: 0.070318
- slot_collapse_rate_mixed: 0.200000
- scaleup_threshold_pass: false

### scale_a_sanity_reference / T2_replay_protected_mixed

- epochs: 15
- train_sample_count: 200
- dev_sample_count: 50
- train_loss_first_epoch: 2.060087
- train_loss_last_epoch: 0.633350
- dev_loss_mixed: 1.120880
- dev_loss_k2_only: 0.946734
- count_accuracy_mixed: 0.760000
- over_split_rate_on_k1_mixed: 0.400000
- k2_split_recall_mixed: 0.880000
- second_slot_gold_recall_mixed: 0.480000
- unit_accuracy_gain_over_all_one_mixed: 0.045203
- slot_collapse_rate_mixed: 0.140000
- scaleup_threshold_pass: true

### scale_b_medium / naive_balanced_mixed

- epochs: 15
- train_sample_count: 600
- dev_sample_count: 150
- train_loss_first_epoch: 1.857419
- train_loss_last_epoch: 0.236479
- dev_loss_mixed: 0.851864
- dev_loss_k2_only: 1.560926
- count_accuracy_mixed: 0.906667
- over_split_rate_on_k1_mixed: 0.040000
- k2_split_recall_mixed: 0.666667
- second_slot_gold_recall_mixed: 0.316476
- unit_accuracy_gain_over_all_one_mixed: 0.064797
- slot_collapse_rate_mixed: 0.173333
- scaleup_threshold_pass: false

### scale_b_medium / T2_replay_protected_mixed

- epochs: 15
- train_sample_count: 600
- dev_sample_count: 150
- train_loss_first_epoch: 1.611336
- train_loss_last_epoch: 0.670516
- dev_loss_mixed: 0.788075
- dev_loss_k2_only: 1.019239
- count_accuracy_mixed: 0.920000
- over_split_rate_on_k1_mixed: 0.133333
- k2_split_recall_mixed: 0.760000
- second_slot_gold_recall_mixed: 0.378095
- unit_accuracy_gain_over_all_one_mixed: 0.065300
- slot_collapse_rate_mixed: 0.166667
- scaleup_threshold_pass: false

### scale_c_larger / naive_balanced_mixed

- epochs: 15
- train_sample_count: 1000
- dev_sample_count: 250
- train_loss_first_epoch: 1.639099
- train_loss_last_epoch: 0.309629
- dev_loss_mixed: 0.664675
- dev_loss_k2_only: 0.727591
- count_accuracy_mixed: 0.924000
- over_split_rate_on_k1_mixed: 0.136000
- k2_split_recall_mixed: 0.872000
- second_slot_gold_recall_mixed: 0.532533
- unit_accuracy_gain_over_all_one_mixed: 0.088782
- slot_collapse_rate_mixed: 0.108000
- scaleup_threshold_pass: true

### scale_c_larger / T2_replay_protected_mixed

- epochs: 15
- train_sample_count: 1000
- dev_sample_count: 250
- train_loss_first_epoch: 1.434024
- train_loss_last_epoch: 0.569290
- dev_loss_mixed: 0.793326
- dev_loss_k2_only: 1.046896
- count_accuracy_mixed: 0.900000
- over_split_rate_on_k1_mixed: 0.160000
- k2_split_recall_mixed: 0.656000
- second_slot_gold_recall_mixed: 0.386914
- unit_accuracy_gain_over_all_one_mixed: 0.050186
- slot_collapse_rate_mixed: 0.228000
- scaleup_threshold_pass: false

## T2 vs Naive

### scale_a_sanity_reference

- delta_k2_split_recall: 0.200000
- delta_second_slot_gold_recall: 0.234667
- delta_unit_accuracy_gain_over_all_one: -0.025115
- delta_slot_collapse_rate: -0.060000
- delta_count_accuracy: -0.120000
- delta_over_split_rate_on_k1: 0.240000

### scale_b_medium

- delta_k2_split_recall: 0.093333
- delta_second_slot_gold_recall: 0.061619
- delta_unit_accuracy_gain_over_all_one: 0.000504
- delta_slot_collapse_rate: -0.006667
- delta_count_accuracy: 0.013333
- delta_over_split_rate_on_k1: 0.093333

### scale_c_larger

- delta_k2_split_recall: -0.216000
- delta_second_slot_gold_recall: -0.145619
- delta_unit_accuracy_gain_over_all_one: -0.038596
- delta_slot_collapse_rate: 0.120000
- delta_count_accuracy: -0.024000
- delta_over_split_rate_on_k1: 0.024000

## Judgment

- t2_scaleup_validated: false
- scale_b_valid: false
- scale_c_valid: false
- reason: T2 did not pass required Scale B/C validation.
- next_step: representation/architecture revision inside Stage 1, not later-stage data
- freeze_candidate_formal_stage1_schedule: false

