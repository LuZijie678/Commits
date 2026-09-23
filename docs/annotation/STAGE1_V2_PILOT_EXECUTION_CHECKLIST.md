# Stage1-v2 Pilot 执行检查单

状态：`pilot_execution_ready`

## 1. 标注前

- protocol version 已确认：`stage1-v2-protocol`
- guideline version 已确认：
  - `stage1-v2-count-guideline-pilot-v1`
  - `stage1-v2-alignment-guideline-pilot-v1`
- annotator package 已盲化
- qualification 已完成
- pilot sample 不在未来 final benchmark freeze 集合内

## 2. 标注中

- annotator A/B 独立作业
- 不查看模型预测
- 不查看 commit message / PR / issue
- 不修改 sample ID / unit ID

## 3. 标注后

- 导入 A/B 结果
- 运行 pre-adjudication agreement
- 导出 adjudication queue
- 导入 adjudicated result
- 导出 blind review sample
- 生成 post-adjudication quality report

## 4. 当前不能做的事

- 冻结 final benchmark
- 冻结 Kmax 真实 count asset
- 启动 Stage1-v2 训练
- 进入 Stage 2
