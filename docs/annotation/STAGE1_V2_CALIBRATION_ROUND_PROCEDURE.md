# Stage1-v2 校准轮执行流程

状态：`calibration_round_prepared` + `human_execution_pending`

本文档说明 Stage1-v2 calibration round 的执行与通过条件。当前只生成了执行包和模板，没有人工结果。

## 1. 当前执行包

- annotator A package：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_a.jsonl`
- annotator B package：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_b.jsonl`
- blinding map：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_blinding_map.json`
- adjudication template：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_adjudication_template.jsonl`
- result template：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_result_template.json`
- sampling report：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_sampling_report.json`

当前 calibration round 规模：`30` 条真实 commit 候选。

## 2. 用途

Calibration round 用于：

- 验证 annotator 是否一致理解 guideline。
- 找出 merge/split、background/support、uncertain/shared/mixed 的规则缺口。
- 决定是否需要修订 pilot guideline。
- 阻止在 guideline 未稳定时继续扩大 pilot。

Calibration round 不进入 final benchmark。

## 3. 禁止字段

Annotator package 不得包含：

- 模型预测
- 原始 commit message
- PR title
- issue text
- weak label
- predicted k
- candidate stratum 名称
- split 名称
- 另一位 annotator 的结果

## 4. 分析指标

导入 A/B 结果后，必须计算：

- exact-k agreement
- weighted kappa
- split/no-split agreement
- foreground/background agreement
- pairwise agreement
- B-cubed agreement
- ARI
- disagreement categories
- merge-vs-split disagreement
- background-vs-support disagreement
- uncertain/shared/mixed disagreement

输出：

- `calibration_round_1_agreement_report.json`
- `calibration_round_1_disagreement_queue.jsonl`
- `guideline_revision_proposal.md`

## 5. Gate

若低于协议 gate：

- `guideline_status=revision_required`
- pilot 不得继续扩大执行
- annotator 需要重新培训并重做 calibration round

若达到协议 gate：

- `guideline_status=pilot_ready`
- 仍需人工确认，不能由代码自动冻结 final guideline
