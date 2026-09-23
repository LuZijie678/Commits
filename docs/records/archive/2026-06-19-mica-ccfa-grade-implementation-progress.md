> 状态：已归档 / 过时
> 本文档是历史实现说明，可能不反映当前代码状态。
> 当前事实来源：docs/MICA_CURRENT_STATE_AND_PLAN_GAP.md

# 2026-06-19 MICA CCF-A 级实现进展

## 1. Scope

本轮目标不是继续堆 placeholder，而是把若干关键链路从 skeleton 推到可以真实执行 unit-test fixture 的实现层：

- Stage 2 training backend / loop / checkpoint contract
- Stage 3 calibration backend / replay retention path
- Stage 1 official validation execution path
- flat classifier / no-slot baseline 提升
- final eval runner 真实指标计算路径
- anti-shortcut / OOD rerun-ready harness
- deterministic evidence-locked renderer 质量提升

本轮仍然没有运行真实训练、正式 validation、final eval 或任何真实 runtime experiment。

## 2. Stage 2 / Stage 3

Stage 2 / Stage 3 不再只是 guarded skeleton：

- 新增 `TrainableAttributionBackend`
- 新增 `ToyAttributionBackend`，可在 fixture 上产生真实可训练参数更新
- 新增 `MicaModelBackendAdapter`，为后续接入真实 MICA model 做适配
- 新增 `run_train_epoch / run_eval_epoch`
- 新增 checkpoint payload / save / load / validate contract
- Stage 2 loss routing 支持：
  - strict replay
  - hard_b anti-over-splitting
  - M weak censored `k>=2`
  - optional real alignment calibration path
- Stage 3 loss routing支持：
  - real alignment calibration
  - strict replay anti-forgetting

同时继续保持：

- `M weak` 不转成 exact `k=2`
- `hard_b-test / M-final-test` 不进入训练
- renderer / generation loss 不进入 attribution

## 3. Stage 1 Official Validation Path

Stage 1 official validation 已补到可消费 fixture prediction/gold 的执行路径：

- manifest/gold dataset builder
- prediction evaluator
- baseline integration
- summary builder

仍然保留：

- dry-run / execute guard
- thresholds 不用于本轮正式 pass/fail
- 未运行真实 frozen manifest

## 4. Baselines

baseline 不再停留在 placeholder：

- flat classifier 现在是可训练轻量 classifier，可 fit / predict / predict_proba / save / load
- no-slot decoder 现在使用 similarity graph + clustering，而不是单纯 file-path 分桶
- oracle-k / predicted-k 两种模式都可跑

## 5. Eval / Harness / Renderer

本轮还补了：

- real-domain detection eval 实际指标计算
- alignment eval 实际指标计算
- message utility proxy eval 实际指标计算
- anti-shortcut rerun request / masked views
- OOD slice builder
- deterministic renderer 对 type/scope/body/evidence term 的更严格组合

这些都只在小型测试 fixture 上验证，没有跑真实实验。

## 6. Boundaries Still Preserved

本轮仍然严格保持：

1. 不运行真实 Stage 1 validation
2. 不运行真实 Stage 2 / Stage 3 training
3. 不运行 final eval
4. 不生成 repo `outputs/**`
5. 不调用 API / retrieval / verifier
6. 不修改 Stage 1 core training 默认行为
7. 不把 advisor-pending 问题写成最终 scientific conclusion

## 7. Remaining Work

距离真正开始 staged experiments，还剩几类工作：

- 用真实数据资产填充 registry / manifests
- 在 approval 条件满足后接真实 Stage 2 / Stage 3 runner execution
- 对 official Stage 1 validation 使用 frozen manifest 和真实 predictions
- 真实 final eval / anti-shortcut rerun / OOD rerun

当前准确表述是：

> the implementation is substantially more complete and testable, but no new experimental result has been produced in this round.

## 8. Verification Status

已在本地完成：

- targeted unit-test fixture verification for Stage 2 / Stage 3 backend and loop components
- Stage 1 official validation execution-path fixture verification
- baseline / final-eval / anti-shortcut / OOD / deterministic-renderer fixture verification

本轮仍未完成或未触发：

- real Stage 1 official validation
- real Stage 2 / Stage 3 / Stage 4 training
- real final evaluation on hard_b / M-final-test / RealDomainBinary
- any runtime output generation under repository `outputs/**`
