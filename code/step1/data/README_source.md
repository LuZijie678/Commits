# data 目录说明

这个目录已退役，不再作为 Step1 的活跃运行数据根。

当前正式数据已迁移到：

- `../../datasets/step1/canonical/`
- `../../datasets/step1/manifest/`
- `../../datasets/step1/review/`
- `../../datasets/step1/workspace/`

## 当前主入口

- 当前 `code/step1/data/` 只保留迁移说明文件。
- 任何仍然引用 `code/step1/data/...` 的旧文档，都应按下列映射理解：
  - `code/step1/data/annotated_dataset.csv` -> `../../datasets/step1/canonical/annotated_dataset.csv`
  - `code/step1/data/prefilter_allcommits.csv` -> `../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv`
  - `code/step1/data/allcommits_local_backfill/...` -> `../../datasets/step1/runtime_support/...`
