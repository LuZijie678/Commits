# 2026-05-28 Step2 正式基线论文主表初稿

> 历史快照：本文的“当前”“正式”指 2026 年 5 月当时的 Step2 运行判断，不代表新仓库当前全部实验已完成。当前项目状态见 [当前状态入口](../CURRENT_STATUS.md)。

## 1. 适用范围

本页用于把当前 Step2 已完成的 `6 seed` 正式基线结果整理成可直接贴入论文草稿的主表初稿。

当前对应实验设置：

- 选样策略：`legacy_guarded`
- 阈值方法：`kmeans_1d`
- 生成模型：`deepseek-v4-pro`
- thinking 口径：`disabled`
- `target_count = 100`
- seeds：`7 / 11 / 19 / 23 / 29 / 31`

数据来源：

- `code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run1/multiseed_summary.json`
- `code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run2/multiseed_summary.json`

统计说明：

- `可交付样本数` 与 `可交付产率` 使用 `6 seed` 的均值与样本标准差；
- `产率范围` 使用 `6 seed` 的最小值和最大值；
- `质量门通过率` 与 `严格交付门通过率@1.0` 按 run 级二元状态统计。
- 敏感性分析表中的 `@0.75` 定义为 `required_samples = ceil(100 * 0.75) = 75`，仅用于报告层分析，不改变正式执行默认值。

## 2. 论文主表初稿

| 配置/方法 | 种子数 | 目标数 | 可交付样本数 | 可交付产率 | 产率范围 | 质量门通过率 | 严格交付门通过率@1.0 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `legacy_guarded + kmeans_1d + deepseek-v4-pro(thinking=disabled)` | 6 | 100 | `73.3 ± 5.8` | `73.3% ± 5.8%` | `67-81` | `6/6` | `0/6` | 六轮均通过 `message_gate`，但六轮均未满足严格 `100/100` 交付；当前瓶颈是自然可交付比例不足，而不是质量门整体失效。 |

## 3. 严格交付门敏感性分析表

| 配置/方法 | `min_target_ratio` | 需要样本数 | 严格交付门通过率 | 说明 |
|---|---:|---:|---:|---|
| `legacy_guarded + kmeans_1d + deepseek-v4-pro(thinking=disabled)` | `1.0` | 100 | `0/6` | 执行层默认正式口径；六轮均未满足严格 `100/100` 交付。 |
| `legacy_guarded + kmeans_1d + deepseek-v4-pro(thinking=disabled)` | `0.75` | 75 | `3/6` | 仅用于报告层敏感性分析；达到阈值的 seed 为 `7 / 11 / 29`，未达到阈值的 seed 为 `19 / 23 / 31`。 |

## 4. 对应原始 seed 结果

| seed | 可交付样本数 | 可交付产率 | 质量门 | 严格交付门@1.0 | 严格交付门@0.75 |
|---|---:|---:|---:|---:|---:|
| 7 | 77 | `77%` | pass | fail | pass |
| 11 | 77 | `77%` | pass | fail | pass |
| 19 | 68 | `68%` | pass | fail | fail |
| 23 | 67 | `67%` | pass | fail | fail |
| 29 | 81 | `81%` | pass | fail | pass |
| 31 | 70 | `70%` | pass | fail | fail |

## 5. 可直接用于正文的中文表述

当前 `legacy_guarded` 正式基线在 `target_count=100`、`6 seed` 设置下，平均可交付样本数为 `73.3 ± 5.8`，对应自然可交付产率为 `73.3% ± 5.8%`，范围为 `67-81`。六轮运行均通过 `message_gate`，但在默认严格交付门 `min_target_ratio=1.0` 下，`target_gate` 通过率为 `0/6`；若仅作为报告层敏感性分析把阈值降到 `0.75`，对应通过率为 `3/6`。这说明当前主瓶颈不是质量门失效，而是在严格 `100/100` one-shot 交付目标下，自然可交付比例仍然不足；即便放宽到 `75/100`，当前基线也只在一半 seed 上达到交付阈值。

## 6. 使用注意

1. 这张表适合放在论文主结果表中，前提是表下注明 `target_gate` 是严格交付门，而不是质量门。
2. 不建议把 `pass / fallback / reject`、`coverage`、`faithfulness`、`few-shot failed rate` 等诊断指标塞进主表；这些更适合放附表或正文分析段。
3. `@0.75` 只能作为报告层敏感性分析口径，不能回写成当前正式执行默认值。
4. 如果后续加入新的正式 seed，必须重算均值、标准差、范围和敏感性分析通过率，不能手工只追加单行。

## 7. 2026-05-30 clean fullscale 状态更新

代理入口修复后已经新起一轮 clean formal fullscale：

- 输出根：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/`
- 计划规模：`27901` selected pairs，`280` shards
- source coverage：`4658 / 5099 = 91.35%`
- 收尾状态：`processed_shard_count = 280 / 280`
- 成功分片：`280 / 280`
- 失败分片：`0 / 280`
- 成功分片产出：`19137 / 27901 = 68.59%` step3-ready
- 全计划交付覆盖：`19137 / 27901 = 68.59%`

这轮已经可写入论文或实验记录作为当前 fullscale 口径，但需要与第 2 节的 `6 seed target_count=100` 多种子基线区分用途：前者反映全量合成产率，后者反映小规模多种子稳定性。

| 配置/方法 | 计划目标 | 成功分片 | 失败分片 | 可交付样本数 | 可交付产率 | 全计划交付覆盖 | 论文状态 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `post-proxy clean formal fullscale + legacy_guarded + kmeans_1d + deepseek-v4-pro(thinking=disabled)` | 27901 | `280/280` | `0/280` | `19137/27901` | `68.59%` | `68.59%` | 当前正式结果 | 最终 aggregate 与 runtime_state 已对齐，可作为当前 Step2 fullscale 正式口径。 |

正式结果数据文件位置：

- [fullscale_summary.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json)
- [runtime_state.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json)
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）

主表如果强调多种子稳定性，仍建议保留第 2 节的 `6 seed target_count=100` 基线结果作为主行；如果强调全量合成覆盖，则应增加这条 fullscale 行并明确它与多 seed 基线衡量的是不同层面的现象。
