# Stage1-v2 标注者培训手册

状态：`pilot_material_ready`

## 1. 使用对象

- RealCount pilot 标注者
- Real-Adjudicated pilot 标注者

## 2. 工作顺序

1. 阅读：
   - `docs/annotation/STAGE1_V2_COUNT_GUIDELINE_PILOT_V1.md`
   - `docs/annotation/STAGE1_V2_ALIGNMENT_GUIDELINE_PILOT_V1.md`
   - `docs/annotation/STAGE1_V2_BACKGROUND_ANNOTATION_GUIDELINE.md`
2. 完成 qualification test。
3. 通过资格阈值后，领取 annotator package。
4. 独立完成标注，不与另一位标注者交流具体样本。
5. 导入结果，等待 agreement / adjudication。

## 3. 禁止事项

- 不得查看模型预测。
- 不得使用原始 commit message、PR title、issue text。
- 不得查看另一位标注者结果。
- 不得修改 package 中的 sample ID、unit ID、guideline version。

## 4. 资格阈值

- `exact_k_accuracy >= 0.85`
- `pairwise_partition_f1 >= 0.80`
- `background_classification_f1 >= 0.85`

## 5. 交付要求

导入文件必须保留：

- annotator ID
- sample ID
- guideline version
- annotation version
- 时间戳

不得直接交付裁决后的结果文件。
