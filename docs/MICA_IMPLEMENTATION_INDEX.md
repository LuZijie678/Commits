# MICA 文档索引

## 当前事实来源

- `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md`
- `docs/MICA_STAGE1_INDEPENDENT_AUDIT.md`
  - `2026-07-23` 的 Stage 1 只读独立复核审计。
  - 结论：当前 Stage 1 不能据此直接进入 Stage 2。
- `docs/MICA_STAGE1_V2_REAL_ADJUDICATED_PROTOCOL.md`
  - Stage1-v1 降级与 Stage1-v2 重建协议。
  - 当前状态：`protocol_frozen + assets_pending`
- `docs/MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md`
  - Stage1-v2 数据、标注、baseline、anti-shortcut 和 readiness 执行说明。
- `docs/MICA_STAGE1_V2_SYNTHETIC_SCALE_UP_PROCEDURE.md`
  - Stage1-v2 synthetic scale-up candidate 方案和 freeze 条件。
  - 当前状态：`synthetic_scale_candidate_planned + not_frozen_training_asset`
  - 当前 `140 / 109 / 143` 只代表 pipeline-validation scale。

## 核心方案

- `docs/plans/MICA_v3_trainable_algorithm_plan.md`
  - 原始 v3 方案参照版，保留原始论证与叙事。
- `docs/plans/MICA_v3_trainable_algorithm_plan_cn.md`
  - 中文整理版 / 目标规格 companion，便于阅读、实现映射和文档治理。
  - 与原始 v3 plan 并列保留，但两者都不是当前实现事实来源。
- `docs/plans/MICA_multi_intent_commit_attribution_plan.md`
  - 历史 / 上游方案说明，用于记录更早期、更宽范围的方案背景。
  - 不是当前目标方案，不应与 MICA-v3 plan 并列视为当前规范。

## 数据与评测协议

- `docs/DATA_CARD.md`
- `docs/EVAL_PROTOCOL.md`
- `configs/mica/protocol_decisions/stage1_v2_protocol_reset.json`
  - Stage1-v2 协议重置 decision record。
- `configs/mica/stage1_v2_protocol_spec.json`
  - Stage1-v2 machine-readable frozen protocol spec。
- `configs/mica/stage1_v2_asset_registry.json`
  - Stage1-v2 asset registry namespace，当前为 `candidate_materialized / annotation_pending / pending_generation`。

## 实现说明 / 协议类文档

- `docs/MICA_CONSUMER_ARCHITECTURE.md`
- `docs/MICA_STAGE0_STAGE1_EXECUTION.md`
- `docs/MICA_DATA_ASSET_REGISTRY.md`
- `docs/archive_policy.md`
- `docs/git-lfs-and-runtime-output-policy.md`
- `docs/annotation/REAL_ALIGNMENT_GUIDELINES.md`
- `docs/records/2026-06-19-mica-runner-registry.md`

## 标注文档

- `docs/annotation/REAL_ALIGNMENT_GUIDELINES.md`
- `docs/annotation/STAGE1_V2_COUNT_GUIDELINE_PILOT_V1.md`
- `docs/annotation/STAGE1_V2_ALIGNMENT_GUIDELINE_PILOT_V1.md`
- `docs/annotation/STAGE1_V2_COUNT_GUIDELINE_PILOT_V2.md`
- `docs/annotation/STAGE1_V2_ALIGNMENT_GUIDELINE_PILOT_V2.md`
- `docs/annotation/STAGE1_V2_LLM_ANNOTATION_AMENDMENT.md`
- `docs/annotation/STAGE1_V2_BACKGROUND_ANNOTATION_GUIDELINE.md`
- `docs/annotation/STAGE1_V2_ANNOTATOR_TRAINING_MANUAL.md`
- `docs/annotation/STAGE1_V2_ADJUDICATOR_MANUAL.md`
- `docs/annotation/STAGE1_V2_QUALIFICATION_INSTRUCTIONS.md`
- `docs/annotation/STAGE1_V2_ANNOTATION_STATE_MACHINE.md`
- `docs/annotation/STAGE1_V2_PILOT_EXECUTION_CHECKLIST.md`
- `docs/annotation/STAGE1_V2_ANNOTATION_CAMPAIGN_OPERATOR_GUIDE.md`
- `docs/annotation/STAGE1_V2_CALIBRATION_ROUND_PROCEDURE.md`
- `docs/annotation/STAGE1_V2_SOURCE_REVIEW_PROCEDURE.md`
- `docs/annotation/STAGE1_V2_ANNOTATION_AUDIT_LOG_SPEC.md`

## 历史记录

- `docs/records/`

## 已归档 / 过时记录

- `docs/records/archive/`
- `docs/plans/archive/`

## 重要规则

历史记录不是当前事实来源。

当前实现状态必须以代码和 `docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md` 为准，而不是以任一历史或方案文档为准。

若需要查看当前 Stage 1 official result 是否已经通过独立有效性审计，请同时阅读 `docs/MICA_STAGE1_INDEPENDENT_AUDIT.md`。

若需要查看当前 Stage 1 official result 的历史降级状态，请读取：

- `configs/mica/official_results/stage1_v1_audit_status.json`

## 2026-07-26 Stage1-v2 R2 / Hardening Artifacts

Implementation:

- `code/mica/stage1_v2/source_review.py`
- `code/mica/stage1_v2/audit_log.py`

Tests:

- `tests/mica/test_stage1_v2_hardening.py`

R2 reports:

- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_annotation_integrity_report.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_pre_adjudication_agreement.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_gate_report.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_adjudication_report.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_guideline_decision.json`
- `datasets/mica/stage1_v2/real_alignment/codex_calibration_round_2_llm_markings.jsonl`
- `datasets/mica/stage1_v2/real_alignment/codex_calibration_round_2_llm_marking_summary.json`
- `datasets/mica/stage1_v2/real_alignment/human_review_receipt_codex_calibration_round_2.json`
- `datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_markings.jsonl`
- `datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_summary.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_reviewed_diagnostic_analysis.json`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_review_followup_queue.jsonl`
- `docs/annotation/CALIBRATION_ROUND_2_P0_HUMAN_REVIEW_SHEET.md`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p0_human_review_template.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p0_codex_review_filled.jsonl`
- `datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p0_codex_review.json`
- `datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p0_codex_review.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p1_codex_review_filled.jsonl`
- `datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p1_codex_review.json`
- `datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p1_codex_review.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p2_codex_review_filled.jsonl`
- `datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p2_codex_review.json`
- `datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p2_codex_review.jsonl`
- `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p3_codex_review_filled.jsonl`
- `docs/annotation/STAGE1_V2_GUIDELINE_PILOT_V3_REVISION_DRAFT.md`

R2 diagnostic analysis runner:

- `code/mica/stage1_v2/reviewed_diagnostic.py`
- `code/mica/runners/run_stage1_v2_reviewed_diagnostic_analysis.py`
- `tests/mica/test_stage1_v2_reviewed_diagnostic.py`

Synthetic quarantine / candidate v2:

- `datasets/mica/stage1_v2/synthetic/quarantined_synthetic_samples.jsonl`
- `datasets/mica/stage1_v2/synthetic/rejected_source_impact_map.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_train.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_dev.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_control_test.jsonl`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_leakage_report.json`
- `datasets/mica/stage1_v2/synthetic/synthetic_candidate_v2_summary.json`

Current state remains:

- `human_execution_pending`
- `stage1_v2_training_blocked`
- `stage2_entry_blocked`

Latest R2 diagnostic review state:

- P1 user-reviewed diagnostic decisions: `5` rows, `formal_human_evidence=false`
- P2 user-reviewed diagnostic decisions: `14` rows, `formal_human_evidence=false`
- P3 user-reviewed diagnostic decisions: `7` rows, `formal_human_evidence=false`
- Annotation audit log: `60` chained `reviewed` events, hash-chain valid
