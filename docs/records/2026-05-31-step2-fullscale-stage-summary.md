# 2026-05-31 Step2 fullscale 阶段总结

> 历史快照：本文的“当前”“正式”指 2026 年 5 月当时的 Step2 运行判断，不代表新仓库当前全部实验已完成。当前项目状态见 [当前状态入口](../CURRENT_STATUS.md)。

## 1. 阶段目标

本阶段的目标是完成一次 clean formal fullscale 的 Step2 合成，并把最终结果统一收口成可直接引用的正式实验口径。

本轮对应输出根：

- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/`

## 2. 合成过程

这次 Step2 合成以 Step1 交付的保守单意图 source pool 为输入，在 clean 代理入口下执行 fullscale shard 化生成。

整体过程可以概括为三步：

1. 规划全量 selected pairs，并切成 `280` 个 shard
2. 对每个 shard 运行 `construct_simple_two_intent.py`，完成 few-shot 检索、subject 生成、message gate 判定与 shard 级结果落盘
3. 将全部 shard 结果聚合到 aggregate 层，形成最终 fullscale summary

本轮合成的计划规模是：

- `source_pool_size = 5099`
- `selected_pair_count = 27901`
- `primary_source_coverage_count = 4658`
- `primary_uncovered_source_count = 441`
- `shard_count = 280`

## 3. 最终数据

最终 fullscale aggregate 已与 runtime_state 对齐，核心结果如下：

- `successful_shard_count = 280`
- `failed_shard_count = 0`
- `generated_count_merged = 27901`
- `step3_ready_count_merged = 19137`
- `precheck_rejected_count_merged = 1207`
- `step3_ready_rate_over_generated = 68.59%`

正式结果数据文件位置：

- [fullscale_summary.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json)
- [runtime_state.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json)
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）

这些字段的含义与来源如下：

- `successful_shard_count = 280`
  - 含义：最终被 aggregate 认定为成功完成的 shard 数量。
  - 来源：`aggregate/fullscale_summary.json` 的 `successful_shard_count`。
  - 统计口径：对所有 shard 结果中 `status in {completed, reused}` 的 shard 计数。

- `failed_shard_count = 0`
  - 含义：最终被 aggregate 认定为失败的 shard 数量。
  - 来源：`aggregate/fullscale_summary.json` 的 `failed_shard_count`。
  - 统计口径：对所有 shard 结果中 `status == failed` 的 shard 计数。

- `generated_count_merged = 27901`
  - 含义：最终聚合到 `aggregate/synthetic_samples.jsonl` 中的样本总数。
  - 来源：`aggregate/fullscale_summary.json` 的 `generated_count_merged`。
  - 统计口径：把全部成功 shard 下的 `synthetic_samples.jsonl` 逐行合并后得到的总行数。

- `step3_ready_count_merged = 19137`
  - 含义：最终聚合到 `aggregate/synthetic_samples_step3_ready.jsonl` 中的 `step3_ready` 样本总数。
  - 来源：`aggregate/fullscale_summary.json` 的 `step3_ready_count_merged`。
  - 统计口径：把全部成功 shard 下的 `synthetic_samples_step3_ready.jsonl` 逐行合并后得到的总行数。

- `precheck_rejected_count_merged = 1207`
  - 含义：在 source-pair precheck 阶段就被跳过、未进入生成阶段的样本总数。
  - 来源：`aggregate/fullscale_summary.json` 的 `precheck_rejected_count_merged`。
  - 统计口径：把全部成功 shard 下的 `synthetic_samples_precheck_rejected.jsonl` 逐行合并后得到的总行数。

- `step3_ready_rate_over_generated = 68.59%`
  - 含义：最终生成样本里，有多少比例进入了 `step3_ready`。
  - 来源：`aggregate/fullscale_summary.json` 的 `step3_ready_rate_over_generated`。
  - 计算方式：`19137 / 27901 = 0.685889`，按百分比记为 `68.59%`。

样本级状态分布：

| 指标 | 数量 | 占全体样本比例 |
|---|---:|---:|
| `generation generated` | `25900` | `92.83%` |
| `generation failed` | `794` | `2.85%` |
| `precheck skip` | `1207` | `4.33%` |
| `message pass` | `7542` | `27.03%` |
| `message fallback` | `11595` | `41.56%` |
| `message reject` | `6763` | `24.24%` |
| `step3_ready` | `19137` | `68.59%` |

这些样本级状态字段的含义与来源如下：

- `generation generated = 25900`
  - 含义：成功生成出 synthetic subject 并进入后续 message 判定的样本数。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `generation_status == generated` 计数。

- `generation failed = 794`
  - 含义：尝试生成，但最终没有得到可用 synthetic subject 的样本数。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `generation_status == generation_failed` 计数。

- `precheck skip = 1207`
  - 含义：在 source-pair precheck 阶段就被判定跳过、未尝试生成的样本数。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `generation_status == not_attempted_precheck_skip` 计数；它与 `precheck_rejected_count_merged` 应一致。

- `message pass = 7542`
  - 含义：message gate 后被标为 `pass` 的样本数。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `message_status == pass` 计数。

- `message fallback = 11595`
  - 含义：message gate 后未达到 `pass`，但仍保留为可交付样本的数量。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `message_status == fallback` 计数。

- `message reject = 6763`
  - 含义：message gate 后被判为 `reject`、不能进入 `step3_ready` 的样本数。
  - 来源：遍历 `aggregate/synthetic_samples.jsonl` 后，对 `message_status == reject` 计数。

- `step3_ready = 19137`
  - 含义：最终进入 `step3_ready` 集合的样本数。
  - 来源：`aggregate/synthetic_samples_step3_ready.jsonl` 的总行数；也等于 `message pass + message fallback = 7542 + 11595 = 19137`。

source-pair precheck 分布：

| 状态 | 数量 | 占比 |
|---|---:|---:|
| `pass` | `9319` | `33.40%` |
| `warn` | `17375` | `62.27%` |
| `skip` | `1207` | `4.33%` |

分片级 `step3_ready` 分布：

- `min = 0`
- `p10 = 59`
- `median = 70`
- `p90 = 78`
- `max = 86`
- `mean = 68.35`

补充观察：

- `>= 75 step3_ready` 的 shard：`65`
- `>= 70 step3_ready` 的 shard：`151`
- `< 50 step3_ready` 的 shard：`12`
- 唯一 `0 step3_ready` 的 shard 是 `shard_0280`，该 shard 计划规模本身只有 `1` 个 pair

## 4. 结果解释

这次 Step2 fullscale 合成的核心结论有三点。

第一，clean formal fullscale 已经可以完整执行并收口。最终 `280/280` shard 成功，说明当前 Step2 顶层入口、few-shot 检索、subject 生成、message gate 和 aggregate 链路已经能支撑一次全量合成。

第二，当前 fullscale 的自然可交付产率稳定落在约七成附近。最终 `19137 / 27901 = 68.59%` 的 `step3_ready` 比例，和此前 `target_count=100` 多 seed 基线观察到的产率带宽是相容的，说明小规模基线与 fullscale 结果在量级上是一致的。

第三，当前主瓶颈不是“能不能跑完”，而是“最终有多少样本能进入 step3-ready”。从状态分布看，生成失败只占 `2.85%`，而更大的损失来自 message 阶段的 `reject` 与 precheck `skip`。也就是说，当前 Step2 的主要优化空间仍然在样本质量和可交付比例，而不是基础运行链路。

## 5. 当前建议口径

对外统一口径建议写成：

- Step2 clean formal fullscale 已完成，最终生成 `27901` 条样本，其中 `19137` 条为 `step3_ready`，总体产率为 `68.59%`
- 这组 fullscale aggregate 可作为当前 Step2 合成的正式结果口径
- 如果论文主表强调多种子稳定性，仍可保留 `6 seed target_count=100` 基线行；如果强调全量合成覆盖，则应同时报告本轮 fullscale 行
