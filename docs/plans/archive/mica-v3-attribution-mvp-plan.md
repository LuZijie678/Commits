> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# MICA-v3 Attribution MVP Plan

## 1. 文档角色

本文件是 `experiment/mica-v3-attribution-mvp` 的实现侧计划文档。

它与两份更高层级的算法文档保持对齐：

- `MICA_multi_intent_commit_attribution_plan.md`
- `MICA_v3_trainable_algorithm_plan.md`

本分支的解释规则如下：

- 第一份文档定义整体算法、问题 framing 和论文级贡献边界
- 第二份文档定义 trainable v3 的目标、分阶段训练协议，以及必须从主 loss 中移除的部分

本分支计划必须同时遵循这两份文档：

- 原始 MICA plan 中的 **overall algorithm framing**
- v3 plan 中的 **trainable loss and staged optimization protocol**

不能让当前 skeleton 按照自己衍生出来的命名或 stage 逻辑继续独立演化。

### 1.1 Experiment Observation Record

为了区分“计划”和“现实执行状态”，本分支采用如下规则：

- 本文件用于记录算法范围、stage 边界和实现策略
- experiment observation record 用于记录真实运行现象、指标变化和负面结果

当前 experiment observation 记录入口：

- `docs/records/archive/2026-06-14-mica-stage1-attribution-experiment-observations.md`

## 2. Canonical Problem Definition

MICA-v3 不是“只是更好的 commit message generator”。

核心任务是：

```text
count-aware, evidence-grounded latent intent attribution
```

规范任务分解是：

```text
diff
  -> evidence-grounded intent attribution
  -> structured intent plan
  -> rendered commit message
```

主输出：

- intent count
- slot existence
- edit/hunk-to-intent attribution
- structured intent plan

次输出：

- rendered commit message

rendered message 是下游验证结果，不是本分支当前的训练目标。

## 3. Canonical Algorithm Vocabulary

本分支实现应统一使用以下术语。

### 3.1 Core structure

- `EditUnit`
- `Evidence Graph Encoder`
- `Count-aware Latent Intent Slot Decoder`
- `Evidence Attribution Head`
- `Structured Intent Plan Builder`
- `Evidence-locked Message Renderer`

### 3.2 Count and attribution terms

- `foreground intent slots`
- `optional null/background slot`
- `slot existence`
- `dual-cardinality count`
- `P_count(k)`
- `P_pb(k)` for Poisson-binomial count
- `evidence-first Hungarian matching`
- `oracle-k` vs `predicted-k`

### 3.3 Data supervision terms

- `atomic_k1`
- `synthetic_k2`
- `hard_b`
- `M censored k>=2`
- `real alignment calibration`

### 3.4 Terms that are optional or explicitly not part of the main claim

以下内容不属于本分支的核心算法要求：

- role taxonomy main training
- latent cohesion taxonomy main training
- retrieval-controlled generation
- verifier-guided reranking
- DPO / RLHF message tuning
- full call graph / full dataflow
- LLM relation annotation
- full `k>=3` decomposition

如果后续出现这些内容，必须明确标为 optional、ablation、diagnostic 或 future work。

## 4. Overall Three-Stage Training Protocol

本分支必须对齐 v3 算法文档中的三阶段协议。

### Stage 1: Synthetic attribution pretraining

目标：

- learn count-aware evidence attribution

主要监督：

- Step1 high-confidence atomic `k=1`
- Step2 synthetic `k=2` with reliable `edit_to_intent`

主要目标：

- count
- slot existence
- edit/hunk alignment

这是当前本分支唯一处于主动实现范围内的 stage。

### Stage 2: Real-domain calibration

目标：

- reduce over-splitting
- calibrate real-domain multi-intent boundary

主要监督：

- `hard_b` as real complex single-intent restraint
- `M` only as censored `k>=2`
- small real alignment calibration/evaluation pool

本分支尚未开始 Stage 2。

### Stage 3: Evidence-locked generation

目标：

- validate downstream utility of the attributed intent plan

规则：

- generation reads the structured plan
- generation does not backprop into attribution

本分支尚未开始 Stage 3。

## 5. Current Branch Scope

本分支范围限制为：

- Stage 1 attribution data interfaces
- Stage 1 model skeleton
- Stage 1 loss skeleton
- Stage 1 tiny sanity training
- Stage 1 metric plumbing

本分支明确不处理：

- generation pilot continuation
- real API experiments
- Stage 2 `hard_b` anti-over-splitting
- Stage 2 `M` censored calibration
- Stage 3 renderer / verifier / retrieval

## 6. Current Available Data

已确认与 MICA-v3 相关的数据资产：

- Step1 atomic source pool:
  - `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- Step2 bridge artifacts:
  - `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
  - `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json`
- Step1 tracked split metadata:
  - `datasets/step1/manifest/dataset_split_report.json`
- Step2 strict repo/SHA-disjoint candidate source:
  - `datasets/step2/candidate_sources/strict_repo_sha_disjoint_candidates.csv`
  - `datasets/step2/candidate_sources/strict_repo_sha_disjoint_candidates_report.json`
- Tracked `M` canonical data:
  - `datasets/m_verified/canonical/usable_m_with_real_diff.jsonl`
  - `datasets/m_verified/manifest/usable_m_with_real_diff_manifest.json`
- Tracked `hard_b` canonical data:
  - `datasets/hard_b/canonical/usable_hard_b_with_real_diff.jsonl`
  - `datasets/hard_b/manifest/usable_hard_b_with_real_diff_manifest.json`

当前本地仅运行时可用的 Stage 1 sanity 数据源：

- local Step2 fullscale `synthetic_samples_step3_ready.jsonl`

重要边界：

- 该本地 runtime synthetic 路径只允许用于 Stage 1 chain sanity
- 它还不是正式冻结的 Stage 1 paper split

## 7. Current Unavailable or Out-of-Scope Data

- 本分支没有被跟踪的官方冻结版 MICA Stage 1 train/dev/test split manifest
- 没有被跟踪的 clean-branch `synthetic_samples_step3_ready.jsonl`
- 这条稳定 checkpoint 谱系中不存在 `code/step3/`
- `RealDomainBinary` 不属于当前 Stage 1 训练范围
- `hard_b` 不属于当前 Stage 1 训练范围
- `M weak` 与 `M alignment` 不属于当前 Stage 1 训练范围

## 8. Stage 1 Canonical Data Protocol

即使当前本地 sanity run 仍然是近似版本，Stage 1 训练也应使用正式算法术语来定义。

### 8.1 Allowed Stage 1 supervision

- `atomic_k1`
  - from Step1 high-confidence atomic pool
  - all edit units map to gold intent `0`
- `synthetic_k2`
  - from Step2 synthetic data with reliable `edit_to_intent`
  - gold count is `2`

### 8.2 Stage 1 exclusions

以下数据不得作为 Stage 1 主训练数据：

- `hard_b`
- `M weak`
- `M alignment`
- `RealDomainBinary`

### 8.3 Current branch policy

对本分支而言：

- 本地 runtime 的 Stage 1 sanity 可以使用确定性的 balanced subset 做 chain validation
- 该 subset 不得被描述为正式 paper split
- 正式的 Stage 1 split freeze 应在训练链稳定之后进行

### 8.4 Degenerate `synthetic_k2` diagnostics

Stage 1 sanity 必须区分“有信息量的 `k=2` synthetic 样本”和“退化样本”。

当前诊断类别：

- `singleton_dominated`
  - `min(intent_unit_count) <= 1`
- `path_dominated`
  - file-path clustering already nearly solves the grouping problem
- `nondegenerate_candidate`
  - enough edit units per intent and weak enough trivial baselines to make attribution learning meaningful

当前分支策略：

- 在解释 attribution metrics 之前，先审计这些类别
- 不要把所有 `synthetic_k2` 样本都当作对 Stage 1 sanity 同等有价值
- 如果某个 subset 需要 fallback 选择规则，必须显式记录

## 9. Stage 1 Main Objective

本分支必须遵循 v3 trainable objective，而不是旧的九损失目标。

Main objective:

```text
L_main =
  lambda_align * L_align
  + lambda_count * L_count
  + lambda_exist * L_exist
```

Current default weights:

```text
lambda_align = 1.0
lambda_count = 0.5
lambda_exist = 0.5
alpha_pb = 0.5
lambda_cal = 0.0
```

Current `L_count` decomposition:

```text
L_count =
  CE(P_count, k*)
  + alpha_pb * CE(P_pb, k*)
```

### 9.1 Explicit exclusions from Stage 1 main training

以下内容不得进入 Stage 1 main objective：

- `L_multi`
- `L_gen`
- `L_faith`
- `L_role`
- `L_cohesion`

### 9.2 Optional later additions

v3 文档允许后续增加低权重的 optional 项，但它们不是当前分支的优先事项：

- `L_type`
- `L_stabilizer`
- delayed `lambda_cal` warmup

只有在核心 Stage 1 attribution chain 稳定之后，才应考虑这些项。

### 9.3 Stage 1-only stabilizer policy

低权重 stabilizer 只允许作为 Stage 1 的训练技巧使用。

规则：

- keep them optional
- keep them switchable off
- keep `lambda_stab <= 0.05`
- do not treat them as the main contribution
- do not use them to justify pulling in Stage 2 data

## 10. Canonical Model Structure for This Branch

本分支实现应被理解为完整 MICA-v3 算法中的 Stage 1 子集：

```text
EditUnit normalization
  -> lightweight evidence encoder
  -> Kmax latent intent slots
  -> slot existence
  -> dual-cardinality count
  -> evidence-first Hungarian attribution
```

当前分支实现状态：

- `EditUnit` schema：已实现
- observable evidence features：已实现
- lightweight encoder：已实现
- slot decoder：已实现
- count head + Poisson-binomial count：已实现
- Hungarian matching：已实现
- Stage 1 main losses：已实现
- structured intent plan builder：尚未作为正式分支产物实现
- evidence-locked renderer：本分支尚未实现

## 11. Stage 1 Sanity Run Protocol

Stage 1 sanity 是本地 chain-validation run，不是论文评测。

### 11.1 Path policy

synthetic source 的优先级：

1. CLI `--synthetic-jsonl`
2. environment `MICA_STAGE1_SYNTHETIC_JSONL`
3. config `synthetic_jsonl`

规则：

- fail fast if all three are absent
- committed config keeps `synthetic_jsonl: null`
- local runtime-only path must not be hard-coded into committed config

### 11.2 Runtime outputs

允许的本地 runtime outputs：

- `outputs/mica_stage1_sanity_<timestamp>/stage1_sanity_manifest.json`
- `outputs/mica_stage1_sanity_<timestamp>/metrics.json`
- `outputs/mica_stage1_sanity_<timestamp>/training_log.jsonl`
- `outputs/mica_stage1_sanity_<timestamp>/dev_predictions_sample.jsonl`
- `outputs/mica_stage1_structure_audit_<timestamp>/...`
- `outputs/mica_stage1_curriculum_<timestamp>/manifest_easy.json`
- `outputs/mica_stage1_curriculum_<timestamp>/manifest_medium.json`
- `outputs/mica_stage1_curriculum_<timestamp>/manifest_hard.json`
- `outputs/mica_stage1_sanity_easy_<timestamp>/...`
- `outputs/mica_stage1_sanity_medium_<timestamp>/...`

允许提交的 summary：

- `reports/mica_stage1_sanity_data_audit.json`
- `reports/mica_stage1_sanity_data_audit.md`
- `reports/mica_stage1_sanity_result.json`
- `reports/mica_stage1_sanity_result.md`
- `reports/mica_stage1_synthetic_structure_audit.json`
- `reports/mica_stage1_synthetic_structure_audit.md`
- `reports/mica_stage1_curriculum_manifest_summary.json`
- `reports/mica_stage1_curriculum_manifest_summary.md`
- `reports/mica_stage1_curriculum_sanity_result.json`
- `reports/mica_stage1_curriculum_sanity_result.md`
- `reports/mica_stage1_attribution_debug.json`
- `reports/mica_stage1_attribution_debug.md`
- `reports/mica_stage1_assignment_overfit_result.json`
- `reports/mica_stage1_assignment_overfit_result.md`

### 11.3 Stage 1 curriculum sanity protocol

最初那个很小的本地 sanity subset，不能作为 attribution learning 成立的充分证据。

当前分支策略是按 curriculum level 报告 Stage 1 sanity：

- `easy`
  - confirms that the model can learn basic `k=1` / `k=2` behavior on obvious synthetic separation
- `medium`
  - checks whether attribution exceeds trivial clustering behavior on less degenerate `synthetic_k2`
- `hard`
  - stress test only; not required for MVP passage

当前工作定义：

- `easy`
  - `k1`: 100 train / 25 dev
  - `k2`: 100 train / 25 dev
  - allows singleton intents and strong file-path separation
- `medium`
  - `k1`: 100 train / 25 dev
  - `k2`: 100 train / 25 dev
  - prefers:
    - `total_edit_units >= 4`
    - each intent has at least 2 edit units when possible
    - file-path baseline ceiling around `<= 0.90`
    - random-gold-k ceiling around `<= 0.80`
- `hard`
  - `k1`: 100 train / 25 dev
  - `k2`: 100 train / 25 dev
  - prefers:
    - `total_edit_units >= 4`
    - each intent has at least 2 edit units
    - file-path baseline ceiling around `<= 0.75`

如果 `medium` 或 `hard` 样本不足：

- 按记录好的顺序放宽条件
- 记录 `fallback_applied`
- 记录 `fallback_reason`
- 不得扩展到 `hard_b`、`M` 或任何 Stage 2 来源

### 11.4 Sanity metrics

必需的 sanity metrics：

- `train_loss_first_epoch`
- `train_loss_last_epoch`
- `dev_loss`
- `count_accuracy`
- `binary_multi_accuracy`
- `over_split_rate_on_k1`
- `under_split_rate_on_k2`
- `slot_collapse_rate`
- `assignment_entropy`
- `oracle_k_alignment_pairwise_f1`
- `predicted_k_alignment_pairwise_f1`
- `alignment_pairwise_f1_all_one_cluster`
- `alignment_pairwise_f1_file_path_baseline`
- `alignment_pairwise_f1_random_gold_k_mean`
- `alignment_gain_over_all_one`
- `alignment_gain_over_file_path`
- `alignment_gain_over_random_gold_k`
- `unit_accuracy_hungarian`
- `hunk_accuracy_hungarian`
- `macro_intent_f1_hungarian`
- `micro_intent_f1_hungarian`
- `per_intent_recall_mean`
- `per_intent_precision_mean`
- `k2_split_recall`
- `second_slot_gold_recall`
- `second_slot_assignment_mass`
- `foreground_slot_usage_count`
- `effective_slot_count_mean`
- `assignment_top1_nonprimary_fraction`
- `all_one_unit_accuracy`
- `file_path_unit_accuracy`
- `random_gold_k_unit_accuracy_mean`
- `all_one_macro_intent_f1`
- `file_path_macro_intent_f1`
- `random_gold_k_macro_intent_f1_mean`

这些是 chain-validation metrics，不是最终 paper metrics。

### 11.5 File-path baseline ceiling and singleton-intent pitfall

如果本地 sanity subset 的 file-path baseline 很高，就不能根据这个 subset 宣称 attribution 已成功学习。

解释规则：

- if file-path baseline is around `0.90+`, that subset is path-dominated
- if file-path baseline remains near `1.0`, the subset is not a meaningful proof that attribution has been learned
- if singleton-intent frequency is high, pairwise F1 can be distorted by degenerate grouping structure
- do not interpret count improvement or non-zero F1 as attribution success without checking these conditions

### 11.6 Stage 1 attribution debug protocol

在继续改动 Stage 1 attribution 之前，先运行一轮显式 debug pass，检查：

- whether `oracle-k` and `predicted-k` alignment really use different active-slot selection
- whether the current model beats trivial and observable baselines
- whether gold masks are non-empty, mutually exclusive, and cover all active edit units
- whether padding is excluded from both loss and metrics
- whether slot collapse is happening at the assignment level or only at the count level

必需的 debug artifacts：

- `reports/mica_stage1_attribution_debug.json`
- `reports/mica_stage1_attribution_debug.md`

### 11.7 Trivial baseline definitions

For Stage 1 attribution sanity, the following baselines must be reported explicitly:

- `all_one_cluster`
  - every active edit unit is assigned to one cluster
- `file_path_baseline`
  - active edit units are clustered by file path
- `random_gold_k`
  - a seed-fixed balanced random assignment using the gold `k`

Count improvement is not attribution success.

The Stage 1 attribution chain is only behaving usefully if `model_oracle_k_alignment_f1` exceeds at least the trivial and random baselines with margin.

### 11.8 Oracle-k vs predicted-k evaluation

Definitions:

- `oracle_k_alignment_pairwise_f1`
  - evaluates grouping quality using `gold_count`
  - should not be penalized by count prediction error
- `predicted_k_alignment_pairwise_f1`
  - evaluates grouping quality using model `predicted_count`
  - exposes the combined effect of attribution and count

If these two are numerically identical, do not assume that the eval is correct.

First confirm whether:

- active-slot selection is really different
- the model is simply collapsing to one foreground slot

### 11.9 Gold mask validation

Stage 1 sanity must validate:

- `atomic_k1`
  - every active edit unit maps to intent `0`
- `synthetic_k2`
  - both intent masks are non-empty
  - masks are mutually exclusive
  - masks cover all active non-padding edit units
- padding
  - does not enter `L_align`
  - does not enter Hungarian matching
  - does not enter alignment metrics

### 11.10 Assignment collapse diagnosis

Stage 1 attribution debug must report:

- assignment top-1 slot distribution
- slot usage histogram
- average assignment mass per slot
- slot-pair cosine similarity
- assignment entropy by `k`
- matched vs unmatched slot existence distributions

If one foreground slot absorbs nearly all active edit units, that is attribution collapse even when count metrics improve.

### 11.11 Direct attribution metrics

Pairwise F1 alone is insufficient for Stage 1 attribution sanity.

The branch must also report direct attribution metrics after Hungarian matching:

- `unit_accuracy_hungarian`
- `hunk_accuracy_hungarian`
- `macro_intent_f1_hungarian`
- `micro_intent_f1_hungarian`
- `per_intent_recall_mean`
- `per_intent_precision_mean`

These must be compared against corresponding simple baselines:

- `all_one_unit_accuracy`
- `file_path_unit_accuracy`
- `random_gold_k_unit_accuracy_mean`
- `all_one_macro_intent_f1`
- `file_path_macro_intent_f1`
- `random_gold_k_macro_intent_f1_mean`

Count improvement does not substitute for direct attribution improvement.

### 11.12 Why pairwise F1 alone is insufficient

`pairwise_f1` can be dominated by degenerate cluster structure.

Failure modes:

- all-one clustering can remain competitive when one intent dominates pair counts
- file-path clustering can appear strong when `synthetic_k2` is naturally separable by file
- random balanced assignments can look better than expected when the subset is structurally shallow

Branch policy:

- do not claim attribution success from pairwise F1 alone
- require direct unit/hunk metrics and second-slot diagnostics
- require explicit baseline comparison, not just raw loss decrease

### 11.13 Second-slot recall diagnostic

Stage 1 sanity must report:

- `k2_split_recall`
- `second_slot_gold_recall`
- `second_slot_assignment_mass`
- `foreground_slot_usage_count`
- `effective_slot_count_mean`
- `assignment_top1_nonprimary_fraction`

Interpretation:

- if `k2_split_recall == 0`, the model is not separating two gold intents in practice
- if `second_slot_gold_recall == 0`, the minority gold intent is collapsing into the primary slot
- if `assignment_top1_nonprimary_fraction == 0`, top-1 assignment remains a single-slot collapse

### 11.14 Assignment overfit test

Before trusting a Stage 1 training failure, verify assignment learnability on a tiny medium-subset overfit diagnostic.

Required overfit settings:

- `20 k2 only`
- `50 k2 only`
- `50 k2 + 50 k1`
- optional `align_only` diagnostic

Purpose:

- determine whether the assignment head, Hungarian matching, and `L_align` are learnable at all
- separate learnability failures from generalization failures

Branch interpretation:

- if no tiny overfit setting passes, do not scale data or continue Stage 1 protocol freezing
- fix assignment / loss correctness first

### 11.15 Loss correctness probe

Stage 1 attribution sanity must explicitly verify:

- perfect assignment has substantially lower `L_align` than all-one assignment
- swapped slots remain low-loss after Hungarian matching
- padding does not contaminate the perfect-vs-all-one comparison

This probe is diagnostic only. It does not change the main objective.

### 11.16 Align-only diagnostic policy

An `align_only` overfit run is allowed for debugging, with:

- `lambda_count = 0`
- `lambda_exist = 0`

Rules:

- use only as a diagnostic
- do not present it as the branch objective
- do not replace the main Stage 1 claim with align-only results
- use it to answer one question only: whether `L_align` can drive assignment separation at all

### 11.17 Stage 1 slot competition ablation

After assignment overfit and loss-correctness probes pass, Stage 1 must test whether normal training still collapses because of schedule dynamics rather than unlearnable attribution.

Required ablation questions:

- does mixed `k1/k2` training suppress early slot specialization?
- do `count` / `existence` losses suppress attribution when introduced too early?
- does deterministic assignment-mass / pb-prior coupling worsen collapse?
- is the current failure just an undertraining problem?

Branch rule:

- answer these questions before changing the paper claim
- do not jump to Stage 2 to rescue a Stage 1 schedule failure

### 11.18 Align-only warmup hypothesis

Hypothesis:

- early `count` / `existence` pressure can prevent foreground slots from specializing
- a short `align-only` warmup may let slots separate before count calibration

Diagnostic interpretation:

- if `align-only warmup then full` succeeds while normal mixed training fails, the bottleneck is training schedule, not assignment learnability
- this remains Stage 1 work, not Stage 2

### 11.19 K2-focused warmup hypothesis

Hypothesis:

- early `k1` exposure can teach the model that collapsing to one slot is locally safe
- `k2-focused` warmup may be needed before mixing in `atomic_k1`

Diagnostic interpretation:

- if `k2-only` generalization succeeds while mixed settings fail, then `k1/k2` mixing is suppressing early slot specialization
- if `k2-focused warmup then mixed` still fails, the warmup may need to remain longer or the representation may still be too weak

### 11.20 Count/existence coupling risk

The current branch contains deterministic couplings:

- assignment-mass to slot-existence
- Poisson-binomial prior to count logits

These are allowed as Stage 1 training aids, but they are not part of the main claim.

Policy:

- treat them as optimization choices
- ablate them explicitly when attribution collapse persists
- do not attribute Stage 1 failure to representation until coupling-induced collapse has been checked

### 11.21 When to freeze Stage 1 protocol

Formal Stage 1 protocol freezing requires more than trainability.

At minimum:

- assignment overfit must pass on nondegenerate `k2`
- direct attribution metrics must beat the `all-one` baseline on `medium`
- `second_slot_gold_recall` must be nontrivial
- a plausible Stage 1 schedule must exist without using Stage 2 data

If `slot_competition_fix_found = false`, do not freeze the formal Stage 1 protocol.

### 11.22 Stage 1 freeze gate

Formal Stage 1 protocol/split freezing is not allowed merely because the training chain runs.

Current branch policy:

- the subset used for attribution sanity must not be obviously degenerate
- `medium` should show attribution gain over trivial baselines
- do not use `hard_b` or `M` to rescue Stage 1 attribution sanity
- only after that should the branch freeze a formal Stage 1 evaluation protocol

### 11.23 Stage 1 staged curriculum schedule

Once the branch establishes that:

- assignment can overfit on nondegenerate `k2`
- `L_align` is structurally correct
- naive mixed `k1/k2` training still collapses

the next Stage 1 step is staged schedule design, not Stage 2 escalation.

Current branch policy:

- treat `k2-only` training as an attribution upper reference
- test whether `k1` can be reintroduced gradually without destroying second-slot specialization
- report both `mixed_dev` and `k2_only_dev`
- do not replace the branch objective or data boundary while doing this

### 11.24 K2 specialization before K1 reintroduction

Current working hypothesis:

- `synthetic_k2` provides the cleanest early supervision for foreground-slot specialization
- early `atomic_k1` pressure can teach the model that a single foreground slot is locally sufficient

Therefore staged Stage 1 schedules may require:

- an initial `k2-only` phase
- delayed `k1` introduction
- a controlled `k2:k1` mixture rather than naive balanced mixing from epoch 1

Important interpretation rule:

- `k2-only` success is not itself the final protocol
- it is only an upper reference for attribution capacity under Stage 1 data

### 11.25 Replay-protected mixed training

When `k1` is reintroduced, the branch may use replay-protected mixed training.

Purpose:

- preserve already learned `k2` slot specialization
- reduce catastrophic drift back to `all-one` behavior during mixed training

Acceptable Stage 1 tactic:

- keep a fixed `k2` replay subset or replay ratio during mixed epochs

This is still Stage 1 because:

- it does not add Stage 2 data
- it does not change the main loss family
- it only changes optimization schedule and sample exposure

### 11.26 Coupling delay policy

The branch already contains deterministic optimization couplings:

- assignment-mass -> slot-existence
- Poisson-binomial prior -> count logits

Stage 1 policy:

- these couplings may be delayed, weakened, or disabled during early attribution specialization
- if staged runs show that delayed/disabled coupling preserves second-slot behavior better, formal Stage 1 should adopt the delayed schedule
- this remains an optimization-policy decision, not a new paper contribution

### 11.27 Formal Stage 1 freeze criteria after staged schedules

A formal Stage 1 schedule should not be frozen unless a staged mixed protocol is viable.

Current gate:

- `staged_schedule_fix_found = true`
- mixed-dev `k2_split_recall` is nontrivial
- mixed-dev `second_slot_gold_recall` is nontrivial
- mixed-dev direct attribution metrics beat `all-one`
- `k1` reintroduction no longer destroys slot specialization

If staged schedules still fail:

- do not use `hard_b` or `M` to patch the problem
- do not jump to Stage 2
- investigate Stage 1 evidence representation or assignment architecture first

### 11.28 T2 replay-protected Stage 1 schedule

The current strongest staged candidate is `T2_replay_protected_mixed`.

Definition:

- epochs 1-8: train `synthetic_k2` only
- epochs 1-8 loss weights: `L_align=1.0`, `L_count=0.2`, `L_exist=0.2`
- epochs 9-15: train mixed `atomic_k1` / `synthetic_k2`
- epochs 9-15 replay rule: `k2_replay_ratio >= 0.5`
- epochs 9-15 loss weights: `L_align=1.0`, `L_count=0.5`, `L_exist=0.5`

Interpretation:

- T2 is a candidate formal Stage 1 schedule, not a frozen protocol
- T2 remains Stage 1-only because it changes schedule and sample exposure only
- T2 must be compared against naive balanced mixed training at the same scale and seed

### 11.29 Stage 1 scale-up validation

T2 must pass scale-up validation before any formal Stage 1 split/protocol freeze.

Required validation:

- Scale A sanity reference: `100 k1 train / 100 k2 train / 25 k1 dev / 25 k2 dev`
- Scale B medium: `300 / 300 / 75 / 75`
- Scale C larger: prefer `800 / 800 / 200 / 200`; allowed CPU fallback is `500 / 500 / 125 / 125`
- every scale must run both naive balanced mixed and T2 replay-protected mixed

Scale-up gate:

- T2 must pass mixed-dev direct attribution thresholds on Scale B and Scale C
- T2 must improve over naive on `second_slot_gold_recall`
- T2 must reduce `slot_collapse_rate` relative to naive

If T2 fails scale-up:

- do not freeze formal Stage 1
- do not enter Stage 2
- investigate Stage 1 representation, assignment architecture, or training capacity

### 11.30 Naive mixed baseline requirement

Naive balanced mixed training is a required control for T2.

The branch must not claim that replay protection is necessary or sufficient unless:

- naive and T2 use the same data scale
- naive and T2 use the same seed and comparable initialization policy
- naive trains mixed `k1/k2` from epoch 1
- naive does not use replay
- reports include T2-minus-naive deltas

Required deltas:

- `delta_k2_split_recall`
- `delta_second_slot_gold_recall`
- `delta_unit_accuracy_gain_over_all_one`
- `delta_slot_collapse_rate`
- `delta_count_accuracy`
- `delta_over_split_rate_on_k1`

### 11.31 Formal Stage 1 freeze criteria after T2 scale-up

Formal Stage 1 freeze is allowed only if:

- `t2_scaleup_validated = true`
- Scale B and Scale C both pass the T2 mixed-dev threshold set
- T2 is stable relative to naive balanced mixed
- no Stage 2 data or losses are used

Current branch result:

- Scale A reproduced T2 second-slot behavior under the fixed schedule
- Scale B improved over naive on second-slot recall but missed the T2 pass threshold
- Scale C fallback showed scale sensitivity and T2 underperformed naive
- `t2_scaleup_validated = false`

Therefore:

- the candidate formal Stage 1 schedule cannot be frozen yet
- the next work should stay inside Stage 1 and target representation/architecture or capacity, not Stage 2 escalation

### 11.32 Stage 1 candidate schedule comparison

After T2 scale-up failed, the branch must compare candidate schedules rather than invent another schedule immediately.

The comparison question is:

```text
At larger Stage 1 medium scale, is naive balanced mixed training consistently better than
T2 replay-protected mixed training, or was the Scale C result a seed/sample artifact?
```

Candidate schedules:

- `naive_balanced_mixed`
- `T2_replay_protected_mixed`

Primary comparison scale:

- Scale C fallback: `500 k1 train / 500 k2 train / 125 k1 dev / 125 k2 dev`

Required seeds:

- `[13, 42, 2026]` unless runtime forces a documented downgrade

Policy:

- do not add new schedules in this comparison step
- do not change model structure
- do not change loss structure
- do not use Stage 2 data to decide a Stage 1 schedule

### 11.33 Naive mixed vs replay-protected mixed

The comparison must report, for each seed and schedule:

- direct attribution metrics
- count and over-split metrics
- slot-collapse metrics
- pass/fail under the same Stage 1 threshold set

The comparison must summarize each schedule over seeds:

- mean
- std
- min
- max
- pass count
- pass rate

Core decision metrics:

- `k2_split_recall_mixed`
- `second_slot_gold_recall_mixed`
- `unit_accuracy_gain_over_all_one_mixed`
- `slot_collapse_rate_mixed`
- `count_accuracy_mixed`
- `over_split_rate_on_k1_mixed`

### 11.34 Multi-seed validation policy

A schedule cannot be frozen from a single seed.

Candidate schedule validation requires:

- pass rate at least `0.67`
- mean second-slot recall not worse than the competing schedule
- mean unit-accuracy gain not worse than the competing schedule
- mean slot-collapse rate not worse than the competing schedule
- no seed variance high enough to reverse the conclusion

If neither schedule clearly dominates:

- `candidate_schedule_validated = unstable` or `none`
- do not freeze formal Stage 1
- continue with Stage 1 representation or assignment architecture work

### 11.35 Candidate schedule freeze criteria

Current comparison result:

- `naive_balanced_mixed` passed all three Scale C seeds
- `T2_replay_protected_mixed` passed two of three Scale C seeds
- naive had higher mean `second_slot_gold_recall`
- naive had higher mean `unit_accuracy_gain_over_all_one`
- naive had lower mean `slot_collapse_rate`
- seed variance was not high enough to change the conclusion
- `candidate_schedule_validated = naive`

Therefore:

- the next Stage 1 step may freeze a naive larger-scale candidate protocol
- this is still only a Stage 1 candidate freeze step
- Stage 2 remains out of scope until the candidate Stage 1 protocol/split is explicitly frozen and re-run

### 11.36 Formal Stage 1 candidate schedule

The candidate formal Stage 1 schedule is now:

```text
candidate_stage1_schedule = naive_balanced_mixed_large_scale
epochs = 15
train = mixed k1/k2 from epoch 1
lambda_align = 1.0
lambda_count = 0.5
lambda_exist = 0.5
replay = false
staged_k2_warmup = false
stage2_loss = false
```

This remains a Stage 1-only schedule:

- only Step1 atomic `k=1` and Step2 strict/sanity synthetic `k=2` are allowed
- no `hard_b`
- no `M weak`
- no `M alignment`
- no `RealDomainBinary`
- no Stage 2 loss
- no generation, retrieval, verifier, LLM Judge, or real API

### 11.37 Why T2 was not selected

T2 replay-protected mixed training remains useful as a diagnostic ablation, but it is not the formal candidate schedule.

Observed progression:

- T2 was effective at tiny staged curriculum scale
- T2 did not pass scale-up validation
- Scale C single-seed naive mixed was stronger than T2
- Scale C multi-seed comparison confirmed naive mixed was more stable

Scale C multi-seed summary:

- seeds: `[13, 42, 2026]`
- `naive_balanced_mixed pass_rate = 1.0`
- `T2_replay_protected_mixed pass_rate = 0.6667`
- naive mean `second_slot_gold_recall = 0.5628`
- T2 mean `second_slot_gold_recall = 0.4063`
- naive mean `unit_accuracy_gain_over_all_one = 0.1002`
- T2 mean `unit_accuracy_gain_over_all_one = 0.0561`
- naive mean `slot_collapse_rate = 0.1267`
- T2 mean `slot_collapse_rate = 0.2333`

Conclusion:

```text
candidate_schedule_validated = naive
```

### 11.38 Why larger-scale naive mixed was selected

Larger-scale naive mixed was selected because it was the only candidate schedule that:

- passed all Scale C seeds
- had higher mean second-slot recall than T2
- had higher unit attribution gain over all-one than T2
- had lower mean slot collapse than T2
- did not rely on replay or staged warmup

This does not prove final Stage 1 success. It only justifies freezing a candidate formal Stage 1 protocol and running the official validation.

### 11.39 Formal manifest freeze

The formal manifest freeze writes runtime-only manifests:

- `outputs/mica_stage1_formal_manifest_<timestamp>/stage1_formal_manifest.json`
- `outputs/mica_stage1_formal_manifest_<timestamp>/stage1_formal_manifest_train.json`
- `outputs/mica_stage1_formal_manifest_<timestamp>/stage1_formal_manifest_dev.json`
- `outputs/mica_stage1_formal_manifest_<timestamp>/stage1_formal_manifest_test.json`

Committed reports contain only summary statistics and leakage checks:

- `reports/mica_stage1_formal_manifest_summary.json`
- `reports/mica_stage1_formal_manifest_summary.md`
- `reports/mica_stage1_protocol_freeze.json`
- `reports/mica_stage1_protocol_freeze.md`

The runtime manifest is not committed.

### 11.40 Next official Stage 1 validation

After protocol/split freeze, the next action is:

```text
run_official_stage1_validation
```

The official validation must use:

- the frozen runtime manifest
- `candidate_stage1_schedule = naive_balanced_mixed_large_scale`
- the unchanged Stage 1 objective
- all direct attribution metrics and trivial baselines
- leakage checks from the freeze report

Stage 2 remains blocked until this official Stage 1 validation passes.

## 12. Current Stage 1 Sanity Status

Current local sanity result:

- training runs end to end
- forward/backward are working
- loss decreases
- count learns above a coarse majority baseline
- the original tiny local subset is now known to be degenerate for attribution sanity
- `easy` local curriculum still behaves like a path-dominated sanity set
- `medium` local curriculum removes most singleton/path dominance but the model still does not beat the all-one baseline
- `oracle-k` and `predicted-k` are currently identical because the model still collapses to one foreground slot on dev attribution
- tiny and medium assignment-overfit settings can fit gold attribution, so current failure is not evidence that `L_align` is unlearnable
- Stage 1 slot-competition ablation shows that `k2-only` medium generalization can succeed while mixed settings still collapse
- the remaining problem is schedule-sensitive slot competition under mixed `k1/k2`, not basic inability to optimize assignment
- staged curriculum ablation found T2 replay-protected mixed training as the first tiny-scale candidate schedule
- T2 scale-up validation did not hold: Scale B missed thresholds and Scale C fallback underperformed naive mixed
- multi-seed Scale C candidate comparison showed naive balanced mixed is more stable than T2

Current status:

```text
sanity_status = inconclusive
t2_scaleup_validated = false
candidate_schedule_validated = naive
```

Reason:

- the original tiny subset should not be used as attribution evidence
- `easy` fails because attribution does not beat the all-one baseline
- `medium` still fails because attribution does not beat the all-one baseline
- mixed settings still collapse or under-recall the second slot
- only `k2-only` Stage 1 ablation currently clears the slot-competition fix threshold
- T2 is promising at tiny sanity scale but is not stable enough under Scale B/C validation
- naive larger-scale mixed now has multi-seed support as the candidate schedule, but the formal Stage 1 protocol/split has not yet been frozen

Interpretation:

- the Stage 1 skeleton is trainable
- the Stage 1 schedule question now points to naive larger-scale mixed as the candidate
- the current bottleneck is formalizing and freezing the Stage 1 protocol/split, not entering Stage 2
- Stage 2 calibration remains blocked until that Stage 1 freeze step is complete

## 13. Stage 1 Remodel Priorities

The next implementation work should not be "keep extending the skeleton".

It should be a bounded Stage 1 remodel aligned to the formal MICA-v3 algorithm.

### Priority 1: Make the decoder semantics match the v3 formulation more closely

Focus:

- foreground slot usage
- slot existence behavior
- `P_count` vs `P_pb` interaction
- oracle-k vs predicted-k gap visibility
- pairwise evidence actually affecting assignment discrimination
- collapse-resistant assignment behavior on `synthetic_k2`

Goal:

- reduce collapse and over-splitting without introducing Stage 2 data

### Priority 2: Keep Stage 1 strictly attribution-only

Do not reintroduce:

- generation-side loss
- faithfulness loss
- retrieval
- verifier
- renderer training

### Priority 3: Tighten Stage 1 data protocol

The branch should move toward:

- clearer formal distinction between sanity-only local runtime data and future frozen Stage 1 protocol
- explicit handling of reliable vs unreliable `edit_to_intent`
- explicit curriculum reporting for `easy` / `medium` / `hard`
- explicit separation between “count got better” and “attribution actually beats trivial baselines”

### Priority 4: Prepare for, but do not start, Stage 2

The implementation should leave clean interfaces for:

- `hard_b` anti-over-splitting
- `M censored k>=2`
- real alignment calibration

But none of these should be trained in the current branch step.

## 14. What This Branch Explicitly Does Not Implement

- Stage 2 `hard_b` calibration
- Stage 2 `M` censored calibration
- Stage 3 generation tuning
- role/cohesion main-objective training
- retrieval-controlled generation
- verifier-guided reranking
- DPO / RLHF tuning
- full call graph / dataflow
- full `k>=3` decomposition

## 15. Risks and Limitations

- the current Stage 1 sanity split is local and deterministic, not a formal paper split
- the current runtime synthetic source is local-only
- current alignment metrics are still sanity diagnostics
- current `easy` subset is still heavily path-dominated
- even the `medium` subset can retain a strong all-one baseline
- current branch does not yet have a frozen real alignment benchmark protocol
- current branch still needs Stage 1 decoder/count behavior improvement before any Stage 2 transition

## 16. Immediate Next Step

After this document alignment, the next work on this branch should be:

```text
Stage 1 remodel against the formal MICA-v3 algorithm,
not further ad hoc evolution of the current skeleton.
```

Concretely:

1. keep the current three-term main objective
2. keep Stage 1 limited to atomic_k1 + synthetic_k2
3. require `medium` attribution to beat the trivial baselines before calling Stage 1 stable
4. improve assignment discrimination before touching Stage 2 data
5. rerun Stage 1 curriculum sanity and attribution debug together
6. only after Stage 1 attribution stabilizes, define the formal Stage 1 protocol and then the Stage 2 entry

## 17. Downstream Skeleton Isolation Status

To avoid blocking engineering progress while advisor-facing protocol questions remain open, the branch now includes an isolated downstream skeleton:

- `code/mica/schemas.py`
- `code/mica/plan_builder.py`
- `code/mica/renderers/deterministic.py`
- `code/mica/runners/run_official_stage1_validation.py`
- `code/mica/runners/audit_future_stage2_inputs.py`
- `configs/mica/*.json`

These modules are intentionally **not** wired into the current Stage 1 training path.

Current branch policy:

- no change to Stage 1 training logic
- no change to Stage 1 report generation logic
- no change to generation pilot
- no Stage 2 training
- no hard-coded advisor-unconfirmed validation policy

The new runners are opt-in only:

- official Stage 1 runner = dry-run / readiness checker only
- future Stage 2 runner = input audit only

This keeps the current Stage 1 conclusions unchanged while allowing later implementation work to proceed against stable data contracts.

## 18. Offline Downstream Skeleton Follow-up

The downstream skeleton has now been extended into an **offline smoke pipeline**:

- prediction jsonl -> structured intent plans
- structured intent plans -> deterministic rendered messages
- dry-run official Stage 1 readiness + optional plan smoke
- future Stage 2 input audit with explicit guardrails

This still does **not** mean:

- official Stage 1 validation has been executed
- official thresholds have been applied
- generation main experiment has started
- Stage 2 is unlocked

Current branch policy remains:

- offline conversion only
- explicit CLI flags only
- no training
- no API calls
- no retrieval / verifier
- no change to the current Stage 1 scientific status
