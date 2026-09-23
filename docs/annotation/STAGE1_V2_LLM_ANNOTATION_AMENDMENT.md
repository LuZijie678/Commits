# Stage1-v2 LLM 标注协议修订（llm-annotation-amendment-v1）

状态：`amendment_frozen`
机器可读文件：`configs/mica/protocol_decisions/stage1_v2_llm_annotation_amendment.json`

## 1. 修订内容

经项目负责人（fulin）在 2026-07-26 会话中明确指示，Stage1-v2 标注 campaign 的
annotator_a / annotator_b / adjudicator / independent_blind_reviewer / source_reviewer
角色允许由 LLM actor 执行。本修订建立显式的 **llm_annotation_track**，
不修改、不放松任何 human-track 语义与 gate 阈值。

## 2. 硬性约束

- 所有产出记录 `actor_type=llm`，actor_id 如实标识模型身份。
- `human_verified` 一律保持 `false`；`required_atomic_sources_human_verified`
  不能由 LLM review 满足；`formal_ready` 不因本修订而变为可达。
- A/B 必须由**互不共享上下文**的独立模型会话产出，彼此不可见；
  adjudicator 第三上下文只看分歧项的 raw A/B；blind reviewer 第四上下文不看任何标注。
- annotator/adjudicator/blind-reviewer 上下文禁止读取
  `qualification_answer_key_private.jsonl` 与任何 blinding map。
- qualification 阈值、calibration agreement gates、Go/No-Go 阈值全部不变，照真执行；
  不达标即如实记录 `revision_required` 并停止扩量。

## 3. 证据等级声明

本轨道产出的 agreement 指标测量的是**同一模型家族跨上下文的自洽性**，
不是人类标注者间一致性；模型的相关性错误无法被这些 gate 检测。
所有下游报告与论文必须将这些资产标注为
`llm_annotated_under_amendment (stage1-v2-llm-annotation-amendment-v1)`，
不得表述为人工标注证据。

## 4. 人工升级路径

后续人工标注者可按抽样对 LLM 标注做复核；只有经人工复核的行可置
`human_verified=true` 并升级出 llm track。
