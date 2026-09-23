# MICA Stage 0 / Stage 1 Execution Notes

## 1. Scope

本文档只描述当前分支已经实现并已执行的 Stage 0 / Stage 1 formal infrastructure 与运行状态，不外推到 Stage 2 / Stage 3 / Stage 4，也不把一次 official execute 自动等同于 paper-ready。

## 2. Stage 0

- canonical runner:
  - `code/mica/runners/run_stage0_protocol_freeze.py`
- 当前 Stage 0 canonical readiness 会输出：
  - protocol schema validation
  - registry schema validation
  - assets materialized / content valid
  - checkpoint full-model / loadable / hash verified
  - splits leakage clean
  - `thresholds_approved`
  - `Kmax_protocol_frozen`
  - `official_final_test_manifest_frozen`
  - `official_final_test_unexposed`
  - `formal_ready`
- 当前真实状态：
  - checked-in logical registry:
    - `configs/mica/data_asset_registry.json`
  - checked-in `stage1_checkpoint_input` 已是 clean frozen logical asset：
    - `artifact_id=stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42`
    - `sha256=4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
    - `training_git_sha=22bcd358766e1a678ee721c994830bdcf544213c`
    - `dirty_worktree=false`
    - `local_materialization_required=true`
  - exact-count Kmax audit 只接受 exact real count rows，显式排除 synthetic 与 `censored_k_ge_2`
  - 当前 exact-count 统计：
    - eligible train/dev exact real rows: `3910`
    - eligible train/dev exact real multi-intent rows: `2250`
    - `coverage@Kmax=1.0` for `Kmax=4`
  - Kmax 冻结不是 predeclared tau，而是 approved pre-test amendment：
    - `configs/mica/protocol_decisions/stage1_kmax_decision.json`
    - `decision_version=stage1-kmax-v1`
    - `proposed_tau=0.95`
    - `selected_Kmax=4`
    - `amendment_type=pre_test_protocol_amendment`
  - threshold 审批记录：
    - `configs/mica/protocol_decisions/stage1_threshold_approval.json`
    - `approved_threshold_version=frozen_dev_thresholds_v1`
- 最新 Stage 0 readiness runtime report：
  - `outputs/mica_stage1_official_validation_20260723T091744Z/stage0/stage0_readiness.json`
  - 关键 gate：
    - `protocol_schema_valid=true`
    - `registry_schema_valid=true`
    - `assets_materialized=true`
    - `assets_content_valid=true`
    - `checkpoint_full_model=true`
    - `checkpoint_loadable=true`
    - `checkpoint_hash_verified=true`
    - `thresholds_approved=true`
    - `Kmax_protocol_frozen=true`
    - `official_final_test_manifest_frozen=true`
    - `official_final_test_unexposed=true`
    - `formal_ready=true`
- 注意：
  - registry 全局 `formal_ready` 仍为 `false`
  - 原因不是 Stage 1 缺口，而是 Stage 3 / Stage 4 required assets 仍缺失
  - Stage 1 official path 所需的 Stage 0 readiness 当前已经 `formal_ready=true`

## 3. Stage 1 Canonical Official Validation

- canonical runner:
  - `code/mica/runners/run_stage1_official_validation.py`
- execute 前置条件：
  - `--execute`
  - clean execution code state
  - clean checkpoint provenance
  - frozen logical `stage1_checkpoint_input`
  - approved threshold decision
  - approved Kmax decision
  - frozen `stage1_official_final_test`
  - `candidate_validation_split_must_not_equal_official_final_test_split=true`
  - Stage 0 readiness `formal_ready=true`
  - official preflight `status=ready`
- execute 输出契约：
  - `stage1_official_validation_manifest.json`
  - `stage1_official_validation_plan.json`
  - `stage1_official_validation_summary.json`
  - `stage1_official_validation_predictions.jsonl`
  - `stage1_official_validation_prediction_export_errors.jsonl`
  - `stage1_official_validation_metrics.json`
  - `stage1_official_validation_aggregate_metrics.json`
  - `stage1_official_validation_readiness.json`
  - `stage1_official_validation_leakage_report.json`
  - `stage1_official_validation_checkpoint_metadata.json`
  - `stage1_official_validation_stage0_readiness_snapshot.json`
  - `stage1_official_validation_preflight_snapshot.json`
  - `stage1_official_validation_completion.json`

## 4. 当前真实执行状态

- real full-model training：
  - output root:
    - `outputs/mica_stage1_clean_candidate_20260723T081816Z/training`
  - clean training SHA:
    - `22bcd358766e1a678ee721c994830bdcf544213c`
  - checkpoint:
    - `stage1_full_model_checkpoint.pt`
  - checkpoint hash:
    - `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
  - checkpoint round-trip:
    - valid
  - fixed-input prediction consistency:
    - valid
- real dev-only threshold selection：
  - output root:
    - `outputs/mica_stage1_clean_candidate_20260723T081816Z/threshold_selection`
  - `threshold_status=frozen_dev_thresholds_v1`
  - `official_final_test_not_used=true`
- real Kmax exact-count audit：
  - output root:
    - `outputs/mica_stage1_clean_candidate_20260723T081816Z/kmax_audit`
  - current report still records:
    - `tau_predeclared=false`
    - `freeze_supported=false`
  - protocol decision now overrides this as approved pre-test amendment:
    - `stage1-kmax-v1`
- real candidate validation：
  - output root:
    - `outputs/mica_stage1_clean_candidate_20260723T081816Z/candidate_validation`
  - `validation_run_executed=true`
  - `official_validation_executed=false`
  - `execution_tier=candidate_nonformal`
- official preflight：
  - `outputs/mica_stage1_official_validation_20260723T091744Z/official_preflight.json`
  - `status=ready`
- official Stage 1 validation：
  - output root:
    - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run`
  - run id:
    - `stage1_official_validation_20260723T091921Z`
  - `official_validation_executed=true`
  - `validation_run_executed=true`
  - `formal_ready=true`
  - 原始 official result：
    - `paper_ready=false`
  - predictions rows:
    - `500`
  - prediction export errors:
    - `0`
  - frozen acceptance criteria:
    - passed:
      - `count_accuracy_min`
      - `k2_split_recall_min`
      - `over_split_rate_on_k1_max`
      - `second_slot_gold_recall_min`
      - `slot_collapse_rate_max`
    - initial missing:
      - `unit_accuracy_gain_over_all_one_min`
        - `observed=null`
    - 2026-07-23 supplement recovered from frozen artifacts:
      - `unit_accuracy_gain_over_all_one = 0.13218653539692227`
      - `all_one_unit_accuracy = 0.8301833026082103`
      - `mica_unit_accuracy = 0.9623698380051325`
      - `threshold = 0.03`
      - `passed=true`
- latest checked-in status revision：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`
  - `paper_ready=true`
- checked-in independent audit downgrade：
  - `configs/mica/official_results/stage1_v1_audit_status.json`
  - `execution_status=formally_executed`
  - `internal_acceptance=passed`
  - `scientific_validity_audit=failed`
  - `external_paper_evidence=pilot_only`
  - `superseded_by=stage1-v2-protocol`
- checked-in small result record：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z.json`
- checked-in supplemental records：
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_supplement_v1.json`
  - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`
- runtime artifacts：
  - local-only
  - not committed into Git

## 5. Threshold and Acceptance Semantics

- 当前 `configs/mica/stage1_metric_thresholds.json` 已是：
  - `frozen_dev_thresholds_v1`
- 当前状态同时满足：
  - 阈值审批完成
  - Kmax 审批完成
  - official execute 完成
- 当前 latest status revision 只说明 Stage1-v1 的内部 acceptance 链闭合：
  - 原始 official model evaluation 已完成
  - `unit_accuracy_gain_over_all_one_min` 的缺口已通过 frozen-artifact supplement 补上
  - supplement 没有重新训练、没有重跑 model inference、没有调整 threshold / Kmax / split
  - original official result record 保留不变；latest status 由追加式 revision 给出
- 但独立审计后的对外地位已被重新定义：
  - `scientific_validity_audit=failed`
  - `external_paper_evidence=pilot_only`
  - 后续需要通过 `docs/MICA_STAGE1_V2_REAL_ADJUDICATED_PROTOCOL.md` 重建 Stage1-v2，不能直接以 Stage1-v1 进入正式 Stage 2

## 6. Compatibility Runners

- `code/mica/runners/run_official_stage1_validation.py`
  - 当前角色：deprecated readiness wrapper
  - 不是 canonical official execution 入口
- `code/mica/runners/run_stage1_official_validation_dryrun.py`
  - 当前角色：dry-run / metric smoke / optional consumer-plan export
  - 不等于正式 official validation execute

## 7. Non-claims

当前分支不能据此宣称：

- Stage 1 已达到论文最终 acceptance 标准
- Stage1-v1 可以直接作为 Stage 2 正式论文实验入口
- Stage 2 / Stage 3 已开始正式训练
- real alignment benchmark 已完成
- Stage 4 message utility benchmark 已完成
- runtime `outputs/**` 已远程归档或已提交入库
