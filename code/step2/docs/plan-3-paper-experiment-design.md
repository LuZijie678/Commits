# Plan 3: Paper Experiment Design

更新时间：2026-05-27
状态说明：本文档描述的是 Step2 项目面向论文实验的运行矩阵、离线实验支撑工具和可审查协议。其中已在 `code/` 中落地的部分会明确标注为 `implemented`；仍未落地的部分标注为 `planned` 或 `partial`。

---

## 1. 目标

Step2 在论文实验中的职责：

1. 构造 synthetic commit samples。
2. 记录 formal / smoke / debug / preflight 的协议状态。
3. 输出 curriculum-ready / Step3-ready 样本与对应 difficulty / realism metadata。
4. 对每次 run 产出 manifest、metrics、report、leakage audit 和人工审计抽样接口。

Step3 downstream training 仍属于后续阶段，当前状态是 `planned`。

---

## 2. 实验矩阵与实现状态

以下使用 `E0-E15` 作为论文实验路径中的工作包编号。

| 编号 | 实验/支撑项 | 当前状态 | 备注 |
|---|---|---|---|
| E0 | Step2 formal 协议主 pipeline | implemented | 以 `construct_simple_two_intent.py` 为准 |
| E1 | preflight 协议检查 | implemented | 当前仓库默认 few-shot 入口已切到正式交付物；是否已有可直接引用的成功 preflight 证据，以最新重跑结果为准 |
| E2 | api smoke 路径 | implemented | 不可标记为 paper-valid |
| E3 | debug mock 路径 | implemented | 不调用真实 API |
| E4 | few-shot pool 审计 | implemented | `audit_fewshot_pool.py` |
| E5 | split leakage 审计（Step2/few-shot/Step3 eval） | implemented | `audit_split_leakage.py` |
| E6 | run registry 汇总 | implemented | `run_registry.py`，支持 CSV 导出 |
| E7 | experiment manifest generation | implemented | `experiment_manifest.py` |
| E8 | offline metrics aggregation | implemented | `experiment_metrics.py` |
| E9 | paper-style experiment report generation | implemented | `experiment_report.py` |
| E10 | generic dataset leakage checker | implemented | `check_dataset_leakage.py` |
| E11 | human audit sample export | implemented | `export_audit_samples.py` |
| E12 | post-run experiment suite | implemented | `run_experiment_suite.py` |
| E13 | difficulty/realism feature calculation | partial | v1 metadata 已落地；当前主流程可稳定覆盖 C，显式 entangled 模式可覆盖 D |
| E14 | Step2 curriculum metadata / joint-weight export | partial | `difficulty_level`、`realism_score`、`rho`、`realism_weight_config`、`pipeline_order` 已落盘并进入 `final_sample_weight = sample_confidence * pair_quality_weight * rho * message_quality_weight`；Route 1 与完整 curriculum exporter 仍未完成 |
| E15 | Step3 downstream training / eval | planned | 不在本轮实现范围内 |

---

## 3. 已实现的实验支撑工具

### 3.1 Experiment Manifest

状态：`implemented`

脚本：

```bash
python3 code/experiment_manifest.py create \
  --config <CONFIG> \
  --source-data <CSV> \
  --fewshot-pool <POOL> \
  --output-dir <OUT> \
  --run-purpose <PURPOSE> \
  --out <OUT>/experiment_manifest.json
```

作用：

1. 为每次实验绑定代码版本、配置版本、输入数据、few-shot pool 和随机种子。
2. 记录当前 git commit / branch / dirty 状态。
3. 记录 source manifest / few-shot build manifest 的 formal asset 状态。
4. 记录 protocol blockers，避免 smoke/debug/preflight 被误写成 formal paper run。
5. 不写入 API key。

### 3.2 Offline Metrics Aggregation

状态：`implemented`

脚本：

```bash
python3 code/experiment_metrics.py \
  --output-dir <OUT> \
  --out <OUT>/experiment_metrics.json \
  --markdown <OUT>/experiment_metrics.md
```

作用：

1. 读取已有 Step2 output dir。
2. 区分：
   - `precheck skip`
   - `few-shot failure`
   - `generation/API failure`
   - `judge/scoring failure`
   - `true message reject`
   - `pass/fallback`
   - `Step3-ready`
3. 提供 denominator 明确的 rate 指标。
4. 不把 API failure 混进 true quality reject。

### 3.3 Paper-Style Report

状态：`implemented`

脚本：

```bash
python3 code/experiment_report.py \
  --manifest <MANIFEST> \
  --metrics <METRICS> \
  --run-metadata <OUT>/run_metadata.json \
  --gate-report <OUT>/message_gate_report.json \
  --fewshot-audit-report <OUT>/fewshot_audit_report.json \
  --out-md <OUT>/experiment_report.md \
  --out-json <OUT>/experiment_report.json
```

作用：

1. 合并 manifest、metrics、run metadata、gate report 与可选的 few-shot audit report。
2. 统一呈现 run identity、protocol status、formal asset readiness、failure taxonomy、quality metrics、difficulty/realism 摘要与 blockers。
3. few-shot audit report 未提供时，report 仍可生成，但会显式标记 few-shot formal-readiness 解释链不完整；这不是放松 formal gate。
3. 输出适合附录或实验日志归档的 Markdown / JSON 报告。

### 3.4 Leakage and Audit Support

状态：

- `check_dataset_leakage.py`: `implemented`
- `audit_split_leakage.py`: `implemented`
- `export_audit_samples.py`: `implemented`

作用：

1. 自动检查 source / few-shot / audit / eval 之间的 repo / SHA overlap。
2. 支持 generic CSV/JSONL 资产，不强绑某一类 schema。
3. 导出 message / structural / source 三类人工审计 CSV 模板。

### 3.5 Post-Run Experiment Suite

状态：`implemented`

脚本：

```bash
python3 code/run_experiment_suite.py --config configs/experiment_suite.local.json
```

作用：

1. 统一调度 manifest -> metrics -> report。
2. 可选补跑 leakage / audit export。
3. 仅做本地后处理，不调用真实 API。
4. 支持 `--dry-run`。

---

## 4. 论文实验执行建议

### 4.0 状态更新（2026-05-27）

相较于早期草稿阶段，Step2 的默认 few-shot 入口状态已经发生实质变化：

1. 仓库内已经存在正式 few-shot 交付物：
   - `../../datasets/step2/delivery/current/fewshot_pool.db`
   - `../../datasets/step2/delivery/current/build_manifest.json`
2. 当前默认运行配置已经显式指向这份正式 few-shot 资产，而不是旧的 `examples/synthetic_index_harder.csv` preview/fallback 路径。
3. 这份正式 few-shot 资产的当前真实状态为：
   - `selected_count = 130`
   - `audit_pass = true`
   - `retrieval_probe_ok = true`
   - `bad_style_count = 0`
4. few-shot 交付层里虽然保留了历史 preflight 相关 metadata，
   但它不自动等价于“针对当前 source current 的 latest formal preflight 已通过”。
5. 一旦 Step1 source / Step2 bridge current 发生切换，就必须重新生成新的 preflight 证据，并核对：
   - `checks.input_data.a_tier_count`
   - source 路径
   - 报告时间戳

因此，当前论文实验设计中的 Step2 默认入口不应再表述为“few-shot 仍停留在 preview/fallback 路径”，而应表述为：

> Step2 默认 few-shot 入口已经对齐到当前正式 delivered asset；但“few-shot 资产可用”和“针对当前 source 的 latest formal preflight 已通过”必须分开陈述。当前剩余风险除了真实生成质量与跨 source/few-shot/eval 的最终泄露审计，还包括供应侧 API 可用性与最新 preflight 证据是否已刷新。

### 4.1 单次 run 的最小闭环

```text
Step2 run
  -> run_metadata.json / synthetic_samples.jsonl / message_gate_report.json
  -> experiment_manifest.json
  -> experiment_metrics.json
  -> experiment_report.json
```

### 4.2 论文级审计闭环

```text
formal-ready few-shot pool
  -> preflight
  -> formal run
  -> experiment metrics/report
  -> split leakage audit
  -> run registry
  -> human audit sample export
```

### 4.3 明确不应混淆的 run 类型

1. `formal`
   - 才可能成为 `paper-valid`
2. `api_smoke`
   - 只能验证 API 连通性与链路，不可作为论文主结果
3. `debug`
   - 不调用真实 API，不可作为论文主结果
4. `preflight`
   - 是 readiness check，不产出正式样本集

补充说明：

- 当前正式 few-shot 交付物在默认配置中已经是仓库内实物资产，不再需要把“手工补 `--fewshot-db`”写成默认论文运行前提。
- 只有在研究者刻意切换 few-shot 资产时，才需要显式覆盖 `--fewshot-db` / `fewshot_build_manifest_path`。

### 4.4 `target_gate` 的论文口径

当前代码里，`target_gate` 的执行语义是硬门：

1. `required_samples = ceil(target_count * min_target_ratio)`
2. 若 `step3_ready_count < required_samples`，正式单次运行会返回非零
3. 因此它在工程执行层表示“本轮 one-shot 是否达成既定交付数量”

但论文里不能把这件事直接等同于“质量失败”。

建议统一写成两层：

1. `message_gate`
   - 质量与协议门
   - 失败表示质量链路或协议链路不成立
2. `target_gate`
   - 严格交付门
   - 失败表示在当前目标规模与比率下，最终可交付样本数不足
3. `step3_ready_rate = step3_ready_count / target_count`
   - 报告型产率指标
   - 用于比较不同 seed / prompt / threshold / selection 策略的自然交付能力

因此，论文表格与正文应避免以下错误：

1. 不要把 `target_gate_failed` 直接写成“模型失败”或“质量失败”
2. 不要只报告 `passed/failed` 而不报告 `step3_ready_count / target_count`
3. 不要把 `message_gate_failed` 与 `target_gate_failed` 混为一类失败

推荐报告方式：

| 指标 | 作用 |
|---|---|
| `message_gate_passed` | 质量/协议是否成立 |
| `target_gate_passed` | 严格交付是否达标 |
| `step3_ready_count` | 最终可交付样本数 |
| `step3_ready_rate` | 自然交付产率 |

推荐文字口径：

> 在 Step2 中，`target_gate` 作为严格交付门用于判断单次 run 是否达到预设交付规模；而 `step3_ready_rate` 作为连续产率指标，用于分析不同配置下的自然可交付能力。`target_gate` 失败并不等同于质量门失败，尤其在 `message_gate` 已通过时，应解释为“样本质量链路成立，但 one-shot 交付数量不足”。

### 4.5 论文主表最终列项与表头口径

当前代码与真实产物表明，Step2 主表需要优先回答三个问题：

1. 当前配置的自然可交付产率是多少；
2. 质量门是否稳定通过；
3. 严格交付门是否达到预设规模。

因此，论文主表不应塞入过多诊断指标，也不应把 `target_gate` 是否通过当作唯一主结论。推荐固定为下面这组列项。

#### 4.5.1 主表推荐列项

| 列项作用 | 中文表头 | 英文表头 | 取值口径 |
|---|---|---|---|
| 行标识 | 配置/方法 | Setup | 一行代表一个固定实验设置；包含选样策略、提示版本、阈值方法、模型口径等 |
| 运行规模 | 种子数 | Seeds | 多种子正式比较时填写 seed 数；单次 run 可写 `1` |
| 运行规模 | 目标数 | Target Count | 即 `target_count` |
| 主结果 | 可交付样本数 | Step3-ready Count | 多种子时写 `均值±标准差`；单次 run 写原始计数 |
| 主结果 | 可交付产率 | Step3-ready Rate | 定义为 `step3_ready_count / target_count`；多种子时写 `均值±标准差` |
| 稳定性 | 产率范围 | Step3-ready Range | 多种子时写 `min-max`；单次 run 可写 `NA` |
| 质量门 | 质量门通过率 | Message Gate Pass Rate | 以 run 为单位统计，通过率或 `x/y` 都可，但全文必须统一 |
| 交付门 | 严格交付门通过率@1.0 | Target Gate Pass Rate @ 1.0 | 这里的 `1.0` 指执行层默认 `min_target_ratio=1.0` |
| 解释列 | 备注 | Notes | 用于写明主要失败原因，例如“质量门通过但严格交付不足” |

#### 4.5.2 主表模板

建议主表最终直接使用下面的表头：

| 配置/方法 | 种子数 | 目标数 | 可交付样本数 | 可交付产率 | 产率范围 | 质量门通过率 | 严格交付门通过率@1.0 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `<配置名>` | `<seed数>` | `<target_count>` | `<均值±标准差 / 单次原始值>` | `<均值±标准差 / 单次原始值>` | `<min-max / NA>` | `<x/y 或 %>` | `<x/y 或 %>` | `<主失败原因或关键解释>` |

格式要求：

1. `可交付样本数` 与 `可交付产率` 是主表核心列，不能省略其一；
2. `严格交付门通过率@1.0` 必须显式带 `@1.0`，避免和敏感性分析口径混淆；
3. `备注` 必须避免把 `target_gate_failed` 误写成“质量失败”；
4. 如果是单次 run，不写伪装的 `±0`，直接写原始值，并把 `产率范围` 标成 `NA`。

#### 4.5.3 不建议进入主表的列

以下列更适合作为附表、补充材料或正文诊断分析，不建议进入论文主表：

1. `pass / fallback / reject` 的逐项计数；
2. `avg_coverage_non_reject`；
3. `avg_faithfulness_non_reject`；
4. `avg_message_quality_weight_non_reject`；
5. `few_shot_failed_rate`；
6. `few_shot_generic_rate`；
7. `generation_failure_rate_attempted`；
8. `coverage_min_avg` 与 `coverage_min_p10`。

原因是这些指标的角色主要是解释“为什么质量门通过或失败”，而不是直接承担主结果结论。

#### 4.5.4 附表与敏感性分析口径

若论文需要额外解释严格交付门的影响，建议单独增加敏感性分析表，而不是污染主表。

推荐附表表头：

| 配置/方法 | `min_target_ratio` | 需要样本数 | 严格交付门通过率 | 说明 |
|---|---:|---:|---:|---|
| `<配置名>` | `1.0` | `<ceil(target_count * 1.0)>` | `<x/y 或 %>` | 执行层默认正式口径 |
| `<配置名>` | `0.75` | `<ceil(target_count * 0.75)>` | `<x/y 或 %>` | 仅用于报告层敏感性分析，不改变正式执行默认值 |

这里必须保持如下边界：

1. 执行层默认仍然是 `min_target_ratio=1.0`；
2. `0.75` 只作为报告层附加分析，不得回写为默认运行配置；
3. 主表优先报告自然 `step3_ready_rate`，附表才解释不同交付门阈值下的通过情况。

---

## 5. 当前仍是 planned 的部分

以下项目在文档上已有方案，但当前仍未完整落地，不应在论文中被表述为“已完整实现”：

1. `Level A / Level B` 的真实样本构造路线
2. `complex single-intent Route 1`
3. `realism perturbation` 的完整代码实现
4. Step2 侧 `difficulty-aware curriculum` 元数据与导出接口的完整实现
5. `Step3` downstream training / evaluation
6. performance-driven curriculum
7. realism discriminator

---

## 6. 推荐的论文附录材料

建议在附录中至少提供：

1. `experiment_manifest.example.json`
2. `experiment_suite.example.json`
3. `build_manifest.example.json`
4. `experiment_report.md` 示例
5. `dataset_leakage_report.json` 示例
6. `audit_message_sample.csv` 模板
7. `run_registry.py --csv-out` 导出的 registry 表

---

## 7. 导师确认清单

建议在进入正式论文主实验前确认以下事项：

1. 当前 few-shot 正式交付物是否已交付，并且是否已有最新可复现的 `audit_fewshot_pool.py` 与 preflight 证据。
2. source / few-shot / Step3 eval split 的 repo/SHA 边界是否已冻结。
3. 是否接受当前 `experiment_manifest -> metrics -> report` 作为单次 run 的标准归档协议。
4. 是否要求在 `plan-2` 落地前先做人工 structural realism audit。
5. Step3 下游训练是否等待 Step2 的 difficulty / realism / `rho` 联合元数据全部稳定后再启动。

截至 2026-05-27，对第 1 项的当前真实回答应更新为：

- 当前正式 few-shot 交付物已交付；
- 默认运行配置已指向该资产；
- 资产层 `audit_pass=true`、`retrieval_probe_ok=true`；
- latest delivery metadata 已与成功 preflight 对齐；
- 当前未完成的是更下游的 Step2 真实生成质量验证与最终 split leakage 冻结，而不是默认 few-shot 入口缺失。
