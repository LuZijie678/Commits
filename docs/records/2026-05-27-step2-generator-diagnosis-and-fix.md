# 2026-05-27 Step2 生成失败定位与最短修复记录

## 1. 背景

本轮工作目标是解释为什么 Step2 一轮真实小规模合成里，几乎所有样本都落到：

- `quality_not_pass_after_repair`

需要分清问题到底来自：

- Prompt 本身
- 长度或输出格式约束
- 后处理 / 质量判定过严
- 还是生成器与当前调用方式不匹配

本轮定位基于以下已有失败产物：

- `code/step2/outputs/step2_balanced_step3_ready/summary.md`
- `code/step2/outputs/step2_balanced_step3_ready/synthetic_samples.jsonl`
- `code/step2/outputs/step2_balanced_step3_ready/cache/generation_cache.json`

## 2. 原始失败现象

在失败 run 中，关键现象是：

- `Generated samples = 100`
- `step3_ready_count = 0`
- `generation_failure_rate_attempted = 1.0000`
- 统一失败原因为：`quality_not_pass_after_repair`

如果只看 summary，很容易误以为是“修复后质量仍不达标”。

但继续下钻 `generation_cache.json` 和 `generation_trace` 后，发现这不是后处理把正常文本拒掉，而是生成器经常根本没有给出最终正文。

## 3. 根因定位结论

本轮定位后的结论是：

- 首因不是后处理过严
- 首因也不是 prompt 不够聚焦
- 首因是 `deepseek-v4-pro` 在当前调用口径下会把大量输出预算耗在推理通道
- 当 `max_output_tokens` 过小时，返回里 `reasoning_content` 很长，但 `content` 为空串
- 旧代码只读取 `content`，于是这些响应被当成“生成成功但格式/质量失败”，最终统一落到 `quality_not_pass_after_repair`

换句话说，旧现象的真实含义不是：

> 模型生成了正文，但被后处理判定太严。

而是：

> 模型经常没有产出可用正文，只产出了推理过程。

## 4. 关键证据

### 4.1 针对失败缓存的直接证据

失败缓存中反复出现以下模式：

- `finish_reason = length`
- `message.content = ""`
- `message.reasoning_content` 非空
- `completion_tokens_details.reasoning_tokens = max_output_tokens`

这说明 token 预算被推理通道吃满，最终正文没有落到 `content`。

### 4.2 `v4-pro` 的隔离探针

本轮对同一样本做了直接 API 探针，对比如下：

1. `deepseek-v4-pro + 128`
   - 结果：`reasoning_only_truncated`
   - 现象：只有推理，无正文
2. `deepseek-v4-pro + 256`
   - 结果：仍然 `reasoning_only_truncated`
3. `deepseek-v4-pro + 512`
   - 结果：开始能出正文，但不稳定
4. `deepseek-v4-pro + 1024`
   - 结果：能稳定出正文，但 repair 链路仍有较多失败

由此可见：

- 问题不是简单的 `32 -> 128` 就能完全解决
- `v4-pro` 这条路线对当前“一句 commit subject”任务并不经济
- 它需要很高输出预算才能稳定落正文

### 4.3 Prompt 不是主因

本轮还对同一样本试了“短 prompt”版本。

结果：

- `v4-pro + 128` 下，完整 prompt 失败
- `v4-pro + 128` 下，短 prompt 仍失败
- `v4-pro + 256` 下，短 prompt 仍失败

因此，当前 96 条全灭并不是 prompt 过长导致的单一问题。

Prompt 当然仍可继续优化，但它不是这一轮系统性失败的首因。

### 4.4 后处理不是主因

本轮做了两个对照：

1. 中间对照：切到 `deepseek-chat`
2. 最终约束内修复：保留 `deepseek-v4-pro`，但显式设置 `thinking = disabled`

在这两种情况下，系统都能恢复到“有可用 `step3_ready` 样本”的状态。

这说明：

- 旧的后处理链路不是完全不可用
- 真正的主故障在生成端，而不是 gate 先天过严
- 对 `v4-pro` 而言，关键不是单纯拉高预算，而是不要让 thinking 默认开启

## 5. 对照实验结果

### 5.1 `deepseek-v4-pro + 128`

小规模真实运行：

- 产物目录：`code/step2/outputs/step2_api_smoke_repair_check/`
- 结果：`step3_ready = 0 / 3`
- 三条样本全部失败为：`reasoning_only_truncated`

### 5.2 `deepseek-v4-pro + 1024`

小规模真实运行：

- 产物目录：`code/step2/outputs/step2_api_smoke_repair_check_1024/`
- 结果：`step3_ready = 1 / 3`
- 说明高预算可以部分缓解，但成本高，且整体稳定性仍不够

### 5.3 `deepseek-chat + 128`

小规模真实运行：

- 产物目录：`code/step2/outputs/step2_api_smoke_deepseek_chat_128/`
- 结果：`step3_ready = 2 / 3`
- `generation_failure_rate_attempted = 0.0`
- `message_gate.passed = 1`
- 三条样本中：
  - `pass = 1`
  - `fallback = 1`
  - `reject = 1`

这一步的作用是证明：

- 当前 gate 不是主故障
- 只要生成器能稳定输出正文，后续链路可以工作

但它不是本轮最终默认方案，因为后续约束改为：必须保留 `deepseek-v4-pro`。

### 5.4 `deepseek-v4-pro + thinking=disabled + 128`

在保持 `deepseek-v4-pro` 不变的前提下，本轮进一步按官方口径显式关闭 thinking。

小规模真实运行：

- 产物目录：`code/step2/outputs/step2_api_smoke_v4_pro_disabled_128/`
- 结果：`step3_ready = 2 / 3`
- `generation_failure_rate_attempted = 0.0`
- `message_gate.passed = 1`
- 三条样本中：
  - `pass = 1`
  - `fallback = 1`
  - `reject = 1`

这说明在“必须用 `v4-pro`”的限制下，最短、最稳的修复路线不是把预算一路拉到 `1024`，而是：

- 保留 `deepseek-v4-pro`
- 显式设置 `thinking = disabled`
- 将 `max_output_tokens` 保持在 `128`

## 6. 本轮代码修复

本轮落实了三类修复。

### 6.1 显式暴露真实错误类型

在 `code/step2/code/construct_simple_two_intent.py` 中新增：

- `reasoning_only_truncated`
- `empty_content_response`

当响应满足以下条件时，不再记为“成功生成后再失败”，而是直接标为生成失败：

- `content` 为空
- `finish_reason = length`
- `reasoning_content` 非空

这样后续 summary 和样本轨迹会更接近真实故障。

### 6.2 提高默认输出预算

默认 `max_output_tokens` 从 `32` 提高到 `128`。

这一步本身不能单独救活默认开启 thinking 的 `v4-pro`，但在 `thinking = disabled` 之后，`128` 已足够支持当前 Step2 小规模真实运行。

### 6.3 保留 `v4-pro`，显式关闭 thinking

Step2 默认生成器最终调整为：

- 生成模型：`deepseek-v4-pro`
- thinking 模式：`disabled`

这是本轮在“必须使用 `v4-pro`”约束下的关键行为修复。

理由是：

1. 官方接口支持对 `v4-pro` 显式设置 thinking 模式
2. 当前问题的首因正是默认 thinking 抢占输出预算
3. 在 `thinking = disabled` 后，`128` token 下即可稳定产出正文
4. 同一套 repair / gate 下，`v4-pro + thinking=disabled + 128` 已通过小规模真实烟测
5. 相比 `v4-pro + 1024`，这条路线成本更低、稳定性更高、改动更小

### 6.4 为什么 `thinking=disabled` 仍然可信

当前“关闭 thinking”并不等于“放弃 `v4-pro` 能力”，而是明确切到官方支持的 non-thinking 模式。

这一点的方法学含义应写清：

1. `thinking=disabled` 是 DeepSeek 官方文档明确支持的请求参数，不是非正式绕过
2. Step2 当前要验证的是短 synthetic commit subject 的输出质量，而不是模型显式思维链本身
3. 因此，当前结果是否可信，主要取决于输出侧验证是否充分，而不是模型是否返回长 `reasoning_content`

在 Step2 中，输出侧验证至少包括：

- `coverage`
- `faithfulness`
- 格式约束
- message gate
- review sample / 人工抽检

所以更准确的说法不是：

- “为了跑通，先把 thinking 关掉”

而是：

- “对于 Step2 的短 subject 生成任务，使用 `deepseek-v4-pro` 的官方 non-thinking 模式，以避免思维链默认占用输出预算；最终质量由输出侧验证与人工审计约束。”

需要注意的限制是：

- `thinking=enabled` 与 `thinking=disabled` 是两种不同生成配置
- 后续对外报告时必须明确写成 `deepseek-v4-pro, thinking=disabled`
- 不应把两种模式的结果直接混合为单一模型默认结果

## 7. 本轮新增验证

本轮补充了以下测试：

- 检测 `reasoning_only_truncated`
- 检测 `v4-pro` 请求 payload 中显式带有 `thinking = disabled`
- 检测默认输出预算为 `128`
- 检测默认生成模型为 `deepseek-v4-pro`
- 检测默认 thinking 模式为 `disabled`
- 检测仓库配置文件与代码默认值一致

执行结果：

## 8. 2026-05-30 代理入口修复与 formal fullscale 恢复补记

### 8.1 新暴露出的根因不是 prompt，而是 Python 网络出口

在继续推进 Step2 formal fullscale 时，出现了一类新的系统性失败：

- 分片不再因为 `Broken pipe` 中途崩掉；
- 但大量分片虽然能写出 `run_metadata.json`，最终却是：
  - `Generated samples = 100`
  - `step3_ready_count = 0`
  - `generation_failure_rate_attempted = 1.0000`

对 `shard_0016`、`shard_0017` 的样本级排查显示：

- 绝大多数样本的 `message_error_type = request_error`
- `generation_trace.raw_response_preview` 统一为：
  - `<urlopen error [Errno 8] nodename nor servname provided, or not known>`

这说明新的主故障不是：

- prompt 不聚焦
- 长度修复失效
- 后处理过严

而是：

- Step2 的 Python `urllib/socket` 无法解析 `api.deepseek.com`

### 8.2 关键证据

同一台机器上出现了明确分叉：

1. Python 直连失败

- `python3 urllib` 访问 `https://api.deepseek.com/v1/models`
- 返回：`URLError(gaierror(8, 'nodename nor servname provided, or not known'))`

2. `curl` 访问正常

- `curl -I https://api.deepseek.com`
- 返回：`HTTP/2 401`

3. macOS 系统代理存在

- `scutil --proxy` 显示本机启用了：
  - `HTTPProxy=127.0.0.1:7890`
  - `HTTPSProxy=127.0.0.1:7890`

4. 给 Python 显式注入代理后立刻恢复

- 在进程环境中显式设置：
  - `HTTP_PROXY=http://127.0.0.1:7890`
  - `HTTPS_PROXY=http://127.0.0.1:7890`
- Python `urllib` 随即能访问 DeepSeek，并返回正常鉴权响应
- 同时 Step2 formal preflight 通过：
  - `code/step2/outputs/step2_preflight_network_probe_via_proxy/preflight_report.json`
  - 其中 `generator=1`

因此，根因可明确表述为：

> DeepSeek 服务本身可达，API key 也可用；真正的问题是 Step2 的 Python 进程默认没有继承本机系统代理，导致 DNS/网络出口在 Python 侧失败。

### 8.3 本轮最短修复

本轮没有继续改 prompt，而是只改运行入口：

1. 新增代理环境导出脚本

- `code/step2/tools/emit_proxy_env.py`

作用：

- 读取 `scutil --proxy`
- 生成：
  - `HTTP_PROXY`
  - `HTTPS_PROXY`
  - 对应小写变量

2. 更新顶层 Makefile 的 Step2 常用入口

当前以下入口会自动注入系统代理，并统一设置：

- `MPLCONFIGDIR=/private/tmp/step2_mplconfig`

已覆盖：

- `make step2-preflight`
- `make step2-mock`
- `make step2-fullscale-plan`
- `make step2-fullscale-run`

3. 保留前一轮“不可达即 fail-fast”的保护

当 API ping 已明确失败时，分片现在会直接记为 `failed`，不再污染结果为：

- `completed`
- `step3_ready_count = 0`

### 8.4 修复后验证

#### 8.4.1 顶层 preflight 恢复

通过顶层入口执行：

- `make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"`

当前通过产物：

- `datasets/step2/delivery/current_proxycheck/preflight_report.json`

关键结果：

- `preflight_passed=1`
- `generator=1`
- `fewshot=1`
- `formal_assets=1`
- `scoring=1`
- `input_data=1`
- `output=1`

#### 8.4.2 真实生成 smoke 恢复

在代理入口修复后，1 shard smoke 的实时运行信号显示：

- `processed=10/100`
- `gen_ok=9`
- `gen_fail=1`

这说明：

- 真实生成已经恢复
- 不再是旧的“全量 request_error 空跑”

因此，这轮修复已经足够证明：

- 代理入口修复生效
- DeepSeek 主调用链路已恢复真实可运行性

### 8.5 对 `step2_fullscale_formal_20260529T1` 的结果口径修正

代理入口修复后，`code/step2/outputs/step2_fullscale_formal_20260529T1/aggregate/fullscale_summary.json`
当前汇总状态为：

- `shard_count = 280`
- `successful_shard_count = 280`
- `failed_shard_count = 0`
- `generated_count_merged = 27901`
- `step3_ready_count_merged = 4173`
- `step3_ready_rate_over_generated = 0.149565`

但这份结果不能直接被当作“代理修复后的正式最终主结果”，原因是：

1. 成功分片分成两部分

- `reused = 58`
- `completed = 222`

2. `58` 个 reused 分片有非零产出

这些分片来自较早阶段已经完成并复用的结果，贡献了全部当前 `4173` 条 `step3_ready`

3. 本轮恢复补跑的 `222` 个 completed 分片全部为零产出

即：

- `recovered_zero_step3_ready_count = 222`
- `reused_zero_step3_ready_count = 0`

也就是说，当前 `step2_fullscale_formal_20260529T1` 的形式状态虽然已经变成：

- `280/280` 完成
- `0` 失败

但它的方法学含义更准确地说是：

> 这轮 fullscale 已经完成“运行完成性修复”，不再被 `Broken pipe` 或代理缺失阻断；  
> 但由于其中 `222` 个后续补跑分片是在错误网络口径下产出的 `0 step3_ready` 完成分片，所以这份 aggregate 不能直接当作新的正式主结果。

### 8.6 当前推荐结论

到本轮为止，最稳妥的结论应写成：

1. `Broken pipe` 问题已修复；
2. Python 侧未继承系统代理导致的 `request_error / gaierror(8)` 问题已定位，并通过代理入口修复；
3. 代理修复后，Step2 顶层 preflight 已恢复通过，真实生成 smoke 也恢复非零成功；
4. 但 `step2_fullscale_formal_20260529T1` 当前这份 aggregate 混合了：
   - 早先已完成的有效分片
   - 后续在错误网络口径下补出的 `0 step3_ready` 分片
5. 因此，如需得到可直接用于论文主表或正式报告的 fullscale 结果，应在代理入口修复后重新按干净口径重跑 fullscale，而不是继续直接引用当前这份 aggregate 作为最终主结果。

### 8.7 clean formal fullscale 重跑结果

代理入口修复后已经按干净口径新起一轮 fullscale：

- 输出根：`code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/`
- 计划规模：`27901` selected pairs，`280` shards
- source coverage：`4658 / 5099 = 91.35%`
- 最终状态：`processed_shard_count = 280 / 280`
- 成功分片：`280 / 280`
- 失败分片：`0 / 280`
- 成功分片产出：`19137 / 27901 = 68.59%` step3-ready
- 全计划交付覆盖：`19137 / 27901 = 68.59%`

最终 aggregate 还原出的核心状态分布：

| 指标 | 数量 |
|---|---:|
| `generation generated` | `25900` |
| `generation failed` | `794` |
| `precheck skip` | `1207` |
| `message pass` | `7542` |
| `message fallback` | `11595` |
| `message reject` | `6763` |

这轮说明：

1. clean 入口确实恢复了真实非零生成；
2. 经过缺失 shard 结果文件补回与重新聚合后，最终 aggregate 已与 runtime_state 对齐；
3. 当前 `step2_fullscale_formal_proxyclean_20260530T030311Z` 可作为正式 Step2 合成结果口径；
4. 论文或阶段报告中的 fullscale 结果应以最终 aggregate 为准。

正式结果数据文件位置：

- [fullscale_summary.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/fullscale_summary.json)
- [runtime_state.json](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/runtime_state.json)
- [synthetic_samples.jsonl](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples.jsonl)
- [synthetic_samples_step3_ready.jsonl](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_step3_ready.jsonl)
- [synthetic_samples_precheck_rejected.jsonl](../../code/step2/outputs/step2_fullscale_formal_proxyclean_20260530T030311Z/aggregate/synthetic_samples_precheck_rejected.jsonl)

```bash
python3 -m py_compile code/step2/code/construct_simple_two_intent.py
pytest -q code/step2/tests
```

结果：

- `py_compile` 通过
- `117 passed`

## 8. 当前建议口径

当前可以写入实验记录的结论是：

1. 本轮 Step2 失败的主因已经定位清楚，属于生成器与调用口径不匹配，而不是单纯后处理过严。
2. `deepseek-v4-pro` 在当前 Step2 “短 subject 生成”任务上，会显著消耗输出预算到推理通道，导致低预算时正文为空。
3. 仅提高 token 预算可以部分缓解，但性价比差，且在小规模验证中仍不稳定。
4. 在保留 `deepseek-v4-pro` 的前提下，显式设置 `thinking = disabled`，并保留 `max_output_tokens = 128` 后，小规模真实验证已经恢复为可用状态。

同时也必须明确限制：

1. 这轮通过的是 `api_smoke` 级别的小规模真实验证，不是 formal 正式批次完成。
2. `v4-pro + thinking=disabled + 128` 当前只能证明“最短修复路线可用”，还不能直接等价于“正式批次一定稳定”。
3. 后续仍需要再跑更大规模真实生成，并继续抽检生成质量。

## 9. 当前推荐运行口径

在新的默认配置下，当前推荐口径是：

- 默认生成模型：`deepseek-v4-pro`
- 默认 thinking 模式：`disabled`
- 默认输出预算：`128`
- 继续保留 `reasoning_only_truncated` 显式错误分类

对于当前仓库，后续 Step2 若要继续真实验证，建议优先基于新的默认配置继续跑：

- `api_smoke`
- 再进入更大规模 formal run

而不是继续保留 `v4-pro` 的默认 thinking 开启状态，也不是简单把预算一路抬高到 `1024`。

## 10. 关联产物

本轮最关键的对照产物如下：

- 原失败 run：`code/step2/outputs/step2_balanced_step3_ready/`
- `v4-pro + 128`：`code/step2/outputs/step2_api_smoke_repair_check/`
- `v4-pro + 1024`：`code/step2/outputs/step2_api_smoke_repair_check_1024/`
- `deepseek-chat + 128`：`code/step2/outputs/step2_api_smoke_deepseek_chat_128/`
- `v4-pro + thinking=disabled + 128`：`code/step2/outputs/step2_api_smoke_v4_pro_disabled_128/`

如果后续要继续补论文或实验记录，应优先引用 `v4-pro + thinking=disabled + 128` 这轮作为“在最终模型约束下的修复后真实小规模验证”证据，而不是继续引用旧的 `quality_not_pass_after_repair` 失败现象做模糊解释。

## 11. 2026-05-28 50 条级验证批次结果

在补入“为什么 `thinking=disabled` 仍然可信”的方法学口径后，本轮继续直接使用当前默认配置跑了一轮 `50` 条级别真实验证批次：

- 配置口径：`deepseek-v4-pro + thinking=disabled + max_output_tokens=128`
- 运行目录：`code/step2/outputs/step2_validation50_v4_pro_disabled_20260528T002957Z/`
- source 输入：`datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`

这轮结果需要分成两层理解：

### 11.1 生成与评分链路是否恢复可用

答案是“是”。

真实结果如下：

- sampled candidate：`50`
- LLM generation attempted：`47`
- precheck skip：`3`
- generated success：`46`
- generation failure attempted rate：`1/47 = 0.0213`
- BERTScore 计算失效率：`0`
- format fail rate：`0`
- few-shot failed rate：`0`
- message gate：`passed`

这说明当前默认口径下，真正修复成功的是：

1. `v4-pro` 不再因为默认 thinking 抢占预算而大面积正文为空
2. 本地离线 `BERTScore` 初始化与评分链路可以跑通
3. few-shot 检索、生成、评分、message gate 这条主链路已恢复到可用状态

### 11.2 为什么整轮仍然返回失败

答案是“失败在严格数量闸门，不是失败在生成器崩溃”。

这轮配置保留了严格目标：

- `target_count = 50`
- `min_target_ratio = 1.0`
- 也就是必须 `50/50` 都进入 `step3_ready`

而真实结果是：

- pass / fallback / reject：`20 / 15 / 11`
- `step3_ready_count = 35`
- `final_usable_sample_count = 35`
- target gate：`failed`

因此程序最终报错为：

- `Target gate failed: step3_ready=35, generated=50, required=50`

这表示当前问题已经从“模型几乎不出正文”转为“在严格协议下，50 条里只有 35 条达到 Step3 可用标准”。

### 11.3 质量侧的真实指标

对非 reject 样本，本轮真实质量指标为：

- avg_message_quality_weight_non_reject：`0.7773`
- avg_coverage_non_reject：`0.8991`
- avg_coverage_balance_non_reject：`0.9651`
- avg_faithfulness_non_reject：`0.8647`
- avg_style_non_reject：`0.8929`
- coverage_min_avg / coverage_min_p10：`0.8876 / 0.8488`

这说明：

1. `thinking=disabled` 没有把任务退化成“能出字但内容失真”
2. 当前 non-reject 样本的覆盖度、忠实度和样式分数都处于可接受水平
3. 当前主要短板是 acceptance yield 不足，而不是生成器完全不可用

### 11.4 当前应如何对外表述

现阶段更准确的实验结论应写成：

1. `deepseek-v4-pro, thinking=disabled` 在 Step2 短 subject 生成任务上是可信且必要的正式运行口径
2. 可信性来自输出侧验证与人工审查约束，而不是显式思维链本身
3. 在该口径下，生成链路和评分链路已恢复可用
4. 但按当前严格数量闸门，`50` 条验证批次只得到 `35` 条 Step3-ready 样本，因此这轮不能宣称“formal 批次通过”

换句话说：

- `thinking=disabled` 这件事本身不是新的可信性风险
- 当前真实风险是“可用样本产率还不够高”

## 12. 2026-05-28 条件性长度放宽复核

本轮按正式新口径做了进一步收口：

- 基线长度限制仍为：`62`
- 保留 repair 末端的 `final_strong_compress`
- 只对“经过 generate/compress/rewrite 后仍然因超长失败”的样本，做条件性放宽
- 条件性放宽上限取当前真实单意图 subject 长度分布的 `P95=68`
- 非 `final_strong_compress` 阶段一律仍按 `62` 判定

### 12.1 代码层实际修改

已在 `code/step2/code/construct_simple_two_intent.py` 中接入：

1. `final_strong_compress` 可使用条件性放宽上限
2. `message_meta` 明确记录：
   - `length_limit_base`
   - `length_limit_relaxed_candidate`
   - `length_limit_relaxed_used`
3. 新增回归测试，防止“前一轮进入强压缩后，后一轮重生成功却错误沿用放宽上限”

对应新增/更新测试位于：

- `code/step2/tests/test_source_pair_precheck.py`

### 12.2 50 条完整验证批次真实结果

已真实运行：

- `code/step2/outputs/step2_validation50_v4_pro_disabled_condrelax_20260528T022131Z/`

关键结果：

- sampled candidate：`50`
- generation attempted：`47`
- precheck skip：`3`
- pass / fallback / reject：`7 / 29 / 10`
- step3_ready：`36`
- final usable：`36`
- generation failure attempted rate：`1/47 = 0.0213`
- target gate：`failed`

因此，这轮同样不能表述为 formal 批次通过。真实失败原因仍是严格数量闸门：

- 要求：`50/50 step3_ready`
- 实际：`36/50`

### 12.3 条件性放宽到底救了多少

这轮需要区分“进入强压缩阶段”和“真正依赖放宽长度通过”：

- 进入 `final_strong_compress` 且记录 `length_limit_relaxed_used=true` 的样本：`14`
- 其中最终 subject 真实长度仍 `<=62` 的样本：`13`
- 最终 subject 真实长度 `63-68`、即真正依赖条件性放宽保留下来的样本：`1`

也就是说：

1. `final_strong_compress` 作为“最后一次更强语义压缩”本身有价值
2. 但“把 62 放宽到 68”本身带来的净收益非常小，本轮只实质性救回了 `1` 条

### 12.4 这轮结果是否被长度判定 bug 污染

在接入条件性放宽后，又发现并修复了一个边界问题：

- 如果某次外层生成尝试进入过 `final_strong_compress`
- 后续另一轮外层重生成功时，`effective_length_limit` 可能错误保留为放宽值

该问题已通过失败测试复现，并已修复。修复方式是：

- 每次新的 generation attempt 开始时，重新将 `effective_length_limit` 复位为基线 `62`

同时，对已完成的这轮 `50` 条批次做了逐样本复核：

- 所有 `length_limit_relaxed_used=true` 且最终成功的样本，最终成功阶段都发生在 `final_strong_compress`
- 未发现“后一轮按 62 成功却被错误按 68 记账”的污染样本

因此：

- 这轮 `36/50` 的核心结果仍可作为有效诊断证据使用
- 但后续如需继续跑正式批次，应基于修复后的代码重新运行

### 12.5 当前最短结论

截至这一步，可以更准确地写成：

1. `62 + final_strong_compress + 仅超长失败条件放宽到 68` 这条口径已经正确实现
2. 这条修复能避免少量超长样本被不必要拒绝，但不是当前产率瓶颈
3. 当前主矛盾仍然不是“长度上限过紧”，而是大量样本停留在 `fallback`，即覆盖/忠实度/风格综合分数还不足以转成 `pass`
