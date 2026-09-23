# Guideline Revision Proposal

- Guideline status: `revision_required`
- Sample count: `30`

## Agreement Gates
- `bcubed_agreement`: observed=0.9350901566875931 threshold=0.8 passed=True
- `exact_k_weighted_kappa`: observed=0.8040885860306644 threshold=0.8 passed=True
- `foreground_background_agreement`: observed=0.9975172413793103 threshold=0.85 passed=True
- `pairwise_unit_agreement`: observed=0.7499263645462487 threshold=0.8 passed=False
- `split_no_split_kappa`: observed=0.6636771300448431 threshold=0.8 passed=False

## Top Disagreement Categories
- `pairwise_partition_disagreement`: 13
- `exact_k_disagreement`: 8
- `split_vs_no_split`: 5
- `uncertain_shared_mixed_disagreement`: 4
- `merge_vs_split`: 3
- `background_vs_foreground`: 2

## Required Human Action
- Human reviewer must revise the pilot guideline and rerun the calibration round.
