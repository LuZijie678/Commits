# Plan 1: Step2 Experiment Protocol

更新时间：2026-05-27
对齐依据：`code/construct_simple_two_intent.py`、当前配置文件与当前仓库默认资产。

## 1. 目标

Step2 的职责是：

1. 消费 Step1 提供的单意图 source commits
2. 组合生成 synthetic multi-intent commits
3. 生成 `synthetic_subject`
4. 执行 message 质量检查与 gate
5. 输出供后续阶段使用的样本、索引和 run metadata

## 2. 当前默认入口

### 2.1 默认 source

当前默认 Step2 source 来自 Step1 正式交付层：

- `../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- `../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- `../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json`

### 2.2 默认 few-shot 资产

当前仓库默认已经包含当前正式 few-shot 交付物：

- `../../datasets/step2/delivery/current/fewshot_pool.db`
- `../../datasets/step2/delivery/current/build_manifest.json`

当前真实状态：

- `selected_count = 130`
- `audit_pass = true`
- `retrieval_probe_ok = true`

`examples/synthetic_index_harder.csv` 只保留为 fallback preview，不是默认 formal 入口。

补充说明：

- 上述状态说明 few-shot 资产本身已通过审计
- 不能只看 `build_manifest.json.validation.preflight_passed`
- 是否存在“针对当前 source 的最新 formal preflight 证据”，必须单独核对
- 如果后续更换 source、few-shot 资产或配置，仍应以最新重跑的 preflight 结果为准

## 3. 运行模式

主入口：

```bash
python3 code/construct_simple_two_intent.py
```

当前常用模式：

- `formal`: 正式配置路径
- `api_smoke`: 真实 API 冒烟
- `debug`: 本地 mock 调试
- `preflight`: 只做预检

优先级以 CLI 参数和配置为准，`--preflight` 优先进入 `preflight`。

## 4. 推荐命令

### 4.1 Step1 -> Step2 桥接

```bash
make step2-bridge
```

### 4.2 默认预检

```bash
make step2-preflight
```

如需把真实接口连通性一起纳入 formal 预检：

```bash
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

建议先准备本地覆盖配置：

```bash
cp configs/step2_runtime_config.json configs/step2_runtime_config.local.json
```

然后在 `configs/step2_runtime_config.local.json` 中填写 `deepseek_api_key`。
默认入口在本地文件存在时会自动优先使用它。

### 4.3 本地 mock 调试

```bash
make step2-mock
```

### 4.4 真实 API 运行

```bash
cd code/step2
python3 code/construct_simple_two_intent.py --config configs/step2_runtime_config.local.json
```

如需手动重跑并刷新 `delivery/current/preflight_report.json`：

```bash
cd code/step2
python3 code/construct_simple_two_intent.py \
  --preflight \
  --preflight-api-ping \
  --output-dir ../../datasets/step2/delivery/current \
  --config configs/step2_runtime_config.local.json
```

## 5. 输入契约

source CSV 至少应包含：

- `repo`
- `sha`
- `type`
- `subject`
- `message`
- `git_diff`
- `manual_label`

当前推荐使用的新格式桥接层还会保留：

- `selection_strategy`
- `selection_reason`
- `conservative_tier`
- `model_tier`
- `model_prob`
- `rule_label`
- `rule_weight`
- `source_confidence`

Step2 当前优先消费新格式 `conservative_atomic_sources.csv`，旧格式只保留兼容路径。

## 6. few-shot 契约

few-shot 正式资产要求：

- 数据来源是正式 `M` 资产
- 相对当前 Step2 source 做 `repo + sha` 双重去泄露
- SQLite 表使用 `fewshot_examples`
- `train` 可检索样本总数 `>= 80`
- 默认 common signatures 每类 `>= 3`
- `bad_style_count = 0`
- `audit_pass = true`
- `retrieval_probe_ok = true`

## 7. formal 有效性

可以视为当前代码口径下的 formal-ready，仅当：

- 运行模式不是 mock
- message stage 启用
- message gate 启用
- few-shot 启用
- source manifest 可用
- few-shot build manifest 可用
- preflight 关键检查通过

few-shot 资产 formal-ready，不等于整条论文实验已经完成；真实生成质量和最终泄露审计仍需单独验证。
当前仓库里若存在旧的 `delivery/preflight_report.json`，也不能自动推导为“新的 current source 已经通过预检”；必须核对报告里的 `a_tier_count`、source 路径和时间戳。

## 7.1 关于 `thinking=disabled` 的实验口径

当前 Step2 默认生成配置为：

- `generator_model = deepseek-v4-pro`
- `generator_thinking_type = disabled`

这一定义的含义是：

1. 仍然使用 `deepseek-v4-pro`
2. 但显式走官方 non-thinking 模式
3. 不让推理通道默认占用输出预算

这样做在方法学上是可接受的，原因有三点：

1. 这是官方文档明确支持的模式切换，而不是未文档化的私有技巧
2. Step2 任务目标是生成一行可审计的 synthetic commit subject，而不是评估模型显式思维链本身
3. 当前结果可信性由输出侧验证保证，包括 `coverage`、`faithfulness`、格式约束、message gate 和人工抽检，而不是由是否返回长 `reasoning_content` 保证

因此，论文和实验记录应明确写为：

- `deepseek-v4-pro, thinking=disabled`

而不应模糊写成仅仅“`deepseek-v4-pro` 默认设置”。

同时需要避免：

- 将 `thinking=enabled` 与 `thinking=disabled` 的样本混合后直接做统一统计
- 把 `thinking=disabled` 表述成“关闭模型能力”或“规避模型缺陷”

更准确的口径是：

- 对于 Step2 的短 subject 生成任务，使用 `v4-pro` 的官方 non-thinking 模式，以避免思维链内容占用输出预算；最终质量仍由输出层验证与审计来约束。

官方文档：

- `https://api-docs.deepseek.com/zh-cn/guides/thinking_mode`
- `https://api-docs.deepseek.com/api/create-chat-completion`

## 8. 输出

Step2 运行应至少输出：

- synthetic sample 数据文件
- run metadata
- gate / report 文件
- 与 source/few-shot 相关的 manifest 引用

具体文件名以当前配置和输出目录约定为准。

## 8.1 `message_gate` 与 `target_gate` 的口径区分

这两个 gate 不是一回事，必须分开解释。

### `message_gate`

定位：

- 质量与协议门

含义：

1. 检查 message 质量、few-shot 异常率、覆盖率、生成失败率等；
2. 如果它失败，说明本轮 run 在质量或协议层面不合格；
3. 这种失败不能被解释成“只是没凑够数量”。

### `target_gate`

定位：

- 交付数量门

当前代码事实：

1. `required_samples = ceil(target_count * min_target_ratio)`；
2. `step3_ready_count >= required_samples` 才算通过；
3. 在 `enforce_gates=True` 的正式单次运行里，`target_gate` 失败会直接抛错退出。

这意味着：

1. 在执行层，`target_gate` 是严格交付门；
2. 它回答的问题是：“这轮 one-shot run 最终是否交付了足够多的 Step3-ready 样本？”
3. 它不直接回答“这些已生成样本的质量是否达标”。

### 论文与实验记录口径

论文里应明确采用双层表述：

1. `target_gate_passed`
   - 作为二元交付状态位报告；
   - 表示这轮 run 是否满足既定交付数量目标。
2. `step3_ready_count / target_count`
   - 作为连续产率指标报告；
   - 表示当前配置下的自然可交付比例。

因此：

1. `message_gate_failed`
   - 这是质量/协议失败；
   - 不应当被写成“只是数量不够”。
2. `message_gate_passed && target_gate_failed`
   - 这是“质量链路通过，但严格交付数量不足”；
   - 可以作为正式 yield evidence 报告；
   - 但不能被记成 delivery success。
3. `message_gate_passed && target_gate_passed`
   - 才是完整意义上的 delivery success。

推荐措辞：

- `message_gate`: 质量与协议门
- `target_gate`: 严格交付门
- `step3_ready_rate = step3_ready_count / target_count`: 报告型产率指标

## 8.2 论文主表最小列集

Step2 正式实验进入论文主表时，最小建议列集固定为：

| 中文表头 | 对应口径 |
|---|---|
| 配置/方法 | 一行代表一个固定设置，例如 `legacy_guarded + kmeans_1d` |
| 种子数 | 多种子重复次数 |
| 目标数 | `target_count` |
| 可交付样本数 | `step3_ready_count`；多种子时建议写 `均值±标准差` |
| 可交付产率 | `step3_ready_count / target_count`；多种子时建议写 `均值±标准差` |
| 产率范围 | 多种子时写 `min-max` |
| 质量门通过率 | `message_gate_passed` 的 run 级通过率 |
| 严格交付门通过率@1.0 | `target_gate_passed` 的 run 级通过率，显式绑定默认 `min_target_ratio=1.0` |
| 备注 | 用于解释“质量门通过但严格交付不足”等情况 |

执行要求：

1. 主表必须同时保留 `可交付产率` 和 `严格交付门通过率@1.0`；
2. 不允许只写 `passed/failed` 而省略 `step3_ready_count / target_count`；
3. `message_gate_passed && target_gate_failed` 必须解释为“质量链路成立，但 one-shot 交付数量不足”；
4. `pass / fallback / reject`、`coverage`、`faithfulness`、`few-shot failed/generic rate` 等指标默认转入附表或正文诊断段，不放入主表。

## 8.3 严格交付门敏感性分析

如果论文需要补充“不同交付比例阈值下是否达标”，单独使用敏感性分析表：

| 配置/方法 | `min_target_ratio` | 需要样本数 | 严格交付门通过率 | 说明 |
|---|---:|---:|---:|---|
| `<配置名>` | `1.0` | `<ceil(target_count * 1.0)>` | `<x/y 或 %>` | 正式执行默认口径 |
| `<配置名>` | `0.75` | `<ceil(target_count * 0.75)>` | `<x/y 或 %>` | 仅用于报告层分析 |

这里的原则是：

1. 默认执行配置不改，仍维持 `min_target_ratio=1.0`；
2. `0.75` 只用于解释自然产率与严格交付门之间的关系；
3. 敏感性分析不能替代主表主结论。

## 9. 边界

- Step2 不应把 fallback preview few-shot 当作正式默认资产
- Step2 不应直接消费未桥接、未审计的临时 source
- `configs/step2_from_step1_source_config.json` 是小规模 `api_smoke` 配置，不应当作 formal 默认配置引用
- Step2 论文叙事应基于当前正式 source 与正式 few-shot，而不是旧 preview 资产
