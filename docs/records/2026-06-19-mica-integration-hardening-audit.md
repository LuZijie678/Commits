> 状态：过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-19 MICA Integration Hardening Audit

本记录对应 `8f9cd31 feat: implement MICA core method enhancements` 之后的 integration hardening 审计。本轮没有运行任何真实训练、真实 validation、final eval 或 anti-shortcut/OOD rerun，只做静态扫描、接口对齐、config 收口、runner 接线与单元测试。

## 1. 仍然存在的 pending / placeholder / abstract contract

以下项继续保留，且属于合理 pending，不应伪装成已完成实验结果：

- `code/mica/baselines/llm_prompting_baseline.py`
  - 只提供 prompt / execution manifest。
  - `api_execution_enabled=false`，需要手工或外部执行。
- `code/mica/baselines/pretrained_classifier_placeholder.py`
  - 明确依赖外部模型下载。
  - `implemented=false` / `requires_external_model=true`。
- `code/mica/eval/training_diagnostics.py::grad_conflict_placeholder_or_optional`
  - 没有真实梯度捕获时返回 `available=false`，不会伪造 grad-conflict 结果。
- `message_utility` 中的人类指标位
  - `human_usefulness` 仍需要真实人工标注，不以 proxy 代替。

以下 `NotImplementedError` 属于抽象后端接口，保留合理：

- `code/mica/training/backend.py`
  - `TrainableAttributionBackend` 抽象基类方法。
  - 真实可测试后端由 `ToyAttributionBackend` 和 adapter 提供。

## 2. 不应继续保留为“孤立 skeleton”的项

本轮已把下列 helper 从“仅测试引用”推进到被真实 runner 消费：

- `schema_validation.py`
  - 被 `run_stage1_official_validation.py`
  - `run_alignment_eval.py`
  - `run_message_utility_eval.py`
  - `run_real_domain_detection_eval.py`
  消费。
- `paper_tables/metric_registry.py`
  - 被 real-domain / alignment / message utility eval runners 消费。
- `experiment/manifest_versioning.py`
  - 被 stage0 / stage1 / stage2 / stage3 / eval runners 消费。
- `experiment/report_schema.py`
  - 被 stage0 / stage1 / eval runners 消费。

## 3. 重复入口与接口并存情况

当前仍存在两组并行入口，但属于可解释的历史兼容，不是无意重复：

1. `run_official_stage1_validation.py` vs `run_stage1_official_validation.py`
   - 前者保留旧 dry-run / readiness / smoke 风格。
   - 后者作为 candidate formal Stage 1 official validation entrypoint。
   - 后续默认应以 `run_stage1_official_validation.py` 为正式入口。

2. `run_stage1_baseline_dryrun.py` vs `run_stage1_baselines.py`
   - 前者保留 deterministic dry-run 兼容链路。
   - 后者承接更完整的 Stage 1 baseline execution contract。

这两组接口当前不建议直接删除，避免破坏已有测试和历史文档引用，但文档中已明确 canonical 入口。

## 4. 本轮发现并修复的关键 integration gap

### 4.1 eval runner 与 paper table 指标键不一致

已修复：

- `run_message_utility_eval.py`
  - 统一输出 `intent_coverage`
  - `specificity_proxy`
  - `proxy_not_human_eval`
- `run_alignment_eval.py`
  - 补齐 `count_exact`
  - `count_mae`
  - `pairwise_f1`
  - `ari`
  - `nmi`
  - `bcubed_f1`
  - `hunk_micro_f1`
  - `over_segmentation_rate`
  - `under_segmentation_rate`
- `run_real_domain_detection_eval.py`
  - 补齐 `ece`
  - `hard_b_fpr`
  - `m_recall`

### 4.2 experiment manifest / provenance 只存在于 helper，未被 runner 消费

已修复：

- Stage 0 protocol freeze runner
- Stage 1 official validation runner
- Stage 2 calibration runner
- Stage 3 alignment calibration runner
- real-domain / alignment / message utility eval runners

均已挂入 `experiment_manifest`；其中 stage0 / stage1 / eval 还接入了 `report_schema`。

### 4.3 config family 校验没有汇总 stage warnings

已修复：

- `config_loader.validate_config_family()` 现在汇总 stage1/2/3/4 warnings。
- advisor-pending threshold、final-test guard、forbidden loss 检查被统一汇总。

## 5. 本轮保留但明确标注的风险

- final-test 相关数据边界仍靠 config / registry / runner policy 三层共同守卫，尚未进入真实实验执行验证。
- Stage 4 仍限定为 deterministic evidence-locked 主线，trainable renderer 只保留 future/ablation gate。
- `configs/mica/data_asset_registry.json` 路径仍允许为 `null`，后续运行真实实验前必须补齐。

## 6. 审计结论

本轮的主要收口是：

1. 新增的 schema/config/metric/manifest helper 不再是孤立模块；
2. runner policy、experiment manifest、report schema、metric registry 已形成闭环；
3. 合理 pending contract 被明确保留，不会伪装为已完成结果；
4. 没有引入新的训练、验证或 final eval 执行。
