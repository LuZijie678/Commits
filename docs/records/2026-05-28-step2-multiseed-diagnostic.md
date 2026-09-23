# 2026-05-28 Step2 多种子与阈值方法诊断记录

## 1. 本轮目的

本轮不再继续优先修单条 prompt，而是先回答两个更基础的问题：

1. 在不改 prompt、只改随机种子的情况下，`legacy_guarded` 基线有多稳定；
2. 在固定同一批样本时，只改阈值方法会不会显著改动最终分层。

结论先说：

1. 会，而且波动不小；
2. 因此 `20` 条批次只能继续作为快速诊断，不应再当正式比较结论；
3. 正式比较应迁到更大样本量，当前建议至少 `target_count=100`，并做多种子重复。

## 2. 多种子重复实验

运行口径：

- 选样策略：`legacy_guarded`
- prompt：保持原始正式默认口径，不启用 `feat_fix_repair` 和 `final_strong_compress` 实验开关
- 阈值方法：`kmeans_1d`
- 仅改 `seed`
- 目标规模：`target_count=20`

真实产物目录：

- [step2_multiseed_legacy_guarded_diag_20260528T063942Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_diag_20260528T063942Z)
- [multiseed_summary.json](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_diag_20260528T063942Z/multiseed_summary.json)
- [threshold_stability_report.md](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_diag_20260528T063942Z/stability/threshold_stability_report.md)

### 2.1 真实结果

| seed | step3_ready | pass | fallback | reject | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|
| 7 | 17 | 9 | 8 | 3 | 0.755254 | 0.793723 |
| 11 | 13 | 6 | 7 | 7 | 0.763563 | 0.792500 |
| 19 | 11 | 7 | 4 | 8 | 0.765602 | 0.795320 |
| 23 | 12 | 6 | 6 | 6 | 0.761811 | 0.794411 |

聚合结果：

- `step3_ready span = 6`，即 `11 -> 17`
- `t_reject span = 0.010348`
- `t_pass span = 0.002820`
- `status_variability_sample_count = 19`

### 2.2 解释

这组结果说明：

1. 只改 `seed`，`20` 条小批次就会从 `11/20` 波动到 `17/20`；
2. 波动主要不来自大规模代码改动，而来自小样本选样差异和近阈值样本翻转；
3. 因此，这类 `20` 条批次只适合快速看：
   - prompt 是否明显退化；
   - 某个修复是否引入大面积坏例；
   - 阈值是否明显失稳。

它不适合承担：

1. 正式产率比较；
2. prompt 版本优劣定论；
3. 阈值方法优劣定论。

## 3. 固定样本阈值方法比较

为把“生成文本变化”和“阈值重估变化”拆开，本轮对同一批 baseline `20` 条样本做离线重分层，只改阈值方法，不重新生成文本。

输入 run：

- [step2_compare20_legacy_guarded_20260528T121100Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_compare20_legacy_guarded_20260528T121100Z)

比较产物：

- [step2_threshold_method_compare_baseline_20260528T063942Z](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_baseline_20260528T063942Z)
- [threshold_method_comparison.json](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_baseline_20260528T063942Z/threshold_method_comparison.json)

### 3.1 真实结果

| 阈值方法 | step3_ready_estimate | pass | fallback | reject | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|
| `kmeans_1d` | 15 | 7 | 8 | 4 | 0.757990 | 0.791892 |
| `reference_quantile_band` | 13 | 7 | 6 | 6 | 0.781073 | 0.793379 |

发生状态变化的样本只有 2 条，但已经足以把 `step3_ready` 从 `15` 降到 `13`：

- `simple2_0002`: `fallback -> reject`
- `simple2_0016`: `fallback -> reject`

### 3.2 解释

这说明：

1. 即使完全固定同一批文本，不重新调用模型；
2. 只要更换阈值方法，边界样本就会发生真实翻转；
3. 在 `20` 条规模下，`2` 条边界样本已经足够显著改变总体结论。

因此，当前最稳妥的实验口径是：

1. 小批次只做快速诊断；
2. 正式比较迁到更大样本；
3. 阈值方法比较必须报告“固定样本离线比较”与“真实重跑比较”是两个不同问题。

## 4. 当前实验口径调整

从本轮开始，明确采用以下口径：

1. `target_count=20`：
   - 仅用于快速诊断；
   - 不作为正式比较主结论。
2. 正式比较：
   - 迁到更大样本量；
   - 当前建议至少 `target_count=100`；
   - 保持 `legacy_guarded` 与原始 prompt 不变；
   - 通过多种子重复估计自然波动范围。

## 5. 当前建议命令

大样本正式比较建议直接使用当前多种子脚本：

```bash
cd code/step2
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/run_multiseed_step2_baseline.py \
  --config configs/step2_runtime_config.local.json \
  --seed 7 \
  --seed 11 \
  --seed 19 \
  --output-root outputs/step2_multiseed_legacy_guarded_100_<timestamp> \
  --target-count 100 \
  --keep-going
```

首轮大样本 baseline 完成后，再对其中一个 baseline run 做固定样本阈值比较：

```bash
cd code/step2
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
MPLCONFIGDIR=/private/tmp/mplconfig \
python3 code/compare_threshold_methods_fixed_samples.py \
  --run-dir outputs/<baseline_run_dir> \
  --method kmeans_1d \
  --method reference_quantile_band \
  --output-dir outputs/<threshold_compare_dir>
```

## 6. 当前结论

当前可以直接写入实验记录的结论是：

1. 原始 `legacy_guarded` 仍应保持为正式默认基线；
2. `20` 条批次对 `seed` 和阈值方法都过于敏感，只能承担快速诊断角色；
3. 正式比较已经不应再围绕 `20` 条批次展开，而应迁到更大样本量并使用多种子重复；
4. 下一步重点不是继续修单条 prompt，而是先在大样本上确认基线稳定性和阈值方法影响范围。

## 7. 后续执行结果：100 条大样本多种子正式比较

在完成上面的诊断之后，继续按同一口径实际运行了更大样本 baseline：

- 选样策略：`legacy_guarded`
- prompt：不改
- 阈值方法：`kmeans_1d`
- 目标规模：`target_count=100`
- seeds：`7 / 11 / 19`

真实产物目录：

- [step2_multiseed_legacy_guarded_100_20260528_run1](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run1)
- [multiseed_summary.json](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run1/multiseed_summary.json)
- [threshold_stability_report.json](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run1/stability/threshold_stability_report.json)

### 7.1 三轮真实结果

| seed | step3_ready | generated | pass | fallback | reject | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| 7 | 77 | 100 | 27 | 50 | 22 | 0.751413 | 0.790598 |
| 11 | 77 | 100 | 26 | 51 | 22 | 0.750338 | 0.788045 |
| 19 | 68 | 100 | 23 | 45 | 30 | 0.758290 | 0.791652 |

共同点：

1. 三轮 `message_gate_passed=true`；
2. 三轮 `few_shot_failed_rate=0`、`few_shot_generic_rate=0`；
3. 三轮 `coverage_min_avg` 都在 `0.894+`；
4. 三轮 `target_gate_passed=false`，原因都是严格 `100/100` 目标未满足，而不是 few-shot、覆盖率或格式门失败。

### 7.2 聚合稳定性

多种子稳定性报告给出：

- `step3_ready_min = 68`
- `step3_ready_max = 77`
- `step3_ready_span = 9`
- `t_reject_span = 0.007952`
- `t_pass_span = 0.003607`
- `status_variability_sample_count = 64`

### 7.3 解释

这组结果比 `20` 条诊断批次更可信，因为：

1. 样本量已经扩大到 `100`；
2. 三轮都跑的是同一正式默认基线；
3. 波动虽然仍然存在，但已经从“11 到 17 / 20”的剧烈比例波动，变成了“68 到 77 / 100”的更稳定区间。

更直白地说：

1. 这说明原始 `legacy_guarded` 在大样本下的自然可交付率，大致落在 `68% -> 77%`；
2. 失败点不是“质量门整体崩了”，而是严格 `min_target_ratio=1.0` 下，`step3_ready` 还达不到 `100/100`；
3. 因此，后续讨论应区分：
   - 消息门是否通过；
   - 最终可交付样本数是否达到目标。

## 8. 后续执行结果：100 条固定样本阈值方法比较

在上述每个 `100` 条 baseline run 完成后，又分别做了固定样本离线阈值比较。

对应产物：

- [step2_threshold_method_compare_legacy_guarded_100_seed7_20260528_run1](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed7_20260528_run1)
- [step2_threshold_method_compare_legacy_guarded_100_seed11_20260528_run1](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed11_20260528_run1)
- [step2_threshold_method_compare_legacy_guarded_100_seed19_20260528_run1](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed19_20260528_run1)

### 8.1 真实结果

| baseline run | `kmeans_1d` step3_ready | `reference_quantile_band` step3_ready | changed_sample_count |
|---|---:|---:|---:|
| seed_7 | 77 | 67 | 16 |
| seed_11 | 77 | 67 | 17 |
| seed_19 | 68 | 66 | 12 |

对应阈值变化：

- `seed_7`:
  - `kmeans_1d`: `t_reject=0.751413`, `t_pass=0.790598`
  - `reference_quantile_band`: `t_reject=0.762171`, `t_pass=0.786146`
- `seed_11`:
  - `kmeans_1d`: `t_reject=0.750338`, `t_pass=0.788045`
  - `reference_quantile_band`: `t_reject=0.761530`, `t_pass=0.783962`
- `seed_19`:
  - `kmeans_1d`: `t_reject=0.758290`, `t_pass=0.791652`
  - `reference_quantile_band`: `t_reject=0.761923`, `t_pass=0.786437`

### 8.2 解释

这说明两点：

1. 到了 `100` 条规模，阈值方法仍然会影响结果，但不像 `20` 条批次那样容易被 2 条样本牵着走；
2. 在当前三轮里，`reference_quantile_band` 都比 `kmeans_1d` 更保守，`step3_ready` 分别少了 `10 / 10 / 2`。

因此，当前可以更稳妥地说：

1. 阈值方法不是无关紧要；
2. 但它的影响幅度需要放到更大样本里看，不能只靠 `20` 条批次下结论；
3. 当前正式默认继续保留 `kmeans_1d` 更合适，因为它对应现有正式链路真实运行口径。

## 9. 更新后的结论

截至本轮结束，当前最稳妥的实验判断是：

1. `legacy_guarded` 继续作为正式默认基线；
2. `20` 条批次永久降级为快速诊断，不再承担正式比较结论；
3. 更大样本下，`legacy_guarded` 的自然 `step3_ready` 区间目前观测为 `68/100 -> 77/100`；
4. 三轮大样本都通过了消息门，但都没达到严格 `100/100` 的 target gate；
5. 当前 Step2 的主要约束已经更清楚：不是 few-shot 资产不合格，也不是覆盖率崩坏，而是最终可交付样本比例仍不足以满足过严的目标门；
6. 阈值方法对结果仍有影响，但在 `100` 条规模下已经能被更稳定地比较；
7. 后续如果要继续推进正式实验，优先级应该是：
   - 扩大样本继续确认自然区间；
   - 明确 `target gate` 的正式论文口径；
   - 再讨论是否需要调阈值方法或重设目标比率，而不是先改 prompt。

## 10. 补充执行结果：再加 3 个 seed 后的 6-seed 区间

随后继续补跑了第二批 `100` 条 baseline seeds：

- `23 / 29 / 31`

真实产物目录：

- [step2_multiseed_legacy_guarded_100_20260528_run2](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_run2)

第二批结果：

| seed | step3_ready | generated | pass | fallback | reject | t_reject | t_pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| 23 | 67 | 100 | 22 | 45 | 31 | 0.753336 | 0.788877 |
| 29 | 81 | 100 | 35 | 46 | 17 | 0.746683 | 0.785266 |
| 31 | 70 | 100 | 35 | 35 | 28 | 0.752163 | 0.784904 |

与第一批 `7 / 11 / 19` 合并后，得到 `6` 个 seed 的联合稳定性报告：

- [step2_multiseed_legacy_guarded_100_20260528_all6_stability](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_multiseed_legacy_guarded_100_20260528_all6_stability)

联合聚合结果：

- `run_count = 6`
- `step3_ready_min = 67`
- `step3_ready_max = 81`
- `step3_ready_span = 14`
- `t_reject_span = 0.011607`
- `t_pass_span = 0.006748`
- `status_variability_sample_count = 90`

### 10.1 新结论

补完到 `6 seed` 之后，可以把之前的 `68-77/100` 区间更新为：

- 当前观测到的自然 `step3_ready` 区间：`67/100 -> 81/100`

这意味着：

1. 当前 baseline 的自然波动比“三个 seed 时”更大；
2. 之前的 `68-77` 还不是稳定上界；
3. 至少在当前 source / few-shot / prompt / threshold_method 固定不变时，`legacy_guarded` 的 one-shot 交付能力已经被观测到最低 `67%`、最高 `81%`。

但仍然没有任何一轮达到严格 `100/100`：

1. 因此，`target_gate=100/100` 仍然过严；
2. `target_gate_failed` 依旧不应被解读为“质量门失败”；
3. 更准确的表述是：当前配置下，质量链路成立，但 one-shot 交付比例存在明显自然波动。

## 11. 补充执行结果：新增 3 个 seed 的固定样本阈值比较

新增离线比较产物：

- [seed23 threshold compare](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed23_20260528_run2)
- [seed29 threshold compare](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed29_20260528_run2)
- [seed31 threshold compare](/Users/lifulin/Downloads/Commits/code/step2/outputs/step2_threshold_method_compare_legacy_guarded_100_seed31_20260528_run2)

结果：

| baseline run | `kmeans_1d` step3_ready | `reference_quantile_band` step3_ready | changed_sample_count |
|---|---:|---:|---:|
| seed_23 | 67 | 66 | 12 |
| seed_29 | 81 | 66 | 17 |
| seed_31 | 70 | 66 | 6 |

解释：

1. 阈值方法在新增 seeds 上仍然有真实影响；
2. 其中 `seed_29` 最典型：只改阈值方法，`step3_ready` 会从 `81` 掉到 `66`；
3. 这再次说明，论文里必须把“生成输出差异”和“阈值重估差异”拆开分析。

## 12. 最终收口

截至目前，这轮工作的正式收口口径应当是：

1. `target_gate` 在代码执行层是严格交付门；
2. `step3_ready_rate = step3_ready_count / target_count` 在论文里是报告型产率指标；
3. `message_gate_failed` 和 `target_gate_failed` 必须分开解释；
4. 当前 `legacy_guarded` 在 `6 seed, target_count=100` 下的自然交付区间观测为 `67% -> 81%`；
5. 现阶段最需要讨论的不是 prompt 小修，而是：
   - 是否继续扩大 seeds 估计稳定区间；
   - 是否调整 `target_gate` 的正式交付口径；
   - 是否把 `step3_ready_rate` 作为主报告指标，而把 `target_gate_passed` 作为交付状态位单独报告。
