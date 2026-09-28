# 当前项目状态入口（2026-09-28 核对）

本页区分**新仓库当前可见的证据**与旧分支的历史运行记录。它不是一次新实验，也不改变任何冻结结果。后续若新增实验，应以新的运行产物、哈希和审核结论更新本页；不要把历史文档中写的“当前”直接当作今天的状态。

## 实验与证据边界

- Stage1-v1：历史正式运行的内部状态修订曾为 `paper_ready=true`，但[独立审计](MICA_STAGE1_INDEPENDENT_AUDIT.md)给出 `NO_GO_STAGE2`；[审计状态记录](../configs/mica/official_results/stage1_v1_audit_status.json)将其外部论文证据降为 `pilot_only`。内部验收与科研有效性是不同判断，不能用前者覆盖后者。
- Stage1-v2：[数据与标注执行说明](MICA_STAGE1_V2_DATA_AND_ANNOTATION_EXECUTION.md)和[readiness 记录](../datasets/mica/stage1_v2/readiness/stage1_v2_annotation_readiness.json)均显示 `stage1_v2_training_allowed=false`、`stage2_entry_allowed=false`。候选/试运行资产已物化，但人工标注和正式训练仍未完成。
- Step2：2026 年 5 月 fullscale 运行的汇总与状态文件已随[历史实验文件补充](EXPERIMENT_ARTIFACT_RECOVERY.md)进入 Git；完整样本 JSONL 已[在新工作目录本机补回](LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md)，但仍未进入 GitHub，不能据此声称新克隆具备完整逐行复核材料。
- 更早的 [2026-06-14/15 Stage1 观察记录](records/archive/2026-06-14-mica-stage1-attribution-experiment-observations.md)指向 11 个旧 macOS 临时目录中的原始指标文件；在新、旧本地目录均未找到。其中 6 份 staged 指标内容可从保存的汇总报告[重建为带来源标记的副本](LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md)，另 5 份 sanity 只剩部分摘要；原件均未找回。
- Stage1-v1 官方输出存在一处 manifest 哈希登记与最终文件不一致。[哈希核查说明](STAGE1_OFFICIAL_MANIFEST_HASH_AUDIT.md)已确定这是运行程序的自引用写入顺序造成；原始记录保持不变，不能宣称原始 13 项哈希表全部匹配最终文件。

## 如何读旧文档

- [MICA 实现状态与方案差距](MICA_CURRENT_STATE_AND_PLAN_GAP.md)、[数据卡](DATA_CARD.md)、[Stage1-v1 独立审计](MICA_STAGE1_INDEPENDENT_AUDIT.md)及 `docs/records/` 下的“当前分支”“当前结果”，均须按各自记录日期理解。
- 旧分支名与 Git SHA 是**历史来源标识**，不是新仓库 `main` 的可解析提交；新仓库的首次导入不会自动带入旧 Git 历史。
- GitHub 上的新仓库只包含部分历史运行输出；本机新工作目录另有六份被忽略的大型逐行文件。缺失范围与保存状态见[本机补回记录](LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md)。

本页不替代协议、原始结果或人工审批；任何“可以训练 / 可以进入 Stage 2 / 可以用于论文”的新结论，都需要对应 gate 和证据更新。
