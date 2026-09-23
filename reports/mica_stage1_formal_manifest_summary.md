# MICA Stage 1 Formal Manifest Summary

- seed: 42
- schedule_candidate: naive_balanced_mixed_large_scale
- formal_manifest_status: frozen_runtime_manifest_created
- formal_manifest_downgraded: false
- fallback_applied: false
- fallback_reason: []
- runtime_manifest_not_committed: true
- runtime_manifest_path: outputs/mica_stage1_formal_manifest_20260615T000000Z/stage1_formal_manifest.json
- synthetic_source_path_is_local_runtime_only: true

## Counts

- train: total=2000, k1=1000, k2=1000
- dev: total=500, k1=250, k2=250
- test: total=500, k1=250, k2=250

## Split Diagnostics

### train

- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.561651
- random_gold_k_baseline_mean: 0.428769
- avg_edit_units: 8.212000
- p50_edit_units: 7.000000
- p90_edit_units: 14.000000

### dev

- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.560980
- random_gold_k_baseline_mean: 0.429497
- avg_edit_units: 8.032000
- p50_edit_units: 7.000000
- p90_edit_units: 13.000000

### test

- singleton_intent_fraction: 0.000000
- file_path_baseline_mean: 0.558746
- random_gold_k_baseline_mean: 0.424208
- avg_edit_units: 8.092000
- p50_edit_units: 6.000000
- p90_edit_units: 15.000000

## Leakage Checks

- sample_id_overlap_count: 0
- sha_overlap_count: 0
- synthetic_id_overlap_count: 0
- normalized_subject_overlap_count: 674
- repo_overlap_count: 125
- repo_overlap_allowed_for_stage1_synthetic: true
- repo_overlap_reason: Stage 1 synthetic attribution splits are sample-disjoint; repo-disjointness is not guaranteed by current local Step1/Step2 pools.
