# MICA Stage1-v2 Synthetic 正式扩容流程

状态：`synthetic_scale_candidate_planned` + `not_frozen_training_asset`

本文档说明 Stage1-v2 synthetic formal scale-up 的候选方案。当前只生成 candidate plan，没有冻结正式训练资产。

## 1. 当前小规模 synthetic 资产地位

当前已物化：

- train：`140`
- dev：`109`
- synthetic_control_test：`143`

当前状态：

- `candidate_materialized`
- `pipeline_validation_complete`
- `scale_insufficient_for_formal_training`
- `not_frozen_training_asset`

这些资产只用于验证 family-safe split 与 construction pipeline，不得作为 Stage1-v2 formal training/dev/control asset。

## 2. Scale audit

当前报告：

- `datasets/mica/stage1_v2/synthetic/synthetic_scale_audit.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_scale_gap_report.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_formal_target_plan.json`

关键观测：

- 当前总记录数：`392`
- unique atomic sources：`433`
- unique atomic families：`91`
- repository count：`58`
- 当前 synthetic 只有 `k=2`
- same-file synthetic count：`0`
- source+docs/config count：`1`
- max samples per atomic source：`9`
- max samples per atomic family：`12`

## 3. Formal target candidate

候选规模：

- synthetic_train：
  - minimum：`3000`
  - target：`5000-8000`
- synthetic_dev：
  - minimum：`400`
  - target：`500-800`
- synthetic_control_test：
  - minimum：`400`
  - target：`500-800`

候选约束：

- 单 atomic source 在同一 split 内最多进入 `3` 个 synthetic samples。
- dev/control 单 repository 不超过 `5%`。
- train 单 repository 不超过 `10%`。
- k 分布、same-file/cross-file、source+test、source+docs/config 仍需人工确认。

## 4. 当前阻塞项

Formal scale freeze 当前被阻塞：

- `k3_k4_construction_not_implemented`
- `required_atomic_sources_need_human_verification`

当前容量估计：

- accepted source count：`3754`
- manual-review source count：`1345`
- accepted-only pair capacity at reuse cap：`5631`
- accepted-plus-manual pair capacity at reuse cap：`7648`
- planned minimum total samples：`3800`

## 5. 当前候选输出

- `datasets/mica/stage1_v2/synthetic/formal_synthetic_composition_plan.jsonl`
- `datasets/mica/stage1_v2/synthetic/required_atomic_sources.jsonl`
- `datasets/mica/stage1_v2/synthetic/unresolved_atomic_sources.jsonl`
- `datasets/mica/stage1_v2/synthetic/projected_split_summary.json`
- `datasets/mica/stage1_v2/synthetic/projected_leakage_report.json`

这些文件是 formal materialization 的候选输入，不是 frozen asset。

## 6. Freeze 条件

正式 scale-up 只有在以下条件都满足后才能执行：

- required atomic sources 全部 human verified。
- k=3/k=4 construction 支持已实现并测试。
- formal target scale 和 strata mix 经人工确认。
- projected leakage report 通过。
- materialized train/dev/control leakage report 通过。
- registry 仍保持 Stage1-v2 namespace，不继承 Stage1-v1 证据。
