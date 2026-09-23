> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-18 MICA Stage 1 Validation Dry-run 骨架

## 1. Purpose

本文档记录在 `2341c16 chore: extend isolated MICA downstream smoke pipeline` 基础上的继续实现。

本轮目标不是正式 `Stage 1` validation，不是调参，不是 `Stage 2`，也不是 generation 主实验。目标只是把以下后续链路的 dry-run skeleton 先搭好：

- official Stage 1 validation dry-run
- deterministic baseline dry-run
- anti-shortcut readiness audit dry-run
- manifest / prediction / edit-unit compatibility checking

## 2. What Was Added

本轮新增了以下隔离模块：

- `code/mica/eval/manifest_checks.py`
  - manifest / prediction / edit-unit compatibility summary
  - split distribution / overlap / duplicate checks
- `code/mica/eval/attribution_metrics.py`
  - pairwise F1
  - Hungarian-style unit accuracy
  - count / over-split / under-split diagnostics
- `code/mica/eval/baseline_metrics.py`
  - `all_one`
  - `file_path`
  - `random_gold_k`
  - `size_heuristic_count`
- `code/mica/eval/anti_shortcut_audit.py`
  - path-masked view
  - diff-marker-masked view
  - identifier-masked view
  - shortcut feature readiness summary
- `code/mica/runners/run_stage1_official_validation_dryrun.py`
- `code/mica/runners/run_stage1_baseline_dryrun.py`
- `code/mica/runners/run_anti_shortcut_audit_dryrun.py`
- `configs/mica/stage1_baseline_spec.json`
- `configs/mica/anti_shortcut_audit_spec.json`

## 3. What This Is Not

这些新增能力都不是正式实验结论：

- 没有执行 official Stage 1 validation training
- 没有应用 threshold 做 pass/fail 判定
- 没有训练 `flat classifier`
- 没有训练 `no-slot decoder`
- 没有运行 anti-shortcut 模型实验
- 没有进入 `Stage 2`

更准确的描述是：

> downstream validation-related interfaces now have dry-run skeletons, but no official validation result has been produced.

## 4. Isolation Guarantees

本轮继续保持以下边界不变：

1. 不改 `core training`
2. 不改 `encoder / slot decoder / count head / Hungarian / L_align / L_count / L_exist`
3. 不改现有 `Stage 1` reports 生成逻辑
4. 不改 generation pilot 默认流程
5. 所有新增 runner 都必须显式 `--dry-run`
6. 不读取 `hard_b / M / RealDomainBinary` 进入训练或校准
7. 不调用 retrieval / verifier / LLM API / DPO
8. 不提交 runtime outputs

## 5. Advisor Decisions Still Unresolved

老师尚未确认的问题仍然保留为 unresolved spec，没有写死成正式科学结论：

1. formal validation thresholds
2. repo overlap 是否可接受
3. 是否需要 repo-disjoint diagnostic
4. 是否需要 `flat classifier / no-slot decoder baseline`
5. anti-shortcut 的时机
6. real alignment benchmark 的标注方案
7. `Stage 2` unlock criteria

因此，本轮新增代码只能视为：

> implementation-side preparation under unresolved scientific decisions.
