# Stage1-v2 Annotation State Machine

状态：`frozen_for_workflow`

## 1. 状态

- `pending`
- `annotated_a`
- `annotated_b`
- `independently_double_annotated`
- `agreement`
- `conflict`
- `adjudication_pending`
- `adjudicated`
- `quality_reviewed`
- `eligible_for_asset`

## 2. 允许迁移

- `pending -> annotated_a`
- `pending -> annotated_b`
- `annotated_a -> independently_double_annotated`
- `annotated_b -> independently_double_annotated`
- `independently_double_annotated -> agreement`
- `independently_double_annotated -> conflict`
- `conflict -> adjudication_pending`
- `adjudication_pending -> adjudicated`
- `adjudicated -> quality_reviewed`
- `quality_reviewed -> eligible_for_asset`

## 3. 禁止迁移

- 直接从 `pending` 跳到 `adjudicated`
- 未 double annotation 就进入 `agreement` 或 `conflict`
- 未 adjudication 就把冲突样本放入正式资产

## 4. 不可覆盖规则

- raw A 不可被 raw B 覆盖
- raw B 不可被 adjudication 覆盖
- adjudication 只能写入独立字段

## 5. LLM Diagnostic Track Fail-Closed Rule

`llm_annotation_track` 可以用于 guideline diagnostic，但不能满足 human evidence gate。

Calibration Round 2 的状态规则：

- 如果 A/B labels 只存在于 combined file，且缺少独立 actor/context/audit provenance，则状态为 `blocked_by_incomplete_annotation`。
- 没有通过 integrity check 的 A/B 不得进入 pre-adjudication agreement。
- 没有通过 integrity check 的 A/B 不得进入 adjudication。
- adjudication 后的统一 gold 不能反向提高 A/B agreement。
- LLM result 必须保留 `actor_type=llm` 与 `human_verified=false`。
- 用户复审后的 LLM diagnostic sidecar 可以标记 `human_verified=true`，但必须同时保留 `formal_human_evidence=false` 与 blocker `not_independent_double_annotation_or_adjudication`。
- 复审后的 diagnostic sidecar 不得替代独立 A/B 标注、pre-adjudication agreement 或 adjudicated gold。
