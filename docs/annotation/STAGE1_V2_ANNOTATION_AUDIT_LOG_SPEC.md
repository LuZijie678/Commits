# Stage1-v2 标注审计日志规范

状态：`audit_log_infrastructure_ready` + `human_execution_pending`

本文档定义 Stage1-v2 annotation event log。audit log 只记录事件，不替代 annotation record 本身。

## 1. 当前文件

- empty event log：
  - `datasets/mica/stage1_v2/campaign/annotation_event_log.jsonl`
- log spec：
  - `datasets/mica/stage1_v2/campaign/annotation_event_log_spec.json`
- implementation：
  - `code/mica/stage1_v2/audit_log.py`

## 2. 事件字段

每个 event 至少包含：

- `campaign_id`
- `batch_id`
- `sample_id`
- `actor_id`
- `actor_role`
- `event_type`
- `old_record_hash`
- `new_record_hash`
- `timestamp`
- `guideline_version`
- `tool_version`

## 3. 事件类型

允许事件：

- `opened`
- `draft_saved`
- `submitted`
- `validation_failed`
- `imported`
- `conflict_detected`
- `adjudication_started`
- `adjudicated`
- `reviewed`
- `superseded`

## 4. Append-only 规则

- 已提交 annotation 不得原地覆盖。
- 修订必须生成新 revision。
- 每次 revision 必须记录旧 record hash 与新 record hash。
- audit log 不得被用作 gold annotation。
- audit log 不得包含另一位 annotator 的结果或模型预测。

## 5. 当前状态

当前 event log 为空，因为人工 campaign 尚未开始。

这表示：

- `calibration_round_complete=false`
- `pilot_double_annotation_complete=false`
- `pilot_adjudication_complete=false`
- `annotation_assets_formal_ready=false`
