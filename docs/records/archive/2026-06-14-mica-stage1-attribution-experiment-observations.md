> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

> 2026-09-28 证据补注：下文五轮 sanity 的原始 `metrics.json` 在现存两处本地目录均未找到；表格为历史转录，不能逐项复核，也不作为当前正式结果或 Stage 2 放行证据。处置见 [五份 sanity 指标的证据使用决定](../../LEGACY_STAGE1_SANITY_EVIDENCE_DECISION.md)。

# 2026-06-14 MICA Stage 1 Attribution 实验现象与关键数据记录

## 1. 记录目的

本文档只记录 `experiment/mica-v3-attribution-mvp` 分支上，MICA-v3 Stage 1 attribution MVP 在本地 sanity 过程中的重要现象、关键数据和当前可成立的结论。

本文档不是计划文档，也不是最终论文叙事。它的作用是避免后续讨论时把：

- 计划里的目标
- 代码当前能做的事情
- 实验里真实出现的现象

混在一起。

## 2. 实验边界

本阶段所有运行都严格限制在：

- `Step1 atomic k=1`
- `Step2 strict/sanity synthetic k=2`
- Stage 1 当前 `L_main` 边界：
  - `1.0 * L_align`
  - `0.5 * L_count`
  - `0.5 * L_exist`

没有使用：

- `hard_b`
- `M weak`
- `M alignment`
- `RealDomainBinary`
- Stage 2 loss
- generation / retrieval / verifier
- 任何真实 API

## 3. 权威数据来源

本记录中的数值以本地 runtime 输出为准，主要来自：

- `outputs/mica_stage1_sanity_20260614T062358Z/metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_sanity_20260614T063849Z/metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_sanity_20260614T064442Z/metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_sanity_20260614T064731Z/metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_sanity_20260614T083245Z/metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- [reports/mica_stage1_attribution_debug.json](../../../reports/mica_stage1_attribution_debug.json)

补充说明：

- `reports/mica_stage1_sanity_result.*` 是轻量摘要；
- `outputs/.../metrics.json` 与 `outputs/.../stage1_sanity_manifest.json` 才是完整 runtime 结果；
- 后续复盘如需精确引用，请优先引用 `outputs/.../metrics.json`。

## 4. 数据规模与当前 sanity protocol

当前正式使用的 Stage 1 sanity protocol 为：

- `k1_train = 100`
- `k2_train = 100`
- `k1_dev = 25`
- `k2_dev = 25`
- `epochs = 3`
- `batch_size = 8`
- `device = cpu`
- `Kmax = 4`

当前大样本 runtime 数据统计：

- `atomic_candidates_total = 5099`
- `synthetic_candidates_total = 19137`
- `avg_edit_units = 3.14`
- `p50_edit_units = 2`
- `p90_edit_units = 5`
- `max_edit_units = 36`

当前 `k=2` dev 子集的进一步诊断：

- `k2_dev_sample_count = 25`
- `k2_avg_edit_unit_count = 2.8`
- `k2_singleton_intent_fraction = 0.96`

这说明当前 `synthetic_k2` dev 子集高度偏向“小样本、双意图里至少一个 intent 只有单 hunk”的结构。

## 5. 实验时间线与关键指标

下表记录 Stage 1 attribution sanity 的关键演化。

| Run | 含义 | train_loss(first->last) | count_acc | k1 over-split | k2 under-split | slot_collapse | assign_entropy | oracle F1 | predicted F1 | sanity |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `20260614T062358Z` | 初始 skeleton sanity | `1.9262 -> 1.3217` | `0.62` | `0.72` | `0.04` | `0.70` | `1.7649` | `0.6158` | `0.6158` | `inconclusive` |
| `20260614T063849Z` | decoder semantics 对齐 v3 后 | `2.2046 -> 1.4227` | `0.62` | `0.72` | `0.04` | `0.70` | `0.9677` | `0.6158` | `0.6158` | `inconclusive` |
| `20260614T064442Z` | 过强 count/existence coupling 试验 | `4.9220 -> 1.1851` | `0.54` | `0.00` | `0.92` | `0.50` | `1.0089` | `0.6158` | `0.6158` | `inconclusive` |
| `20260614T064731Z` | 调弱后的 tuned coupling | `2.0599 -> 1.1178` | `0.64` | `0.40` | `0.32` | `0.56` | `0.8301` | `0.6158` | `0.6158` | `inconclusive` |
| `20260614T083245Z` | 第三轮 attribution remodel | `2.5348 -> 1.3636` | `0.64` | `0.24` | `0.48` | `0.52` | `0.7491` | `0.6158` | `0.6158` | `inconclusive` |

## 6. 已经确认的重要现象

### 6.1 训练链路是可运行的，但 attribution 还没有学起来

从第一轮到第三轮，以下事实稳定成立：

- 前向、反向、loss 计算是通的；
- train loss 一直在下降；
- count head 至少能学到比 `0.5` 粗略多数类 baseline 更好的东西；
- 但 attribution F1 一直停在 `0.6158333333333333`。

这意味着：

- 当前 Stage 1 MVP skeleton 不是“根本训不动”；
- 当前真正卡住的是 attribution discrimination，而不是训练链路本身。

### 6.2 count / existence 调优可以显著改变 split 行为，但并不会自动带来 attribution gain

从 `20260614T062358Z` 到 `20260614T083245Z`：

- `over_split_rate_on_k1: 0.72 -> 0.24`
- `slot_collapse_rate: 0.70 -> 0.52`
- `assignment_entropy: 1.7649 -> 0.7491`

但同时：

- `oracle_k_alignment_pairwise_f1` 完全没变；
- `predicted_k_alignment_pairwise_f1` 完全没变；
- `attribution_gain = false`。

结论：

- count 行为变好，不等于 attribution 成功；
- 后续不能再把 count 提升解释成 Stage 1 attribution 已经完成。

### 6.3 过强 coupling 只是把错误从 over-splitting 翻成 under-splitting

`20260614T064442Z` 这一轮是重要反例。

它实现了：

- `k1 over-split = 0.00`

但代价是：

- `k2 under-split = 0.92`
- `count_accuracy = 0.54`

结论：

- 仅靠更强的 count/existence coupling，不会得到正确 attribution；
- 它只是把“把一个 intent 拆成两个”的错误，翻成了“把两个 intent 压成一个”的错误。

### 6.4 `oracle-k` 和 `predicted-k` 相等，不是 eval 混淆 bug，而是模型真的 collapse 了

当前 debug 结论：

- `oracle_predicted_k_exactly_equal = true`
- `oracle_predicted_k_label_diff_count = 0`
- `oracle_predicted_k_f1_diff_count = 0`

这不是因为评估代码把两者写成了一样，而是因为：

- 模型在 `k=2` 样本上几乎总是把 edit units 压到同一个 foreground slot；
- 因此就算 `gold_count = 2`，实际得到的 grouping 仍是单簇；
- 所以 `oracle-k` 和 `predicted-k` 会在数值上重合。

这是一个真实模型行为，不是评估假象。

### 6.5 file-path baseline 在当前 local sanity 上非常强

第三轮 debug 给出的 baseline 对比：

- `model_oracle_k = 0.6158`
- `all_one_cluster = 0.6158`
- `file_path_baseline = 0.96`
- `random_gold_k_mean = 0.8922`

这说明当前 local sanity 上：

- 按文件路径聚类，已经比模型强得多；
- 即使是固定 `gold_k` 的随机平衡聚类，也比模型强；
- 当前模型还没有学到比这些简单 baseline 更有价值的 attribution 结构。

这是目前最关键的负结果之一。

### 6.6 当前 pairwise observable relation 之前并没有真正进入 assignment 决策

第三轮前已经确认一个结构性问题：

- 旧的 `pairwise_bias` 只给 assignment logits 加了“按 unit 汇总后的常数项”；
- 该项对跨-slot softmax 基本不起排序作用；
- 因此它理论上很难改变最终 assignment 分配。

第三轮已改为轻量 relation-aware pooling，但从当前结果看：

- 结构接入已经真实发生；
- attribution 指标还没有因此立刻超过 baseline。

说明：

- 之前的问题不只是“模型没把 pairwise 用进去”；
- 还包括当前 Stage 1 数据本身的可分性和 collapse 行为。

### 6.7 当前 `k=2` dev 子集高度偏向 singleton intent

第三轮 debug：

- `k2_singleton_intent_fraction = 0.96`

这意味着：

- 绝大多数 `k=2` 样本里，两个 intent 中至少一个只有单 edit unit；
- 在这种数据形态下，`all-one`、`file-path`、`gold-k random` 这些 baseline 本来就会显得很强；
- attribution model 若没有很强的 evidence separation，很容易在 pairwise F1 上输给简单规则。

这不是说 Stage 1 设定错了，而是说：

- 当前 sanity 集合对“是否真的学会 attribution”提出了一个比较苛刻的信号条件；
- 解释结果时必须把这个数据形态写清楚。

### 6.8 collapse 目前仍然是 slot-level 的真实问题

当前 debug：

- `assignment_top1_slot_distribution = {1: 145}`
- `average_assignment_mass_per_slot = [0.3158, 2.5653, 0.0091, 0.0097]`
- `slot_usage_histogram = {0: 25, 1: 50}`
- `slot_pair_cosine_similarity_mean = 0.8470`

这组现象说明：

- 大部分 active edit unit 的 top-1 都落到同一个 slot；
- 有效质量主要集中在一个 foreground slot；
- 其他 slot 大多只是名义存在，没有承载稳定 attribution 角色。

这就是当前 `slot_collapse_rate` 持续偏高的实质含义。

## 7. 当前能成立的结论

目前可以成立的结论只有以下几条：

1. **Stage 1 训练链路已通。**
   - 可以稳定做 forward / backward / loss / metrics。

2. **count / existence 行为已经比最初版本更平衡。**
   - `k=1` 过拆明显下降。

3. **当前 attribution 仍未超过 trivial baseline。**
   - `model_oracle_k == all_one_cluster`。

4. **当前 attribution 明显弱于 file-path baseline 和 random-gold-k baseline。**

5. **当前 `oracle-k == predicted-k` 的主要原因是 collapse，而不是 eval bug。**

6. **当前 Stage 1 仍不能冻结为正式 protocol。**

## 8. 当前不能成立的结论

目前不能说：

- “Stage 1 attribution 已经成功”
- “pairwise evidence graph bias 已经显著起效”
- “当前模型已经比简单启发式聚类更强”
- “可以开始 Stage 2 hard_b / M calibration”
- “可以冻结正式 Stage 1 split/protocol”

## 9. 最新 staged curriculum 实验补充

在 `632e41d test: ablate MICA stage1 slot competition` 之后，又新增了一轮 **Stage 1-only staged curriculum schedule** 实验。

这一轮不改数据边界，不进 Stage 2，只测试：

- `k2-only specialization` 能否保住；
- `k1` 渐进式重引入后，second slot 是否还能存活；
- 哪一种 Stage 1 schedule 能在 mixed 训练下保住 attribution。

### 9.1 新增权威数据来源

本轮新增的主要权威数据来源：

- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T0_k2_only_reference_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T1_long_k2_specialization_then_gentle_k1_reintroduction_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T2_k2_specialization_with_replay_protected_mixed_training_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T3_align_preserving_mixed_training_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T4_freeze_slot_queries_after_k2_specialization_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- `outputs/mica_stage1_staged_curriculum_20260615T023159Z/T5_disable_deterministic_coupling_during_reintroduction_metrics.json`（旧 macOS 临时目录产物，当前本地未找到）
- [reports/mica_stage1_staged_curriculum_result.json](../../../reports/mica_stage1_staged_curriculum_result.json)
- [reports/mica_stage1_staged_curriculum_result.md](../../../reports/mica_stage1_staged_curriculum_result.md)

后续恢复说明：上述 6 份原始 `*_metrics.json` 仍未找到；汇总 JSON 的 `settings[0..5]` 保留了对应完整指标对象，已生成[带来源与哈希的 reconstructed 副本](../../../recovered_artifacts/stage1_staged_curriculum_20260615T023159Z/RECOVERY_MANIFEST.json)。这些副本不能冒充原始运行文件。

### 9.2 staged schedule 矩阵与关键结果

本轮实际跑了 6 个 setting：

- `T0_k2_only_reference`
- `T1_long_k2_specialization_then_gentle_k1_reintroduction`
- `T2_k2_specialization_with_replay_protected_mixed_training`
- `T3_align_preserving_mixed_training`
- `T4_freeze_slot_queries_after_k2_specialization`
- `T5_disable_deterministic_coupling_during_reintroduction`

其中最重要的 mixed 指标如下：

| Setting | count_acc(mixed) | k2_split_recall(mixed) | second_slot_gold_recall(mixed) | unit_acc_gain_over_all_one(mixed) | slot_collapse_rate(mixed) | 结论 |
|---|---:|---:|---:|---:|---:|---|
| `T0` | `0.50` | `0.92` | `0.43` | `-0.0035` | `0.18` | 只证明 `k2-only` 上界，不是可用 mixed protocol |
| `T1` | `0.86` | `0.72` | `0.3833` | `0.0461` | `0.20` | 接近通过，但 second-slot 仍低于阈值 |
| `T2` | `0.78` | `0.92` | `0.4867` | `0.0438` | `0.12` | **唯一满足 fix 条件的 mixed setting** |
| `T3` | `0.70` | `0.68` | `0.2933` | `0.0339` | `0.22` | align-preserving 仍不足 |
| `T4` | `0.76` | `0.68` | `0.2800` | `0.0149` | `0.20` | freeze slot queries 不够 |
| `T5` | `0.90` | `0.84` | `0.3200` | `0.0227` | `0.12` | 去掉 deterministic coupling 有帮助，但仍未通过 |

补充：

- `best_by_mixed_second_slot_gold_recall = T2`
- `best_by_mixed_k2_split_recall = T2`
- `best_by_lowest_mixed_slot_collapse = T2`
- `best_balanced_stage1_schedule = T2`

### 9.3 最新确认的重要现象

#### 9.3.1 `k2-only specialization` 可以稳定复现

`T0` 在 `k2_only_dev` 上给出：

- `count_accuracy_k2_only = 1.00`
- `k2_split_recall_k2_only = 0.92`
- `second_slot_gold_recall_k2_only = 0.43`
- `slot_collapse_rate_k2_only = 0.08`

这说明：

- 当前模型不是“根本分不出 second slot”；
- 在纯 `k2` 条件下，slot specialization 是可以形成并维持的；
- 因此后续 mixed collapse 已经不能再归因于“assignment 不可学”。

#### 9.3.2 问题已经进一步定位为 `k1` 重引入阶段的训练过程问题

新的核心结论是：

- `k2-only` 训练可以学 attribution；
- naive mixed 会 collapse；
- 但 **不是所有 mixed 都会 collapse**；
- collapse 主要发生在 `k1` 重引入方式不当时。

这比前一轮结论更精确：

- 之前只能说 `k1/k2 mixing suppresses early slot specialization`；
- 现在可以说：
  - **不受保护的 mixed / reintroduction 会压制 second slot；**
  - **带 replay 的 staged mixed 可以保住 second slot。**

#### 9.3.3 数据退化不是当前主要瓶颈

前一轮已经确认：

- `medium` 子集比原 tiny subset 更健康；
- file-path/random baseline 已被降低；
- overfit 也通过了。

这轮 `T2` 的成功进一步说明：

- 当前 medium 数据并不是“根本没法学 attribution”；
- 真正瓶颈是训练 schedule，而不是单纯数据退化。

#### 9.3.4 count/existence loss 不是当前主要矛盾

`T3_align_preserving_mixed_training` 已经给了较温和的 count/exist warmup：

- `count_accuracy_mixed = 0.70`
- `k2_split_recall_mixed = 0.68`
- `second_slot_gold_recall_mixed = 0.2933`

它比 naive mixed 好，但仍然不如 `T2`。

说明：

- 当前不是简单的“count/existence 太早开启”；
- 更关键的是 mixed 阶段如何**保护已学到的 k2 slot specialization**。

#### 9.3.5 deterministic coupling 不是主因

`T5_disable_deterministic_coupling_during_reintroduction` 的结果：

- `count_accuracy_mixed = 0.90`
- `k2_split_recall_mixed = 0.84`
- `second_slot_gold_recall_mixed = 0.32`
- `slot_collapse_rate_mixed = 0.12`

它确实比早期 naive mixed 更好，但仍然没有达到 fix 条件。

因此当前可以确认：

- deterministic coupling 可能会加剧问题；
- 但它不是 primary bottleneck；
- 仅靠“晚一点开 coupling / 关 coupling”还不够。

#### 9.3.6 replay-protected mixed training 是当前最小可行修复

`T2` 是本轮唯一满足 mixed fix 条件的 schedule：

- `k2_split_recall_mixed = 0.92`
- `second_slot_gold_recall_mixed = 0.4867`
- `unit_accuracy_gain_over_all_one_mixed = 0.0438`
- `slot_collapse_rate_mixed = 0.12`
- `count_accuracy_mixed = 0.78`
- `over_split_rate_on_k1_mixed = 0.40`

这表明：

- 当前 Stage 1 已经不只是“存在一个 upper reference”；
- 而是已经存在一个 **可工作的 staged mixed protocol 候选**；
- 当前最小可行候选就是：
  - `T2_k2_specialization_with_replay_protected_mixed_training`

## 10. 当前能成立的结论（更新）

在第 8 节原有结论基础上，现在新增以下可以成立的结论：

7. **`k2-only` specialization 可以稳定复现。**
   - 因此 Stage 1 attribution 不是“完全不可学”。

8. **当前 mixed collapse 主要是 schedule 问题，而不是 loss correctness 问题。**
   - `L_align`、Hungarian、assignment overfit 都已经验证通过。

9. **`k1` 的重引入方式决定 second slot 是否被破坏。**
   - naive mixed 会塌；
   - replay-protected staged mixed 可以保住。

10. **当前已经找到一个 Stage 1-only 的最小可行修复候选：`T2`。**

11. **当前不需要进入 Stage 2 来修 Stage 1 attribution collapse。**
   - 先把 `T2` 作为 formal Stage 1 schedule 候选扩样验证更合理。

## 11. 当前仍不能成立的结论（更新）

即使 `T2` 成功，也还不能直接说：

- “Stage 1 formal protocol 已经最终冻结”
- “当前 representation 已经充分”
- “当前 architecture 已经无须继续审视”
- “可以跳过更大样本 rerun”
- “可以开始用 `hard_b` / `M` 做 Stage 1 attribution 修补”

当前更准确的说法应是：

- **staged Stage 1 protocol is viable**
- 但还需要：
  - 用更大样本 rerun `T2`
  - 复核 mixed-dev 上的 second-slot 保持情况
  - 再决定是否正式冻结 Stage 1 protocol

这些说法都与当前数据不符。

## 9. 当前最值得保留的实验教训

如果后续继续推进 Stage 1 attribution，当前最重要的经验是：

1. 不要再继续把主要精力放在 count coupling 上；
2. attribution 的成败必须用 baseline 对比来定义，而不是用 loss 下降或 count_accuracy；
3. 需要单独针对 assignment discrimination 和 slot collapse 做建模；
4. 当前 local sanity 的 `k=2` 结构很偏 singleton-intent，解释结果时必须始终显式说明这一点。

## 10. 后续使用建议

后续讨论时，建议这样引用当前阶段：

- 若讨论“训练链路是否打通”：
  - 引用 `20260614T083245Z`
- 若讨论“count coupling 有没有改善 k=1 over-splitting”：
  - 对比 `20260614T062358Z -> 20260614T064731Z -> 20260614T083245Z`
- 若讨论“为什么 attribution 还不能算成功”：
  - 直接引用 `reports/mica_stage1_attribution_debug.json`
  - 特别强调：
    - `model_oracle_k = all_one_cluster`
    - `file_path_baseline = 0.96`
    - `random_gold_k_mean = 0.8922`
    - `k2_singleton_intent_fraction = 0.96`

当前最简洁的总结是：

> Stage 1 现在已经从“能不能训”推进到了“为什么 attribution 还没学出来”，但还没有推进到“attribution 已经超过简单 baseline”。

## 12. 2026-06-15 更新：T2 scale-up、多 seed schedule comparison 与 protocol freeze

本节追加记录 `7122cef -> 3df2f8e` 之间的新实验事实和结论。权威摘要来自：

- [reports/mica_stage1_t2_scaleup_result.md](../../../reports/mica_stage1_t2_scaleup_result.md)
- [reports/mica_stage1_candidate_schedule_comparison_result.md](../../../reports/mica_stage1_candidate_schedule_comparison_result.md)
- [reports/mica_stage1_formal_manifest_summary.md](../../../reports/mica_stage1_formal_manifest_summary.md)
- [reports/mica_stage1_protocol_freeze.md](../../../reports/mica_stage1_protocol_freeze.md)

### 12.1 T2 replay-protected mixed 的 scale-up validation 失败

上一轮 staged curriculum 中，`T2_replay_protected_mixed` 是 tiny-scale 上唯一满足 mixed-dev fix 条件的 schedule。但扩样验证显示：

- `t2_scaleup_validated = false`
- Scale A sanity reference 中 T2 通过；
- Scale B 中 T2 相比 naive 有改善，但未达到通过阈值；
- Scale C fallback 中 naive 反而强于 T2，且 naive 通过、T2 失败。

关键 Scale C 单 seed 对比：

| schedule | k2_split_recall | second_slot_gold_recall | unit_gain_over_all_one | slot_collapse | count_acc | pass |
|---|---:|---:|---:|---:|---:|---|
| `naive_balanced_mixed` | `0.8720` | `0.5325` | `0.0888` | `0.1080` | `0.9240` | true |
| `T2_replay_protected_mixed` | `0.6560` | `0.3869` | `0.0502` | `0.2280` | `0.9000` | false |

这一结果推翻了“直接把 T2 冻结为正式 Stage 1 schedule”的判断。更准确的结论是：

- T2 是 tiny-scale 上有效的 staged diagnostic；
- T2 在更大 medium subset 上不稳定；
- naive mixed 在 Scale C 单 seed 上反超 T2；
- 不能根据 tiny-scale T2 成功直接冻结 formal protocol。

### 12.2 Scale C 多 seed comparison 确认 naive mixed 更稳定

随后固定 Scale C fallback 规模：

- `k1_train = 500`
- `k2_train = 500`
- `k1_dev = 125`
- `k2_dev = 125`
- seeds = `[13, 42, 2026]`

只比较两个候选：

- `naive_balanced_mixed`
- `T2_replay_protected_mixed`

多 seed 汇总：

| schedule | pass_rate | mean second_slot_gold_recall | mean unit_gain_over_all_one | mean slot_collapse_rate |
|---|---:|---:|---:|---:|
| `naive_balanced_mixed` | `1.0000` | `0.5628` | `0.1002` | `0.1267` |
| `T2_replay_protected_mixed` | `0.6667` | `0.4063` | `0.0561` | `0.2333` |

逐 seed 结果：

- seed `13`: naive pass, T2 pass；但 naive second-slot recall 和 unit gain 更高、collapse 更低；
- seed `42`: naive pass, T2 fail；
- seed `2026`: naive pass, T2 pass；但 naive 仍在核心 direct attribution 指标上更强。

最终判断：

```text
candidate_schedule_validated = naive
freeze_candidate_formal_stage1_schedule = true
```

这说明 Scale C 的 naive 胜出不是单 seed 偶然现象。当前 Stage 1 候选正式 schedule 应选：

```text
candidate_stage1_schedule = naive_balanced_mixed_large_scale
```

而不是 T2。

### 12.3 为什么最新结论与上一节 T2 结论不同

上一节记录的是 staged curriculum tiny sanity 的现象：

- `k2-only` 能形成 second-slot specialization；
- naive mixed 在小规模设置下容易 collapse；
- T2 是当时唯一满足 tiny mixed-dev fix 条件的 schedule。

最新 scale-up 和多 seed 结果补充了新的事实：

- T2 的 tiny-scale 优势不能外推到 larger medium scale；
- 更大样本下 naive mixed 本身已经能提供足够的 split signal；
- replay-protected schedule 反而可能在 larger scale 下削弱 mixed attribution/generalization；
- 因此当前不再应把 T2 当作正式候选，而应把它保留为 diagnostic ablation。

当前最准确的修正结论是：

- **tiny-scale collapse 主要暴露 schedule sensitivity；**
- **larger-scale candidate schedule comparison 支持 naive mixed；**
- **正式 Stage 1 下一步应冻结并验证 larger-scale naive mixed，而不是继续发明新 schedule。**

### 12.4 Formal Stage 1 candidate protocol 已冻结

最新 protocol freeze 结果：

```text
protocol_status = candidate_frozen
candidate_schedule = naive_balanced_mixed_large_scale
formal_manifest_status = frozen_runtime_manifest_created
stage2_allowed = false
next_action = run_official_stage1_validation
```

候选 schedule 固定为：

- epochs = `15`
- train mixed `k1/k2` from epoch 1
- `lambda_align = 1.0`
- `lambda_count = 0.5`
- `lambda_exist = 0.5`
- no replay
- no staged k2 warmup
- no Stage 2 loss
- no `hard_b/M`

这一步只是 protocol/split freeze，不是正式训练结果。

### 12.5 Formal manifest 结果

runtime manifest 已生成，但不提交：

```text
outputs/mica_stage1_formal_manifest_20260615T000000Z/stage1_formal_manifest.json
```

正式 split 未降级：

| split | k1 | k2 | total |
|---|---:|---:|---:|
| train | `1000` | `1000` | `2000` |
| dev | `250` | `250` | `500` |
| test | `250` | `250` | `500` |

medium candidate pool：

- `medium_candidate_count_available = 3599`
- `fallback_applied = false`
- `formal_manifest_downgraded = false`

split 结构诊断：

| split | singleton_fraction | file_path_baseline_mean | random_gold_k_mean | avg_edit_units | p50 | p90 |
|---|---:|---:|---:|---:|---:|---:|
| train | `0.0000` | `0.5617` | `0.4288` | `8.2120` | `7` | `14` |
| dev | `0.0000` | `0.5610` | `0.4295` | `8.0320` | `7` | `13` |
| test | `0.0000` | `0.5587` | `0.4242` | `8.0920` | `6` | `15` |

相较最早 tiny sanity，这个 formal candidate split 明显更健康：

- singleton intent 问题被消除；
- file-path baseline 不再接近 `0.96`；
- random-gold-k baseline 不再异常高；
- edit unit 数量更适合 attribution 评估。

### 12.6 Leakage / overlap sanity

hard leakage 检查：

- `sample_id_overlap_count = 0`
- `sha_overlap_count = 0`
- `synthetic_id_overlap_count = 0`

非 hard-leakage overlap：

- `normalized_subject_overlap_count = 674`
- `repo_overlap_count = 125`
- `repo_overlap_allowed_for_stage1_synthetic = true`

解释：

- 当前 split 保证 sample/sha/synthetic id 级别无 hard leakage；
- repo 和 normalized subject overlap 没有伪造成 0；
- 当前 Stage 1 synthetic attribution 设置是 sample-disjoint，不声称 repo-disjoint。

### 12.7 当前能成立的新结论

在前文基础上，最新可以成立的结论更新为：

12. **T2 不能作为 formal Stage 1 schedule 直接冻结。**
    - tiny scale 有效，但 scale-up 未验证。

13. **Scale C 多 seed 支持 naive mixed 作为 candidate formal Stage 1 schedule。**
    - naive pass_rate = `1.0`；
    - T2 pass_rate = `0.6667`；
    - naive 在 second-slot recall、unit gain、slot collapse 上均优于 T2。

14. **Formal Stage 1 candidate protocol/split 已冻结。**
    - schedule = `naive_balanced_mixed_large_scale`；
    - train/dev/test runtime manifest 已生成；
    - manifest 本体不提交。

15. **Formal candidate split 的结构比早期 tiny sanity 健康。**
    - no singleton dominated k2；
    - file-path/random baselines 明显降低；
    - k2 edit units 更充足。

16. **Stage 2 仍然禁止进入。**
    - protocol freeze 不是 validation pass；
    - 下一步必须是 official Stage 1 validation。

### 12.8 当前仍不能成立的新边界

即使 protocol 已冻结，仍不能说：

- “Stage 1 已正式通过”
- “Stage 1 attribution 已最终稳定”
- “可以进入 Stage 2”
- “formal manifest 已提交”
- “repo-disjoint split 已实现”

当前准确说法是：

> Stage 1 candidate schedule and split are frozen; the next required step is official Stage 1 validation under the frozen manifest. Stage 2 remains blocked.

## 13. 2026-06-18 implementation skeleton update

为了不让导师尚未回复的问题阻塞工程实现，本分支新增了一个 downstream skeleton，但它不改变上面的实验结论。

新增内容：

- `code/mica/schemas.py`
- `code/mica/plan_builder.py`
- `code/mica/renderers/deterministic.py`
- `code/mica/runners/run_official_stage1_validation.py`
- `code/mica/runners/audit_future_stage2_inputs.py`
- `configs/mica/stage1_protocol_spec.json`
- `configs/mica/stage1_metric_thresholds.json`
- `configs/mica/unresolved_questions.json`

这些新增模块的边界是：

- 只提供 schema / builder / renderer skeleton / dry-run runner / future input audit
- 不接入当前 Stage 1 默认训练入口
- 不改已有 reports 生成链路
- 不开始 Stage 2
- 不读取 `hard_b / M / RealDomainBinary` 并启动训练

因此，这一轮实现应被理解为：

> 预先搭建后续代码骨架，但不改变当前 Stage 1 scientific status。

## 14. 2026-06-18 downstream follow-up update

在上一轮 skeleton 基础上，本分支又补齐了一个 downstream offline smoke pipeline：

- batch plan builder
- batch deterministic renderer
- plan/message smoke runner
- official Stage 1 dry-run runner 的可选 plan smoke
- future Stage 2 input audit 的字段审计与 guard

这些更新的边界仍然是：

- 不执行 official Stage 1 validation 指标
- 不给 Stage 1 做 pass/fail
- 不开始 generation 主实验
- 不开始 Stage 2

因此到目前为止，最新准确说法仍然是：

> Stage 1 remains frozen-but-not-yet-officially-validated; downstream offline conversion is now available, but Stage 2 is still blocked.
