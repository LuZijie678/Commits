> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# MICA Stage 1 Formal Candidate Protocol

## 文档用途

This document freezes the candidate Stage 1 protocol for the next official validation run. It is a protocol and split freeze step only. It does not run formal training and does not open Stage 2.

## Data Boundary

Allowed Stage 1 data:

- Step1 atomic `k=1`: `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- Step2 strict/sanity synthetic `k=2`: local runtime `synthetic_samples_step3_ready.jsonl`

The synthetic source path is local-runtime-only. The full source file and runtime manifests are not committed.

Explicitly not included:

- `hard_b`
- `M weak`
- `M alignment`
- `RealDomainBinary`
- `Stage 2`
- generation
- retrieval
- verifier
- LLM Judge
- real API calls

## Medium Curriculum Definition

Synthetic `k=2` samples use the medium curriculum filter:

- `total_edit_units >= 4`
- each intent has at least two edit units if possible
- `file_path_baseline_pairwise_f1 <= 0.90`
- `random_gold_k_pairwise_f1 <= 0.80` if possible

If the requested formal split cannot be filled, fallback is allowed only inside Stage 1 data. The manifest summary must record `fallback_applied`, `fallback_reason`, and the post-fallback baseline distribution.

## Formal Split Definition

Target split:

- train: `k1=1000`, `k2=1000`
- dev: `k1=250`, `k2=250`
- test: `k1=250`, `k2=250`

The runtime manifest contains:

- `stage1_formal_manifest.json`
- `stage1_formal_manifest_train.json`
- `stage1_formal_manifest_dev.json`
- `stage1_formal_manifest_test.json`

These files are written under `outputs/mica_stage1_formal_manifest_<timestamp>/` and are not committed.

## Candidate Schedule

The candidate schedule is larger-scale naive_balanced_mixed:

- `candidate_stage1_schedule = naive_balanced_mixed_large_scale`
- epochs: `15`
- train mixed `k1/k2` from epoch 1
- `lambda_align = 1.0`
- `lambda_count = 0.5`
- `lambda_exist = 0.5`
- no replay
- no staged `k2` warmup
- no Stage 2 loss
- no `hard_b/M`

T2 replay-protected mixed training remains a diagnostic ablation. It is not selected as the candidate formal Stage 1 schedule because larger-scale multi-seed comparison favored naive mixed.

## Objective

The Stage 1 objective remains:

```text
L_main =
  1.0 * L_align
  + 0.5 * L_count
  + 0.5 * L_exist
```

No new main loss is introduced.

## Metrics

The official validation must report:

- train loss first and last epoch
- dev and test loss
- count accuracy
- binary multi accuracy
- over-split rate on `k=1`
- under-split rate on `k=2`
- unit accuracy after Hungarian matching
- macro and micro intent F1 after Hungarian matching
- `k2_split_recall`
- `second_slot_gold_recall`
- `second_slot_assignment_mass`
- effective slot count
- slot collapse rate
- assignment entropy
- pairwise alignment F1 against all-one, file-path, random-gold-k, oracle-k, and predicted-k baselines

## Baselines

The validation must include:

- all-one cluster baseline
- file-path cluster baseline
- random-gold-k baseline

Pairwise F1 alone is insufficient; direct unit and intent metrics are required.

## Pass/Fail Criteria

Candidate Stage 1 validation should pass only if the formal dev/test results satisfy:

- `k2_split_recall >= 0.50`
- `second_slot_gold_recall >= 0.40`
- `unit_accuracy_gain_over_all_one > 0.03`
- `slot_collapse_rate <= 0.45`
- `count_accuracy >= 0.55`
- `over_split_rate_on_k1 <= 0.45`

If these fail, Stage 1 remains blocked and Stage 2 must not start.

## Leakage Checks

The manifest freeze must report:

- sample ID overlap between train/dev/test
- atomic SHA overlap between train/dev/test where available
- synthetic ID or source SHA overlap where available
- normalized subject overlap where available
- repo overlap status

Hard leakage must be zero for sample IDs and SHA/source identifiers where available. Repo overlap is allowed for the current Stage 1 synthetic setting because the local Step1/Step2 pools are sample-disjoint but not guaranteed repo-disjoint.

## Reproducibility

Freeze parameters:

- seed: `42`
- deterministic sample ordering by seed and sample ID
- runtime manifest path recorded in reports
- summary reports committed under `reports/`
- runtime manifests and full source data not committed

## What Is Explicitly Not Included

This protocol does not include:

- Stage 2 calibration
- `hard_b`
- `M weak`
- `M alignment`
- `RealDomainBinary`
- generation training
- retrieval
- verifier
- real API calls
- model architecture changes
- new main losses

## Next Step After Freeze

The next action is to run official Stage 1 validation using the frozen candidate schedule and runtime manifest. Stage 2 remains disallowed until that validation completes and passes.
