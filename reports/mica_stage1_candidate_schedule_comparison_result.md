# MICA Stage 1 Candidate Schedule Comparison Result

- training_run: true
- sanity_only: true
- seeds: [13, 42, 2026]
- seed_count_downgraded: false
- candidate_schedule_validated: naive
- uses_only_stage1_sources: true
- uses_forbidden_stage2_sources: false
- model_structure_changed: false

## Results by Seed

### seed 13 / scale_c_larger / naive_balanced_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.684639
- train_loss_last_epoch: 0.176514
- dev_loss_mixed: 0.676780
- count_accuracy_mixed: 0.904000
- over_split_rate_on_k1_mixed: 0.160000
- k2_split_recall_mixed: 0.896000
- second_slot_gold_recall_mixed: 0.606133
- unit_accuracy_gain_over_all_one_mixed: 0.118325
- slot_collapse_rate_mixed: 0.096000
- candidate_threshold_pass: true

### seed 13 / scale_c_larger / T2_replay_protected_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.452869
- train_loss_last_epoch: 0.542764
- dev_loss_mixed: 0.979882
- count_accuracy_mixed: 0.848000
- over_split_rate_on_k1_mixed: 0.264000
- k2_split_recall_mixed: 0.712000
- second_slot_gold_recall_mixed: 0.408800
- unit_accuracy_gain_over_all_one_mixed: 0.064354
- slot_collapse_rate_mixed: 0.236000
- candidate_threshold_pass: true

### seed 42 / scale_c_larger / naive_balanced_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.639099
- train_loss_last_epoch: 0.309629
- dev_loss_mixed: 0.664675
- count_accuracy_mixed: 0.924000
- over_split_rate_on_k1_mixed: 0.136000
- k2_split_recall_mixed: 0.872000
- second_slot_gold_recall_mixed: 0.532533
- unit_accuracy_gain_over_all_one_mixed: 0.088782
- slot_collapse_rate_mixed: 0.108000
- candidate_threshold_pass: true

### seed 42 / scale_c_larger / T2_replay_protected_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.434024
- train_loss_last_epoch: 0.569290
- dev_loss_mixed: 0.793326
- count_accuracy_mixed: 0.900000
- over_split_rate_on_k1_mixed: 0.160000
- k2_split_recall_mixed: 0.656000
- second_slot_gold_recall_mixed: 0.386914
- unit_accuracy_gain_over_all_one_mixed: 0.050186
- slot_collapse_rate_mixed: 0.228000
- candidate_threshold_pass: false

### seed 2026 / scale_c_larger / naive_balanced_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.689700
- train_loss_last_epoch: 0.203458
- dev_loss_mixed: 0.970626
- count_accuracy_mixed: 0.888000
- over_split_rate_on_k1_mixed: 0.096000
- k2_split_recall_mixed: 0.728000
- second_slot_gold_recall_mixed: 0.549733
- unit_accuracy_gain_over_all_one_mixed: 0.093522
- slot_collapse_rate_mixed: 0.176000
- candidate_threshold_pass: true

### seed 2026 / scale_c_larger / T2_replay_protected_mixed

- train_sample_count: 1000
- dev_sample_count: 250
- medium_candidate_count_available: 3599
- train_loss_first_epoch: 1.450248
- train_loss_last_epoch: 0.505500
- dev_loss_mixed: 1.236770
- count_accuracy_mixed: 0.788000
- over_split_rate_on_k1_mixed: 0.376000
- k2_split_recall_mixed: 0.744000
- second_slot_gold_recall_mixed: 0.423333
- unit_accuracy_gain_over_all_one_mixed: 0.053730
- slot_collapse_rate_mixed: 0.236000
- candidate_threshold_pass: true

## Multi-seed Summary

### T2_replay_protected_mixed

- run_count: 3
- pass_count: 2
- pass_rate: 0.666667
- k2_split_recall_mixed: mean=0.704000, std=0.036368, min=0.656000, max=0.744000
- second_slot_gold_recall_mixed: mean=0.406349, std=0.014969, min=0.386914, max=0.423333
- unit_accuracy_gain_over_all_one_mixed: mean=0.056090, std=0.006020, min=0.050186, max=0.064354
- slot_collapse_rate_mixed: mean=0.233333, std=0.003771, min=0.228000, max=0.236000
- count_accuracy_mixed: mean=0.845333, std=0.045763, min=0.788000, max=0.900000
- over_split_rate_on_k1_mixed: mean=0.266667, std=0.088202, min=0.160000, max=0.376000

### naive_balanced_mixed

- run_count: 3
- pass_count: 3
- pass_rate: 1.000000
- k2_split_recall_mixed: mean=0.832000, std=0.074189, min=0.728000, max=0.896000
- second_slot_gold_recall_mixed: mean=0.562800, std=0.031436, min=0.532533, max=0.606133
- unit_accuracy_gain_over_all_one_mixed: mean=0.100210, std=0.012955, min=0.088782, max=0.118325
- slot_collapse_rate_mixed: mean=0.126667, std=0.035226, min=0.096000, max=0.176000
- count_accuracy_mixed: mean=0.905333, std=0.014727, min=0.888000, max=0.924000
- over_split_rate_on_k1_mixed: mean=0.130667, std=0.026399, min=0.096000, max=0.160000

## Judgment

- candidate_schedule_validated: naive
- reason: naive pass rate and mean direct attribution metrics dominate T2
- naive_pass_rate: 1.000000
- t2_pass_rate: 0.666667
- naive_mean_second_slot_gold_recall: 0.562800
- t2_mean_second_slot_gold_recall: 0.406349
- naive_mean_unit_accuracy_gain: 0.100210
- t2_mean_unit_accuracy_gain: 0.056090
- naive_mean_slot_collapse_rate: 0.126667
- t2_mean_slot_collapse_rate: 0.233333
- seed_variance_high_enough_to_change_conclusion: false
- freeze_candidate_formal_stage1_schedule: true
- next_step: freeze naive larger-scale Stage 1 candidate protocol

