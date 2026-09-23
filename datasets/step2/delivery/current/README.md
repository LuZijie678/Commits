# Formal-ready Few-shot Delivery

## Artifacts
- fewshot_pool.db: `datasets/step2/delivery/current/fewshot_pool.db`
- build_manifest.json: `datasets/step2/delivery/current/build_manifest.json`
- fewshot_audit.json: `datasets/step2/delivery/current/fewshot_audit.json`
- preflight_report.json: `datasets/step2/delivery/current/preflight_report.json`
- selection_summary.json: `datasets/step2/delivery/current/selection_summary.json`

## Summary
- selected_count: `130`
- audit_pass: `True`
- retrieval_probe_ok: `True`
- preflight_attempted: `True`
- preflight_passed: `True`

## Notes
- 本交付使用 canonical M-only 数据源。
- repo+sha 去泄露对象是当前 Step2 正式 source CSV。
- Step3 eval/test 泄露审计仍待冻结资产后补做。
- `current/` 只保留最新一次 preflight 证据层。
- 更早的 preflight 子目录已归档到 `archive/datasets/step2/current_delivery_preflight_history/`。
