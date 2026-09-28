> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# 2026-06-19 MICA Stage2-Stage3 可执行骨架

## 1. 范围

本轮继续补 `P0-5 / P0-6`，但仍然只做 implementation work：

- Stage 2 trainer plan / freeze plan / LR plan / loss routing
- Stage 2 runner executable skeleton
- Stage 3 calibration plan / freeze plan / loss routing
- Stage 3 runner executable skeleton
- Stage 2 / Stage 3 report contract builders

没有运行任何真实训练、正式 validation、final eval 或 runtime experiment runner。

## 2. Stage 2 进展

Stage 2 已从 guarded stub 推进到 executable skeleton：

- 新增统一 training dataclasses 和 batch adapters
- strict replay / hard_b / M weak / real alignment batch semantics 可分别适配
- `M weak` 继续严格保持为 `censored_k_ge_2`
- Stage 2 loss routing 已能按 `source_kind` 选择：
  - strict replay -> Stage 1 `L_main` adapter
  - hard_b -> anti-over-splitting calibration loss
  - M weak -> censored multi-intent loss
  - optional real alignment calib -> guarded adapter path
- freeze strategy / LR plan / checkpoint contract 已具备代码接口

当前 `--train` 路径仍然受 guard 保护，但已经可以做 implementation-level preflight check。

## 3. Stage 3 进展

Stage 3 也已从 guarded stub 推进到 executable skeleton：

- freeze base encoder 计划明确化
- trainable components 限定为轻量 calibration 组件
- strict replay anti-forgetting 接口已接入
- real alignment batch loss routing 已实现
- 缺少 gold alignment 时会产生显式 diagnostic，而不是 silent fail

`M-final-test` 仍然禁止用于 calibration。

## 4. 保留的边界

本轮仍然保持以下边界不变：

1. 不改 Stage 1 core training
2. 不改 `encoder / slot decoder / count head / Hungarian / L_align / L_count / L_exist`
3. `hard_b-test / M-final-test` 不进入训练或 calibration
4. renderer / generation loss 不进入 Stage 2 / Stage 3 attribution
5. consistency 默认关闭
6. 所有训练入口仍需 advisor approval
7. 不生成 runtime outputs，不提交 `outputs/**`

## 5. 当前仍缺少的部分

当前状态仍然不是“真实训练已可直接运行完成”，而是：

- trainer backend 的大规模执行仍未启动
- official Stage 1 validation 仍未运行
- Stage 2 / Stage 3 仍未产生新实验结论
- final eval 仍未运行

下一步应当是在 approval 条件明确后，先跑 implementation check，再逐步接真实 trainer backend 或正式数据路径。
