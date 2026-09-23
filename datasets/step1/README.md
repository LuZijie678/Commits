# Step1 Dataset

这是 Step1 的正式数据目录。

## live 结构

- `canonical/`: 正式标注集与正式候选池
- `runtime_support/`: 当前正式运行必需的补全支撑件
- `review/`: 人工标注 / 一致性复核资产
- `manifest/`: 数据构建与质检说明

## 当前正式输入

- `canonical/annotated_dataset.csv`
- `canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv`
- `runtime_support/resolved_metadata.csv`
- `runtime_support/resolved_commit_texts.jsonl`

## 说明

- `runtime_support/` 虽然不是标注集本身，但它是当前 Step1 默认 runner 的正式依赖，不再归入 `workspace/` 语义。
- 历史 upstream 候选池和旧 backfill 工作区已迁到 `archive/datasets/step1/workspace/`。
- 当前 Step1 交付层不在本目录，而在 `datasets/derived/step1_source_pool/current/`。
