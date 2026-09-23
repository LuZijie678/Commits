# EVAL_PROTOCOL

状态：当前工作区参考文档

本文档总结当前工作区希望遵守的 Stage 0 评测协议约束。它描述协议边界，不代表这些评测已经在当前分支上完成执行。

## 阶段划分

- Stage 1 synthetic attribution validation
- Stage 2 hard_b / M calibration
- Stage 3 real alignment calibration/eval
- Stage 4 deterministic evidence-locked rendering

## 主表方向

- RealDomainSplit / hard_b main table
- alignment benchmark table
- message utility table
- anti-shortcut / OOD stress
- baseline table
- RealDomainSplit table
- RealDomainSelective table

## 防护规则

- Abstention thresholds:
  - selection_split: dev only
  - default_rule: fixed target coverage or full coverage-risk curve
  - final_test_tuning: forbidden
  - status:
    - protocol_defined
    - values_to_be_populated_by_dev_calibration_script
    - approved_for_stage1_official_validation
    - version: `frozen_dev_thresholds_v1`
    - approved_by: `fulin`
    - approved_at: `2026-07-23T16:45:14+08:00`
- real alignment benchmark held-out policy:
  - status: protocol_requires_freeze_before_final_evaluation
  - allowed_options:
    - cross_repository_heldout_primary
    - time_based_heldout_secondary
  - forbidden:
    - unspecified repo overlap
    - mixed train/test repositories without reporting overlap
- final-test never used for training/tuning
- oracle-k vs predicted-k must be reported
- Kmax coverage reporting is mandatory on every evaluation split
- overflow / abstention rate must be reported
- clustering is a baseline, not the primary formulation
- renderer scores cannot select attribution checkpoints
- background/null must be audited separately from semantic uncertainty
- oracle-k / predicted-k / overflow must be jointly reported where applicable
- Stage 2 uses hard_b and M weak labels only for split/no-split/abstain boundary calibration
- Stage 3 real alignment calibration is parameter-light and separate from Stage 2 count calibration
- renderer metrics cannot select attribution checkpoints, thresholds, templates, prompts, or verifier settings
- alignment benchmark construction must be documented
- coverage-risk curve must be reported for abstaining models
- selective attribution metrics must be reported at fixed coverage levels
- abstention precision and false-abstain rate must be reported
- forced-decomposition error on out-of-scope commits must be reported
- generation is downstream utility, not main contribution
- RealDomainSplit = k=1 vs k>=2 split / no-split boundary evaluation
- RealDomainSelective = in-scope decomposable vs overflow / abstain evaluation
- FPR_hard_b = percentage of hard_b single-intent commits predicted as multi-intent
- pseudo alignment cannot be used as final real-alignment gold
- synthetic construction labels cannot be mixed into the real alignment benchmark
- these diagnostics are validity checks, not method-selection ablations

## Real alignment benchmark held-out policy

- Primary setting:
  - cross-repository held-out evaluation
  - no repository overlap between train/dev calibration assets and final real alignment test
- Secondary setting, if cross-repository sample size is insufficient:
  - time-based held-out evaluation within repository
  - train/dev commits must be earlier than test commits
  - no PR, issue, release branch, or tangled construction group overlap
- Reporting rule:
  - final paper must state which setting is used:
    - cross-repository held-out
    - time-based held-out
    - both
  - repo overlap decision cannot remain pending in the final protocol

## Background slot audit metrics

- Required:
  - background assignment rate
  - foreground evidence swallowed by background
  - foreground-to-background error
  - missing-intent rate by file role
  - background precision on rule-verified background units
  - background recall on rule-verified background units
- Reporting rules:
  - background errors must be reported separately from foreground attribution errors
  - semantic uncertainty must not be counted as correct background assignment
  - ambiguous units with unknown background labels must be excluded from L_bg metric denominators unless manually adjudicated

## 当前分支现实检查

- 当前代码通过 `code/mica/stage0/eval_protocol.py` 校验上述协议文本。
- `code/mica/runners/run_stage1_official_validation.py` 现已是 Stage 1 canonical formal runner：
  - `--execute` 路径要求 full-model checkpoint，而不是 metadata-only checkpoint
  - `--checkpoint` 必须匹配 registry 中登记的 `stage1_checkpoint_input`
  - `--manifest` execute 路径必须绑定：
    - `stage1_official_final_test`
  - official execute 前必须通过 clean checkpoint provenance gate，dirty-worktree candidate 不能进入 official path
  - 会写出 predictions、metrics、readiness、leakage report、checkpoint metadata、manifest
  - 只有在阈值已 approved/frozen 且 Stage 0 gates 全部满足时，才能标记 `official_validation_executed=true`
  - 若阈值仍是 candidate / pending，只能执行 nonformal candidate validation，不能标记 final-paper-ready
- `code/mica/runners/run_stage1_official_preflight.py` 当前提供只读 preflight：
  - 检查 clean git worktree
  - 检查 clean-commit checkpoint provenance
  - 检查 logical registry 与 local materialization hash 一致
  - 检查 `candidate_validation_split_must_not_equal_official_final_test_split`
  - 检查 thresholds / Kmax 是否已经人工审批
  - 不执行 official evaluation
- `code/mica/runners/run_official_stage1_validation.py` 仍保留，但当前只作为 deprecated readiness wrapper，不是正式 execution 入口。
- 当前分支的真实 Stage 1 执行证据：
  - 已从 clean SHA `22bcd358766e1a678ee721c994830bdcf544213c` 重建 full-model checkpoint candidate
  - 已完成 dev-only threshold candidate selection
  - 已执行 `candidate_nonformal` Stage 1 validation，并写出真实 predictions / metrics
  - 已生成并审批 split exposure audit、threshold approval packet 和 Kmax decision packet
  - threshold 冻结记录：
    - `configs/mica/stage1_metric_thresholds.json`
    - `configs/mica/protocol_decisions/stage1_threshold_approval.json`
  - Kmax 冻结记录：
    - `configs/mica/protocol_decisions/stage1_kmax_decision.json`
    - 该决定明确属于 `pre_test_protocol_amendment`，不是 predeclared tau
    - 对 Stage1-v2 的当前地位：
      - `invalidated_by_data_audit`
      - 不得继续作为 Stage1-v2 的真实 Kmax 证据
  - checked-in `stage1_checkpoint_input` 现已提升为 clean frozen logical asset：
    - `artifact_id=stage1_candidate_22bcd358766e_f280eebdf24a_9320b20f609e_seed42`
    - `sha256=4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`
  - 已执行 Stage 0 readiness：
    - `outputs/mica_stage1_official_validation_20260723T091744Z/stage0/stage0_readiness.json`
    - `formal_ready=true`
  - 已执行 official preflight：
    - `outputs/mica_stage1_official_validation_20260723T091744Z/official_preflight.json`
    - `status=ready`
  - `candidate_validation_split_must_not_equal_official_final_test_split=true`
  - 已执行 official Stage 1 validation：
    - output root:
      - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run`
    - `official_validation_executed=true`
    - `formal_ready=true`
    - 原始 official aggregate metrics：
      - `paper_ready=false`
      - frozen acceptance criterion `unit_accuracy_gain_over_all_one_min` 当时 `observed=null`
    - 2026-07-23 当前分支已追加只读 metric supplement：
      - runtime audit：
        - `outputs/mica_stage1_official_validation_20260723T091744Z/official_run/stage1_unit_accuracy_observability_audit.json`
      - recovered metric：
        - `unit_accuracy_gain_over_all_one = 0.13218653539692227`
      - threshold：
        - `unit_accuracy_gain_over_all_one_min = 0.03`
    - current internal status revision：
      - `configs/mica/official_results/stage1_official_validation_20260723T091921Z_status_revision_v1.json`
      - `paper_ready=true`
    - 但当前对外协议地位已被独立审计降级：
      - `configs/mica/official_results/stage1_v1_audit_status.json`
      - `scientific_validity_audit=failed`
      - `external_paper_evidence=pilot_only`
- 当前 Stage1-v2 重建协议入口：
  - `docs/MICA_STAGE1_V2_REAL_ADJUDICATED_PROTOCOL.md`
  - `configs/mica/protocol_decisions/stage1_v2_protocol_reset.json`
- 当前 Stage1-v2 machine-readable frozen protocol：
  - `configs/mica/stage1_v2_protocol_spec.json`
  - primary endpoint：
    - `bcubed_f1_real_k_ge_2`
  - 该配置当前只表示协议冻结，不表示真实 benchmark 已物化。
- 当前 Stage1-v2 readiness / data execution 入口：
  - `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`
  - `configs/mica/stage1_v2_asset_registry.json`
- 2026-07-26 当前已真实物化但仍不得视为正式论文证据的 Stage1-v2 资产：
  - atomic source audit accepted：`3754`
  - atomic source manual review：`1345`
  - synthetic train/dev/control：`140 / 109 / 143`
  - real count candidate / pilot：`5856 / 200`
  - real adjudicated candidate / pilot：`1800 / 100`
  - background annotation pilot：`120`
  - critical atomic-source review queue：`4679`
  - deferred atomic-source review queue：`420`
  - deduplicated real annotation workload：`199` unique real commits
  - annotation campaign batches：`10`
  - calibration round 1：`30`
- 2026-07-26 当前 synthetic scale 状态：
  - current train/dev/control manifests：`140 / 109 / 143`
  - `scale_insufficient_for_formal_training=true`
  - `not_frozen_training_asset=true`
  - formal target candidate：
    - train minimum：`3000`
    - dev minimum：`400`
    - control minimum：`400`
  - blocking reasons：
    - `k3_k4_construction_not_implemented`
    - `required_atomic_sources_need_human_verification`
- 2026-07-26 当前 annotation campaign 状态：
  - `annotation_campaign_prepared`
  - `human_execution_pending`
  - `annotation_staffing_complete=false`
  - `annotators_qualified=false`
  - `calibration_round_complete=false`
  - `calibration_agreement_passed=false`
- 2026-07-26 当前 Stage1-v2 readiness：
  - `synthetic_scale_sufficient=false`
  - `required_atomic_sources_human_verified=false`
  - `annotation_assets_formal_ready=false`
  - `stage1_v2_training_allowed=false`
  - `stage2_entry_allowed=false`
- 2026-07-26 R2 LLM diagnostic status：
  - R2 integrity：`r2_annotation_incomplete`
  - pre-adjudication agreement：`not_computed_due_to_integrity_failure`
  - gate basis：pre-adjudication A/B agreement only; adjudication cannot improve gate metrics.
  - adjudication：not started because validated independent A/B outputs are missing.
  - guideline status：`blocked_by_incomplete_annotation`
  - formal human evidence：`false`
  - Codex diagnostic markings：`30` rows, user-reviewed via chat confirmation.
  - User-reviewed diagnostic markings remain `formal_human_evidence=false` and cannot be used as formal A/B agreement or adjudicated gold.
  - R2 audit log：`60` chained `reviewed` events, hash-chain valid across reviewed diagnostic marking and P0/P1/P2/P3 sidecars.
  - Reviewed diagnostic analysis：follow-up queue `23`; P0/P1/P2/P3 = `4 / 5 / 14 / 7`.
  - Guideline v3 draft is `revision_draft_only`; it cannot change frozen agreement gates or unlock training.
- 2026-07-26 synthetic quarantine status：
  - quarantined samples：`45`
  - synthetic candidate v2 train/dev/control：`128 / 100 / 119`
  - candidate v2 leakage audit：required overlaps zero; near-duplicate comparison not skipped.
  - candidate v2 remains non-formal：`human_verified_sources=false`, `formal_frozen=false`
- Stage 2/3/4 runner 与大多数 eval runner 仍主要停留在 dry-run、fixture 或 contract 校验路径；当前分支没有 committed 的正式 Stage 2/3/4 benchmark 结果。
- 阅读本文件时，应同时参考 `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md`，后者记录当前分支里真正已经实现和已经接入的状态。
