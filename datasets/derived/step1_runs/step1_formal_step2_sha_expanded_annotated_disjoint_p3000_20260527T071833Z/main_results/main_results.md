# Step1 Main Results

## Rule-only vs Model

| Group | Tier-A precision | Tier-A recall | Tier-A yield | Brier | ECE |
|---|---:|---:|---:|---:|---:|
| Rule-only | `1.0` | `0.7430167597765364` | `133` | `NA` | `NA` |
| Model-on-rule-labels | `1.0` | `0.770949720670391` | `138` | `0.06666506487892893` | `0.026646` |
| Feature-reduced Model | `0.9696969696969697` | `0.3575418994413408` | `66` | `0.09216285904141135` | `0.140568` |

## Gain Summary

- Tier-A precision gain (model - rule): `0.0`
- Tier-A recall gain (model - rule): `0.027932960893854664`
- Tier-A yield gain (model - rule): `5`
- Tier-A precision gain (feature-reduced - rule): `-0.030303030303030276`
- Tier-A recall gain (feature-reduced - rule): `-0.38547486033519557`
- Tier-A yield gain (feature-reduced - rule): `-67`
- Tier-A precision delta (full - feature-reduced): `0.030303030303030276`
- Tier-A recall delta (full - feature-reduced): `0.41340782122905023`
- Tier-A yield delta (full - feature-reduced): `72`
- Summary: Full model improves over rule-only, and feature ablation quantifies how much of that gain survives after removing rule-adjacent features.

## Independent Audit Precision

- Tier-A precision: `None`
- Tier-A sample count: `0`
- Tier-B precision: `None`
- Tier-B sample count: `0`

## Feature Ablation

- Removed rule-adjacent features: `['file_count', 'module_count', 'file_role_purity', 'has_single_prefix', 'multi_intent_markers', 'single_issue_link', 'doc_or_test_only', 'repo_norm_size', 'repo_norm_module_span']`
- Retained feature count: `8`

- Rule-only is reported as a tri-state selector; probabilistic reliability metrics are therefore `NA` rather than back-filled with an arbitrary score proxy.
