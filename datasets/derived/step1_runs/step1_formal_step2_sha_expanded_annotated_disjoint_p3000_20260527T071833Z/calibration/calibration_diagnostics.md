# Calibration Diagnostics

- Primary artifact: `step1_atomic_gbdt_isotonic_v1`
- Proxy artifact: `step1_message_only_platt_v1`

## Primary Model

- Weak-label source: `independent_rule_protocol_v1`
- Tier-A positive recall: `0.770949720670391`
- ECE: `0.026646`
- Rule-only recall: `0.7430167597765364`
- Model recall: `0.770949720670391`

### Per-threshold Coverage

| Metric | Value |
|---|---|
| Tier-A predicted count | `138` |
| Tier-B-or-higher predicted count | `138` |
| Tier-A positive recall | `0.770949720670391` |
| Tier-B-or-higher positive recall | `0.770949720670391` |

### Rule-only vs Model

- Rule-only recall: `0.7430167597765364`
- Model recall: `0.770949720670391`
- Takeaway: Model Tier-A recall exceeds rule-only recall by `0.027933`.

### ECE Bin Table

| Bin | Range | Count | Avg confidence | Empirical accuracy | Absolute gap |
|---|---|---:|---:|---:|---:|
| `0` | `[0.0, 0.1]` | `0` | `None` | `None` | `None` |
| `1` | `[0.1, 0.2]` | `0` | `None` | `None` | `None` |
| `2` | `[0.2, 0.3]` | `58` | `0.210526` | `0.155172` | `0.055354` |
| `3` | `[0.3, 0.4]` | `0` | `None` | `None` | `None` |
| `4` | `[0.4, 0.5]` | `0` | `None` | `None` | `None` |
| `5` | `[0.5, 0.6]` | `0` | `None` | `None` | `None` |
| `6` | `[0.6, 0.7]` | `0` | `None` | `None` | `None` |
| `7` | `[0.7, 0.8]` | `42` | `0.736728` | `0.738095` | `0.001367` |
| `8` | `[0.8, 0.9]` | `1` | `0.834592` | `1.0` | `0.165408` |
| `9` | `[0.9, 1.0]` | `239` | `0.761234` | `0.748954` | `0.01228` |

- MCE: `0.165408`

## Proxy Model

- Raw Brier: `0.4152590649284389`
- Calibrated Brier: `0.13008308296529467`
- Raw log-loss: `1.0855402266864065`
- Calibrated log-loss: `0.42200874824190077`

## Annotation Agreement

- Status: `available`
- Shared overlap rows: `76`
- Raw agreement: `1.0`
- Cohen's kappa: `1.0`
- Adjudication coverage: `0.0`

### Disagreement Summary

- `0->0`: 1
- `1->1`: 75
