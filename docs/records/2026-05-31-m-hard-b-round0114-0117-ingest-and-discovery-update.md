# 2026-05-31 M / hard_b round0114-0117 ingest 与 discovery 更新

这份记录用于补充 `2026-05-31` 这轮 `M` / `hard_b` 真实运行结果，并统一替换此前“等待 label / ingest”“hard_b 默认连续恢复”的旧口径。

## 1. 本轮目标

本轮主要完成三件事：

- 把 `batchcrawl_20260530T160513Z` 剩余可用数据做完 label / ingest
- 确认 DeepSeek 配置可真实跑通当前 ingest 链路
- 新起一次 discovery campaign，验证修改后的 `M` discovery 策略还能继续产出新增

## 2. DeepSeek label 配置确认

本轮先确认：

- 当前 `.llm_api_key` 不是可用的 OpenAI key；
- 直接打 OpenAI 接口会返回 `401 Unauthorized`；
- 当前可用方案是 DeepSeek 兼容接口。

实际跑通的配置：

- endpoint：`https://api.deepseek.com/chat/completions`
- model：`deepseek-v4-flash`
- key 来源：`DEEPSEEK_EXPERIMENT_API_KEY`

这意味着后续文档里不应再把这条链路写成“等待 `.llm_api_key` 就位”或“当前 label 尚未恢复”。

## 3. round0114 ingest

对应 ingest 批次：

- `ingest_round0114_20260531`

结果：

- `new_label_rows_written = 51`
- combined labels：`10354 -> 10405`
- `hard_b usable_real_diff_count: 426 -> 442`

这一批说明：

- 当前 DeepSeek 配置已经能真实完成补标；
- ingest 链路本身没有阻塞。

## 4. round0115 / round0116 ingest

剩余 `current_campaign = batchcrawl_20260530T160513Z` 中尚未处理的两轮为：

- `round0115`
- `round0116`

实际结果：

- `round0115`
  - `candidate_rows = 55`
  - `enriched_rows = 51`
  - `diff_ok = 51`
- `round0116`
  - `candidate_rows = 54`
  - `enriched_rows = 54`
  - `diff_ok = 54`

随后统一 ingest：

- 批次名：`ingest_round0115_0116_20260531`
- `new_label_rows_written = 105`

回灌前后变化：

- combined labels：`10405 -> 10510`
- `m_positive_pool_count: 2130 -> 2141`
- `hard_b usable_real_diff_count: 442 -> 483`

到这一步，`hard_b` backlog 已经清到 `0`。

## 5. 新 discovery campaign 与 round0117

在处理完 `current_campaign` 之后，本轮新触发了一次 discovery campaign：

- campaign prefix：`batchcrawl_20260531T112341Z`

实际 discovery 结果：

- `repo_count = 1`
- 新 repo：`vitest-dev/vitest`

随后完成：

- `batchcrawl_20260531T112341Z_round0117`

结果：

- `candidate_rows = 2`
- `diff_ok = 2`

对应 ingest：

- 批次名：`ingest_round0117_20260531`
- `new_label_rows_written = 2`

回灌前后变化：

- combined labels：`10510 -> 10512`
- `m_positive_pool_count: 2141 -> 2142`
- `hard_b usable_real_diff_count` 保持 `483`

这说明：

- 修改后的 discovery 口径仍能继续发现新增；
- 当前搜索空间已很薄，但不是完全扫空。

## 6. 当前最终状态

截至本轮结束：

- `datasets/m_verified/canonical/usable_m_with_real_diff.csv = 2142`
- `datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv = 483`
- `archive/datasets/m_verified/workspace/label_snapshots/gitlog_all_pilot_labels_combined.csv = 10512`
- `datasets/hard_b/manifest/usable_hard_b_with_real_diff_manifest.json`
  中：
  - `candidate_b_rows = 5588`
  - `need_full_diff_rows = 0`
  - `usable_real_diff_count = 483`
- `archive/datasets/m_verified/workspace/crawl_state_relaxed/original_batch_m_crawl_state.json`
  中：
  - `last_completed_round = batchcrawl_20260531T112341Z_round0117`
  - `current_campaign = null`
  - `current_round = null`

## 7. 字段口径

这些字段的含义统一如下：

- `combined labels`：`archive/datasets/m_verified/workspace/label_snapshots/gitlog_all_pilot_labels_combined.csv` 的总行数，表示当前已经汇总进联合标签库的全部 `(repo, sha)` 级样本数，不区分最后会不会进入 `M` 或 `hard_b`。
- `m_positive_pool_count`：`datasets/m_verified/canonical/usable_m_with_real_diff.csv` 的正式条数，表示当前已经通过 `llm_label == M` 且拥有真实 `diff --git` 的 `M` 正例池规模。
- `hard_b usable_real_diff_count`：`datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv` 的正式条数，表示当前已经通过 `llm_label == B`、排除与 `M` 重叠、并且拥有真实 `diff --git` 的 `hard_b` 正式池规模。
- `need_full_diff_rows`：`hard_b` 侧仍待补完整 diff 的候选行数；如果这个值是 `0`，就表示当前 `hard_b` backlog 已经清空。
- `candidate_b_rows`：`hard_b` 上游候选库里满足基础筛选、但未必已经具备正式 real diff 的 `B` 类候选总数。

## 8. 需要同步更新的运行口径

本轮之后，文档里的统一表述应改为：

- `M` 侧优先改 discovery 策略，不再反复重启旧 query；
- `hard_b` recovery 默认按需 one-shot 运行，除非显式传 `--daemon`；
- 当前 label / ingest 已确认可通过 DeepSeek 路线稳定执行；
- 当前 `hard_b` 不再处于“持续恢复中”，而是“backlog 为 0，等待新的上游 diff backlog 出现”。
