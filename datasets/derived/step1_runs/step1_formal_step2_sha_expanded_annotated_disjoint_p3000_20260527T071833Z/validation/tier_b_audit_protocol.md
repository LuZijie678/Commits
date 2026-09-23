# Tier-A Audit Template (300-500)

## Goal

Estimate Tier-A precision as the primary high-confidence claim, with Tier-B precision as auxiliary evidence.

## Sampling Setup

- Candidate source: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/enriched/resolved_candidates.csv`
- Primary calibration file: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/calibration/atomic_calibration_full_diff.json`
- Proxy calibration file: `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z/calibration/message_only_calibration.json`
- Tier thresholds in this run: `tau_a=0.94732`, `tau_b=0.834592`
- Audit sampling policy: `random`
- Audit sampling seed: `128`
- Audit sample size: `1`

## How To Label

- Fill `audit_is_single_intent` with `1` (single-intent) or `0` (not single-intent).
- Fill `audit_confidence` with a reviewer confidence score in `[0,1]`.
- Optional: fill `audit_reviewer` and `audit_notes`.

## Reported Metric

- `tier_a_precision = mean(tier_a_audit_is_single_intent)`
- `tier_b_precision = mean(tier_b_audit_is_single_intent)`

## Suggested Report Snippet

- We manually audited a random Tier-A sample and report its precision as the primary high-confidence claim; Tier-B is reported as auxiliary evidence for the broader candidate layer.
