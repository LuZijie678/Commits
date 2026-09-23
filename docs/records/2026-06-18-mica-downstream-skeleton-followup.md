> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-18 MICA Downstream Skeleton Follow-up

## 1. Purpose

本文档记录的是在 `954ef07 chore: add isolated MICA downstream skeleton` 基础上的 follow-up 实现。

这一轮的目标不是调参，不是正式 `Stage 2`，不是 generation 主实验，也不是改 `core training`。目标只是把 downstream offline skeleton 从“有基本接口”推进到“可以离线 smoke / 可批量转换 / 可做 dry-run 检查”。

## 2. What Was Added

本轮新增和增强了以下能力：

- `code/mica/io_utils.py`
  - 标准库 JSON / JSONL I/O
  - 显式 path
  - output-root 辅助
- `code/mica/plan_builder.py`
  - 支持 prediction jsonl 批量转 `StructuredIntentPlan`
  - 支持 embedded edit units 与 separated edit units 两种模式
  - 支持 summary / diagnostic histogram
- `code/mica/renderers/deterministic.py`
  - 支持 plan jsonl 批量渲染
  - 支持 renderer summary
- `code/mica/runners/run_plan_renderer_smoke.py`
  - 新增 offline smoke runner：
    - prediction -> plans -> deterministic messages
  - 只做离线转换
- `code/mica/runners/run_official_stage1_validation.py`
  - 增强可选 `plan_smoke_check`
  - 但仍然只是 dry-run / readiness
- `code/mica/runners/audit_future_stage2_inputs.py`
  - 增强 future Stage 2 输入字段审计
  - 新增 train/calibrate/pseudo-label guard

## 3. What This Still Does Not Mean

这一轮实现仍然不代表：

- official Stage 1 validation 已执行；
- Stage 1 已正式通过；
- generation 主实验已经开始；
- renderer training 已开始；
- Stage 2 已经开始；
- `hard_b / M` 已经进入训练或校准。

当前准确说法仍然是：

> downstream offline smoke pipeline is available, but remains isolated from the active Stage 1 mainline.

## 4. 为什么这仍然是安全的

这一轮继续保持了上一轮的隔离原则：

1. 不改 Stage 1 训练逻辑；
2. 不改 Stage 1 reports 链路；
3. 不改 generation pilot；
4. 所有新 runner 都必须显式 CLI 参数；
5. 不显式 `--smoke-only` / `--dry-run` / `--validate-only` / `--audit-only` 就 fail fast；
6. 不调用 verifier / retrieval / LLM API；
7. 不读取 `hard_b / M / RealDomainBinary` 后进入训练；
8. 不新增 loss；
9. 不改变当前实验结论。

## 5. Relationship to MICA-v3 Trainable Algorithm

这一轮做的是对 MICA-v3 trainable algorithm 的 **implementation-side preparation**：

- M4 `StructuredIntentPlan` builder：有了 batch/offline path；
- M5 deterministic evidence-locked renderer：有了 batch/offline path；
- future Stage 2 audit：只保留输入边界与 guard，不做训练；
- official Stage 1 validation runner：仍停留在 readiness / smoke 层，不做正式指标结论。

换句话说，本轮只把后续链路的工程接口补齐，没有越过当前 scientific boundary。

## 6. Remaining Advisor Decisions

以下问题仍然没有解决，仍然保留为 unresolved spec：

1. formal validation thresholds；
2. repo overlap 是否可接受；
3. repo-disjoint diagnostic 是否需要先做；
4. no-slot / flat baseline 是否需要加入；
5. anti-shortcut 的时机；
6. real alignment benchmark 的标注方案；
7. Stage 2 unlock criteria。

因此，本轮依然严格遵循：

> advisor-unconfirmed questions remain unresolved and are not encoded as final scientific conclusions.
