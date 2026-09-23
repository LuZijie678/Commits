# Stage1-v2 标注 Campaign 操作指南

状态：`annotation_campaign_prepared` + `human_execution_pending`

本文档说明如何执行 Stage1-v2 人工标注 campaign。它不是人工标注结果，也不是标注质量通过证明。

## 1. 当前 campaign 资产

- campaign manifest：
  - `datasets/mica/stage1_v2/campaign/annotation_campaign_manifest.json`
- batch schedule：
  - `datasets/mica/stage1_v2/campaign/annotation_batch_schedule.json`
- progress：
  - `datasets/mica/stage1_v2/campaign/annotation_campaign_progress.json`
- role assignment：
  - `datasets/mica/stage1_v2/campaign/campaign_role_assignment.json`
- role conflict report：
  - `datasets/mica/stage1_v2/campaign/role_conflict_report.json`

当前 batch 总数：`10`。当前已完成人工样本数：`0`。

## 2. 角色约束

正式 campaign 至少需要：

- `annotator_a`
- `annotator_b`
- `adjudicator`
- `independent_blind_reviewer`

约束：

- 同一样本的 A 和 B 必须是两个独立人类。
- adjudicator 不能伪装成第二个独立标注者。
- blind reviewer 不应查看模型输出、原裁决理由或原标注者身份。
- Codex、LLM、AI agent 或模型输出不能注册为正式 annotator、adjudicator 或 blind reviewer。
- AI 生成内容只能作为 diagnostic suggestion，不能进入 gold。

当前状态：

- `human_staffing_incomplete=true`
- `annotation_campaign_blocked=true`

## 3. 本地 CLI

当前轻量 CLI：

- `code/mica/stage1_v2/annotation_cli.py`

支持动作：

- 查看单个 sample 的盲化 diff / edit units。
- 初始化 annotation draft。
- 校验 draft schema。
- 提交并锁定 annotation revision。
- 写入 append-only audit log。

CLI 不显示：

- commit message
- PR title
- issue text
- model prediction
- weak label
- predicted k
- split 名称
- 另一位 annotator 的结果

提交后不得原地覆盖 completed record；修改必须生成新 revision。

## 4. 执行顺序

1. 完成人员注册与 role assignment。
2. 对 annotator A/B 执行 qualification test。
3. 只有资格测试达标后，才能开始 calibration round。
4. calibration round 1 完成 A/B 独立双标。
5. 计算 pre-adjudication agreement。
6. 若 agreement gate 不达标，修订 guideline 并重训。
7. 若 agreement gate 达标，人工确认 guideline 进入 pilot-ready。
8. 执行 pilot batch 2 和 batch 3。
9. 对冲突样本导出 adjudication queue。
10. 导入裁决结果并生成 post-adjudication quality report。

## 5. 当前禁止事项

- 不得自动填写 exact k。
- 不得自动填写 unit partition。
- 不得用 weak label 派生 gold。
- 不得让 Codex/LLM 代替人工标注。
- 不得将 calibration 或 pilot 结果直接当作 final benchmark。
- 不得启动 Stage1-v2 training。
- 不得启动 Stage 2。
