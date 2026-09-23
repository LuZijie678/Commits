# MICA: 面向多意图 Commit 的证据归因与可信 Commit Message 生成方案

> 状态：历史 / 上游方案说明
> 本文档记录的是 MICA 较早期、范围更宽的上游方案讨论，用于解释后续 `MICA_v3_trainable_algorithm_plan.md` 的收缩来源。
> 它不是当前目标方案，也不是当前实现状态的事实来源。
> 当前目标方案：`docs/plans/MICA_v3_trainable_algorithm_plan.md`
> 当前实现状态：`docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md`

## 0. CCF-A 严厉复审结论：可训练版重构要求

本节作为最终重构约束写入方案。其目的不是继续增加模块，而是将 MICA 从“复杂系统方案”收缩为一个可训练、可复现、可发表的方法。

### 0.1 当前版本如果被拒稿，主要原因会是什么

以 ICSE/FSE/TOSEM 级别审稿标准看，当前方案最危险的问题不是研究方向，而是**贡献边界与训练目标仍然过宽**。

1. **九项总损失不可训练、不可解释。**  
   $L_multi + L_count + L_align + L_role + L_cohesion + L_anti + L_cons + L_gen + L_faith$ 如果同时训练，会被认为是 loss engineering。审稿人会要求解释每一项的监督来源、梯度冲突、权重选择和必要性。当前数据条件下，`role/cohesion/faith` 很难都有可靠 gold supervision。

2. **主任务和辅助任务混在一起。**  
   MICA 的主 claim 是 evidence-grounded latent intent attribution，但文档中 role、latent cohesion、generation、verifier、retrieval 都容易被读成主方法。这样会导致论文像“多模块系统”，而不是一个清晰算法贡献。

3. **真实监督不足以支撑所有结构输出。**  
   当前强监督主要来自 Step2 $k=2$ separable synthetic；M alignment pool 仍小；shared-file/$k>=3$ 不足。因此可以主张 count-aware attribution，但不能主张完整恢复 `core/support/auxiliary`、`supports/enables/conflict` 等细粒度语义关系。

4. **generation 风险遮蔽 attribution 贡献。**  
   如果主表大量强调 commit message 分数，审稿人会把文章归类为普通 CMG，并用 LLM prompting baseline 攻击。MICA 必须把 generation 固定为 attribution 的 downstream validation，而不是第二个大算法。

5. **可复现性风险。**  
   如果依赖复杂静态分析、retrieval、verifier、reranker、LLM relation annotation，复现门槛过高。主方法必须能用 edit-unit extraction + observable evidence features + slot decoder + count/alignment losses 复现。

### 0.2 最小可接受修改

#### 核心贡献

最终只卖一件事：

```text
count-aware, evidence-grounded latent intent attribution
```

论文三条贡献必须对应三个可验证对象：

1. **Formulation**：将多意图 commit 理解定义为 evidence-grounded intent attribution，统一 binary detection、intent count、edit/hunk attribution 和 structured intent plan。
2. **Method**：提出 MICA，一个 count-aware latent intent slot model，用 compositional weak supervision、dual-cardinality count 和 anti-over-splitting 约束学习 unordered intent factors。
3. **Evaluation Protocol**：在 RealDomainBinary、hard_b、real alignment benchmark 和 human faithfulness eval 上验证 attribution 与 message grounding。

不要把 PaDIG、retrieval、verifier、global composer、role taxonomy 或 latent cohesion taxonomy 单独写成贡献。

#### 模型结构

最终主模型必须收缩为四个必要组件：

```text
edit units
  -> lightweight evidence graph encoder
  -> count-aware latent intent slot decoder
  -> evidence attribution head
  -> structured intent plan renderer
```

其中：

- Evidence Graph Encoder 只使用 observable features，不声称恢复真实程序依赖。
- Slot decoder 输出 unordered slots 和 slot existence。
- Attribution head 输出 edit/hunk-to-slot assignment。
- Intent plan 是 primary output；message 是 plan 的 deterministic/semi-template rendering。

#### 训练协议

训练必须从“五阶段复杂 recipe”收缩为三阶段，并且每阶段只优化与该阶段监督相匹配的目标：

```text
Stage 1: Synthetic attribution pretraining
  supervised by Step2 strict/reuse edit_to_intent

Stage 2: Real-domain calibration
  supervised by hard_b k=1, M censored k>=2, and small real alignment calib

Stage 3: Evidence-locked generation tuning
  supervised by intent plan/message pairs, with attribution model frozen or lightly tuned
```

严禁在 Stage 1 同时训练复杂 generation/verifier objective；严禁在 M 只有 censored label 时当作 $k=2$ 强监督。

#### Loss

主方法的可训练 loss 必须改成**主损失 + 阶段性附加项**，而不是一个九项总和。

主损失：

$$
L_main = L_count + lambda_align * L_align + lambda_exist * L_exist
$$

真实域适配附加项：

$$
L_adapt = L_hard_anti_split + L_M_censored + lambda_cons * L_aug_consistency
$$

生成阶段附加项：

$$
L_msg = L_plan_json + lambda_cov * L_coverage_proxy
$$

其中 $L_role$、$L_cohesion$、$L_faith$ 不进入主训练目标。它们只能作为：

- diagnostic auxiliary loss；
- ablation；
- reranking/verifier 的 post-hoc metric；
- 或 appendix extension。

#### 评估

主评估必须围绕 attribution，而不是围绕 CMG：

1. RealDomainBinary detection；
2. hard_b false positive / over-splitting rate；
3. intent count accuracy / MAE；
4. real alignment benchmark：pairwise F1、ARI、B-cubed、hunk F1；
5. message intent coverage / faithfulness human eval；
6. anti-shortcut：size/path/template/mask/OOD；
7. oracle-k 与 predicted-k gap；
8. synthetic-only、+hard_b、+M weak、+real calib 的 staged ablation。

### 0.3 必须降级为 optional/ablation 的 fancy component

以下组件不能作为主方法必要条件：

```text
core/support/auxiliary role prediction
latent cohesion relation taxonomy
SUPPORTS / ENABLES / CONFLICT relation prediction
retrieval controlled verbalizer
verifier-guided reranking
DPO/RLHF-style message tuning
precise interprocedural call graph
full dataflow slicing
LLM pairwise relation annotation
shared-file deep entanglement handling
k>=3 full decomposition
```

这些组件可以进入 appendix、ablation 或 future work，但主结论不能依赖它们。

必须保留的组件只有：

```text
edit/hunk unit extraction
observable evidence features
latent intent slots
dual-cardinality count
Hungarian evidence-first matching
edit/hunk attribution loss
hard_b anti-over-splitting
M censored real-domain calibration
structured intent plan output
```

### 0.4 最终认可条件

我会认可的最终版本必须满足以下条件：

1. 主文中 MICA 的定义不超过一个清晰模型图和一个主 objective。
2. 主 objective 只包含 count、existence、alignment 三个核心监督信号。
3. 真实域适配只加入 hard_b anti-split、M censored 和小规模 real alignment calibration。
4. Generation 不作为主贡献，只作为 attribution 的 downstream proof。
5. 至少有一个真实 alignment test set，否则 attribution claim 不成立。
6. hard_b FPR 必须进入主表，证明模型没有把复杂单意图过拆。
7. 所有 k>=3/shared-file/deep entanglement 结果只作为 stress test。

### 0.5 第二轮复审硬条件

第二轮我会检查以下硬条件，任何一项失败都应降级 claim：

```text
H1. 是否删除九项总损失，改为分阶段主 objective。
H2. 是否提供 hard_b-test 的 FPR 和 over-split rate。
H3. 是否有完全隔离的 M-final-test，不参与 pseudo label、threshold、prompt、retrieval、reranker tuning。
H4. 是否有 >=100 条真实 final-test alignment 样本；若没有，不允许写强 attribution claim。
H5. 是否报告 oracle-k vs predicted-k，区分 count error 与 alignment error。
H6. 是否有 flat classifier / no-slot decoder baseline。
H7. 是否有 direct generation / no intent plan baseline。
H8. 是否证明 gain 不是来自 diff size、file path、synthetic template 或 retrieval leakage。
H9. 是否将 role/cohesion/verifier/retrieval 全部标为 optional 或 ablation。
H10. 摘要和结论是否只声称 low-cardinality k=2/weakly-entangled 场景。
```

若上述硬条件满足，MICA 才是一个可训练、可复现、可发表的方法，而不是一个复杂工程系统。

## 1. 方案定位

本方案面向当前项目 Step2/Step2.5 之后的下一阶段研究：在已有 synthetic 多意图数据、strict/reuse/residual 防泄漏协议、`hard_b` 真实复杂单意图数据、`M` 真实多意图数据和 RealDomainBinary 真实域评测集的基础上，设计一个能够识别多意图 commit、预测 intent count、完成 hunk/edit-to-intent alignment，并生成准确 commit message 的智能化算法。

基于共识是：

> 不应把论文主贡献写成“更强的 commit message generator”，而应写成“commit message generation 前缺失的 evidence-grounded intent attribution layer”。

最终方法命名为：

```text
MICA: Multi-Intent Commit Attribution for Faithful Message Generation
```

核心主张为：

> MICA is a count-aware latent intent attribution framework that predicts a small unordered set of evidence-grounded intent slots from edit units, aligns hunks to active slots, and uses the resulting structured intent plan as a faithful intermediate representation for commit message generation.

也就是说，MICA 的主贡献不是 LLM 生成、不是 retrieval、不是普通图聚类，而是：

```text
count-aware, evidence-grounded latent intent attribution
```

生成只是该归因结构的下游应用，用于证明结构化 intent attribution 能提升多意图 commit message 的 coverage、faithfulness 和 traceability。

## 2. 项目现状与可用数据

### 2.1 已完成的数据资产

当前项目已完成 Step2/Step2.5，关键事实如下：

1. **Step1 高可信单意图 source pool**

   - 数量：`5099`
   - 字段：`repo`, `sha`, `type`, `subject`, `message`, `git_diff`, `source_confidence`, `model_prob`, `rule_weight` 等。
   - 用途：作为 Step2 synthetic multi-intent 的 atomic source。
2. **Step2 same-repo synthetic multi-intent**

   - 当前正式主线：$k=2$ separable
   - Step3-ready 数量：`19137`
   - 关键字段：
     - `synthetic_diff`
     - `edit_units`
     - `edit_to_intent`
     - `hunks[].gold_intent_id`
     - `intent_types`
     - `intent_subjects`
     - `intent_messages`
     - `synthetic_subject`
     - `message_status`
     - `final_sample_weight`
3. **Step2.5 bootstrap export 与 leakage control**

   - 已有 `strict`, `reuse_ablation`, `residual_k1_ablation`。
   - `strict` 目前：
     - $k1 = 713$
     - $k2 = 1800$
     - hard leakage gate = `passed`
4. **hard_b**

   - 真实复杂单意图 commit。
   - 作用：防止模型学到“大 commit = 多意图”的 shortcut。
   - 当前 integrated 数量约 `1545`。
5. **M**

   - 真实多意图 commit。
   - 当前主要用于真实域评测、recall pressure test 和 alignment annotation pool。
   - M alignment annotation pool 当前 `128` 条候选。
6. **RealDomainBinary**

   - 真实域核心二分类 benchmark。
   - negative class：held-out `hard_b_test_challenge`
   - positive class：held-out `M_test`
   - balanced test：`618`
   - natural-prior test：`2171`
   - leakage gate = `passed`

### 2.2 当前限制

必须诚实承认以下限制，并将其写入方法边界：

1. 当前 synthetic 主体仍以 $k=2$ separable 为主。
2. $k>=3$ 正式主干数据不足。
3. shared-file entangled / deep entanglement 尚未形成大规模正式监督。
4. M alignment pool 只有 128 候选，Round0 尚未形成正式双标结果。
5. 当前 Step3-v0 只做到 $k=1$ vs $k>=2$ 二分类，且 CodeBERT baseline 还停留在 smoke 阶段。

因此，MICA 的主 claim 应限定为：

```text
common low-cardinality tangled commits,
primarily k=2 separable / weakly entangled cases
```

$k>=3$、shared-file、deep entanglement 应作为 stress test 和 future work，而不是主胜利场景。

## 3. 研究问题重定义

传统 commit message generation 通常将任务定义为：

```text
diff -> message
```

这对多意图 commit 不够，因为单句 message 很容易漏掉某些 intent，或者生成模糊的“update files / fix issues”。

MICA 将任务重定义为：

```text
diff -> evidence-grounded intent attribution -> structured intent plan -> rendered commit message
```

给定 commit diff $C$，模型预测：

```text
(multi_label, K, A, P, M)
```

其中：

- $multi_{\text{label}}$：是否为多意图 commit。
- $K$：intent count。
- $A$：edit-unit / hunk 到 intent slot 的 attribution。
- $P$：structured intent plan。
- $M$：由 intent plan 渲染出的 commit message。

核心输出不是一段文本，而是一个可以审计的 intent plan：

```json
{
  "intent_count": 2,
  "is_multi_intent": true,
  "intents": [
    {
      "intent_id": "I1",
      "edit_unit_ids": ["e3", "e4"],
      "role": {
        "core": ["e3"],
        "support": ["e4"],
        "auxiliary": []
      },
      "type": "fix",
      "scope": "auth",
      "subject": "fix validation for expired session tokens",
      "body": "Reject expired tokens before session lookup.",
      "evidence": ["e3", "e4"]
    },
    {
      "intent_id": "I2",
      "edit_unit_ids": ["e7"],
      "role": {
        "core": ["e7"],
        "support": [],
        "auxiliary": []
      },
      "type": "docs",
      "scope": "api",
      "subject": "document expired-token error responses",
      "body": "Add API docs for expired-token responses.",
      "evidence": ["e7"]
    }
  ],
  "rendered_message": "fix auth token validation and document expired-token responses\n\n- fix validation for expired session tokens\n- document expired-token error responses"
}
```

注意：

- structured JSON intent plan 是 primary output。
- rendered commit message 是 secondary output。
- `core/support/auxiliary` 是弱监督辅助结构，不作为主 claim 的必要正确性指标。

## 4. MICA 总体架构

MICA v2 的最终架构如下：

```text
git diff
  -> M0 Diff/Edit Unit Normalizer
  -> M1 Evidence Graph Encoder
  -> M2 Count-aware Latent Intent Slot Decoder
  -> M3 Evidence Attribution Layer
  -> M4 Structured Intent Plan Builder
  -> M5 Evidence-locked Message Renderer
```

### 4.1 M0: Diff/Edit Unit Normalizer

输入是原始 `git_diff`，输出 edit units、hunks、file metadata 和基础结构特征。

每个 edit unit $x_i$ 包含：

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

推荐第一版 edit unit 粒度：

1. hunk-level edit unit 作为主粒度。
2. 对大型 hunk 可进一步拆分为 AST/action-level edit units。
3. 训练和评估主指标以 hunk/edit-unit 级为主，不直接从 token 级开始。

### 4.2 M1: Evidence Graph Encoder

专家一致建议将 PaDIG 降级为 Evidence Graph Encoder 的实现，而不是独立主贡献。原因是程序依赖图在多语言真实项目中很难成为“真值图”，更稳妥的表述是：

```text
observable evidence features + learned latent cohesion
```

也就是说，MICA 构建的是 typed candidate evidence graph，而不是真值程序依赖图。

#### 4.2.1 双轴关系设计

关系分为两条轴：

**Observable Program Relation**

这些关系来自 diff、路径、轻量静态分析和启发式规则：

```text
same_hunk
same_file / proximity
same_symbol
same_function_or_method
call/use/import relation, if available
test_target
doc_refers_to
config/build/lockfile relation
lexical / identifier overlap
historical co-change, optional
```

**Latent Intent Cohesion**

这些不是输入真值边，而是由下游 alignment/count/message 目标塑形的潜在关系：

```text
core_same
supports_core
enables_but_distinct
parallel_related
unrelated
conflict
```

关键约束：

- `SAME_INTENT` 不作为输入边。
- `SUPPORTS / ENABLES / CONFLICT` 不作为强监督关系标签，除非后续有真实标注。
- Observable relations 只作为 slot attention bias、候选边和辅助特征。
- Latent cohesion 由 downstream losses 间接学习。

#### 4.2.2 Edge-to-Partition Semantics

每类 latent cohesion 对 partition 的作用不同：

```text
core_same:
  strong merge evidence

supports_core:
  attach support unit to the supported primary intent
  but do not create a standalone intent unless it has independent topic/type

enables_but_distinct:
  dependency-aware ordering evidence
  weak or no merge evidence

parallel_related:
  semantically related but may remain separate

unrelated:
  no merge evidence

conflict:
  split evidence
```

这使得程序依赖和意图聚合不再混淆。程序依赖不等于同一意图。

#### 4.2.3 MVP 必需静态分析特征（MVP最小可实现单元）

MVP 不依赖完整 call graph/dataflow，只使用跨语言更稳定的特征：

```text
file path
hunk index
line span
changed line count
add/delete/modify ratio
same hunk / adjacent hunk
file role classifier: source/test/doc/config/build/lockfile/generated/format-only
tree-sitter AST node/action, if available
changed function/method/class
changed identifiers and symbols
test-target linking
manifest/config detection
sparse candidate graph
```

可选扩展：

```text
precise interprocedural call graph
full dataflow slicing
type inference
LSP cross-reference
dynamic test coverage
issue/PR context
LLM pairwise relation annotation at inference time
```

这些扩展不应作为主方法依赖。

### 4.3 M2: Count-aware Latent Intent Slot Decoder

给定 edit-unit 表示：

$$
X = \{x_i\}_{i=1}^N
$$

MICA 预测一个无序 latent intent set：

$$
Y = \{y_j\}_{j=1}^{Kmax}
$$

每个 slot 定义为：

$$
y_j = (p_j, a_j, role_j, plan_j, g_j)
$$

其中：

- $p_j$：slot existence probability。
- $a_j$：edit/hunk attribution vector。
- $role_j$：slot 内部 evidence role，分为 core/support/auxiliary。
- $plan_j$：evidence-locked structured intent plan。
- $g_j$：per-intent generated message。

slot 是 latent intent object，不是普通 cluster id，也不是普通 message clause。

#### 4.3.1 Slot Attention / Set Prediction

模型使用 $Kmax$ 个 learnable intent queries：

$$
q_1, q_2, ..., q_Kmax
$$

推荐：

$$
Kmax = 4
$$

作为主实验默认值；$Kmax \in \{4, 6, 8\}$ 做 sensitivity。虽然模型容量支持更高 K，但主 claim 仍然是 low-cardinality commit。

slot attention 可写为：

$$
score_{ij} = q_j^T W x_i + b_{ij}^{graph}
$$

其中 $b_{ij}^{graph}$ 来自 observable evidence graph 的 relation bias。assignment 通过 slot 维度 softmax 得到：

$$
a_{ij} = softmax_j(score_{ij})
$$

### 4.4 M3: Dual Cardinality Count Prediction

专家一致认为 count 不能只靠 slot existence 阈值，也不能只靠单独 count head。最终采用 dual cardinality。

#### 4.4.1 Slot Existence

每个 slot 输出：

$$
p_j = sigmoid(w^T z_j)
$$

#### 4.4.2 Commit-level Count Head

全局池化后输出：

$$
P_count(k | X) = softmax(f_pool(X))
$$

#### 4.4.3 Poisson-binomial Consistency

由 slot existence 得到：

$$
P_pb(k | X) = P(sum_j Bernoulli(p_j) = k)
$$

训练 count loss：

$$ L_count = CE(P_count, k^*) + CE(P_pb, k^*) + lambda_cal * KL(P_count || P_pb) $$

对于 M 中只有 $k >= 2$ 的真实多意图样本，不可当作 $k=2$ 监督，只能使用 censored loss：

$$
L_M = -log sum_{k=2..Kmax} P_count(k)
$$

对于 hard_b：

$$
L_hard = -log P_count(k=1)
$$

推理时：

$$ k_hat = argmax_k [ log P_count(k) + beta * log P_pb(k) - lambda_complexity * k ] $$

然后选择 top-$k_{\text{hat}}$ 个 active slots。

### 4.5 M4: Evidence Attribution 与 Hungarian Matching

由于 intent slots 无序，训练时必须使用 permutation-invariant loss。采用 Hungarian matching 或早期 Sinkhorn warmup。

#### 4.5.1 Evidence-first Matching Cost

给定 gold intent $m$ 与 predicted slot $j$，matching cost：

$$ C_{jm} = lambda_e * C_edit(a_j, a_m^*) + lambda_h * C_hunk(h_j, h_m^*) + lambda_t * C_type(t_j, t_m^*) + lambda_s * C_subject(s_j, s_m^*) $$

权重优先级：

$$
lambda_e, lambda_h > lambda_t, lambda_s
$$

原因是 MICA 的核心是 attribution，不应让生成文本相似性或生成难度主导 matching。

推荐：

$$ C_edit = 1 - Dice(a_j, a_m^*) + BCE(a_j, a_m^*) $$

$$ C_hunk = 1 - IoU(h_j, h_m^*) + BCE(h_j, h_m^*) $$

$$ C_type = CE(t_j, t_m^*) $$

$$ C_subject = 1 - cos(s_j, s_m^*) $$

主方法不在 Hungarian matching 中加入 $C_{\text{gen}}$。$C_{\text{gen}}$ 只能作为 appendix 消融项，因为语言相似性会把 evidence-first matching 拉回 language-first matching，并可能污染 alignment/count 训练。

#### 4.5.2 可训练目标：主 objective 与阶段性附加项

严禁将所有目标写成一个九项总损失。MICA 的主方法必须能用一个稳定、可解释的 attribution objective 训练：

$$ L_main = L_count + lambda_exist * L_exist + lambda_align * L_align $$

其中：

- $L_count$：dual-cardinality count loss，包含 commit-level count、Poisson-binomial count 和二者 consistency。
- $L_exist$：slot existence BCE。对 matched gold intent 的 slot 标为 active，对 unmatched slot 标为 inactive。
- $L_align$：edit/hunk-to-intent attribution loss，以 Dice/BCE/IoU 为主。

这是论文主方法的唯一核心训练目标。它直接对应 MICA 的主 claim：count-aware evidence attribution。

真实域适配阶段只允许加入与真实 weak labels 匹配的轻量附加项：

$$ L_stage2 = L_main + lambda_hard * L_hard_anti_split + lambda_M * L_M_censored + lambda_cons * L_aug_consistency $$

其中：

- $L_hard_anti_split$：hard_b 样本约束为 $k=1$，惩罚 active slot 过多和 edit units 被过拆。
- $L_M_censored$：M 中只有 $k>=2$ 时使用 censored likelihood，不把它当 $k=2$。
- $L_aug_consistency$：path/message marker masking、diff perturbation 后的 count/alignment 稳定性。

generation 阶段单独训练，不反向主导 attribution：

$$ L_stage3 = L_plan_json + lambda_cov * L_coverage_proxy $$

其中：

- $L_plan_json$：intent plan 到 structured JSON/per-intent message 的条件生成损失。
- $L_coverage_proxy$：生成内容覆盖 active slots 的代理目标，可用 clause-slot matching 或 entity/action coverage 近似。

以下目标不进入主训练 objective：

```text
L_role
L_cohesion
L_faith
retrieval ranking loss
verifier/reranker loss
DPO/RLHF-style preference loss
```

它们只能作为 diagnostic、optional ablation、post-hoc verifier 或 appendix extension。这样做的原因是当前真实标注不足以支撑这些细粒度语义监督；若强行放入主 loss，会使论文被认为是不可复现的 loss engineering。

### 4.6 Core / Support / Auxiliary Role

本节是 optional diagnostic structure，不是 MICA 主 claim。为处理 test/doc/config/support changes，slot 内部可以区分：

```text
core_units:
  实现主要意图的 source/config/build 变更

support_units:
  tests/docs/examples/changelog that validate or describe core_units

auxiliary_units:
  lockfile, generated files, formatting, metadata updates
```

重要约束：

- $role_j$ 不参与 intent count 决策。
- $role_j$ 不进入主 objective。
- $role_j$ 不作为主实验强 claim。
- support/auxiliary 不应自动形成新的 intent。
- message generation 可以优先使用 core + high-confidence support。
- auxiliary 默认不进入 subject。
- 如果没有真实 role 标注，role 只能由启发式产生，并作为 ablation 或 error analysis。

#### 4.6.1 Test Support Changes

对于 test edit unit，预测：

```text
p_attach(test_unit -> source_intent_slot)
p_standalone(test_unit)
```

规则：

```text
if TEST_TARGET(test, source) high and source slot exists:
  prefer attach as support

if test changes introduce independent test maintenance:
  allow standalone test intent

if test unit has no target source in commit:
  no attach loss
```

#### 4.6.2 Doc Support Changes

doc 分为：

```text
support doc:
  documents changed API/behavior

independent doc:
  typo, README restructuring, unrelated guide update
```

判断依据：

```text
symbol names in doc
code blocks
CLI flags
API path strings
config keys
same module name in path/header
```

#### 4.6.3 Config / Build / Lockfile

config 分为：

```text
runtime config:
  can be core behavior intent

build/CI config:
  often support infra intent

dependency manifest / lockfile:
  dependency update intent or support for source change
```

lockfile 应特殊处理：

```text
lockfile-only with manifest -> attach to dependency intent
lockfile plus source feature -> auxiliary unless dependency itself is semantically important
```

### 4.7 Evidence-locked Generation

MICA 不把 generation 作为第二个主贡献。generation 用于验证 attribution 的实际价值。

#### 4.7.1 Primary Output

主输出是 structured JSON intent plan。

#### 4.7.2 Secondary Output

rendered commit message 由 deterministic 或 semi-template composer 产生：

```text
<aggregate subject>

- <intent 1 subject/body>
- <intent 2 subject/body>
```

global composer 不应自由生成大量新内容，避免引入 hallucination。

#### 4.7.3 Evidence Lock

evidence-locked generation 至少包含以下约束：

```text
每个 generated clause 必须对应一个 active slot
每个 slot message 只能访问该 slot 的 assigned evidence
message 中的 identifier/API/file/module/action 必须来自 assigned evidence 或 repo style vocabulary
unsupported claim 被 verifier 或 loss 惩罚
```

可用技术：

```text
decoder cross-attention mask
KL(decoder_attention || slot_attribution)
entity copy constraint
unsupported action/entity verifier
```

第一版主方法建议只实现前两类最小约束：

```text
1. 每个 intent message 只能访问该 slot 的 assigned evidence。
2. rendered message 由 active slot messages 确定性组合。
```

$KL(\text{decoder\_attention} \parallel \text{slot\_attribution})$、entity copy constraint 和 unsupported verifier 只作为可选增强或 ablation。不要让 generation 约束成为主方法不可复现的依赖。

#### 4.7.4 Retrieval 与 Verifier 的位置

slot-level retrieval 可以作为 optional enhancement：

```text
diff -> intent slots -> per-slot query -> leak-safe retrieval -> verbalizer
```

但 retrieval 不是主创新。

verifier/reranker 也作为 safety layer 和 ablation，而不是主贡献。第一版主方法使用 verifier-guided reranking 即可，DPO 放 optional / appendix。

## 5. 训练协议

五阶段训练已被专家收缩为三阶段，以避免工程拼装感。

### Stage 1: Compositional Weak Pretraining

数据：

```text
Step2 strict synthetic
reuse/residual as diagnostic or auxiliary
Step1 high-confidence k=1 source
```

主目标：

```text
learn edit-to-intent attribution
learn slot existence and count under compositional supervision
```

优化目标：

$$
L_stage1 = L_main
$$

其中 $L_{\text{main}} = L_{\text{count}} + lambda_{\text{exist}} * L_{\text{exist}} + lambda_{\text{align}} * L_{\text{align}}$。Stage 1 不训练 verifier，不训练 retrieval，不训练 role/cohesion，不让 generation loss 影响 attribution encoder。

使用字段：

```text
edit_units
edit_to_intent
hunks[].gold_intent_id
intent_types
intent_subjects
intent_messages
synthetic_subject
final_sample_weight
```

重要注意：

- 主结果以 strict split 为准。
- reuse 只能用于诊断、上限、pretraining 消融，不能污染主表。
- 不把 synthetic binary multi classifier 当最终表示目标，避免 k=2 separable shortcut。

### Stage 2: Real-domain Adaptation / Calibration

数据：

```text
hard_b-train/dev
M-weak-train/dev
M-align-calib
```

目标：

```text
hard_b anti-over-splitting
M censored k>=2 loss
path/marker/template perturbation consistency
threshold/count calibration
```

优化目标：

$$ L_stage2 = L_main + lambda_hard * L_hard_anti_split + lambda_M * L_M_censored + lambda_cons * L_aug_consistency $$

`MIL separation` 和 `pseudo alignment consistency` 只能在 high-confidence 情况下作为 $L_{\text{aug\_consistency}}$ 的实现方式，不能写成强监督 alignment。M 的弱标签只提供 $k>=2$ censored pressure 和 real-domain calibration，不提供完整 intent decomposition gold。

hard_b 用法：

```text
hard_b-train:
  anti-over-splitting loss
  hard negative contrastive training
  boundary suppression

hard_b-dev:
  tune over-splitting penalty and thresholds

hard_b-test:
  final FPR_hard_b only
```

M 用法：

```text
M-weak-train:
  censored k>=2 loss
  high-confidence MIL-style count pressure
  high-confidence consistency candidates only

M-weak-dev:
  tune weak adaptation

M-align-calib:
  small supervised calibration

M-final-test:
  final real-domain detection/alignment/generation/human eval
```

严禁：

```text
M-final-test 参与 pseudo-label generation
M-final-test 参与 active learning rule tuning
M-final-test 参与 prompt/example selection
M-final-test 参与 verifier/reranker tuning
```

### Stage 3: Evidence-locked Generation Tuning

目标：

```text
intent plan -> per-intent subject/body
intent plan -> deterministic/semi-template rendered message
faithfulness and coverage tuning
```

generation 训练主张：

```text
不是训练一个更强 CMG
而是证明 attributed intent plan 能产生更完整、更少 hallucination、更可审计的 message
```

优化目标：

$$ L_stage3 = L_plan_json + lambda_cov * L_coverage_proxy $$

推荐默认设置：

```text
freeze attribution encoder/slot decoder
train only plan-to-message renderer
report oracle-alignment generation and predicted-alignment generation separately
```

如果允许轻微 joint tuning，只能使用很小 learning rate，并必须报告是否损害 alignment/count。generation loss 不得主导 slot matching。

默认论文主方法不做 joint tuning；若作为 appendix variant 尝试 joint tuning，必须显式 stop-gradient 或冻结 attribution backbone，并单独报告 alignment/count 是否退化。

## 6. 数据拆分与标注要求

### 6.1 hard_b 拆分

建议：

```text
hard_b-train: 50-60%
hard_b-dev:   20%
hard_b-test:  20-30%
```

硬约束：

- `hard_b-test` 必须完全隔离。
- 不参与训练、threshold tuning、pseudo labeling、reranking tuning。
- 主表必须报告 $FPR_{\text{hard\_b}}$ 和 single-intent over-split rate。

### 6.2 M 拆分

建议：

```text
M-weak-train: 60-70%
M-weak-dev:   10%
M-align-calib: 10-15%
M-final-test: 15-20%
```

如果 M 中只有 $k>=2$，只能用 censored loss，不可当 $k=2$。

### 6.3 真实 Alignment Benchmark

这是 MICA 成立的硬门槛。没有真实 alignment test set，MICA 的核心 attribution claim 不成立。

最低可接受：

```text
>=300 full-alignment commits overall
>=100 final-test-aligned commits
>=100 double-annotated commits
```

更稳妥：

```text
500 full-alignment commits
150 double-annotated commits
2,000 commit-level binary/count labels
```

标注内容：

```text
是否 multi-intent
intent count
hunk/edit-unit-to-intent assignment
每个 intent 的 concise message
core/support/auxiliary, optional
shared/uncertain hunk, optional
annotator confidence
```

agreement 指标：

```text
binary Cohen/Fleiss kappa
intent count exact agreement / MAE
hunk assignment ARI / NMI / pairwise F1
message semantic agreement by human rating
```

如果无法达到最低标注量，应将论文降级为 dataset/protocol + preliminary method，而不是完整方法论文。

## 7. 推理流程

给定一个真实 commit diff：

```text
1. Normalize diff into edit units/hunks.
2. Extract observable evidence features.
3. Build sparse candidate evidence graph.
4. Encode edit units with graph-aware encoder.
5. Decode Kmax latent intent slots.
6. Predict P_count(k), P_pb(k), and slot existence.
7. Select active slots by dual-cardinality decision.
8. Assign edit units/hunks to active slots.
9. Separate assigned units into core/support/auxiliary.
10. Build structured intent plan.
11. Generate per-intent subject/body from evidence-locked plan.
12. Render aggregate commit message deterministically or semi-template.
13. Run verifier/reranker if enabled.
14. If evidence support fails, downgrade to conservative message.
```

保守 fallback 示例：

```text
update config validation and related tests
```

优于 unsupported hallucination：

```text
fix memory leak in config parser
```

## 8. 实验设计

### 8.1 主实验 1：Real-domain Detection

数据：

```text
RealDomainBinary-test
hard_b-test
M-final-test weak labels, if available
```

指标：

```text
AUROC
AUPRC
Macro-F1
Balanced Accuracy
FPR_hard_b
ECE
```

对比：

```text
diff-size heuristic
metadata LR/SVM
TF-IDF baselines
CodeBERT/GraphCodeBERT/UniXcoder/CodeT5 classifier
LLM zero/few-shot prompting
synthetic-only MICA
MICA + hard_b
MICA + M weak
full MICA
```

### 8.2 主实验 2：Intent Count 与 Alignment

数据：

```text
M-final-test-aligned
hard_b-test-aligned subset, if annotated
synthetic strict test for controlled evaluation
```

指标：

```text
intent count exact accuracy
intent count MAE
within-1 accuracy
over-segmentation rate
under-segmentation rate
pairwise F1
ARI
NMI
B-cubed F1
hunk-level micro/macro F1
```

必须包含：

```text
oracle-k
predicted-k
synthetic-only
full MICA
```

### 8.3 主实验 3：Evidence-grounded Message Generation

评估设置：

```text
oracle alignment generation
predicted alignment end-to-end generation
```

主指标：

```text
intent coverage
evidence support / faithfulness
hallucination rate
missing-intent rate
extra-intent rate
specificity
human acceptability
```

辅助指标：

```text
BERTScore
CodeBERTScore
ROUGE-L
BLEU
```

BLEU/ROUGE 只作为辅助，不作为主 claim 证据。

### 8.4 主实验 4：End-to-End Success

定义：

```text
E2E strict success =
  correct multi/single decision
  AND correct or tolerated intent count
  AND hunk/edit alignment above threshold
  AND all major intents covered by generated messages
  AND no severe unsupported claim
```

同时报告 relaxed success：

```text
correct binary decision
AND major intents covered
AND no severe hallucination
```

### 8.5 Anti-shortcut 主表

该表必须进入主文，不应只放 appendix。

至少包含：

```text
original
size / overlap-weighted diagnostic
path-masked
diff-marker-masked
message-template masked
hard_b-test
cross-project OOD
cross-time OOD, if available
```

目的：

- 证明模型没有只学 diff size。
- 证明模型没有只学 file path。
- 证明模型没有只学 synthetic k=2 template。
- 证明 hard_b 上不过度拆分。

### 8.6 消融实验

主文关键消融：

```text
full MICA
- hard_b anti-over-splitting
- M weak adaptation
- real alignment calibration
- evidence lock / verifier
- evidence graph features
- dual cardinality
- role core/support/aux
synthetic-only
flat classifier, no slot decoder
direct generation, no intent plan
```

### 8.7 Human Evaluation

必须有人评，因为 commit message 自动指标不可靠。

样本：

```text
100-200 commits
覆盖 M multi、hard_b、k>=3 stress、shared-file stress
```

系统：

```text
best non-LLM baseline
LLM prompting baseline
MICA full
oracle alignment upper bound
```

维度：

```text
coverage
faithfulness
specificity
separation
readability
maintainer usefulness
```

输出：

```text
pairwise win-rate
Likert mean with bootstrap CI
severe hallucination rate
missing-intent rate
```

## 9. 论文贡献写法

最终论文只建议写三条贡献。

### Contribution 1: Problem Formulation

提出 evidence-grounded multi-intent commit attribution，将多意图识别、intent count、hunk alignment 和 faithful message generation 统一为 structured prediction：

```text
diff -> latent intent slots -> evidence attribution -> intent plan -> rendered message
```

### Contribution 2: Method

提出 MICA，一个 count-aware latent intent slot model，通过 compositional weak supervision、dual cardinality count、evidence-first matching 和 anti-over-splitting constraints 学习 intent factorization。

### Contribution 3: Evaluation Protocol

基于 strict/reuse/residual、hard_b、M、RealDomainBinary 和 expert-calibrated alignment set，建立覆盖 detection、counting、alignment、message faithfulness、anti-shortcut 和 OOD 的评测协议。

不要将 retrieval、verifier、global composer、PaDIG 三层图分别写成独立贡献。它们是 supporting machinery。

## 10. 必须收缩的 Claim

不要写：

```text
MICA solves tangled commit decomposition.
MICA recovers developer true intent.
MICA handles arbitrary k>=3 and deeply entangled commits.
MICA is a SOTA commit message generator.
PaDIG recovers causal program dependence.
```

推荐写：

```text
MICA improves evidence-grounded attribution for common low-cardinality tangled commits.

MICA recovers evidence-supported semantic intents approximated by edit-unit grouping and human annotation.

k>=3 and shared-file entanglement are evaluated as stress settings.

MICA improves multi-intent message faithfulness and coverage by grounding generation in attributed intent slots.

The evidence graph provides observable structural features and learned latent cohesion, not verified causal program dependence.
```

## 11. 实施路线

### Phase 0：协议冻结，1 周

产物：

```text
DATA_CARD.md
EVAL_PROTOCOL.md
split manifest
metric scripts
leakage reports
```

确认：

- strict 是主结果 split。
- hard_b/M 的 train/dev/test 分工固定。
- M-final-test 完全隔离。
- hard_b-test 完全隔离。

### Phase 1：强 baseline，1-2 周

完成：

```text
heuristic size baseline
metadata/TF-IDF baselines
CodeBERT/UniXcoder/CodeT5 classifier
LLM prompting baseline
RealDomainBinary evaluation
hard_b FPR
size/overlap diagnostic
```

### Phase 2：MICA-Attribution MVP，2-4 周

实现：

```text
diff/edit unit extraction
MVP evidence graph features
latent intent slot decoder
dual cardinality count
Hungarian evidence-first matching
alignment/count training on strict synthetic
```

重点验证：

```text
synthetic alignment sanity
oracle-k vs predicted-k gap
zero-shot transfer to RealDomainBinary
```

### Phase 3：hard_b/M 真实域适配，2-4 周

实现：

```text
hard_b anti-over-splitting loss
M censored k>=2 loss
MIL separation
pseudo alignment consistency filter
path/marker/template perturbation consistency
```

主表开始成型：

```text
synthetic-only
+ hard_b
+ M weak
+ hard_b + M
full MICA
```

### Phase 4：真实 Alignment Benchmark，3-6 周

目标：

```text
>=300 full-alignment commits overall
>=100 final-test-aligned commits
>=100 double-annotated commits
```

如果标注资源不足：

- 先做 150 seed full alignment + active learning 150。
- 但最终 claim 要相应收缩。

### Phase 5：Evidence-locked Generation，2-4 周

实现：

```text
structured JSON intent plan generation
per-intent subject/body
deterministic rendered commit message
optional slot-level retrieval
optional verifier-guided reranking
```

同时做：

```text
oracle alignment generation
predicted alignment generation
human eval
faithfulness/coverage metrics
```

### Phase 6：反 Shortcut + OOD + 论文主实验，2-3 周

完成：

```text
path masking
diff marker masking
template split
size/overlap weighted diagnostic
cross-project OOD
cross-time OOD
k>=3 stress
shared-file stress
hard_b FPR
human eval
```

## 12. 最终结论

MICA 的最终共识方案是：

```text
count-aware, evidence-grounded latent intent attribution
```

其核心不是“更强 commit message generator”，而是为多意图 commit message generation 提供缺失的中间层：

```text
edit units
  -> latent intent slots
  -> evidence attribution
  -> structured intent plan
  -> faithful rendered message
```

该方案能够充分利用当前项目已经完成的数据资产：

- Step2 的 `edit_to_intent` 提供 compositional weak structure supervision；
- strict/reuse/residual 提供防泄漏和诊断协议；
- hard_b 提供复杂单意图反例，抑制 over-splitting；
- M 提供真实多意图弱监督和 alignment 校准来源；
- RealDomainBinary 提供真实域核心二分类 benchmark。

最终论文应主张：

> MICA improves real-domain detection, count prediction, edit-unit attribution, and evidence-grounded message rendering for common low-cardinality multi-intent commits, while explicitly reporting limitations on high-cardinality and deeply entangled cases.
