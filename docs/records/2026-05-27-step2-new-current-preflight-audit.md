# 2026-05-27 Step2 新 current 正式预检前审核记录

## 1. 审核对象

本轮审核的目标不是直接产出 Step2 正式样本，而是在基于新的 `current` 运行 Step2 正式预检或正式构造实验之前，先核清以下事项：

- 新的 Step2 source 是否已经正确切到新的 Step1 交付层
- 默认 few-shot 资产是否仍然合规
- Step2 formal preflight 是否真的针对新的 source 重跑过
- 真实大模型接口是否可用
- Step2 source 与 few-shot 是否存在 repo / sha 泄漏
- Prompt、实验协议、拟真元数据的论文表述是否可靠

## 2. 当前审核对象与输入资产

当前实际审核对象如下：

- Step1 保守单意图交付层：`datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- Step2 bridge current：`datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- Step2 bridge manifest：`datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json`
- Step2 few-shot current：`datasets/step2/delivery/current/fewshot_pool.db`
- Step2 few-shot build manifest：`datasets/step2/delivery/current/build_manifest.json`

本轮核到的 source 真实规模：

- source rows：`5099`
- source repo 数：`82`
- source type 分布：`feat / fix / refactor / test`

## 3. few-shot 资产复验结论

本轮执行：

```bash
cd code/step2
python3 code/audit_fewshot_pool.py --db ../../datasets/step2/delivery/current/fewshot_pool.db --json
```

结果：通过。

关键事实：

- `passed = true`
- `raw_rows = 130`
- `eligible_rows = 130`
- `retrieval_probe_ok = true`
- `audit_pass = true`
- `bad_style_count = 0`

common signature 覆盖满足当前 formal 门槛：

- `fix+test = 14`
- `feat+test = 12`
- `fix+docs = 7`
- `feat+docs = 6`
- `fix+refactor = 10`
- `feat+refactor = 15`
- `docs+test = 4`
- `perf+refactor = 3`
- `fix+perf = 4`

结论：

- 当前 few-shot 资产本身仍然是合规的 formal-ready few-shot 资产。
- 这只能证明 few-shot 池可用，不能自动证明“新的 current source 已经完成 latest formal preflight”。

## 4. source 与 few-shot 泄漏审计结论

本轮按当前 Step2 代码口径做了 source / few-shot repo 与 sha 交叉检查。

结果：

- source rows：`5099`
- few-shot rows：`130`
- repo overlap count：`0`
- sha overlap count：`0`

结论：

- 就当前仓库内的 Step2 source 与 few-shot 而言，本轮没有发现 repo 泄漏，也没有发现 sha 泄漏。
- 这满足比原协议更严格的 source/few-shot 双零重叠口径。

补充：

- 当前仓库里没有发现明确冻结的 Step3 eval/test 正式资产。
- 因此，本轮不能给出“Step2 / few-shot / Step3 全链路无泄漏”的结论。
- 这一项应记为：`待补风险，而不是已通过`。

## 5. 新 current formal preflight 结论

### 5.1 沙箱内首次尝试

本轮先在受限环境下执行：

```bash
cd code/step2
python3 code/construct_simple_two_intent.py \
  --preflight \
  --preflight-api-ping \
  --config configs/step2_runtime_config.json \
  --output-dir ../../datasets/step2/delivery/current
```

产物：

- `datasets/step2/delivery/current/preflight_20260527T083728Z/preflight_report.json`

结果：失败，但失败原因是沙箱 DNS/外网访问限制，不是代码逻辑问题。

错误摘要：

- `generator.api_ping.error_type = request_error`
- `raw_response_preview = <urlopen error [Errno 8] nodename nor servname provided, or not known>`

### 5.2 真实网络下再次尝试

在真实网络放行后，本轮再次执行同一条 formal preflight。

产物：

- `datasets/step2/delivery/current/preflight_20260527T083852Z/preflight_report.json`

结果：仍未通过，但失败点已明确缩小到远程接口供应侧。

关键检查项：

- `input_data = 1`
- `fewshot = 1`
- `formal_assets = 1`
- `scoring = 1`
- `output = 1`
- `generator = 0`

新的 source 证据已经对齐成功：

- `checks.input_data.a_tier_count = 5099`
- `checks.input_data.pool_stats.repo_count = 82`

真实失败原因：

- `generator.api_key_present = true`
- `generator.api_ping.error_type = http_402`
- 返回信息：`Insufficient Balance`

结论：

- 新的 `current` source 已经真正进入当前 formal preflight 检查链路。
- 本地数据入口、few-shot 资产、formal assets 和 scorer 都通过了。
- 当前 formal preflight 的现实 blocker 是远程供应侧余额不足，不是本地代码、source 数据或 few-shot 资产 defect。

## 6. 配置与入口审查结论

本轮额外发现并修正了一处真实入口错位：

- 顶层 `make step2-preflight` 原先默认指向 `configs/step2_from_step1_source_config.json`
- 该配置的 `run_purpose = api_smoke`
- 它不应被当作 formal preflight 的默认配置

本轮已经修正为：

- 顶层 `make step2-preflight` 默认改为 `configs/step2_runtime_config.json`
- 同时支持：

```bash
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

这次修正的意义是：

- 把“默认预检入口”重新对齐到 formal 路线
- 避免继续用 `api_smoke` 配置冒充 formal 预检

## 7. Prompt 审查结论

基于 `code/step2/code/construct_simple_two_intent.py` 的静态检查，本轮结论如下：

- 当前 Prompt 的目标非常明确：只生成一行 synthetic subject
- Prompt 主要依赖：
  - few-shot 示例
  - 每个 intent 的原始 message / subject / diff evidence card
  - 12 条文本规则
- 当前 API 调用只有单轮 `user` 消息，没有单独的 `system` 角色约束
- 生成后仍依赖：
  - 超长压缩
  - 格式不合法时重写

可接受之处：

- 任务目标聚焦
- 对“不要乱编”和“不要机械模板拼接”有明确限制
- 输出面向的是短 subject，不是长解释段落

保留风险：

- 可能偏向过短、过泛
- 可能覆盖两个 intent 但不够均衡
- few-shot 表层句式可能牵引模型输出风格

结论：

- 当前 Prompt 可以作为正式实验的工作 Prompt 使用
- 但不能把它表述成“已经充分稳健”
- 真正的结论仍需依赖后续真实生成样本抽检

## 8. 拟真扰动与难度元数据审查结论

本轮静态审查看到：

- 已实现字段：
  - `difficulty_level`
  - `realism_score`
  - `rho`
  - `final_sample_weight`
  - `pipeline_order`
- 但代码里仍明确写有：
  - `level_a_b_route_status = schema_ready_route_not_implemented`
- 当前 formal 配置仍为：
  - `allow_entangled_candidates = false`
  - `max_shared_files_per_group = 0`

结论：

- 当前可以说“已有难度/拟真元数据框架，并已在主流程落盘”
- 不能说“完整拟真扰动实验路线已经 fully implemented”
- `realism_score` 更适合表述为结构化拟真分数，不应夸大成强真实度证明

## 9. 旧 preflight 证据状态纠偏

本轮先发现旧的 `datasets/step2/delivery/current/preflight_report.json` 不能给新的 `5099` 条 source 背书，随后已将它同步到本轮 latest 结果。

当前 `delivery/current/preflight_report.json` 现在对应的是：

- `preflight_20260527T083852Z`
- 状态：失败
- 失败点：`generator`
- 失败原因：`http_402 / Insufficient Balance`

因此，之后若再引用 Step2 preflight，必须写清：

- 报告路径
- 时间戳
- 对应 source 规模
- 是否包含真实 API ping

## 10. go / no-go 结论

本轮结论是：`no-go（当前不能直接开始 Step2 formal 生成）`。

原因不是本地代码或数据资产不合格，而是：

- 真实 formal preflight 在 `generator` 阶段失败
- 失败原因为远程接口 `http_402 / Insufficient Balance`

更细的拆分结论如下：

- `本地数据与协议层准备度`：基本通过
- `few-shot formal-ready`：通过
- `source/few-shot 泄漏边界`：通过
- `Step3 冻结评测边界`：待补风险
- `真实 formal 可运行性`：未通过

## 11. 后续动作

按最短路径推进，下一步应做：

1. 补足当前接口账户余额，重新执行：

```bash
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

2. 若通过，再决定是否启动正式 Step2 构造实验。

3. 在启动正式实验前，如需论文级封口，再补：
   - 冻结 Step3 eval/test 资产
   - 再做 Step2 source / few-shot / Step3 的 repo / sha 泄漏审计
