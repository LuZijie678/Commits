> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# 2026-06-19 MICA Implementation Interface Completion

## 1. Scope

本轮没有运行任何实验。工作仅限于实现层连接件补全：

- Stage 1 prediction adapter
- unified run manifest / safety guard helpers
- data asset registry template
- split boundary guards
- config validation utilities
- lightweight report writer
- baseline registry

## 2. What Was Explicitly Not Run

以下内容本轮都没有执行：

- Stage 1 candidate validation
- Stage 2 calibration training
- Stage 3 alignment calibration training
- Stage 4 renderer training
- RealDomainBinary eval
- M-final-test eval
- anti-shortcut actual model run
- real prediction -> plan -> renderer smoke on runtime data

## 3. Interface Closure Added

### Stage 1 prediction adapter

新增 adapter 用于把未来 Stage 1 prediction 输出适配到：

- `AttributionPrediction`
- `EditUnitRecord`
- downstream `StructuredIntentPlan` builder 所需输入

并保留 degraded diagnostics，而不是 silent guess。

### Unified run manifest / guards

新增统一 helper，给 dry-run / smoke / audit 类 runner 提供一致的：

- `training_enabled=false`
- `official_validation_executed=false`
- `stage2/3/4_training_enabled=false`
- `thresholds_applied_to_pass_fail=false`
- advisor approval guard

### Data asset registry / split guards

新增 template registry 和 final-test protection helper，用于后续正式实验前填充真实数据资产位置，同时继续隔离：

- `M-final-test`
- `hard_b-test`
- final eval only assets

### Config validation

新增 Stage 2/3/4 和 eval spec validator，确保关键 guard 没有被静默删除。

### Reporting utilities

新增轻量 JSON/Markdown report writer，只写显式路径，不默认写 `outputs/`。

### Baseline registry

把 deterministic diagnostic baselines 与 pending baselines 明确登记，避免 placeholder 被误读成已完成实验。

## 4. Current Scientific Status

本轮没有新增任何 Stage 1/2/3/4 实验结论。

仍然成立的约束：

1. Stage 2/3/4 训练入口仍需要 advisor approval
2. `M-final-test` / `hard_b-test` 仍受保护
3. renderer 仍不能更新 attribution
4. unresolved advisor decisions 仍未写死为正式 scientific conclusion

## 5. Next Practical Requirement Before Real Runs

真正开始后续实验前，仍需先完成：

1. asset registry 实际路径填写
2. Stage 1 prediction/export schema 对齐
3. manifest / split compatibility re-check
4. advisor approval / unlock 条件确认
