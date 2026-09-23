# Stage1-v2 Qualification 说明

状态：`pilot_material_ready`

## 1. 目的

qualification 用于筛查标注者是否已经理解：

- exact-count 定义
- intent partition 边界
- background 判定

## 2. 公开材料

- `datasets/mica/stage1_v2/qualification/qualification_test.jsonl`
- `datasets/mica/stage1_v2/qualification/annotator_examples.jsonl`

## 3. 私有材料

- `datasets/mica/stage1_v2/qualification/qualification_answer_key_private.jsonl`

私有答案不得进入 annotator public package。

## 4. 评分维度

- exact-k accuracy
- pairwise partition F1
- background classification F1

## 5. 结果解释

- 通过资格测试不等于 final benchmark 标注质量已经合格。
- pilot agreement 仍需独立统计与复核。
