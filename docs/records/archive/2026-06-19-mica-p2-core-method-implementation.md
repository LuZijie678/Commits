> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# MICA P2 核心方法实现

## 范围

本轮把 P2 核心方法部件实现为可测试的代码组件，但没有运行 Stage 1 validation、Stage 2/3/4 training、final eval、anti-shortcut rerun 或 OOD rerun。

本轮工作严格限制在实现、配置、诊断和单元测试边界内，没有生成或提交任何运行时实验产物。

## 已实现组件

### 1. Null / Background Slot

- 新增 `code/mica/model/null_slot.py`
- 新增 `code/mica/losses/null_slot_losses.py`
- 新增 `code/mica/eval/null_slot_metrics.py`

已实现：

- conservative background eligibility rules
- null-slot mask construction
- null-slot assignment augmentation helpers
- foreground/null split helpers
- null-slot loss and gold-to-null penalty
- background absorption / gold-to-null / null assignment metrics

保留的设计约束：

- null slot does not count as an intent
- null slot is excluded from Hungarian matching
- null slot is excluded from `L_exist`

### 2. Dual-cardinality Warmup

- 新增 `code/mica/losses/cardinality.py`
- 新增 `code/mica/schedules/loss_schedules.py`
- 更新 `code/mica/losses/mica_losses.py`，使 count supervision 通过共享的 dual-cardinality helper 路由

已实现：

- Poisson-binomial distribution helper
- `P_count` + `P_pb` loss composition
- `alpha_pb` scheduling support
- KL calibration warmup support
- `P_multi` derived only from `P_count`

明确保持：

- no `L_multi`
- no independent multi-intent classifier loss

### 3. Stabilizers and Auxiliary Type Loss

- 新增 `code/mica/schedules/assignment_schedules.py`
- 新增 `code/mica/losses/stabilizers.py`
- 新增 `code/mica/losses/type_loss.py`

已实现：

- assignment temperature schedule
- assignment entropy coefficient schedule
- entropy stabilizer loss
- optional low-weight type auxiliary loss

这些都被实现为 optional helper 和受 config 控制的附加项，不应被表述成主结论级改动。

### 4. Evidence Graph Bias Expansion

- 新增 `code/mica/evidence/relations.py`
- 新增 `code/mica/evidence/relation_bias.py`
- 新增 `code/mica/evidence/graph_features.py`
- 新增 `configs/mica/evidence_relation_spec.json`

已实现的 observable relations：

- same file
- same hunk
- path distance
- same symbol / same identifier
- same language
- test target
- doc refers to
- config/build/lockfile
- generated file
- identifier Jaccard
- file role pair

保留的约束：

- no gold same-intent leakage
- no hidden program-dependency oracle
- no message-derived inference feature enabled by default

### 5. Consistency Ablation Components

- 增强 `code/mica/losses/consistency_losses.py`
- 新增 `code/mica/training/ema_teacher.py`
- 新增 `code/mica/augmentations/diff_augmentations.py`

已实现：

- EMA teacher
- stop-gradient teacher target
- count / assignment / slot-existence consistency terms
- warmup gate
- confidence gate
- entropy gate
- stability gate
- augmentation views:
  - path masked
  - identifier masked
  - file-order permuted
  - context-line dropout

默认仍为关闭状态。

### 6. Renderer Ablation and Entity Coverage

- 增强 `code/mica/eval/message_utility.py`
- 增强 `code/mica/renderers/deterministic.py`

已实现：

- entity coverage score / penalty helper
- oracle-vs-predicted renderer comparison helper
- renderer ablation summary helper
- renderer diagnostics for evidence support and entity coverage

保留的约束：

- deterministic renderer remains evidence-locked
- attribution remains frozen
- hallucination / faithfulness signals remain proxies unless human labels exist

### 7. Training Diagnostics

- 新增 `code/mica/eval/training_diagnostics.py`

已实现：

- slot collapse rate
- active slot count distribution
- assignment entropy summary
- `P_count` / `P_pb` calibration gap
- oracle-k vs predicted-k gap
- strict replay forgetting
- gradient conflict placeholder with explicit unavailable state

## 配置更新

已更新：

- `configs/mica/stage1_protocol_spec.json`
- `configs/mica/stage2_calibration_spec.json`

新增了如下 schedule 和 auxiliary-loss 配置段：

- dual-cardinality warmup
- assignment temperature / entropy schedules
- optional type/stabilizer loss controls
- consistency gate defaults

## 验证边界

本轮仅限实现，不包含任何真实实验执行：

- no Stage 1 validation run
- no Stage 2/3/4 training run
- no final eval run
- no anti-shortcut or OOD model rerun
- no runtime outputs committed

## 下一步

下一步不应该继续发明方法，而应转向受控集成：

1. wire these options into staged trainers behind explicit config gates
2. fill real asset registry paths
3. run guarded implementation-checks
4. only then proceed to advisor-approved staged experiments
