# 2026-05-27 Step1 结果分析报告

## 1. 这轮 Step1 结果在回答什么问题

当前 Step1 的核心目标是为 Step2 稳定提供一批数量够大、噪声够低的单意图原料。

所以，这轮结果真正要回答的是：

1. 当前 Step1 能不能稳定产出足够大的单意图原料池；
2. 这批原料池的纯度是否足够高；
3. 最终应该把哪一种策略的结果交给 Step2；
4. 当前结果里哪些可以直接写进实验记录，哪些不能夸大。

本报告基于当前正式交付层与最新 `p3000` 正式 run：

- 当前交付层：`datasets/derived/step1_source_pool/current/`
- 对应正式 run：`datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z`

## 2. 最重要的结论

一句话概括：

> 当前 Step1 已经能稳定交付一批规模为 `5099` 条、纯度较高、适合继续喂给 Step2 的保守单意图原料池；推荐继续使用 `model_rule_refilter` 作为正式交付策略。

这句话背后的关键事实是：

- 输入候选数：`12000`
- full-diff 模型判为 A 层：`7647`
- 规则复筛后保留：`5099`
- 最终交付池：`5099`
- Tier-A 人工审计：`288 / 300 = 0.9600`
- Wilson 95% 置信区间：`[0.9314, 0.9770]`

这说明两件事：

1. 规模上，Step1 已经不是“勉强够用”，而是明显超过了下游对 `1500+` 数量级的需求；
2. 纯度上，当前主链路 A 层已经比较干净，至少从这轮 300 条人工审计样本看，噪声处在一个可以接受的范围内。

## 3. 三种策略该怎么理解

当前比较的三种策略是：

- `rule_only`
- `model_only`
- `model_rule_refilter`

这三者在最新 formal run 中的选中规模分别是：

- `rule_only.selected_count = 5166`
- `model_only.selected_count = 7647`
- `model_rule_refilter.selected_count = 5099`

它们的关系不是“谁绝对更高级”，而是分工不同：

### 3.1 `model_only`

`model_only` 更像主链路的高置信大池子。

它的优点是：

- 候选规模最大；
- 保留了 full-diff 校准模型的排序能力；
- 方便给后续做再筛选。

但它的问题是：

- 直接交付给 Step2 还是偏宽；
- 里面包含了一批规则协议不愿意放行的样本。

从交叉计数可以直接看出来：

- `model_tier_a_count = 7647`
- `model_tier_a_rule_positive_count = 5099`
- `model_tier_a_rule_rejected_count = 2548`

也就是说，模型 A 层里有 `2548` 条最后被独立规则协议拦下来了。这说明如果把 `model_only` 直接当正式交付层，用于 Step2 的原料噪声边界会偏松。

### 3.2 `rule_only`

`rule_only` 更像一套独立精度守门协议。

它的特点是：

- 更保守；
- 可解释性更直接；
- 很适合拿来做最终复筛。

但它也不是当前最理想的正式交付形态。原因不是它“差”，而是它没有利用 full-diff 模型的排序信息。

从交叉关系看：

- `rule_positive_model_tier_a_count = 5099`
- `rule_positive_model_not_a_count = 67`

也就是说，规则认为好的样本里，绝大部分本来就在模型 A 层里，只有 `67` 条没有进模型 A。换句话说，模型主链路先做排序，再让规则做精度守门，比只看规则更符合当前实验叙事。

### 3.3 `model_rule_refilter`

这就是当前推荐交付策略。

它的含义很直接：

- 先让 full-diff 校准模型给出 A 层高置信候选；
- 再用独立规则协议做保守复筛；
- 最终只把两者都同意的样本交给 Step2。

这套策略的价值在于：

- 保留了模型排序能力；
- 又避免把模型 A 层里的边界样本全量放下游；
- 更符合 Step1 的真实目标，也更方便对外叙述。

## 4. 为什么说当前结果“够正式”

这里的“够正式”不是说一切都完美，而是说它已经满足作为 Step2 原料池的基本要求。

### 4.1 数量已经足够

当前正式交付池是 `5099` 条。

相比此前较小规模正式 run 的 `2712` 条，这次新增了 `2387` 条，几乎翻了一倍。

这意味着：

- Step2 后面即使做更严格过滤，仍然有可用余量；
- 当前 Step1 已经不再受“交付规模太小”的主问题约束。

### 4.2 主链路纯度已经比较高

当前 A 层人工审计结果是：

- `288 / 300 = 0.9600`
- Wilson 95% 区间：`[0.9314, 0.9770]`

这个结果不能被夸张成“所有候选都绝对无噪声”，但它足以支持一个稳妥结论：

- 当前主链路 A 层总体是干净的；
- 在这个基础上再做一层规则复筛，最终交付池的保守性是有说服力的。

另外，`strategy_comparison.json` 里还给了一个很有用的交叉结果：

- `model_rule_refilter` 在命中的 `207` 条审计子样本上，精度是 `203 / 207 = 0.9807`

这个数字不能和 300 条 A 层全样本审计完全等价，但它能说明：

- 被规则保留下来的那部分样本，比模型 A 层整体还要更干净一些。

### 4.3 协议边界是清楚的

当前 formal run 明确采用了严格互斥协议。

`audit_precision_report.json` 里给出的独立检查结果是：

- `candidate_rows = 11960`
- `pilot_rows = 239`
- `overlap_sha_count = 0`
- `is_disjoint = true`

这直接导致一个重要后果：

- 当前 `precision / recall / F1` 在 formal run 的 `evaluation.csv` 上被明确标记为“不可直接计算”。

这不是报错，也不是实验没做完，而是协议本身要求把 evaluation split 和正式候选池严格隔离。

这件事要说清楚，因为它影响论文叙事：

- 当前 Step1 正式结果的主证据，不应写成 evaluation split 的直接分类指标；
- 更适合写成“人工审计纯度 + 策略交叉计数 + 严格互斥协议下的正式交付规模”。

## 5. 不能怎么解读这轮结果

这轮结果虽然整体是正面的，但有几件事不能乱说。

### 5.1 不能说“模型全面赢了规则”

当前 Step1 的真正目标不是这个。

而且从当前数据看，更合理的说法是：

- 模型负责排序；
- 规则负责保守复筛；
- 最终交付层是两者结合的结果。

### 5.2 不能说“300 条审计证明所有候选都绝对单意图”

`288 / 300 = 0.9600` 说明纯度高，但不等于零噪声。

稳妥的说法应该是：

- 当前主链路 A 层在人工审计样本上表现出较高纯度；
- 这支持它作为高精度 source mining 模块的角色；
- 但仍然不能把单次审计结果外推成全体绝对无噪声。

### 5.3 不能把 message-only proxy 再拿回去当最终高置信过滤器

当前 `strategy_comparison.json` 给出的 proxy 角色总结是：

- `proxy_role = recall_prefilter_only`
- `proxy_to_full_diff_agreement = 0.2896`
- `proxy_high_confidence_warning = true`

这说明当前 proxy 链路和 full-diff 主链路的一致性仍然很差。

因此，当前比较稳妥的口径仍然是：

- `message-only proxy` 只适合做召回前置粗筛；
- 不适合直接当最终高置信单意图过滤器。

## 6. 当前 Step1 结果对 Step2 的意义

对 Step2 来说，当前最重要的不是 Step1 模型多漂亮，而是有没有一批：

- 规模够大；
- 边界够保守；
- 质量足够稳定；
- 可以直接桥接过去的单意图 source。

这轮结果已经满足这几个条件。

当前 Step2 实际消费的就是：

- `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`

而且这份交付层已经桥接成：

- `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`

当前桥接规模同样是：

- `5099` 条

这意味着当前 Step1 的主要价值已经不在“理论上可不可以”，而在“已经形成一个可以稳定对接 Step2 的正式原料池”。

## 7. 仓库口径整理结果

本轮手扫仓库后，和 Step1 正式产物路径相关的情况可以分成三类：

### 7.1 已修正

已修正为当前正式口径的地方：

- `code/step1/README.md`
- `docs/project_map.md`
- `code/step1/docs/2026-05-26-step1-正式结果记录.md` 中针对 `p1600` 正式 run 的产物路径

这些地方现在统一指向：

- `datasets/derived/step1_runs/...`
- `datasets/derived/step1_source_pool/current/...`

### 7.2 保留但不算错误

以下 `outputs/` 引用没有改，因为它们不是“当前正式产物主路径”口径，而是：

- 代码默认输出目录
- 离线工具说明
- 历史或局部实验工具的工作目录

例如：

- `code/step1/offline_backfill_tools/README.md`
- Step1 代码里的默认 `output_dir` 参数

这些路径是工具运行时输出位置，不等同于当前正式交付层。

### 7.3 现在该怎么找 Step1 正式结果

如果以后只想看当前 Step1 正式结果，直接看这两层：

1. 当前正式交付层：
   - `datasets/derived/step1_source_pool/current/`
2. 对应正式 run 快照：
   - `datasets/derived/step1_runs/step1_formal_step2_sha_expanded_annotated_disjoint_p3000_20260527T071833Z`

## 8. 最终建议

当前建议非常明确：

1. Step1 对外正式交付，继续使用 `model_rule_refilter` 的 `conservative_atomic_sources.csv`。
2. 论文或实验记录里，优先强调：
   - 交付池规模 `5099`
   - A 层人工审计 `288/300 = 0.9600`
   - 严格互斥协议下 evaluation 指标不可直接计算
   - `message-only proxy` 只作粗筛
3. 不要再把“Step1 正式结果”默认写成 `outputs/...`，当前主路径已经是：
   - `datasets/derived/step1_runs/...`
   - `datasets/derived/step1_source_pool/current/...`

当前最稳妥的总评可以写成：

> Step1 已经形成一个面向 Step2 的高精度单意图原料挖掘模块。当前推荐交付策略不是单纯依赖模型高阈值判定，而是采用“full-diff 校准模型排序 + 独立规则协议复筛”的保守交集方案。基于最新 formal run，这一路径已经稳定产出 `5099` 条可交付 source commits，并在主链路 A 层人工审计中达到 `288/300 = 0.9600` 的精度水平，足以支持其作为 Step2 上游正式原料池的当前实现形态。
