# 2026-05-27 当前项目状态

> 历史快照：本文的“当前”“正式”指 2026 年 5 月当时的 Step2 运行判断，不代表新仓库当前全部实验已完成。当前项目状态见 [当前状态入口](../CURRENT_STATUS.md)。

这份文档是当前单仓库状态总记录，用来取代分散的联通性测试、few-shot 上限分析和默认入口切换碎片记录。

## 1. 单仓库状态

当前仓库已经完成 Step1、Step2、datasets、archive、docs 的顶层统一管理。

当前推荐入口：

- Step1：`code/step1/`
- Step2：`code/step2/`
- 正式数据：`datasets/`
- 当前文档入口：`README.md`

## 2. Step1 当前状态

当前 Step1 正式交付层：

- `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`

关键事实：

- 正式 run 来源：`datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z`
- 最终保守单意图原料池：`5099` 条
- 推荐策略：`model_rule_refilter`
- A 层人工审计：`288/300 = 0.9600`
- 保守交付池命中的审计子样本精度：`203/207 = 0.9807`

当前结论：

- Step1 已达到向 Step2 稳定供给高精度单意图原料的状态。
- `message-only proxy` 不再被视为最终高置信过滤器。

## 3. Step1 -> Step2 联通状态

当前桥接主路径：

```text
datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv
  -> datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv
```

当前桥接结果：

- `step2_source_candidates_from_step1.csv = 5099` 条
- 作为 Step2 默认 source 输入使用

这意味着当前阻塞点已经不在 Step1 与 Step2 的数据格式兼容性。

## 4. Step2 当前状态

当前默认 few-shot 正式交付物：

- `datasets/step2/delivery/current/fewshot_pool.db`
- `datasets/step2/delivery/current/build_manifest.json`

关键事实：

- 来源资产：`datasets/m_verified/canonical/usable_m_with_real_diff.csv`
- canonical `M` 总数：`2142`
- 当前正式 few-shot 规模：`130`
- 当前 few-shot 状态：`audit_pass=true`、`retrieval_probe_ok=true`
- Step2 默认配置已显式指向这份正式资产
- `delivery/current/preflight_report.json` 已同步到最新一次针对 `5099` 条 source 的 formal preflight 包装结果，当前状态为通过

当前结论：

- Step2 默认入口已经切到当前正式 few-shot 交付物。
- 旧 preview/fallback few-shot 不再是默认实验入口。
- few-shot 资产本身可用，而且当前已经具备“latest successful preflight 证据”。
- `2026-05-27` 早些时候确实出现过 `http_402 / Insufficient Balance`，但那属于较早的一次失败尝试，不是 latest preflight 状态。
- Step2 生成器默认口径已经进一步调整为
  `deepseek-v4-pro + thinking=disabled + 128`；详见
  `docs/records/2026-05-27-step2-generator-diagnosis-and-fix.md`
- 2026-05-30 又进一步定位并修复了一个运行入口问题：
  Python 进程默认未继承本机系统代理，导致真实调用 DeepSeek 时出现
  `request_error / gaierror(8)`；当前顶层 Step2 入口已补上系统代理自动注入。

### 4.0 当前字段口径

这里的几个关键数值统一按下面理解：

- `canonical M 总数`：`datasets/m_verified/canonical/usable_m_with_real_diff.csv` 的正式行数，表示已经过 `llm_label == M` 和真实 `diff --git` 双重门槛的 `M` 正例池规模。
- `current few-shot 规模`：`datasets/step2/delivery/current/fewshot_pool.db` 里的正式 few-shot 条数，只反映 Step2 交付层当前可用示例数，不等于上游 `M` 总量。
- `combined labels`：联合标签库总行数，表示 `gitlog_all_pilot_labels_combined.csv` 已汇总的样本总数，覆盖所有 `A/B/M/U` 标签，不代表正式 canonical 条数。
- `hard_b usable_real_diff_count`：`datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv` 的正式条数，表示已满足 `B`、排除与 `M` 重叠并拥有真实 `diff --git` 的 `hard_b` 池规模。
- `need_full_diff_rows`：`hard_b` 侧还需要补完整 diff 的候选数；为 `0` 时表示当前没有待恢复 backlog。

## 4.1 2026-05-28 50 条级验证批次补充

在保持当前默认生成配置不变的前提下，本轮已真实跑完一轮 `50` 条级 Step2 验证批次：

- 运行目录：`code/step2/outputs/step2_validation50_v4_pro_disabled_20260528T002957Z/`
- 配置口径：`deepseek-v4-pro + thinking=disabled + 128`
- 输入 source pool：`5099` 条
- sampled candidate：`50`
- generation attempted：`47`
- pass / fallback / reject：`20 / 15 / 11`
- step3_ready：`35`
- final usable：`35`

这轮结果说明：

1. 当前 `v4-pro + thinking=disabled` 路线已经不是“生成器正文为空”的旧问题，生成、few-shot、离线评分、message gate 都能正常运行。
2. 这轮最终返回失败，是因为严格数量闸门要求 `50/50` 全部达到 `step3_ready`，而真实结果只有 `35/50`。
3. 因此，当前 Step2 的主要问题已经从“链路跑不通”转为“严格协议下的可用样本产率不足”。
4. 这轮不能被表述成 formal 批次通过，但它可以作为“当前默认配置已恢复真实可运行性”的直接证据。

## 4.2 2026-05-27 新 current 审核补充

围绕新的 Step2 `current` source，本轮额外核到以下事实：

- 当前 bridge source 为 `5099` 条，`82` 个 repo
- 当前 latest formal preflight 已刷新到：
  `datasets/step2/delivery/current/preflight_20260527T103534Z/preflight_report.json`
- 这次 latest preflight 中：
  - `input_data=1`
  - `fewshot=1`
  - `formal_assets=1`
  - `scoring=1`
  - `generator=1`
- 其对应包装结果即当前 `datasets/step2/delivery/current/preflight_report.json`
- 同日较早的一次失败 preflight 为：
  `datasets/step2/delivery/current/preflight_20260527T083852Z/preflight_report.json`
  失败原因是当时远程接口返回 `http_402 / Insufficient Balance`

这意味着：

- 新 `current` 的数据入口与 formal 资产链路已经通过 latest preflight
- 当前 latest preflight 不再以供应侧余额作为 blocker
- 但这仍然只能说明“formal preflight 已通过”，不能自动推出“大规模正式生成结果已经充分验证”

## 4.3 2026-05-28 条件性长度放宽复核

围绕 Step2 当前的 subject 长度问题，本轮已按更保守的正式口径落地并实跑：

- 基线长度限制保持 `62`
- 保留 `final_strong_compress`
- 只对“repair 后仍因超长失败”的样本做条件性放宽
- 放宽上限取真实单意图 subject 长度分布的 `P95=68`

对应真实运行目录：

- `code/step2/outputs/step2_validation50_v4_pro_disabled_condrelax_20260528T022131Z/`

真实结果：

- sampled candidate：`50`
- generation attempted：`47`
- pass / fallback / reject：`7 / 29 / 10`
- step3_ready：`36`
- final usable：`36`
- target gate：`failed`

需要特别说明：

1. 这轮相比上一轮 `35/50`，只把 `step3_ready` 提高到 `36/50`，增益很小。
2. 真正依赖 `63-68` 条件放宽而被保留的样本只有 `1` 条。
3. 因此当前主瓶颈不是“62 太紧”，而是大量样本仍停留在 `fallback`，说明消息质量综合得分还不够稳定。
4. 本轮后又修复了一个长度上限记账边界问题，但逐样本复核后，未发现这轮 `36/50` 结果被该问题实质污染。

结论上，当前可对外统一表述为：

- `deepseek-v4-pro + thinking=disabled` 的 Step2 主链路已恢复真实可运行性；
- `62 + final_strong_compress + 条件性放宽` 已正确实现；
- 但当前 formal 口径下的核心瓶颈仍是可用样本产率不足，而不是长度限制本身。

## 4.4 2026-05-30 代理入口修复与 fullscale 汇总口径修正

本轮新增结论：

1. DeepSeek 服务本身并未不可用；
2. 问题在于：
   - `curl` 能通过本机系统代理访问外网；
   - 但 Python `urllib/socket` 默认没有继承这条代理；
3. 通过顶层入口自动注入 `HTTP_PROXY/HTTPS_PROXY` 后：
   - Step2 formal preflight 已重新通过；
   - 1 shard 真实 smoke 已恢复非零生成成功；
4. 因此，当前 Step2 的真实 API 链路已恢复可运行。

与此同时，需要对既有 fullscale 输出口径做修正：

- `code/step2/outputs/step2_fullscale_formal_20260529T1/aggregate/fullscale_summary.json`
  当前确实已经收口为：
  - `280/280` 成功
  - `0` 失败
  - `generated_count_merged = 27901`
  - `step3_ready_count_merged = 4173`

但进一步拆分后发现：

- `58` 个 `reused` 分片贡献了全部当前 `4173` 条 `step3_ready`
- 之后恢复补跑完成的 `222` 个 `completed` 分片全部是：
  - `step3_ready_count = 0`

因此，这份 fullscale aggregate 的正确解释不是：

- “代理修复后已得到新的 clean formal fullscale 主结果”

而是：

- “运行完成性问题已经修复，fullscale 可以完整收口；
  但当前这份 aggregate 混合了早先有效分片和后续错误网络口径下的零产出分片，
  不能直接作为新的正式主结果。”

当前最稳妥的后续路径是：

- 保留这次代理入口修复与恢复证据；
- 如需正式主结果，必须在修复后的干净代理口径下重新重跑 fullscale。

## 4.5 2026-05-30 clean fullscale 收尾状态

代理入口修复后已新起一轮 clean formal fullscale：

- 输出根：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/`
- 计划规模：`27901` selected pairs，`280` shards
- source coverage：`4658 / 5099 = 91.35%`
- 最终状态：`processed_shard_count = 280 / 280`
- 成功分片：`280 / 280`
- 失败分片：`0 / 280`
- 成功分片产出：`19137 / 27901 = 68.59%` step3-ready
- 全计划交付覆盖：`19137 / 27901 = 68.59%`

这轮的正确解释是：

- clean 入口已经能够真实生成非零 `step3_ready` 样本；
- 成功分片的主体产率与此前 `target_count=100` 多 seed 基线大体一致；
- clean run 当前已经完整收口，可直接作为正式 fullscale 结果口径。

当前最稳妥的状态表述应更新为：

- `6 seed target_count=100` 基线仍然是重要的多种子稳定性参考；
- `step2_fullscale_formal_proxyclean_20260530T030311Z` 已完成完整收口，可作为当前 clean formal fullscale 正式结果口径；
- 若写论文 fullscale 行，应引用最终 aggregate 数字而不是中途失败阶段的局部统计。

正式结果数据文件位置：

- [fullscale_summary.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json)
- [runtime_state.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json)
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl`（旧/新本地目录均有，仍未纳入 GitHub）

## 4.6 2026-05-31 M / hard_b 资产更新

围绕 `M` 与 `hard_b` 的上游资产，本轮又追加完成了一次真实的 discovery -> label -> ingest 收口：

- 新增 ingest 批次：
  - `ingest_round0114_20260531`
  - `ingest_round0115_0116_20260531`
  - `ingest_round0117_20260531`
- 当前 combined labels：
  `archive/datasets/m_verified/workspace/label_snapshots/gitlog_all_pilot_labels_combined.csv = 10512`
- 当前 formal `M`：
  `datasets/m_verified/canonical/usable_m_with_real_diff.csv = 2142`
- 当前 formal `hard_b`：
  `datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv = 483`

同时需要统一更新运行口径：

- `M` discovery 现已改为更宽的自动 query 集，不再继续重启旧的单一 query 方案；
- `hard_b` recovery 当前默认是按需 one-shot 运行，不再把常驻 daemon 作为默认做法；
- 本轮 label / ingest 已确认使用 DeepSeek 接口跑通：
  `https://api.deepseek.com/chat/completions` + `deepseek-v4-flash`。

## 5. 当前有效数据资产

- Step1 正式数据根：`datasets/step1/`
- Step2 few-shot 正式 `M` 来源：`datasets/m_verified/`
- hard-B 资产：`datasets/hard_b/`
- 跨阶段交付层：`datasets/derived/`

当前不再作为默认主路径：

- `code/step1/data/`
- `code/step2/data/`
- `archive/step2_preview_source/.../annotation_round3_atomicity_spectrum_3000_minimal.csv`

## 6. 当前仍未完成的部分

当前仍需继续推进的不是入口整理，而是实验本身的后续验证：

- Step2 真实 API 生成质量
- 与冻结 Step3 eval/test 的最终 repo/SHA 泄露审计
- 更多人工审计和更多规模实验
- 更强的最终模型与论文级对照实验

## 7. 已合并进本记录的旧文档主题

这份记录已经吸收了以下旧记录的核心结论：

- Step1 -> Step2 联通性测试
- Step2 few-shot 候选上限分析的历史结论与其后续失效原因
- Step2 默认入口切换到正式 few-shot 资产的状态变更

需要看更细的单阶段细节时，再分别查看：

- `code/step1/docs/2026-05-26-step1-正式结果记录.md`
- `code/step2/README.md`
- `datasets/step2/README.md`
