> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# 2026-06-18 MICA 下游 Skeleton 实现

## 1. 为什么可以在导师回复前先实现

当前 `Stage 1` 还存在多项待导师确认的问题，包括：

- formal validation 阈值是否沿用当前 sanity 阈值；
- synthetic split 是否允许 repo overlap；
- 是否要补 repo-disjoint diagnostic；
- 是否要补 flat classifier / no-slot decoder baseline；
- anti-shortcut 的时机；
- real alignment benchmark 的标注方案；
- Stage 2 的解禁条件。

这些问题都属于 **scientific protocol / evaluation policy**，不是后续代码骨架必须立即拍板的工程前置条件。

因此本轮工作的原则是：

> 先把后续模块的输入输出接口、旁路 runner 和隔离测试搭好；  
> 但不把导师尚未确认的科学决策写死成正式执行逻辑。

## 2. What Was Added

本轮新增的能力全部位于 `code/mica/` 的旁路模块中：

- `schemas.py`
  - 定义 `EditUnitRecord`
  - `AttributionSlot`
  - `AttributionPrediction`
  - `StructuredIntent`
  - `StructuredIntentPlan`
  - `StageRunManifest`
  - `DegradationDiagnostic`
- `plan_builder.py`
  - 将 Stage 1 attribution 输出转换为 `StructuredIntentPlan`
  - 支持 degraded diagnostics
- `renderers/deterministic.py`
  - 只基于 structured plan 渲染保守 message
  - 不读取 full raw diff
  - 不调用 LLM / retrieval / verifier
- `runners/run_official_stage1_validation.py`
  - 当前只实现 dry-run / readiness check
  - 不训练
- `runners/audit_future_stage2_inputs.py`
  - 当前只做未来 Stage 2 输入审计
  - 不训练
  - 不 pseudo-label

同时新增：

- `configs/mica/stage1_protocol_spec.json`
- `configs/mica/stage1_metric_thresholds.json`
- `configs/mica/unresolved_questions.json`

## 3. Isolation Guarantees

本轮新增模块全部满足以下隔离约束：

1. 不修改现有 `Stage 1` 训练逻辑；
2. 不修改现有 `Stage 1` reports 生成逻辑；
3. 不修改现有 generation pilot 流程；
4. 不实现 `Stage 2` 训练；
5. 不读取 `hard_b / M / RealDomainBinary` 后开始训练；
6. 不实现 verifier / retrieval / real API；
7. 不新增主 loss；
8. 不修改 encoder / slot decoder / count head / Hungarian / `L_align/L_count/L_exist`。

这些新模块默认都不会被旧脚本自动调用。

## 4. What The New Modules Explicitly Do Not Mean

需要避免误读：

- `StructuredIntentPlanBuilder` 的加入，不等于 generation 实验已经开始；
- deterministic renderer 的加入，不等于已经开始 renderer 训练；
- official Stage 1 validation runner 的加入，不等于已经开始 official validation；
- future Stage 2 audit runner 的加入，不等于已经进入 Stage 2。

当前准确说法是：

> downstream skeleton is implemented, but remains isolated from the current Stage 1 mainline.

## 5. Current Status of Stage 2

Stage 2 仍未进入。

在新增的 protocol spec 和 audit runner 中，仍明确保持：

- `stage2_allowed = false`
- `stage2_training_enabled = false`
- `requires_stage1_official_validation = true`

也就是说，本轮只是为未来接口做准备，不改变当前项目阶段。

## 6. Remaining Unresolved Decisions

本轮代码没有替导师做决定，以下问题仍保留在 `configs/mica/unresolved_questions.json` 中：

1. formal validation 阈值是否沿用当前 sanity 阈值；
2. Stage 1 synthetic split 是否允许 repo overlap；
3. 是否需要 repo-disjoint diagnostic；
4. 是否需要 no-slot / flat baseline；
5. anti-shortcut 何时做；
6. real alignment benchmark 如何标注；
7. Stage 2 的解禁条件是什么。

这些问题目前仍然是 **unresolved spec**，不是已写死的科学结论。
