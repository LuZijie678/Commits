# MICA Stage0 Protocol Freeze Readiness

## Status
- `protocol_freeze_ready`: True
- `formal_ready`: False
- `dry_run`: True
- `training_executed`: False

## Data Card
- `valid`: True
- `missing_requirements`: []
- `requirement_count`: 45

## Eval Protocol
- `valid`: True
- `missing_requirements`: []
- `requirement_count`: 58

## Asset Boundary
- `valid`: True
- `errors`: 0

## Kmax Coverage
- `status`: protocol_defined
- `paper_readiness`: ready_for_kmax_freeze_if_tau_satisfied
- `kmax`: 4
- `tau`: None
- `selected_Kmax`: {'value': 4, 'status': 'implementation_default_not_final_boundary'}
- `train_dev_selection_basis`: {'sample_count': 3910, 'covered_count': 3910, 'overflow_count': 0, 'coverage_at_kmax': 1.0, 'overflow_rate': 0.0, 'values_status': 'values_populated', 'selection_allowed': True, 'final_test_used_for_selection': False, 'exact_real_multi_intent_row_count': 2250, 'coverage_computed': True, 'tau_predeclared': False, 'freeze_supported': False}
- `coverage_at_Kmax`: {'train': {'sample_count': 3338, 'covered_count': 3338, 'overflow_count': 0, 'coverage_at_kmax': 1.0, 'overflow_rate': 0.0, 'values_status': 'values_populated'}, 'dev': {'sample_count': 572, 'covered_count': 572, 'overflow_count': 0, 'coverage_at_kmax': 1.0, 'overflow_rate': 0.0, 'values_status': 'values_populated'}, 'test': {'sample_count': 573, 'covered_count': 573, 'overflow_count': 0, 'coverage_at_kmax': 1.0, 'overflow_rate': 0.0, 'values_status': 'values_populated'}}
- `missing_count_rows`: 2137
- `selection_basis_constraints`: {'train_dev_only': True, 'synthetic_allowed_for_selection': False, 'censored_counts_allowed_for_selection': False, 'exact_real_multi_intent_required': True}
- `eligibility_summary`: {'total_rows_received': 6620, 'eligible_exact_real_rows': 4483, 'eligible_train_dev_rows': 3910, 'eligible_train_dev_multi_intent_rows': 2250, 'excluded_rows_by_reason': {'censored_count_excluded': 2137}}
- `synthetic_distribution_usage`: {'synthetic_rows': 0, 'reported_separately': True, 'can_alone_justify_Kmax': False}
- `overflow_policy`: {'k_gt_Kmax_truncated': False, 'k_gt_Kmax_evaluated_as': 'overflow_or_out_of_scope', 'overflow_rate_reported_on_every_split': True}
- `forbidden`: {'final_test_attribution_scores_for_kmax_selection': True, 'message_utility_scores_for_kmax_selection': True, 'synthetic_cardinality_distribution_alone': True}
