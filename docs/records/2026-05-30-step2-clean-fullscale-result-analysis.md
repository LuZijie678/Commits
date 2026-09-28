# 2026-05-30 Step2 clean formal fullscale 结果分析

> 历史快照：本文的“当前”“正式”指 2026 年 5 月当时的 Step2 运行判断，不代表新仓库当前全部实验已完成。当前项目状态见 [当前状态入口](../CURRENT_STATUS.md)。

## 1. 本轮输出根

本轮是在代理入口修复后新起的 clean formal fullscale：

- 输出根：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/`
- 计划清单：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/plan/selected_pairs_primary_manifest.json`
- 运行状态：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json`
- 汇总结果：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json`

正式结果数据文件位置：

- [fullscale_summary.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json)
- [runtime_state.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json)
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）

这轮不复用旧的 `step2_fullscale_formal_20260529T1` 作为主结果。

## 2. 计划规模

计划阶段结果：

- source pool size：`5099`
- pool repo count：`82`
- selected pair count：`27901`
- source coverage：`4658 / 5099 = 91.35%`
- uncovered source：`441 / 5099 = 8.65%`
- shard size：`100`
- shard count：`280`

未覆盖 source 的主要原因：

- `411` 条没有可用 eligible diff pair
- `30` 条被 `legacy_guarded` 过滤

## 3. 收尾状态

`runtime_state.json` 的最终状态：

- `processed_shard_count = 280 / 280`
- `running_shards = []`
- `pending_shards = []`
- `completed_shard_count = 51`
- `failed_shard_count = 229`
- `generated_count_so_far = 5100`
- `step3_ready_count_so_far = 3534`

因此，本轮已经收尾，但不是健康的 fullscale 完成。

## 4. 成功分片质量

成功完成的 `51` 个分片合计：

- generated samples：`5100`
- step3-ready samples：`3534`
- step3-ready rate over generated（当时局部统计）：`3534 / 5100 = 69.29%`
- precheck rejected samples：`114`

样本级状态拆分：

| 状态 | 数量 |
|---|---:|
| generation generated | `4713` |
| generation failed | `273` |
| not attempted by precheck skip | `114` |
| message pass | `1439` |
| message fallback | `2095` |
| message reject | `1179` |

其中 `message pass + fallback = 3534`，与 `step3_ready` 计数一致。

成功分片的 `step3_ready_count` 分布：

- min：`1`
- p10：`62`
- median：`71`
- mean：`69.29`
- max：`86`

低值 outlier：

- `shard_0151 = 1 / 100`
- `shard_0011 = 27 / 100`

除 outlier 外，成功分片的主体产率仍大体落在此前 `target_count=100` 多 seed 基线的自然区间附近。

## 5. 失败分片原因

失败分片合计 `229` 个，按归一化原因分组：

| 失败原因 | 分片数 |
|---|---:|
| `http_402_insufficient_balance` | `96` |
| `[Errno 5] Input/output error` | `128` |
| `api_ping_request_error` | `5` |

其中 `http_402_insufficient_balance` 是明确的供应侧余额/计费阻断信号。`[Errno 5] Input/output error` 集中出现在同一轮 worker 后续分片中，属于运行环境/进程侧失败，不能解释为模型质量或 prompt 质量问题。

## 6. 论文口径

在缺失 shard 结果文件补回并重新聚合后，这轮 clean fullscale 的最终口径应更新为：

1. `processed_shard_count = 280 / 280`，且 `successful_shard_count = 280`；
2. `generated_count_merged = 27901`；
3. `step3_ready_count_merged = 19137`；
4. `step3_ready_rate_over_generated = 68.59%`；
5. `precheck_rejected_count_merged = 1207`。

因此，论文或阶段总结里应把这轮写为：

- `post-proxy clean formal fullscale`
- 状态：`final aggregate recovered`
- 可报告全量结果：`19137 / 27901 = 68.59%`
- 可直接用于后续 label / ingest 与 fullscale 口径更新

## 7. 后续动作

下一步不是继续引用这轮作为主结果，而是：

1. 先恢复 DeepSeek 余额/计费可用性；
2. 确认 `[Errno 5] Input/output error` 不再由当前运行环境复现；
3. 用同一个 clean 输出根或新的 clean 输出根继续 `--resume`；
4. 只有当 failed shard 归零或被完整补跑后，再更新论文主结果表。
