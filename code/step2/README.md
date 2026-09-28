# Step2

Step2 负责把单意图 source commits 组合成 synthetic multi-intent commits，并输出供后续阶段使用的数据。

## 当前默认输入

Step2 当前默认 source 不再来自临时 dropzone，而是来自 Step1 正式交付层：

- `../../datasets/derived/step1_source_pool/current/conservative_atomic_sources.csv`
- `../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1.csv`
- `../../datasets/derived/step2_bridge/current/step2_source_candidates_from_step1_manifest.json`

其中，`step2_source_candidates_from_step1.csv` 由桥接脚本生成，是 Step2 实际读取的输入格式。

## 当前默认 few-shot 资产

Step2 当前默认使用仓库内正式 few-shot 交付物：

- `../../datasets/step2/delivery/current/fewshot_pool.db`
- `../../datasets/step2/delivery/current/build_manifest.json`

当前真实状态：

- `selected_count = 130`
- `audit_pass = true`
- `retrieval_probe_ok = true`
- 默认配置已显式指向这份资产

`examples/synthetic_index_harder.csv` 只保留为兼容 fallback，不再是默认 formal 入口。

补充：

- 上面这些事实说明当前 few-shot 资产本身已通过审计
- 当前 few-shot 资产通过，不等于新的 source `current` 已经完成最新 formal preflight
- 如后续更换 source、few-shot 资产或配置，再重新运行 `make step2-preflight`

## 主入口

- Step1 -> Step2 桥接：`python3 tools/export_step1_to_step2_source.py`
- Step2 主流程：`python3 code/construct_simple_two_intent.py`
- Step2 few-shot 资产构建：`python3 code/build_formal_fewshot_pool.py`

顶层快捷入口：

```bash
make step2-bridge
make step2-preflight
make step2-mock
make step2-fullscale-plan
make step2-fullscale-run
make step2-fewshot-prepare
make step2-fewshot-report
make step2-fewshot-materialize
```

补充（以下代理说明仅针对历史 macOS/Makefile 运行环境；Windows 命令见 `../../docs/WINDOWS_SETUP_AND_VALIDATION.md`）：

- Step2 真实 API 路径依赖 Python 进程能够访问 DeepSeek。
- 历史 macOS 机器上，`curl` 可通过系统代理访问外网，但 Python 默认不一定自动继承系统代理。
- 顶层 `make step2-preflight`、`make step2-mock`、`make step2-fullscale-plan`、`make step2-fullscale-run` 现在会先读取系统代理并注入 `HTTP_PROXY/HTTPS_PROXY`，同时设置 `MPLCONFIGDIR=/private/tmp/step2_mplconfig`。
- 如果你绕过 Makefile 直接运行 `python3 ...`，需要自己显式带上代理环境变量，否则可能出现 `request_error` / `gaierror(8)`。

## 诊断与正式比较

当前 Step2 默认正式基线是：

- `selection_quality_priority = legacy_guarded`
- 不启用 `feat_fix_repair` 实验开关
- 不启用 `final_strong_path_tail_compress` 实验开关

当前口径约束：

- `target_count=20` 的小批次只用于快速诊断，不再作为正式比较主结论
- 正式比较应迁到更大样本量，当前建议至少 `target_count=100`
- 大样本比较优先做：
  - 原始 `legacy_guarded` 多种子重复运行
  - 固定样本下的阈值方法离线比较

`target_gate` 口径：

- 执行层：严格交付门
- 报告层：`step3_ready_count / target_count` 才是连续产率指标

不要混淆：

- `message_gate_failed` = 质量/协议失败
- `message_gate_passed && target_gate_failed` = 质量链路成立，但 one-shot 交付数量不足
- `target_gate_passed` = 既满足质量链路，也满足当前交付规模要求

推荐命令：

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

## 推荐运行路径

1. 桥接 Step1 正式 source

```bash
make step2-bridge
```

2. 先跑 formal preflight

```bash
make step2-preflight
# 如需把真实接口连通性也纳入 formal 预检：
make step2-preflight STEP2_PREFLIGHT_ARGS="--preflight-api-ping"
```

建议先准备本地覆盖配置：

```bash
cp configs/step2_runtime_config.json configs/step2_runtime_config.local.json
```

然后在 `configs/step2_runtime_config.local.json` 中填写 `deepseek_api_key`。
顶层 `make step2-preflight` 在本地文件存在时会自动优先使用它。

3. 本地调试

```bash
make step2-mock
```

4. 真实 API 路径

```bash
cd code/step2
eval "$(python3 tools/emit_proxy_env.py)"
MPLCONFIGDIR=/private/tmp/step2_mplconfig \
python3 code/construct_simple_two_intent.py --config configs/step2_runtime_config.local.json
```

5. 全量分片路径

不要直接拿 `step2_runtime_config.json` 去硬跑全量。当前推荐单独使用全量配置和分片 runner：

```bash
make step2-fullscale-plan
```

上面只会产出：

- `outputs/.../plan/selected_pairs_primary.jsonl`
- `outputs/.../plan/selected_pairs_primary_manifest.json`
- `outputs/.../plan/uncovered_sources.csv`
- `outputs/.../plan/shards/shard_*.json`

确认 plan 后再执行：

```bash
make step2-fullscale-run
```

默认全量 runner 会：

- 基于当前严格成组约束先生成 primary pair plan
- 把 selected pairs 切成分片
- 每片单独调用 Step2 主流程
- 结果汇总到 `outputs/.../aggregate/fullscale_summary.json`
- 默认仍用 fullscale config 做选样，但分片生成阶段会优先复用本地 `step2_runtime_config.local.json` 里的 API / few-shot / scorer 设置

如需恢复中断后的运行：

```bash
make step2-fullscale-run STEP2_FULLSCALE_ARGS="--resume"
```

如需手动重跑 formal preflight 并刷新 `delivery/current/preflight_report.json`：

```bash
cd code/step2
eval "$(python3 tools/emit_proxy_env.py)"
MPLCONFIGDIR=/private/tmp/step2_mplconfig \
python3 code/construct_simple_two_intent.py \
  --preflight \
  --preflight-api-ping \
  --output-dir ../../datasets/step2/delivery/current \
  --config configs/step2_runtime_config.local.json
```

## few-shot 更新路径

```bash
cd code/step2
python3 code/build_formal_fewshot_pool.py prepare
python3 code/build_formal_fewshot_pool.py report
python3 code/build_formal_fewshot_pool.py materialize
```

## 输入兼容性

- 当前推荐优先使用 Step1 新格式 `conservative_atomic_sources.csv`
- 旧格式 `resolved_candidates.csv` 仍可兼容，但不再是推荐主路径

## 关键约束

- Step2 默认入口已经对齐到正式 few-shot 资产；不要再把 fallback few-shot 当作 formal 默认口径。
- few-shot 资产的 formal-ready 与整条 Step2 正式实验完成不是一回事；真实生成质量与跨 split 泄露审计仍需单独验证。
- few-shot 资产当前的 `audit_pass` / `retrieval_probe_ok` 与“仓库内已保留一份最新成功 preflight 报告”也不是一回事；引用 preflight 结论前要重跑。
- 顶层 `make step2-preflight` 当前默认会优先使用 `configs/step2_runtime_config.local.json`，不存在时才回退到 `configs/step2_runtime_config.json`；`configs/step2_from_step1_source_config.json` 只适合作为小规模 `api_smoke` / 调试配置。
- Step2 默认优先消费 `datasets/derived/` 下的正式桥接层，而不是 `code/step2/data/`。
- Step2 当前默认生成器是 `deepseek-v4-pro`，并显式设置 `generator_thinking_type=disabled`。这对应官方支持的 non-thinking 模式，不是临时 debug 绕过。
- 对 Step2 而言，结果可信性主要来自输出侧约束与验证：`coverage / faithfulness / format / gate / audit`。是否暴露长 `reasoning_content` 不是当前任务的主要可信性来源。
- 比较实验时不要混用 `thinking=enabled` 与 `thinking=disabled` 的结果并直接合并统计；两者应被视为不同生成配置。
- DeepSeek 官方文档参考：
  - `https://api-docs.deepseek.com/zh-cn/guides/thinking_mode`
  - `https://api-docs.deepseek.com/api/create-chat-completion`

## 推荐阅读

- `docs/plan-1-step2-experiment-protocol.md`
- `docs/formal-preflight-last-mile-checklist.md`
- `../../datasets/step2/README.md`
