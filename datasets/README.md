# Datasets

这是当前仓库中 Step1 / Step2 的正式数据根。

## live 目录

- `step1/`: Step1 正式输入、运行支撑件、人工复核与 manifest
- `step2/`: Step2 正式 few-shot 候选、复核表、交付层
- `m_verified/`: Step2 few-shot 的正式 `M` 类来源资产
- `hard_b/`: 边界样本 / 难负例资产
- `derived/`: 跨阶段正式交付层

## 当前主链路

```text
datasets/step1/canonical + datasets/step1/runtime_support
  -> Step1 formal run
  -> datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv
  -> datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv
  -> Step2 main pipeline

datasets/m_verified/canonical/usable_m_with_real_diff.csv
  -> datasets/step2/review/m_only_review_sheet.csv
  -> datasets/step2/delivery/current/fewshot_pool.db
```

## archive 口径

- 不再参与当前主链路运行的历史工作区，已迁到 `archive/datasets/`
- 当前不要把 `archive/datasets/` 当作默认 live 输入

## 就绪检查

```bash
make datasets-check
```

这会刷新 `manifests/local_asset_status.json`，并检查当前完整运行 Step1 / Step2 所需的 live 数据是否齐全。
