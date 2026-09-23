> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-19 MICA Integration Hardening

本轮不是继续横向加功能，而是把前几轮已经实现的 Stage 0/1/2/3/4、baseline、eval、paper table、null slot、cardinality warmup、consistency、evidence graph、provenance 等模块做一次 integration hardening。

## 本轮做了什么

1. 增加跨阶段 schema 校验：
   - Stage 1 prediction
   - `AttributionPrediction`
   - `StructuredIntentPlan`
   - renderer input
   - `TrainBatch`
   - eval payload
   - paper table row

2. 增加统一 config loader / family validator：
   - 聚合 stage1/2/3/4 warnings
   - 检查 final-test eval-only
   - 检查 consistency 默认关闭
   - 检查 forbidden attribution loss（`L_multi` / `L_gen` / `L_faith`）

3. 增加 runner registry：
   - 集中登记 stage / purpose / approval gate / final-test policy / API policy / attribution-update policy。

4. 增加 metric registry：
   - 对齐 eval runner 与 paper table 所用指标键。

5. 把 experiment manifest / report schema 接入真实入口：
   - Stage 0
   - Stage 1 official validation
   - Stage 2 calibration
   - Stage 3 alignment calibration
   - real-domain eval
   - alignment eval
   - message utility eval

6. 把 Stage 1/2/3 config family 与 P2 core-method config 接通：
   - `null_slot`
   - `dual_cardinality`
   - `assignment_schedule`
   - `evidence_graph`
   - `consistency`

## 本轮没有做什么

- 没有运行 Stage 1 validation
- 没有运行 Stage 2/3/4 training
- 没有运行 final eval
- 没有运行 anti-shortcut / OOD model rerun
- 没有生成 runtime predictions / plans / rendered messages
- 没有修改 `outputs/**`

## 主要收口效果

### schema 闭环

不再是“某个模块自己定义一份输入格式”，而是通过 `schema_validation.py` 把：

- prediction
- plan
- renderer input
- train batch
- eval payload
- paper table row

放进统一校验。

### config 闭环

不再是每个 stage 只做局部检查，而是通过 `config_loader.py` + `config_validation.py` 形成 family 级校验。

### runner 闭环

不再是 runner 只返回 ad hoc json；现在核心 runner 会带：

- `experiment_manifest`
- `report_schema`
- runner policy 对应的 safety semantics

### metric 闭环

paper table 与 eval runner 现在共享 metric registry，避免键名漂移和 proxy 标记丢失。

## 结论

本轮完成的是 integration hardening，而不是新增孤立模块。当前代码库的主要结构性闭环已经形成：

- schema
- config
- runner policy
- metric registry
- experiment manifest
- report schema

后续再进入真实实验时，主要剩余工作会转向：

1. 补真实 asset registry path；
2. 在 advisor approval 条件满足后运行 staged experiments；
3. 处理真实数据与 benchmark 的执行级问题，而不是继续搭接口。
