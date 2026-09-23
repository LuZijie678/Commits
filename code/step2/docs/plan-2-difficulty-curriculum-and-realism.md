# Plan 2: Difficulty Curriculum and Realism Perturbation

> 状态声明：本文档是 Step2 后续 difficulty curriculum 与 realism perturbation 的正式设计稿。除非在 `code/`、`tests/`、`README` 或 `plan-1` 中明确出现，对应字段与流程均应视为 planned / not implemented yet，而不是当前代码已实现。

## 1. 目标与职责边界

本节的目标是把 Step2 synthetic construction 中与结构难度和拟真性有关的实验方案整理为 implementation-ready 的正式设计。设计要求如下：

1. 概念严谨，避免把“复杂 commit”错误等同于“multi-intent commit”。
2. 分层自洽，能够同时覆盖复杂单目的 commit 和多意图 tangled commit。
3. 字段可落盘，能够直接进入 Step2 输出 schema。
4. 实现路径清楚，便于后续拆分为 feature calculator、level assignment、builder、normalizer、summary exporter 和 curriculum export interface。

Step2 与后续下游训练阶段的职责边界明确如下：

```text
Step2：可控构造并标注样本，同时输出 curriculum-ready difficulty / realism metadata
Step3：消费 Step2 导出的数据进行下游弱监督预训练
```

因此，难度课程、拟真扰动、来源置信度与拟真度联合建模都属于 Step2 本身，而不是 Step3 sampler 的职责。Step2 的职责不是只“打标签后交给别人采样”，而是设计并落盘一套可审查的 difficulty/realism 控制顺序与数据分布。

---

## 2. 修正后的分层原则

### 2.1 新分层的核心修正

新的难度分层不再把“更多 intent”直接视为“更高难度”，而是采用：

```text
single-intent → simple / complex
multi-intent  → separable / entangled
```

对应的四个训练层级为：

| Level | intent cardinality | structure pattern | 名称 | 核心含义 |
|---|---|---|---|---|
| Level A | single | simple | single-intent simple | 单一意图，改动范围简单 |
| Level B | single | complex | single-intent complex | 单一意图，但跨文件、多 hunk、多 supporting edits |
| Level C | multi-2 / multi-3 | separable | multi-intent separable | 多个意图，但文件、模块或语义边界清楚 |
| Level D | multi-2 / multi-3 | entangled | multi-intent entangled | 多个意图，且共享文件、identifier 或存在轻度依赖 |

### 2.2 这不是完整笛卡尔积分类

本设计不是对 `intent_cardinality × structure_pattern` 做完整笛卡尔积展开。`structure_pattern` 在 `single-intent` 和 `multi-intent` 条件下的语义不同：

1. 当 `intent_cardinality == single` 时，`structure_pattern` 只能取 `simple` 或 `complex`。
2. 当 `intent_cardinality in {multi-2, multi-3}` 时，`structure_pattern` 只能取 `separable` 或 `entangled`。
3. 因而 v1 中只有四个有效组合：

| intent_cardinality | structure_pattern | difficulty_level |
|---|---|---|
| single | simple | A |
| single | complex | B |
| multi-2 / multi-3 | separable | C |
| multi-2 / multi-3 | entangled | D |

这个设计的目的，是避免“二维设计和四个层级对不上”的问题，并同时覆盖两类真实难例：

1. 复杂单目的 commit。
2. 多意图、局部缠绕的 commit。

### 2.3 命名与计数口径

为避免实现时混淆，本文强制采用以下口径：

1. `source_commit_count`：构造该样本时选入的 source commit 数量。
2. `intent_count`：最终分配给该样本的 intent 数量，不等于 `source_commit_count`。
3. `intent_cardinality`：对 `intent_count` 的离散化标签，v1 取值为 `single`、`multi-2`、`multi-3`。

例如，Route 1 可能用 3 个 source commits 合成 1 个 complex single-intent sample；此时：

```text
source_commit_count = 3
intent_count = 1
intent_cardinality = single
```

---

## 3. 总体流程与模块关系

`3.2.5 Difficulty-aware Curriculum` 与 `3.2.6 Realism Perturbation` 应被组织为同一条 Step2 流水线中的两个连续阶段：

```text
source commits / source set
        ↓
结构特征分析
        ↓
difficulty level assignment
        ↓
realism feature / score
        ↓
source confidence / joint weight metadata
        ↓
输出 synthetic sample
        + difficulty metadata
        + perturbation metadata
        + realism metadata
        + curriculum-ready metadata
```

其中：

1. `sample construction` 先决定该样本实际由哪些 source commits 和 edit units 构成。
2. `difficulty feature extraction` 在已构造样本上提取结构复杂度特征。
3. `difficulty level assignment` 决定样本属于哪种结构复杂度。
4. `realism feature / score` 决定该样本在 presentation-level 上有多接近真实 tangled commit。
5. `source confidence / joint weight metadata` 把 `sample_confidence`、`pair_quality_weight`、`rho`、`message_quality_weight` 组织为可审查的联合权重字段。
6. 以上顺序全部属于 Step2 内部流程；Step3 只消费其输出，不负责定义这套顺序。

在 Step2 内部，Level A/B/C/D 的来源建议如下：

1. Level A：单 source commit passthrough 或单意图轻量规范化样本。
2. Level B：Route 1 complex single-intent construction。
3. Level C / D：Route 2 multi-intent construction。

Level A 不是新的“合成路线”，而是对单意图样本池做统一 schema 包装，使后续下游训练能够消费与其它 level 同构的样本记录。

---

## 4. Difficulty Features 设计

### 4.1 字段清单与总体要求

每条样本至少需要落盘以下 difficulty features：

```text
intent_count
intent_cardinality
structure_pattern
total_file_count
hunk_count
module_count
file_role_mix
main_topic_coherence
shared_file_count
shared_file_ratio
same_file_hunk_count
identifier_overlap_score
max_pairwise_identifier_overlap
avg_pairwise_identifier_overlap
module_overlap_score
dependency_hint_score
patch_conflict_risk
```

实现要求：

1. 每个字段都必须有明确含义、用途和计算口径。
2. 阈值优先使用 distribution-derived thresholds，而不是手写常数。
3. 如果 v1 使用默认阈值，必须记录 `threshold_source`，并在实验计划中加入 sensitivity analysis。
4. `main_topic_coherence` 主要服务于 Level B。
5. `identifier_overlap_score` 与 `dependency_hint_score` 主要服务于 Level C / D 区分。
6. 对 `k > 2` 的样本，必须保留 `max_pairwise_identifier_overlap` 和 `avg_pairwise_identifier_overlap`。

### 4.2 字段定义、用途与计算方式

| 字段 | 含义 | 用途 | v1 可能计算方式 |
|---|---|---|---|
| `intent_count` | 最终 intent 数量 | Level A/B/C/D 判定、下游 count task | Route 1 固定为 1；Route 2 由 source grouping 决定，v1 取 2 或 3 |
| `intent_cardinality` | `intent_count` 的离散标签 | curriculum bucket、ablation | `1 -> single`，`2 -> multi-2`，`3 -> multi-3` |
| `structure_pattern` | 条件化的结构模式 | Level A/B/C/D 判定 | `single` 下判定 `simple/complex`；`multi` 下判定 `separable/entangled` |
| `total_file_count` | 样本涉及的唯一文件数 | 区分简单与复杂、汇报分布 | 从最终 synthetic diff 去重统计文件路径 |
| `hunk_count` | 样本中的 hunk 总数 | 区分简单与复杂、扰动策略 | 从最终 synthetic diff 统计 `@@` 数量 |
| `module_count` | 样本涉及的模块数 | 区分简单与复杂、分析跨模块扩展 | 由 repo module resolver 解析；v1 可退化为 top-level dir 或前两级 path segment 去重 |
| `file_role_mix` | 文件角色混合程度 | Level B supporting edit 分析、summary | 先把文件映射到 `source/test/doc/config/build/script/asset`，再计算归一化熵或归一化 distinct role count |
| `main_topic_coherence` | 多个 edits 是否仍服务于一个主意图 | Level B 关键判定、Route 1 source selection | 规则加权分数，综合 `message similarity`、`path concentration`、`identifier focus`、`source-test linkage`、`issue/PR linkage` |
| `shared_file_count` | 被多个构造单元共同修改的文件数 | 区分 C / D，分析结构交织 | 统计被 2 个及以上构造单元触达的文件数 |
| `shared_file_ratio` | 共享文件占比 | 区分可分离与交织 | `shared_file_count / total_file_count` |
| `same_file_hunk_count` | 同一共享文件内、来自不同构造单元的 hunk 数量 | C / D 区分、interleaving 目标选择 | 对共享文件统计跨单元 hunk 数 |
| `identifier_overlap_score` | 跨构造单元 identifier 重叠主分数 | C / D 区分、bucket sampling | `k=2` 时为 pairwise overlap；`k>2` 时 v1 定义为 `max_pairwise_identifier_overlap` |
| `max_pairwise_identifier_overlap` | 任意两单元间最大 identifier overlap | `k>2` 难例检出 | 对所有 pair 取最大值 |
| `avg_pairwise_identifier_overlap` | 任意两单元间平均 identifier overlap | 汇报多意图总体缠绕度 | 对所有 pair 取平均值 |
| `module_overlap_score` | 构造单元是否集中在相同模块 | B 的主题集中度辅助、C / D 分析 | 对单元模块集合计算 pairwise Jaccard，再取 max 或 avg |
| `dependency_hint_score` | 构造单元之间的轻量依赖迹象 | C / D 区分、supporting edit 识别 | 规则打分：共享 exported identifier、source-test target match、config reader match、import/call relation 等 |
| `patch_conflict_risk` | 合成后接近 patch 冲突的风险 | 过滤或降权 | 基于同文件邻近行范围重叠、删除/修改碰撞、hunk header 冲突等启发式打分 |

### 4.3 构造单元与 pairwise 特征的计算基础

为了让 Level B 与 Level C / D 共用一套结构特征，v1 推荐把 pairwise overlap / dependency 相关特征的计算基础统一定义为 `construction units`：

1. Route 1 中的 `construction unit` 是被选入同一主话题的 source commits。
2. Route 2 中的 `construction unit` 是最终 intent groups。
3. Level A passthrough 中若只有 1 个 source commit，则 pairwise 字段记为 `0`，并在 assignment metadata 中记录 `feature_basis = single_source_passthrough`。

这样可避免“单意图样本无法计算 shared-file / overlap 特征”的实现断层，同时保持 `intent_count` 与 `source_commit_count` 的语义分离。

### 4.4 关键分数定义

#### 4.4.1 `main_topic_coherence`

`main_topic_coherence` 是 Level B 成立的核心条件。它回答的问题是：

```text
多个 edits 是否仍然可以被一个主意图压缩表达？
```

v1 可定义为规则加权分数：

$$
\mathrm{main\_topic\_coherence}
= w_{msg}s_{msg} + w_{path}s_{path} + w_{id}s_{id} + w_{role}s_{role} + w_{link}s_{link} - w_{split}p_{split}
$$

其中：

1. `$s_{msg}$`：source commit subject / message 的语义相似度或关键词重合度。
2. `$s_{path}$`：文件路径是否集中在同一功能域。
3. `$s_{id}$`：核心 identifier 是否围绕同一对象簇。
4. `$s_{role}$`：source、test、config、doc 是否呈现“主代码 + supporting edit”结构。
5. `$s_{link}$`：是否共享同一 issue / PR / ticket / bug id。
6. `$p_{split}$`：是否存在明显的第二主目标信号，例如两个无依赖、可独立成 subject 的改动簇。

`main_topic_coherence` 高，不等于“identifier overlap 高”。它衡量的是“可否压缩为一个主意图”，不是多意图之间是否缠绕。

#### 4.4.2 `identifier_overlap_score`

对任意两个构造单元 `$u_i, u_j$`，先抽取 identifier 集合 `$I_i, I_j$`，计算：

$$
\mathrm{ov}(u_i, u_j) = \frac{|I_i \cap I_j|}{|I_i \cup I_j|}
$$

v1 中：

1. `k = 2` 时：`identifier_overlap_score = ov(u_1, u_2)`。
2. `k > 2` 时：`identifier_overlap_score = max_pairwise_identifier_overlap`。
3. 同时保留：

$$
\mathrm{max\_pairwise\_identifier\_overlap} = \max_{i < j} \mathrm{ov}(u_i, u_j)
$$

$$
\mathrm{avg\_pairwise\_identifier\_overlap} = \frac{1}{\binom{k}{2}} \sum_{i<j} \mathrm{ov}(u_i, u_j)
$$

之所以让 `identifier_overlap_score` 在 `k > 2` 时对齐到 `max`，是因为只要任意一对 intent 发生局部缠绕，就足以把样本推向 Level D 候选。

#### 4.4.3 `dependency_hint_score`

v1 不要求 AST-level 依赖图，但需要轻量依赖迹象。对任意两个构造单元，可以累加以下启发式规则并截断到 `[0,1]`：

| 规则 | 建议分值 |
|---|---:|
| A 修改的 exported identifier 出现在 B 的新增代码或上下文中 | 0.4 |
| A 修改 source，B 修改对应 test，且共享核心 identifier | 0.3 |
| A 修改 config key，B 修改读取或消费该 key 的位置 | 0.3 |
| A 修改 class / function，B 修改 import / call site | 0.4 |
| A、B 位于同模块且 identifier overlap 中等以上 | 0.2 |

对两单元得分求和后截断：

$$
\mathrm{dep}(u_i, u_j) = \min(1, \sum r_t)
$$

样本级 `dependency_hint_score` 在 v1 中建议取 pairwise 最大值，以提高 Level D 检出率。

#### 4.4.4 `patch_conflict_risk`

`patch_conflict_risk` 用于判断一个样本是否虽然能合成，但已经接近不自然或高冲突边界。v1 可综合以下信号：

1. 同一文件相同行范围被不同单元同时修改。
2. 删除 / 修改、重命名 / 修改、相邻 hunk 合并后 header 不稳定。
3. 同文件改动在 patch 排序后出现 apply 风险。

该字段既可用于过滤，也可用于 realism 降权；但 v1 不建议把它当作唯一 gate。

### 4.5 阈值来源与落盘要求

阈值优先采用 distribution-derived thresholds。推荐顺序如下：

1. 先在当前 run 的 candidate source sets 上计算连续特征分布。
2. 对 overlap / dependency / coherence 等特征，优先用分位数划分 bucket。
3. 对 file / hunk / module 等规模特征，优先用中位数或高分位作为 `small` / `complex` 分界。

v1 推荐的默认策略：

```text
low    = <= P33
medium = (P33, P66]
high   = > P66
```

如果某个 run 暂时没有足够稳定的候选分布，可使用默认阈值，但必须落盘：

```json
{
  "threshold_source": "v1_default",
  "threshold_profile_id": "step2_v1_default_2026-05-13",
  "thresholds": {
    "topic_high": 0.75,
    "file_simple_max": 2,
    "hunk_simple_max": 3,
    "module_simple_max": 1,
    "overlap_low": 0.10,
    "overlap_medium": 0.30,
    "dependency_medium": 0.35,
    "same_file_hunk_entangled_min": 2
  }
}
```

无论采用哪种来源，实验报告都应加入 sensitivity analysis，至少覆盖：

1. `main_topic_coherence`
2. `identifier_overlap_score`
3. `dependency_hint_score`
4. `simple/complex` 的 file / hunk / module cutoffs

---

## 5. Level A-D 的完整可执行规则

### 5.1 Level A: single-intent simple

#### 定义

Level A 表示单一意图、结构简单、主证据集中、无需复杂 supporting edit 聚合的样本。它通常来自单 source commit passthrough，也可以来自已经证明仍然极简的单意图样本。

#### 可执行判定

```text
intent_cardinality == single
structure_pattern == simple
main_topic_coherence >= tau_topic_high
and total_file_count <= tau_file_simple
and hunk_count <= tau_hunk_simple
and module_count <= tau_module_simple
and file_role_mix <= tau_role_low
and patch_conflict_risk <= tau_conflict_low
```

#### 典型样本

```text
fix null guard in login token parser
```

该样本只修改一个 source file 或一个 source file 加一个非常局部的 test hunk，主意图与证据几乎一一对应。

#### 训练目标

```text
main intent identification
basic evidence grounding
diff-to-subject mapping
```

#### metadata 示例

```json
{
  "difficulty_level": "A",
  "difficulty_name": "single-intent simple",
  "intent_cardinality": "single",
  "structure_pattern": "simple",
  "difficulty_features": {
    "intent_count": 1,
    "total_file_count": 1,
    "hunk_count": 1,
    "module_count": 1,
    "file_role_mix": 0.00,
    "main_topic_coherence": 0.93,
    "shared_file_count": 0,
    "shared_file_ratio": 0.00,
    "same_file_hunk_count": 0,
    "identifier_overlap_score": 0.00,
    "max_pairwise_identifier_overlap": 0.00,
    "avg_pairwise_identifier_overlap": 0.00,
    "module_overlap_score": 0.00,
    "dependency_hint_score": 0.00,
    "patch_conflict_risk": 0.00
  },
  "training_focus": [
    "main_intent_identification",
    "basic_evidence_grounding",
    "diff_to_subject_mapping"
  ]
}
```

### 5.2 Level B: single-intent complex

#### 定义

Level B 表示样本仍然只有一个主意图，但这个主意图本身复杂，通常跨文件、多 hunk、跨模块，且伴随 test / config / call-site / supporting cleanup 等辅助改动。Level B 是对真实 repo 中“复杂单目的 commit”最重要的覆盖。

#### 可执行判定

```text
intent_cardinality == single
structure_pattern == complex
main_topic_coherence >= tau_topic_high
and (
  total_file_count > tau_file_simple
  or hunk_count > tau_hunk_simple
  or module_count > tau_module_simple
  or file_role_mix > tau_role_low
)
and patch_conflict_risk <= tau_conflict_low
```

#### 典型样本

```text
fix session cache invalidation handling
```

可能同时修改：

```text
src/session/SessionService.java
src/cache/CacheManager.java
src/repository/SessionRepository.java
tests/session/SessionServiceTest.java
config/cache.yaml
```

这些 edits 分散，但仍然围绕同一个主意图，不应被错误拆成多个独立 intent。

#### 训练目标

```text
main intent identification
evidence selection
supporting edit aggregation
message compression
```

#### 与 multi-intent 的区别

Level B 与 multi-intent 的关键差异，不在于文件数，而在于这些 edits 能否被一个主意图压缩表达。Level B 的 message 应该是：

```text
fix session cache invalidation handling
```

而不是：

```text
fix cache invalidation and update tests and adjust config
```

也就是说，test / config / supporting edits 不应被机械写成独立 intent。

#### metadata 示例

```json
{
  "difficulty_level": "B",
  "difficulty_name": "single-intent complex",
  "intent_cardinality": "single",
  "structure_pattern": "complex",
  "difficulty_features": {
    "intent_count": 1,
    "total_file_count": 5,
    "hunk_count": 11,
    "module_count": 3,
    "file_role_mix": 0.64,
    "main_topic_coherence": 0.84,
    "shared_file_count": 1,
    "shared_file_ratio": 0.20,
    "same_file_hunk_count": 2,
    "identifier_overlap_score": 0.18,
    "max_pairwise_identifier_overlap": 0.18,
    "avg_pairwise_identifier_overlap": 0.11,
    "module_overlap_score": 0.71,
    "dependency_hint_score": 0.28,
    "patch_conflict_risk": 0.03
  },
  "training_focus": [
    "main_intent_identification",
    "evidence_selection",
    "supporting_edit_aggregation",
    "message_compression"
  ]
}
```

### 5.3 Level C: multi-intent separable

#### 定义

Level C 表示样本包含多个意图，但这些意图在文件、模块或语义上边界清楚，可分离性强。它既可以是 `multi-2`，也可以是 `multi-3`；`3 intents` 本身不是 Level 的定义依据。

#### 可执行判定

```text
intent_cardinality in {multi-2, multi-3}
structure_pattern == separable
shared_file_count <= tau_shared_file_low
and shared_file_ratio <= tau_shared_ratio_low
and identifier_overlap_score <= tau_overlap_low
and dependency_hint_score <= tau_dependency_low
and patch_conflict_risk <= tau_conflict_low
```

说明：`shared_file_count` 可以为 0，也可以是极低值。只要共享文件没有引入明显 identifier overlap 或 dependency，样本仍可归入 Level C。

#### 典型样本

```text
intent 1: fix login null pointer
intent 2: update export API docs
```

或：

```text
intent 1: add CSV export flag
intent 2: refresh default config comments
intent 3: update CLI usage text
```

#### 训练目标

```text
intent count prediction
edit-to-intent assignment
intent ordering
multi-intent message coverage
```

#### metadata 示例

```json
{
  "difficulty_level": "C",
  "difficulty_name": "multi-intent separable",
  "intent_cardinality": "multi-2",
  "structure_pattern": "separable",
  "difficulty_features": {
    "intent_count": 2,
    "total_file_count": 4,
    "hunk_count": 5,
    "module_count": 3,
    "file_role_mix": 0.58,
    "main_topic_coherence": 0.29,
    "shared_file_count": 0,
    "shared_file_ratio": 0.00,
    "same_file_hunk_count": 0,
    "identifier_overlap_score": 0.05,
    "max_pairwise_identifier_overlap": 0.05,
    "avg_pairwise_identifier_overlap": 0.05,
    "module_overlap_score": 0.18,
    "dependency_hint_score": 0.04,
    "patch_conflict_risk": 0.00
  },
  "training_focus": [
    "intent_count_prediction",
    "edit_to_intent_assignment",
    "intent_ordering",
    "multi_intent_message_coverage"
  ]
}
```

### 5.4 Level D: multi-intent entangled

#### 定义

Level D 表示样本包含多个意图，并且这些意图在结构上存在明显交织，例如共享文件、共享 identifier、共享模块，或存在 source-test / call-site / config 等轻度依赖。

#### 可执行判定

```text
intent_cardinality in {multi-2, multi-3}
structure_pattern == entangled
shared_file_count >= 1
and (
  identifier_overlap_score >= tau_overlap_medium
  or dependency_hint_score >= tau_dependency_medium
  or same_file_hunk_count >= tau_same_file_hunk_entangled
)
and patch_conflict_risk <= tau_conflict_low
```

#### 典型样本

```text
intent 1: refactor validateUser()
intent 2: fix validation edge case in validateUser()
```

或：

```text
intent 1: rename cache key constant
intent 2: optimize cache lookup using the same constant
```

#### 训练目标

```text
fine-grained edit-to-intent alignment
shared-file decomposition
identifier-overlap disambiguation
dependency-aware planning
```

#### metadata 示例

```json
{
  "difficulty_level": "D",
  "difficulty_name": "multi-intent entangled",
  "intent_cardinality": "multi-2",
  "structure_pattern": "entangled",
  "difficulty_features": {
    "intent_count": 2,
    "total_file_count": 3,
    "hunk_count": 8,
    "module_count": 1,
    "file_role_mix": 0.42,
    "main_topic_coherence": 0.33,
    "shared_file_count": 1,
    "shared_file_ratio": 0.33,
    "same_file_hunk_count": 4,
    "identifier_overlap_score": 0.41,
    "max_pairwise_identifier_overlap": 0.41,
    "avg_pairwise_identifier_overlap": 0.41,
    "module_overlap_score": 0.79,
    "dependency_hint_score": 0.38,
    "patch_conflict_risk": 0.05
  },
  "training_focus": [
    "fine_grained_edit_to_intent_alignment",
    "shared_file_decomposition",
    "identifier_overlap_disambiguation",
    "dependency_aware_planning"
  ]
}
```

---

## 6. 原 Level 3 的处理方式

旧方案中的“3 intents, multi-file mixture”不再作为独立 difficulty level。新的处理方式是：

```text
3 intents 是 intent_cardinality 属性，而不是独立难度 Level。
```

例如：

```text
multi-3 + low overlap + no dependency
→ Level C

multi-3 + shared file + identifier overlap
→ Level D
```

这样处理的原因有三点：

1. `3 intents` 不一定比 `2 intents + entangled` 更难。
2. 难度应由 `intent_cardinality` 和 `structure_pattern` 共同决定，而不是只看 intent 数量。
3. `multi-3` 更适合作为扩展实验或 ablation，而不是 v1 主实验的唯一高难度来源。

---

## 7. 两条 Step2 构造路线

除 Level A 的 single-source passthrough 规范化之外，Step2 的正式构造路线分为两条：

```text
Route 1: complex single-intent construction
Route 2: multi-intent construction
```

### 7.1 Route 1: complex single-intent construction

Route 1 用于构造 Level B。

#### 7.1.1 输入来源

候选 source commits 应优先来自以下高相关关系：

1. 同一 issue / PR / ticket。
2. 同一主 identifier cluster。
3. 同一模块下的同一 bug fix / feature fix-up。
4. source change 与其 regression test、config follow-up、call-site adaptation。

#### 7.1.2 `main_topic_coherence` 判定逻辑

Route 1 的核心是判断“多个 source commits 是否仍属于一个主话题”。v1 推荐按如下顺序判定：

1. 先做硬约束排除：若存在两个明显独立、可单独成 subject 的主目标，直接排除出 Route 1。
2. 再算 `main_topic_coherence`：综合 message、path、identifier、role、issue linkage。
3. 若 `main_topic_coherence >= tau_topic_high`，进入 Route 1 候选池。
4. 若 `main_topic_coherence` 边界不清，则优先保守地转入 Route 2 或丢弃，而不是强行压缩成单意图。

#### 7.1.3 supporting edits 识别

v1 中 supporting edits 的识别规则建议如下：

1. 修改 test，且 test target 与主 source edit 共享核心 identifier。
2. 修改 config，且 config key 被主代码路径直接读取或消费。
3. 修改 call site / adapter / glue code，且依赖于主 API / class 的变化。
4. 修改 doc 或 comments，但只解释主变更，不引入独立用户目标。
5. 局部 cleanup 若仅服务于主修复的可编译性、稳定性或一致性，也视为 supporting edits。

相反，如果某一组 edits 满足以下特征，则不应被压成 supporting edit：

1. 可以自然写成另一个独立 subject。
2. 与主改动共享依赖很弱。
3. 与主改动的 identifier cluster 和 path domain 都明显不同。

#### 7.1.4 构造输出

Route 1 输出时：

1. `intent_count = 1`。
2. `intent_cardinality = single`。
3. 所有 hunk 的 `edit-to-intent assignment` 统一映射到单一 intent id。
4. `structure_pattern` 依据复杂度判定为 `complex`。
5. `training_focus` 对齐 Level B。

#### 7.1.5 message generation 约束

Route 1 的 global message 生成约束必须区别于 multi-intent prompt：

1. 输出只表达一个主意图。
2. supporting edits 只作为 evidence，不作为并列 intent 枚举。
3. 禁止把 test / config / cleanup 机械写入并列谓词。
4. 优先生成“主目标压缩表达”，而不是“变更列表汇总”。

期望输出：

```text
fix session cache invalidation handling
```

不期望输出：

```text
fix cache invalidation and update tests and adjust config
```

### 7.2 Route 2: multi-intent construction

Route 2 用于构造 Level C / D。

#### 7.2.1 输入来源

候选 source commits 应来自不同主目标的 atomic / A-tier source commits。v1 推荐优先约束：

1. 来源 repo 一致。
2. precheck 后 `patch_conflict_risk` 可接受。
3. 每个 source commit 本身具有较高 source confidence。

#### 7.2.2 Level C 与 Level D 的采样策略

Level C 和 Level D 不应混为一类“multi-intent”样本，而应通过结构特征做目标采样：

1. Level C：优先采样 `shared_file_count` 低、`identifier_overlap_score` 低、`dependency_hint_score` 低的组合。
2. Level D：优先采样 `shared_file_count >= 1`、且 `identifier_overlap_score` 或 `dependency_hint_score` 进入 medium / high bucket 的组合。
3. 若 overlap 过高且实体类型高度同质，可能是 near-duplicate pair，应 skip 或降权，而不是无条件归为 Level D。

#### 7.2.3 edit-to-intent assignment

Route 2 的核心标签是 `edit-to-intent assignment`。v1 推荐以 hunk-level assignment 为主：

1. 每个 hunk 保留 provenance id 和 intent id。
2. shared-file 情况下，不因 interleaving 丢失 hunk 到 intent 的映射。
3. 若后续引入 AST edit atoms，它们只能作为辅助语义，不替代 hunk-level 主标签。

#### 7.2.4 message generation 约束

Route 2 的 global message 必须覆盖多个 intent：

1. 至少覆盖所有主 intent。
2. 支持 Step3 学习 `intent ordering`。
3. 禁止使用 `Change 1 / Change 2`、`Intent 1 / Intent 2` 等人工标记。
4. 输出应是自然的 multi-intent message，而不是按来源序号拼接。

#### 7.2.5 输出

Route 2 输出时：

1. `intent_count in {2, 3}`。
2. `intent_cardinality in {multi-2, multi-3}`。
3. `structure_pattern` 依据 separable / entangled 判定。
4. `training_focus` 对齐 Level C 或 Level D。

---

## 8. 3.2.6 拟真扰动实现方案

### 8.1 基本约束

拟真扰动的目标是削弱人工拼接痕迹，而不是制造新的语义变化。v1 只允许 presentation-level perturbation。

允许改变：

1. diff 的呈现顺序。
2. 上下文格式与 header 风格。
3. source boundary 的显著性。
4. 文件级和 hunk 级的自然排序方式。

禁止改变：

1. 代码语义。
2. identifier 本身。
3. hunk 内容。
4. edit-to-intent assignment。
5. 任何会导致 patch apply 或 hunk header 不合理的重排。

可以把约束写成：

```text
perturbation 只能改变 diff 的呈现顺序、上下文格式和边界显著性；
不能改变代码语义；
不能改 identifier；
不能改 hunk 内容；
不能改变 edit-to-intent assignment。
```

### 8.2 Interleaving

Interleaving 指把不同 source / intent 的 hunks 按自然顺序交错排列，以削弱“先 source A、后 source B”的人工边界。

设计原则：

1. interleaving 的目标不是随机打乱，而是恢复更接近真实 patch 的自然排列。
2. 优先按 hunk line number 排序。
3. 只有 line number 不可靠时，才使用轻度 alternating。
4. 不能破坏 patch apply 或 hunk header 的合理性。

按 Level 的默认策略：

| Level | interleaving 策略 |
|---|---|
| Level A | 不需要 |
| Level B | 可用于 evidence ordering，但不制造多意图边界 |
| Level C | 通常只做文件级自然排序，不强制同文件交织 |
| Level D | 重点使用，但优先 `line_order` |

v1 建议支持的 `strategy`：

1. `none`
2. `file_natural_order`
3. `line_order`
4. `alternating_light`

其中 `alternating_light` 只能作为 `line_order` 不可靠时的 fallback，且应在 metadata 中明确记录原因。

### 8.3 Context normalization

Context normalization 的目标是统一 diff 的包装格式，消除 source construction 的外部痕迹，而不是删除真实结构信息。

统一内容：

1. diff header。
2. 路径格式。
3. hunk context window。
4. 文件排序策略。
5. 换行与空白格式。

移除内容：

1. commit hash
2. Author
3. Date
4. `source 1 / source 2`
5. `Change 1 / Change 2`
6. 人工拼接分隔符

保留内容：

1. file path
2. hunk header
3. 必要 context lines
4. added / removed lines

建议标准格式：

```diff
diff --git a/path b/path
--- a/path
+++ b/path
@@ -l,s +l,s @@
 context lines...
```

### 8.4 Identifier overlap control

Identifier overlap control 只能通过采样控制实现，不能通过代码 token 改写实现。

实现原则：

1. 不通过重写变量名、函数名来制造或降低 overlap。
2. 只通过 source selection / source grouping 把样本放入目标 overlap bucket。
3. Level C 目标是 low overlap。
4. Level D 目标是 medium / high overlap。
5. overlap 过高且实体类型几乎一致时，更可能是 near-duplicate pair，应 skip 或降权。
6. Level B 的 `main_topic_coherence` 不是 multi-intent overlap；不能把二者混用。

v1 可使用如下 bucket：

```text
low:        [0.00, 0.10]
medium:     (0.10, 0.30]
high:       (0.30, 0.60]
too_high:   > 0.60
```

若采用 distribution-derived thresholds，则应将 bucket 边界由经验区间改为分位数边界，并记录 `threshold_source`。

### 8.5 Style normalization

Style normalization 分为 diff style 和 message style 两部分。

#### 8.5.1 Diff style

需要做：

1. 统一文件排序。
2. 统一 hunk 排序。
3. 去掉人工分隔符。
4. 统一换行。
5. 统一路径前缀与 header 格式。

不能做：

1. 改代码风格。
2. 改缩进。
3. 重新格式化源码。
4. 改 identifier。

#### 8.5.2 Message style

需要避免：

1. `Change 1 / Change 2`
2. `Intent 1 / Intent 2`
3. 多个 conventional prefixes
4. 分号式机械拼接
5. 纯来源枚举式 message

message quality filter 应记录 `artifact_score` 或等价字段，用于衡量 message 是否仍保留明显 synthetic artifact。

---

## 9. Perturbation Metadata 设计

每条样本都必须同时记录：

```text
perturbation_plan
perturbation_applied
```

要求：

1. 如果某项没有执行，必须记录 `reason`。
2. 所有扰动都必须可审计。
3. `label_mapping_preserved` 必须显式记录。

推荐 schema 如下：

```json
{
  "perturbation_plan": {
    "interleaving": {
      "enabled": true,
      "strategy": "line_order",
      "reason": "Level D shared-file entangled sample"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "remove source boundary artifacts"
    },
    "identifier_overlap_control": {
      "bucket": "medium",
      "method": "sampling_only",
      "reason": "target Level D overlap band"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "normalize diff and message style"
    },
    "label_mapping_preserved": true
  },
  "perturbation_applied": {
    "interleaving": {
      "enabled": true,
      "strategy": "line_order",
      "reason": "reliable hunk line numbers available"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "applied to all files"
    },
    "identifier_overlap_control": {
      "bucket": "medium",
      "method": "sampling_only",
      "reason": "selected pair landed in target bucket"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "source markers and multi-prefix artifacts removed"
    },
    "label_mapping_preserved": true
  }
}
```

若某项未执行，也必须保留原因：

```json
{
  "perturbation_applied": {
    "interleaving": {
      "enabled": false,
      "strategy": "none",
      "reason": "Level C sample with no shared file and natural file order already sufficient"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "always-on normalization"
    },
    "identifier_overlap_control": {
      "bucket": "low",
      "method": "sampling_only",
      "reason": "selected for Level C"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "message artifacts removed"
    },
    "label_mapping_preserved": true
  }
}
```

---

## 10. Realism Score 设计

### 10.1 轻量公式

v1 推荐使用轻量、可执行、可审计的 realism score：

$$
\rho = s_{structure} \times s_{interleave} \times s_{context} \times s_{overlap} \times s_{style}
$$

其中每个子项都取值于 `[0,1]`。

### 10.2 子项解释

| 子项 | 含义 | v1 解释 |
|---|---|---|
| `s_structure` | 是否满足对应 Level 定义 | 满足 hard rules 记为 1；边界样本按偏离程度折减 |
| `s_interleave` | hunk 排列是否自然 | `line_order` 或无需 interleaving 时得分高；fallback `alternating_light` 略降 |
| `s_context` | context normalization 是否完成且无明显 source boundary | header、path、context window 一致且无人工边界时得分高 |
| `s_overlap` | overlap 是否落在目标 bucket | Level C 偏 low，Level D 偏 medium/high；偏离目标 bucket 时降分 |
| `s_style` | diff / message 是否无明显 synthetic artifact | 多前缀、来源枚举、人工分隔符等越少，得分越高 |

### 10.3 与训练权重的关系

若启用样本权重，研究记号上可写为：

$$
\omega_{syn} = \omega_{src} \times \omega_{pair} \times \rho \times \omega_{msg}
$$

若需要避免样本权重过小，研究记号上可加 clipping：

$$
\omega_{syn}^{clip} = \max(\omega_{min}, \omega_{src} \times \omega_{pair} \times \rho \times \omega_{msg})
$$

字段对齐说明：

1. 上述 `\omega_src / \omega_pair / \omega_msg` 是研究层记号。
2. 当前代码中的对应字段名是：
   - `sample_confidence`
   - `pair_quality_weight`
   - `message_quality_weight`
3. 当前代码的 `final_sample_weight` 使用：
   - `sample_confidence * pair_quality_weight * rho * message_quality_weight`

实现要求：

1. 当前代码已让 `realism_score` 经 `rho` 进入 `final_sample_weight`。
2. `realism_weight_config` 必须记录权重字段名与公式。
3. clipping 若未来启用，必须配置化；当前代码尚未实现 clipping。
4. 不建议把 v1 的轻量 score 误写成 learned discriminator。

推荐记录：

```json
{
  "realism_weight_config": {
    "enabled": true,
    "clipping_enabled": true,
    "min_weight": 0.20,
    "weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight"
  }
}
```

---

## 11. Step2 Curriculum Order 与导出接口

### 11.1 职责划分

Step2 与后续训练阶段必须明确拆开：

```text
Step2 负责构造、标注、拟真评分和 curriculum-ready metadata 导出；
Step3 负责把这些 Step2 产物接入下游训练任务。
```

因此，不应把课程学习表述为“等 Step3 sampler 再来定义”。当前更准确的写法是：

1. Step2 生成带有 `difficulty_level`、`intent_cardinality`、`structure_pattern`、`realism_score`、`rho` 的样本池。
2. Step2 记录内部控制顺序：`sample construction -> difficulty feature extraction -> difficulty level assignment -> realism feature / score -> joint weight metadata`。
3. 下游阶段可以按这些字段决定训练消费方式，但不改变它们的定义归属。

### 11.2 下游消费接口

后续下游训练至少应能直接消费以下字段：

```json
{
  "difficulty_level": "B",
  "difficulty_name": "single-intent complex",
  "intent_cardinality": "single",
  "structure_pattern": "complex",
  "realism_score": 0.84,
  "rho": 0.84,
  "final_sample_weight": 0.71,
  "training_focus": [
    "main_intent_identification",
    "evidence_selection",
    "supporting_edit_aggregation",
    "message_compression"
  ]
}
```

其中：

1. `difficulty_level` 是 curriculum bucket 主键。
2. `intent_cardinality` 和 `structure_pattern` 用于 ablation 和细粒度切片。
3. `realism_score`、`rho` 和 `final_sample_weight` 用于 bucket 内部排序、过滤或概率加权。
4. `training_focus` 是解释性字段，不参与训练逻辑，但便于分析和报表。

### 11.3 推荐课程顺序

| training phase | Level A | Level B | Level C | Level D |
|---|---:|---:|---:|---:|
| warmup | 60% | 30% | 10% | 0% |
| early | 35% | 35% | 25% | 5% |
| middle | 20% | 30% | 35% | 15% |
| late | 10% | 25% | 35% | 30% |

这个顺序体现的 Step2 difficulty curriculum 假设是：

1. 先学主意图识别。
2. 再学复杂单目的 evidence selection。
3. 再学 separable multi-intent。
4. 最后学 entangled multi-intent。

### 11.4 建议消融

建议至少覆盖以下 ablation：

```text
No curriculum
Old multi-intent only
Without Level B
Without Level D
Easy-to-hard
```

其中：

1. `Old multi-intent only`：只用 Level C / D，验证 complex single-intent 被忽略时的退化。
2. `Without Level B`：直接检验复杂单目的必要性。
3. `Without Level D`：检验 shared-file / overlap / dependency 难例是否真的带来增益。

---

## 12. Step2 输出 Schema

### 12.1 Canonical 字段

Step2 输出中至少应包含：

```json
{
  "difficulty_level": "B",
  "difficulty_name": "single-intent complex",
  "intent_cardinality": "single",
  "structure_pattern": "complex",
  "difficulty_features": {},
  "difficulty_assignment_meta": {},
  "training_focus": [],
  "perturbation_plan": {},
  "perturbation_applied": {},
  "realism_features": {},
  "realism_score": 0.0,
  "rho": 0.0,
  "realism_weight_config": {}
}
```

为保证可审计性，推荐额外增加：

```json
{
  "source_commit_count": 3,
  "difficulty_assignment_meta": {
    "feature_basis": "source_units",
    "threshold_source": "global_distribution_p33_p66",
    "threshold_profile_id": "run_20260513_global"
  },
  "realism_weight_config": {
    "enabled": true,
    "clipping_enabled": true,
    "min_weight": 0.20,
    "weight_formula": "sample_confidence * pair_quality_weight * rho * message_quality_weight"
  }
}
```

### 12.2 Level B 完整示例

```json
{
  "difficulty_level": "B",
  "difficulty_name": "single-intent complex",
  "source_commit_count": 3,
  "intent_cardinality": "single",
  "structure_pattern": "complex",
  "difficulty_features": {
    "intent_count": 1,
    "total_file_count": 5,
    "hunk_count": 11,
    "module_count": 3,
    "file_role_mix": 0.64,
    "main_topic_coherence": 0.84,
    "shared_file_count": 1,
    "shared_file_ratio": 0.20,
    "same_file_hunk_count": 2,
    "identifier_overlap_score": 0.18,
    "max_pairwise_identifier_overlap": 0.18,
    "avg_pairwise_identifier_overlap": 0.11,
    "module_overlap_score": 0.71,
    "dependency_hint_score": 0.28,
    "patch_conflict_risk": 0.03
  },
  "difficulty_assignment_meta": {
    "feature_basis": "source_units",
    "threshold_source": "global_distribution_p33_p66",
    "threshold_profile_id": "run_20260513_global"
  },
  "training_focus": [
    "main_intent_identification",
    "evidence_selection",
    "supporting_edit_aggregation",
    "message_compression"
  ],
  "perturbation_plan": {
    "interleaving": {
      "enabled": true,
      "strategy": "file_natural_order",
      "reason": "preserve natural evidence ordering without introducing fake multi-intent boundaries"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "remove source-construction wrappers"
    },
    "identifier_overlap_control": {
      "bucket": "not_applicable_multi_intent_bucket",
      "method": "sampling_only",
      "reason": "Level B relies on topic coherence rather than multi-intent overlap"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "suppress synthetic list-style message artifacts"
    },
    "label_mapping_preserved": true
  },
  "perturbation_applied": {
    "interleaving": {
      "enabled": true,
      "strategy": "file_natural_order",
      "reason": "applied as evidence ordering only"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "applied to final diff"
    },
    "identifier_overlap_control": {
      "bucket": "not_applicable_multi_intent_bucket",
      "method": "sampling_only",
      "reason": "no token rewrite performed"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "removed source labels and multi-prefix message template"
    },
    "label_mapping_preserved": true
  },
  "realism_features": {
    "s_structure": 1.00,
    "s_interleave": 0.96,
    "s_context": 1.00,
    "s_overlap": 0.95,
    "s_style": 0.93,
    "message_artifact_score": 0.93,
    "source_boundary_removed": true
  },
  "realism_score": 0.85
}
```

### 12.3 Level D 完整示例

```json
{
  "difficulty_level": "D",
  "difficulty_name": "multi-intent entangled",
  "source_commit_count": 2,
  "intent_cardinality": "multi-2",
  "structure_pattern": "entangled",
  "difficulty_features": {
    "intent_count": 2,
    "total_file_count": 3,
    "hunk_count": 8,
    "module_count": 1,
    "file_role_mix": 0.42,
    "main_topic_coherence": 0.33,
    "shared_file_count": 1,
    "shared_file_ratio": 0.33,
    "same_file_hunk_count": 4,
    "identifier_overlap_score": 0.41,
    "max_pairwise_identifier_overlap": 0.41,
    "avg_pairwise_identifier_overlap": 0.41,
    "module_overlap_score": 0.79,
    "dependency_hint_score": 0.38,
    "patch_conflict_risk": 0.05
  },
  "difficulty_assignment_meta": {
    "feature_basis": "intent_units",
    "threshold_source": "global_distribution_p33_p66",
    "threshold_profile_id": "run_20260513_global"
  },
  "training_focus": [
    "fine_grained_edit_to_intent_alignment",
    "shared_file_decomposition",
    "identifier_overlap_disambiguation",
    "dependency_aware_planning"
  ],
  "perturbation_plan": {
    "interleaving": {
      "enabled": true,
      "strategy": "line_order",
      "reason": "shared-file entanglement should look like a natural patch rather than source-block concatenation"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "remove source boundary artifacts while preserving file and hunk structure"
    },
    "identifier_overlap_control": {
      "bucket": "medium",
      "method": "sampling_only",
      "reason": "target Level D overlap band without identifier rewrite"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "remove source labels and list-style message artifacts"
    },
    "label_mapping_preserved": true
  },
  "perturbation_applied": {
    "interleaving": {
      "enabled": true,
      "strategy": "line_order",
      "reason": "hunk line numbers were reliable on shared files"
    },
    "context_normalization": {
      "enabled": true,
      "context_window": 3,
      "header_policy": "standard_git_diff",
      "reason": "applied to all files"
    },
    "identifier_overlap_control": {
      "bucket": "medium",
      "method": "sampling_only",
      "reason": "selected pair landed in target bucket"
    },
    "style_normalization": {
      "enabled": true,
      "reason": "message filter removed synthetic connective artifacts"
    },
    "label_mapping_preserved": true
  },
  "realism_features": {
    "s_structure": 1.00,
    "s_interleave": 0.92,
    "s_context": 1.00,
    "s_overlap": 0.82,
    "s_style": 0.90,
    "message_artifact_score": 0.90,
    "source_boundary_removed": true
  },
  "realism_score": 0.68
}
```

---

## 13. Step2 Summary 指标

Step2 summary 中必须至少报告以下指标：

```text
Level A/B/C/D count and ratio
intent_cardinality distribution
structure_pattern distribution
file_count / hunk_count / module_count distribution
shared_file_count / shared_file_ratio distribution
identifier_overlap distribution
dependency_hint_score distribution
main_topic_coherence distribution
interleaving applied ratio
context normalization applied ratio
style normalization applied ratio
label_mapping_preserved ratio
realism_score mean / p50 / p90
low-realism count
```

补充要求：

1. 若启用了 `multi-3`，必须额外报告 `multi-2 / multi-3` 分布。
2. 对 `identifier_overlap`、`dependency_hint_score`、`main_topic_coherence` 建议同时报告 overall 和 per-level 分布。
3. `low-realism count` 必须与配置中的 `tau_realism_low` 对齐，并在 summary 里注明阈值来源。

---

## 14. v1 / v2 实施路线

### 14.1 v1 必须包括

1. Level A/B/C/D schema。
2. difficulty feature calculation。
3. Level assignment。
4. Route 1 complex single-intent construction 设计。
5. Route 2 multi-intent construction 设计。
6. context normalization。
7. line-order interleaving。
8. sampling-only identifier overlap control。
9. perturbation metadata。
10. lightweight realism score。
11. summary statistics。
12. curriculum-ready export interface。

### 14.2 v1 不做

```text
AST-level dependency graph
semantic-changing perturbation
identifier rewrite
code token modification
real-vs-synthetic discriminator
performance-driven curriculum
```

### 14.3 v2 可以做

```text
AST edit atom extraction
dependency graph
realism discriminator
performance-driven curriculum
real repo distribution calibration
multi-3 formal extension
manual realism validation
```

---

## 15. 论文实验设计与评估矩阵

本节描述的是 `plan-2` 进入论文实验阶段后，建议如何组织主实验、对照实验、消融实验与报告口径。除非对应字段和导出器已落地到 `code/` 与 `tests/`，本节默认属于 planned research protocol，而非当前代码已自动完成。

### 15.1 研究问题（Research Questions）

建议将论文实验至少组织为以下四个研究问题：

1. `RQ1`：修正后的 Level A/B/C/D 分层，是否比旧的 multi-intent-only 设计更贴近真实 repo 结构？
2. `RQ2`：complex single-intent construction（Level B）是否能为 Step3 提供独特且必要的训练信号？
3. `RQ3`：realism perturbation 是否能降低 synthetic artifact，并提升 Step3 在真实复杂 commit 上的泛化？
4. `RQ4`：difficulty-aware curriculum 是否比无课程或简单 easy-to-hard 更有效？

这四个问题分别对应：

1. 结构建模是否更合理；
2. 训练数据覆盖是否更完整；
3. synthetic 数据是否更像真实数据；
4. Step3 学习策略是否真正受益。

### 15.2 主实验矩阵

建议主实验矩阵按“数据构造策略 × 课程策略”组织。

最小主实验集：

| experiment id | Step2 data recipe | Step3 sampling recipe | 目的 |
|---|---|---|---|
| `E0` | old multi-intent-only surrogate | no curriculum | 旧方案近似对照 |
| `E1` | Level A/C/D only | no curriculum | 检验缺失 Level B 的影响 |
| `E2` | Level A/B/C only | no curriculum | 检验缺失 Level D 的影响 |
| `E3` | Level A/B/C/D | no curriculum | 完整数据但无课程 |
| `E4` | Level A/B/C/D | easy-to-hard fixed schedule | 结构化课程主实验 |
| `E5` | Level A/B/C/D + realism perturbation | easy-to-hard fixed schedule | 主推荐方案 |

其中：

1. `E0` 用于近似复现旧的“复杂度主要来自 multi-intent”思路。
2. `E3 -> E4` 检验 curriculum 的独立贡献。
3. `E4 -> E5` 检验 realism perturbation 的独立贡献。

### 15.3 baseline 与对照

建议 baseline 分三类：

#### 15.3.1 数据构造 baseline

1. `Old multi-intent only`
2. `No Level B`
3. `No Level D`
4. `No realism perturbation`

#### 15.3.2 课程 baseline

1. `No curriculum`
2. `Uniform sampling`
3. `Easy-to-hard fixed schedule`

#### 15.3.3 few-shot / message baseline

若论文需要隔离 Step2 message 质量影响，建议额外控制：

1. `with few-shot`
2. `without few-shot` 或 `generic-only fallback`

但这类 baseline 只建议作为附加分析。因为当前 formal 协议要求 few-shot 为 mandatory，若做这类实验，必须明确标注为 non-paper-valid diagnostic run，而不是主结果。

### 15.4 ablation 设计

除前文已有 ablation 建议外，推荐补充以下几类：

1. `Without Level B`
2. `Without Level D`
3. `Without realism perturbation`
4. `Without context normalization`
5. `Without interleaving`
6. `Sampling-only overlap control off`
7. `Default thresholds vs distribution-derived thresholds`
8. `multi-2 only vs multi-2 + multi-3`

每个 ablation 都应对应一个明确问题，而不是只为了“多做表”。

### 15.5 评估指标建议

论文评估至少应区分 Step2 指标与 Step3 指标。

#### 15.5.1 Step2 指标

1. Step3-ready yield
2. precheck skip rate
3. generation failure rate
4. true message reject rate
5. few-shot failed rate
6. few-shot generic fallback rate
7. realism score 分布
8. 各 difficulty level 的样本产量和占比

#### 15.5.2 Step3 指标

建议至少覆盖：

1. main intent identification
2. edit-to-intent assignment
3. intent count prediction
4. multi-intent message coverage
5. 在真实复杂 commit 评测集上的 end-task 指标

若最终 Step3 任务是 commit message generation / decomposition / alignment，则应将这些指标映射到对应任务定义，但论文中必须明确“哪个指标回答哪个研究问题”。

### 15.6 分层评估（per-level evaluation）

若采用 Level A/B/C/D 作为训练结构标签，评估时不应只看 overall。建议至少报告：

1. overall
2. Level A slice
3. Level B slice
4. Level C slice
5. Level D slice

原因：

1. 只看 overall 很容易掩盖 Level B 或 Level D 上的退化。
2. 若 Level B 改善显著但 overall 提升不大，仍可能构成支持新分层的重要证据。
3. Level D 是最难 slice，应单独观察是否真正受益于 perturbation 与 curriculum。

### 15.7 统计报告与显著性

若论文主结论依赖多个实验设置之间的差异，建议：

1. 每个主实验至少跑 3 个 seeds
2. 报告 mean ± std
3. 对主指标报告 paired significance test 或 bootstrap confidence interval

推荐最小统计口径：

```text
mean
std
absolute delta
relative delta
95% CI or paired significance
```

如果实验资源有限，无法做完整显著性检验，也应至少：

1. 报告多 seed 结果；
2. 明确哪些差异仅是 descriptive，而不是 statistically validated。

### 15.8 人工审查协议（manual review）

为避免只依赖自动指标，建议对 Step2 至少抽样做人工审查。

#### 15.8.1 审查目标

建议抽查三类问题：

1. `difficulty label` 是否合理
2. `realism perturbation` 是否保留语义且减少了明显拼接痕迹
3. `synthetic_subject` 是否 faithful、自然、覆盖充分

#### 15.8.2 抽样策略

建议每个 level 至少抽样固定数量，例如：

```text
Level A: 30
Level B: 30
Level C: 30
Level D: 30
```

若资源不足，至少保证：

1. 每个 level 都有样本
2. Level B 与 Level D 的抽样数不低于其它层级

#### 15.8.3 审查表

建议人工审查记录以下维度：

1. `level_label_correct`：0/1
2. `intent_count_correct`：0/1
3. `message_faithful`：0/1/partial
4. `message_natural`：1-5
5. `artifact_visible`：0/1
6. `realism_plausible`：1-5
7. `keep_for_step3`：0/1

若有两名审查者，建议报告一致性，例如 Cohen's kappa 或简单 agreement。

### 15.9 威胁与局限（Threats to Validity）

论文中建议显式讨论以下威胁：

#### 15.9.1 内部效度

1. `main_topic_coherence`、`identifier_overlap_score`、`dependency_hint_score` 仍带启发式误差。
2. Route 1 与 Route 2 的边界在部分样本上可能模糊。
3. automatic realism score 不是 learned discriminator，可能与人工感知不完全一致。

#### 15.9.2 外部效度

1. source pool 来自 A-tier commits，可能与低质量真实 commit 分布不同。
2. few-shot pool 的来源、规模与风格会影响 message generation 的泛化。
3. 当前 repo 分布、语言分布、模块结构分布可能不代表更广泛生态。

#### 15.9.3 构念效度

1. Level A/B/C/D 是否完全刻画“训练难度”仍需实证验证。
2. realism_score 只刻画部分拟真性，未覆盖真实开发时序和作者风格等因素。
3. Step3 指标与“真实 commit 理解能力”之间并非一一等价。

#### 15.9.4 结论效度

1. 单 seed 结果不稳定。
2. 若只报告 overall，不足以支撑关于 Level B 或 Level D 的结论。
3. 若没有人工审查，自动指标可能夸大 synthetic quality。

### 15.10 论文附录建议内容

建议在附录中至少提供：

1. Step2 formal protocol 简表
2. few-shot 审计口径
3. Level A/B/C/D 定义表
4. 主实验矩阵
5. ablation 列表
6. 多 seed 结果表
7. 人工审查 rubric
8. failure case study
9. artifact case study

---

## 16. 导师确认清单

实现前建议确认以下问题：

1. 是否接受 Level A/B/C/D 作为正式替代分层。
2. 是否接受“复杂单目的 commit”作为主训练对象之一，而不是只关注 multi-intent。
3. `multi-3` 是否在 v1 中仅作为扩展实验，而非主实验依赖。
4. `main_topic_coherence` 是否作为 Route 1 的核心 gate。
5. `identifier_overlap_score + dependency_hint_score` 是否作为 Level C / D 的主区分信号。
6. 阈值是否优先采用 distribution-derived thresholds。
7. 若分布阈值不稳定，是否允许 v1 使用默认阈值并记录 `threshold_source`。
8. 拟真扰动是否严格限制为 presentation-level perturbation。
9. `interleaving` 是否优先采用 `line_order`，而不是随机交错。
10. `realism_score` 在 v1 中是只用于 summary，还是同时进入 `rho` / `final_sample_weight`。
11. 是否接受 difficulty curriculum 的定义、顺序与联合权重字段都归属于 Step2。
12. 是否需要抽样做人工 realism validation，验证 Level B 与 Level D 的标签边界。

---

## 17. 最终推荐结论

本节最终建议如下：

1. 正式采用 Level A / B / C / D，而不再沿用旧的 Level 1-4。
2. 明确 `structure_pattern` 是条件化字段：`single` 下为 `simple / complex`，`multi` 下为 `separable / entangled`。
3. 把 `3 intents` 从“独立难度等级”降为 `intent_cardinality` 属性。
4. 在 Step2 内显式支持两条正式构造路线：Route 1 complex single-intent construction，Route 2 multi-intent construction。
5. 让 realism perturbation 只做 presentation-level 操作，不改代码语义、不改 identifier、不改 edit-to-intent assignment。
6. 让 Step2 负责构造、难度课程设计、拟真评分与联合权重标注，Step3 只消费这些导出结果。

这样修正后，Step2 输出将同时覆盖：

1. 真实 repo 中大量存在的复杂单目的 commit。
2. 结构边界清楚的 multi-intent commit。
3. 共享文件、identifier overlap 和轻度依赖下的 entangled multi-intent commit。

这比“只把复杂度理解为 multi-intent 的不同强度”更贴近真实仓库分布，也更适合作为 Step3 弱监督训练的结构化输入。
