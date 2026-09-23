# Step2 Dataset

这是 Step2 的正式数据目录。

## live 结构

- `candidate_sources/`: few-shot 候选全集与候选报告
- `review/`: few-shot 人工复核表
- `delivery/current/`: 当前正式 few-shot 交付层
- `notes/`: 少量保留的复核说明

## 当前正式 few-shot 入口

- `delivery/current/fewshot_pool.db`
- `delivery/current/build_manifest.json`
- `delivery/current/preflight_report.json`

## 使用口径

- Step2 主流程默认消费 `datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- Step2 默认 few-shot 资产默认消费 `delivery/current/`
- `code/step2/fewshot待制备/` 已退役为迁移说明入口，不再承载 live formal 数据

## 说明

- `candidate_sources/` 和 `review/` 是当前 few-shot 正式交付的上游证据层
- `delivery/current/` 是当前默认正式资产层
- 如需追溯旧代码树内的 few-shot delivery，请看 `archive/datasets/step2/legacy_code_tree_delivery/`
