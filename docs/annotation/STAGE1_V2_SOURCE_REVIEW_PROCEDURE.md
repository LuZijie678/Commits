# Stage1-v2 Atomic Source 人工审核流程

状态：`source_review_queue_materialized` + `human_execution_pending`

本文档说明 Stage1-v2 atomic source review 的人工审核流程。当前 queue 已生成，但未人工确认。

## 1. 当前 review 资产

- critical queue：
  - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_critical.jsonl`
- deferred queue：
  - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_deferred.jsonl`
- priority summary：
  - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_priority_summary.json`

当前计数：

- critical：`4679`
- deferred：`420`

priority 分布：

- `critical_current_and_formal`：`363`
- `critical_current_materialized_use`：`70`
- `critical_formal_scale_required`：`4073`
- `critical_high_ambiguity`：`173`
- `deferred_not_currently_blocking`：`420`

## 2. 审核目标

人工审核需要确认 source atomic commit 是否适合作为 synthetic construction 的 atomic intent 来源。

必须检查：

- 是否真实单意图。
- 是否包含多个独立 action-object。
- 是否包含大规模机械修改。
- 是否包含 generated/vendor 内容。
- 是否存在 message-derived label。
- 是否存在空 diff、异常 diff 或不可解析 diff。
- 是否存在重复、revert、backport、cherry-pick。
- 是否缺少可靠 edit-unit evidence。
- 是否含有 background/support edits。

## 3. 去重原则

- 同一 `source_atomic_commit_id` 只人工审核一次。
- 审核结果可被所有 synthetic composition 复用。
- 未人工确认的 manual-review source 不得进入 formal frozen synthetic asset。
- heuristic accepted 不等于 human verified。

## 4. 输出字段

每条 review record 至少应包含：

- `source_atomic_commit_id`
- `atomic_family_id`
- `repository`
- `current_quality_status`
- `planned_usage_count`
- `target_splits`
- `required_strata`
- `ambiguity_reasons`
- `review_priority`
- `blocking_asset_ids`
- `manual_review_status`
- `reviewer_id`
- `review_decision`
- `review_reason`
- `review_version`

## 5. Freeze gate

只有当 required atomic sources 均为 `human_verified`，且 synthetic leakage audit 通过时，才能运行 formal synthetic materialization。

当前状态：

- `required_atomic_sources_human_verified=false`
- `formal_synthetic_freeze_blocked=true`
