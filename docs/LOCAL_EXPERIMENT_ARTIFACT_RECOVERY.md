# 历史实验原始文件：本机补回与剩余缺口（2026-09-28）

本记录区分**新工作目录中的本机文件**和**GitHub 上可克隆的文件**。本次只从 `D:/BaiduNetdiskDownload/Commits/Commits/` 复制，不删除旧目录，不重新运行实验，也不把原始数据公开上传。六份文件已原样补到 `D:/BaiduNetdiskDownload/Commits/Commits-LuZijie678/` 的同名相对路径；逐份核对源、目标 SHA-256 一致。它们按 `.gitignore` 保持本机专用，因此普通 `git clone` **仍不会得到**这些文件。

## 已在新工作目录补回的六份文件

| 相对路径 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `outputs/mica_stage1_clean_candidate_20260723T081816Z/kmax_audit/kmax_exact_count_rows.jsonl` | 942771385 | `0ae284ea14e0f5558c73031c660e31fa7d3c30be3c9ce3a60dc24294c02bca5d` |
| `outputs/mica_kmax_exact_count_audit_20260723T073600Z/kmax_exact_count_rows.jsonl` | 942770385 | `6cf1f7dbf4bfadd46107928d82a43ceb4e5d890d800c7c59200b96c94fa06a89` |
| `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl` | 678712402 | `ee22136e82f7410202e89535f02c3080fe3013967721e67554c68b6464ea0db3` |
| `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl` | 461369830 | `203f201b1c81c96b95e2d85b74bdc016818cdc3ff2c00c8ecc0f77e460ed96f4` |
| `code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl` | 28938440 | `82e188d314c7ddffd71b875dbf92f6ae664df626972e8f8c82773b073abcac74` |
| `datasets/step1/runtime_support/resolved_commit_texts.jsonl` | 2903806661 | `2e43e4abc06a2dd110b68d99fb7814246e6e428d1d91346c07172f24da6e0bbc` |

合计 `5958369103` 字节（约 5.55 GiB）。其中包含仓库名、提交文本、`git_diff`、合成 diff 等字段；公开发布前须确认第三方代码/数据许可、隐私和项目授权。本机复制不是异地备份：旧目录和新目录都在 D 盘。

## 确实无法从现有两处目录原样补回的文件

[2026-06-14/15 Stage1 历史观察记录](records/archive/2026-06-14-mica-stage1-attribution-experiment-observations.md)引用 5 份 sanity `metrics.json` 和 6 份 staged-curriculum `*_metrics.json`，原路径在旧 Mac 的 `/private/tmp/Commits-mica-v3-attribution-mvp/`。按相对路径检查，11 份在现存旧目录、新工作目录均不存在；无法恢复它们的原始字节和 SHA-256。

其中 6 份 staged-curriculum 指标对象仍完整嵌在已提交的 `reports/mica_stage1_staged_curriculum_result.json` 的 `settings[0..5]` 中。根据当时[运行代码](../code/mica/train/run_stage1_staged_curriculum.py)的写入顺序，逐项指标文件和汇总报告使用同一个 `result_row` 对象及相同 JSON 序列化格式。因此已用[恢复脚本](../scripts/recover_stage1_staged_metrics_from_report.py)生成 6 份 **`*.reconstructed.json`** 和[来源清单](../recovered_artifacts/stage1_staged_curriculum_20260615T023159Z/RECOVERY_MANIFEST.json)。它们可以用于复核报告中的指标内容，但原始文件及其哈希不存在，不能宣称已找回原件或证明字节完全一致。

另 5 份 sanity `metrics.json` 没有发现可一一对应的完整对象；`reports/mica_stage1_sanity_result.json`、`reports/mica_stage1_attribution_debug.json` 和历史文字记录只保留了部分数值。不能把历史表格中的四舍五入数值写成同名“原件”。根据[证据使用决定](LEGACY_STAGE1_SANITY_EVIDENCE_DECISION.md)，它们不是当前正式实验的放行必需项，暂不为补旧文件而重跑。

如需继续研究，应：

1. 把 11 份原始文件在证据目录中标为 `original_runtime_artifact_missing`；6 份 reconstructed 文件明确引用来源报告，5 份 sanity 仅引用现存的部分摘要，不把两者混同。
2. 若将来的新论文设计必须检验这些早期假设，而当前 Stage1-v2 实验无法覆盖，则根据旧 Git 历史、保存的配置/报告和现存输入，在独立目录**重新运行**；使用新 run ID、环境、随机种子和文件哈希记录结果。重跑结果属于新证据，不得覆盖或冒充 2026-06-14/15 原件。
3. 若无法重跑或仍缺必要输入，则不把依赖这 11 份原始文件的细节作为可复核的正式证据；保留为历史探索记录。

## 仅有 GitHub + D 盘时的持久保存方案

GitHub [普通仓库拒收大于 100 MiB 的文件](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。GitHub Free 的 [LFS 单文件上限为 2 GiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)，因此最后一份约 2.70 GiB 文件不能原样进入 LFS。LFS 还受账户存储和下载额度约束，不能仅凭文件尺寸推定该账户有足够余额。

若项目负责人确认可以公开这些原始 diff 和提交文本，可考虑单独发布一个**版本化 GitHub Release**：六份数据作为 Release assets，不进入 Git 历史；最后一份先拆成小于 2 GiB 的有序分卷，并发布每卷及整文件的 SHA-256、字节数和合并说明。GitHub 文档称 [单个 Release asset 须小于 2 GiB，单次 Release 无总大小限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。上传后要从下载端验证分卷和重建文件的哈希，再在仓库中记录固定 Release 版本链接。未经数据权利与隐私确认，不应公开发布。

若不允许公开，保持这六份为本机受限数据，另需由项目负责人指定受控存储或离线备份；同一 D 盘上的两份副本不算可靠灾备。不要把个人网盘链接写成论文中的永久数据标识。
