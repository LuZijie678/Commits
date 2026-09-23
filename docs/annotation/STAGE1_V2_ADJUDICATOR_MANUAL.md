# Stage1-v2 裁决手册

状态：`pilot_material_ready`

## 1. 裁决职责

裁决人只处理：

- A/B exact-k 冲突
- unit-level assignment 冲突
- background / shared / mixed / uncertain 分类冲突

## 2. 裁决原则

- 优先依据 guideline，而不是个人偏好。
- 不因“想让模型更好学”而改写 gold。
- 不得读取模型预测或官方结果。
- 必须保留 raw A/B，不能覆盖。

## 3. 裁决输出

每条冲突记录必须补齐：

- `adjudicator_id`
- `adjudicated_annotation`
- `adjudication_reason`
- `guideline_version`
- `timestamp`

## 4. 何时标记 out-of-scope

以下情况可在裁决中建议 future stress set / overflow：

- `k > Kmax`
- release aggregation
- mass refactor
- 纯机械大提交
- evidence 边界无法通过现有 unitization 稳定表达
