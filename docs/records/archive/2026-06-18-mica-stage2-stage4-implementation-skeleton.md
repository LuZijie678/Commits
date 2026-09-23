> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-18 MICA Stage2-Stage4 实现骨架

## 1. Purpose

本轮修正了“后续实现只局限在 Stage 1”的理解偏差。

根据 `MICA_v3_trainable_algorithm_plan` 的 staged protocol，本轮开始补齐：

- Stage 2 real-domain count calibration skeleton
- Stage 3 real alignment calibration skeleton
- Stage 4 evidence-locked renderer training skeleton
- downstream evaluation / baseline / anti-shortcut / readiness code skeleton

这些实现都保持 gated / opt-in，不会默认启动，也不会覆盖已冻结的 Stage 1 主线。

## 2. What Was Added

- Stage 2
  - `stage2_losses.py`
  - `stage2_mixture.py`
  - `run_stage2_calibration.py`
- Stage 3
  - `real_alignment.py`
  - `run_stage3_alignment_calibration.py`
- Stage 4
  - `renderer_dataset.py`
  - `renderer_losses.py`
  - `stage4_renderer_training.py`
  - `run_stage4_renderer_training.py`
- Evaluation
  - `real_domain_detection.py`
  - `message_utility.py`
  - `calibration_metrics.py`
  - `ood_stress.py`
- Config
  - `stage2_calibration_spec.json`
  - `stage3_alignment_calibration_spec.json`
  - `stage4_renderer_spec.json`
  - `eval_real_domain_spec.json`
  - `eval_alignment_spec.json`
  - `eval_message_utility_spec.json`

## 3. Guardrails Kept

本轮继续保持以下边界：

1. 不改 Stage 1 core training
2. 不改 `encoder / slot decoder / count head / Hungarian / L_align / L_count / L_exist`
3. `hard_b-test / M-final-test / RealDomainBinary test` 不进入训练
4. `M weak` 只作为 `censored k>=2` supervision
5. consistency 默认关闭，且需要显式 gate
6. Stage 4 renderer 必须冻结 attribution
7. renderer 不允许把 raw full diff 当成 ungrounded context
8. 不调用 retrieval / verifier / LLM API
9. 不把 proxy metric 写成正式结论

## 4. What This Still Is Not

本轮新增的是 implementation skeleton，不是正式实验结果：

- 没有执行 Stage 2 真训练
- 没有执行 Stage 3 真 calibration
- 没有执行 Stage 4 renderer training
- 没有生成新的正式 paper-level 结论
- 没有解禁 Stage 2/3/4

准确表述仍然是：

> staged implementation skeleton is now available, but all downstream training paths remain gated behind explicit approval and dry-run guards.

## 5. Remaining Advisor Decisions

以下问题仍未定稿：

1. formal Stage 1 thresholds
2. repo overlap / repo-disjoint diagnostic
3. real alignment annotation plan
4. Stage 2 unlock and approval
5. Stage 3 approval
6. Stage 4 renderer training approval
7. anti-shortcut timing

因此，这一轮代码只提供 future-ready skeleton，不写死最终 scientific conclusion。
