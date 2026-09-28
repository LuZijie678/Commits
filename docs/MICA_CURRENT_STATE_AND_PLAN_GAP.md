# MICA 当前实现状态与方案差距

> 历史状态审计：主体记录截至 2026-07-23 的旧分支工作区，后续附有当时的更新。“当前分支”和“当前结果”均指记录时的环境，不是新仓库 `main`。旧 Git SHA 保留为实验来源标识；新仓库没有继承旧 Git 历史。现在请先看 [当前项目状态入口](CURRENT_STATUS.md)。

## 1. 审计方法

- 审计时的旧分支：`experiment/llm-generation-pilot-clean`
- 当前实现审计与 official Stage 1 执行代码 SHA：`f85b5260057a213a04bb4ea0a3c8cb720caa5dff`
  - Stage 1 clean training checkpoint provenance SHA：`22bcd358766e1a678ee721c994830bdcf544213c`
  - 当前工作树仅保留被过滤的无关外部脏文件：
    - `m_existing_diff_package/data/continuous_m_crawl.launchd.log`
- 扫描路径：
  - `code/mica`
  - `configs/mica`
  - `tests/mica`
  - `docs`
  - `reports`
- 原则：
  - current code is source of truth
  - 文档是辅助信息，不是实现事实
- 当前独立审计 companion：
  - `docs/MICA_STAGE1_INDEPENDENT_AUDIT.md`
  - 该审计是只读复核，不修改 official result，但明确给出 Stage 2 `NO_GO` 结论
- 当前 Stage1-v1 历史降级状态：
  - `configs/mica/official_results/stage1_v1_audit_status.json`
  - `formally_executed + internal_acceptance=passed + scientific_validity_audit=failed + external_paper_evidence=pilot_only`
- 当前 Stage1-v2 重建协议：
  - `docs/MICA_STAGE1_V2_REAL_ADJUDICATED_PROTOCOL.md`
  - `configs/mica/protocol_decisions/stage1_v2_protocol_reset.json`
  - 当前 machine-readable protocol：
    - `configs/mica/stage1_v2_protocol_spec.json`
    - 状态：`protocol_frozen`
  - 当前 Stage1-v2 asset registry：
    - `configs/mica/stage1_v2_asset_registry.json`
    - 顶层状态：`assets_pending`
    - 当前 per-asset 实际状态：
      - synthetic manifests / family map / leakage report：`candidate_materialized`
      - real count / real alignment pilot queues：`annotation_pending`
      - adjudicated train/dev/final assets：`pending_generation`
  - 当前 Stage1-v2 数据 / 标注执行说明：
    - `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`
- 本轮已运行：
  - real Stage 1 full-model training from clean git commit
  - real dev-only threshold selection
  - real Kmax exact-count audit
  - real Stage 0 readiness
  - real Stage 1 candidate validation
  - Stage 1 split exposure audit
  - Stage 1 threshold / Kmax approval packet generation
  - Stage 1 official preflight
  - canonical official Stage 1 validation
- 本轮未运行：
  - Stage 2 / Stage 3 training
  - Stage 2 / Stage 3 / Stage 4 formal eval

## 2. 执行摘要

- 已较稳固实现：
  - `code/mica/models/` 中的核心 latent-slot 模型部件
  - Stage 1 attribution metrics 与 prediction adapter
  - deterministic plan builder、consumer pipeline 与 deterministic renderer
  - asset registry 校验、split guard、runner policy registry
  - `required_for` 分层 readiness 视图与 Stage 1 frozen-manifest execute guard
- 部分实现：
  - Stage 0 protocol freeze 的代码化 dry-run 检查
  - Stage 1 对 fixture 或外部 prediction 的 official validation 路径
  - eval runner、paper table builder、baseline 覆盖
- 已完成主流程接入但尚未完成真实实验闭环：
  - Stage 2 / Stage 3 guarded train runner 已接入 `MicaModelBackendAdapter`
  - Stage 2 selective-risk dev-only calibration artifact 已由 runner 写出
  - patch + marked enclosing-symbol context protocol 已进入 `collate_mica_samples`
  - real alignment runner validation 已加入 action-object ontology 与 edit-unit consistency checks
- 已实现但仍未形成完整实验产物：
  - consistency helper、EMA teacher、null-slot helper
  - Stage 2 / Stage 3 的真实资产训练、checkpoint、metric artifact 仍未在当前分支实跑
- 已有函数级基础设施但尚无真实实验结论：
  - Stage 4 guarded executable trainable reranker path
  - optional externally configured FrozenLLMRenderer path
  - message-level external reference baseline infrastructure
- 仍为 placeholder / compatibility-only：
  - `code/mica/eval/baseline_metrics.py` 中的 report-side `not_run_in_this_stage` status helper
  - `code/mica/eval/training_diagnostics.py::grad_conflict_placeholder_or_optional` 的 optional diagnostic wrapper
- 当前缺失：
  - 当前分支上的真实 real-alignment / human-eval 资产
- 当前分支上的 final eval 产物
- 过时文档风险：
  - 多份 `docs/records/*` 仍描述历史实现轮次，容易被误读成当前完成状态
- 当前 Stage1-v2 新增基础设施：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/stage1_v2/protocol.py`
    - `code/mica/stage1_v2/family_split.py`
    - `code/mica/stage1_v2/leakage.py`
    - `code/mica/stage1_v2/real_count.py`
    - `code/mica/stage1_v2/real_adjudicated.py`
    - `code/mica/stage1_v2/statistics.py`
    - `code/mica/stage1_v2/readiness.py`
    - `code/mica/stage1_v2/synthetic_scale.py`
    - `code/mica/stage1_v2/campaign.py`
    - `code/mica/stage1_v2/annotation_cli.py`
    - `code/mica/stage1_v2/audit_log.py`
    - `code/mica/runners/run_stage1_v2_family_split.py`
    - `code/mica/runners/run_stage1_v2_real_count_queue.py`
    - `code/mica/runners/run_stage1_v2_real_adjudicated_queue.py`
    - `code/mica/runners/run_stage1_v2_readiness.py`
    - `code/mica/runners/run_stage1_v2_materialize_assets.py`
    - `code/mica/runners/run_stage1_v2_annotation_readiness.py`
    - `code/mica/runners/run_stage1_v2_prepare_campaign.py`
    - `datasets/mica/stage1_v2/synthetic/synthetic_train.jsonl`
    - `datasets/mica/stage1_v2/synthetic/synthetic_dev.jsonl`
    - `datasets/mica/stage1_v2/synthetic/synthetic_control_test.jsonl`
    - `datasets/mica/stage1_v2/synthetic/synthetic_scale_audit.json`
    - `datasets/mica/stage1_v2/synthetic/synthetic_formal_target_plan.json`
    - `datasets/mica/stage1_v2/atomic_source_pool/atomic_source_review_critical.jsonl`
    - `datasets/mica/stage1_v2/campaign/annotation_campaign_manifest.json`
    - `datasets/mica/stage1_v2/campaign/deduplicated_human_workload_report.json`
    - `datasets/mica/stage1_v2/real_count/real_count_candidate_pool.jsonl`
    - `datasets/mica/stage1_v2/real_alignment/real_adjudicated_candidate_pool.jsonl`
    - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_a.jsonl`
    - `datasets/mica/stage1_v2/real_alignment/calibration_round_1_annotator_b.jsonl`
    - `datasets/mica/stage1_v2/readiness/stage1_v2_annotation_readiness.json`
  - 说明：
    - Stage1-v2 protocol spec 已冻结为 machine-readable config。
    - family-safe synthetic split、RealCount queue、Real-Adjudicated queue、null/background preflight、baseline matrix、anti-shortcut plan 和 multi-seed/statistics protocol 都已有代码入口和测试覆盖。
    - 2026-07-26 当前工作区已真实物化并准备 campaign：
      - atomic source audit：`accepted=3754`、`manual_review=1345`
      - synthetic train/dev/control manifests：`140 / 109 / 143`
      - real count candidate / pilot queue：`5856 / 200`
      - real adjudicated candidate / pilot queue：`1800 / 100`
      - background pilot queue：`120`
      - synthetic scale audit：当前 `scale_insufficient_for_formal_training`
      - formal synthetic target candidate：train minimum `3000`、dev minimum `400`、control minimum `400`
      - critical atomic-source review queue：`4679`
      - deferred atomic-source review queue：`420`
      - deduplicated real annotation workload：`199` unique real commits
      - campaign batches：`10`
      - calibration round 1：`30`
    - 当前 small synthetic manifests 是 pipeline-validation scale，不是 final formal training asset。
    - 当前新增 annotation CLI 与 append-only audit log infrastructure，但没有人工标注事件或人工 gold。
    - 当前状态：
      - `annotation_campaign_prepared`
      - `human_execution_pending`
      - `synthetic_scale_candidate_planned`
      - `annotation_assets_formal_ready=false`
      - `stage1_v2_training_allowed=false`
      - `stage2_entry_allowed=false`
- 2026-07-23 Stage 1 独立复核结论：
  - `NO_GO_STAGE2`
  - 当前 P0 有效性问题包括：
    - strict synthetic 原子来源跨 split 暴露
    - Kmax freeze 证据链被 synthetic / replay / 重复行污染
    - official final test 由 `250 atomic k=1 + 250 strict synthetic k=2` 组成，不是人工 adjudicated 的真实多意图 final benchmark
    - final-test 标注质量当前缺少独立 agreement / adjudication 证据
  - 因此当前 official Stage1-v1 结果只能视为：
    - `formally_executed`
    - `internal_acceptance=passed`
    - `scientific_validity_audit=failed`
    - `external_paper_evidence=pilot_only`
    - `superseded_by=stage1-v2-protocol`

## 3. 当前实现清单

### Stage 0

- protocol freeze / DATA_CARD / EVAL_PROTOCOL / registry / leakage：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/stage0/data_card.py`
    - `code/mica/stage0/eval_protocol.py`
    - `code/mica/stage0/leakage_report.py`
    - `code/mica/stage0/protocol_freeze.py`
    - `code/mica/runners/run_stage0_protocol_freeze.py`
    - `configs/mica/data_asset_registry.json`
    - `docs/DATA_CARD.md`
    - `docs/EVAL_PROTOCOL.md`
  - 说明：
    - 校验逻辑存在且已有测试覆盖
    - `configs/mica/data_asset_registry.json` 已切到 `mica-data-asset-registry-v2` 并填入当前工作区可验证路径
    - registry validation 当前已区分全局 `formal_ready` 与按用途的 `readiness_by_requirement`
    - registry validation 现在还会对 `mica-checkpoint-v2` 做 full-model checkpoint 内容级校验；metadata-only checkpoint 不能让 `stage1_checkpoint_input` formal-ready
    - `run_stage0_protocol_freeze.py` 现在会在未显式提供 rows 文件时，从 registry 冻结 manifests 自动派生 Kmax coverage rows
    - 自动派生的 Kmax freeze 统计只接受 exact real count rows；synthetic、`censored_k_ge_2` 与缺少 exact-count 语义的 rows 会被显式排除
    - 当前 exact real count coverage 已真实计算：
      - eligible train/dev rows: `3910`
      - eligible train/dev multi-intent rows: `2250`
      - `coverage@Kmax=1.0` for `Kmax=4`
    - checked-in `stage1_checkpoint_input` 已提升为 clean frozen logical asset：
      - `artifact_id=stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42`
      - `produced_from_clean_commit=true`
      - `dirty_worktree=false`
      - `sha256=4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
    - 2026-07-23 clean candidate rebuild 与 local materialization 已真实校验：
      - clean SHA: `22bcd358766e1a678ee721c994830bdcf544213c`
      - checkpoint hash: `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
    - 原始 exact-count 报告仍保留 `tau_predeclared=false` 与 `freeze_supported=false`，因为它忠实反映“分布已被查看后才提出 tau”的事实
    - 当前已通过人工协议修订冻结 Kmax：
      - `configs/mica/protocol_decisions/stage1_kmax_decision.json`
      - `decision_version=stage1-kmax-v1`
      - `proposed_tau=0.95`
      - `selected_Kmax=4`
      - `amendment_type=pre_test_protocol_amendment`
      - `approved_by=fulin`
      - `approved_at=2026-07-23T16:45:14+08:00`
    - Stage 1/2 formal split manifests 已 materialize；`stage1_checkpoint_input` 已在 checked-in logical registry + local materialization registry 中校验通过；real alignment、message utility 等 required assets 仍缺失
    - `configs/mica/stage1_metric_thresholds.json` 已冻结为 `frozen_dev_thresholds_v1`
    - threshold 审批记录：
      - `configs/mica/protocol_decisions/stage1_threshold_approval.json`
      - `approved_by=fulin`
      - `approved_at=2026-07-23T16:45:14+08:00`
    - 已重新执行 Stage 0 readiness：
      - `outputs/mica_stage1_official_validation_20260723T091744Z/stage0/stage0_readiness.json`
      - `formal_ready=true`

### Stage 1

- official validation / metrics / baselines / prediction adapter：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/stages/stage1_official_validation.py`
    - `code/mica/runners/run_stage1_official_validation.py`
    - `code/mica/adapters/stage1_prediction_adapter.py`
    - `code/mica/eval/attribution_metrics.py`
    - `code/mica/baselines/baseline_runner.py`
    - `tests/mica/test_stage1_protocol_freeze.py`
    - `tests/mica/test_stage1_baselines_runner.py`
  - 说明：
    - canonical `run_stage1_official_validation.py` 已支持 full-model checkpoint execute path
    - execute 现在要求 formal-ready `stage1_official_final_test` registry asset
    - execute 现在还会校验 `--manifest` 是否匹配 registry 中冻结的 `stage1_official_final_test` manifest
    - execute 现在还会校验 `--checkpoint` 是否匹配 registry 中登记的 `stage1_checkpoint_input` checkpoint
    - execute 现在还会校验 checkpoint provenance 必须来自 clean git commit
    - execute 会写出 predictions、metrics、readiness、leakage report、checkpoint metadata 和 manifest
    - 当前分支已从 clean SHA `22bcd358766e1a678ee721c994830bdcf544213c` 执行真实 Stage 1 formal training，产出 full-model checkpoint：
      - `outputs/mica_stage1_clean_candidate_20260723T081816Z/training/stage1_full_model_checkpoint.pt`
      - checkpoint hash: `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
      - checkpoint round-trip: valid
    - 当前分支已执行真实 dev-only threshold selection：
      - `threshold_status=frozen_dev_thresholds_v1`
      - `approved_threshold_version=frozen_dev_thresholds_v1`
      - `official_final_test_not_used=true`
    - 当前分支已执行 split exposure audit：
      - 结论：`dev_only_unexposed_final_test`
    - 当前分支已执行真实 candidate validation：
      - `validation_run_executed=true`
      - `official_validation_executed=false`
      - `execution_tier=candidate_nonformal`
      - predictions rows: `500`
    - 当前分支已执行 official preflight：
      - `clean_git_worktree=true`
      - `clean_commit_checkpoint_provenance=true`
      - `logical_registry_materialized_hash_match=true`
      - `thresholds_approved=true`
      - `kmax_approved=true`
      - 总状态：`ready`
    - 当前分支已执行 canonical official validation：
      - output root:
        - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run`
      - `run_id=stage1_official_validation_20260723T091921Z`
      - `official_validation_executed=true`
      - `validation_run_executed=true`
      - `formal_ready=true`
      - 原始 official result：
        - `paper_ready=false`
      - predictions rows: `500`
      - prediction export errors: `0`
      - initial failure-closed acceptance gate:
        - `unit_accuracy_gain_over_all_one_min`
          - `observed=null`
      - 2026-07-23 frozen-artifact supplement：
        - runtime audit：
          - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_unit_accuracy_observability_audit.json`
        - runtime supplement：
          - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_unit_accuracy_supplemental_metrics.json`
        - checked-in supplement：
          - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_supplement_v1.json`
        - checked-in status revision：
          - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`
        - `root_cause=metric_computation_bug`
        - `mica_unit_accuracy=0.9623698380051325`
        - `all_one_unit_accuracy=0.8301833026082103`
        - `unit_accuracy_gain_over_all_one=0.13218653539692227`
        - `threshold=0.03`
        - `passed=true`
        - latest internal status revision：`paper_ready=true`
        - 但该状态已被独立审计重新定性为 `pilot_only`
    - checked-in official result record：
      - `configs/mica/official_results/stage1_official_validation_20260723T091921Z.json`

### Stage 2

- real-domain calibration / losses / trainer backend / mixture / runner：
  - `integrated_guarded_train_path_not_experiment_completed`
  - 证据文件：
    - `code/mica/stages/stage2_real_calibration.py`
    - `code/mica/runners/run_stage2_calibration.py`
    - `code/mica/losses/stage2_losses.py`
    - `code/mica/data/stage2_mixture.py`
    - `code/mica/training/backend.py`
    - `code/mica/training/loop_engine.py`
    - `code/mica/training/train_loop.py`
    - `code/mica/selective_risk.py`
    - `configs/mica/stage2_calibration_spec.json`
  - 说明：
    - loss routing、freeze plan、mixture plan 都存在
    - guarded `--train` 路径已使用 `MicaModelBackendAdapter`，不再由 Toy backend 充当 runner 主路径
    - train 执行仍需要 advisor approval / 显式 flag，不等于已经完成真实训练
    - dry-run 会写出 `stage2_selective_risk_calibration_artifact.json`
    - 若 dev rows 缺少 risk scores / component values，selective-risk artifact 会保持 `values_to_be_populated_by_dev_calibration_script`
    - 当前分支没有真实 Stage 2 checkpoint 或 dev calibration metric artifact

### Stage 3

- real alignment calibration / annotation / agreement / runner：
  - `integrated_guarded_train_path_not_experiment_completed`
  - 证据文件：
    - `code/mica/stages/stage3_real_alignment_calibration.py`
    - `code/mica/runners/run_stage3_alignment_calibration.py`
    - `code/mica/data/real_alignment.py`
    - `code/mica/annotation/agreement.py`
    - `docs/annotation/REAL_ALIGNMENT_GUIDELINES.md`
    - `configs/mica/stage3_alignment_calibration_spec.json`
  - 说明：
    - validation、summary、agreement、loss routing 都已实现
    - guarded `--train` 路径已使用 `MicaModelBackendAdapter`
    - real alignment validation 已检查 scope_status、action-object intent、unit_ids、gold_count、background/shared/uncertain/mixed unit consistency
    - train 执行仍需要 advisor approval / 显式 flag，不等于已经完成真实 calibration training
    - 当前分支没有真实 Stage 3 checkpoint 或 real alignment metric artifact

### Stage 4

- renderer / message utility / evidence lock：
  - deterministic renderer：`implemented`
  - optional FrozenLLM / external reference path：`function_level_infrastructure_without_real_experiment_evidence`
  - trainable reranker：`function_level_infrastructure_without_real_experiment_evidence`
  - 证据文件：
    - `code/mica/consumers/plan_schema.py`
    - `code/mica/consumers/evidence_summarizer.py`
    - `code/mica/consumers/message_generator.py`
    - `code/mica/consumers/verifier.py`
    - `code/mica/consumers/candidate_selector.py`
    - `code/mica/consumers/pipeline.py`
    - `code/mica/adapters/oracle_plan_adapter.py`
    - `code/mica/eval/message_coverage.py`
    - `code/mica/eval/unsupported_claims.py`
    - `code/mica/eval/entity_grounding.py`
    - `code/mica/eval/consumer_metrics.py`
    - `code/mica/eval/consumer_stratification.py`
    - `code/mica/eval/compare_consumer_runs.py`
    - `code/mica/eval/export_human_pilot.py`
    - `code/mica/baselines/llm_prompting_baseline.py`
    - `code/mica/baselines/pretrained_generation_baseline.py`
    - `code/mica/runners/run_message_baseline_generation.py`
    - `code/mica/renderers/deterministic.py`
    - `code/mica/renderers/trainable_reranker.py`
    - `code/mica/plan_builder.py`
    - `code/mica/runners/run_plan_renderer_smoke.py`
    - `code/mica/runners/export_consumer_plans.py`
    - `code/mica/runners/run_stage4_renderer_training.py`
    - `code/mica/stages/stage4_renderer_training.py`
    - `configs/mica/stage4_renderer_spec.json`
    - `configs/mica/frozen_llm_renderer_openai_compatible.example.json`
    - `configs/mica/message_baseline_generation_spec.example.json`
  - 说明：
    - deterministic evidence-locked rendering 是真实代码路径
    - frozen structured plan -> summarizer -> generator -> verifier -> selector 的本地 deterministic pipeline 已接入
    - legacy `DeterministicRenderer` 已改为兼容 wrapper，不再直接混合生成与弱校验逻辑
    - legacy `StructuredIntent.subject/body` 不再被视为运行时 surface message 输入
    - `decision=abstain|overflow` 时，pipeline 会返回 rejected，而不是伪造普通 commit message
    - slot coverage verifier 会按实际生成文本重算所有 foreground intent 的覆盖，不信任 renderer 自报 coverage
    - background exclusion verifier 依赖冻结后的 `background_units` assignment 与 `background_unit_records` evidence contract，而不是仅凭文件类型推断
    - 若 background record 缺失，consumer 会显式报告 `evidence_incomplete` 与 `missing_record_ids`
    - background audit schema 现已区分 `background_reason_source`、`background_assignment_type` 与 `background_record_resolution_status`
    - canonical `export_consumer_plans.py` 已能把 prediction / legacy plan 输出转换成 consumer plan JSONL，并对单条失败写 structured error row
    - `export_consumer_plans.py` 当前支持 `review_ready` 导出模式与外部 `edit_units` join，可显式区分“仅链路可跑”和“可审阅 structured plan”；summary 已提供 blocker 统计与 ready/blocked preview
    - `export_stage1_predictions.py` 已能把单样本 `TrainBatch + TrainOutputs` backend snapshot 导出为 canonical prediction JSONL，并要求显式 `release_decision`；summary 已提供 source/release/error 摘要
    - `export_stage1_predictions.py` 当前公开 `build_backend_snapshot_rows_from_samples(...)`；上游 producer 必须按 sample 切分后再写 snapshot JSONL，exporter 不负责拆分 multi-sample batch
    - `debug_stage1_attribution.py` 当前已通过 shared helper 支持可选 backend snapshot JSONL 导出，可把 debug/sanity 执行中的单样本 backend output 接到 `export_stage1_predictions.py -> export_consumer_plans.py --review-ready`
    - `run_stage1_official_validation.py` 与 `run_stage1_official_validation_dryrun.py` 当前已支持显式 consumer-plan export 接入，可在不执行真实 official validation 的前提下把 Stage 1 prediction artifact 导出为 canonical consumer plans
    - oracle-plan adapter 已能把 synthetic manual-adjudicated fixture 适配为 `plan_source=oracle` 的 canonical plan
    - `run_consumer_evaluation.py` 已提供 deterministic consumer eval runner，可产出 per-sample JSONL 与 aggregate JSON
    - eval runner 已支持 `plan_source`、`validate_only`、`overwrite`、`lenient malformed input`、atomic output write
    - message utility 基础设施已补齐 deterministic stratified aggregation、predicted-vs-oracle paired comparison、human-pilot blind export 格式
    - `FrozenLLMRenderer` 已实现为可选外部配置候选路径；仓库当前提供 `configs/mica/frozen_llm_renderer_openai_compatible.example.json` 默认真配置骨架，但默认 `enabled=false`，也没有当前分支真实 benchmark 结果
    - `run_message_baseline_generation.py` 已能把 `llm_prompting` / `pretrained_generation` 导出为 message-level external reference rows；当前支持 `validate_only`、`lenient`、`error_jsonl` 与 overwrite protection。仓库提供 `configs/mica/message_baseline_generation_spec.example.json`，其中 backend 默认 `enabled=false`
    - `run_stage4_renderer_training.py --train --train-ablation` 当前会执行 guarded reranker 训练并写 checkpoint/metrics；`trainable_reranker.py` 已公开 `load_candidate_reranker_checkpoint(...)` 与 `score_candidates_with_checkpoint(...)` 供 checkpoint replay / preview。这只证明 fixture 级可执行，不等于已完成 Stage 4 实验
    - backend snapshot export 仍只支持单样本 row；当前分支没有真实 multi-sample snapshot split/export 实现

### Core model / losses

- edit unit / encoder / evidence graph / slot decoder / null slot / count head / Hungarian / losses：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/models/encoder.py`
    - `code/mica/models/slot_decoder.py`
    - `code/mica/models/count_head.py`
    - `code/mica/models/mica_model.py`
    - `code/mica/model/null_slot.py`
    - `code/mica/evidence/relations.py`
    - `code/mica/evidence/relation_bias.py`
    - `code/mica/evidence/graph_features.py`
    - `code/mica/losses/cardinality.py`
    - `code/mica/losses/mica_losses.py`
    - `code/mica/losses/hungarian_matching.py`
    - `code/mica/losses/consistency_losses.py`
- 说明：
    - M0/M1/M2/M3/M4 都已有真实代码
    - null-slot helper 已存在，Stage 2/3 runner 构造的 MICA backend 使用 null slot assignment path
    - Stage 2/3 guarded train 已接入真实 MICA backend，但未形成真实实验产物
    - `solve_slot_matching()` 仍是 brute-force permutation 实现，更适合低 `Kmax` 场景

### Evaluation

- RealDomain / alignment / message utility / OOD / anti-shortcut：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/runners/run_real_domain_detection_eval.py`
    - `code/mica/runners/run_alignment_eval.py`
    - `code/mica/runners/run_message_utility_eval.py`
    - `code/mica/runners/run_consumer_evaluation.py`
    - `code/mica/runners/export_consumer_plans.py`
    - `code/mica/runners/run_ood_stress_eval.py`
    - `code/mica/runners/run_anti_shortcut_audit_dryrun.py`
    - `code/mica/eval/real_domain_detection.py`
    - `code/mica/eval/message_utility.py`
    - `code/mica/eval/consumer_metrics.py`
    - `code/mica/eval/consumer_stratification.py`
    - `code/mica/eval/compare_consumer_runs.py`
    - `code/mica/eval/export_human_pilot.py`
    - `code/mica/eval/ood_stress.py`
  - 说明：
    - 指标计算代码存在
    - runner 仍以 dry-run / fixture / summary 写出为主
    - 当前分支已具备 canonical export、oracle adapter、paired comparison、blind human-pilot export 的代码基础设施，但这些都只在 synthetic fixture 上验证
    - 当前分支没有完整 final evaluation 已执行的证据

### Baselines

- flat / no-slot / graph / TF-IDF / direct generation / LLM / pretrained generation：
  - 综合判断：`mixed`
  - 已实现：
    - `code/mica/baselines/flat_classifier.py`
    - `code/mica/baselines/no_slot_decoder.py`
    - `code/mica/baselines/graph_clustering.py`
    - `code/mica/baselines/metadata_tfidf_classifier.py`
    - `code/mica/baselines/direct_generation_baseline.py`
    - `code/mica/baselines/llm_prompting_baseline.py`
    - `code/mica/baselines/pretrained_generation_baseline.py`
    - `code/mica/runners/run_message_baseline_generation.py`
  - compatibility alias / historical name：
    - `code/mica/baselines/pretrained_classifier_placeholder.py`
  - 说明：
    - Stage 1 baseline runner 只消费 attribution baselines，并会显式拒绝 message utility baselines
    - message-level baselines 已通过独立 runner 消费 canonical structured plans
    - `pretrained_classifier_placeholder.py` 当前只是 `pretrained_generation` 的兼容别名包装，不应再被解读为独立 classifier placeholder 主线
    - `code/mica/eval/baseline_metrics.py` 对已实现但未在当前阶段执行的 baseline 统一输出 `not_run_in_this_stage`
    - 真实外部 API 调用仍需显式配置；当前分支没有提交 message-level benchmark 产物

### Annotation / benchmark

- real alignment 标注要求：
  - `partially_implemented`
  - 证据文件：
    - `docs/annotation/REAL_ALIGNMENT_GUIDELINES.md`
    - `code/mica/annotation/real_alignment_schema.py`
    - `code/mica/annotation/agreement.py`
    - `code/mica/annotation/adjudication.py`
  - 说明：
    - benchmark contract 已存在
    - 当前分支并不能证明 benchmark 的规模和双标覆盖已满足

### Experiment infra

- manifest / provenance / report schema / paper tables：
  - `partially_implemented`
  - 证据文件：
    - `code/mica/experiment/manifest_versioning.py`
    - `code/mica/experiment/provenance.py`
    - `code/mica/experiment/report_schema.py`
    - `code/mica/reporting.py`
    - `code/mica/paper_tables/`
  - 说明：
    - schema 与 table builder 已实现
    - 许多 table 仍明确是 placeholder 或 pending experiment rows
    - `grad_conflict_placeholder_or_optional` 当前会输出 machine-readable optional diagnostic contract；无数据时返回 `missing_grad_conflict`

### Tests

- 覆盖情况与风险：
  - `partially_implemented`
  - 证据文件：
    - `tests/mica/`
    - `tests/generation/`
  - 说明：
    - helper、metrics、fixture、dry-run runner 的单测覆盖较广
    - Stage 2/3 guarded train runner 已有 `MicaModelBackendAdapter` 路径测试覆盖
    - 当前测试仍主要验证 fixture / implementation-check 级别，不代表真实实验已执行
    - Stage 0 当前分支文档是在本次审计中补齐的

### Docs / reports

- docs：
  - current：
    - `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md`
    - `docs/MICA_IMPLEMENTATION_INDEX.md`
    - `docs/MICA_CONSUMER_ARCHITECTURE.md`
    - `docs/DATA_CARD.md`
    - `docs/EVAL_PROTOCOL.md`
  - historical：
    - `docs/records/*` 的大部分文件
  - outdated or potentially conflicting：
    - 多份 6 月 18-19 日实现进度记录
    - 一些更早的 broad checkpoint 文档
- reports：
  - `possibly_stale`
  - 证据文件：
    - `reports/mica_stage1_*`
    - `reports/current_experiment_checkpoint.json`
  - 说明：
    - 这些 reports 是历史运行总结，不是当前分支的 source-of-truth

## 4. 方案与代码差距矩阵

本节保留原有状态标签、证据路径与优先级判断，但不再重复扩展解释性大段英文正文。当前结论可概括为：

- 与方案基本对齐的部分：
  - M0 / M2 / M3 / M4 / M5 / M6 的代码骨架已存在
  - `L_multi` 已从 attribution 主路径中移除
  - deterministic evidence-locked rendering 是实际的当前 Stage 4 路径
  - frozen consumer pipeline 已实现 deterministic summarizer / verifier / selector 主链
- 仅部分对齐的部分：
  - Stage 0 有 validator 和文档，但仍不等于资产已可运行
  - Stage 1 有执行路径，但没有当前分支真实执行证明
- 主要差距：
  - Stage 2 与 Stage 3 已有 guarded runner/backend 接入，但没有当前分支真实训练和 calibration artifact 产物
  - null-slot assignment path 已在 MICA backend 中启用，但完整 null-slot 监督效果仍需真实数据验证
  - message utility benchmark 仍以 dry-run / proxy runner 为主，尚非真实 human benchmark
  - external frozen LLM renderer 仍未配置
  - 多份历史文档对“已完成 / paper-strength / CCF-A”表述强于当前真实状态

## 5. 集成风险

- integrated but not experiment-complete：
  - Stage 2 / Stage 3 guarded train path
  - Stage 2 selective-risk dev calibration artifact
  - null-slot support
  - consistency support
  - deterministic consumer pipeline 已上线，但未在真实 held-out benchmark 上完成 message utility 实跑
- duplicated logic：
  - Stage 1 仍保留旧 readiness wrapper、dry-run runner 与 canonical formal runner 三条入口
  - 其中 `run_official_stage1_validation.py` 现已显式标记为 deprecated readiness wrapper
- config not consumed：
  - asset registry 路径已填实，但仍有 required pending assets
  - 一些 Stage 2/3 config 开关存在，但没有真实执行证明
- runner/backend boundary：
  - Stage 2/3 canonical runner 已消费 train loop 与 `MicaModelBackendAdapter`
  - 当前仍缺真实 checkpoint loading / saving 和完整资产级训练产物
- tests only use toy fixtures：
  - backend、train loop、eval runner、paper table 路径主要还是 fixture / implementation-check 驱动
- docs overclaiming：
  - 历史实现进度记录仍可能被误读为当前集成状态
  - deterministic consumer 已实现，不应被扩大叙述成 “已完成 trainable / LLM renderer”

## 6. 过时 / 归档 / 移动文件

- `docs/records/archive/2026-06-18-mica-stage1-validation-dryrun-skeleton.md`
  - action taken：stale header + archive
  - reason：历史实现轮次记录，不再是当前事实来源
- `docs/records/archive/2026-06-18-mica-stage2-stage4-implementation-skeleton.md`
  - action taken：stale header + archive
  - reason：skeleton 阶段记录，容易夸大后续阶段完成度
- `docs/records/archive/2026-06-19-mica-ccfa-grade-implementation-progress.md`
  - action taken：stale header + archive
  - reason：完成度表述强于当前真实集成状态
- `docs/records/archive/2026-06-19-mica-p1-paper-strength-infra.md`
  - action taken：stale header + archive
  - reason：paper-strength 表述易误导
- `docs/records/archive/2026-06-19-mica-p2-core-method-implementation.md`
  - action taken：stale header + archive
  - reason：历史实现总结不应再充当当前状态摘要
- `docs/records/archive/2026-06-19-mica-stage2-stage3-executable-skeleton.md`
  - action taken：stale header + archive
  - reason：仍是 skeleton，而非 integrated training

## 7. 后续优先级

### P0

- 持续保证文档诚实区分：
  - Stage 2 / Stage 3 是 `integrated_guarded_train_path_not_experiment_completed`
  - Stage 1 有路径，不等于已执行
  - asset registry 已填实 formal split 路径，但整体 registry 仍非 formal-ready

### P1

- 如果未来恢复开发，应优先解决：
  - Stage 2 / Stage 3 checkpoint loading / saving 与真实资产训练产物
  - Stage 2 selective-risk dev rows 的真实 risk_score / component values 填充
  - real alignment / message utility 缺失资产的正式补齐
  - renderer-side message utility benchmark 的真实 held-out 执行
  - Stage 1 runner 叙事的进一步收口

### P2

- 继续清理 null-slot、consistency、ablation table、benchmark gate 等文档表述
- 如果历史记录继续造成混淆，可进一步扩大 archive 范围

## 8. 非执行确认

- 本轮执行了 real Stage 1 full-model training、threshold selection、Kmax exact-count audit、candidate validation、Stage 0 readiness、official preflight 与 canonical official Stage 1 validation
- 本轮没有执行 Stage 2 / Stage 3 训练
- 本轮没有执行 Stage 4 benchmark
- 本轮 runtime outputs 保持 local-only，没有提交到 Git

## 9. 2026-07-23 当前分支正式实验完成度审查

### 9.1 总体判断

- 当前分支已经具备：
  - core latent-slot attribution 主链
  - Stage 1 sanity / validation 基础设施
  - 一次 canonical official Stage 1 validation runtime result
  - Stage 2 / Stage 3 guarded calibration runner
  - Stage 4 deterministic consumer 与 message-utility 基础设施
- 但当前分支仍不具备“正式论文实验已完成”的证据链。
- 当前最主要阻塞项：
  - Stage 1 official path 已经形成 `paper_ready=true` 的 latest internal status revision，但该结果已被独立审计降级为 `pilot_only`
  - real alignment、message utility 相关 required assets 仍缺失
  - Stage 2 / Stage 3 没有当前分支真实 checkpoint、prediction、metric artifact
  - 没有 committed predicted plans、oracle plans、human message-utility annotation / result
  - Stage 2 / Stage 3 / Stage 4 仍没有当前分支正式 benchmark 结果

### 9.2 分阶段状态

- Stage 0
  - implemented：yes
  - tested：yes
  - integrated：yes
  - executable：yes
  - executed on real assets：yes
  - result available：yes
  - protocol-frozen：yes for Stage 1 official path
  - 备注：最新 Stage 0 readiness 对 Stage 1 official path 返回 `formal_ready=true`；registry 全局 `formal_ready` 仍因 Stage 3/4 缺失资产保持 `false`。
- Stage 1
  - implemented：yes
  - tested：yes
  - integrated：yes
  - executable：yes
  - executed on real assets：yes
  - result available：yes
  - protocol-frozen：yes
  - 备注：真实 full-model training、threshold selection、candidate validation、official preflight 与 official validation 都已在 formal Stage 1 assets 上执行；原始 official aggregate 中 `unit_accuracy_gain_over_all_one_min` 为 `observed=null`，现已通过 frozen-artifact supplement 补算恢复，因此 latest internal status revision 为 `paper_ready=true`。但独立审计已将该整套 Stage1-v1 结果降级为 `pilot_only`，并阻止直接进入 Stage 2。
- Stage 2
  - implemented：yes
  - tested：yes
  - integrated：partial
  - executable：yes
  - executed on real assets：no
  - result available：no
  - protocol-frozen：partial
  - 备注：`code/mica/runners/run_stage2_calibration.py` 与 `code/mica/stages/stage2_real_calibration.py` 已接入真实 backend，但 checkpoint 仍是 metadata-only。
- Stage 3
  - implemented：yes
  - tested：yes
  - integrated：partial
  - executable：yes
  - executed on real assets：no
  - result available：no
  - protocol-frozen：partial
  - 备注：`code/mica/runners/run_stage3_alignment_calibration.py` 已有 parameter-light calibration 路径，但真实 benchmark、真实 checkpoint 与真实 metric artifact 仍未见证据。
- Stage 4
  - deterministic consumer：implemented / tested / integrated / executable
  - oracle-predicted comparison / human pilot export：implemented / tested / fixture-only
  - executed on real assets：no
  - result available：no
  - protocol-frozen：partial
  - 备注：当前只有 deterministic consumer 与 eval infrastructure 的代码闭环，尚无正式 predicted-plan benchmark、oracle-plan benchmark、human pilot 结果。

### 9.3 资产就绪度

- 已存在且当前 registry / runtime 已消费的上游资产：
  - `datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
  - `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
  - `datasets/m_verified/canonical/usable_m_with_real_diff.csv`
  - `datasets/m_verified/canonical/usable_m_with_real_diff.jsonl`
  - `datasets/hard_b/canonical/usable_hard_b_with_real_diff.csv`
  - `datasets/hard_b/canonical/usable_hard_b_with_real_diff.jsonl`
- 当前未找到已提交正式资产或正式输出的项目：
  - `M-align-calib`
  - real alignment final benchmark
  - predicted plan JSONL
  - oracle plan JSONL
  - human message-utility annotations / ratings / reports
- 当前已提交 formal split manifests：
  - `datasets/mica/formal_assets/stage1/step1_high_conf_single_{train,dev,test}.json`
  - `datasets/mica/formal_assets/stage1/strict_synthetic_{train,dev,test}.json`
  - `datasets/mica/formal_assets/stage1/stage1_official_validation_dev.json`
  - `datasets/mica/formal_assets/stage1/stage1_official_final_test.json`
  - `datasets/mica/formal_assets/stage2/strict_replay.json`
  - `datasets/mica/formal_assets/stage2/hard_b_{train,dev,test}.json`
  - `datasets/mica/formal_assets/stage2/m_weak_{train,dev,test}.json`
- 当前已找到本分支 runtime 输出目录：
  - `outputs/mica_stage1_formal_training_20260723T073100Z`
    - 历史 dirty candidate runtime bundle，不是最终 official frozen asset
  - `outputs/mica_stage1_clean_candidate_20260723T081816Z`
    - 当前 clean candidate runtime bundle
    - 包含 training / threshold_selection / kmax_audit / candidate_validation / approval_packets
  - `outputs/mica_stage1_official_validation_20260723T091744Z`
    - 当前 official Stage 1 runtime bundle
    - 包含 stage0 readiness / official preflight / official_run

### 9.4 Canonical runner 与 smoke 证据

- 已通过实现级 smoke / validate-only 检查的入口：
  - `code/mica/runners/export_consumer_plans.py`
  - `code/mica/runners/run_consumer_evaluation.py`
  - `code/mica/runners/run_alignment_eval.py`
  - `code/mica/runners/run_real_domain_detection_eval.py`
  - `code/mica/runners/run_message_utility_eval.py`
- 当前 smoke 结论不应外推为正式实验完成：
  - Stage 1 / 2 / 3 / 4 runner 可以在 fixture 或 dry-run 路径下通过实现检查
  - 但这不等于已经基于正式冻结资产执行，也不等于已有可提交论文的结果

### 9.5 当前阻止宣称“实验已完成”的关键事实

- `configs/mica/data_asset_registry.json` 已把 `stage1_checkpoint_input` 提升为 clean frozen logical asset，但 local materialization 仍是机器本地 runtime 文件，不是 checked-in artifact
- `configs/mica/stage1_metric_thresholds.json` 当前已冻结为 `frozen_dev_thresholds_v1`
- Kmax 当前已通过 `pre_test_protocol_amendment` 冻结为 `selected_Kmax=4`、`tau=0.95`，但这不是 predeclared tau；且该 `stage1-kmax-v1` 对 Stage1-v2 已被 `invalidated_by_data_audit`
- official preflight 与 official execution 已发生；Stage 1 current remaining gap 已不在 acceptance metric，而在 Stage 2/3/4 正式资产与结果仍未闭合
- 原始 `paper_ready=false` 的根因不是审批缺失，而是 frozen acceptance criterion `unit_accuracy_gain_over_all_one_min` 在 original aggregate metrics 中 `observed=null`
- 该缺口现已通过 frozen-artifact supplement 恢复；当前 latest internal status revision 为 `paper_ready=true`，但 Stage1-v1 的外部论文证据地位已被独立审计降级为 `pilot_only`
- `code/mica/training/checkpointing.py` 目前没有闭合 Stage 2 / Stage 3 的完整权重 checkpoint 证据链
- `run_message_utility_eval.py` 当前仍是 proxy / infrastructure 路径，不是 human evaluation result
- 当前分支没有直接证据支持以下论文级宣称：
  - Stage 2 / Stage 3 calibration 已在真实资产上执行
  - real alignment benchmark 已完成
  - predicted-vs-oracle consumer comparison 已完成
  - message utility human pilot 已完成

## 10. 2026-07-26 Stage1-v2 R2 / Source Review / Synthetic Quarantine

新增事实状态：

- Source-review sidecar hardening 已实现并通过 validator：
  - `code/mica/stage1_v2/source_review.py`
  - `tests/mica/test_stage1_v2_hardening.py`
  - `source_review_status_summary.json`
- 当前 LLM source review：
  - total rows：`613`
  - `llm_accept=552`
  - `llm_reject=61`
  - `llm_second_review=92`
  - all rows：`actor_type=llm`, `human_verified=false`
- R2 LLM calibration：
  - status：`llm_calibration_round_2=incomplete`
  - pre-adjudication agreement：`not_computed_due_to_integrity_failure`
  - adjudication：not started
  - guideline status：`blocked_by_incomplete_annotation`
  - Codex diagnostic markings：`30` rows
  - user-reviewed diagnostic markings：`30` rows
  - review evidence：`chat_confirmation`
  - formal blocker：`not_independent_double_annotation_or_adjudication`
  - audit log：`60` chained `reviewed` events, hash-chain valid
  - reviewed diagnostic analysis：`30` rows
  - follow-up queue：`23` rows
  - P0/P1/P2/P3：`4 / 5 / 14 / 7`
  - guideline v3 draft：`revision_draft_only`
  - P0 user-reviewed diagnostic decisions：`overflow_stress=3`, `usable_k_le_4=1`
  - P1 user-reviewed diagnostic decisions：`5` rows, all `usable_k_le_4`, exact-k distribution `k=1:2`, `k=2:3`
  - P2 user-reviewed diagnostic decisions：`14` rows, all `usable_k_le_4`, exact-k distribution `k=1:5`, `k=2:5`, `k=3:3`, `k=4:1`
  - P2 changed original Codex exact-k for `calibration_round_2_0022` (`4→3`) and `calibration_round_2_0027` (`4→2`)
  - P3 user-reviewed diagnostic decisions：`7` rows, all `accepted_low_risk_diagnostic`, exact-k distribution `k=1:6`, `k=3:1`
- Synthetic quarantine：
  - quarantined samples：`45`
  - synthetic candidate v2 counts：train/dev/control `128 / 100 / 119`
  - leakage audit：all required overlaps zero; near-duplicate comparison not skipped
  - candidate v2 is `synthetic_llm_screened_candidate`, not formal frozen asset

Readiness remains blocked:

- `required_atomic_sources_human_verified=false`
- `annotation_assets_formal_ready=false`
- `stage1_v2_training_allowed=false`
- `stage2_entry_allowed=false`
