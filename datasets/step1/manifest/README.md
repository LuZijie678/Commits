# Step1 Manifest

这里存放 Step1 正式数据的构建与质检说明。

## 当前 live 输入

- `datasets/step1/canonical/annotated_dataset.csv`
- `datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv`
- `datasets/step1/runtime_support/resolved_metadata.csv`
- `datasets/step1/runtime_support/resolved_commit_texts.jsonl`

## 文件口径

- `annotated_dataset_build_report.json`
- `annotated_dataset_materialization_report.json`
- `annotated_dataset_qc_report.json`

上面三份报告已经对齐到当前仓库内的正式路径。

- `dataset_split_report.json`
- `prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint_report.json`

这两份报告保留的是当前 live 数据的历史构建来源，因此会同时引用 `archive/datasets/` 或 `archive/runs/` 中的上游证据文件。它们用于追溯，不是当前 Step1 runner 的默认输入。
