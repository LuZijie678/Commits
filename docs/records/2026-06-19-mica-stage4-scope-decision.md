> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/CURRENT_STATUS.md

# MICA Stage4 范围决策

Date: 2026-06-19

## 决策

Stage 4 is fixed to the deterministic evidence-locked renderer as the default path for the current MICA-v3 line.

## 范围

- `stage4_scope = deterministic_evidence_locked_renderer`
- `trainable_renderer_main_result = false`
- trainable renderer remains future work or ablation only
- attribution must stay frozen
- renderer must not update attribution
- no LLM API
- no retrieval
- no verifier

## 原因

The current paper line is centered on count-aware evidence attribution. Rendering is downstream utility, not the main contribution.
