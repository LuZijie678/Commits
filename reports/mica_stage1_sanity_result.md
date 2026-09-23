# MICA Stage 1 Sanity Result

- training_run: true
- sanity_only: true
- synthetic_source: local_runtime_only
- synthetic_source_committed: false
- local_runtime_only_path_available: true
- max_train_samples: 8
- max_dev_samples: 4
- epochs: 2
- batch_size: 4
- device: cpu
- assignment_temperature: 0.700
- assignment_tau_first_epoch: 1.500
- assignment_tau_last_epoch: 0.700
- existence_mass_coupling_strength: 1.500
- count_pb_coupling_strength: 0.500
- with_stabilizer: true
- lambda_stab: 0.030
- train_loss_first_epoch: 2.881058
- train_loss_last_epoch: 2.824128
- dev_loss: 2.490282
- count_accuracy: 1.000000
- binary_multi_accuracy: 1.000000
- over_split_rate_on_k1: 0.000000
- under_split_rate_on_k2: 0.000000
- slot_collapse_rate: 0.000000
- assignment_entropy: 2.247814
- oracle_k_alignment_pairwise_f1: 1.000000
- predicted_k_alignment_pairwise_f1: 1.000000
- alignment_pairwise_f1_all_one_cluster: 1.000000
- alignment_pairwise_f1_file_path_baseline: 1.000000
- alignment_pairwise_f1_random_gold_k_mean: 1.000000
- alignment_gain_over_all_one: 0.000000
- alignment_gain_over_file_path: 0.000000
- alignment_gain_over_random_gold_k: 0.000000
- attribution_gain: false
- sanity_status: failed

## Notes

- all_samples_predicted_same_count

## Comparison to a294243

- count_accuracy: previous=1.000000, current=1.000000, delta=0.000000
- binary_multi_accuracy: previous=1.000000, current=1.000000, delta=0.000000
- over_split_rate_on_k1: previous=0.000000, current=0.000000, delta=0.000000
- under_split_rate_on_k2: previous=0.000000, current=0.000000, delta=0.000000
- slot_collapse_rate: previous=0.000000, current=0.000000, delta=0.000000
- assignment_entropy: previous=2.248834, current=2.247814, delta=-0.001020
- oracle_k_alignment_pairwise_f1: previous=1.000000, current=1.000000, delta=0.000000
- predicted_k_alignment_pairwise_f1: previous=1.000000, current=1.000000, delta=0.000000

## Next Recommended Action

- debug training collapse or data issues before attempting any Stage 2 calibration
