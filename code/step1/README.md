# Step1

Step1 负责从大规模 commit 候选中挖掘高精度、低噪声的单意图 source pool，供 Step2 使用。

## 目标

Step1 的目标是高精度 source mining，而不是证明模型必须全面优于规则。

当前推荐策略是：

```text
full-diff calibrated model Tier-A
  + independent rule positive
  -> model_rule_refilter
  -> conservative_atomic_sources.csv
```

## 当前正式输入

- 标注集：`../../datasets/step1/canonical/annotated_dataset.csv`
- 正式候选池：`../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv`
- 本地补全元数据：`../../datasets/step1/runtime_support/resolved_metadata.csv`

`code/step1/data/` 已退役，只保留迁移说明。

## 三种策略

- `rule_only`: 独立规则协议判正即入选
- `model_only`: `model_prob > tau_a` 即入选
- `model_rule_refilter`: 先过 `model_prob > tau_a`，再过独立规则协议

当前推荐给 Step2 的是 `model_rule_refilter`。

## 当前正式结果

当前稳定交付层位于：

- `../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`

关键事实：

- `final_source_count = 5099`
- `selection_strategy = model_rule_refilter`
- `Tier-A audit precision = 288/300 = 0.9600`
- `Wilson 95% CI = [0.9314, 0.9770]`

对应正式运行快照：

- `../../datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z`

## 只消费现成结果时

如果你现在只是想给 Step2 喂当前稳定原料池，不需要重跑 Step1，直接使用：

- `../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- `../../datasets/derived/step1_source_pool/current/source_pool_metadata.json`
- `../../datasets/derived/step1_source_pool/current/strategy_comparison.json`
- `../../datasets/derived/step1_source_pool/current/audit_precision_report.json`

## 当前主入口

Windows PowerShell 的可执行命令见 `../../docs/WINDOWS_SETUP_AND_VALIDATION.md`；其中的 Python 包装器对应下方 Bash 策略对比脚本。

```bash
python3 -m src.pipeline.run_step1 --help
```

顶层快捷入口：

```bash
make step1-help
make step1-run
```

如需直接跑策略对比：

```bash
bash scripts/run_step1_strategy_compare.sh
```

## 当前输出

- 当前正式 run 快照：`../../datasets/derived/step1_runs/`
- 当前正式交付层：`../../datasets/derived/step1_source_pool/current/`
- `outputs/`：历史或临时运行输出目录，不作为当前正式结果主路径

## 口径约束

- `message-only proxy` 只作召回前置粗筛，不是最终高置信过滤器。
- `rule re-filter` 必须基于独立规则协议，不能回到弱标签循环依赖。
- 在严格互斥 formal run 中，`evaluation split` 指标可能被明确标记为“不可直接计算”；此时以人工 audit 和策略交叉统计为主。

## 推荐阅读

- `docs/2026-05-26-step1-正式结果记录.md`
