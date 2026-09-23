# MICA-v3: bounded latent intent set attribution for low-cardinality tangled commits

> 状态：target protocol / paper-facing plan
> 本文档描述 MICA-v3 的目标实验方案，而不是当前仓库已经完成的实现状态。
> 当前分支真实实现边界必须以 `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md` 和代码为准。

## 0. Core Principle

MICA-v3 的主线必须保持为：

```text
Attribution is learned.
Generation is rendered.
Faithfulness is verified.
```

因此：

```text
1. 主模型只学习 evidence-to-intent attribution。
2. 真实域阶段只做 split / no-split / abstain 边界校准。
3. renderer 只消费冻结后的 structured intent plan。
4. renderer 不能反向更新 attribution，也不能用于 attribution checkpoint、threshold、prompt、template 或 verifier 选择。
```

MICA-v3 应被定义为：

> bounded latent intent set attribution for low-cardinality tangled commits

而不是：

```text
ordinary clustering
fixed-slot classification
commit message generation
joint generation tuning
```

## 1. Problem Boundary

### 1.1 Task Definition

正式问题定义：

```text
input:
  edit units extracted from a commit diff

output:
  if in-scope:
    an unordered foreground intent set with 1 <= k <= Kmax
  if out-of-scope:
    overflow decision
  if in-scope but low-confidence:
    abstention decision
  always:
    constrained background evidence assignment
```

目标域：

```text
Target domain:
  commits with 1 <= k <= Kmax, where Kmax is fixed before training according to the DATA_CARD
Main focus:
  k=1 / k=2 low-cardinality tangled commits
  separable or weakly entangled multi-intent commits
```

非目标域：

```text
Out-of-scope:
  k > Kmax complex commits
  release aggregation commits
  mass refactoring commits
  dependency/vendor synchronization commits
  mechanically generated diffs
```

非目标主张：

```text
not full developer-intent recovery
not arbitrary complex tangled decomposition
not full call graph / dataflow reconstruction
not message generation as the primary contribution
```

### 1.2 Kmax as Task Boundary, Not Tuning Knob

Kmax is a task-scope constant, not a tuned model hyperparameter.

`Kmax=4` 只能表示默认 bounded-capacity setting，不能写成“真实 commit 最多只有四个 intent”的断言。

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

必须明确：

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

### 1.3 In-scope vs Out-of-scope and Overflow / Abstention

若样本在目标域内，模型输出 foreground intent set。
若样本超出目标域或分解低置信，模型应输出 overflow / abstention，而不是静默截断成 `Kmax` 个 intent。

Overflow and abstention are related reject decisions, but they are not the same label:

```text
overflow:
  the commit is outside the task boundary or capacity assumption
  examples include k > Kmax, release aggregation, mass refactoring, dependency/vendor synchronization, or mechanically generated diffs

abstention:
  the commit may be in-scope, but the model is not confident enough to release a decomposition
  examples include high assignment uncertainty, count disagreement, or foreground evidence not absorbed by confident slots
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

MVP 中如果没有 out-of-scope gold labels，只能暴露一个 reject option：

```text
The MVP exposes one reject option.
It is reported as selective abstention, not as semantic overflow detection.
Do not claim a supervised overflow classifier unless explicit overflow labels exist.
```

decomposition risk score 可定义为：

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
  capacity saturation signal; it indicates the model is using the maximum allowed count, not direct proof that true k exceeds Kmax
JS(P_count || P_pb):
  global count 与 slot-level existence 不一致
AssignmentEntropy:
  edit units 对 slots 的分配不确定
ResidualForegroundMass:
  语义 edit 未被可信 foreground slots 吸收
LowSlotMargin:
  slot 竞争边界不清晰
```

Risk component definitions:

```text
ForegroundAssignmentEntropy:
  H_i^fg = - sum_j a_ij^fg log a_ij^fg over foreground slots only
  report foreground-only entropy separately from foreground-plus-null entropy

ForegroundPlusNullEntropy:
  H_i^all = - sum_j a_ij log a_ij over foreground slots plus q_null
  used as a diagnostic, because confident null routing is not automatically a risk signal

ResidualForegroundMass:
  RFM(X) = sum_i m_i^semantic max(0, tau_fg - max_j a_ij^fg) / sum_i m_i^semantic
  m_i^semantic excludes rule-verified background and unknown/ignored units

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
threshold is fixed on dev split only
final test cannot retune the threshold
coverage-risk curve must be reported
covered-only attribution scores are insufficient
```

若没有 overflow gold labels：

```text
MVP uses calibrated abstention, not a fully supervised overflow classifier
optional overflow calibration may use k>Kmax synthetic or real complex commits
final-test data must not be used for abstention threshold tuning
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

Gold edit/hunk-to-intent assignments are valid only when their provenance is explicit and auditable.

Gold assignments are available only from:

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

Exclude a synthetic sample from `L_align` supervision if:

```text
one output hunk mixes semantic lines from multiple source atomic commits
conflict resolution rewrites semantic content
provenance mapping is incomplete
one edit unit cannot be assigned to a unique primary source intent
construction metadata is missing or inconsistent
```

Non-sources of gold assignment:

```text
M weak labels do not provide gold intent assignments
hard_b labels do not provide detailed gold alignment unless manually annotated
commit messages do not provide gold intent assignments
PR titles and issue text do not provide gold intent assignments
pseudo labels do not provide final gold assignments
```

### 2.1 Edit Unit Normalizer

MICA-v3 的默认粒度是 hunk / edit-unit，而不是 token-level directly.

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

This protocol is evidence expansion, not label expansion:

```text
function-level context may be used as model input evidence
function-level context must not include commit message, PR title, issue text, gold intent id, or synthetic construction metadata
function-level context does not change the primary edit-unit assignment target
the assigned evidence remains the edit unit / hunk, while the enclosing symbol provides disambiguating local program context
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

约束：

```text
hunk-level is the default training granularity
large hunk splitting is not an MVP prerequisite
large mixed-intent hunks are treated as hard cases and separately reported
```

MVP assignment 假设必须明确：

```text
MVP assumes each semantic edit unit has one primary foreground intent.
Shared-support units are marked and reported separately, but not used as the main supervision target.
background edit units are assigned to q_null.
```

### 2.2 Lightweight Evidence Graph Encoder

只使用 commit-time observable evidence，不把模型写成完整程序分析系统。若实现只是 relation bias，论文应称为 `relation-aware edit-unit encoder`，而不是暗示必须实现 full GNN。

推荐 relation / bias：

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

所有 relation features 必须满足：

```text
computed from the diff and repository snapshot available at commit time
never derived from gold intent labels
never derived from synthetic construction metadata
never derived from commit message, PR title, issue text, or post-commit artifacts
```

来源约束：

```text
test_target:
  heuristic relation from file path, naming convention, import target, or changed symbol overlap
doc_refers_to:
  lexical or path-based reference only, no LLM annotation in MVP
```

### 2.3 Bounded Latent Intent Slots

方法范式：

```text
bounded latent intent set prediction
evidence-to-intent attribution
structured intent plan
evidence-locked rendering
```

模型维护：

```text
Kmax unordered foreground latent intent slots
1 constrained background slot q_null
```

MICA 不是“先定 k 再分配 evidence”，而是让 foreground slots 竞争性吸收 evidence，再由 `P_count` 与 slot existence 共同决定有效 intent 数。

Slot assignment distribution:

```text
a_ij:
  assignment probability of edit unit i to foreground slot j
a_i,null:
  assignment probability of edit unit i to q_null
a_j:
  vector [a_1j, ..., a_nj]
```

For MVP primary-intent attribution:

$$
\sum_{j=1}^{Kmax} a_{ij} + a_{i,null} = 1
$$

Foreground slots and `q_null` form one normalized assignment distribution per edit unit. Unknown units are excluded from background supervision but remain in the assignment softmax.

Evidence-aware slot representation:

```text
MICA uses a two-way coupling between slot queries and absorbed evidence.
Existence is not predicted from an independent learned query alone.
```

Given encoded edit-unit evidence:

$$
H'=\{h_1,\dots,h_n\},\quad h_i\in\mathbb{R}^d
$$

Initialize `Kmax` learnable foreground queries and one background query:

$$
Q=\{q_1,\dots,q_{Kmax}\},\quad q_{null}
$$

First obtain contextualized foreground slot states:

$$
\tilde z_j=\operatorname{CrossAttn}(q_j,H',R)
$$

where `R` is relation-aware bias from the observable evidence graph.

Initial foreground assignment score:

$$
s_{ij}=
\frac{(W_h h_i)^\top(W_z\tilde z_j)}{\sqrt d}
+b_{ij}^{rel}
$$

Background score:

$$
s_{i,null}=
\frac{(W_h h_i)^\top(W_n q_{null})}{\sqrt d}
+b_{i,null}
$$

Assignment probabilities are computed with a joint softmax over all foreground slots and `q_null`:

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

Each foreground slot then reconstructs an assignment-weighted evidence summary:

$$
e_j=
\frac{
\sum_{i=1}^{n}a_{ij}h_i
}{
\epsilon+\sum_{i=1}^{n}a_{ij}
}
$$

with evidence mass:

$$
m_j=\sum_{i=1}^{n}a_{ij}
$$

The final evidence-aware slot representation is:

$$
z_j=
\operatorname{LayerNorm}
\left(
\tilde z_j+
W_e e_j+
W_m\phi(m_j)
\right)
$$

where `phi(m_j)` is a scalar evidence-mass embedding. This makes `p_j` depend on slot semantics, absorbed evidence, and evidence mass, reducing failures where an empty slot receives high existence confidence or a high-mass slot receives low existence confidence.

### 2.4 Constrained Background Slot

background slot 不是 free rejection bucket。

background labels are three-valued:

```text
1. positive background
2. reliable foreground
3. unknown / ignored
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
ambiguous edits without reliable semantic/background labels
```

背景监督目标：

$$
L_{bg} = MaskedBCE(a_{null}, y_{bg}, mask_{bg})
$$

必须明确：

```text
A semantic edit without background proof must not be treated as background positive.
background slot is not a free rejection channel for difficult semantic evidence.
semantically uncertain units remain in foreground competition with low confidence.
```

必须报告：

```text
background assignment rate
foreground evidence swallowed by background
foreground-to-background error
missing-intent rate by file role
```

### 2.5 Dual-cardinality Count Head

保留：

$$
P_{count}(k|X) = softmax(f_{pool}(H'))
$$

Slot existence probability:

$$
p_j = \sigma(f_{exist}(z_j))
$$

where `z_j` is the contextualized representation of foreground slot `j`.

Poisson-binomial cardinality distribution, denoted `P_pb`:

$$
P_{pb}(k|X) = P\left(\sum_j Bernoulli(p_j)=k\right)
$$

职责必须写清：

```text
L_count supervises global cardinality
L_exist supervises slot occupancy / set-cardinality structure
P_pb connects global count and slot-level existence
dual-cardinality consistency is calibration, not an independent supervision claim
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

For active slot set `A`, assignment is renormalized as:

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

### 2.6 Evidence-first Hungarian Matching

#### Why not clustering?

Commit intent attribution is not equivalent to similarity-based clustering.

```text
one intent may span files, languages, tests, and docs
different intents may share files, symbols, or even one hunk
background edits exist and cannot be forced into foreground clusters
clustering does not naturally support count supervision, weak real-domain count calibration, background routing, or overflow handling
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

约束：

```text
default matching cost does not use type, role, generation, faithfulness, or message-level signals
C_type is only an optional tie-breaker and does not enter MVP default matching
C_hunk is used only when edit units are finer than hunks or when hunk-level projection labels exist
C_gen, C_faith, and C_role are prohibited in main matching
```

MVP 主监督假设：

```text
Hungarian matching is permutation-invariant over foreground slots
each semantic edit unit has one primary foreground assignment
shared-support edits are diagnostic only in MVP
```

Formal `L_align`:

Let Hungarian matching produce:

$$
\mathcal M=\{(j,m)\}
$$

where `j` is a predicted foreground slot and `m` is a gold intent. For matched slots:

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

where:

$$
\operatorname{Dice}(a_j,y_m)
=
\frac{
2\sum_i a_{ij}y_{im}+\epsilon
}{
\sum_i a_{ij}+\sum_i y_{im}+\epsilon
}
$$

Unmatched foreground slots are not forced to an all-zero assignment mask through `L_align`, because joint softmax always allocates some assignment mass. Unmatched slots are supervised through `L_exist=0`.

### 2.7 Structured Intent Plan

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
scope/action/object are derived after attribution
they are not attribution supervision targets in MVP
optional role tags are diagnostic metadata, not core claims
```

### 2.8 Evidence-locked Renderer

renderer 只消费冻结后的 structured intent plan 与 assigned evidence。

硬约束：

```text
renderer does not update attribution
renderer does not select attribution checkpoints
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
renderer does not redefine count, slot existence, or matching
```

## 3. Training Protocol

### 3.1 Layered Objective

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

原则：

```text
losses are normalized to comparable scales
lambda_align is the reference scale
L_align is evidence assignment supervision
L_exist is slot occupancy / set-cardinality structure supervision
L_count is global cardinality supervision
L_pb and L_card_cons are dual-cardinality calibration terms
L_exist, L_count, L_pb, L_card_cons, and L_bg are normalized auxiliary terms
background routing is explicit rather than implicit in matching
abstention is optional in training but mandatory in evaluation if exposed at inference
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

`L_M,pb` is disabled by default unless the protocol explicitly enables a low-weight aggregate calibration term.

### 3.2 Data-source Supervision Matrix

| Data source | L_align | L_exist | CE(P_count) | CE(P_pb) | censored M | L_bg |
| --- | --- | --- | --- | --- | --- | --- |
| strict synthetic | yes | yes | exact | exact | no | yes |
| Step1 high-conf single | optional | yes if foreground coverage reliable | k=1 | k=1 or optional | no | optional |
| hard_b | no/weak | no/weak only if foreground coverage reliable | k=1 | optional low-weight | no | optional |
| M weak | no | no | no | no | yes | no |
| M real alignment calib | yes | yes | exact/soft if annotated | optional | no | optional |

关键解释：

```text
M weak labels provide censored k at least 2 supervision only
M weak labels must not be converted into exact count or alignment labels
hard_b supervises no-split restraint, not detailed evidence alignment unless manually annotated
Step1 high-confidence single-intent is not merely pretraining supplement; it is anti-over-segmentation restraint
```

### 3.3 Stage 0: Protocol Freezing

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
hard_b-test does not participate in training, threshold tuning, pseudo label construction, or reranker tuning
M-final-test does not participate in prompt selection, threshold tuning, teacher filtering, or retrieval tuning
commit message, PR title, issue text, gold intent id, and synthetic construction metadata are forbidden as attribution inputs or relation features
```

### 3.4 Stage 1: Supervised Synthetic Attribution Learning

数据：

```text
Step2 strict synthetic
Step1 high-confidence k=1
optional Step2/Step3-ready synthetic replay
```

职责：

```text
learn evidence-to-intent attribution
learn foreground slot existence
learn global count and P_pb consistency
learn anti-over-segmentation restraint from high-confidence single-intent data
```

采样原则：

```text
cardinality-balanced or reweighted batches
report training cardinality distribution and effective sampling distribution separately
avoid collapse into k=1 prior or synthetic-only k prior
```

禁止项：

```text
no generation loss in attribution training
no message-level leakage
no renderer-side signal in checkpoint selection
```

### 3.5 Stage 2: Real-domain Split / No-split / Abstain Boundary Calibration

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

约束：

```text
Stage 2 does not use real alignment calibration data
M-align-calib is excluded from Stage 2
M weak remains censored k at least 2 supervision only
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

### 3.6 Stage 3: Small Real Alignment Calibration

Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration.

数据：

```text
M-align-calib
small strict replay
hard_b-dev monitoring only
```

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

### 3.7 Stage 4: Evidence-locked Message Rendering

Stage 4 只做 downstream rendering。

规则：

```text
Message utility is reported only after attribution evaluation is completed and frozen.
renderer scores cannot be used to select attribution checkpoints, thresholds, templates, prompts, or verifier settings
oracle-slot and predicted-slot rendering must be reported separately
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

### 4.1 Real Alignment Benchmark

real alignment benchmark construction protocol:

```text
1. sample commits from held-out real projects or held-out time periods
2. filter out trivial generated/vendor-only commits
3. annotate intent count and primary evidence-to-intent assignment
4. allow annotator abstain / out-of-scope label
5. use at least two annotators per sample
6. resolve disagreements through adjudication
7. report inter-annotator agreement
8. pseudo alignment cannot be used as final gold
9. synthetic construction labels cannot be mixed into the real alignment benchmark
```

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

Do not compute Cohen's kappa directly on raw `intent_id`, because intent IDs are sample-local and unordered.

### 4.2 RealDomainSplit

任务：

```text
k=1 vs k at least 2
split / no-split boundary evaluation
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

### 4.3 hard_b No-split Evaluation

hard_b 用于验证复杂单意图 restraint，而不是 detailed alignment.

必须报告：

```text
hard_b no-split accuracy
FPR_hard_b
over-segmentation rate on hard single-intent commits
```

### 4.4 M Censored Boundary Evaluation

M weak 只验证真实多意图边界，不验证 gold alignment。

必须报告：

```text
censored multi-intent recall
calibration under weak real-domain supervision
P_count vs P_pb consistency under M weak
```

### 4.5 RealDomainSelective

任务：

```text
in-scope decomposable vs overflow / abstain
whether the model should output decomposition
```

指标：

```text
coverage
risk@coverage
AURC
false abstention on in-scope commits
```

Metrics requiring reject / out-of-scope gold labels:

```text
abstention precision
missed overflow rate on out-of-scope commits
forced-decomposition error on out-of-scope commits
```

If reject / out-of-scope gold labels are unavailable, RealDomainSelective reports selective abstention metrics only:

```text
coverage
selective attribution risk
AURC
false abstention on known in-scope commits
coverage-risk curve on labeled in-scope samples
```

对于支持 abstention 的模型，还必须报告：

```text
coverage-risk curve
selective pairwise F1
selective hunk-F1
```

The constrained background slot is credible only if its swallowing errors and file-role-specific missing-intent rates are reported. A high attribution score with high foreground-to-background error is not acceptable.

### 4.6 Attribution Diagnostics

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

Attribution metric denominator policy:

```text
foreground-only pairwise F1 excludes rule-verified background and unknown units
all-assigned-unit pairwise F1 includes foreground and adjudicated background assignments
unknown units are masked unless adjudicated
background routing metrics are reported separately and must not be hidden inside pairwise F1
oracle-k means only replacing predicted cardinality with gold cardinality; slot ranking and assignments remain model-predicted
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

### 4.7 Anti-shortcut and OOD Audits

审查目标不是要求 path / identifier 完全无贡献，而是识别模型是否依赖 brittle synthetic artifacts。

```text
legitimate structural features:
  file role
  language
  path distance
  test-source relation
suspicious shortcut features:
  synthetic separators
  template subjects
  construction metadata
  generated intent IDs
  message keywords
```

### 4.8 Minimum Necessary Baselines

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
B5 is for message utility only, not for the main attribution claim
similarity-based clustering is a diagnostic baseline, not the primary formulation
```

### 4.9 Message Utility

Message utility is secondary.

主比较只保留：

```text
oracle slots -> renderer
predicted slots -> renderer
direct diff -> message
```

约束：

```text
renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
LLM prompting / pretrained generation baselines are external references only
message utility cannot redefine the attribution objective
```

## 5. Leakage and Validity Controls

必须单列以下控制：

```text
no message / PR / issue / gold / synthetic metadata leakage
atomic-source split
pseudo alignment isolation
renderer isolation
Kmax fixed before final evaluation
```

额外硬规则：

```text
commit message, PR title, issue text, and gold intent fields are never attribution inputs
pseudo alignment is never final gold
renderer-side metrics cannot select attribution configurations
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

## 9. Current-branch Code-derived Mapping

This section is code-derived from the current branch audit. It is not inferred from historical documents.
Implemented and test-covered code does not automatically imply final-paper evidence.

### 9.1 Target protocol / intended final content

Sections 1-8 describe the intended final protocol, not the current-branch completion status. In particular, the target protocol expects:

- Stage 0 protocol freeze with populated train/dev `coverage@Kmax`, split freeze, and leakage audit before final evaluation.
- Stage 1 synthetic attribution learning plus frozen-split official validation under the metrics defined in `docs/EVAL_PROTOCOL.md`.
- Stage 2 real-domain split / no-split / abstain calibration with dev-only threshold freezing and selective-risk reporting.
- Stage 3 manually adjudicated real-alignment calibration and evaluation, not pseudo alignment.
- Stage 4 evidence-locked consumer evaluation after attribution is frozen; any trainable renderer path is optional and cannot feed back into attribution selection.
- Final paper tables only after the required assets, calibration artifacts, and frozen evaluation outputs actually exist.

### 9.2 Current branch already implemented and test-covered

The following items are implemented as real code paths on the current branch and have direct test coverage:

- Stage 0 protocol validators and freeze dry-run:
  `code/mica/stage0/data_card.py`, `code/mica/stage0/eval_protocol.py`, `code/mica/stage0/protocol_freeze.py`;
  tests: `tests/mica/test_stage0_protocol_freeze.py`, `tests/mica/test_current_mica_docs.py`.
- Core bounded-slot modeling components and attribution-side losses:
  `code/mica/models/mica_model.py`, `code/mica/models/slot_decoder.py`, `code/mica/models/count_head.py`,
  `code/mica/losses/hungarian_matching.py`, `code/mica/losses/cardinality.py`, `code/mica/losses/consistency_losses.py`;
  tests: `tests/mica/test_mica_model_semantics.py`, `tests/mica/test_assignment_loss_correctness.py`,
  `tests/mica/test_hungarian_matching.py`, `tests/mica/test_cardinality_losses.py`, `tests/mica/test_consistency_losses.py`.
- Stage 1 prediction normalization and structured-plan construction:
  `code/mica/adapters/stage1_prediction_adapter.py`, `code/mica/plan_builder.py`;
  tests: `tests/mica/test_stage1_prediction_adapter.py`, `tests/mica/test_structured_intent_plan_builder.py`,
  `tests/mica/test_plan_builder_batch.py`.
- Deterministic evidence-locked consumer pipeline:
  `code/mica/consumers/plan_schema.py`, `code/mica/consumers/evidence_summarizer.py`,
  `code/mica/consumers/message_generator.py`, `code/mica/consumers/verifier.py`,
  `code/mica/consumers/candidate_selector.py`, `code/mica/consumers/pipeline.py`,
  `code/mica/renderers/deterministic.py`;
  tests: `tests/mica/test_consumer_plan_schema.py`, `tests/mica/test_consumer_pipeline.py`,
  `tests/mica/test_consumer_verifiers.py`, `tests/mica/test_consumer_pipeline_end_to_end.py`,
  `tests/mica/test_deterministic_renderer.py`, `tests/mica/test_deterministic_renderer_consumer_integration.py`.
- Lightweight local baselines and baseline registry:
  `code/mica/baselines/flat_classifier.py`, `code/mica/baselines/no_slot_decoder.py`,
  `code/mica/baselines/graph_clustering.py`, `code/mica/baselines/metadata_tfidf_classifier.py`,
  `code/mica/baselines/direct_generation_baseline.py`, `code/mica/eval/baseline_registry.py`;
  tests: `tests/mica/test_stage1_flat_classifier_baseline.py`, `tests/mica/test_stage1_no_slot_decoder_baseline.py`,
  `tests/mica/test_oracle_k_clustering_baseline.py`, `tests/mica/test_baseline_registry.py`,
  `tests/mica/test_stage1_baselines_runner.py`.

### 9.3 Current branch function-level infrastructure without real experiment evidence

The following areas have concrete functions, runners, or schemas on the current branch, and many also have fixture-based tests, but they do not constitute completed experimental evidence:

- Stage 2 guarded calibration/training infrastructure:
  `code/mica/runners/run_stage2_calibration.py`, `code/mica/stages/stage2_real_calibration.py`,
  `code/mica/training/backend.py`;
  tests: `tests/mica/test_stage2_calibration_runner_guards.py`, `tests/mica/test_stage2_runner_executable_skeleton.py`.
  Code shows guarded `dry_run` / advisor-approved training paths and `values_to_be_populated_by_dev_calibration_script`; this is infrastructure, not a committed benchmark result.
- Stage 3 guarded real-alignment calibration infrastructure:
  `code/mica/runners/run_stage3_alignment_calibration.py`, `code/mica/stages/stage3_real_alignment_calibration.py`;
  tests: `tests/mica/test_stage3_alignment_calibration_guards.py`, `tests/mica/test_stage3_runner_executable_skeleton.py`.
  The code can validate and execute guarded calibration paths, but the branch does not itself prove that a real benchmark has been run and frozen.
- Canonical consumer-evaluation and export infrastructure:
  `code/mica/runners/export_consumer_plans.py`, `code/mica/runners/run_consumer_evaluation.py`,
  `code/mica/eval/consumer_metrics.py`, `code/mica/eval/consumer_stratification.py`,
  `code/mica/eval/compare_consumer_runs.py`, `code/mica/eval/export_human_pilot.py`,
  `code/mica/adapters/oracle_plan_adapter.py`;
  tests: `tests/mica/test_export_consumer_plans_runner.py`, `tests/mica/test_consumer_evaluation_runner.py`,
  `tests/mica/test_consumer_metrics.py`, `tests/mica/test_compare_consumer_runs.py`,
  `tests/mica/test_export_human_pilot.py`, `tests/mica/test_oracle_plan_adapter.py`.
  These modules establish reproducible infrastructure and fixture-level validation, but they are not by themselves real predicted-plan or oracle-plan benchmark results.
- optional externally configured FrozenLLMRenderer path:
  `code/mica/consumers/message_generator.py`, `code/mica/consumers/pipeline.py`;
  tests: `tests/mica/test_frozen_llm_renderer.py`.
  The current branch implements an externally configurable frozen LLM candidate path that is isolated behind the structured-plan consumer pipeline. This is infrastructure and test-covered behavior, not a completed external LLM benchmark result.
- message-level external reference baseline infrastructure:
  `code/mica/baselines/llm_prompting_baseline.py`, `code/mica/baselines/pretrained_generation_baseline.py`,
  `code/mica/runners/run_message_baseline_generation.py`;
  tests: `tests/mica/test_message_baseline_generation_runner.py`,
  `tests/mica/test_llm_prompting_baseline_contract.py`, `tests/mica/test_direct_generation_baseline_contract.py`.
  The branch can now render canonical structured plans into message-level baseline rows, with mock-provider local execution and explicit opt-in for real API usage. This is still infrastructure, not benchmark evidence.
- Message-utility dry-run and proxy-metric infrastructure:
  `code/mica/runners/run_message_utility_eval.py`, `code/mica/eval/message_utility.py`.
  The code explicitly marks `proxy_not_human_eval`; therefore it supports later evaluation setup, not final human-study or benchmark claims.
- guarded executable trainable reranker path:
  `code/mica/stages/stage4_renderer_training.py`, `code/mica/runners/run_stage4_renderer_training.py`,
  `code/mica/renderers/trainable_reranker.py`;
  tests: `tests/mica/test_stage4_renderer_training_guards.py`.
  The current code supports guarded `--train --train-ablation` reranker training on fixture datasets and writes checkpoint/metric artifacts. This is executable infrastructure, not a completed trainable-renderer experiment.

### 9.4 Current branch placeholder interfaces / not implemented

The following paths are present as contracts or placeholders and must not be described as completed implementation:

- `code/mica/eval/baseline_metrics.py`: the `*_baseline_placeholder()` payload builders are still report-side placeholders for "not run in this stage", not runnable baseline systems.
- `code/mica/eval/training_diagnostics.py::grad_conflict_placeholder_or_optional`: remains an explicit optional/placeholder diagnostic helper.
- No repository-shipped default external LLM configuration or frozen benchmark assets exist for `FrozenLLMRenderer`; implementation exists, but benchmark evidence does not.
- `code/mica/baselines/pretrained_classifier_placeholder.py`: no longer represents an independent classifier baseline; it is only a compatibility alias wrapper around `pretrained_generation`, and must not be mistaken for a completed pretrained classifier experiment.

### 9.5 Claims prohibited on the current branch

The current branch must not claim any of the following as already completed paper evidence unless new code-backed assets and frozen outputs are added later:

- populated train/dev `coverage@Kmax` statistics that justify the final-paper Kmax boundary;
- completed Stage 1 official validation on real frozen prediction artifacts;
- completed Stage 2 or Stage 3 benchmark results, checkpoints, or frozen metric tables;
- completed real-alignment benchmark construction at publishable scale;
- completed message-utility benchmark results, human-study findings, or oracle-vs-predicted conclusions;
- completed trainable renderer results, repository-shipped external LLM benchmark runs, or any claim that FrozenLLMRenderer is part of the default mainline;
- completed final paper tables based only on dry-runs, fixture tests, proxy metrics, or placeholder manifests.

If the repository code and this target protocol diverge, the code is the factual implementation state and the divergence must be recorded as an implementation gap.
