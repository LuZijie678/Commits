# Proxy Gap Analysis

- Selection count: `12000`
- Resolved count: `12000`
- Audit target (`Tier-B` / Validate Mid Band): `300`
- Message-only proxy AUC: `0.9539007092198581`
- Full-diff primary AUC: `0.8191489361702128`
- Message-only proxy Brier: `0.09212123451787596`
- Full-diff primary Brier: `0.22192024251293582`
- Message-only proxy log-loss: `0.3369870437637489`
- Full-diff primary log-loss: `0.6014481658366431`
- Tier consistency: `0.28963210702341136`
- Missing-tier policy: `missing_as_unknown`
- Unknown rate: `0.0033333333333333335`
- Downgrade rate (`message_only A -> full_diff C`): `None`
- Expected Tier-B yield from reference table: `0.0`
- Conservative Tier-B lower bound (Wilson-based): `0.0`
- Observed full-diff Tier-B yield: `1`
- Observed full-diff tier counts: `{'C': 4317, 'A': 7642, 'UNKNOWN': 40, 'B': 1}`

## Interpretation

- Classification: `usable_with_risk`
- Reason: Proxy quality is mixed; message-only should stay subordinate to full-diff.
- Paper sentence: The message-only proxy is usable for broad prefiltering but remains subordinate to the full-diff primary model.
- Policy note: Primary proxy-gap statistics use missing_as_unknown; missing_as_C is reported only as a sensitivity analysis.
- This report keeps the static pipeline unchanged and quantifies the proxy gap between message-only selection-side signals and post-enrich full-diff validate tiers.
- Main conversion statistics use `missing_as_unknown`; `missing_as_C` is reported only as sensitivity analysis.
- `expected_target_tier_yield` and `conservative_target_tier_lower_bound` come from the annotated reference table grouped by `type x message_only_probability_band`.
- `observed_tier_b_yield` is the realized full-diff Tier-B count in this run.
