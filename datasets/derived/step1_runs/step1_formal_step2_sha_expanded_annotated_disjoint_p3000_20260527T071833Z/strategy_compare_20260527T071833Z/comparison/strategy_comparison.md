# Step1 Strategy Comparison

| 指标 | rule_only | model_only | model_rule_refilter |
|---|---:|---:|---:|
| selected_count | 5166 | 7647 | 5099 |
| precision | NA | NA | NA |
| recall | NA | NA | NA |
| F1 | NA | NA | NA |
| estimated_noise_rate | NA | NA | NA |
| Tier-A audit precision | 0.980676 | 0.960000 | 0.980676 |
| candidate overlap with rule_only | 5166 | 5099 | 5099 |
| candidate overlap with model_only | 5099 | 7647 | 5099 |
| candidate overlap with model_rule_refilter | 5099 | 5099 | 5099 |

## Evaluation Metric Notes

- rule_only: `not_directly_computable_strict_disjoint`; the formal protocol keeps evaluation labels SHA-disjoint from the candidate pool, so direct precision/recall/F1 are not directly computable from evaluation.csv
- model_only: `not_directly_computable_strict_disjoint`; the formal protocol keeps evaluation labels SHA-disjoint from the candidate pool, so direct precision/recall/F1 are not directly computable from evaluation.csv
- model_rule_refilter: `not_directly_computable_strict_disjoint`; the formal protocol keeps evaluation labels SHA-disjoint from the candidate pool, so direct precision/recall/F1 are not directly computable from evaluation.csv

## 模型与规则交叉计数

- model_tier_a_count: `7647`
- model_tier_a_rule_positive_count: `5099`
- model_tier_a_rule_rejected_count: `2548`
- rule_positive_model_tier_a_count: `5099`
- rule_positive_model_not_a_count: `67`

## Proxy 角色说明

- proxy_role: `recall_prefilter_only`
- proxy_to_full_diff_agreement: `0.28963210702341136`
- proxy_a_to_full_diff_c_rate: `None`
- proxy_high_confidence_warning: `True`

