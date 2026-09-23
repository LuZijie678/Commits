# 真实 Alignment 标注指南

## 目的

本指南定义 MICA 真实 alignment benchmark 的标注协议，用于保证 Stage 3 calibration 与最终 alignment evaluation 可复现，并避免静默混用 calibration 数据和 final-test 数据。

## 必填字段

每一行都必须提供：

- `sample_id`
- `repo`
- `sha`
- `split`
- `annotator_id`
- `annotation_round`
- `edit_units`
- `intent_count`
- `intent_groups`
- `unit_to_intent`
- `created_at`
- `schema_version`

## 建议但非强制字段

- `hunk_to_intent`
- `major_minor_flags`
- `intent_types`
- `intent_subjects`
- `annotator_confidence`
- `uncertain_units`
- `notes`
- `adjudicator_id`

## 核心规则

1. `intent_count` 必须和 `intent_groups` 的数量一致。
2. `unit_to_intent` 必须与 `intent_groups` 保持一致。
3. `hunk_to_intent` 可以缺失，但缺失必须被记为诊断信息，不能被静默忽略。
4. 如果两个标注者在 `intent_count` 上不一致，该样本必须进入 adjudication。
5. 如果两个标注者在 unit grouping 上不一致，该样本必须进入 adjudication。
6. `M-final-test` 行绝不能作为 calibration 数据。

## 标注状态

- `single_annotated`
- `double_annotated`
- `adjudicated`

其中 `adjudicated` 的行必须记录 `adjudicator_id`。

## Benchmark Gate

在对 real-alignment 作较强主张之前，建议至少满足：

- `>= 300` 条完整 alignment commit
- `>= 100` 条 final-test aligned commit
- `>= 100` 条 double-annotated commit

如果达不到这些门槛，benchmark 的主张级别应降为：

- `preliminary_attribution_only`

## 数据边界

- calibration 数据和 final-test 数据必须严格分离。
- `M-final-test` 是 eval-only。
- final-test 行绝不能用于 threshold tuning、pseudo-labeling 或 filtering。
