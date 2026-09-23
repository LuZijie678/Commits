# 当前 Step1 Source Pool

这里是当前推荐给 Step2 的稳定单意图交付层。

## 主文件

- `conservative_atomic_sources.csv`
- `source_pool_metadata.json`
- `strategy_comparison.json`
- `audit_precision_report.json`
- `proxy_gap_analysis.json`

## 当前事实

- `final_source_count = 5099`
- `selection_strategy = model_rule_refilter`
- `Tier-A audit precision = 288/300 = 0.9600`
- `model_rule_refilter` 在命中到的 Tier-A 审计子样本上为 `203/207 = 0.9807`

## 来源

来自正式 Step1 run：

- `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z`

Markdown 摘要文件已清理；如需权威结果，请直接读取这里的 JSON 与 CSV。
