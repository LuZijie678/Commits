# MICA Stage 1 Sanity Plan

- Branch: `experiment/mica-v3-attribution-mvp`
- Base checkpoint: `b15eb20`
- Scope: MICA-v3 Stage 1 attribution MVP skeleton only

## Confirmed Inputs

- Step1 atomic source pool:
  - `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- Step2 bridge:
  - `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
  - `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json`
- Step1 split report:
  - `datasets/step1/manifest/dataset_split_report.json`
- Local Step2 strict synthetic runtime source on this machine:
  - `/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl`

## Confirmed Gaps

- no tracked `code/step3/`
- no tracked official MICA bootstrap `train/dev/test` split
- no tracked clean-branch `synthetic_samples_step3_ready.jsonl`
- no tracked live `RealDomainBinary` dataset found

## MVP Objective

```text
L_main =
  1.0 * L_align
  + 0.5 * L_count
  + 0.5 * L_exist
```

Explicitly disabled:

- `L_multi`
- `L_gen`
- `L_faith`
- `L_role`
- `L_cohesion`

## This Round

Implemented:

- Stage 1 schema
- diff-to-edit-unit parsing
- Stage 1 loader
- observable evidence features
- lightweight PyTorch model skeleton
- alignment / existence / count losses
- CPU sanity script
- `tests/mica/`

Not implemented:

- Stage 2 hard_b calibration
- Stage 3 generation
- verifier / reranker / retrieval
- fine-tuning
- real API work

## Runtime Decision

`training_not_run = true`

Reason:

`implementation_skeleton_only`
