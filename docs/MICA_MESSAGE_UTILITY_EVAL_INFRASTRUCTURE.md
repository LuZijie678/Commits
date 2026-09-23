# MICA Message Utility 评估基础设施

状态：实现接口说明，不代表真实 benchmark 已执行。

## 1. 当前已实现组件

- `code/mica/runners/export_consumer_plans.py`
  - 将 prediction / legacy plan-builder 输出导出为 canonical `StructuredIntentPlan` JSONL。
- `code/mica/runners/export_stage1_predictions.py`
  - 将单样本 backend snapshot 导出为 canonical Stage 1 prediction JSONL，供后续 plan export / spot-check 使用。
  - 导出 summary 当前会输出 `source_kind_distribution`、`release_decision_distribution`、`error_type_counts` 与 `exported_samples_preview`。
  - 当前公开 `build_backend_snapshot_rows_from_samples(...)`；正式协议要求上游一条 snapshot 对应一个 sample，exporter 不负责拆分 multi-sample batch。
- `code/mica/runners/run_stage1_official_validation.py`
  - 当前正式 Stage 1 入口已支持显式 consumer-plan export，可把 prediction artifact 连到 canonical consumer plan JSONL。
  - CLI 开关：
    - `--export-consumer-plans`
    - `--consumer-plan-review-ready`
  - run manifest `metadata.consumer_plan_export` 稳定字段：
    - `requested`
    - `review_ready`
    - `output_jsonl`
    - `error_jsonl`
    - `summary_json`
    - `summary`
  - `output_jsonl` / `error_jsonl` / `summary_json` 当前记录为 basename，消费方应相对 `output_root` 解析。
  - 当前输出文件名：
    - `stage1_official_validation_consumer_plans.jsonl`
    - `stage1_official_validation_consumer_plan_export_errors.jsonl`
    - `stage1_official_validation_consumer_plan_export_summary.json`
- `code/mica/runners/run_stage1_official_validation_dryrun.py`
  - dry-run companion 已支持相同的 consumer-plan export 接入，用于只检查导出链，不执行真实 official validation。
  - CLI 开关：
    - `--export-consumer-plans`
    - `--consumer-plan-review-ready`
  - run manifest `metadata.consumer_plan_export` 稳定字段：
    - `requested`
    - `review_ready`
    - `output_jsonl`
    - `error_jsonl`
    - `summary_json`
    - `summary`
  - `output_jsonl` / `error_jsonl` / `summary_json` 当前记录为 basename，消费方应相对 `output_root` 解析。
  - 当前输出文件名：
    - `stage1_official_validation_dryrun_consumer_plans.jsonl`
    - `stage1_official_validation_dryrun_consumer_plan_export_errors.jsonl`
    - `stage1_official_validation_dryrun_consumer_plan_export_summary.json`
- `code/mica/adapters/oracle_plan_adapter.py`
  - 将未来人工 adjudicated alignment record 适配为 oracle plan。
- `code/mica/runners/run_consumer_evaluation.py`
  - 对 canonical plan JSONL 执行 deterministic consumer pipeline，并写出 per-sample JSONL 与 aggregate JSON。
- `code/mica/runners/run_message_baseline_generation.py`
  - 对 canonical plan JSONL 生成 message-level external reference baseline rows。
  - 当前支持 `llm_prompting`、`pretrained_generation` 与 `direct_generation`。
  - 当前支持 `--validate-only`、`--lenient`、`error_jsonl` 和 overwrite protection。
- `code/mica/baselines/llm_prompting_baseline.py`
  - message-level external reference baseline infrastructure。
  - 继续保留 prompt manifest contract，同时新增 canonical structured-plan -> baseline row 适配与 mock/real backend 路径。
- `code/mica/baselines/pretrained_generation_baseline.py`
  - 预训练生成型 external reference baseline 适配层。
- `code/mica/renderers/trainable_reranker.py`
  - guarded executable trainable reranker path。
  - 仅表示 Stage 4 候选重排基础设施已可在 fixture 上执行，不代表真实实验结果。
  - 当前公开 `load_candidate_reranker_checkpoint(...)` 与 `score_candidates_with_checkpoint(...)`，用于 checkpoint replay / preview。
- `code/mica/eval/consumer_metrics.py`
  - 计算 micro aggregate 指标。
- `code/mica/eval/consumer_stratification.py`
  - 按 `predicted_k`、`plan_source`、`background_assignment_type` 等字段做分层聚合。
- `code/mica/eval/compare_consumer_runs.py`
  - 对 predicted vs oracle 的 consumer 结果做 paired comparison。
- `code/mica/eval/export_human_pilot.py`
  - 生成 blind annotator package 与 private mapping。

## 2. Canonical Plan Export

导出结果是 consumer schema JSONL，每条至少包含：

- `schema_version`
- `sample_id`
- `commit_id`
- `decision`
- `predicted_k`
- `overall_confidence`
- `intents`
- `background_units`
- `background_unit_records`
- `uncertain_units`
- `risk_score`
- `background_contract`
- `source_metadata`

说明：

- export 只做格式适配，不运行 attribution inference；
- 不读取 raw commit message、PR title、issue text、gold intent ID；
- `review_ready` 模式要求显式 `release_decision`、assignment scores 和 evidence payload；
- `review_ready` summary 额外输出 blocker 统计和 ready/blocked sample preview，便于人工先筛掉不可审阅样本；
- 若 prediction row 未内嵌 `edit_units/unit_records`，可按 `sample_id` 从外部 `edit_units` 索引 join；
- 单条失败会生成 structured error row；
- `validate-only` 只校验输入，不写正式结果。
- 当前 backend snapshot export 仍只支持单样本 row；多样本 snapshot 会显式拒绝，而不是做猜测性拆分。
- 本基础设施文档中的 `run_message_baseline_generation.py`、`FrozenLLMRenderer` 与 `trainable_reranker.py` 都属于“已实现代码基础设施，但没有真实 benchmark 结论”的范畴。
- 仓库内当前提供默认真配置骨架：
  - `configs/mica/frozen_llm_renderer_openai_compatible.example.json`
  - `configs/mica/message_baseline_generation_spec.example.json`
  二者都使用真实 provider 字段骨架，但默认 `enabled=false`。

## 3. Oracle Plan Adapter

oracle adapter 只实现 schema 与约束：

- metadata 固定带有 `plan_source=oracle`
- metadata 固定带有 `annotation_source=manual_adjudicated`
- `gold_k` 必须等于 foreground intent 数量
- foreground / background primary assignment 不得重叠
- shared-support / uncertain units 默认不进入 MVP primary assignment
- `scope_status=out_of_scope` 输出 `decision=overflow`

human intent statement：

- 只保存在 annotation metadata / intent metadata
- 不伪装成模型 `action/object`
- 不读取原始 commit message 作为 statement

## 4. Evaluation Runner

当前公共函数：

```python
run_consumer_evaluation(
    predicted_plan_jsonl,
    per_sample_output_jsonl,
    aggregate_output_json,
    mode="deterministic",
    plan_source="predicted",
    overwrite=False,
    validate_only=False,
    strict=True,
)
```

CLI 语义：

- `--plans`
- `--per-sample-output`
- `--aggregate-output`
- `--mode deterministic`
- `--plan-source predicted|oracle`
- `--overwrite`
- `--validate-only`
- `--lenient`

说明：

- runner 默认不读取 raw commit message；
- malformed JSON line 在 lenient 模式下会转成 structured error row；
- 输出写入采用 atomic write；
- 本轮没有对真实资产执行该 runner。

## 4.1 Optional Frozen LLM Path

- `code/mica/consumers/message_generator.py` 中的 `FrozenLLMRenderer` 已实现为 optional externally configured FrozenLLMRenderer path。
- 它只消费 frozen slot summaries，不读取 raw diff、commit message、PR title、issue text、gold label 或 synthetic metadata。
- 其 example config 位于 `configs/mica/frozen_llm_renderer_openai_compatible.example.json`，默认 `enabled=false`。
- 当前仓库没有默认启用的外部 API 配置，也没有提交任何 Frozen LLM benchmark 产物。

## 5. Stratified Metrics

当前支持分层键：

- `predicted_k`
- `gold_k`
- `decision`
- `plan_source`
- `background_contract.evidence_complete`
- `fallback_level`
- `file_role_composition`
- `source_type`
- `hard_b_flag`
- `multi_intent`
- `background_assignment_type`

每组输出：

- `sample_count`
- `included_count`
- `excluded_count`
- `success_count`
- `rejected_count`
- `denominators`
- `success_rate`
- `reject_rate`
- `fallback_rate`
- `mean_intent_coverage`
- `missing_intent_rate`
- `unsupported_claim_rate`
- `entity_grounding_precision`
- `background_mention_rate`
- `format_compliance`

空分母处理：

- 返回 `null`
- 并显式保留 `denominator=0`

## 6. Paired Comparison

`compare_consumer_runs(predicted_records, oracle_records)` 当前输出：

- `paired_sample_count`
- `predicted_only_count`
- `oracle_only_count`
- `excluded_pairs`
- `aggregate_predicted_metrics`
- `aggregate_oracle_metrics`
- `paired_deltas`
- `per_sample_deltas`

约束：

- 按 `commit_id` 对齐
- duplicate commit id 默认报错
- 不修改输入记录
- 不使用 oracle 结果选择 renderer 配置

## 7. Human Pilot Blind Export

annotator package 包含：

- `sample_id`
- `evidence_display`
- `candidate_id`
- `subject`
- `body`
- `faithfulness_rating`
- `completeness_rating`
- `conciseness_rating`
- `usefulness_rating`
- `unsupported_claim`
- `missing_intent`
- `notes`

private mapping 包含：

- `sample_id`
- `candidate_id`
- `original_system_name`
- `plan_source`
- `original_record_id`

blind 规则：

- annotator package 不暴露 `oracle/predicted`
- 不暴露 model 名称
- 不暴露 slot id
- 不暴露内部 confidence
- 固定 seed 下完全可复现

## 8. Background Audit 字段

当前 `background_unit_records` 额外包含：

- `background_reason_source`
- `background_assignment_type`
- `background_record_resolution_status`

语义：

- `null_slot_assignment` 只表示模型分配背景，不等于规则验证背景
- `rule_verified_background` 与 `model_assigned_background` 在 schema 层显式区分
- `id_only` / `partial` 表示背景证据记录不完整，但 verifier 仍只依据 plan 中显式 assignment 工作

## 9. 当前未执行的事项

本轮未执行：

- 真实 prediction export
- 正式 consumer evaluation
- oracle/predicted 实验比较
- human evaluation pilot
- Frozen LLM renderer 的真实 benchmark 运行

因此本文档不包含任何真实 benchmark 结论或性能数字。

## 10. Report-side Status / Optional Diagnostics

- `code/mica/eval/baseline_metrics.py` 当前把“代码已实现但本阶段未运行”的状态统一表述为 `not_run_in_this_stage`，不再把已实现 baseline 误记为 `implemented=false`。
- `code/mica/eval/training_diagnostics.py::grad_conflict_placeholder_or_optional` 当前输出 machine-readable optional diagnostic contract。
  - 无数据时会返回 `missing_grad_conflict`
  - 这表示诊断不可用，不表示训练路径不存在
