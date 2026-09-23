# MICA-v3 可训练算法方案（中文整理版）

> 状态：target protocol companion
> 本文档是 `docs/plans/MICA_v3_trainable_algorithm_plan.md` 的中文 companion，用于把目标方案整理成更适合工程执行、gap 审核与论文实验设计对照的结构。
> 当前实现事实不是由本文档定义，必须以代码与 `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md` 为准。

## 0. 文档定位

本文档不声称当前仓库已经完成了 MICA-v3。
它的职责是把 MICA-v3 从“合理的算法设计文档”收口为“接近 CCF A 优秀标准的可训练、可评估、可复现实验方案”。

核心原则保持不变：

```text
Attribution is learned.
Generation is rendered.
Faithfulness is verified.
```

换句话说：

```text
主模型只学习 evidence-to-intent attribution
真实域阶段只做 split / no-split / abstain 边界校准
renderer 只消费冻结后的 structured intent plan
renderer 不能反向影响 attribution
```

## 1. Problem Boundary

### 1.1 任务定义

MICA-v3 的目标问题应统一定义为：

> bounded latent intent set attribution for low-cardinality tangled commits

输入与输出：

```text
输入：从 commit diff 规范化得到的 edit units
若样本处于目标域内：输出 1 <= k <= Kmax 的无序 foreground intent set
若样本超出目标域：输出 overflow decision
若样本处于目标域但分解低置信：输出 abstention decision
同时输出：受约束的 background evidence assignment
```

这意味着 MICA-v3 不是：

```text
普通 clustering
固定 slot 分类器
commit message generator
joint generation tuning 系统
```

### 1.2 目标域与非目标域

```text
Target domain:
  commits with 1 <= k <= Kmax, where Kmax is fixed before training according to the DATA_CARD
主场景:
  k=1 / k=2 的 low-cardinality tangled commits
  可分离或弱纠缠的多意图 commit
Out-of-scope:
  k > Kmax 的复杂 commit
  release aggregation commits
  mass refactoring commits
  dependency/vendor synchronization commits
  mechanically generated diffs
```

非目标：

```text
恢复开发者全部真实心理意图
恢复完整程序因果依赖
分解任意复杂 tangled commit
把 renderer 写成主贡献
```

### 1.3 Kmax 作为任务边界

Kmax is a task-scope constant, not a tuned model hyperparameter.

`Kmax=4` 只能写成默认 bounded-capacity setting，不能写成真实世界理论上界。

Kmax selection protocol:

```text
1. Before model training, estimate intent-cardinality distribution on train/dev annotation assets only.
2. Choose the smallest Kmax such that cumulative coverage of target low-cardinality samples reaches a pre-specified threshold tau.
3. Fix Kmax in DATA_CARD before any test evaluation.
4. Report coverage@Kmax and overflow rate on every evaluation split.
5. Never tune Kmax according to final-test attribution or message utility scores.
6. Synthetic cardinality distribution alone cannot justify Kmax, because synthetic k is construction-controlled.
7. If Kmax=4 is used in MVP, describe it as the default bounded-capacity setting, not as a claim that real commits have at most four intents.
```

必须补充：

```text
synthetic cardinality distribution alone cannot justify Kmax
```

必须保留一句硬边界：

```text
Kmax=4 is acceptable only if DATA_CARD shows that it covers the intended low-cardinality target domain.
```

还必须补一句可执行边界：

```text
Kmax=4 is a default bounded-capacity setting only after DATA_CARD freezes tau, selected_Kmax, and coverage@Kmax on train/dev annotation assets. Without populated DATA_CARD statistics, Kmax=4 remains an implementation default, not a final-paper task boundary.
```

Kmax readiness states:

```text
Final-paper state:
  Kmax is selected from manually annotated train/dev intent-count assets.
  coverage@Kmax is populated in DATA_CARD before final evaluation.

MVP state:
  If real intent-count annotations are insufficient, Kmax=4 remains an engineering default.
  No data-driven coverage claim is made in the MVP state.
  coverage@Kmax is reported only after the annotation asset is populated.
```

### 1.4 overflow / abstention

overflow / abstention 不能只写成“低置信时拒绝”，而应被定义为 selective prediction 机制。

必须先区分两个概念：

```text
overflow:
  样本超出任务边界或容量假设
  例如 k > Kmax、release aggregation、mass refactoring、dependency/vendor synchronization、mechanically generated diffs

abstention:
  样本可能处于目标域内，但模型没有足够置信释放 decomposition
  例如 assignment uncertainty 高、count disagreement 高、foreground evidence 没有被可信 slots 吸收
```

Inference decision schema:

```text
decision:
  decompose | abstain | overflow
risk_score:
  calibrated selective-risk score
overflow_evidence:
  optional evidence that the sample is outside the task boundary
abstention_reason:
  optional reason such as count_disagreement, high_assignment_entropy, or low_slot_margin
```

如果 MVP 没有 out-of-scope gold labels：

```text
The MVP exposes one reject option.
It is reported as selective abstention, not as semantic overflow detection.
Do not claim a supervised overflow classifier unless explicit overflow labels exist.
```

建议定义 decomposition risk score：

$$
r(X) =
w_1 \cdot P_{count}(Kmax)
+ w_2 \cdot JS(P_{count} \Vert P_{pb})
+ w_3 \cdot AssignmentEntropy(X)
+ w_4 \cdot ResidualForegroundMass(X)
+ w_5 \cdot LowSlotMargin(X)
$$

语义解释：

```text
P_count(Kmax):
  capacity saturation signal；表示模型顶到最大容量，不直接证明 true k 超过 Kmax
JS(P_count || P_pb):
  global count 与 slot existence 不一致
AssignmentEntropy:
  edit units 对 slots 的分配不确定
ResidualForegroundMass:
  语义 edit 没有被可信 foreground slot 吸收
LowSlotMargin:
  top slots 的竞争边界不清晰
```

Risk component definitions:

```text
ForegroundAssignmentEntropy:
  H_i^fg = - sum_j a_ij^fg log a_ij^fg over foreground slots only
  foreground-only entropy 与 foreground-plus-null entropy 分开报告

ForegroundPlusNullEntropy:
  H_i^all = - sum_j a_ij log a_ij over foreground slots plus q_null
  仅作为诊断，因为高置信 null routing 不必然表示风险高

ResidualForegroundMass:
  RFM(X) = sum_i m_i^semantic max(0, tau_fg - max_j a_ij^fg) / sum_i m_i^semantic
  m_i^semantic 排除 rule-verified background 与 unknown/ignored units

LowSlotMargin:
  Margin_i = top1_j(a_ij^fg) - top2_j(a_ij^fg)
  LowSlotMargin(X) = average over semantic units of max(0, delta - Margin_i)
```

abstention 规则：

```text
if r(X) > threshold:
  abstain / overflow
else:
  output decomposition
```

阈值协议：

```text
threshold 只能在 dev split 上固定
final test 不能调阈值
必须报告 coverage-risk curve
不能只报 covered samples 的 attribution score
```

若无 overflow gold labels：

```text
MVP 中 overflow 是 calibrated abstention，不是 fully supervised overflow classifier
若存在 k>Kmax synthetic / real complex commits，可用于 optional overflow calibration
这些样本不能污染 final test
```

Abstention / overflow calibration protocol:

```text
Risk score:
  r(X) =
    w1 * P_count(Kmax)
  + w2 * JS(P_count || P_pb)
  + w3 * AssignmentEntropy(X)
  + w4 * ResidualForegroundMass(X)
  + w5 * LowSlotMargin(X)
Default MVP setting:
  If no supervised overflow labels are available, use fixed non-learned weights:
    w1 = w2 = w3 = w4 = w5 = 1.0 after metric normalization on dev.
  Each component must be normalized on dev split only.
  No final-test statistics may be used for normalization.
Optional calibrated setting:
  If dev overflow / out-of-scope labels exist, fit a simple calibration model on dev only, such as logistic regression or isotonic calibration.
  The fitted calibration is frozen before final evaluation.
  Do not train or tune overflow calibration on final test.
Threshold selection:
  thresholds are selected on dev only.
  final test must report coverage-risk curve, not only one chosen threshold.
  if a single operating point is needed, choose it by a pre-declared target coverage or target risk on dev.
No overflow gold case:
  overflow is reported as calibrated abstention, not as a fully supervised overflow classifier.
  use coverage-risk, selective attribution F1, false abstention on in-scope commits, and forced-decomposition error where out-of-scope labels exist.
```

## 2. Method

### 2.0 Gold Alignment Provenance

Gold edit/hunk-to-intent assignments 只有在 provenance 明确且可审计时才有效。

Gold assignments 只允许来自：

```text
1. strict synthetic samples whose edit units can be deterministically traced to one and only one source atomic commit
2. manually annotated and adjudicated real alignment data
```

Strict synthetic provenance contract:

```text
each output edit unit stores source_atomic_commit_id
each output edit unit stores source_hunk_id or source_line_span when available
each output edit unit stores construction_group_id
each output edit unit stores provenance_resolution_status
each gold_intent_id is derived from a unique source atomic commit within the same synthetic construction group
```

以下 synthetic sample 必须排除在 `L_align` supervision 之外：

```text
one output hunk mixes semantic lines from multiple source atomic commits
conflict resolution rewrites semantic content
provenance mapping is incomplete
one edit unit cannot be assigned to a unique primary source intent
construction metadata is missing or inconsistent
```

以下来源不能提供 gold assignment：

```text
M weak labels do not provide gold intent assignments
hard_b labels do not provide detailed gold alignment unless manually annotated
commit messages do not provide gold intent assignments
PR titles and issue text do not provide gold intent assignments
pseudo labels do not provide final gold assignments
```

### 2.1 Edit Unit Normalizer

默认粒度为 hunk / edit-unit。

Input-side fields:

```text
unit_id
file_path
hunk_id
old_span / new_span
patch_text
added_lines / deleted_lines / context_lines
enclosing_symbol_type
enclosing_symbol_name
enclosing_symbol_signature
enclosing_symbol_old_span / enclosing_symbol_new_span
enclosing_symbol_old_text
enclosing_symbol_new_text
enclosing_symbol_resolution_status
changed_identifiers
file_role
language
source_sha
```

Input context protocol:

```text
context is function-level by default, but the edit representation is not function-only.
For each changed edit unit, the normalizer should resolve the smallest enclosing function, method, initializer, or property that contains the changed span.
Class block context is used only when the changed span is at class-level declaration scope and no smaller executable/member symbol applies.
The downstream attribution model receives both the patch span and the full before/after enclosing-symbol content.
The changed span must be explicitly marked inside the enclosing-symbol context.
If a language parser is unavailable, use a conservative lexical fallback and mark enclosing_symbol_resolution_status.
If no reliable enclosing symbol can be resolved, fall back to hunk-level context and report the fallback rate.
Large files or very large enclosing symbols may be clipped only by a pre-declared token budget policy that preserves the changed span, signature, and nearest control-flow boundaries.
```

这一定义强调：

```text
function-level context is input evidence expansion, not label expansion.
变动所在函数/方法/类的完整 before/after 内容应进入后续 attribution 模型。
不能只把修改行或 hunk patch 喂给后面。
function-level context 不得包含 commit message、PR title、issue text、gold intent id 或 synthetic construction metadata。
function-level context 不改变主监督粒度；主 assignment 目标仍然是 edit unit / hunk。
```

Representation protocol:

```text
h_patch_i:
  representation of the changed span, patch text, and explicit added/deleted/context lines
h_symbol_i:
  representation of the full before/after enclosing symbol with EDIT_START and EDIT_END markers around the changed span
h_metadata_i:
  representation of file path, language, file role, changed identifiers, and source metadata
h_i:
  Fuse(h_patch_i, h_symbol_i, h_metadata_i)
```

Function-level context efficiency protocol:

```text
encode each unique enclosing symbol once per commit
each edit unit references the shared symbol representation plus its own patch-span representation
do not duplicate the same large enclosing symbol independently for every hunk
report AST resolution success rate, lexical fallback rate, hunk-only fallback rate, clipping rate, and resolution rate by language
```

Label-side fields:

```text
gold_intent_id
gold_background_flag
gold_intent_type, optional diagnostic annotation only
```

必须区分输入字段与标签字段，避免 label leakage 表述混淆。

MVP assignment 假设：

```text
MVP assumes each semantic edit unit has one primary foreground intent.
Shared-support units are marked and reported separately, but not used as the main supervision target.
background edit units are assigned to q_null.
large mixed-intent hunks are separately reported as hard cases.
```

### 2.2 Lightweight Evidence Graph Encoder

只使用 commit-time observable evidence。若实现只是 relation bias，论文应称为 `relation-aware edit-unit encoder`，不要暗示必须实现 full GNN。

relation / bias 候选：

```text
same_file
path_distance
same_symbol
same_identifier
same_language
test_target
doc_refers_to
config/build/lockfile
generated_file
```

Conditional relation / audit-only features:

```text
same_hunk:
  enabled only when one hunk is split into multiple edit units
message_keyword_overlap:
  offline auditing / shortcut diagnosis only
  offline leakage / shortcut audit only
  not a recommended encoder relation
not used by encoder input
not used by relation construction
not used by attribution checkpoint selection
```

Graph object definition:

```text
Nodes:
  one node per normalized edit unit
Optional auxiliary nodes:
  file nodes or symbol nodes are disabled in MVP unless explicitly implemented
Edges:
  deterministic typed relations between edit-unit nodes
Direction:
  undirected by default unless a relation has natural direction, such as test_target
Relation aggregation:
  additive attention bias or typed pairwise relation embedding in the edit-unit encoder
```

所有 relation features 只能来自：

```text
the diff and repository snapshot available at commit time
```

禁止来源：

```text
gold intent labels
synthetic construction metadata
commit message
PR title
issue text
post-commit artifacts
```

### 2.3 bounded latent intent slots

方法范式统一为：

```text
bounded latent intent set prediction
evidence-to-intent attribution
structured intent plan
evidence-locked rendering
```

模型维护：

```text
Kmax 个无序 foreground latent intent slots
一个 constrained background slot
```

MICA 不是“先定 k 再分配 evidence”，而是让 slots 竞争性吸收 evidence，再由 count 与 existence 决定有效 intent 数。

Slot assignment distribution:

```text
a_ij:
  assignment probability of edit unit i to foreground slot j
a_i,null:
  assignment probability of edit unit i to q_null
a_j:
  vector [a_1j, ..., a_nj]
```

MVP primary-intent attribution 采用联合归一化 assignment distribution：

$$
\sum_{j=1}^{Kmax} a_{ij} + a_{i,null} = 1
$$

Foreground slots 与 `q_null` 对每个 edit unit 构成一个 normalized assignment distribution。Unknown units 不进入 background supervision，但仍保留在 assignment softmax 中。

Evidence-aware slot representation:

```text
MICA uses a two-way coupling between slot queries and absorbed evidence.
Existence is not predicted from an independent learned query alone.
```

给定 encoded edit-unit evidence：

$$
H'=\{h_1,\dots,h_n\},\quad h_i\in\mathbb{R}^d
$$

初始化 `Kmax` 个 foreground queries 与一个 background query：

$$
Q=\{q_1,\dots,q_{Kmax}\},\quad q_{null}
$$

先得到 contextualized foreground slot states：

$$
\tilde z_j=\operatorname{CrossAttn}(q_j,H',R)
$$

其中 `R` 是 observable evidence graph 提供的 relation-aware bias。

foreground assignment score：

$$
s_{ij}=
\frac{(W_h h_i)^\top(W_z\tilde z_j)}{\sqrt d}
+b_{ij}^{rel}
$$

background score：

$$
s_{i,null}=
\frac{(W_h h_i)^\top(W_n q_{null})}{\sqrt d}
+b_{i,null}
$$

每个 edit unit 在所有 foreground slots 与 `q_null` 上做联合 softmax：

$$
a_{ij}
=
\frac{\exp(s_{ij}/\tau_a)}
{
\exp(s_{i,null}/\tau_a)
+
\sum_{\ell=1}^{Kmax}\exp(s_{i\ell}/\tau_a)
}
$$

$$
a_{i,null}
=
\frac{\exp(s_{i,null}/\tau_a)}
{
\exp(s_{i,null}/\tau_a)
+
\sum_{\ell=1}^{Kmax}\exp(s_{i\ell}/\tau_a)
}
$$

每个 foreground slot 重构 assignment-weighted evidence summary：

$$
e_j=
\frac{
\sum_{i=1}^{n}a_{ij}h_i
}{
\epsilon+\sum_{i=1}^{n}a_{ij}
}
$$

evidence mass：

$$
m_j=\sum_{i=1}^{n}a_{ij}
$$

最终 evidence-aware slot representation：

$$
z_j=
\operatorname{LayerNorm}
\left(
\tilde z_j+
W_e e_j+
W_m\phi(m_j)
\right)
$$

其中 `phi(m_j)` 是 evidence-mass scalar embedding。这样 `p_j` 同时依赖 slot semantics、实际吸收的 evidence 和 evidence mass，避免 empty slot 高 existence 或 high-mass slot 低 existence。

### 2.4 constrained background slot

background slot 不是垃圾桶，也不是困难语义 evidence 的自由拒绝通道。

background labels are three-valued:

```text
positive background
reliable foreground
unknown / ignored
```

positive background:

```text
generated files
lockfiles
vendor/minified artifacts
pure formatting changes
mechanical import sorting
rule-verified generated snapshots
```

reliable foreground:

```text
strict synthetic 中带 gold_intent_id 的 foreground edit units
real alignment benchmark / calibration 中人工确认的 foreground evidence
```

unknown / ignored:

```text
缺少可靠 semantic/background label 的 ambiguous edits
```

监督目标改为：

$$
L_{bg} = MaskedBCE(a_{null}, y_{bg}, mask_{bg})
$$

必须明确：

```text
A semantic edit without background proof must not be treated as background positive.
不确定但有语义的 evidence 应留在 foreground competition 中
```

必须报告：

```text
background assignment rate
foreground evidence swallowed by background
foreground-to-background error
missing-intent rate by file role
```

### 2.5 dual-cardinality count head

保留：

$$
P_{count}(k|X) = softmax(f_{pool}(H'))
$$

Slot existence probability:

$$
p_j = \sigma(f_{exist}(z_j))
$$

其中 `z_j` 是 foreground slot `j` 的 contextualized representation。

Poisson-binomial cardinality distribution, denoted `P_pb`:

$$
P_{pb}(k|X) = P\left(\sum_j Bernoulli(p_j)=k\right)
$$

职责分工：

```text
L_count 监督 global cardinality
L_exist 监督 slot occupancy / set-cardinality structure
P_pb 连接 global count 与 slot-level existence
dual-cardinality consistency 是 calibration，不是额外独立 supervision claim
```

Final count decoding:

```text
Primary cardinality:
  k_hat = argmax_k P_count(k | X), for 1 <= k <= Kmax
Slot activation:
  select the top-k_hat foreground slots ranked by calibrated p_j
P_pb:
  used for L_pb, L_card_cons, calibration diagnostics, and selective-risk disagreement
  not used as the primary final-count decoder in the default protocol
```

Inference-time active-slot decoding:

```text
1. compute a_ij, a_i,null, z_j, p_j, P_count, and P_pb
2. compute k_hat = argmax P_count(k)
3. select top-k_hat foreground slots by calibrated p_j
4. mask inactive slots
5. renormalize assignment over active foreground slots plus q_null
6. construct the structured intent plan
7. compute selective risk
8. output decomposition, abstention, or overflow
```

对 active slot set `A`，assignment 重新归一化为：

$$
\hat a_{ij}
=
\frac{a_{ij}}
{
a_{i,null}
+
\sum_{\ell\in\mathcal A}a_{i\ell}
},
\quad j\in\mathcal A
$$

$$
\hat a_{i,null}
=
\frac{a_{i,null}}
{
a_{i,null}
+
\sum_{\ell\in\mathcal A}a_{i\ell}
}
$$

### 2.6 evidence-first Hungarian matching

#### Why not clustering?

Commit intent attribution is not equivalent to similarity-based clustering.

理由必须覆盖：

```text
一个 intent 可跨文件、跨语言、跨测试/文档
不同 intent 可共享文件、符号甚至同一 hunk
真实 diff 中存在 background edits
clustering 无法自然承接 count supervision、weak real-domain calibration、background routing 与 overflow handling
```

结论：

```text
similarity-based clustering may be used as a diagnostic baseline, but it does not provide the primary learning interface for MICA
MICA's primary method is bounded latent slot attribution with calibrated cardinality
```

默认 matching cost：

$$
C_{jm} = \lambda_{edit} \cdot C_{edit}(a_j, y_m) + \lambda_{hunk} \cdot C_{hunk}(a_j, y_m)
$$

必须写清：

```text
默认 matching cost 不使用 type、role、generation、faithfulness 或 message-level signal
C_type 只可作为 optional tie-breaker，不进入 MVP 主 matching
C_hunk 只在 edit units finer than hunks 或存在 hunk-level projection labels 时使用
禁止 C_gen、C_faith、C_role 进入主 matching
```

Formal `L_align`:

设 Hungarian matching 输出：

$$
\mathcal M=\{(j,m)\}
$$

其中 `j` 是 predicted foreground slot，`m` 是 gold intent。对 matched slots：

$$
L_{\text{align}}
=
\frac{1}{|\mathcal M|}
\sum_{(j,m)\in\mathcal M}
\left[
\lambda_{\text{bce}}
\operatorname{BCE}(a_j,y_m)
+
\lambda_{\text{dice}}
\left(1-\operatorname{Dice}(a_j,y_m)\right)
\right]
$$

其中：

$$
\operatorname{Dice}(a_j,y_m)
=
\frac{
2\sum_i a_{ij}y_{im}+\epsilon
}{
\sum_i a_{ij}+\sum_i y_{im}+\epsilon
}
$$

Unmatched foreground slots 不通过 `L_align` 强制 assignment mask 全零，因为 joint softmax 下总会分配一部分质量。Unmatched slots 只通过 `L_exist=0` 监督其不应存在。

### 2.7 structured intent plan

Attribution-core fields:

```text
slot_id
slot_confidence
assigned_edit_units
assigned_hunks
evidence
```

Renderer-facing derived fields:

```text
type
scope
action
object
```

Diagnostic metadata:

```text
role tags
```

约束：

```text
scope/action/object 是 attribution 之后的派生字段
它们不是 MVP attribution supervision
optional role tags 只是 diagnostic metadata
```

### 2.8 evidence-locked renderer

renderer 只消费冻结后的 structured intent plan。

必须明确：

```text
renderer does not update attribution
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
renderer 不能重新定义 count、slot existence 或 matching
```

## 3. Training Protocol

### 3.1 分层 objective

Attribution core and slot-structure supervision:

$$
L_{attr} = \lambda_{align} \cdot L_{align} + \lambda_{exist} \cdot L_{exist}
$$

Cardinality calibration:

$$
L_{card} = \lambda_{count} \cdot L_{count} + \lambda_{pb} \cdot L_{pb} + \lambda_{cal} \cdot L_{card\_cons}
$$

Background routing:

$$
L_{bg} = MaskedBCE(a_{null}, y_{bg}, mask_{bg})
$$

Optional selective risk:

$$
L_{abs} = \text{abstention / overflow calibration loss, if labels exist}
$$

Stage 1:

$$
L_{stage1} =
L_{align}
+ \lambda_{exist} \cdot L_{exist}
+ \lambda_{count} \cdot L_{count}
+ \lambda_{pb} \cdot L_{pb}
+ \lambda_{cal} \cdot L_{card\_cons}
+ \lambda_{bg} \cdot L_{bg}
$$

Stage 2:

$$
L_{stage2} =
\lambda_{replay} \cdot L_{stage1\_on\_strict\_replay}
+ \lambda_{hard} \cdot L_{hard\_no\_split}
+ \lambda_{M} \cdot L_{M\_censored}
+ \lambda_{abs} \cdot L_{abs\_optional}
$$

补充约束：

```text
lambda_align is the reference scale
L_align is evidence assignment supervision
L_exist is slot occupancy / set-cardinality structure supervision
L_count is global cardinality supervision
L_pb and L_card_cons are dual-cardinality calibration terms
L_exist, L_count, L_pb, L_card_cons, and L_bg are normalized auxiliary terms
L_abs_optional is disabled unless abstention labels or an approved dev calibration protocol exist
```

Stage 2 boundary losses:

$$
L_{hard\_no\_split} =
-\log P_{count}(1)
- \eta \log P_{pb}(1)
$$

$$
L_{M\_censored} =
-\log \sum_{k=2}^{Kmax} P_{count}(k)
$$

Optional low-weight Poisson-binomial censored loss:

$$
L_{M,pb} =
-\log \sum_{k=2}^{Kmax} P_{pb}(k)
$$

`L_M,pb` 默认关闭，除非协议明确启用低权重 aggregate calibration term。

### 3.2 数据源监督表

| Data source | L_align | L_exist | CE(P_count) | CE(P_pb) | censored M | L_bg |
| --- | --- | --- | --- | --- | --- | --- |
| strict synthetic | yes | yes | exact | exact | no | yes |
| Step1 high-conf single | optional | yes if foreground coverage reliable | k=1 | k=1 or optional | no | optional |
| hard_b | no/weak | no/weak only if foreground coverage reliable | k=1 | optional low-weight | no | optional |
| M weak | no | no | no | no | yes | no |
| M real alignment calib | yes | yes | exact/soft if annotated | optional | no | optional |

关键边界：

```text
M weak labels 只能提供 censored k at least 2 supervision
M weak labels 不得转成 exact count 或 alignment label
hard_b 监督 no-split restraint，不监督 detailed evidence alignment，除非有人工 alignment
Step1 high-confidence single-intent 不只是预训练补充，而是 anti-over-segmentation restraint
```

### 3.3 Stage 0: protocol freezing

训练前冻结：

```text
DATA_CARD
EVAL_PROTOCOL
split manifest
leakage report
threshold selection protocol
```

Split policy:

```text
project-level or repository-level split for OOD evaluation
time-based split for temporal generalization
no synthetic variants of the same atomic source may cross train/dev/test
no commits from the same PR/tangled construction group may cross splits
atomic-source leakage is prohibited
```

硬规则：

```text
hard_b-test 不参与训练、阈值、pseudo label、reranker tuning
M-final-test 不参与 prompt selection、threshold tuning、teacher filtering、retrieval tuning
commit message、PR title、issue text、gold intent id、synthetic construction metadata 不得作为 attribution input 或 relation feature
```

### 3.4 Stage 1: supervised synthetic attribution learning

数据：

```text
Step2 strict synthetic
Step1 high-confidence k=1
optional Step2/Step3-ready synthetic replay
```

职责：

```text
学习 evidence-to-intent attribution
学习 count 与 slot existence
学习 dual-cardinality calibration
学习 anti-over-segmentation restraint
```

采样原则：

```text
cardinality-balanced or reweighted batches
report training cardinality distribution and effective sampling distribution separately
避免 collapse 到 k=1 或 synthetic 先验
```

### 3.5 Stage 2: real-domain split / no-split / abstain boundary calibration

数据：

```text
hard_b-train/dev
M-weak-train/dev
strict synthetic replay
```

Stage 2 uses hard_b and M weak labels only for split/no-split/abstain boundary calibration.

Stage 2 definition:

```text
Stage 2 calibrates cardinality activation and release decisions over the frozen Stage-1 evidence partition.
It does not learn a new real-domain evidence partition.
It does not update the core evidence-assignment function.
```

这一阶段学的是：

```text
when to split
when not to split
when to release a decomposition
```

补充说明：

```text
Stage 2 learns split / no-split boundary by default.
Stage 2 learns abstention only when dev overflow/out-of-scope labels or calibrated selective-risk protocol is available.
Without such labels, abstention is a post-hoc calibrated selective prediction layer using frozen dev-only thresholds, not a supervised training objective.
```

必须明确：

```text
Stage 2 不使用 real alignment calibration
M-align-calib 不属于 Stage 2
M weak 仍然只是 censored k at least 2 supervision
```

Stage 2 default trainable parameters:

```text
global count head
slot existence head
count calibration temperatures
existence temperature
small top adapter, optional
selective-risk calibration head, optional if dev reject labels or an approved dev-only calibration protocol exist
```

Stage 2 default frozen parameters:

```text
edit-unit encoder lower layers
relation encoder / relation bias parameters
slot query initialization
assignment decoder
background routing head, unless reliable background calibration labels are explicitly used
renderer
```

Strict synthetic replay in Stage 2 is used for retention monitoring and light replay regularization. It must not justify full weak-label fine-tuning that destroys Stage 1 attribution behavior.

Why Stage 2 cannot update assignment:

```text
hard_b and M weak labels do not contain gold edit-to-intent assignments.
Updating the assignment decoder with these weak labels could reorganize evidence according to boundary noise.
Stage 2 therefore decides how many learned latent slots to activate and whether to release a decomposition, not how real edit units should be regrouped.
```

hard_b compactness reporting:

```text
Do not add unsupervised compactness loss on hard_b.
Report top-1 retained foreground mass on hard_b.
Report ResidualForegroundMass on hard_b.
Report background swallowing rate on hard_b.
If count equals 1 but the top slot does not absorb the semantic evidence, report it as a failure rather than forcing assignment changes without gold alignment.
```

### 3.6 Stage 3: small real alignment calibration

Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration.

Stage 3-Core is the default protocol:

```text
Stage 3-Core performs real-domain temperature and threshold calibration over the frozen Stage-1/Stage-2 attribution function.
It answers how to make confidence, thresholds, and count decisions better calibrated without changing the learned evidence partition.
```

Learned parameters in Stage 3-Core:

```text
count temperature
slot existence calibration temperature
```

Dev-selected operating parameters in Stage 3-Core:

```text
assignment threshold
background threshold, optional
abstention threshold, if selective-risk protocol is active
```

Frozen in Stage 3:

```text
edit-unit encoder lower layers
relation bias parameters by default
slot query initialization
main attribution decoder by default
renderer
```

原则：

```text
Only top calibration heads and adapters are trainable in the default Stage 3 protocol.
Full encoder/decoder fine-tuning is not allowed by default.
Stage 3 checkpoint selection uses M-align-calib metrics and strict replay retention.
hard_b-dev is a non-selection safety diagnostic if it was already used during Stage 2 calibration.
```

Stage 3-Plus is optional and separately reported:

```text
Enable Stage 3-Plus only when M-align-calib contains reliable manually annotated edit-unit alignment and is large enough to justify real-domain assignment adaptation.
Stage 3-Plus is not part of the default protocol.
If real alignment is very small, do not enable Stage 3-Plus.
```

Stage 3-Plus may add a low-rank assignment adapter:

$$
s_{ij}^{real}
=
s_{ij}^{base}
+
\Delta s_{ij}
$$

$$
\Delta s_{ij}
=
(W_h^{A}h_i)^\top(W_z^{B}z_j)
$$

where the adapter rank is small, for example rank 4 or rank 8.

Stage 3-Plus trainable parameters:

```text
low-rank assignment adapter
optional slot-existence temperature
```

Stage 3-Plus frozen parameters:

```text
base encoder
base slot decoder
base slot queries
base assignment scorer
count head, unless separately calibrated
renderer
```

Stage 3-Plus objective:

$$
L_{\text{stage3+}}
=
L_{\text{align}}^{real}
+
\lambda_{\text{replay}}L_{\text{align}}^{strict}
+
\lambda_{\text{drift}}L_{\text{drift}}
$$

Drift control:

$$
L_{\text{drift}}
=
\frac{1}{N}
\sum_i
KL
\left(
a_i^{base}
\parallel
a_i^{adapted}
\right)
$$

Stage 3-Plus results must be reported separately from Stage 3-Core so that real-domain assignment adaptation is not confused with default calibration.

### 3.7 Stage 4: evidence-locked message rendering

规则：

```text
Message utility is reported only after attribution evaluation is completed and frozen.
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
oracle-slot 与 predicted-slot rendering 必须分开报告
```

Renderer implementation protocol:

```text
Main renderer:
  deterministic rule-based renderer
  consumes frozen structured intent plan and assigned evidence only
Optional external renderer:
  frozen LLM or pretrained generator with plan-only input
  reported separately as an external reference
Primary system:
  no trainable renderer
  no direct raw-diff generation objective
  no renderer feedback into attribution checkpoint or threshold selection
```

## 4. Evaluation Protocol

### 4.1 real alignment benchmark

real alignment benchmark construction protocol:

```text
1. sample commits from held-out real projects / held-out time periods
2. filter out trivial generated/vendor-only commits
3. annotate intent count and primary evidence-to-intent assignment
4. allow annotator abstain / out-of-scope label
5. at least two annotators per sample
6. resolve disagreements through adjudication
7. report inter-annotator agreement
8. pseudo alignment cannot be used as final gold
9. synthetic construction labels cannot be mixed into the real alignment benchmark
```

必须报告：

```text
intent-count agreement:
  exact agreement and weighted Cohen's kappa
assignment agreement:
  pairwise same-intent agreement
  pairwise F1
  Adjusted Rand Index
  B-cubed agreement
  optionally Krippendorff's alpha over pairwise same-intent decisions
```

不要直接对 raw `intent_id` 计算 Cohen's kappa，因为 intent ID 是 sample-local 且无序的。

Annotation unit protocol:

```text
one annotation decision is made per normalized edit unit
the benchmark annotation unit must match the model evaluation unit
annotators mark each unit as foreground intent assignment, background, shared-support, uncertain, or out-of-scope
mixed hunks are retained as hard cases only if the normalized edit-unit boundary can represent the primary assignment
shared-support units are reported separately and excluded from MVP primary-assignment scoring unless a future multi-assignment protocol is defined
unknown / uncertain units are masked from attribution denominators unless adjudicated
```

Gold intent ontology:

```text
A gold intent is a coherent action-object objective supported by a non-empty set of normalized edit units.
Each intent must be expressible at minimum as action + object.
Optional fields are type and scope.
Intent IDs are sample-local and unordered.
Intent statements are used for annotation consistency and adjudication only; they are never model inputs.
```

Merge rules:

```text
source modification plus tests added solely to validate that modification -> same intent
feature code plus required configuration wiring or schema change -> same intent if support edits have no independent objective
backend handler plus frontend client plus API type definition for the same flow -> same intent
multiple files fixing the same defect root cause -> same intent
local documentation that directly synchronizes the same behavior change -> same intent or supporting evidence
```

Split rules:

```text
different action-object pairs -> split
edits that can be independently reverted without invalidating another objective -> split
independent user-visible or maintenance objectives -> split
refactoring beyond what is necessary for the primary fix or feature -> split
dependency or build upgrade as an independent maintenance target -> split
large documentation rewrite, tutorial addition, or independent API documentation update -> split
```

Boundary-case rules:

```text
code plus tests:
  tests only validate the code change -> merge
  tests add independent infrastructure or cover independent behavior -> split
code plus docs:
  local docs synchronized with the same behavior change -> merge as supporting evidence
  independent docs objective -> split
bug fix plus refactor:
  local refactor required for the bug fix -> merge
  structural refactor beyond fix necessity -> split
feature plus config:
  required config wiring -> merge
  independent config cleanup or default adjustment -> split
semantic edit plus formatting:
  pure formatting -> background
  semantic and formatting mixed in an inseparable unit -> mixed/hard case
dependency update:
  required for feature implementation -> supporting evidence
  independent upgrade or maintenance target -> separate intent
  mechanical lockfile change -> background
```

Annotation workflow:

```text
Step 1: mark commit scope_status as in_scope, out_of_scope, or uncertain
Step 2: mark each edit unit as foreground, background, shared_support, uncertain, or mixed
Step 3: assign each foreground unit one sample-local primary intent ID
Step 4: write an action-object intent statement for each intent
Step 5: check action-object coherence and independent reversibility
Step 6: resolve disagreement by adjudication
```

Adjudication priority:

```text
1. action-object coherence
2. direct support dependency
3. independent reversibility
4. developer-visible objective
```

Recommended annotation record:

```json
{
  "commit_id": "abc123",
  "scope_status": "in_scope",
  "gold_k": 2,
  "intents": [
    {
      "intent_id": "I1",
      "action": "fix",
      "object": "token expiration validation",
      "scope": "authentication",
      "unit_ids": ["u1", "u2"]
    },
    {
      "intent_id": "I2",
      "action": "update",
      "object": "authentication API documentation",
      "scope": "docs",
      "unit_ids": ["u3"]
    }
  ],
  "background_units": ["u4"],
  "shared_support_units": [],
  "uncertain_units": ["u5"],
  "mixed_units": [],
  "annotator_confidence": 0.85
}
```

MVP scoring uses only:

```text
primary foreground assignments
adjudicated background assignments
```

MVP scoring excludes:

```text
shared_support
uncertain
unresolved mixed units
```

Report separately:

```text
intent count agreement
foreground pairwise agreement
B-cubed agreement
Adjusted Rand Index
background agreement
out-of-scope agreement
```

### 4.2 RealDomainSplit

任务：

```text
k=1 vs k at least 2
split / no-split boundary
```

指标：

```text
AUROC
AUPRC
Balanced Accuracy
ECE
FPR_hard_b
```

其中：

```text
FPR_hard_b = percentage of hard_b single-intent commits predicted as multi-intent
```

### 4.3 hard_b no-split evaluation

必须报告：

```text
hard_b no-split accuracy
FPR_hard_b
over-segmentation rate on hard single-intent commits
```

### 4.4 M censored boundary evaluation

必须报告：

```text
censored multi-intent recall
P_count vs P_pb consistency under weak real-domain supervision
boundary calibration quality on M weak
```

### 4.5 RealDomainSelective

任务：

```text
in-scope decomposable vs overflow / abstain
是否应该输出 decomposition
```

指标：

```text
coverage
risk@coverage
AURC
false abstention on in-scope commits
```

需要 reject / out-of-scope gold labels 的指标：

```text
abstention precision
missed overflow rate on out-of-scope commits
forced-decomposition error on out-of-scope commits
```

如果没有 reject / out-of-scope gold labels，只能报告 selective abstention 口径：

```text
coverage
selective attribution risk
AURC
false abstention on known in-scope commits
coverage-risk curve on labeled in-scope samples
```

若模型支持 abstention，还必须报告：

```text
coverage-risk curve
selective pairwise F1
selective hunk-F1
```

The constrained background slot is credible only if its swallowing errors and file-role-specific missing-intent rates are reported. A high attribution score with high foreground-to-background error is not acceptable.

### 4.6 三类机制诊断

A. Cardinality diagnostics

```text
global count vs P_pb consistency
count exact / MAE / ECE
calibration before/after hard_b and M censored adaptation
```

B. Attribution diagnostics

```text
oracle-k vs predicted-k attribution
pairwise F1
B-cubed F1
hunk micro-F1
over-segmentation rate
under-segmentation rate
foreground swallowed by background
```

C. Validity and shortcut diagnostics

```text
Leakage audit:
  verify synthetic markers, construction IDs, message-derived features, and generated gold fields are absent from model inputs
Structural robustness:
  path-masked
  identifier-masked
Generalization:
  cross-project
  cross-time
  k at least 3 stress
  shared-file stress
```

必须说明：

```text
These diagnostics are validity checks, not method-selection ablations.
these diagnostics are validity checks, not method-selection ablations
```

### 4.7 最小必要 baselines

Baselines are used to contextualize the attribution formulation, not to tune MICA components.

```text
B1: single-intent always
B2: file/path clustering
B3: embedding clustering with oracle-k
B4: supervised count-only + heuristic assignment
B5: direct generation baseline
```

其中：

```text
B5 only serves message utility, not the main attribution conclusion
clustering remains a diagnostic baseline, not the primary formulation
```

### 4.8 message utility

Message utility is secondary.

主比较只保留：

```text
oracle slots -> renderer
predicted slots -> renderer
direct diff -> message
```

约束：

```text
Message utility is reported only after attribution evaluation is completed and frozen.
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
LLM prompting / pretrained generation baselines 只能作为外部参考
```

## 5. Leakage and Validity Controls

必须单列：

```text
no message / PR / issue / gold / synthetic metadata leakage
atomic-source split
pseudo alignment isolation
renderer isolation
Kmax fixed before final evaluation
```

额外硬规则：

```text
commit message、PR title、issue text、gold intent fields 永不进入 attribution input
pseudo alignment 永远不是 final gold
renderer-side metrics 不得选择 attribution config
atomic-source leakage is prohibited
```

## 6. Claims and Validation Protocol

Claim 1:

```text
MICA is trained for evidence-grounded attribution on provenance-preserving synthetic data and evaluated on manually annotated real alignment data.
```

Validation:

```text
real alignment benchmark
oracle-k / predicted-k attribution metrics
no renderer feedback into attribution
```

Claim 2:

```text
MICA supports selective decomposition of low-cardinality tangled commits with calibrated cardinality estimates.
```

Validation:

```text
count exact / MAE / ECE
hard_b FPR
M censored recall
P_count vs P_pb consistency
```

Claim 3:

```text
MICA avoids over-splitting complex single-intent commits.
```

Validation:

```text
hard_b no-split accuracy
over-segmentation rate
Step1 restraint transfer
```

Claim 4:

```text
MICA exposes calibrated selective abstention rather than forcing decomposition when confidence or task-boundary evidence is insufficient.
```

Validation:

```text
selective abstention metrics
coverage-risk curve
forced-decomposition error
missed overflow rate, only when out-of-scope gold labels exist
```

Claim 5a:

```text
MICA exposes evidence-linked structured intent plans.
```

Validation:

```text
slot-level assigned evidence
foreground/background routing audit
oracle-k / predicted-k attribution reports
```

Claim 5b:

```text
Frozen structured plans support downstream message rendering.
```

Validation:

```text
predicted slots -> renderer
oracle slots -> renderer
direct diff -> message as a non-attribution reference
```

## 7. MVP-Core / MVP-Plus / Target Paper System

MVP-Core:

```text
diff / hunk parser
edit-unit encoder
Kmax-bounded foreground slots
constrained background slot with masked supervision
global count head + slot existence head
Hungarian evidence-first matching
L_stage1 on strict synthetic + Step1 restraint
deterministic renderer
```

MVP-Plus:

```text
observable evidence graph bias
Poisson-binomial count consistency
hard_b no-split calibration
M censored multi-intent calibration
overflow / abstention calibration
```

Target paper system:

```text
MVP-Core
MVP-Plus
real alignment benchmark evaluation
Kmax coverage report
selective attribution evaluation
anti-shortcut / OOD audits
downstream evidence-locked message utility
```

必须明确：

```text
If the target is a CCF A-level paper, MVP-Core alone is insufficient.
The minimum publishable target system must include real alignment evaluation, hard_b no-split evaluation, Kmax coverage reporting, and selective attribution evaluation.
```

## 8. Non-negotiable Protocol Constraints

1. Kmax must be fixed before final evaluation and justified by DATA_CARD coverage, not by performance tuning.
2. Synthetic construction metadata, commit messages, PR titles, issue texts, and gold intent fields must never enter attribution model inputs or relation construction.
3. Atomic source commits and their synthetic variants must not cross train/dev/test splits.
4. M weak labels provide censored multi-intent supervision only; they must not be converted into exact count or alignment labels.
5. hard_b supervises no-split restraint, not detailed evidence alignment unless manually annotated.
6. Background slot uses masked supervision with positive / reliable-negative / unknown labels.
7. Abstention must be evaluated with coverage-risk metrics; covered-only attribution scores are insufficient.
8. Renderer metrics must not select attribution checkpoints, thresholds, prompts, templates, or verifier settings.
9. Real alignment evaluation must use manually verified labels or adjudicated annotations, not pseudo alignment.
10. All oracle-k and predicted-k attribution results must be reported separately.

## 9. 当前分支代码映射

本节结论来自当前分支代码审计，不来自历史文档推断。
“已经实现并有测试覆盖”不等于“已经具备论文最终证据”。

### 9.1 target protocol 中计划最终实现的内容

第 1-8 节描述的是目标协议，而不是当前分支已经完成的状态。按 target protocol，最终应具备：

- Stage 0 protocol freeze：在 final evaluation 之前填充并冻结 train/dev `coverage@Kmax`、split 规则和 leakage audit。
- Stage 1 synthetic attribution learning 与基于冻结 split 的 official validation，并按 `docs/EVAL_PROTOCOL.md` 报告指标。
- Stage 2 real-domain split / no-split / abstain 校准，且 selective-risk 阈值只能在 dev 上冻结。
- Stage 3 基于人工 adjudicated real alignment 的校准与评估，不能用 pseudo alignment 充当最终 gold。
- Stage 4 在 attribution 冻结后进行 evidence-locked consumer evaluation；trainable renderer 只能作为可选附加路径，不能反向影响 attribution 选择。
- 只有在所需资产、校准产物和冻结评估输出真实存在后，才能形成最终论文表格。

### 9.2 当前分支已经实现并有测试覆盖的内容

以下内容在当前分支上是实代码路径，且有直接测试覆盖：

- Stage 0 协议校验与 freeze dry-run：
  `code/mica/stage0/data_card.py`、`code/mica/stage0/eval_protocol.py`、`code/mica/stage0/protocol_freeze.py`；
  测试：`tests/mica/test_stage0_protocol_freeze.py`、`tests/mica/test_current_mica_docs.py`。
- bounded-slot 核心模型与 attribution 侧损失：
  `code/mica/models/mica_model.py`、`code/mica/models/slot_decoder.py`、`code/mica/models/count_head.py`、
  `code/mica/losses/hungarian_matching.py`、`code/mica/losses/cardinality.py`、`code/mica/losses/consistency_losses.py`；
  测试：`tests/mica/test_mica_model_semantics.py`、`tests/mica/test_assignment_loss_correctness.py`、
  `tests/mica/test_hungarian_matching.py`、`tests/mica/test_cardinality_losses.py`、`tests/mica/test_consistency_losses.py`。
- Stage 1 prediction 规范化与 structured plan 构建：
  `code/mica/adapters/stage1_prediction_adapter.py`、`code/mica/plan_builder.py`；
  测试：`tests/mica/test_stage1_prediction_adapter.py`、`tests/mica/test_structured_intent_plan_builder.py`、
  `tests/mica/test_plan_builder_batch.py`。
- deterministic evidence-locked consumer pipeline：
  `code/mica/consumers/plan_schema.py`、`code/mica/consumers/evidence_summarizer.py`、
  `code/mica/consumers/message_generator.py`、`code/mica/consumers/verifier.py`、
  `code/mica/consumers/candidate_selector.py`、`code/mica/consumers/pipeline.py`、
  `code/mica/renderers/deterministic.py`；
  测试：`tests/mica/test_consumer_plan_schema.py`、`tests/mica/test_consumer_pipeline.py`、
  `tests/mica/test_consumer_verifiers.py`、`tests/mica/test_consumer_pipeline_end_to_end.py`、
  `tests/mica/test_deterministic_renderer.py`、`tests/mica/test_deterministic_renderer_consumer_integration.py`。
- 本地 lightweight baselines 与 baseline registry：
  `code/mica/baselines/flat_classifier.py`、`code/mica/baselines/no_slot_decoder.py`、
  `code/mica/baselines/graph_clustering.py`、`code/mica/baselines/metadata_tfidf_classifier.py`、
  `code/mica/baselines/direct_generation_baseline.py`、`code/mica/eval/baseline_registry.py`；
  测试：`tests/mica/test_stage1_flat_classifier_baseline.py`、`tests/mica/test_stage1_no_slot_decoder_baseline.py`、
  `tests/mica/test_oracle_k_clustering_baseline.py`、`tests/mica/test_baseline_registry.py`、
  `tests/mica/test_stage1_baselines_runner.py`。

### 9.3 当前只有函数级基础设施但没有真实实验结果的内容

以下区域在当前分支上已有真实函数、runner 或 schema，很多也有 fixture 级测试，但这不等于已经形成真实实验结论：

- Stage 2 guarded calibration / training 基础设施：
  `code/mica/runners/run_stage2_calibration.py`、`code/mica/stages/stage2_real_calibration.py`、
  `code/mica/training/backend.py`；
  测试：`tests/mica/test_stage2_calibration_runner_guards.py`、`tests/mica/test_stage2_runner_executable_skeleton.py`。
  代码里明确存在 guarded `dry_run` / advisor-approved training 路径，以及 `values_to_be_populated_by_dev_calibration_script`；这说明有基础设施，不说明当前分支已经提交正式 benchmark 结果。
- Stage 3 guarded real-alignment calibration 基础设施：
  `code/mica/runners/run_stage3_alignment_calibration.py`、`code/mica/stages/stage3_real_alignment_calibration.py`；
  测试：`tests/mica/test_stage3_alignment_calibration_guards.py`、`tests/mica/test_stage3_runner_executable_skeleton.py`。
  当前代码能做 validation 和 guarded calibration，但不能据此宣称 real-alignment benchmark 已经真实跑完并冻结。
- canonical consumer evaluation / export 基础设施：
  `code/mica/runners/export_consumer_plans.py`、`code/mica/runners/run_consumer_evaluation.py`、
  `code/mica/eval/consumer_metrics.py`、`code/mica/eval/consumer_stratification.py`、
  `code/mica/eval/compare_consumer_runs.py`、`code/mica/eval/export_human_pilot.py`、
  `code/mica/adapters/oracle_plan_adapter.py`；
  测试：`tests/mica/test_export_consumer_plans_runner.py`、`tests/mica/test_consumer_evaluation_runner.py`、
  `tests/mica/test_consumer_metrics.py`、`tests/mica/test_compare_consumer_runs.py`、
  `tests/mica/test_export_human_pilot.py`、`tests/mica/test_oracle_plan_adapter.py`。
  这些代码建立了后续评估基础设施和 synthetic fixture 验证，但本身不是 predicted-plan 或 oracle-plan 的正式 benchmark 结果。
- 可选外部配置的 FrozenLLMRenderer 路径：
  `code/mica/consumers/message_generator.py`、`code/mica/consumers/pipeline.py`；
  测试：`tests/mica/test_frozen_llm_renderer.py`。
  当前分支已经实现一个受 structured-plan consumer pipeline 隔离约束保护的外部可配置 frozen LLM 候选路径。这是基础设施和测试覆盖，不是已经完成的外部 LLM benchmark 结果。
- message-level external reference baseline 基础设施：
  `code/mica/baselines/llm_prompting_baseline.py`、`code/mica/baselines/pretrained_generation_baseline.py`、
  `code/mica/runners/run_message_baseline_generation.py`；
  测试：`tests/mica/test_message_baseline_generation_runner.py`、
  `tests/mica/test_llm_prompting_baseline_contract.py`、`tests/mica/test_direct_generation_baseline_contract.py`。
  当前分支已经能把 canonical structured plan 渲染成 message-level baseline rows，支持 mock-provider 本地执行以及显式 opt-in 的真实 API 路径。这仍然只是基础设施，不是 benchmark 证据。
- message-utility dry-run 与 proxy metric 基础设施：
  `code/mica/runners/run_message_utility_eval.py`、`code/mica/eval/message_utility.py`。
  代码中显式写有 `proxy_not_human_eval`，因此它们只能作为后续评估基础设施，不能被当成正式人评或最终 benchmark 证据。
- guarded 可执行的 trainable reranker 路径：
  `code/mica/stages/stage4_renderer_training.py`、`code/mica/runners/run_stage4_renderer_training.py`、
  `code/mica/renderers/trainable_reranker.py`；
  测试：`tests/mica/test_stage4_renderer_training_guards.py`。
  当前代码支持在 fixture 数据集上执行 guarded `--train --train-ablation` reranker 训练，并写出 checkpoint/metric artifact。这说明基础设施可执行，不等于已经完成 trainable renderer 实验。

### 9.4 当前只有占位接口、尚未实现的内容

以下路径在当前分支上只是 contract 或 placeholder，不能写成“已完成实现”：

- `code/mica/eval/baseline_metrics.py`：其中 `*_baseline_placeholder()` 仍只是“本阶段未运行”的 report-side placeholder payload，不是可运行 baseline 系统。
- `code/mica/eval/training_diagnostics.py::grad_conflict_placeholder_or_optional`：仍是显式 optional/placeholder diagnostic helper。
- 仓库当前没有为 `FrozenLLMRenderer` 提供默认启用的外部 LLM 配置，也没有提交冻结 benchmark 资产；已有实现，但没有 benchmark 证据。
- `code/mica/baselines/pretrained_classifier_placeholder.py`：它已经不再表示独立 classifier baseline，只是 `pretrained_generation` 的兼容别名包装，不能误读成“已完成 pretrained classifier 实验”。

### 9.5 当前禁止宣称已经完成的论文证据

除非后续新增真实代码产物与冻结输出，否则当前分支禁止宣称以下论文证据已经完成：

- 已经填充并冻结 train/dev `coverage@Kmax`，足以证明最终论文版 Kmax 边界；
- 已经完成基于真实冻结 prediction artifact 的 Stage 1 official validation；
- 已经完成 Stage 2 或 Stage 3 的正式 benchmark 结果、checkpoint 或冻结指标表；
- 已经完成可发表规模的 real-alignment benchmark 构建；
- 已经完成 message-utility benchmark、human study 或 oracle-vs-predicted 结论；
- 已经完成 trainable renderer 结果、仓库内置外部 LLM benchmark 运行，或 FrozenLLMRenderer 已成为默认主线；
- 仅凭 dry-run、fixture tests、proxy metrics 或 placeholder manifest 就宣称最终论文表格已经完成。

如果代码与本文档 target protocol 不一致，应把它记为 implementation gap，而不是把本文档当作“当前事实”。
