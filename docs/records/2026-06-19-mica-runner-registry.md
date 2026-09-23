> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# MICA Runner Registry

本表整理当前 MICA attribution 主线中已经登记的 runner 及其安全策略。该表对应 `code/mica/runners/registry.py`，用于说明哪些入口可以训练、哪些需要 advisor approval、哪些可以接触 final-test，以及哪些默认只能 dry-run。

| runner | stage | default_mode | can_train | requires_advisor_approval | can_use_final_test | can_call_api | can_update_attribution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `run_stage0_protocol_freeze` | `stage0` | `dry_run` | `False` | `False` | `False` | `False` | `False` |
| `run_stage1_official_validation` | `stage1` | `dry_run` | `False` | `True` | `False` | `False` | `False` |
| `run_stage1_baselines` | `stage1` | `dry_run` | `True` | `True` | `False` | `False` | `False` |
| `run_stage2_calibration` | `stage2` | `dry_run` | `True` | `True` | `False` | `False` | `True` |
| `run_stage3_alignment_calibration` | `stage3` | `dry_run` | `True` | `True` | `False` | `False` | `True` |
| `run_stage4_renderer_training` | `stage4` | `dry_run` | `True` | `True` | `False` | `False` | `False` |
| `run_real_domain_detection_eval` | `eval` | `dry_run` | `False` | `False` | `True` | `False` | `False` |
| `run_alignment_eval` | `eval` | `dry_run` | `False` | `False` | `True` | `False` | `False` |
| `run_message_utility_eval` | `eval` | `dry_run` | `False` | `False` | `True` | `False` | `False` |
| `run_plan_renderer_smoke` | `downstream_smoke` | `smoke_only` | `False` | `False` | `False` | `False` | `False` |
| `run_anti_shortcut_audit_dryrun` | `eval` | `dry_run` | `False` | `True` | `True` | `False` | `False` |
| `run_ood_stress_eval` | `eval` | `dry_run` | `False` | `False` | `True` | `False` | `False` |

## 当前建议入口

- Stage 1 official validation 正式入口：`run_stage1_official_validation`
- Stage 2 calibration 正式入口：`run_stage2_calibration`
- Stage 3 calibration 正式入口：`run_stage3_alignment_calibration`
- Stage 4 只允许 deterministic renderer 作为主线；`run_stage4_renderer_training` 仅 future/ablation gated path

## 安全说明

1. 所有 train-capable runner 都要求 advisor approval。
2. 所有 eval runner 默认禁止 API。
3. Stage 4 runner 明确不得更新 attribution。
4. final-test 只能用于 eval runner，不能用于训练或 tuning。
