# MICA Stage1-v2 数据与标注执行说明

状态：`infrastructure_ready` + `synthetic_assets_materialized` + `annotation_campaign_prepared` + `human_execution_pending` + `synthetic_scale_candidate_planned` + `not_formal_ready` + `stage1_v2_training_blocked` + `stage2_entry_blocked`

本文档只记录 Stage1-v2 当前已经真实物化的数据资产、候选池、标注 pilot 包和 readiness 状态。它不是训练完成、正式 benchmark 完成或 Stage 2 已解锁的证明。

## 1. 当前地位

Stage1-v2 当前已经完成的是：

- machine-readable protocol freeze：
  - `configs/mica/stage1_v2_protocol_spec.json`
- candidate / pilot asset registry：
  - `configs/mica/stage1_v2_asset_registry.json`
- family-safe synthetic split 真实物化：
  - `datasets/mica/stage1_v2/synthetic/`
- RealCount exact-count 候选池与 pilot queue：
  - `datasets/mica/stage1_v2/real_count/`
- Real-Adjudicated full-alignment 候选池、pilot 包和盲化映射：
  - `datasets/mica/stage1_v2/real_alignment/`
- background annotation pilot queue：
  - `datasets/mica/stage1_v2/background/`
- qualification 材料：
  - `datasets/mica/stage1_v2/qualification/`
- annotation readiness report：
  - `datasets/mica/stage1_v2/readiness/stage1_v2_annotation_readiness.json`
- synthetic scale audit / formal scale-up candidate plan：
  - `datasets/mica/stage1_v2/synthetic/synthetic_scale_audit.json`
  - `datasets/mica/stage1_v2/synthetic/synthetic_scale_gap_report.json`
  - `datasets/mica/stage1_v2/synthetic/synthetic_formal_target_plan.json`
- critical atomic-source review queue：
  - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_critical.jsonl`
  - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_deferred.jsonl`
- unified annotation campaign assets：
  - `datasets/mica/stage1_v2/campaign/`
- calibration round 1 packages：
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_*.jsonl`
  - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_*.json`

Stage1-v2 当前还没有完成的是：

- 真实双标 exact-count 资产
- 真实双标 + 裁决的 Real-Adjudicated-Test
- blind review 完成记录
- Kmax 的 Stage1-v2 正式 freeze
- null-enabled Stage1-v2 checkpoint
- Stage1-v2 baseline / anti-shortcut / multi-seed 真实结果
- Stage1-v2 训练
- Stage1-v2 final test
- Stage 2 入口
- 人员注册、资格测试、calibration round、pilot 双标、裁决和 blind review

## 2. 三类资产边界

Stage1-v2 必须严格区分三类资产：

- `Synthetic-Train`
  - 仅用于 slot attribution 训练监督。
  - 不作为真实论文主结果。
- `Synthetic-Control-Test`
  - 仅用于受控 synthetic 机制分析。
  - 显式标记 `controlled_synthetic_evaluation_only=true`。
- `Real-Adjudicated-Test`
  - 未来的真实论文主 benchmark。
  - 当前仍为 `annotation_pending` / `pending_generation`，尚未 freeze。

## 3. Atomic source 审计与 family-safe synthetic 物化

### 3.1 Atomic source 质量审计

来源池：

- `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`

当前真实审计产物：

- `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_quality_report.json`
- `datasets/mica/stage1_v2/atomic_source_pool/accepted_atomic_sources.jsonl`
- `datasets/mica/stage1_v2/atomic_source_pool/manual_review_queue.jsonl`
- `datasets/mica/stage1_v2/atomic_source_pool/rejected_atomic_sources.jsonl`

当前审计结果：

- source rows：`5099`
- accepted：`3754`
- manual review：`1345`
- rejected：`0`
- source quality status：`source_quality_unverified`
- formal ready：`false`

说明：

- 当前不会因为旧流程把来源称为 `conservative_atomic`，就自动将其当作可冻结 atomic gold。
- `manual_review_queue.jsonl` 中的来源仍需人工确认是否真正单意图 atomic commit。

### 3.2 Family-safe synthetic split

当前真实物化产物：

- `datasets/mica/stage1_v2/synthetic/synthetic_train.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_dev.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_control_test.jsonl`
- `datasets/mica/stage1_v2/synthetic/atomic_family_map.jsonl`
- `datasets/mica/stage1_v2/synthetic/split_summary.json`
- `datasets/mica/stage1_v2/synthetic/cross_split_leakage_report.json`
- `datasets/mica/stage1_v2/synthetic/excluded_records.jsonl`
- `datasets/mica/stage1_v2/synthetic/construction_errors.jsonl`

当前 split 计数：

- train：`140`
- dev：`109`
- synthetic_control_test：`143`

当前 repository 计数：

- train：`18`
- dev：`10`
- synthetic_control_test：`30`

当前 family-safe 约束结果：

- `sample_overlap=0`
- `source_atomic_commit_overlap=0`
- `atomic_family_overlap=0`
- `construction_group_overlap=0`
- `normalized_diff_overlap=0`
- `PR overlap=0`
- `leakage_clean=true`

当前构造异常：

- `construction_error_count=20`
- `fatal_construction_error_count=0`
- 当前 `construction_errors.jsonl` 仅包含 `source_pair_precheck_skip`，未阻止 split 物化。

当前状态：

- `synthetic_assets_materialized`
- `pipeline_validation_complete`
- `scale_insufficient_for_formal_training`
- `not_frozen_training_asset`
- `controlled_synthetic_evaluation_only=true` 仅适用于 `synthetic_control_test`
- `real_paper_main_test=false`

### 3.3 Synthetic scale audit 与 formal target candidate

当前新增 scale audit 产物：

- `datasets/mica/stage1_v2/synthetic/synthetic_scale_audit.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_scale_gap_report.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_formal_target_plan.json`

当前小规模 synthetic 物化资产的定位：

- train：`140`
- dev：`109`
- synthetic_control_test：`143`
- status：`candidate_materialized`
- pipeline validation：`complete`
- formal training scale：`insufficient`
- formal frozen training asset：`false`

关键 scale audit 观测：

- total synthetic records：`392`
- unique atomic sources：`433`
- unique atomic families：`91`
- repositories：`58`
- 当前 gold k 分布：`k=2: 392`
- same-file synthetic count：`0`
- source+docs/config count：`1`
- max samples per atomic source：`9`
- max samples per atomic family：`12`

formal target candidate：

- synthetic_train：
  - minimum：`3000`
  - target：`5000-8000`
- synthetic_dev：
  - minimum：`400`
  - target：`500-800`
- synthetic_control_test：
  - minimum：`400`
  - target：`500-800`

当前 formal scale freeze 阻塞原因：

- `k3_k4_construction_not_implemented`
- `required_atomic_sources_need_human_verification`

候选计划文件：

- `datasets/mica/stage1_v2/synthetic/formal_synthetic_composition_plan.jsonl`
- `datasets/mica/stage1_v2/synthetic/required_atomic_sources.jsonl`
- `datasets/mica/stage1_v2/synthetic/unresolved_atomic_sources.jsonl`
- `datasets/mica/stage1_v2/synthetic/projected_split_summary.json`
- `datasets/mica/stage1_v2/synthetic/projected_leakage_report.json`

这些文件只是 formal scale-up 的候选计划，不是 frozen asset。

### 3.4 Critical atomic-source review queue

当前新增 review queue：

- `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_critical.jsonl`
- `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_deferred.jsonl`
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

当前状态：

- `required_atomic_sources_human_verified=false`
- 未人工确认的 required source 不得进入 formal frozen synthetic asset。

## 4. RealCount-TrainDev exact-count 候选池

当前真实物化产物：

- `datasets/mica/stage1_v2/real_count/real_count_candidate_pool.jsonl`
- `datasets/mica/stage1_v2/real_count/real_count_annotation_queue_pilot.jsonl`
- `datasets/mica/stage1_v2/real_count/real_count_candidate_summary.json`
- `datasets/mica/stage1_v2/real_count/real_count_leakage_report.json`
- `datasets/mica/stage1_v2/real_count/real_count_exclusions.jsonl`

当前计数：

- candidate pool：`5856`
- pilot queue：`200`
- repositories：`1446`

来源分解：

- `real_candidate`：`3244`
- `m_weak`：`2130`
- `hard_b`：`482`

当前 split 计数：

- train：`4707`
- dev：`1149`

当前 provisional strata 计数：

- `probable_k1_regular`：`3244`
- `probable_k1_hard_single`：`482`
- `probable_k2`：`1090`
- `probable_k3`：`391`
- `probable_k4_or_complex`：`649`
- `background_heavy`：`286`
- `cross_module`：`288`
- `large_commit`：`1449`
- `ambiguous_boundary`：`43`
- `same_file_multi_intent`：`10`

重要约束：

- 这些 strata 只用于 pilot sampling 和后续人工标注分层。
- `annotator_a_exact_k`
- `annotator_b_exact_k`
- `adjudicated_exact_k`
  - 当前全部保持为空。
- weak label 不得自动转成 exact count。

当前状态：

- candidate pool：`candidate_materialized`
- pilot queue：`annotation_pending`
- Kmax asset：`pending_generation`

## 5. Real-Adjudicated pilot 候选池与盲化包

当前真实物化产物：

- `datasets/mica/stage1_v2/real_alignment/real_adjudicated_candidate_pool.jsonl`
- `datasets/mica/stage1_v2/real_alignment/real_adjudicated_pilot_candidates.jsonl`
- `datasets/mica/stage1_v2/real_alignment/annotator_a_package.jsonl`
- `datasets/mica/stage1_v2/real_alignment/annotator_b_package.jsonl`
- `datasets/mica/stage1_v2/real_alignment/adjudicator_package_template.jsonl`
- `datasets/mica/stage1_v2/real_alignment/pilot_blinding_map.json`
- `datasets/mica/stage1_v2/real_alignment/pilot_sampling_report.json`
- `datasets/mica/stage1_v2/real_alignment/pilot_leakage_report.json`
- `datasets/mica/stage1_v2/real_alignment/pilot_exclusions.jsonl`
- `datasets/mica/stage1_v2/real_alignment/provisional_sampling_report.json`
- `datasets/mica/stage1_v2/real_alignment/uncovered_strata_report.json`
- `datasets/mica/stage1_v2/real_alignment/repository_concentration_report.json`

当前计数：

- candidate pool：`1800`
- candidate repositories：`710`
- pilot package：`100`
- pilot repositories：`54`

当前 pilot strata 计数：

- `probable_k1_regular`：`15`
- `probable_k1_hard_single`：`15`
- `probable_k2`：`35`
- `probable_k3`：`20`
- `probable_k4_or_complex`：`15`

当前 pilot 附加 strata 计数：

- `background_heavy`：`8`
- `cross_module`：`11`
- `ambiguous_boundary`：`2`
- `large_commit`：`55`

当前 repository concentration：

- candidate max repository share：`0.013888888888888888`
- candidate top-5 share：`0.06944444444444445`
- pilot max repository share：`0.15`
- pilot top-5 share：`0.3`

当前 blinding 约束：

- annotator A/B package 不包含：
  - 模型预测
  - commit message
  - PR title
  - issue text
  - weak label
  - predicted k
  - split 名称
  - 另一位标注者结果
- `pilot_blinding_map.json` 与 annotator package 分离保存。

当前状态：

- candidate pool：`candidate_materialized`
- pilot package：`annotation_pending`
- blind review asset：`pending_generation`
- final adjudicated test：`pending_generation`

## 6. Background pilot 与 qualification 资产

### 6.1 Background pilot

当前真实物化产物：

- `datasets/mica/stage1_v2/background/background_annotation_queue_pilot.jsonl`
- `datasets/mica/stage1_v2/background/background_candidate_distribution.json`

当前计数：

- queue rows：`120`

当前类型分布：

- formatting：`50`
- import_sorting：`43`
- unspecified：`41`
- mechanical_snapshot：`7`
- generated：`6`
- lockfile：`5`
- vendor：`1`

说明：

- 当前只是背景标注候选集，不是 gold background。
- 文件角色或扩展名不得自动视为人工真值。

### 6.2 Qualification 材料

当前真实物化产物：

- `datasets/mica/stage1_v2/qualification/annotator_examples.jsonl`
- `datasets/mica/stage1_v2/qualification/qualification_test.jsonl`
- `datasets/mica/stage1_v2/qualification/qualification_answer_key_private.jsonl`

当前 gate：

- `exact_k_accuracy >= 0.85`
- `pairwise_partition_f1 >= 0.80`
- `background_classification_f1 >= 0.85`

说明：

- `qualification_answer_key_private.jsonl` 不进入 annotator public package。
- 当前只实现评分与报告，不自动授予标注资格。

## 7. 标注工作流与状态机

当前代码入口：

- `code/mica/stage1_v2/annotation_workflow.py`
- `code/mica/runners/run_stage1_v2_annotation_readiness.py`

当前强制状态机：

`pending`
→ `annotated_a` / `annotated_b`
→ `independently_double_annotated`
→ `agreement` / `conflict`
→ `adjudication_pending`
→ `adjudicated`
→ `quality_reviewed`
→ `eligible_for_asset`

当前 workflow 保证：

- A/B 原始标注不可互相覆盖。
- adjudicated 结果不可覆盖 raw A/B。
- 未裁决冲突样本不能进入正式资产。
- 所有导入都校验：
  - annotator ID
  - sample ID
  - guideline version
  - annotation schema
  - 时间戳
  - annotation history

## 8. 当前 annotation readiness

只读 readiness 报告：

- `datasets/mica/stage1_v2/readiness/stage1_v2_annotation_readiness.json`

当前关键状态：

- `real_count_candidate_pool_ready=true`
- `real_count_pilot_queue_ready=true`
- `real_count_double_annotation_rate=0.0`
- `real_count_adjudication_rate=0.0`
- `Kmax_asset_ready=false`
- `real_adjudicated_candidate_pool_ready=true`
- `alignment_pilot_queue_ready=true`
- `alignment_double_annotation_rate=0.0`
- `alignment_adjudication_rate=0.0`
- `blind_review_complete=false`
- `benchmark_strata_provisional=true`
- `benchmark_strata_adjudicated=false`
- `background_annotation_ready=true`
- `guideline_pilot_version=stage1-v2-alignment-guideline-pilot-v1`
- `guideline_final_frozen=false`
- `annotation_assets_formal_ready=false`
- `stage1_v2_training_allowed=false`
- `stage2_entry_allowed=false`
- `synthetic_scale_sufficient=false`
- `required_atomic_sources_human_verified=false`
- `annotation_staffing_complete=false`
- `annotators_qualified=false`
- `calibration_round_complete=false`
- `calibration_agreement_passed=false`
- `pilot_guideline_frozen=false`

当前结论：

- `annotation_pending`
- `annotation_campaign_prepared`
- `human_execution_pending`
- `not_formal_ready`
- `stage1_v2_training_blocked`
- `stage2_entry_blocked`

## 8.1 Unified annotation campaign

当前新增 campaign 资产：

- `datasets/mica/stage1_v2/campaign/annotation_queue_overlap_report.json`
- `datasets/mica/stage1_v2/campaign/unified_pilot_annotation_index.jsonl`
- `datasets/mica/stage1_v2/campaign/deduplicated_human_workload_report.json`
- `datasets/mica/stage1_v2/campaign/annotator_registry.json`
- `datasets/mica/stage1_v2/campaign/campaign_role_assignment.json`
- `datasets/mica/stage1_v2/campaign/role_conflict_report.json`
- `datasets/mica/stage1_v2/campaign/annotation_campaign_manifest.json`
- `datasets/mica/stage1_v2/campaign/annotation_batch_schedule.json`
- `datasets/mica/stage1_v2/campaign/annotation_campaign_progress.json`
- `datasets/mica/stage1_v2/campaign/annotation_event_log.jsonl`
- `datasets/mica/stage1_v2/campaign/annotation_event_log_spec.json`

去重工作量报告：

- raw total tasks：`5099`
- unique commit count：`4868`
- unique real commit annotation count：`232`
- unique atomic source review count：`4679`
- full alignment anchor count：`100`
- full alignment 可派生 count：`100`
- full alignment 可派生 background：`55`
- remaining count-only tasks：`67`
- remaining background-only tasks：`32`
- deduplicated real annotation count：`199`

工作量分组：

- `atomic_source_review_only`：`4636`
- `background_only`：`32`
- `count_only`：`67`
- `count_plus_background`：`33`
- `full_alignment_anchor`：`100`

这些派生只在人工填写了对应字段、双标与裁决完整后才允许。weak label 不能派生 gold。

## 8.2 Qualification 与 calibration round

新增 qualification execution packages：

- `datasets/mica/stage1_v2/qualification/qualification_package_annotator_a.jsonl`
- `datasets/mica/stage1_v2/qualification/qualification_package_annotator_b.jsonl`
- `datasets/mica/stage1_v2/qualification/qualification_scoring_manifest.json`
- `datasets/mica/stage1_v2/qualification/qualification_result_template.json`

answer key 仍隔离在：

- `datasets/mica/stage1_v2/qualification/qualification_answer_key_private.jsonl`

新增 calibration round 1 packages：

- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_a.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_b.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_blinding_map.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_adjudication_template.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_result_template.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_1_sampling_report.json`

calibration round 1 规模：`30`。

当前状态：

- `annotators_qualified=false`
- `calibration_round_complete=false`
- `calibration_agreement_passed=false`
- `pilot_guideline_frozen=false`

## 8.3 Annotation CLI 与 immutable audit log

新增本地 CLI：

- `code/mica/stage1_v2/annotation_cli.py`

支持：

- `show-sample`
- `init-draft`
- `validate-draft`
- `submit-draft`

新增 append-only audit log：

- code：
  - `code/mica/stage1_v2/audit_log.py`
- runtime log：
  - `datasets/mica/stage1_v2/campaign/annotation_event_log.jsonl`
- spec：
  - `datasets/mica/stage1_v2/campaign/annotation_event_log_spec.json`

当前 event log 已包含 R2 diagnostic review receipt 事件；这些事件不是 protocol-compliant A/B 人工标注，也不能作为 formal gold。completed annotation 不允许原地覆盖；后续修改必须创建 revision 并记录旧 / 新 record hash。

## 9. Registry 状态语义

当前 registry：

- `configs/mica/stage1_v2_asset_registry.json`

当前使用中的状态：

- `candidate_materialized`
- `annotation_pending`
- `pending_generation`

状态解释：

- `candidate_materialized`
  - 候选池或 synthetic/control manifest 已真实落盘，可审计，可计算 hash。
- `annotation_pending`
  - 标注输入包或 queue 已真实落盘，但人工双标 / 裁决尚未开始或尚未完成。
- `pending_generation`
  - 未来资产定义已存在，但当前没有物化文件，不能视为 ready。

## 10. 下一步允许动作

在不训练 Stage1-v2 模型、不运行 final test、不启动 Stage 2 的前提下，当前允许继续做的动作只有：

- 开始 RealCount pilot 双标
- 开始 Real-Adjudicated pilot 双标
- 完成 annotator staffing
- 完成 qualification test
- 执行 calibration round 1
- 人工审核 critical atomic sources
- 导入 annotator A/B 结果
- 计算 pre-adjudication agreement
- 导出 adjudication queue
- 导入 adjudicated annotations
- 导出 10% blind review sample
- 生成 post-adjudication quality report

当前仍不允许：

- Stage1-v2 训练
- baseline 真实训练
- anti-shortcut 真实 probe 训练
- Stage1-v2 final benchmark freeze
- Stage 2

## 11. 2026-07-26 R2 LLM Diagnostic Calibration 状态

Calibration Round 2 当前只能作为 `llm_annotation_track` 诊断资产，不能作为 human annotation evidence。

已落盘核验结果：

- integrity report：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_annotation_integrity_report.json`
- annotation errors：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_annotation_errors.jsonl`
- pre-adjudication agreement：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_pre_adjudication_agreement.json`
- gate report：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_gate_report.json`
- adjudication report：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_adjudication_report.json`
- guideline decision：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_guideline_decision.json`

当前结论：

- `llm_calibration_round_2=incomplete`
- `guideline_status=blocked_by_incomplete_annotation`
- `formal_human_evidence=false`
- pre-adjudication agreement 未计算；原因是 A/B labels 只存在于 combined file，缺少独立 actor/context/audit provenance。
- R2 adjudication 未启动；remaining adjudication queue 为 `30` 条。

2026-07-27 追加的 Codex diagnostic markings 已由用户复审确认，但仍不是 protocol-compliant human double annotation：

- Codex marking sidecar：`datasets/mica/stage1_v2/real_alignment/codex_calibration_round_2_llm_markings.jsonl`
- Codex marking summary：`datasets/mica/stage1_v2/real_alignment/codex_calibration_round_2_llm_marking_summary.json`
- human review receipt：`datasets/mica/stage1_v2/real_alignment/human_review_receipt_codex_calibration_round_2.json`
- human-reviewed diagnostic sidecar：`datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_markings.jsonl`
- human-reviewed summary：`datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_summary.json`
- record count：`30`
- source rows：`actor_type=llm`, `human_verified=false`, `formal_human_evidence=false`
- reviewed rows：`human_verified=true`, `review_evidence_type=chat_confirmation`, `formal_human_evidence=false`
- formal blocker：`not_independent_double_annotation_or_adjudication`
- annotation audit log：`60` chained `reviewed` events, hash-chain valid

这些 reviewed diagnostic markings 可用于 guideline/debug review，不得用于计算 formal pre-adjudication agreement、不得作为 adjudicated gold、不得解锁训练。

基于 reviewed diagnostic markings 生成的下一步 triage 资产：

- diagnostic analysis：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_reviewed_diagnostic_analysis.json`
- follow-up queue：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_review_followup_queue.jsonl`
- guideline v3 draft：`docs/annotation/STAGE1_V2_GUIDELINE_PILOT_V3_REVISION_DRAFT.md`
- follow-up queue count：`23`
- priority distribution：P0/P1/P2/P3 = `4 / 5 / 14 / 7`
- P0 samples：`calibration_round_2_0004`, `calibration_round_2_0008`, `calibration_round_2_0009`, `calibration_round_2_0016`
- guideline v3 status：`revision_draft_only`

这些 triage 资产只用于后续人工复核和 guideline debug；不能让 R2 进入 formal agreement、formal adjudication、training 或 Stage 2。

2026-07-27 后续 diagnostic review：

- P0 Codex-filled sidecar：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_p0_codex_review_filled.jsonl`
- P0 user review receipt：`datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p0_codex_review.json`
- P0 human-reviewed diagnostic sidecar：`datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p0_codex_review.jsonl`
- P0 reviewed decisions：`overflow_stress=3`, `usable_k_le_4=1`
- P1 Codex-filled sidecar：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_p1_codex_review_filled.jsonl`
- P1 user review receipt：`datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p1_codex_review.json`
- P1 human-reviewed diagnostic sidecar：`datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p1_codex_review.jsonl`
- P1 reviewed decisions：`5` rows, all diagnostic `usable_k_le_4`; diagnostic exact-k distribution `k=1:2`, `k=2:3`
- P2 Codex-filled sidecar：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_p2_codex_review_filled.jsonl`
- P2 user review receipt：`datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p2_codex_review.json`
- P2 human-reviewed diagnostic sidecar：`datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p2_codex_review.jsonl`
- P2 reviewed decisions：`14` rows, all diagnostic `usable_k_le_4`; diagnostic exact-k distribution `k=1:5`, `k=2:5`, `k=3:3`, `k=4:1`
- P2 changed original Codex exact-k for `calibration_round_2_0022` (`4→3`) and `calibration_round_2_0027` (`4→2`) after diff-level boundary review
- P3 Codex-filled sidecar：`datasets/mica/stage1_v2/real_alignment/calibration_round_2_p3_codex_review_filled.jsonl`
- P3 user review receipt：`datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p3_codex_review.json`
- P3 human-reviewed diagnostic sidecar：`datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p3_codex_review.jsonl`
- P3 reviewed decisions：`7` rows, all diagnostic `accepted_low_risk_diagnostic`; diagnostic exact-k distribution `k=1:6`, `k=3:1`
- Formal human evidence remains `false`; these records do not satisfy independent A/B or adjudication.

旧的 `calibration_round_2_agreement_report.json` 已降级为 `invalidated_by_annotation_integrity_audit`，不得用于放行 guideline。

## 12. 2026-07-26 Source Review 与 Synthetic Quarantine

Source-review sidecar 已完成 hardening：

- `code/mica/stage1_v2/source_review.py`
- `tests/mica/test_stage1_v2_hardening.py`
- `datasets/mica/stage1_v2/atomic_source_pool/source_review_status_summary.json`
- `datasets/mica/stage1_v2/atomic_source_pool/source_review_human_gate_report.json`
- `datasets/mica/stage1_v2/atomic_source_pool/human_source_review_priority_queue.jsonl`

当前 sidecar 统计：

- LLM source-review rows：`613`
- Claude rows：`603`
- Codex rows：`10`
- `llm_accept=552`
- `llm_reject=61`
- `llm_second_review=92`
- `human_verified=false` for all rows
- `required_atomic_sources_human_verified=false`
- `formal_synthetic_freeze_allowed=false`

受 LLM rejected source 影响的 synthetic candidate 已隔离：

- quarantined samples：`45`
- impacted rejected sources in current manifests：`25`
- new candidate counts：train/dev/control `128 / 100 / 119`
- leakage audit：all required overlaps zero; near-duplicate full comparison `39932` pairs, not skipped.

新 candidate files：

- `datasets/mica/stage1_v2/synthetic/quarantined_synthetic_samples.jsonl`
- `datasets/mica/stage1_v2/synthetic/rejected_source_impact_map.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_train.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_dev.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_control_test.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_leakage_report.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_summary.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_supersession_record.json`

这些文件状态是 `synthetic_llm_screened_candidate`，不是 formal frozen train/dev/control asset。
