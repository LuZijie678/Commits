# Step1 Small-Scale Validation Summary

- Candidate pool: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/enriched/resolved_candidates.csv`
- Pilot source: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/annotated_splits/evaluation.csv`
- Primary calibration file: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/calibration/atomic_calibration_full_diff.json`
- Proxy calibration file: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/calibration/message_only_calibration.json`
- Diff-required validation: `True`
- Validate band thresholds: `tau_high=0.94732`, `tau_mid=0.834592`
- Validate band threshold source: `full_diff:fixed_from_args`
- Canonical validate bands: `high / mid / low`; legacy `tier=A/B/C` filenames are retained for compatibility.
- These validate bands use explicit threshold overrides from CLI arguments.
- Audit target band: `Validate High Band` (legacy `Tier-A`)
- Validate High Band count (legacy `Tier-A`): `7642`
- Validate Mid Band count (legacy `Tier-B`): `1`
- Validate Low Band count (legacy `Tier-C`): `4317`
- Validate High Band audit target size (clamped to [300, 500]): `300`

## Independent Audit Precision

- Tier-A precision: `0.96`
- Tier-A sample count: `300`
- Tier-B precision: `None`
- Tier-B sample count: `0`

## Validate High Band Type Distribution

- `test`: 2260
- `fix`: 2142
- `refactor`: 1806
- `feat`: 1434

## Validate Mid Band Type Distribution

- `refactor`: 1

## Validate High Band Role Distribution

- `source`: 5125
- `test`: 1873
- `config`: 193
- `build`: 126
- `ci`: 99
- `source,test`: 98
- `docs`: 76
- `build,source`: 11
- `config,source`: 10
- `docs,source`: 8
- `ci,source`: 6
- `build,test`: 5
- `docs,source,test`: 4
- `config,test`: 2
- `build,ci`: 2
- `config,source,test`: 1
- `build,config`: 1
- `config,docs`: 1
- `ci,test`: 1

## Validate Mid Band Role Distribution

- `source`: 1
