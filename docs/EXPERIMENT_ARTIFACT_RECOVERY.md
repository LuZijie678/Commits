# 补充缺失的历史实验文件

本次提交从本地旧工作目录补入新仓库首次导入时未包含的关键实验文件。它是**历史文件补充**，不是一次新的训练或验证，也不改变 Stage1-v1 独立审计的 `pilot_only` / `NO_GO_STAGE2` 结论。当前 Stage1-v2 的训练与 Stage2 进入条件仍以 `MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md` 为准。

## 本次纳入 Git 的范围

- `outputs/mica_*/` 下的 72 个 Stage 0 / Stage 1 文件：训练 checkpoint、阈值选择、候选验证、官方验证、预检、摘要和元数据；不含两份大型 `kmax_exact_count_rows.jsonl` 及 macOS Finder 的 `.DS_Store`。
- `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/` 下的 `fullscale_summary.json`、`fullscale_summary.md`、`runtime_state.json`。这些是历史 Step 2 运行的汇总与状态，不是完整的生成样本。
- `configs/mica/data_asset_materializations.example.json` 提供相对路径和预期哈希的示例。实际 `configs/mica/data_asset_materializations.local.json` 仍由本机维护，按 `.gitignore` 不提交。新克隆中需要用示例复制出 `.local.json` 后再做本机校验；示例里的 Git SHA 是旧工作目录的历史来源，不是新仓库提交号。

本次纳入的 75 个实验文件合计约 27 MiB；从旧目录复制后逐个计算 SHA-256，复制前后完全一致。Stage 1 clean checkpoint 的 SHA-256 为 `4c292e0b4f6d7e2b0a291fd9ab1117552922076f3ffb6b28eff06484c33f8c11`，与 checked-in logical registry 及本地 materialization 登记一致。

## 已知校验例外

`configs/mica/official_results/stage1_official_validation_20260723T091921Z.json` 列出 13 个官方验证输出文件的预期哈希。本地旧工作目录中这 13 个文件都存在；其中 12 个 SHA-256 一致，但 `stage1_official_validation_manifest.json` 的预期哈希 `32943fae2925943aa183a7404da4e6546fa4a11dc231e65d007cad3f4d482e49` 与实际哈希 `e0fa6c3c4a32f638a0257203ed360a4e29d1c99bd15eee378f02536ef13e808b` 不一致。本次保留原文件，不改写结果记录，也不声称整套官方输出已通过完整一致性校验；后续需调查差异原因。

## 仍未纳入 Git 的文件

- 两份约 899 MiB 的 `kmax_exact_count_rows.jsonl` 审计逐行数据；其余 Kmax 报告和队列文件已纳入。
- Step 2 该次运行中的完整生成样本及预检拒绝样本（`synthetic_samples*.jsonl`），以及分片运行目录；历史文档指向这些文件的链接在新克隆中仍不能打开。
- `datasets/step1/runtime_support/resolved_commit_texts.jsonl`（本地约 2.9 GB，超过 GitHub Free 的 LFS 单文件 2 GB 上限）、`archive/runs/` 的大型历史运行目录、缓存、临时文件和凭据。

这些未上传文件仍在本地旧工作目录中。不要把旧目录整体加入 Git，也不要上传 `.github_token`、`.llm_api_key` 或含密钥的本机配置。若未来需要完整归档，应先确认数据许可、隐私、存储额度及文件哈希，再选用适合大型科研数据的存储方式。
