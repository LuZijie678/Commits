# Stage1-v2 Guideline Pilot V3 Revision Draft

Status: `revision_draft_only`.

This draft is derived from user-reviewed Codex R2 diagnostic markings. It is not a final frozen guideline and does not convert the diagnostic sidecar into formal gold.

## Evidence Scope

- Input artifact: `human_reviewed_codex_calibration_round_2_markings`
- Record count: `30`
- Formal human evidence: `false`
- Formal blocker: `not_independent_double_annotation_or_adjudication`
- Training allowed: `false`
- Stage 2 entry allowed: `false`

## Diagnostic Triage

- Priority counts: `{'p0_blocking_review': 4, 'p1_guideline_review': 5, 'p2_secondary_review': 14, 'p3_low': 7}`
- Rows with background: `3`
- Rows with shared/uncertain/mixed labels: `5`
- Rows with review notes: `23`
- Rows with overflow/ambiguous status: `3`
- Rows with exact_k > Kmax: `1`
- P0 samples: `['calibration_round_2_0004', 'calibration_round_2_0008', 'calibration_round_2_0009', 'calibration_round_2_0016']`

## Proposed Revision Targets

1. Clarify `k > Kmax` and overflow handling: do not force complex commits into `k<=4`; route them to stress/overflow with explicit rationale.
2. Clarify generated/static previewer output: generated files are background only when the diff evidence shows they are build artifacts tied to a foreground change.
3. Clarify lockfile/dependency changes: lockfiles are background only when mechanically synchronized with a foreground dependency/runtime change.
4. Clarify shared support vs foreground: shared_support must identify which intent(s) it supports and must not hide independent action-object edits.
5. Clarify uncertain/mixed units: evidence-insufficient units should remain uncertain or mixed; do not coerce them into background or a foreground intent.
6. Clarify hard-single boundaries: required tests/docs/config can merge with a main intent, but independent infrastructure or maintenance remains separate.

## Follow-up Queue Policy

- P0 rows require direct human review before any guideline decision.
- P1 rows have user-reviewed diagnostic decisions and can be used as guideline examples.
- P2 rows have user-reviewed diagnostic decisions and can be used as secondary examples.
- P3 rows have user-reviewed low-risk diagnostic decisions.
- No row in this queue is eligible for formal training, Kmax, or Stage 2 evidence.

## P0 Follow-up Samples

- `calibration_round_2_0004`: exact_k=`None`, status=`overflow_gt_kmax_or_ambiguous`, reasons=`['exact_k_missing_or_overflow', 'overflow_or_ambiguous_status', 'shared_uncertain_or_mixed_unit', 'review_notes_present', 'high_complexity_provisional_stratum']`
- `calibration_round_2_0008`: exact_k=`5`, status=`proposed_over_kmax`, reasons=`['exact_k_exceeds_kmax', 'review_notes_present', 'high_complexity_provisional_stratum']`
- `calibration_round_2_0009`: exact_k=`None`, status=`overflow_gt_kmax_or_ambiguous`, reasons=`['exact_k_missing_or_overflow', 'overflow_or_ambiguous_status', 'shared_uncertain_or_mixed_unit', 'review_notes_present', 'high_complexity_provisional_stratum']`
- `calibration_round_2_0016`: exact_k=`None`, status=`overflow_gt_kmax_or_ambiguous`, reasons=`['exact_k_missing_or_overflow', 'overflow_or_ambiguous_status', 'review_notes_present', 'high_complexity_provisional_stratum']`

## P0 Reviewed Diagnostic Decisions

Status: `human_reviewed_diagnostic_decisions`.

- `calibration_round_2_0004`: `overflow_stress`
- `calibration_round_2_0008`: `usable_k_le_4`, diagnostic `reviewed_exact_k=4`
- `calibration_round_2_0009`: `overflow_stress`
- `calibration_round_2_0016`: `overflow_stress`

These decisions were user-reviewed from the Codex sidecar, but they remain diagnostic-only. They do not satisfy independent A/B annotation, pre-adjudication agreement, adjudicated gold, or formal human evidence.

## P3 Reviewed Diagnostic Decisions

Status: `human_reviewed_diagnostic_decisions`.

- `calibration_round_2_0005`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0011`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0018`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0021`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0023`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0025`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0028`: `accepted_low_risk_diagnostic`, diagnostic `reviewed_exact_k=3`

P3 results have been user-reviewed as diagnostic decisions. They remain ineligible for formal training, Kmax, adjudicated gold, or Stage 2 evidence.

## P1 Reviewed Diagnostic Decisions

Status: `human_reviewed_diagnostic_decisions`.

- `calibration_round_2_0002`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0003`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0006`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0014`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0019`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`

These decisions were user-reviewed from the Codex sidecar, but they remain diagnostic-only. They do not satisfy independent A/B annotation, pre-adjudication agreement, adjudicated gold, or formal human evidence.

## P2 Reviewed Diagnostic Decisions

Status: `human_reviewed_diagnostic_decisions`.

- `calibration_round_2_0001`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0007`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0010`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0012`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0013`: `usable_k_le_4`, diagnostic `reviewed_exact_k=4`
- `calibration_round_2_0015`: `usable_k_le_4`, diagnostic `reviewed_exact_k=3`
- `calibration_round_2_0017`: `usable_k_le_4`, diagnostic `reviewed_exact_k=3`
- `calibration_round_2_0020`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0022`: `usable_k_le_4`, diagnostic `reviewed_exact_k=3`; original Codex k=4 was over-split by separating `LabelFileBinding` typo cleanup from the label-binding API/support change.
- `calibration_round_2_0024`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0026`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`
- `calibration_round_2_0027`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`; original Codex k=4 was over-split by separating coordinated local-Ollama propagation/prompt/model defaults.
- `calibration_round_2_0029`: `usable_k_le_4`, diagnostic `reviewed_exact_k=2`
- `calibration_round_2_0030`: `usable_k_le_4`, diagnostic `reviewed_exact_k=1`

These decisions were user-reviewed from the Codex sidecar, but they remain diagnostic-only. They do not satisfy independent A/B annotation, pre-adjudication agreement, adjudicated gold, or formal human evidence.
