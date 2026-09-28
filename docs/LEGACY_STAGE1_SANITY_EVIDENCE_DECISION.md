# 五份早期 Stage1 sanity 指标的证据使用决定（2026-09-28）

## 决定

**目前不重跑这五轮实验，也不伪造或重建同名 `metrics.json`。**五份原始文件在现存旧目录和新工作目录均不存在；只保留[历史观察记录](records/archive/2026-06-14-mica-stage1-attribution-experiment-observations.md)中转录的部分指标，标记为“历史探索 / 原件缺失 / 无法逐项复核”。它们不作为当前正式结果表、论文主结论或 Stage1-v2/Stage2 放行依据。

涉及的运行编号：`20260614T062358Z`、`20260614T063849Z`、`20260614T064442Z`、`20260614T064731Z`、`20260614T083245Z`。

## 判断依据

1. 这些运行只在 2026-06-14 的[归档观察记录](records/archive/2026-06-14-mica-stage1-attribution-experiment-observations.md)中按编号引用；对当前 Git 跟踪文件的检索未发现正式结果记录、Stage1-v2 readiness、独立审计或运行入口依赖这五个编号。
2. 归档表格把五轮全部标为 `inconclusive`，用途是说明早期 attribution/slot-collapse 的调试现象；表格中的数值经过四舍五入，不能替代完整 `metrics.json`。
3. 后续的[Stage1-v1 独立审计](MICA_STAGE1_INDEPENDENT_AUDIT.md)已有单独的 `NO_GO_STAGE2` 结论；[审计状态记录](../configs/mica/official_results/stage1_v1_audit_status.json)将 v1 外部论文证据限定为 `pilot_only`。这五份早期 sanity 文件的缺失既不会改变该审计，也不能通过重跑解除审计中的 P0 问题。
4. [Stage1-v2 readiness](../datasets/mica/stage1_v2/readiness/stage1_v2_annotation_readiness.json)仍是 `stage1_v2_training_allowed=false`、`stage2_entry_allowed=false`，其阻塞条件是当前资产和人工标注等，不是找回 2026-06-14 的 sanity 输出。

旧本地 Git 历史中有部分 `reports/mica_stage1_sanity_result.json` 的早期版本，但它们是摘要，不是这五份逐次 `metrics.json` 的完整原件。六份 staged-curriculum 指标的[报告衍生重建](LOCAL_EXPERIMENT_ARTIFACT_RECOVERY.md)属于另一组文件，不适用于这五轮。

## 允许与禁止的用法

- 可用于解释项目早期为何调整 count/existence coupling 或关注 slot collapse，但引用时必须注明“来自历史文字记录，原始逐次指标缺失”。
- 不得把历史表格数值补写成新的原始 `metrics.json`，不得声称五轮能独立复核，也不得作为论文主表、正式消融、强基线优势或 Stage 2 放行证据。

## 何时重新做实验

只有在新的论文设计**确实需要**回答这五轮涉及的具体假设（例如 count/existence coupling 对 attribution 的影响），且现有 Stage1-v2 方案中的实验不能覆盖时，才安排新实验：先确定现在有效的协议、数据划分、人工标注、基线和评估标准，再用独立的新 run ID、代码版本、环境、随机种子、输入/输出哈希记录。新实验回答当前问题，**不替代 2026-06-14 的原件**。在此之前，优先推进 Stage1-v2 的实际阻塞项。
