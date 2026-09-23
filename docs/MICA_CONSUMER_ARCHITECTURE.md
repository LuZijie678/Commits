# MICA 消费者层架构

状态：当前工作区实现说明

本文档描述当前分支已经落地的消费者层代码路径。它不是 attribution 训练方案文档，也不代表真实 message utility benchmark 已执行完成。

## 1. 目标与隔离原则

当前消费者层实现遵守以下硬约束：

- attribution 在进入消费者层前已经冻结；
- 消费者只读取 frozen structured intent plan 与其 assigned evidence；
- 消费者不重新计算 intent count；
- 消费者不重新分配 edit units / hunks；
- 消费者不改变 foreground / background 判定；
- 消费者不读取 commit message、PR title、issue text、gold intent ID、synthetic construction metadata；
- verifier / renderer 结果不反向影响 attribution checkpoint、threshold、prompt、template 或 verifier 选择。

## 2. 当前代码组件

- `code/mica/consumers/plan_schema.py`
  - 定义消费者输入 schema 与 legacy plan adapter。
  - adapter 会过滤掉 commit-message surface text、gold label 与 synthetic metadata；旧 `subject/body` 不会作为运行时生成输入继续传递。
- `code/mica/adapters/oracle_plan_adapter.py`
  - 将未来人工 adjudicated alignment record 适配为 `StructuredIntentPlan` 兼容 oracle plan。
  - 该 adapter 只实现 schema 和约束，不创建真实 oracle 资产。
- `code/mica/consumers/evidence_summarizer.py`
  - 对每个 frozen foreground slot 做 deterministic evidence summarization。
- `code/mica/consumers/message_generator.py`
  - 生成 deterministic subject / body 候选，并内建保守 fallback。
  - 同时包含 `FrozenLLMRenderer`：这是 optional externally configured FrozenLLMRenderer path，只读取 slot summary，不读取 raw diff / commit message / PR / issue / synthetic metadata。
  - 仓库内当前提供默认真配置骨架 `configs/mica/frozen_llm_renderer_openai_compatible.example.json`，其中 `enabled=false`；它是结构完整但默认禁用的 example config，不会自动启用真实 API。
- `code/mica/consumers/verifier.py`
  - 实现 slot coverage、unsupported claim、entity grounding、background exclusion、format verifier。
- `code/mica/consumers/candidate_selector.py`
  - 执行固定硬规则拒绝与软排序。
- `code/mica/consumers/pipeline.py`
  - 对外暴露统一 `ConsumerPipeline.generate(...)` 接口。
- `code/mica/renderers/deterministic.py`
  - legacy `DeterministicRenderer` 兼容层；内部已接入 `ConsumerPipeline`。
- `code/mica/runners/run_consumer_evaluation.py`
  - deterministic consumer evaluation runner；对 structured-plan JSONL 执行渲染、校验和聚合统计。
- `code/mica/runners/run_message_baseline_generation.py`
  - 将 canonical structured plan JSONL 渲染为 message-level external reference baseline rows。
  - 当前支持 `llm_prompting`、`pretrained_generation`、`direct_generation` 三类 message utility baseline 输出格式。
  - 当前支持 `--validate-only`、`--lenient`、`error_jsonl` 与 overwrite protection。
  - 仓库内提供 `configs/mica/message_baseline_generation_spec.example.json` 作为默认真配置骨架；其中 `backend.enabled=false`，不会默认启用真实 API。
- `code/mica/renderers/trainable_reranker.py`
  - guarded executable trainable reranker path。
  - 仅用于 Stage 4 `--train --train-ablation` 的候选重排实验基础设施；当前没有真实 benchmark 结论。
  - 当前公开 `load_candidate_reranker_checkpoint(...)` 与 `score_candidates_with_checkpoint(...)`，用于 checkpoint load / replay / preview，不改变默认 deterministic mainline。
- `code/mica/runners/export_stage1_predictions.py`
  - 将单样本 `TrainBatch + TrainOutputs` backend snapshot 导出为 canonical Stage 1 prediction JSONL。
  - 当前要求显式 `release_decision`，缺失时不会静默默认 `decompose`。
  - 当前 summary 会输出 `source_kind_distribution`、`release_decision_distribution`、`error_type_counts` 与 `exported_samples_preview`，便于初步 spot-check。
  - 当前公开 `build_backend_snapshot_rows_from_samples(...)`，上游 producer 必须按 sample 切分后再写 snapshot JSONL；exporter 本身不负责拆分 multi-sample batch。
- `code/mica/runners/export_consumer_plans.py`
  - 将 prediction / legacy plan-builder 输出适配为 canonical consumer plan JSONL。
  - 当前支持 `review_ready` 模式与外部 `edit_units` join，用于区分“链路可跑”与“可审阅 structured plan”。
  - `review_ready` summary 会额外输出 `review_ready_blocker_counts`、`blocked_sample_count`、`ready_samples_preview` 与 `blocked_samples_preview`。
- `code/mica/train/debug_stage1_attribution.py`
  - 当前已支持可选 `--backend-snapshot-jsonl` 导出，用于把 debug/sanity 执行中的单样本 backend output 写成 canonical backend snapshot，再接到后续 export 链。
  - 该导出路径当前仍是单样本 snapshot 约束；多样本 snapshot 会显式拒绝，而不是猜测性拆分。
- `code/mica/runners/run_stage1_official_validation.py`
  - 当前正式 Stage 1 official validation 入口已支持显式 `consumer plan export` 接入。
  - 当提供 `prediction_jsonl` 且显式打开 export flag 时，会在 `output_root` 下写出 canonical consumer plans、error rows 和 export summary。
  - 相关 CLI 开关：
    - `--export-consumer-plans`
    - `--consumer-plan-review-ready`
  - 当前 run manifest 中 `metadata.consumer_plan_export` 的稳定字段：
    - `requested`
    - `review_ready`
    - `output_jsonl`
    - `error_jsonl`
    - `summary_json`
    - `summary`
  - `output_jsonl` / `error_jsonl` / `summary_json` 当前固定记录 basename，解析时应相对 `output_root` 拼接。
  - 当前输出文件名：
    - `stage1_official_validation_consumer_plans.jsonl`
    - `stage1_official_validation_consumer_plan_export_errors.jsonl`
    - `stage1_official_validation_consumer_plan_export_summary.json`
- `code/mica/runners/run_stage1_official_validation_dryrun.py`
  - dry-run companion 已支持同样的显式 `consumer plan export` 接入，用于在不执行真实 official validation 的前提下检查 structured plan 导出链。
  - 相关 CLI 开关：
    - `--export-consumer-plans`
    - `--consumer-plan-review-ready`
  - 当前 run manifest 中 `metadata.consumer_plan_export` 的稳定字段：
    - `requested`
    - `review_ready`
    - `output_jsonl`
    - `error_jsonl`
    - `summary_json`
    - `summary`
  - `output_jsonl` / `error_jsonl` / `summary_json` 当前固定记录 basename，解析时应相对 `output_root` 拼接。
  - 当前输出文件名：
    - `stage1_official_validation_dryrun_consumer_plans.jsonl`
    - `stage1_official_validation_dryrun_consumer_plan_export_errors.jsonl`
    - `stage1_official_validation_dryrun_consumer_plan_export_summary.json`
- `code/mica/eval/message_coverage.py`
- `code/mica/eval/unsupported_claims.py`
- `code/mica/eval/entity_grounding.py`
  - 为 verifier 和 downstream eval proxy 提供共用 helper。
- `code/mica/eval/consumer_metrics.py`
- `code/mica/eval/consumer_stratification.py`
- `code/mica/eval/compare_consumer_runs.py`
- `code/mica/eval/export_human_pilot.py`
  - 提供 deterministic message-utility 基础设施，但当前只在 synthetic fixture / 单元测试层验证。

## 3. 公共输入 Schema

当前消费者层使用 `code.mica.consumers.plan_schema.StructuredIntentPlan`，核心字段如下：

```json
{
  "sample_id": "commit_001",
  "commit_id": "abc123",
  "decision": "decompose",
  "predicted_k": 2,
  "overall_confidence": 0.91,
  "intents": [
    {
      "slot_id": "slot_1",
      "slot_confidence": 0.86,
      "assigned_unit_ids": ["u1", "u2"],
      "assigned_hunk_ids": ["h_u1", "h_u2"],
      "files": ["src/auth/token.py", "tests/test_token.py"],
      "changed_symbols": ["validate_token"],
      "changed_identifiers": ["token", "validate_token"],
      "file_roles": ["source", "test"],
      "evidence": [
        {
          "unit_id": "u1",
          "hunk_id": "h_u1",
          "file_path": "src/auth/token.py",
          "file_role": "source",
          "language": "python",
          "enclosing_symbol": "validate_token",
          "patch_text": "@@",
          "added_lines": ["+ validate_token(token)"],
          "deleted_lines": ["- token"],
          "changed_identifiers": ["token", "validate_token"]
        }
      ],
      "action": "update",
      "object": "token validation",
      "scope": "auth"
    }
  ],
  "background_units": ["u_lock"],
  "background_unit_records": [
    {
      "unit_id": "u_lock",
      "hunk_id": "h_u_lock",
      "file_path": "package-lock.json",
      "file_role": "lockfile",
      "changed_identifiers": ["lockfile"],
      "patch_operation": "update",
      "background_reason": "lockfile",
      "background_confidence": 0.99,
      "background_reason_source": "file_role_rule",
      "background_assignment_type": "rule_verified_background",
      "background_record_resolution_status": "complete"
    }
  ],
  "uncertain_units": [],
  "risk_score": 0.12,
  "metadata": {
    "prediction_source": "predicted_plan"
  }
}
```

Schema 约束：

- `decision=decompose` 时，`predicted_k` 必须等于 `intents` 数量；
- `decision=abstain|overflow` 时，`predicted_k` 必须为 `0`，且不能暴露 trusted foreground intents；
- `slot_id` 必须唯一；
- 同一 primary-assignment plan 中，`assigned_unit_ids` 与 `assigned_hunk_ids` 不得跨 foreground intent 重复；
- `background_unit_records[*].unit_id` 必须属于 `background_units`；
- foreground primary assignment 与 `background_units` 不得重叠；
- `background_reason_source` / `background_assignment_type` / `background_record_resolution_status` 必须属于有限枚举；
- `null_slot_assignment` 只表示模型将该 unit 路由到 background，不自动等价于 `rule_verified_background`；
- 若 `background_units` 缺少对应 record，schema 兼容保留该输入，但 verifier 会输出 `evidence_incomplete=true` 与 `missing_record_ids`；
- legacy record 若缺少新增 background audit 字段，会兼容迁移为 `legacy_adapter + unresolved_background + partial|id_only`，并在 `background_contract.diagnostic_codes` 中显式提示；
- 置信度字段必须位于 `[0, 1]`；
- legacy `code.mica.schemas.StructuredIntentPlan` 可通过 adapter 转换为该 schema。

## 4. 数据流

当前 deterministic consumer pipeline 的固定数据流如下：

```text
Frozen Structured Intent Plan
  -> DeterministicEvidenceSummarizer
  -> DeterministicMessageGenerator.generate_candidates
  -> SlotCoverage / UnsupportedClaim / EntityGrounding / BackgroundExclusion / Format verifiers
  -> CandidateSelector
  -> Final Commit Message or Rejected
```

对 `decision=abstain|overflow` 的样本：

- pipeline 立即返回 `rejected`；
- 不生成普通语义 commit message；
- 返回 machine-readable diagnostics。

## 5. Verifier 规则

### SlotCoverageVerifier

- 检查 subject/body 是否覆盖全部 foreground slot；
- 以生成后的实际文本为准重新计算覆盖，不信任 renderer 自报的 `covered_slot_ids`；
- 会同时报告 declared-vs-verified mismatch；
- 输出 `intent_coverage_rate`、`missing_slot_ids`。

### UnsupportedClaimVerifier

- 使用固定 risky-claim lexicon；
- 默认拦截：
  - `performance`
  - `security`
  - `crash`
  - `reliability`
  - `breaking change`
  - `race condition`
- 只有 summary 明确给出 supported claim 时才放行。

### EntityGroundingVerifier

- 从 message 中抽取实体样 token；
- 检查其是否能追溯到 slot summary / evidence entity；
- 输出 `unsupported_entities` 与 `entity_grounding_precision`。

### BackgroundExclusionVerifier

- 检查 message 是否把 background-only 变化写成 foreground 内容；
- 依赖 plan 中已经冻结的 `background_units` assignment；
- `background_unit_records` 只有在其 `unit_id` 属于 `background_units` 时才参与判定；
- 若 background record 缺失，会显式报告 `evidence_incomplete` 与 `missing_record_ids`；
- verifier 会保留 `background_assignment_type` / `background_reason_source` / `background_record_resolution_status` 的审计信息，但不会据此反向修改 attribution；
- 不通过文件扩展名单独硬编码重写 foreground 判定。

### FormatVerifier

- 检查 subject 非空；
- 默认 subject 长度上限 `72`；
- 检查无尾部句号；
- 检查 bullet 去重；
- 拒绝空泛 subject 且无 body 的输出。

## 6. Fallback 与拒绝

当前候选与 fallback 顺序：

1. primary deterministic candidate
2. conservative bullet candidate
3. minimal evidence-grounded candidate
4. reject

固定拒绝规则：

- missing foreground slot
- unsupported claim
- unsupported entity 超过阈值
- background-only mention
- format invalid

当前实现会记录：

- `fallback_used`
- `fallback_level`
- `rejection_reason`
- verifier diagnostics

## 7. 公共调用接口

直接调用 pipeline：

```python
from code.mica.consumers.pipeline import ConsumerPipeline

result = ConsumerPipeline().generate(
    structured_plan=plan,
    mode="deterministic",
    verify=True,
)
```

兼容旧 renderer：

```python
from code.mica.renderers.deterministic import DeterministicRenderer

rendered = DeterministicRenderer().render(legacy_structured_plan)
```

其中 `DeterministicRenderer` 已改为 consumer pipeline wrapper：

- legacy decompose plan 会生成 deterministic message；
- legacy `release_decision=abstain|overflow` 会返回 `status=rejected`；
- legacy degraded empty plan 仍保留保守 fallback。
- legacy `subject/body` 不会被当作当前 runtime message 直接复用。

离线 evaluation runner：

```python
from code.mica.runners.run_consumer_evaluation import run_consumer_evaluation

summary = run_consumer_evaluation(
    predicted_plan_jsonl="tmp/predicted_plans.jsonl",
    per_sample_output_jsonl="tmp/consumer_eval_rows.jsonl",
    aggregate_output_json="tmp/consumer_eval_summary.json",
    plan_source="predicted",
    validate_only=False,
)
```

该 runner：

- 只消费 structured-plan JSONL；
- 默认不读取 raw commit message；
- 支持 `--validate-only`、`--plan-source predicted|oracle`、`--overwrite`、`--lenient`；
- malformed JSON line 在 lenient 模式下会转成 structured error row，而不是静默跳过；
- 输出 per-sample diagnostics 与 aggregate metrics；
- 不会触发网络请求或外部 LLM renderer。

canonical plan export：

```python
from code.mica.runners.export_consumer_plans import export_consumer_plans

summary = export_consumer_plans(
    prediction_jsonl="tmp/predictions.jsonl",
    output_jsonl="tmp/consumer_plans.jsonl",
    error_jsonl="tmp/consumer_plan_errors.jsonl",
    validate_only=False,
)
```

该导出器：

- 只做 prediction -> canonical plan 适配，不运行 attribution inference；
- 不读取 raw commit message、PR title、issue text 或 gold intent ID；
- 单条样本的 schema / adapter 失败会写入 structured error row；
- 当前只用 synthetic fixture 测试，未导出真实 benchmark 资产。

oracle adapter：

```python
from code.mica.adapters.oracle_plan_adapter import adapt_oracle_plan_record

oracle_plan = adapt_oracle_plan_record(adjudicated_row)
```

约束：

- 输出 metadata 固定带有 `plan_source=oracle` 与 `annotation_source=manual_adjudicated`；
- human intent statement 只保存在 annotation metadata / intent metadata，不伪装成模型 `action/object`；
- shared-support / uncertain units 默认不进入 MVP primary assignment；
- `scope_status=out_of_scope` 会输出 `decision=overflow`，不会伪装为普通 decompose plan。

message-utility 基础设施：

- `consumer_metrics.py` 提供 micro aggregate；
- `consumer_stratification.py` 提供按 `predicted_k`、`plan_source`、`background_assignment_type` 等字段分层统计；
- `compare_consumer_runs.py` 提供 predicted vs oracle 的 paired delta 结构；
- `export_human_pilot.py` 只负责 blind package / mapping 格式，不创建真实人评包。

## 8. 已实现边界与未实现边界

已实现：

- deterministic structured-plan consumer schema
- background assignment -> verifier evidence contract
- canonical consumer plan export runner
- oracle-plan schema adapter
- legacy plan adapter
- deterministic evidence summarization
- deterministic candidate generation
- deterministic verifier stack
- fixed-rule candidate selection
- legacy renderer integration
- deterministic consumer evaluation runner
- deterministic consumer eval runner 的 validate-only / lenient / stratified aggregation 基础设施
- predicted vs oracle paired comparison helper
- human-pilot blind export helper
- message-level external reference baseline infrastructure
- optional externally configured FrozenLLMRenderer path
- guarded executable trainable reranker path
- report-side `not_run_in_this_stage` baseline status helpers
- machine-readable `missing_grad_conflict` optional diagnostic contract
- no-network execution

未实现或仍为 future work：

- 仓库内默认启用的外部 LLM renderer 配置与正式 benchmark 产物
- trainable renderer 主结果路径与正式 benchmark 产物
- verifier-guided attribution tuning
- 真实 human message utility benchmark
- 真实 predicted-plan benchmark export
- 真实 oracle-plan 资产构建
- renderer-side checkpoint selection capability

当前仓库里的 `FrozenLLMRenderer` 已有可执行代码路径和测试覆盖，但它仍然不是默认主线，也不代表仓库已经完成外部 LLM renderer 实验。当前允许的结论仅是：该接口已实现为可选外部配置路径，并受消费者层隔离约束保护。
