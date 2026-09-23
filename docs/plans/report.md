> supporting note / non-authoritative
> 本文档保留历史性说明与阶段性汇报内容，不定义 MICA-v3 的当前权威方案边界。
> 规范性方法表述请以 `docs/plans/MICA_v3_trainable_algorithm_plan.md`、`docs/plans/MICA_v3_trainable_algorithm_plan_cn.md` 和 `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md` 为准。

## 理想产物 / 模型能力

实验、训练的目的是为了让模型具备以下能力：

**count-aware**：模型能够预测 intent count，也就是判断一个 commit 中有几个修改意图，例如 $K=1/2/3/\ldots$。

**evidence-grounded**：每个 intent 必须绑定具体的 hunk/edit unit 证据，不能只是抽象地说“这里有一个 fix intent”或“这里有一个 docs intent”。

**latent intent attribution**：模型能够从 commit diff 中自动发现隐藏的多个修改意图，并把具体的 hunk/edit unit 分配给这些 intent。

最终主输出应是 structured intent plan。commit message 是基于 intent plan 的下游渲染结果。

## MICA 总体架构

```text
git diff
  -> M0 Diff/Edit Unit Normalizer
       拆解为 edit units / hunks，并抽取基础结构特征

  -> M1 Lightweight Evidence Graph Encoder
       编码 edit units 之间的可观察证据关系

  -> M2 Count-aware Latent Intent Slot Decoder
       预测 latent intent slots、slot existence 和初步 assignment

  -> M3 Evidence Attribution Layer
       预测 intent count，并完成 edit/hunk-to-slot attribution

  -> M4 Structured Intent Plan Builder
       将 active slots 和 assigned evidence 转换为 structured intent plan

  -> M5 Evidence-locked Message Renderer
       基于 evidence-locked intent plan 渲染 commit message
```


---

## 1. M0: Diff/Edit Unit Normalizer

M0 的输入是原始 `git_diff`，M0 会把 diff 切成多个 edit units。每个 edit unit $x_i$ 带有结构化字段：

```text
unit_id
file_path
hunk_id
old_span / new_span
patch_text
added/deleted/context lines
changed identifiers
file role
language
local context
source_sha, if available
gold_intent_id, if synthetic
```

edit unit 是后续 attribution 的最小证据单位。例如，一个 commit diff 可以被拆成：

```text
e1: 修改 src/auth/token.py 中的 token 过期判断
e2: 修改 src/auth/session.py 中的 session 校验逻辑
e3: 新增 tests/test_expired_token.py
e4: 修改 docs/api.md 中的 expired token 返回码说明
e5: 修改 README.md 的格式说明
```

M0 的作用就是把原始 diff 变成这些可被归因的证据单位。

---

## 2. M1: Lightweight Evidence Graph Encoder

M1 的作用是把每个 hunk/edit unit 看成一个节点，用文件路径、标识符、测试/文档/配置关系等可观察线索给节点之间连边，再把这些节点和边编码成模型可以理解的增强 edit-unit 表示。


### 2.1 Evidence Graph 的直观含义


```text
节点 = edit units / hunks
边 = edit units 之间的可观察关系
```

例如：

```text
e1: src/auth/token.py 修改 expired token 判断
e2: tests/test_token.py 新增 expired token 测试
e3: docs/api.md 更新 expired token 文档
e4: README.md 调整标题格式
```

M1 可能抽取出：

```text
e1 -- test_target --> e2
e1 -- doc_refers_to --> e3
e1 -- weak_or_no_relation --> e4
```

这些边是候选证据关系，这一步能让模型学到这些信息。最终是否归为同一个 intent，要由后面的 slot decoder 和 attribution loss 学出来。

### 2.2 推荐 relation / bias

MVP 阶段推荐使用可复现、跨语言较稳定的 relation/bias：

```text
same_file
same_hunk
path_distance
same_symbol
same_identifier
same_language
test_target
doc_refers_to
config/build/lockfile
generated_file
message_keyword_overlap, offline auditing / shortcut diagnosis only
```

这些关系都属于 observable evidence features，也就是可以从 diff、文件路径、标识符、轻量静态分析或启发式规则中直接得到的线索。

注意：

```text
SAME_INTENT 不作为输入边。
SUPPORTS / ENABLES / CONFLICT 不作为强监督关系标签。
Observable relations 只作为 attention bias、候选边或辅助特征。
Latent cohesion 由下游 alignment/count/message 目标间接塑形。
```

原因是 MICA 的任务本身就是预测 intent attribution。如果在输入中直接给出 `SAME_INTENT`，就等于泄漏答案。

### 2.3 实现方式

可以将每个 edit unit 编码为初始向量：

$$ h_i = Encoder(x_i) $$

再根据 edit units 之间的关系得到 pairwise relation bias：

$$ b_{ij} = RelationBias(r_{ij}) $$

然后通过 Transformer/GNN/attention-bias encoder 得到增强后的表示：

$$ H' = Transformer/GNN(H, b_{ij}) $$

其中：

```text
H  = 原始 edit-unit 表示
b_ij = edit unit i 和 edit unit j 之间的关系偏置
H' = 融合关系信息后的 edit-unit 表示
```

$b_{ij}$ 可以进入 attention bias 或 pair representation，但不作为独立的 $L_{cohesion}$ 监督目标。也就是说，不单独训练一个“cohesion relation classifier”作为主任务。

### 2.4 M1 的边界

M1 是线索层，不是判决层。

它只负责提供信息：

```text
e1 和 e2 路径接近
e1 和 e3 有测试/文档引用关系
e4 和其他 edit units 关系较弱
```

不负责直接判断：

```text
e1 和 e2 是同一个 intent
e3 是 support
e4 是 independent docs intent
```

真正的 intent 分组由 M2/M3 完成。

---

## 3. M2: Count-aware Latent Intent Slot Decoder

M2 是 MICA 的核心结构层。它接收 M1 输出的增强 edit-unit 表示，预测一组 latent intent slots。

给定 edit-unit 表示：

$$ X = \{x_i\}_{i=1}^N $$

模型预测一个无序的 latent intent set：

$$ Y = \{y_j\}_{j=1}^{Kmax} $$

其中 $Kmax$ 是任务范围内的最大候选 intent 数。本文保留历史示例：

$$ Kmax = 4 $$

这不代表每个 commit 都有 4 个 intent，也不表示 `Kmax=4` 是理论最优值；更严格的权威表述是：Kmax is a task-scope constant, not a tuned model hyperparameter。

每个 slot 可以表示为：

$$ y_j = (p_j, a_j, role_j, plan_j, g_j) $$

其中：

```text
p_j: slot existence probability，即该 slot 是否存在
a_j: edit/hunk attribution vector，即哪些 edit units 属于该 slot
role_j: slot 内部 evidence diagnostic metadata，区分 core/support/auxiliary，optional
plan_j: evidence-locked structured intent plan，后续构造
g_j: per-intent generated message，generation 阶段使用
```

Stage 1 主要关注前两个：

$$ p_j $$

$$ a_j $$

也就是 slot 是否存在，以及 edit units 如何分配到 slot。

### 3.1 latent intent slot 是什么

latent intent slot 可以理解为一个“空的意图容器”。模型会学习让每个 slot 吸收一部分 edit units。

例如一个 commit 有 5 个 edit units：

```text
e1: 修改 auth token 逻辑
e2: 修改 session 校验逻辑
e3: 新增 auth 测试
e4: 修改 API 文档
e5: 修改 README 格式
```

模型可能预测：

```text
slot1: e1, e2, e3
slot2: e4
slot3: e5
slot4: inactive
```

其中 slot1/slot2/slot3 是 latent intent slots，slot4 没有被激活。

注意，slot 不是普通 cluster id。它不只是一个聚类编号，还应该承载：

```text
这个 intent 是否存在
这个 intent 的 evidence 是哪些 edit units
这个 intent 的类型/主题/摘要是什么
这个 intent 后续如何被写入 structured plan/message
```

### 3.2 Slot Attention / Set Prediction

模型可以使用 $Kmax$ 个 learnable intent queries：

$$ q_1, q_2, \ldots, q_{Kmax} $$

这些 query 就像若干个可学习的 intent 探针。每个 query 会与每个 edit unit 计算匹配分数：

$$ score_{ij} = q_j^T W x_i + b_{ij}^{graph} $$

其中：

```text
i = edit unit index
j = slot index
q_j = 第 j 个 intent query
x_i = 第 i 个 edit unit 表示
b_ij^graph = 来自 M1 evidence graph 的 relation bias
```

然后在 slot 维度做 softmax：

$$ a_{ij} = softmax_j(score_{ij}) $$

得到：

```text
第 i 个 edit unit 属于第 j 个 slot 的概率
```

例如：

```text
        slot1  slot2  slot3  slot4
e1      0.88   0.07   0.03   0.02
e2      0.83   0.10   0.05   0.02
e3      0.79   0.15   0.04   0.02
e4      0.08   0.86   0.04   0.02
e5      0.12   0.10   0.74   0.04
```

则可以理解为：

```text
slot1 吸收 e1/e2/e3
slot2 吸收 e4
slot3 吸收 e5
slot4 inactive
```

### 3.3 Count-aware 的含义

M2 不是单纯聚类。它要和后面的 count prediction 结合。模型不仅要知道：

```text
哪些 edit units 应该分在一起
```

还要知道：

```text
当前 commit 到底应该激活几个 slots
```

这就是 count-aware。M2 输出的 slot existence 会和 M3 的 count prediction 相互校准。

---

## 4. M3: Evidence Attribution Layer

M3 负责完成两个核心任务：

```text
1. 预测 intent count
2. 完成 edit/hunk-to-slot attribution
```

它把 M2 的 latent slots 变成可训练、可评估的结构化归因结果。

### 4.1 Intent Count Prediction

MICA 不只判断 $multi\_label$，还要预测 intent count：

$$ K = 1 / 2 / 3 / \ldots $$

因此 M3 使用 dual cardinality count。它包括两条 count 路线。

第一条是 commit-level count head：

$$ P_{count}(k \mid X) = softmax(f_{pool}(X)) $$

也就是从整个 commit 的全局表示预测有几个 intent。

例如：

$$ P_{count}(k=1) = 0.10 $$

$$ P_{count}(k=2) = 0.78 $$

$$ P_{count}(k=3) = 0.10 $$

$$ P_{count}(k=4) = 0.02 $$

第二条是由 slot existence 推出的 count 分布。每个 slot 输出：

$$ p_j = sigmoid(w^T z_j) $$

例如：

```text
slot1 exists = 0.95
slot2 exists = 0.82
slot3 exists = 0.20
slot4 exists = 0.08
```

由这些 slot existence probabilities 可以得到：

$$ P_{pb}(k \mid X) $$

即 active slot 数量的 Poisson-binomial 分布。

训练时的 count loss：

$$ L_{count} = CE(P_{count}, k^*) + CE(P_{pb}, k^*) + lambda_{cal} * KL(P_{count} \parallel P_{pb}) $$

直观理解：

```text
全局 count head 要预测对；
slot existence 推导出来的 count 也要预测对；
两者要尽量一致。
```

推理时可以综合二者：

$$ k_{hat} = argmax_k [ log \, P_{count}(k) + beta * log \, P_{pb}(k) - lambda_{complexity} * k ] $$

然后选择 top-$k_{hat}$ 个 active slots。

### 4.2 Edit/Hunk-to-Slot Attribution

有了 active slots 之后，M3 还要判断每个 edit unit/hunk 应该归给哪个 slot。

模型会输出 assignment matrix：

$$ A \in \mathbb{R}^{N \times Kmax} $$

其中：

```text
A_ij = 第 i 个 edit unit 属于第 j 个 slot 的概率
```

例如：

```text
e1 -> slot1
e2 -> slot1
e3 -> slot1
e4 -> slot2
e5 -> slot3
```

这就是 evidence-grounded attribution。

### 4.3 Hungarian Matching

因为 predicted slots 是无序的，训练时不能固定要求 slot1 对 gold intent1、slot2 对 gold intent2。

例如 gold 是：

```text
gold intent A: e1, e2, e3
gold intent B: e4
```

模型预测：

```text
slot1: e4
slot2: e1, e2, e3
```

这是正确的，只是 slot 编号反了。

所以训练时需要 Hungarian matching，把 predicted slots 和 gold intents 做最优匹配：

```text
slot1 -> gold intent B
slot2 -> gold intent A
```

matching cost 应该 evidence-first：

$$ C_{jm} = lambda_e * C_{edit}(a_j, a_m^*) + lambda_h * C_{hunk}(h_j, h_m^*) + lambda_t * C_{type}(t_j, t_m^*) + lambda_s * C_{subject}(s_j, s_m^*) $$

其中主导项是：

$$ C_{edit} $$

$$ C_{hunk} $$

因为 MICA 的核心是证据归因，不应该让文本生成相似度主导 matching。

推荐：

$$ C_{edit} = 1 - Dice(a_j, a_m^*) + BCE(a_j, a_m^*) $$

$$ C_{hunk} = 1 - IoU(h_j, h_m^*) + BCE(h_j, h_m^*) $$

$$ C_{type} = CE(t_j, t_m^*) $$

$$ C_{subject} = 1 - cos(s_j, s_m^*) $$

主方法不把 $C_{gen}$ 放进 Hungarian matching。否则模型可能因为生成文本相似而被错误匹配，污染 attribution 训练。

### 4.4 主训练目标

M3 对应的核心训练目标是：

$$ L_{main} = L_{count} + lambda_{exist} * L_{exist} + lambda_{align} * L_{align} $$

其中：

```text
L_count:
  训练 intent count

L_exist:
  训练 slot existence
  matched gold intent 的 slot 应 active
  unmatched slot 应 inactive

L_align:
  训练 edit/hunk-to-intent attribution
  主要使用 Dice/BCE/IoU 等 mask loss
```

这是 MICA 的主 objective。它直接对应 MICA 的主 claim：

```text
count-aware, evidence-grounded latent intent attribution
```

---

## 5. M4: Structured Intent Plan Builder

M4 的作用是把 M2/M3 预测出来的 active slots 和 assigned evidence 转换成 structured intent plan。

M4 不只是简单输出“有几个 intent”，而是把每个 intent 的证据、类型、摘要、角色结构组织成一个可审计的 JSON 结构。

输入：

```text
active slots
edit-unit assignment
slot existence
count prediction
file role / evidence role
optional type / subject prediction
```

输出：

```json
{
  "intent_count": 2,
  "is_multi_intent": true,
  "intents": [
    {
      "intent_id": "I1",
      "edit_unit_ids": ["e1", "e2", "e3"],
      "type": "fix",
      "scope": "auth",
      "subject": "fix expired token validation",
      "evidence": ["e1", "e2", "e3"]
    },
    {
      "intent_id": "I2",
      "edit_unit_ids": ["e4"],
      "type": "docs",
      "scope": "api",
      "subject": "document expired-token responses",
      "evidence": ["e4"]
    }
  ]
}
```

### 5.1 core / support / auxiliary

M4 可以在每个 slot 内部进一步划分 evidence role：

```text
core_units:
  实现主要意图的 source/config/build 变更

support_units:
  tests/docs/examples/changelog that validate or describe core_units

auxiliary_units:
  lockfile, generated files, formatting, metadata updates
```

例如：

```json
{
  "intent_id": "I1",
  "core_units": ["e1", "e2"],
  "support_units": ["e3"],
  "auxiliary_units": [],
  "subject": "fix expired token validation"
}
```

但要注意：

```text
role_j 不参与 intent count 决策；
role_j 不进入主 objective；
role_j 不作为主实验强 claim；
support/auxiliary 不应自动形成新的 intent；
如果没有真实 role 标注，role 只能由启发式产生，并作为 ablation 或 error analysis。
```

### 5.2 M4 的价值

M4 的价值是让模型输出可审计的中间结构。

普通 commit message generation 输出：

```text
fix auth token validation and update docs
```

MICA 输出：

```text
intent_count = 2
I1 evidence = e1/e2/e3
I2 evidence = e4
rendered_message = ...
```

这样可以检查：

```text
每个 intent 是否有证据？
有没有漏掉 intent？
有没有 unsupported claim？
message 中每句话是否能追溯到 assigned evidence？
```

---

## 6. M5: Evidence-locked Message Renderer

M5 是最后的 message 渲染层。它不是 MICA 的主贡献，而是 attribution 的下游验证。

M5 的输入是 M4 生成的 structured intent plan，而不是原始 diff。它根据 active slots 和 assigned evidence 渲染 commit message。

### 6.1 Primary Output 与 Secondary Output

MICA 的 primary output 是 structured intent plan：

```text
primary output = intent plan
```

commit message 是 secondary output：

```text
secondary output = rendered message
```

这是为了避免论文被理解成普通 commit message generation。

### 6.2 Evidence-locked 的含义

Evidence-locked 表示生成过程必须受到 evidence attribution 约束。

至少满足：

```text
每个 generated clause 必须对应一个 active slot；
每个 slot message 只能访问该 slot 的 assigned evidence；
message 中的 identifier/API/file/module/action 必须来自 assigned evidence 或 repo style vocabulary；
unsupported claim 应被 verifier 或 conservative fallback 处理。
```

第一版主方法建议实现最小版本：

```text
1. 每个 intent message 只能访问该 slot 的 assigned evidence。
2. rendered message 由 active slot messages 确定性组合。
```

例如 intent plan 是：

```json
{
  "intent_count": 2,
  "intents": [
    {
      "intent_id": "I1",
      "subject": "fix expired token validation",
      "evidence": ["e1", "e2", "e3"]
    },
    {
      "intent_id": "I2",
      "subject": "document expired-token responses",
      "evidence": ["e4"]
    }
  ]
}
```

M5 可以渲染为：

```text
fix expired token validation and document expired-token responses

- fix expired token validation
- document expired-token responses
```

### 6.3 为什么不能自由生成

如果 M5 直接看完整 diff 并自由生成，可能会 hallucinate：

```text
fix memory leak in config parser
```

但 assigned evidence 中根本没有 memory leak 或 config parser。这样就破坏了 MICA 的核心：faithful message generation。

所以 M5 应优先使用 deterministic 或 semi-template renderer，而不是自由生成大量新内容。

### 6.4 Retrieval / Verifier 的位置

slot-level retrieval 可以作为 optional enhancement：

```text
intent slot -> per-slot query -> leak-safe retrieval -> verbalizer
```

verifier/reranker 也可以作为 safety layer，用来检查 unsupported claim。

但它们不是主创新，不应该作为主方法必要条件。第一版可以只做：

```text
structured intent plan
deterministic / semi-template rendered message
optional verifier-guided reranking
```

DPO/RLHF、复杂 retrieval、LLM relation annotation 都应放到 optional / appendix / future work。

---

## 7. M0–M5 的端到端例子

假设一个 commit diff 被拆成：

```text
e1: src/auth/token.py 修改 expired token 判断
e2: src/auth/session.py 修改 session validation
e3: tests/auth/test_token.py 新增 expired token 测试
e4: docs/api/auth.md 增加 expired token 返回码说明
e5: README.md 调整标题格式
```

M0 输出 edit units：

```text
x1 = e1
x2 = e2
x3 = e3
x4 = e4
x5 = e5
```

M1 提取 evidence relations：

```text
e1-e2: same_directory, identifier_overlap
e1-e3: test_target
e1-e4: doc_refers_to
e5-other: weak relation
```

M2 预测 latent intent slots：

```text
slot1: e1, e2, e3
slot2: e4
slot3: e5
slot4: inactive
```

M3 预测 count 和 attribution：

```text
intent_count = 3
slot1 active
slot2 active
slot3 active
slot4 inactive

e1/e2/e3 -> slot1
e4 -> slot2
e5 -> slot3
```

M4 构造 structured intent plan：

```json
{
  "intent_count": 3,
  "is_multi_intent": true,
  "intents": [
    {
      "intent_id": "I1",
      "edit_unit_ids": ["e1", "e2", "e3"],
      "type": "fix",
      "scope": "auth",
      "subject": "fix expired token validation",
      "evidence": ["e1", "e2", "e3"]
    },
    {
      "intent_id": "I2",
      "edit_unit_ids": ["e4"],
      "type": "docs",
      "scope": "api",
      "subject": "document expired-token response",
      "evidence": ["e4"]
    },
    {
      "intent_id": "I3",
      "edit_unit_ids": ["e5"],
      "type": "docs",
      "scope": "readme",
      "subject": "update README formatting",
      "evidence": ["e5"]
    }
  ]
}
```

M5 渲染 message：

```text
fix expired token validation and update related documentation

- fix expired token validation
- document expired-token response
- update README formatting
```

如果模型判断 e5 只是 auxiliary formatting，也可以在 M4/M5 中降低其权重，不让它进入主 subject。

---

## 8. 总结

MICA 的 M0–M5 可以概括为：

```text
M0 把 diff 拆成可归因的 edit units；
M1 用可观察关系增强 edit-unit 表示；
M2 用 latent slots 表示隐藏 intent；
M3 预测 intent count 并完成 edit-to-slot attribution；
M4 把 active slots 转成 structured intent plan；
M5 基于 evidence-locked plan 渲染 commit message。
```

---

## 附：MICA Stage 1 Attribution 已完成实验、数据与关键结论

这一部分用于给导师汇报当前 `experiment/mica-v3-attribution-mvp` 分支已经完成的 Stage 1 工作，重点是实验事实，而不是后续设想。

### 1. 实验边界

本阶段所有实验都严格限制在 Stage 1：

- 数据只使用 `Step1 atomic k=1` 和 `Step2 strict/sanity synthetic k=2`
- 主目标始终保持：
  - `L_align = 1.0`
  - `L_count = 0.5`
  - `L_exist = 0.5`
- 没有使用：
  - `hard_b`
  - `M weak`
  - `M alignment`
  - `RealDomainBinary`
  - Stage 2 loss
  - generation / retrieval / verifier
  - 任何真实 API

### 2. 已做过的实验脉络

#### 2.1 初始 tiny sanity：训练能跑，但 attribution 完全 collapse

最早的 sanity protocol 是：

- `k1_train = 100`
- `k2_train = 100`
- `k1_dev = 25`
- `k2_dev = 25`
- `epochs = 3`

关键现象：

- train loss 稳定下降；
- count head 有学习信号；
- 但 attribution 一直等于 trivial baseline。

代表性指标：

- `alignment_pairwise_f1_model_oracle_k = 0.6158`
- `alignment_pairwise_f1_all_one_cluster = 0.6158`
- `alignment_pairwise_f1_file_path_baseline = 0.96`
- `alignment_pairwise_f1_random_gold_k_mean = 0.8922`
- `assignment_top1_slot_distribution = {1: 145}`
- `k2_singleton_intent_fraction = 0.96`

结论：

- 训练链路是通的；
- 但模型几乎把所有 edit units 都压到单 foreground slot；
- 当时的数据子集也明显退化，导致 pairwise F1 被 all-one / file-path baseline 主导。

#### 2.2 Curriculum 重构：确认原 tiny subset 退化

随后对 Stage 1 synthetic 结构做了审计，并重建了 `medium curriculum`，目标是降低：

- singleton-dominated `k=2` 样本；
- file-path 直接可分样本；
- random-gold-k 也能拿高分的退化样本。

这一步的意义不是让模型“自动变好”，而是先确认前面的失败不只是坏数据导致的假阴性。

#### 2.3 直接 attribution 指标、loss correctness 与 overfit probe

在 pairwise F1 之外，又补充了更直接的 attribution 指标：

- `unit_accuracy_hungarian`
- `macro_intent_f1_hungarian`
- `k2_split_recall`
- `second_slot_gold_recall`
- `slot_collapse_rate`

同时做了两类关键 probe。

1. `L_align` correctness probe

- perfect assignment loss = `0.1533`
- all-one assignment loss = `2.3217`
- margin = `2.1684`

说明：

- `L_align` 本身是对的；
- Hungarian matching 没有结构性错误；
- “all-one 和 perfect 几乎同分”这种坏情况没有发生。

2. assignment overfit test

以下设置通过：

- `B_50_k2_only`
- `C_50_k2_plus_50_k1`
- `D_20_k2_align_only`

说明：

- assignment head 是可学习的；
- 梯度不是 0；
- 问题不在“模型根本学不会 attribution”。

#### 2.4 Slot competition / schedule ablation：定位 mixed collapse 原因

在 `medium curriculum` 上做了系统 ablation，核心结论是：

- `k2-only` generalization 能学出来；
- `k1/k2` naive mixed 在小规模下会把 second slot 压没。

最关键的对照是：

`S6 k2-only generalization`

- `k2_split_recall = 0.88`
- `second_slot_gold_recall = 0.4233`
- `unit_accuracy_gain_over_all_one = 0.1301`
- `slot_collapse_rate = 0.12`
- `count_accuracy = 1.00`

`S0 current mixed`

- `k2_split_recall = 0.00`
- `second_slot_gold_recall = 0.00`
- `slot_collapse_rate = 0.56`

这一步把问题定位成：

> assignment 可学，loss 也正确，但正常 mixed Stage 1 训练会压制 early slot specialization。

#### 2.5 Staged curriculum：T2 在 tiny mixed 上曾是最优修复

随后测试 staged schedule。tiny mixed 上，`T2_replay_protected_mixed` 是唯一满足 fix 条件的 setting。

T2 mixed-dev 指标：

- `count_accuracy_mixed = 0.78`
- `k2_split_recall_mixed = 0.92`
- `second_slot_gold_recall_mixed = 0.4867`
- `unit_accuracy_gain_over_all_one_mixed = 0.0438`
- `slot_collapse_rate_mixed = 0.12`

当时的中间结论是：

- staged replay-protected schedule 可能是 Stage 1 的最小可行修复；
- 但还不能冻结，必须扩样复现。

#### 2.6 T2 scale-up：tiny 有效，但扩样失败

之后对 T2 做了 scale-up validation，和 naive mixed 做对照。

结论是：

- Scale A: T2 复现成功；
- Scale B: T2 比 naive 有改善，但未达到阈值；
- Scale C: T2 失败，naive mixed 反而通过且更强。

Scale C 单 seed 对比：

`naive_balanced_mixed`

- `k2_split_recall = 0.8720`
- `second_slot_gold_recall = 0.5325`
- `unit_gain_over_all_one = 0.0888`
- `slot_collapse_rate = 0.1080`
- `count_accuracy = 0.9240`

`T2_replay_protected_mixed`

- `k2_split_recall = 0.6560`
- `second_slot_gold_recall = 0.3869`
- `unit_gain_over_all_one = 0.0502`
- `slot_collapse_rate = 0.2280`
- `count_accuracy = 0.9000`

这一步推翻了“直接把 T2 冻结为正式 schedule”的判断。

#### 2.7 Multi-seed candidate comparison：正式候选 schedule 改为 naive mixed

最后在更大规模上做了多 seed 对比：

- 规模：`k1_train = 500, k2_train = 500, k1_dev = 125, k2_dev = 125`
- seeds = `[13, 42, 2026]`
- 只比较：
  - `naive_balanced_mixed`
  - `T2_replay_protected_mixed`

多 seed 汇总：

| schedule | pass_rate | mean second_slot_gold_recall | mean unit_accuracy_gain_over_all_one | mean slot_collapse_rate |
|---|---:|---:|---:|---:|
| `naive_balanced_mixed` | `1.0000` | `0.5628` | `0.1002` | `0.1267` |
| `T2_replay_protected_mixed` | `0.6667` | `0.4063` | `0.0561` | `0.2333` |

最终判断：

- `candidate_schedule_validated = naive`

因此当前正式候选 Stage 1 schedule 不是 T2，而是：

- `naive_balanced_mixed_large_scale`

### 3. 当前冻结的数据与 protocol

当前已经做的是 candidate protocol/split freeze，不是正式 validation pass。

冻结下来的候选 schedule：

- `epochs = 15`
- 从 epoch 1 开始 mixed `k1/k2`
- `lambda_align = 1.0`
- `lambda_count = 0.5`
- `lambda_exist = 0.5`
- no replay
- no staged warmup
- no Stage 2 loss

formal manifest 当前建议规模：

| split | k1 | k2 | total |
|---|---:|---:|---:|
| train | `1000` | `1000` | `2000` |
| dev | `250` | `250` | `500` |
| test | `250` | `250` | `500` |

medium candidate pool：

- `medium_candidate_count_available = 3599`
- `fallback_applied = false`

formal split 结构统计：

| split | singleton_fraction | file_path_baseline_mean | random_gold_k_mean | avg_edit_units |
|---|---:|---:|---:|---:|
| train | `0.0000` | `0.5617` | `0.4288` | `8.2120` |
| dev | `0.0000` | `0.5610` | `0.4295` | `8.0320` |
| test | `0.0000` | `0.5587` | `0.4242` | `8.0920` |

和最早 tiny sanity 相比，这个 formal candidate split 更健康：

- singleton-dominated `k=2` 基本消失；
- file-path baseline 不再接近 `0.96`；
- random baseline 也明显下降；
- attribution 评估信号更可信。

### 4. Leakage / overlap 检查

hard leakage 结果：

- `sample_id_overlap_count = 0`
- `sha_overlap_count = 0`
- `synthetic_id_overlap_count = 0`

说明：

- 目前保证了 sample/sha/synthetic id 级别无硬泄漏；
- 但当前 Stage 1 synthetic split 不是 repo-disjoint；
- `repo_overlap_allowed_for_stage1_synthetic = true`，这一点在文档中已显式写明，没有伪装成 repo-disjoint。

### 5. 当前最重要的结论

1. Stage 1 的问题不是 `L_align` 错、Hungarian 错，或 assignment head 完全不可学。
2. 初始 tiny sanity 的确退化，不能直接拿来作为 attribution 成败依据。
3. 在更健康的 medium data 上，模型可以学会 second-slot attribution，说明任务本身可学。
4. 早期 collapse 的主要原因是训练 schedule 对小规模 mixed 设置过于敏感。
5. `T2` 只在 tiny scale 上有效，扩样后不稳定，不能作为正式 schedule 冻结。
6. larger-scale `naive_balanced_mixed` 在多 seed 上稳定优于 T2，因而被选为当前 candidate formal Stage 1 schedule。
7. 现在只是完成了 Stage 1 candidate protocol/split freeze，还没有完成 official Stage 1 validation。
8. **Stage 2 仍然禁止进入。**

### 6. 下一步

当前下一步不是继续发明新的 schedule，也不是进入 Stage 2，而是：

1. 在冻结的 manifest 和 candidate schedule 下，跑 official Stage 1 validation；
2. 复核 direct attribution 指标是否在正式 split 上稳定成立；
3. 只有 Stage 1 validation 通过后，才讨论是否进入下一阶段。
