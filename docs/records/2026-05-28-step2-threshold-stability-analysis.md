# 2026-05-28 Step2 阈值校准与多轮稳定性分析记录

## 1. 背景

在两轮 `feat+fix repair / final_strong_compress` prompt 试验之后，已经确认：

1. 局部样本可以被救回；
2. 但整轮 `20` 条小批次正式产率并没有提升，反而从原始 `legacy_guarded` 的 `15/20` 下降到 `14/20` 和 `13/20`；
3. 问题已经不适合继续优先从单条 prompt 修补切入，而应该先拆成：
   - 阈值校准是否对小样本过敏；
   - 多次重复运行的状态分层是否稳定。

因此，本轮先做两件事：

1. 把实验版 prompt 改动收口为显式开关，默认关闭；
2. 基于现有三轮真实 run，做一次离线阈值漂移和状态波动分析。

## 2. 代码收口

当前 Step2 代码已经改为：

- 默认正式基线：
  - `selection_quality_priority = legacy_guarded`
  - `feat_fix_repair_guidance_mode = none`
  - `enable_final_strong_path_tail_compress = false`
- 实验版仅通过显式参数开启：
  - `--feat-fix-repair-guidance-mode collapse_risk`
  - `--feat-fix-repair-guidance-mode always`
  - `--enable-final-strong-path-tail-compress`

对应配置文件：

- [step2_runtime_config.local.json](/Users/lifulin/Downloads/Commits/code/step2/configs/step2_runtime_config.local.json)
- [step2_runtime_config.template.json](/Users/lifulin/Downloads/Commits/code/step2/configs/step2_runtime_config.template.json)

这意味着：

1. 当前仓库里的正式默认口径已经重新对齐回原始 `legacy_guarded`；
2. 两轮 prompt 试验结果仍保留在代码与产物中，但不会再混入默认正式运行。

## 3. 稳定性分析工具

新增离线分析脚本：

- [analyze_message_threshold_stability.py](/Users/lifulin/Downloads/Commits/code/step2/code/analyze_message_threshold_stability.py)

作用：

1. 读取多个 run 目录中的：
   - `run_metadata.json`
   - `synthetic_samples.jsonl`
2. 汇总每轮：
   - `t_reject / t_pass`
   - `pass / fallback / reject`
   - `step3_ready_count`
   - 近阈值样本数量
3. 计算：
   - 阈值漂移范围
   - 相对基线的样本状态变化数量
   - 哪些样本在多轮 run 中状态不稳定

测试：

- [test_analyze_message_threshold_stability.py](/Users/lifulin/Downloads/Commits/code/step2/tests/test_analyze_message_threshold_stability.py)

## 4. 本轮分析输入

基于以下三轮真实 run：

1. 原始基线：
   - [step2_compare20_legacy_guarded_20260528T121100Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_compare20_legacy_guarded_20260528T121100Z)
2. 第一轮失败对照：
   - [step2_compare20_legacy_guarded_featfixrepair_20260528T040945Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_compare20_legacy_guarded_featfixrepair_20260528T040945Z)
3. 第二轮失败对照：
   - [step2_compare20_legacy_guarded_featfixrepair_narrow_20260528T062730Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_compare20_legacy_guarded_featfixrepair_narrow_20260528T062730Z)

分析产物输出到：

- [step2_message_stability_20260528T063942Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_message_stability_20260528T063942Z)

核心文件：

- [threshold_stability_report.md](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_message_stability_20260528T063942Z/threshold_stability_report.md)
- [threshold_stability_report.json](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_message_stability_20260528T063942Z/threshold_stability_report.json)

## 5. 真实结果

### 5.1 三轮整体对比

| run | step3_ready | pass | fallback | reject | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|
| legacy_guarded | 15 | 7 | 8 | 4 | 0.757990 | 0.791892 |
| featfixrepair | 14 | 6 | 8 | 5 | 0.762377 | 0.796252 |
| featfixrepair_narrow | 13 | 3 | 10 | 7 | 0.770599 | 0.802706 |

### 5.2 阈值漂移

- `t_reject` 范围：`0.757990 -> 0.770599`
- `t_reject span = 0.012609`
- `t_pass` 范围：`0.791892 -> 0.802706`
- `t_pass span = 0.010814`

这说明：

1. 在只看 `20` 条样本的小批次上，消息分层阈值本身会明显上移；
2. 阈值上移幅度已经足以把多个原本处在 `fallback/pass` 边界上的样本压到更低层；
3. 这类波动并不需要“样本文本严重变坏”才会发生。

### 5.3 状态波动

- `step3_ready span = 2`，即 `13 -> 15`
- 状态不稳定样本数：`11`

代表性不稳定样本：

1. `simple2_0002`: `fallback -> reject`
2. `simple2_0004`: `fallback -> pass`
3. `simple2_0006`: `generation_failed -> reject`
4. `simple2_0009`: `reject -> pass`
5. `simple2_0010`: `fallback -> reject`
6. `simple2_0016`: `fallback -> reject`
7. `simple2_0020`: `pass -> reject -> fallback`

这说明：

1. 这批样本里有相当一部分本来就处于近阈值带；
2. 一旦 prompt 输出、长度压缩、局部措辞发生轻微变化，就会触发状态翻转；
3. 目前 `20` 条小样本对“总体结论”的承载能力偏弱。

### 5.4 近阈值带

分析脚本按 `margin = 0.01` 统计近阈值样本，得到：

- 基线 run：
  - `near_reject = 1`
  - `near_pass = 4`
- 第一轮失败对照：
  - `near_reject = 1`
  - `near_pass = 3`
- 第二轮失败对照：
  - `near_reject = 4`
  - `near_pass = 1`

这说明第二轮失败对照的一个关键问题不是“全部样本都变差”，而是：

1. 更多样本挤在 `reject/fallback` 边界附近；
2. `pass` 高置信带明显缩小；
3. 因此最终 `step3_ready` 下降更快。

## 6. 解释

当前最重要的认识是：

1. 这两轮 prompt 修复不是完全没用；
2. 但它们主要改变的是少数样本的局部表达；
3. 真正把整轮结果拉低的，是小样本下的阈值重估和边界样本分层波动。

更直白地说：

- `simple2_0009` 被救回，是真的；
- `simple2_0006` 从完全失败推进到可生成，是真的；
- 但整轮结果仍然变差，也是真的；
- 这不是因为某一条 prompt 必然错误，而是因为当前 `20` 条规模下，阈值与边界样本非常敏感。

## 7. 当前结论

基于这次分析，当前建议确认如下：

1. 正式默认口径继续维持在原始 `legacy_guarded`，不使用两轮 prompt 修复版；
2. 后续优先级不再是继续修单条 prompt；
3. 下一步应该转向：
   - 更稳定的阈值校准方案；
   - 多次重复运行的稳定性评估；
   - 更大样本量下的正式比较。

## 8. 下一步建议

建议后续按下面顺序推进：

1. 做 `legacy_guarded` 基线的多次重复运行：
   - 只改随机种子；
   - 不改 prompt；
   - 看 `step3_ready / t_reject / t_pass` 的自然波动范围。
2. 分离“生成文本变化”和“阈值重估变化”：
   - 固定一组样本，单独比较不同阈值方法；
   - 例如 `kmeans_1d` vs 固定参考分位带。
3. 评估是否需要把 `20` 条小批次从“正式判断依据”降级为“快速诊断用小样本”，而把正式比较移到更大样本上。

补充：

- 上述第三点在随后同日的多种子诊断中已经被进一步确认；
- 对应补充记录见：
  - [2026-05-28-step2-multiseed-diagnostic.md](/Users/lifulin/Downloads/Commits/docs/records/2026-05-28-step2-multiseed-diagnostic.md)
